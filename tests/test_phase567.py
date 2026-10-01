import asyncio
import json
import time

import httpx
import pytest

from vision.agents import Master
from vision.bus import EventBus, Store
from vision.config import Config, MasterConfig
from vision.masters import build_masters
from vision.orchestrator import Orchestrator
from vision.services import mailcal, oauth
from vision.services.llm import LLMUnavailable

NOW = time.time()


class FakeLLM:
    """Deterministic stand-in for LM Studio / cloud."""

    def __init__(self, chat_script=None):
        self.chat_script = list(chat_script or [])
        self.prompts = []

    async def complete(self, prompt, **kw):
        self.prompts.append(prompt)
        if "Judge this debate" in prompt:
            return "Underweight - momentum fading."
        if "multiplier" in prompt:
            return "0.8 balanced"
        return "Thanks for reaching out. Thursday afternoon works for me.\n\nBest,\nMani"

    async def json(self, prompt, **kw):
        return None  # agents fall back to rules

    async def chat(self, messages, **kw):
        if not self.chat_script:
            raise LLMUnavailable("none")
        return self.chat_script.pop(0)

    async def local_available(self):
        return True


def orch_with(tmp_path, masters_cfg, llm=None):
    cfg = Config(masters=masters_cfg)
    bus, store = EventBus(), Store(tmp_path / "t.db")
    o = Orchestrator(cfg, [m for m in build_masters(cfg) if m.id in masters_cfg], bus, store)
    if llm:
        o.llm = llm
        for m in o.masters:
            m.services["llm"] = llm
    return o


def mails():
    base = {"account": "p", "provider": "google", "to": "me@x.com", "labels": [], "unread": True, "message_id": "<m@x>", "thread": "t"}
    return [
        {**base, "id": "1", "from": "anna@client.com", "from_name": "Anna Lee", "subject": "Can we schedule a call next week?", "snippet": "Are you available for a meeting?", "ts": NOW - 3600},
        {**base, "id": "2", "from": "raj@co.com", "from_name": "Raj", "subject": "Please review the proposal", "snippet": "Could you review and confirm by Friday?", "ts": NOW - 7200},
        {**base, "id": "3", "from": "deals@shop.com", "from_name": "Shop", "subject": "50% off sale", "snippet": "unsubscribe here", "ts": NOW - 9000, "labels": ["CATEGORY_PROMOTIONS"]},
        {**base, "id": "4", "from": "alerts@jobbank.gc.ca", "from_name": "Job Bank", "subject": "New jobs matching your alert", "snippet": "job alert", "ts": NOW - 9500},
    ]


@pytest.fixture
def fake_mail(monkeypatch):
    sent, events = [], []

    async def list_recent(account, hours=24):
        return [dict(m) for m in mails()]

    async def get_body(account, msg_id, limit=6000):
        return "Hi Mani, " + ("https://www.jobbank.gc.ca/jobsearch/jobposting/12345" if msg_id == "4" else "could you take a look?")

    async def send(account, **kw):
        sent.append(kw)

    async def list_events(account, start, end, tz):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        d = datetime.now(ZoneInfo(tz)).replace(second=0, microsecond=0) + timedelta(minutes=5)   # always still ahead
        return [{"id": "e1", "account": "p", "provider": "google", "title": "Standup", "start": d.isoformat(), "end": (d + timedelta(minutes=30)).isoformat(), "all_day": False, "attendees": [], "location": ""},
                {"id": "e2", "account": "p", "provider": "google", "title": "Overlap", "start": (d + timedelta(minutes=15)).isoformat(), "end": (d + timedelta(minutes=45)).isoformat(), "all_day": False, "attendees": [], "location": ""}]

    async def create_event(account, **kw):
        events.append(kw)
        return {"id": "new"}

    for n, f in (("list_recent", list_recent), ("get_body", get_body), ("send", send), ("list_events", list_events), ("create_event", create_event)):
        monkeypatch.setattr(mailcal, n, f)
    return sent, events


