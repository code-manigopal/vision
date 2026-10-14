import asyncio
import os

import httpx
import pytest

from vision.agents import AgentResult, Master, Stage, StubAgent, SubAgent
from vision.bus import EventBus, Store
from vision.config import Config, MasterConfig
from vision.masters import CATALOG, build_masters
from vision.orchestrator import Orchestrator


class Boom(SubAgent):
    name = "Boom"

    async def run(self, ctx):
        raise RuntimeError("upstream API down")


class Echo(SubAgent):
    name = "Echo"

    async def run(self, ctx):
        seen = sorted(ctx["results"])
        return AgentResult("done", "OK", f"saw {seen}")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.db")


def test_catalog_matches_dashboard():
    assert len(CATALOG["order"]) == 10         # Traffic Desk merged into World Watch; the E-books Manager took its slot
    for mid, spec in CATALOG["masters"].items():
        names = [a["name"] for a in spec["agents"]]
        staged = [n for s in spec["stages"] for n in s["agents"]]
        assert sorted(names) == sorted(staged), mid          # every agent sits in exactly one stage
        assert spec["reporter"] in names, mid                  # one reporter, and it is a real sub-agent


def test_only_reporter_summary_reaches_vision(store):
    bus = EventBus()
    m = Master("x", "X", [Stage("A", [StubAgent(name="A1", status="done", label="OK", summary="not me")]),
                          Stage("B", [Echo()])], reporter="Echo")
    report = asyncio.run(m.cycle(bus, store))
    assert report == "saw ['A1']"                              # work was passed down the chain
    assert bus.state["reports"]["x"] == report


def test_error_alerts_master_and_blocks_chain(store):
    bus = EventBus()
    m = Master("x", "X", [Stage("A", [Boom()]), Stage("B", [Echo()])], reporter="Echo")
    report = asyncio.run(m.cycle(bus, store))
    agents = {a["name"]: a for a in bus.state["masters"]["x"]["agents"]}
    assert agents["Boom"]["status"] == "error"
    assert agents["Echo"]["label"] == "BLOCKED"
    assert report == "Blocked: Boom failed"
    assert any("upstream API down" in e["msg"] for e in bus.log)   # error went straight to the master log


def test_reporter_must_exist():
    with pytest.raises(ValueError):
        Master("x", "X", [Stage("A", [Echo()])], reporter="Nobody")


class Down(SubAgent):
    name = "Weather Agent"

    async def run(self, ctx):
        raise RuntimeError("Open-Meteo down")


def test_boot_rolls_call_for_every_agent(store, monkeypatch):
    from vision.masters import world
    monkeypatch.setattr(world, "build_agents", lambda options, cfg=None: {"Weather Agent": Down()})
    cfg = Config(masters={"world": MasterConfig(mode="live"), "youtube": MasterConfig(enabled=False)})
    bus = EventBus()
    orch = Orchestrator(cfg, build_masters(cfg), bus, store)
    orch.seed_state()
    asyncio.run(orch.boot())
    total = sum(len(s["agents"]) for s in CATALOG["masters"].values())
    assert bus.state["boot"] == {"active": False, "done": total, "total": total}
    assert set(bus.state["reports"]) == set(CATALOG["order"]) - {"youtube"}
    # a live agent that fails and blocks -> the rest are blocked, VISION is told
    assert bus.state["reports"]["world"].startswith("Blocked")
    assert "brief" not in bus.state
    assert "World Watch" in orch.compose_brief().title()


