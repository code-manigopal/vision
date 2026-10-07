"""Visa Watch: read-only guard, encryption, comparison, alert de-duplication, sign-in by the person, pausing. The portal is faked."""

import asyncio
import time

import httpx
import pytest
from cryptography.fernet import Fernet

from vision.bus import EventBus, Store
from vision.config import Config, MasterConfig
from vision.masters import build_masters, visa
from vision.orchestrator import Orchestrator
from vision.services import keyvault, visa_portal as vp

SESSION = {"cookies": [{"name": "s", "value": "tok-abc123"}]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setattr(keyvault, "_key", lambda: key)
    monkeypatch.setattr(visa, "session_file", lambda acc_id: tmp_path / "visa" / f"{acc_id}.session")
    cfg = Config(masters={"visa": MasterConfig(mode="live")})
    bus, store = EventBus(), Store(tmp_path / "t.db")
    orch = Orchestrator(cfg, [m for m in build_masters(cfg) if m.id == "visa"], bus, store)
    calls = []

    def portal(answer):
        async def fake(**kw):
            calls.append(kw)
            if not kw.get("state"):
                raise vp.NeedsSignIn("no saved sign-in yet")
            if isinstance(answer, Exception):
                raise answer
            return {"dates": answer, "schedule": "555", "facilities": {c: "94" for c in kw["cities"]}, "state": kw["state"]}
        monkeypatch.setitem(visa.PORTALS, "canada", fake)

    signs = []

    async def person_signs_in(**kw):
        signs.append(kw)
        return SESSION
    monkeypatch.setitem(visa.SIGNERS, "canada", person_signs_in)

    def add(name="Mani", cities=("Toronto",), booked="2027-04-22", signed_in=True):
        acc = visa.add_account(store, name, f"{name.lower()}@example.com", list(cities), booked)
        return asyncio.run(visa.sign_in(store, acc)) if signed_in else acc

    def run(due=True):
        if due:
            store.kv_delete(visa.STATE, "run")
            for a in visa.accounts(store):
                if a["status"] == "active":
                    a["next_due"] = 0
                    visa.save(store, a)
        return asyncio.run(orch.run_master("visa"))

    return type("W", (), {"bus": bus, "store": store, "portal": staticmethod(portal), "run": staticmethod(run), "add": staticmethod(add),
                          "calls": calls, "signs": signs, "tmp": tmp_path})


def test_read_only_guard():
    assert vp.allowed("GET", "https://ais.usvisa-info.com/en-ca/niv/schedule/1/appointment/days/94.json")
    assert vp.allowed("POST", "https://ais.usvisa-info.com/en-ca/niv/users/sign_in")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert not vp.allowed(method, "https://ais.usvisa-info.com/en-ca/niv/schedule/1/appointment")
    assert not vp.allowed("POST", "https://evil.example/en-ca/niv/users/sign_in")     # the one POST is the portal's own sign-in
    assert not vp.allowed("PUT", "https://ais.usvisa-info.com/en-ca/niv/users/sign_in")

    async def send(method, url):
        async with httpx.AsyncClient(event_hooks={"request": [vp._only_get]}, transport=httpx.MockTransport(lambda r: httpx.Response(200, text="[]"))) as c:
            return await c.request(method, url)
    assert asyncio.run(send("GET", "https://ais.usvisa-info.com/en-ca/niv/schedule/1/appointment/days/94.json")).status_code == 200
    for method, url in (("POST", "https://ais.usvisa-info.com/en-ca/niv/schedule/1/appointment"), ("GET", "https://evil.example/x")):
        with pytest.raises(vp.ReadOnlyViolation):                   # the look can only GET, and only from the portal
            asyncio.run(send(method, url))


def test_the_look_is_one_get_per_city_with_the_saved_session():
    seen = []

    def portal(answer, status=200, headers=None):
        def handler(request):
            seen.append(request)
            return httpx.Response(status, text=answer, headers=headers or {})
        return httpx.MockTransport(handler)
    state = {"cookies": [{"name": "_yatri_session", "value": "abc", "domain": "ais.usvisa-info.com", "path": "/"}], "ua": "Chrome-as-signed-in", "schedule": "555"}
    days = '[{"date":"2027-02-01","business_day":true},{"date":"2027-01-14","business_day":true}]'
    res = asyncio.run(vp.check_canada(cities=["Toronto", "Ottawa"], state=state, transport=portal(days, headers={"set-cookie": "_yatri_session=renewed; path=/"})))
    assert res["dates"] == {"Toronto": ["2027-01-14", "2027-02-01"], "Ottawa": ["2027-01-14", "2027-02-01"]} and res["schedule"] == "555"
    assert [r.method for r in seen] == ["GET", "GET"]
    assert [r.url.path for r in seen] == ["/en-ca/niv/schedule/555/appointment/days/94.json", "/en-ca/niv/schedule/555/appointment/days/92.json"]
    assert seen[0].headers["x-requested-with"] == "XMLHttpRequest" and seen[0].headers["user-agent"] == "Chrome-as-signed-in"
    assert "_yatri_session=abc" in seen[0].headers["cookie"]
    assert {c["name"]: c["value"] for c in res["state"]["cookies"]}["_yatri_session"] == "renewed"     # a renewed cookie is kept for next time
    for kw in ({"state": None}, {"state": {"cookies": []}}, {"state": {**state, "schedule": None}}):
        with pytest.raises(vp.NeedsSignIn):
            asyncio.run(vp.check_canada(cities=["Toronto"], transport=portal(days), **kw))
    for answer, status, error in (("", 302, vp.NeedsSignIn), ('<html><form action="/en-ca/niv/users/sign_in">', 200, vp.NeedsSignIn), ("", 401, vp.NeedsSignIn),
                                  ("<html>Please complete the CAPTCHA</html>", 200, vp.Challenge), ("<html>oops</html>", 500, vp.PortalError),
                                  ("<html>maintenance</html>", 200, vp.PortalError)):
        with pytest.raises(error) as e:
            asyncio.run(vp.check_canada(cities=["Toronto"], state=state, transport=portal(answer, status)))
        assert type(e.value) is error
    with pytest.raises(vp.PortalError):
        asyncio.run(vp.check_canada(cities=["Windsor"], state=state, transport=portal(days)))


def test_days_and_cities():
    assert vp.parse_days('[{"date":"2027-02-01","business_day":true},{"date":"2027-01-14","business_day":true}]') == ["2027-01-14", "2027-02-01"]
    assert vp.parse_days("[]") == []
    for bad in ("<html>Sign in</html>", '{"error":"x"}', '[{"day":"x"}]'):
        with pytest.raises(vp.PortalError):
            vp.parse_days(bad)
    assert vp.match_facilities(["toronto", "Quebec City", "Lagos"], {"Lagos": "7"}) == {"toronto": "94", "Quebec City": "93", "Lagos": "7"}
    with pytest.raises(vp.PortalError):
        vp.match_facilities(["Windsor"])
    assert vp.redact("login mani.k@gmail.com with hunter2 failed", "hunter2") == "login ***@gmail.com with *** failed"


def test_by_hand_vision_never_signs_in_and_keeps_only_an_encrypted_session(world):
    acc = world.add(signed_in=False)
    assert acc["status"] == "signin" and "password" not in acc
    world.portal({"Toronto": ["2027-01-14"]})
    assert "needs sign-in" in world.run() and not world.calls                 # no session: the portal is not even opened
    assert "Sign in" in world.bus.state["notices"]["visa:signin:mani"]["text"]
    acc = asyncio.run(visa.sign_in(world.store, visa.accounts(world.store)[0]))      # the person signs in
    assert acc["status"] == "active"
    f = world.tmp / "visa" / "mani.session"
    assert f.exists() and b"tok-abc123" not in f.read_bytes()                  # the saved session is encrypted
    assert "EARLIER SLOT" in world.run() and "visa:signin:mani" not in world.bus.state["notices"]
    assert set(world.calls[0]) == {"cities", "state", "schedule", "facilities"}      # no email, no password goes to the portal code
    assert world.calls[0]["state"] == SESSION
    world.run()
    assert world.signs == [{}]                                                # by hand: the sign-in window got no email and no password

    world.portal(vp.NeedsSignIn("the saved sign-in has run out"))             # the session ends: wait for the person, don't count a failure
    assert "needs sign-in" in world.run()
    acc = visa.accounts(world.store)[0]
    assert acc["status"] == "signin" and acc["fails"] == 0 and len(world.calls) == 3
    world.run()
    assert len(world.calls) == 3                                              # and it is left alone until they do

    async def gave_up(**kw):
        raise vp.PortalError("nobody signed in within 5 minutes")
    visa.SIGNERS["canada"] = gave_up
    acc = asyncio.run(visa.sign_in(world.store, visa.accounts(world.store)[0]))
    assert acc["status"] == "signin" and "nobody signed in" in acc["error"]


def test_automatic_sign_in_once_per_expired_session(world, monkeypatch):
    PW = "s3cret-Pa55"
    acc = visa.add_account(world.store, "Mani", "mani@example.com", ["Toronto"], "2027-04-22", password=PW)
    assert acc["status"] == "active" and PW.encode() not in (world.tmp / "t.db").read_bytes()
    assert visa.public(acc)["auto"] is True and "password" not in visa.public(acc)
    world.portal({"Toronto": ["2027-01-14"]})
    assert "EARLIER SLOT" in world.run()                                       # no session -> one sign-in -> the look
    assert len(world.signs) == 1 and world.signs[0]["email"] == "mani@example.com" and world.signs[0]["password"]() == PW
    assert len(world.calls) == 2 and PW not in str(world.bus.state)
    world.run()
    assert len(world.signs) == 1 and len(world.calls) == 3                     # the session is reused: no second sign-in

    for error, word in ((vp.Locked("the portal says: account is locked until 12:14"), "locked"), (vp.SignInRefused("the portal did not accept the saved email and password"), "did not accept"),
                        (vp.Challenge("the portal showed a CAPTCHA at sign-in"), "CAPTCHA")):
        async def refused(error=error, **kw):
            world.signs.append(kw)
            raise error
        monkeypatch.setitem(visa.SIGNERS, "canada", refused)
        acc = visa.accounts(world.store)[0]
        visa.session_file(acc["id"]).unlink(missing_ok=True)                   # the session has run out
        visa.set_status(world.store, acc, "active")
        before = len(world.signs)
        assert "paused" in world.run()
        acc = visa.accounts(world.store)[0]
        assert acc["status"] == "paused" and word in acc["error"] and len(world.signs) == before + 1      # one attempt, then it stops
        world.run()
        assert len(world.signs) == before + 1

    acc = visa.accounts(world.store)[0]                                        # the daily cap: past it, wait for a sign-in by hand
    acc["sign_ins"] = [time.time()] * visa.MAX_SIGN_INS
    visa.set_status(world.store, acc, "active")
    before = len(world.signs)
    assert "needs sign-in" in world.run() and len(world.signs) == before
    acc = visa.update_account(world.store, visa.accounts(world.store)[0], forget=True)
    assert "password" not in visa.accounts(world.store)[0] and visa.public(acc)["auto"] is False
    assert vp.LOCKED_WORDS.search("Your account is locked until 07 October, 2026, 12:14:22 CST.").group(0) == "account is locked until 07 October, 2026, 12:14:22 CST"


def test_alert_only_for_strictly_earlier_and_once(world):
    world.add(cities=("Toronto", "Ottawa"))
    world.portal({"Toronto": ["2027-04-22", "2027-05-01"], "Ottawa": []})
    assert "nothing earlier" in world.run()
    assert not world.bus.state["notices"]                             # the same day is not earlier

    world.portal({"Toronto": ["2027-01-14", "2027-05-01"], "Ottawa": ["2027-06-01"]})
    events = world.bus.subscribe()
    report = world.run()
    assert "EARLIER SLOT Toronto 2027-01-14" in report and "Ottawa" not in report
    n = world.bus.state["notices"]["visa:slot:mani"]
    assert "Toronto: 2027-01-14" in n["text"] and "booked: 2027-04-22" in n["text"] and n["url"] == vp.SIGN_IN

    def notices():
        out = 0
        while not events.empty():
            out += events.get_nowait().get("type") == "notice"
        return out
    assert notices() == 1
    world.bus.state["notices"].clear()                                # as after a restart
    world.run()
    assert notices() == 0                                             # same city and date: not announced again within 24 h
    world.portal({"Toronto": ["2027-01-10"], "Ottawa": []})
    world.run()
    assert notices() == 1 and "2027-01-10" in world.bus.state["notices"]["visa:slot:mani"]["text"]
    world.portal({"Toronto": [], "Ottawa": []})
    assert "portal lists no dates" in world.run()                     # an empty list is said as such, not as "nothing earlier"
    assert "visa:slot:mani" not in world.bus.state["notices"]         # gone from the portal, gone from the dashboard
    world.run()
    assert "(3 looks in a row)" in world.run() and visa.accounts(world.store)[0]["empties"] == 3


def test_accepted_range_and_skipped_dates(world):
    assert visa.parse_skip("2027-03-10, 2027-04-01..2027-04-07; 2027-02-01 to 2027-02-03") == [["2027-02-01", "2027-02-03"], ["2027-03-10", "2027-03-10"], ["2027-04-01", "2027-04-07"]]
    assert visa.parse_skip("") == [] and visa.parse_skip(None) == []
    for bad in ("soon", "2027-04-07..2027-04-01", "2027-01-01..2027-01-02..2027-01-03"):
        with pytest.raises(ValueError):
            visa.parse_skip(bad)
    acc = visa.add_account(world.store, "Mani", "mani@example.com", ["Toronto", "Ottawa"], "2027-04-22", not_before="2027-01-10", skip="2027-01-14, 2027-02-01..2027-02-10")
    asyncio.run(visa.sign_in(world.store, acc))
    # Toronto: the 5th is too early, the 14th is skipped, so the search goes on to the 20th. Ottawa: only skipped or too-late dates.
    world.portal({"Toronto": ["2027-01-05", "2027-01-14", "2027-01-20", "2027-03-01"], "Ottawa": ["2027-02-05", "2027-04-22", "2027-06-01"]})
    report = world.run()
    assert "EARLIER SLOT Toronto 2027-01-20" in report and "Ottawa" not in report
    assert "Toronto: 2027-01-20" in world.bus.state["notices"]["visa:slot:mani"]["text"]
    a = visa.accounts(world.store)[0]
    assert visa.public(a)["slots"] == [["Toronto", "2027-01-20"]]
    visa.update_account(world.store, a, skip="", not_before="")                 # editable: lift both and the earliest date counts again
    assert visa.earlier(visa.accounts(world.store)[0]) == [("Toronto", "2027-01-05"), ("Ottawa", "2027-02-05")]
    visa.update_account(world.store, a, cities=["Toronto"])                     # leaving them out of an edit keeps them
    assert visa.accounts(world.store)[0]["skip"] == [] and "slots" not in world.store.kv_get(visa.NS, "mani")


def test_challenge_pauses_at_once_and_failures_pause_after_three(world):
    world.add()
    world.portal(vp.Challenge("the portal showed a CAPTCHA"))
    assert "paused" in world.run()
    assert visa.accounts(world.store)[0]["status"] == "paused" and len(world.calls) == 1      # one try, no retry
    assert "CAPTCHA" in world.bus.state["notices"]["visa:paused:mani"]["text"]
    world.run()
    assert len(world.calls) == 1                                      # a paused account is left alone

    visa.set_status(world.store, visa.accounts(world.store)[0], "active")
    world.portal(RuntimeError("timeout for mani@example.com"))
    for n in (1, 2):
        world.run()
        acc = visa.accounts(world.store)[0]
        assert acc["status"] == "active" and acc["fails"] == n and "mani@" not in acc["error"]
        assert "visa:paused:mani" not in world.bus.state["notices"]
    world.run()
    assert visa.accounts(world.store)[0]["status"] == "paused" and len(world.calls) == 4


def test_hourly_with_gap_between_accounts(world):
    for name in ("Mani", "Priya"):
        world.add(name)
    world.portal({"Toronto": []})
    world.run()
    assert len(world.calls) == 1                                      # one account per run
    world.run(due=False)
    assert len(world.calls) == 1                                      # the second waits out the 5-minute gap
    gapless = visa.build_agents({"test_mode": True})["Canada Checker"]                # test mode: no gap
    ctx = {"store": world.store, "bus": world.bus}
    assert asyncio.run(gapless.run(ctx)).label == "CHECKED" and len(world.calls) == 2
    world.calls.pop()
    b = next(a for a in visa.accounts(world.store) if a["id"] == ctx["visa_checked"])
    b["next_due"] = 0
    visa.save(world.store, b)
    world.store.kv_put(visa.STATE, "run", {"started": time.time() - visa.GAP - 1})
    world.run(due=False)
    assert len(world.calls) == 2 and world.calls[0]["cities"] == ["Toronto"]
    world.store.kv_delete(visa.STATE, "run")
    world.run(due=False)
    assert len(world.calls) == 2                                      # both looked at; nothing is due for about an hour
    nxt = [a["next_due"] - time.time() for a in visa.accounts(world.store)]
    assert all(49 * 60 < n <= 70 * 60 for n in nxt)
    assert visa.in_quiet(["01:00", "05:00"], time.mktime((2026, 10, 7, 3, 0, 0, 0, 0, -1)))
    assert not visa.in_quiet(["01:00", "05:00"], time.mktime((2026, 10, 7, 9, 0, 0, 0, 0, -1))) and not visa.in_quiet([], time.time())


def test_remove_deletes_everything(world):
    acc = world.add()
    world.portal({"Toronto": ["2027-01-14"]})
    world.run()
    assert world.store.kv_list(visa.ALERTS) and visa.session_file(acc["id"]).exists()
    visa.remove_account(world.store, acc["id"])
    assert not visa.accounts(world.store) and not world.store.kv_list(visa.ALERTS) and not visa.session_file(acc["id"]).exists()
    with pytest.raises(ValueError):
        visa.add_account(world.store, "Mani", "m@example.com", ["Hyderabad"], "2027-04-22", portal="india")    # parked


def test_dashboard_account_api(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("VISION_HOME", os.getcwd())
    key = Fernet.generate_key()
    monkeypatch.setattr(keyvault, "_key", lambda: key)
    monkeypatch.setattr(visa, "session_file", lambda acc_id: tmp_path / f"{acc_id}.session")

    async def person_signs_in(**kw):
        return SESSION
    monkeypatch.setitem(visa.SIGNERS, "canada", person_signs_in)
    from fastapi.testclient import TestClient
    from vision.server import create_app
    app = create_app(boot_on_start=False, schedules=False, telegram_on=False, voice_on=False)
    with TestClient(app) as c:
        app.state.store = app.state.orch.store = Store(tmp_path / "t.db")       # never the real database
        app.state.orch.asleep = True                                             # and no portal look from this test
        new = {"name": "Priya", "email": "priya@example.com", "cities": "Toronto, Ottawa", "booked": "2027-04-22"}
        assert c.post("/api/visa/accounts", json={**new, "cities": ""}).status_code == 400
        assert c.post("/api/visa/accounts", json={**new, "booked": "22 April"}).status_code == 400
        assert c.post("/api/visa/accounts", json=new, headers={"Origin": "https://evil.example"}).status_code == 403
        r = c.post("/api/visa/accounts", json=new)
        a = r.json()["accounts"][0]
        assert r.status_code == 200 and a["id"] == "priya" and a["cities"] == ["Toronto", "Ottawa"] and a["status"] == "signin" and a["auto"] is False
        r = c.post("/api/visa/accounts/priya", json={"cities": "Toronto", "booked": "2027-03-01", "password": "pw-Zx91"})
        a = r.json()["accounts"][0]
        assert a["cities"] == ["Toronto"] and a["booked"] == "2027-03-01" and a["auto"] is True and a["status"] == "active"
        assert "password" not in r.text and "pw-Zx91" not in r.text and b"pw-Zx91" not in (tmp_path / "t.db").read_bytes()
        assert c.post("/api/visa/accounts/priya", json={"action": "forget"}).json()["accounts"][0]["auto"] is False
        a = c.post("/api/visa/accounts/priya", json={"not_before": "2027-01-10", "skip": "2027-02-01..2027-02-10"}).json()["accounts"][0]
        assert a["not_before"] == "2027-01-10" and a["skip"] == [["2027-02-01", "2027-02-10"]] and a["slots"] == []
        assert c.post("/api/visa/accounts/priya", json={"skip": "next week"}).status_code == 400
        c.post("/api/visa/accounts/priya", json={"action": "signin"})
        for _ in range(50):
            a = c.get("/api/visa/accounts").json()["accounts"][0]
            if a["status"] == "active":
                break
            time.sleep(0.05)
        assert a["status"] == "active" and (tmp_path / "priya.session").exists()
        assert c.post("/api/visa/accounts/priya", json={"action": "pause"}).json()["accounts"][0]["status"] == "paused"
        assert c.post("/api/visa/accounts/priya", json={"action": "resume"}).json()["accounts"][0]["status"] == "active"
        assert c.post("/api/visa/accounts/nobody", json={"action": "pause"}).status_code == 404
        assert c.delete("/api/visa/accounts/priya").json() == {"accounts": []}