ACCTS = {"accounts": [{"id": "p", "provider": "google"}]}


def test_email_and_calendar_work_together(tmp_path, fake_mail):
    sent, events = fake_mail
    o = orch_with(tmp_path, {"email": MasterConfig(mode="live", options=ACCTS), "calendar": MasterConfig(mode="live", options=ACCTS)}, FakeLLM())
    asyncio.run(o.run_master("email"))
    rep = o.bus.state["reports"]["email"]
    assert rep.startswith("4 new · 2 need you")                     # meeting + action; promo and job alert don't
    replies = [a for a in o.store.pending_approvals() if a["payload"]["kind"] == "email_reply"]
    assert len(replies) == 2
    assert o.bus.state["report_data"]["email"]["attention"][0]["from"] in ("Anna Lee", "Raj")

    asyncio.run(o.run_master("calendar"))
    st = {a["name"]: a for a in o.bus.state["masters"]["calendar"]["agents"]}
    assert st["Conflict Checker"]["label"] == "1 CLASHES"
    meet = [a for a in o.store.pending_approvals() if a["payload"]["kind"] == "meeting_accept"]
    assert len(meet) == 1 and "Anna Lee" in meet[0]["title"]
    assert "request waiting" in o.bus.state["reports"]["calendar"]

    # you approve: the reply is sent as a reply in the thread; the meeting is booked and confirmed
    assert asyncio.run(o.execute_approval(replies[0]["id"], "approved")) is None   # nothing decided yet -> store still pending
    o.store.decide_approval(replies[0]["id"], "approved")
    assert asyncio.run(o.execute_approval(replies[0]["id"], "approved")).startswith("reply sent")
    assert sent[-1]["reply_to"]["id"] in ("1", "2")
    o.store.decide_approval(meet[0]["id"], "approved")
    assert asyncio.run(o.execute_approval(meet[0]["id"], "approved")).startswith("booked")
    assert events and events[0]["attendees"] == ["anna@client.com"]
    assert sent[-1]["subject"].startswith("Re: Can we schedule")


def test_email_sign_in_needed(tmp_path, monkeypatch):
    async def need(account, hours=24):
        raise oauth.AuthNeeded(account["id"], account["provider"])
    monkeypatch.setattr(mailcal, "list_recent", need)
    o = orch_with(tmp_path, {"email": MasterConfig(mode="live", options=ACCTS)})
    asyncio.run(o.run_master("email"))
    n = o.bus.state["notices"]["auth:p"]
    assert n["url"].endswith("/auth/google/login?account=p")
    assert o.bus.state["masters"]["email"]["agents"][0]["label"] == "SIGN IN"


def test_oauth_login_url_and_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setattr(oauth, "TOKENS", tmp_path / "tokens.json")
    url = oauth.login_url("google", "personal", 8765)
    assert "access_type=offline" in url and "gmail.readonly" in url and "127.0.0.1%3A8765%2Fauth%2Fgoogle%2Fcallback" in url
    oauth._save("personal", {"provider": "google", "access_token": "old", "refresh_token": "r", "expires_at": 0})
    t = lambda req: httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
    tok = asyncio.run(oauth.access_token("personal", "google", client=httpx.AsyncClient(transport=httpx.MockTransport(t))))
    assert tok == "fresh"