def test_traffic_master_live(store, monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "x")
    from vision.services import traffic_api as tt

    def handler(req):
        if "/search/2/geocode/" in req.url.path:
            return httpx.Response(200, json={"results": [{"position": {"lat": 42.3, "lon": -83.0},
                "address": {"municipality": "Windsor", "countrySubdivision": "Ontario"},
                "boundingBox": {"topLeftPoint": {"lat": 42.35, "lon": -83.1}, "btmRightPoint": {"lat": 42.25, "lon": -82.9}}}]})
        return httpx.Response(200, json={"incidents": [
            {"properties": {"iconCategory": 6, "magnitudeOfDelay": 3, "delay": 900, "roadNumbers": ["EC Row"]}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(tt.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    from vision.masters import world
    a = world.build_agents({"watch_cities": ["Windsor"]})
    m = Master("world", "WORLD WATCH", [Stage("GATHER", [a["City Geocoder"]]), Stage("ROADS", [a["Traffic Poller"]]),
               Stage("INCIDENTS", [a["Incident Scout"]]), Stage("CURATE", [a["News Summarizer"]])], "News Summarizer")
    bus = EventBus()
    report = asyncio.run(m.cycle(bus, store))
    assert report == "No fresh headlines · Windsor 1 incidents, major delay 15 min on EC Row"
    assert bus.state["reports"]["world"] == report


def test_traffic_without_key_never_blocks_world_watch(store, monkeypatch):
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    from vision.masters import world
    a = world.build_agents({"watch_cities": ["Windsor"]})
    m = Master("world", "WORLD WATCH", [Stage("GATHER", [a["City Geocoder"]]), Stage("ROADS", [a["Traffic Poller"]]),
               Stage("INCIDENTS", [a["Incident Scout"]]), Stage("CURATE", [a["News Summarizer"]])], "News Summarizer")
    assert asyncio.run(m.cycle(EventBus(), store)) == "No fresh headlines"


def test_server_ws_and_api(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_HOME", os.getcwd())
    from fastapi.testclient import TestClient
    from vision.server import create_app
    app = create_app(boot_on_start=False, schedules=False, telegram_on=False, voice_on=False)
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        assert "x-dc" in c.get("/dashboard/Main.dc.html").text
        st = c.get("/api/state").json()
        assert len(st["masters"]) == 10
        with c.websocket_connect("/ws") as ws:
            snap = ws.receive_json()
            assert snap["type"] == "snapshot"
            c.post("/api/masters/world/run")
            kinds = {ws.receive_json()["type"] for _ in range(6)}
            assert "agent" in kinds


def _standby_app(monkeypatch, schedules):
    monkeypatch.setenv("VISION_HOME", os.getcwd())
    from vision.server import create_app
    return create_app(boot_on_start=False, schedules=schedules, telegram_on=False, voice_on=False)


@pytest.mark.parametrize("schedules", [False, True])
def test_standby_and_wake(monkeypatch, schedules):
    from apscheduler.schedulers.base import STATE_PAUSED, STATE_RUNNING
    from fastapi.testclient import TestClient
    with TestClient(_standby_app(monkeypatch, schedules)) as c:
        sched = c.app.state.orch.scheduler
        assert c.get("/api/state").json()["power"] == {"on": True}
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
            assert c.post("/api/shutdown").json() == {"ok": True}
            assert c.post("/api/shutdown").json() == {"ok": True}      # idempotent
            seen = [ws.receive_json() for _ in range(2)]
            assert seen[0] == {"type": "power", "on": False}
            assert "standby" in seen[1]["msg"]
            assert c.get("/api/state").json()["power"] == {"on": False}
            if schedules:
                assert sched.state == STATE_PAUSED
            r = c.post("/api/masters/world/run")
            assert r.status_code == 409 and r.json()["detail"] == "VISION is in standby"
            assert c.post("/api/approvals/1/approved").status_code == 409
            assert c.post("/api/boot").json() == {"ok": True}
            assert ws.receive_json() == {"type": "power", "on": True}
            assert c.get("/api/state").json()["power"] == {"on": True}
            if schedules:
                assert sched.state == STATE_RUNNING
            assert c.post("/api/masters/world/run").status_code == 200


def test_standby_cancels_running_cycle(store):
    class Slow(SubAgent):
        name = "Slow"

        async def run(self, ctx):
            await asyncio.sleep(60)

    async def go():
        bus = EventBus()
        orch = Orchestrator(Config(), [Master("x", "X", [Stage("A", [Slow()])], reporter="Slow")], bus, store)
        orch.seed_state()
        run = asyncio.create_task(orch.run_master("x"))
        await asyncio.sleep(0.05)
        assert bus.state["masters"]["x"]["agents"][0]["status"] == "work"
        await orch.standby()
        assert run.cancelled() and not orch._runs
        assert bus.state["masters"]["x"]["agents"][0]["label"] == "STANDBY"
        assert await orch.run_master("x") == "VISION is in standby"
        orch.wake()
        assert bus.state["power"] == {"on": True}

    asyncio.run(go())


# ---- Instruments (vision/services/sysmon.py) ----

def _sysmon(monkeypatch, system, machine, outputs):
    """outputs: {command name: stdout}; a missing command behaves as not installed."""
    from types import SimpleNamespace
    from vision.services import sysmon
    monkeypatch.setattr(sysmon.platform, "system", lambda: system)
    monkeypatch.setattr(sysmon.platform, "machine", lambda: machine)
    monkeypatch.setattr(sysmon.shutil, "which", lambda name: name if name in outputs else None)
    monkeypatch.setattr(sysmon, "_run", lambda cmd: outputs.get(cmd[0], ""))
    monkeypatch.setattr(sysmon.psutil, "cpu_percent", lambda interval=None: 12.4)
    monkeypatch.setattr(sysmon.psutil, "virtual_memory",
                        lambda: SimpleNamespace(total=16 * sysmon.GB, available=4 * sysmon.GB, percent=75.0))
    return {g["id"]: g for g in sysmon.SysMon().sample()}


def test_sysmon_apple_silicon(monkeypatch):
    g = _sysmon(monkeypatch, "Darwin", "arm64", {"ioreg": '"PerformanceStatistics" = {"Tiler Utilization %"=3,"Device Utilization %"=41}'})
    assert list(g) == ["cpu", "mem", "gpu"]          # unified memory: no separate VRAM gauge
    assert g["cpu"]["pct"] == 12 and g["gpu"]["pct"] == 41
    assert g["mem"]["label"] == "UNIFIED MEMORY" and g["mem"]["pct"] == 75 and g["mem"]["detail"] == "12.0 / 16.0 GB"


def test_sysmon_nvidia(monkeypatch):
    g = _sysmon(monkeypatch, "Linux", "x86_64", {"nvidia-smi": "37, 4096, 16384\n"})
    assert list(g) == ["cpu", "mem", "gpu", "vram"]
    assert g["mem"]["label"] == "RAM" and g["gpu"]["pct"] == 37
    assert g["vram"]["pct"] == 25 and g["vram"]["detail"] == "4.0 / 16.0 GB"


def test_sysmon_no_gpu(monkeypatch):
    assert list(_sysmon(monkeypatch, "Linux", "x86_64", {})) == ["cpu", "mem"]


def test_system_event_lands_in_snapshot():
    bus = EventBus()
    bus.publish({"type": "system", "gauges": [{"id": "cpu", "label": "CPU", "pct": 5, "hot": 80, "detail": ""}]})
    assert bus.snapshot()["state"]["system"][0]["id"] == "cpu"


def test_pending_approvals_survive_a_restart(tmp_path):
    """An approval still waiting when VISION restarts must show up again on the dashboard."""
    store = Store(tmp_path / "t.db")
    waiting = store.add_approval("web", "Proposal Drafter", "Pitch · demo https://demo-x.workers.dev", {"key": "pitch:1", "kind": "proposal"})
    done = store.add_approval("web", "Proposal Drafter", "Old pitch", {"key": "pitch:0", "kind": "proposal"})
    store.decide_approval(done["id"], "rejected")
    cfg = Config(masters={"web": MasterConfig(mode="stub")})
    orch = Orchestrator(cfg, [m for m in build_masters(cfg) if m.id == "web"], EventBus(), store)
    orch.seed_state()
    assert [a["id"] for a in orch.bus.snapshot()["state"]["approvals"]] == [waiting["id"]]


def test_notice_can_be_closed_for_a_day():
    from vision.bus import EventBus
    bus = EventBus()
    bus.notice("wealthsimple", "CSV is 11 days old")
    assert bus.dismiss_notice("wealthsimple") and "wealthsimple" not in bus.state["notices"]
    bus.notice("wealthsimple", "CSV is 11 days old")                  # the agent raises it again on its next run: stays closed
    assert "wealthsimple" not in bus.state["notices"]
    bus.notice("wealthsimple", "CSV is 12 days old")                  # something new to say: shows
    assert bus.state["notices"]["wealthsimple"]["text"] == "CSV is 12 days old"
    assert bus.dismiss_notice("wealthsimple") and not bus.dismiss_notice("nothing-here")
    bus.clear_notice("wealthsimple")                                  # settled; when it comes up again it shows
    bus.notice("wealthsimple", "CSV is 12 days old")
    assert "wealthsimple" in bus.state["notices"]
    bus._closed["kite"] = ("Log in", 0.0)                             # closed more than a day ago
    bus.notice("kite", "Log in")
    assert "kite" in bus.state["notices"]


def test_api_schedule(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from fastapi.testclient import TestClient
    from vision.server import create_app
    monkeypatch.setenv("VISION_HOME", os.getcwd())
    app = create_app(boot_on_start=False, schedules=False, telegram_on=False, voice_on=False)
    with TestClient(app) as c:
        orch = app.state.orch
        orch.cfg.masters["youtube"].run_at = ["05:00 | Confessions Shorts | confessions", "07:02 Asia/Kolkata | Pre-market Short | manimarket"]
        orch.cfg.masters["world"].run_at = ["12:00"]
        mac = ZoneInfo(orch.cfg.vision.timezone)
        now = datetime(2026, 10, 14, 0, 30, tzinfo=mac)
        items = orch.schedule(now=now)
        by = {(i["master"], i["label"]): i for i in items}
        assert by[("youtube", "Confessions Shorts")]["local"] == "05:00"
        pre = by[("youtube", "Pre-market Short")]                         # 07:02 IST is 21:32 EDT
        assert pre["local"] == "21:32" and pre["kind"] == "run" and pre["channel"] == "manimarket" and pre["zone_local"] == "07:02 IST"
        assert by[("youtube", "Confessions Shorts")]["channel"] == "confessions" and "zone_local" not in by[("youtube", "Confessions Shorts")]
        assert by[("world", orch.by_id["world"].name)]["local"] == "12:00"   # no label: the master's name
        briefs = [i for i in items if i["kind"] == "brief"]
        assert [(b["local"], b["label"]) for b in briefs] == [("06:00", "Morning brief (Telegram)"), ("18:00", "Evening brief (Telegram)")]
        assert all(i["kind"] in ("run", "brief") for i in items) and [i["at"] for i in items] == sorted(i["at"] for i in items)
        assert all(0 < i["at"] - now.timestamp() <= 86400 for i in items)   # interval cycles and reminders are not here
        live = c.get("/api/schedule").json()
        assert live["standby"] is False and live["items"]
        c.post("/api/shutdown")
        assert c.get("/api/schedule").json() == {"standby": True, "items": []}
