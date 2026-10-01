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
    assert len(CATALOG["order"]) == 10
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


def test_boot_rolls_call_for_every_agent(store, monkeypatch):
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    cfg = Config(masters={"traffic": MasterConfig(mode="live", options={"watch_cities": ["Leamington"]}),
                          "film": MasterConfig(enabled=False)})
    bus = EventBus()
    orch = Orchestrator(cfg, build_masters(cfg), bus, store)
    orch.seed_state()
    asyncio.run(orch.boot())
    total = sum(len(s["agents"]) for s in CATALOG["masters"].values())
    assert bus.state["boot"] == {"active": False, "done": total, "total": total}
    assert set(bus.state["reports"]) == set(CATALOG["order"]) - {"film"}
    # traffic is live with no key -> geocoder errors, the rest are blocked, VISION is told
    assert bus.state["reports"]["traffic"].startswith("Blocked")
    assert "brief" not in bus.state
    assert "Traffic Desk" in orch.compose_brief().title()


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
    cfg = Config(masters={"traffic": MasterConfig(mode="live", options={"watch_cities": ["Windsor"]})})
    traffic = next(m for m in build_masters(cfg) if m.id == "traffic")
    report = asyncio.run(traffic.cycle(EventBus(), store))
    assert report == "Windsor 1 incidents, major delay 15 min on EC Row"


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
            c.post("/api/masters/news/run")
            kinds = {ws.receive_json()["type"] for _ in range(6)}
            assert "agent" in kinds