def test_ask_engine_tools_and_guard(tmp_path, monkeypatch):
    from vision.ask import AskEngine
    from vision.services import traffic_api

    async def route(o, d):
        return {"from": "Windsor", "to": "Leamington", "km": 54, "minutes": 49, "usual_minutes": 45, "delay_minutes": 4}
    monkeypatch.setattr(traffic_api, "route", route)
    script = [
        {"text": "", "tool_calls": [{"id": "c1", "name": "route_traffic", "args": {"origin": "Windsor", "destination": "Leamington"}}],
         "raw_assistant": {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "route_traffic", "args": {}}]}},
        {"text": "Morning, Mani. It's about 50 minutes to Leamington, a few minutes slower than usual.", "tool_calls": [], "raw_assistant": {}},
    ]
    o = orch_with(tmp_path, {}, FakeLLM(script))
    eng = AskEngine(o)
    out = asyncio.run(eng.ask("how's the traffic between windsor and leamington?"))
    assert out["steps"] == [["TRAFFIC DESK", "Traffic Poller", "route traffic", "49 min"]]
    assert out["say"].startswith("Morning, Mani.") and not out["fallback"]
    # approving by voice needs your explicit words
    a = o.store.add_approval("email", "Writer", "Reply to Anna", {"key": "k", "kind": "email_reply", "draft": "x"})
    res = asyncio.run(eng._run_tool("decide_approval", {"id": a["id"], "decision": "approved"}, "what's on today"))
    assert "error" in res and o.store.pending_approvals()
    res = asyncio.run(eng._run_tool("decide_approval", {"id": a["id"], "decision": "approved"}, "yes, send it"))
    assert res["ok"] and not o.store.pending_approvals()
    # no model at all -> the dashboard's built-in engine takes over
    assert asyncio.run(AskEngine(orch_with(tmp_path, {}, FakeLLM())).ask("hi"))["fallback"] is True


def test_voice_endpoints_fall_back(monkeypatch):
    import os
    from fastapi.testclient import TestClient
    from vision.server import create_app
    monkeypatch.setenv("VISION_HOME", os.getcwd())
    import vision.server as server
    real = server.load_config
    def browser_only():                       # whatever engines config.yaml turns on, this test is about the fallback
        cfg = real()
        cfg.voice = {**cfg.voice, "tts": "browser", "stt": "browser"}
        return cfg
    monkeypatch.setattr(server, "load_config", browser_only)
    with TestClient(create_app(boot_on_start=False, schedules=False, telegram_on=False, voice_on=False)) as c:
        assert c.post("/api/tts", json={"text": "hi"}).status_code == 503
        assert c.post("/api/stt", content=b"abc", headers={"content-type": "audio/webm"}).status_code == 503
        assert c.get("/api/state").json()["voice"] == {"tts": False, "stt": False, "wake": False}


# ---------------- Phase 7 ----------------

def candles(n=200, start=1.08, step=0.0004):
    out, p = [], start
    for i in range(n):
        p += step * (1 if i % 5 else -1)
        out.append({"complete": True, "mid": {"o": f"{p:.5f}", "h": f"{p + 0.0006:.5f}", "l": f"{p - 0.0006:.5f}", "c": f"{p:.5f}"}})
    return out


ORDERS = []


DELETED: list[str] = []   # Cloudflare Workers removed during a test


def router(req: httpx.Request) -> httpx.Response:
    h, path = req.url.host, req.url.path
    if h == "opensky-network.org":
        return httpx.Response(200, json={"states": [["a1", "ACA056 ", "Canada", 0, 0, -82.9, 42.2, 10000, False, 240, 90],
                                                    ["b2", "BAW92  ", "UK", 0, 0, -30.0, 50.0, 11000, False, 250, 270],
                                                    ["c3", "", "X", 0, 0, 10, 10, 0, True, 0, 0]]})
    if h == "api.adsbdb.com":
        cs = path.rsplit("/", 1)[-1]
        if cs == "ACA056":
            return httpx.Response(200, json={"response": {"flightroute": {"airline": {"name": "Air Canada"}, "origin": {"iata_code": "YYZ", "municipality": "Toronto"},
                                                                          "destination": {"iata_code": "DEL", "municipality": "Delhi", "latitude": 28.56, "longitude": 77.1}}}})
        return httpx.Response(200, json={"response": "unknown callsign"})
    if h == "api.adzuna.com":
        return httpx.Response(200, json={"results": [
            {"id": 1, "title": "Data Analyst", "company": {"display_name": "Acme"}, "location": {"display_name": "Windsor, Ontario"}, "redirect_url": "https://adzuna/1",
             "description": "Python SQL Power BI dashboards"},
            {"id": 2, "title": "Line Cook", "company": {"display_name": "Diner"}, "location": {"display_name": "Windsor"}, "redirect_url": "https://adzuna/2", "description": "cooking"}]})
    if h == "boards-api.greenhouse.io":
        return httpx.Response(200, json={"jobs": [{"id": 9, "title": "Senior Data Analytics Engineer", "location": {"name": "Toronto, ON"},
                                                   "absolute_url": "https://gh/9", "content": "<p>Python, SQL, Kubernetes, CI/CD</p>"}]})
    if h == "www.jobbank.gc.ca":
        return httpx.Response(200, text="<html><title>Data Analyst - Job Bank</title><body>Python SQL Leamington</body></html>")
    if h == "geocoding-api.open-meteo.com":
        return httpx.Response(200, json={"results": [{"name": "Leamington", "latitude": 42.05, "longitude": -82.6, "admin1": "Ontario", "country_code": "CA"}]})
    if h == "places.googleapis.com":
        if path.endswith(":searchNearby"):
            return httpx.Response(200, json={"places": [
                {"id": "p1", "displayName": {"text": "Jesse's Plumbing"}, "formattedAddress": "1 Main St, Leamington, ON N8H, Canada", "nationalPhoneNumber": "(519) 555-0100", "primaryType": "plumber", "rating": 4.8},
                {"id": "p2", "displayName": {"text": "Big Plumbing Co"}, "formattedAddress": "2 Main St", "websiteUri": "https://bigplumb.example", "primaryType": "plumber"}]})
        return httpx.Response(200, json={"regularOpeningHours": {"weekdayDescriptions": ["Monday: 8 AM–5 PM"]}, "reviews": [{"text": {"text": "Fast and fair"}}]})
    if h == "bigplumb.example":
        return httpx.Response(200, text="<html><body>24/7 emergency service, free quotes</body></html>")
    if h == "api.openverse.org":
        return httpx.Response(200, json={"results": [{"url": "https://img/1.jpg", "title": "Pipes", "creator": "A", "license": "by", "license_version": "4.0", "foreign_landing_url": "https://src/1"}]})
    if h == "api.cloudflare.com":
        if path.endswith("/workers/subdomain"):
            return httpx.Response(200, json={"result": {"subdomain": "mani"}})
        if req.method == "DELETE":
            DELETED.append(path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"success": True, "result": {}})
    if h == "api-fxpractice.oanda.com":
        if "/candles" in path:
            return httpx.Response(200, json={"candles": candles()})
        if path.endswith("/summary"):
            return httpx.Response(200, json={"account": {"NAV": "10000"}})
        if path.endswith("/openTrades"):
            return httpx.Response(200, json={"trades": []})
        if path.endswith("/pricing"):
            p = float(candles()[-1]["mid"]["c"])
            return httpx.Response(200, json={"prices": [{"bids": [{"price": f"{p - 0.00005:.5f}"}], "asks": [{"price": f"{p + 0.00005:.5f}"}]}]})
        if path.endswith("/orders"):
            ORDERS.append(json.loads(req.content))
            return httpx.Response(201, json={"orderFillTransaction": {"id": "77", "price": "1.1", "tradeOpened": {"tradeID": "78"}}})
    if h == "news.google.com":
        return httpx.Response(200, text="<?xml version='1.0'?><rss><channel><title>x</title></channel></rss>")
    return httpx.Response(404)


@pytest.fixture
def web_mock(monkeypatch):
    real = httpx.AsyncClient

    def factory(*a, **kw):
        return real(transport=httpx.MockTransport(router), **{k: v for k, v in kw.items() if k in ("headers", "follow_redirects")})
    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_world_watch_flights(tmp_path, web_mock):
    o = orch_with(tmp_path, {"world": MasterConfig(mode="live", options={"home": [42.05, -82.6], "max_flights": 10})})
    asyncio.run(o.run_master("world"))
    data = o.bus.state["report_data"]["world"]
    ac = next(f for f in data["flights"] if f["cs"] == "ACA056")
    assert ac["airline"] == "Air Canada" and ac["to"] == "DEL" and ac["eta_min"] > 600
    assert "near home" in o.bus.state["reports"]["world"]
    assert all(f["cs"] for f in data["flights"])          # grounded / blank callsigns dropped


def test_job_hunt_pipeline(tmp_path, web_mock, monkeypatch):
    import vision.masters.jobs as jobs
    monkeypatch.setenv("ADZUNA_APP_ID", "a")
    monkeypatch.setenv("ADZUNA_APP_KEY", "b")
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    opts = {"target_titles": ["Data Analyst", "Data Analytics Engineer"], "skills": ["Python", "SQL", "Power BI", "Kubernetes", "CI/CD"],
            "locations": ["Windsor, ON", "Toronto, ON"], "min_match": 70, "target_companies": [{"name": "Acme Cloud", "ats": "greenhouse", "slug": "acme"}]}
    o = orch_with(tmp_path, {"jobs": MasterConfig(mode="live", options=opts)}, FakeLLM())
    asyncio.run(o.run_master("jobs"))
    st = {a["name"]: a for a in o.bus.state["masters"]["jobs"]["agents"]}
    assert st["Job Scout"]["label"] == "2 MATCHES"                        # line cook filtered out
    assert st["Resume Tailor"]["label"] == "NEEDS RESUME"
    (tmp_path / "vault" / "resume").mkdir(parents=True)
    (tmp_path / "vault" / "resume" / "master.md").write_text("# Mani\n- Python, SQL")
    asyncio.run(o.run_master("jobs"))
    pk = [a for a in o.store.pending_approvals() if a["payload"]["kind"] == "job_package"]
    assert len(pk) == 2 and (tmp_path / "data" / "applications").exists()
    o.store.decide_approval(pk[0]["id"], "approved")
    assert "submit" in asyncio.run(o.execute_approval(pk[0]["id"], "approved"))
    assert any(k.startswith("apply:") for k in o.bus.state["notices"])


def test_web_designer_pipeline(tmp_path, web_mock, monkeypatch):
    import vision.masters.web as web
    for k in ("GOOGLE_MAPS_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setattr(web, "ROOT", tmp_path)
    o = orch_with(tmp_path, {"web": MasterConfig(mode="live", options={"business_types": ["plumber"], "price": "CAD 500"})})
    asyncio.run(o.run_master("web"))
    lead = o.store.kv_get("leads", "p1")
    assert lead["url"] == "https://demo-jesse-s-plumbing.mani.workers.dev"
    page = (tmp_path / "data" / "sites" / "jesse-s-plumbing" / "index.html").read_text()
    assert "Jesse&#x27;s Plumbing" in page and "tel:5195550100" in page and "Pipes by A (BY 4.0)" in page
    assert not o.store.kv_has("leads", "p2")                              # has a website: competitor, not a lead
    pitch = [a for a in o.store.pending_approvals() if a["payload"]["kind"] == "proposal"][0]
    assert "CAD 500" in pitch["payload"]["message"] and "pitch waiting" in o.bus.state["reports"]["web"]
    DELETED.clear()                                                       # rejecting the pitch takes the demo offline
    o.store.decide_approval(pitch["id"], "rejected")
    assert "demo site removed" in asyncio.run(o.execute_approval(pitch["id"], "rejected"))
    assert DELETED == ["demo-jesse-s-plumbing"] and "url" not in o.store.kv_get("leads", "p1")


def test_trading_desk_rules_and_guards(tmp_path, web_mock, monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "t")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "001")
    monkeypatch.setenv("OANDA_ENV", "practice")
    o = orch_with(tmp_path, {"trading": MasterConfig(mode="live", options={"instruments": ["EUR_USD"], "max_units": 1000, "min_units": 50})}, FakeLLM())
    asyncio.run(o.run_master("trading"))
    tr = [a for a in o.store.pending_approvals() if a["payload"]["kind"] == "trade"]
    assert len(tr) == 1 and tr[0]["payload"]["units"] < 0 and "Underweight" in tr[0]["title"]   # judge said Underweight -> sell
    assert "waiting for you" in o.bus.state["reports"]["trading"]
    import vision.masters.trading as trading
    ctx = {"cfg": o.cfg, "store": o.store, "bus": o.bus}
    row = o.store.get_approval(tr[0]["id"])
    old = {**row, "payload": {**row["payload"], "created": time.time() - 3600}}
    assert asyncio.run(trading.approve_trade(old, "approved", ctx)).startswith("refused: approval expired")
    monkeypatch.setenv("OANDA_ENV", "live")
    assert asyncio.run(trading.approve_trade(row, "approved", ctx)).startswith("refused: live trading is off")
    monkeypatch.setenv("OANDA_ENV", "practice")
    assert asyncio.run(trading.approve_trade(row, "approved", ctx)).startswith("filled")
    assert ORDERS[-1]["order"]["type"] == "MARKET" and "stopLossOnFill" in ORDERS[-1]["order"]


def test_kokoro_voices_are_listed_and_switchable(monkeypatch):
    from vision import voice

    class FakeKokoro:
        used = []
        def get_voices(self):
            return ["af_heart", "am_adam", "bf_emma", "bm_george", "jf_alpha", "zf_xiaobei"]
        def create(self, text, voice, speed, lang):
            FakeKokoro.used.append((voice, lang))
            return [0.0, 0.1], 24000

    t = voice.TTS({"tts": "kokoro", "kokoro_voice": "bf_emma"})
    monkeypatch.setattr(t, "available", lambda: True)
    monkeypatch.setattr(t, "_load_kokoro", lambda: FakeKokoro())
    monkeypatch.setattr(voice, "_wav", lambda samples, sr: b"wav")
    v = t.voices()
    assert [x["id"] for x in v["voices"]] == ["bf_emma", "bm_george", "af_heart", "am_adam"]      # English only, UK first
    assert v["current"] == "bf_emma" and v["voices"][0] == {"id": "bf_emma", "name": "Emma", "accent": "UK", "gender": "F"}
    asyncio.run(t.synth("hi", "am_adam"))            # a listed voice is used, with its own accent
    asyncio.run(t.synth("hi", "jf_alpha"))           # anything else falls back to the configured voice
    asyncio.run(t.synth("hi"))
    assert FakeKokoro.used == [("am_adam", "en-us"), ("bf_emma", "en-gb"), ("bf_emma", "en-gb")]
    assert voice.TTS({"tts": "browser"}).voices()["voices"] == []


def test_color_theme_from_colorhunt():
    from vision.masters.web import _contrast, pick_theme
    rgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    for t in ("plumber", "beauty_salon", "hair_care", "car_repair", "unknown_type"):
        for i in range(25):
            th = pick_theme({"id": f"lead-{i}", "type": t})
            assert th.get("palette"), "palettes.json should be found"
            assert _contrast(rgb(th["text"]), rgb(th["bg"])) >= 7
            assert _contrast(rgb(th["primary"]), rgb(th["bg"])) >= 4.5
            assert _contrast(rgb(th["accent"]), rgb(th["text"])) >= 4.5
    assert pick_theme({"id": "a", "type": "cafe"}) == pick_theme({"id": "a", "type": "cafe"})
    assert pick_theme({"id": "a", "type": "cafe"}, ["neon"]) != pick_theme({"id": "a", "type": "cafe"})
