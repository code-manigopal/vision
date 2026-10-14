"""Mani Market Tamil: the crew end to end (NSE and YouTube mocked, a stand-in voice and slide pictures; ffmpeg real), the approval, the LM Studio swap."""

import asyncio
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from PIL import Image
from test_market import FILES, FUND_FILES, fund_listing, listing
from test_market_backing import GOOD_MARGIN, GOOD_REV, DOC, feed, pdf

from vision.agents import AgentResult, Director, Master, Stage, SubAgent
from vision.bus import EventBus, Store
from vision.config import Config
from vision.masters import CATALOG, market_crew, slides, youtube
from vision.services import lmstudio, nse, oauth

FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
IST = ZoneInfo("Asia/Kolkata")
RAW = {"id": "manimarket", "name": "Mani Market Tamil", "director": "Mani Market Tamil Director", "crew": "market", "privacy": "approval", "timezone": "Asia/Kolkata",
       "voice_engine": "clone", "free_memory": True, "make_after": "23:00", "make_before": "04:00", "index_csv": "https://nsearchives.test/index.csv",
       "category": "27", "long": {"publish_time": "10:00", "playlist": ""}}
CSV = "Company Name,Industry,Symbol,Series,ISIN Code\nSample Limited,Things,SAMPLE,EQ,INE000A01010\nOther Ltd,Stuff,OTHER,EQ,INE000A01011\n"


def filed_now(rows):
    stamp = time.strftime("%d-%b-%Y %H:%M:%S")
    return [{**r, "broadcast_Date": stamp} for r in rows]


def web(yt):
    def handler(req):
        u = str(req.url)
        if "nsearchives.test/index.csv" in u:
            return httpx.Response(200, text=CSV)
        if "integrated-filing-results" in u:
            if yt.get("analysis") and "symbol" in req.url.params:
                return httpx.Response(200, json=fund_listing())
            rows = filed_now(listing()["data"])
            if "symbol" not in req.url.params:      # market-wide: the SAMPLE results, one company outside the index, and one with an old quarter
                rows = [r for r in rows if r["qe_Date"] == "30-SEP-2026"][:1] + [{**rows[0], "symbol": "STRANGER", "qe_Date": "30-SEP-2026"}]
            return httpx.Response(200, json={"data": rows})
        if yt.get("backing"):                       # the company's press release, and the news around the result
            if "corporate-announcements" in u:
                return httpx.Response(200, json=[{"an_dt": time.strftime("%d-%b-%Y %H:%M:%S"), "desc": "Press Release", "attchmntText": "a press release dated today",
                                                  "attchmntFile": "https://nsearchives.test/pr.pdf", "attFileSize": "300 KB"}])
            if u.endswith("/pr.pdf"):
                return httpx.Response(200, content=pdf(re.findall(r"[^.]+\.", DOC)))
            if "news.google.com" in u:
                now = time.time()
                return httpx.Response(200, text=feed(("Sample Q2 results: profit rises as cloud demand holds", "The Mint", now - 600), ("Sample shares jump after Q2 results", "ET", now - 700),
                                                     ("Sample Q2 results: wage costs weigh on margin", "Hindu", now - 800)))
        if u.startswith("https://nsearchives.test/"):
            return httpx.Response(200, text={**FILES, **FUND_FILES}[u.rsplit("/", 1)[-1]])
        if "corporate-share-holdings-master" in u:
            return httpx.Response(200, json=[{"date": "30-SEP-2026", "pr_and_prgrp": "55.5", "public_val": "44.5"}])
        if "corporates-corporateActions" in u:
            return httpx.Response(200, json=[{"exDate": (datetime.now() - timedelta(days=100)).strftime("%d-%b-%Y"), "subject": "Dividend - Rs 6 Per Share"}])
        if "finance/chart/SAMPLE.NS" in u:
            return httpx.Response(200, json=chart())
        if yt.get("logo") and "commons.wikimedia.org" in u:                # the company's logo from Wikimedia Commons (mocked)
            if req.url.params.get("list") == "search":
                return httpx.Response(200, json={"query": {"search": [{"title": "File:Sample old logo.svg"}, {"title": "File:Sample Logo.svg"}]}})
            return httpx.Response(200, json={"query": {"pages": {"1": {"title": "File:Sample Logo.svg", "imageinfo": [{
                "url": "https://upload.wikimedia.org/x/Sample_Logo.svg", "descriptionurl": "https://commons.wikimedia.org/wiki/File:Sample_Logo.svg", "mime": "image/svg+xml",
                "size": 120, "extmetadata": {"LicenseShortName": {"value": "Public domain"}, "Artist": {"value": "<a>Someone</a>"}}}]}}}})
        if u.startswith("https://upload.wikimedia.org/"):
            return httpx.Response(200, content=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>')
        if "thumbnails/set" in u:
            yt["thumb_set"] = (req.url.params["videoId"], len(req.content))
            return httpx.Response(200, json={})
        if "upload/youtube/v3/videos" in u:
            yt["meta"] = json.loads(req.content)
            return httpx.Response(200, headers={"Location": "https://upload.test/session1"})
        if u.startswith("https://upload.test/"):
            return httpx.Response(200, json={"id": "vid1"})
        if "youtube/v3/videos" in u and req.method == "PUT":
            yt["update"] = json.loads(req.content)
            return httpx.Response(200, json={"id": "vid1"})
        if "youtube/v3/videos" in u:
            return httpx.Response(200, json={"items": yt.get("items", [])})
        return httpx.Response(404)
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def chart(days=700):
    """Daily closes for two years up to yesterday; the last 30 days are 9999, a price the video must never show. (The close of exactly 31 days
    ago is allowed by the rule, so it is an ordinary price here: marking it 9999 made the test fail at some hours of the day.)"""
    now = int(time.time())
    stamps = [now - 86400 * n for n in range(days, 0, -1)]
    return {"chart": {"result": [{"meta": {"gmtoffset": 19800}, "timestamp": stamps,
                                  "indicators": {"quote": [{"close": [9999.0 if n <= 30 else 200.0 + n % 50 for n in range(days, 0, -1)]}]}}]}}


async def tone(text, stem):
    out = stem.with_suffix(".src.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=220:d={max(0.6, len(text.split()) / 4):.2f}", str(out)], check=True)
    return out, None


SEEN = []
THUMBS = []


def thumbnailer(work, out, hook, name, logo, channel, label, tone):
    """Stands in for the Chrome drawing of the cover: records what it was asked to draw and writes a small JPEG."""
    THUMBS.append({"hook": hook, "name": name, "logo": logo, "channel": channel, "label": label, "tone": tone})
    work.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1280, 720), (250, 248, 241)).save(out, "JPEG")
    return out


def pictures(deck, lines, work, **frame):
    SEEN.append(deck)
    work.mkdir(parents=True, exist_ok=True)
    out = []
    for n, _ in enumerate(lines):
        out.append(work / f"s{n:03d}.png")
        Image.new("RGB", (1920, 1080), (20 + n, 30, 60)).save(out[-1])
    return out, None


class NoWriter:
    def writer_available(self):
        return False


class Writer:
    """A stand-in for the writer model: gives the reasons and headline sentences it is told to, and nothing for any other request (so the lines stay plain)."""
    def writer_available(self):
        return True

    async def json(self, prompt, **kw):
        if "WHY a company's numbers moved" in prompt:
            return {"reasons": [GOOD_REV, {**GOOD_MARGIN, "direction": "up"}]}              # the margin reason contradicts our figure: it must not reach the video
        if "news headlines about a company" in prompt:
            return {"gists": {"1": "ஸாம்பிள் ரிசல்ட் பத்தி ஒரு செய்தி வந்திருக்கு.", "2": "ஸாம்பிள் மார்ஜின் பத்தி இன்னொரு செய்தி வந்திருக்கு."}}
        return {}


ANALYSIS = {d: "analysis" for d in market_crew.DAYS}


@pytest.fixture
def env(tmp_path, monkeypatch):
    return build_env(tmp_path, monkeypatch, RAW)


@pytest.fixture
def env_analysis(tmp_path, monkeypatch):
    return build_env(tmp_path, monkeypatch, {**RAW, "pattern": ANALYSIS, "price_lag_days": 31}, analysis=True)


def build_env(tmp_path, monkeypatch, raw, analysis=False):
    monkeypatch.setattr(youtube, "ROOT", tmp_path)
    monkeypatch.setattr(oauth, "TOKENS", tmp_path / "tokens.json")
    monkeypatch.setattr(market_crew, "now_hm", lambda: "23:30")
    monkeypatch.setattr(market_crew, "now_ist", lambda: datetime(2026, 10, 10, 12, 0, tzinfo=IST))      # a Saturday noon in India: no report Short is due, whatever the real clock says
    signed = {"ok": True}

    async def token(account, provider, client=None):
        if not signed["ok"]:
            raise oauth.AuthNeeded(account, provider)
        return "tok"
    monkeypatch.setattr(oauth, "access_token", token)
    yt = {"analysis": analysis}
    ch = youtube.channel(raw)
    d = Director(ch["director"], market_crew.crew(ch, client_factory=web(yt), synth=tone, pictures=pictures, thumbnailer=thumbnailer, logo_root=tmp_path / "logos"), reporter="Market Analytics")
    m = Master("youtube", "YOUTUBE MANAGER", [Stage("CHANNELS", [d])], reporter=ch["director"], mode="live")
    cfg = Config(masters={"youtube": {"mode": "live", "options": {"channels": [raw]}}})
    m.services.update(llm=NoWriter(), cfg=cfg)
    return {"m": m, "yt": yt, "ch": ch, "cfg": cfg, "bus": EventBus(), "store": Store(tmp_path / "t.db"), "signed": signed, "tmp": tmp_path}


def ctx_for(env):
    return {"bus": env["bus"], "store": env["store"], "cfg": env["cfg"], "llm": NoWriter(), "master": "youtube", "client_factory": web(env["yt"])}


def made(env):
    report = asyncio.run(env["m"].cycle(env["bus"], env["store"]))
    return report, [v for v in env["store"].kv_list(youtube.LOG)]


@FFMPEG
def test_a_night_makes_one_video_uploads_it_private_and_asks_for_approval(env):
    env["yt"]["logo"] = True
    THUMBS.clear()
    report, log = made(env)
    crew = {a["name"]: a for a in env["bus"].state["masters"]["youtube"]["agents"]}
    assert [crew[n]["status"] for n in ("Results Scout", "Market Analyst", "Tanglish Writer", "Voice Clone", "Slide Editor", "Market Uploader")] == ["done"] * 6, crew
    rec, = log
    assert rec["status"] == "awaiting" and rec["kind"] == "result" and rec["format"] == "long" and (rec["symbol"], rec["quarter"]) == ("SAMPLE", "Q2 FY27")
    assert rec["title"].startswith("Sample Q2 FY27 Results | Profit ") and rec["title"].endswith("| தமிழில்") and len(rec["title"]) <= 100 and rec["video_id"] == "vid1" and rec["publish_at"] is None
    credit = "Logo: https://commons.wikimedia.org/wiki/File:Sample_Logo.svg (Public domain)"                 # the logo's page is a source, the disclaimer stays last
    assert rec["summary"].endswith(f"Source: NSE filing ({rec['source']['url']})\n{credit}\n{market_crew.DISCLAIMER}") and rec["source"]["url"].endswith("now.xml")
    thumb, = THUMBS                                                       # the cover: the hook from the figures, the company, the cached Commons logo; set on the video after the upload
    assert rec["thumb"].endswith("thumb.jpg") and Path(rec["thumb"]).exists() and thumb["hook"].startswith("Profit ") and thumb["name"] == "Sample" and thumb["label"] == "Q2 FY27 RESULTS"
    assert thumb["logo"].endswith("SAMPLE.svg") and Path(thumb["logo"]).exists() and rec["logo"] == {"source": "https://commons.wikimedia.org/wiki/File:Sample_Logo.svg", "licence": "Public domain", "artist": "Someone"}
    assert env["yt"]["thumb_set"][0] == "vid1" and env["yt"]["thumb_set"][1] > 0
    assert rec["script"].startswith("வணக்கம்") or "investment recommendation" in rec["script"]
    status = env["yt"]["meta"]["status"]
    assert status["privacyStatus"] == "private" and "publishAt" not in status and env["yt"]["meta"]["snippet"]["categoryId"] == "27"
    assert env["yt"]["meta"]["snippet"]["description"] == rec["summary"] and "#SAMPLE" in rec["summary"]
    ap, = env["store"].pending_approvals()
    assert ap["payload"]["kind"] == "yt_publish" and ap["payload"]["key"] == "yt_publish:vid1" and ap["title"].startswith("Publish: Sample Q2 FY27")
    assert ap["payload"]["watch"] == "https://youtu.be/vid1" and ap["payload"]["video"] == "result" and ap["payload"]["new_words"] == {} and ap["payload"]["sources"] == [] and ap["payload"]["seconds"] == rec["seconds"]
    assert "Mani Market Tamil: 1 awaiting your approval" in report and env["store"].kv_has(market_crew.DONE, "SAMPLE:Q2 FY27")
    assert sorted(p.name for p in (env["tmp"] / "data" / "shorts" / "manimarket").glob("*/*")) == ["final.mp4", "thumb.jpg"]
    assert not env["bus"].state["notices"]
    again, log = made(env)                                   # the same company is not filmed twice; the awaiting video is left alone
    assert len(log) == 1 and log[0]["status"] == "awaiting" and "1 awaiting your approval" in again


@FFMPEG
def test_approving_schedules_the_release_for_10_ist_and_rejecting_keeps_it_private(env):
    made(env)
    ap, = env["store"].pending_approvals()
    env["store"].decide_approval(ap["id"], "approved")
    said = asyncio.run(youtube.publish_decision(env["store"].get_approval(ap["id"]), "approved", ctx_for(env)))
    upd = env["yt"]["update"]
    due = datetime.strptime(upd["status"]["publishAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC")).astimezone(IST)
    soon = datetime.now(IST) + timedelta(minutes=30)
    assert (due.hour, due.minute) == (10, 0) and soon < due <= soon + timedelta(days=1)
    assert upd["id"] == "vid1" and upd["status"]["privacyStatus"] == "private" and upd["status"]["selfDeclaredMadeForKids"] is False
    rec = env["store"].kv_list(youtube.LOG)[0]
    assert rec["status"] == "scheduled" and abs(rec["publish_at"] - due.timestamp()) < 1 and said.startswith("Scheduled for ") and "10:00" in said

    env["store"].kv_put(youtube.LOG, "other", {**{k: v for k, v in rec.items() if not k.startswith("_")}, "status": "awaiting", "publish_at": None, "video_id": "vid2"})
    row = {"payload": {"kind": "yt_publish", "channel": "manimarket", "record": "other", "video_id": "vid2"}}
    said = asyncio.run(youtube.publish_decision(row, "rejected", ctx_for(env)))
    other = env["store"].kv_get(youtube.LOG, "other")
    assert other["status"] == "private" and other["rejected"] is True and "does not delete" in said


@FFMPEG
def test_an_approval_decided_while_signed_out_is_scheduled_by_the_uploader_later(env):
    made(env)
    ap, = env["store"].pending_approvals()
    env["signed"]["ok"] = False
    said = asyncio.run(youtube.publish_decision(env["store"].get_approval(ap["id"]), "approved", ctx_for(env)))
    rec = env["store"].kv_list(youtube.LOG)[0]
    assert "not signed in" in said and rec["status"] == "awaiting" and rec["approved"] is True and "auth:youtube-manimarket" in env["bus"].state["notices"]
    env["signed"]["ok"] = True
    env["yt"]["items"] = [{"id": "vid1", "status": {"privacyStatus": "private"}, "statistics": {}}]
    made(env)
    assert env["store"].kv_list(youtube.LOG)[0]["status"] == "scheduled" and "update" in env["yt"]


def scout_ctx(env, **extra):
    return {"store": env["store"], "bus": env["bus"], "reason": "schedule", **extra}


def test_the_scout_idles_outside_the_making_window_unless_a_person_asks(env, monkeypatch):
    scout = market_crew.ResultsScout(env["ch"], client_factory=web(env["yt"]))
    monkeypatch.setattr(market_crew, "now_hm", lambda: "12:00")
    ctx = scout_ctx(env)
    res = asyncio.run(scout.run(ctx))
    assert res.label == "NOT YET" and "job" not in ctx
    ctx = scout_ctx(env, reason="manual")
    res = asyncio.run(scout.run(ctx))
    assert res.label == "FOUND" and ctx["job"]["key"] == "SAMPLE:Q2 FY27" and ctx["job"]["dir"].endswith("2026-09-30-SAMPLE-Q2FY27")
    assert [market_crew.in_window("23:00", "04:00", t) for t in ("22:59", "23:00", "03:59", "04:00")] == [False, True, True, False]


def test_a_company_already_filmed_is_not_filmed_again_and_nothing_new_lets_the_rest_idle(env):
    env["store"].kv_put(market_crew.DONE, "SAMPLE:Q2 FY27", {"at": 1})
    scout = market_crew.ResultsScout(env["ch"], client_factory=web(env["yt"]))
    ctx = scout_ctx(env)
    res = asyncio.run(scout.run(ctx))
    assert (res.status, res.label) == ("done", "NOTHING NEW") and "job" not in ctx          # STRANGER is not in the index
    for later in (market_crew.MarketAnalyst, market_crew.TanglishWriter, market_crew.VoiceClone, market_crew.SlideEditor):
        assert asyncio.run(later(env["ch"]).run(ctx)).label == "IDLE"


def test_no_new_video_while_two_wait(env):
    for n in range(2):
        env["store"].kv_put(youtube.LOG, f"x{n}", {"channel": "manimarket", "status": "awaiting", "made": 1})
    res = asyncio.run(market_crew.ResultsScout(env["ch"], client_factory=web(env["yt"])).run(scout_ctx(env)))
    assert res.label == "BACKLOG"


class Lms:
    """A stand-in for the lms program: records what it was told and answers `ps --json`."""

    def __init__(self, models):
        self.calls, self.models = [], models

    def __call__(self, args):
        self.calls.append(args)
        out = json.dumps(self.models) if args[0] == "ps" else ""
        return subprocess.CompletedProcess(args, 0, out, "")


def test_lm_studio_models_are_put_back_even_when_the_work_fails():
    lms = Lms([{"identifier": "qwen/qwen3-vl-8b", "modelKey": "qwen/qwen3-vl-8b", "contextLength": 8192, "ttlMs": 3600000}])

    async def work():
        async with lmstudio.freed(lms):
            assert ["unload", "--all"] in lms.calls and not any(c[0] == "load" for c in lms.calls)
            raise ValueError("the voice broke")
    with pytest.raises(ValueError):
        asyncio.run(work())
    load = next(c for c in lms.calls if c[0] == "load")
    assert load[:2] == ["load", "qwen/qwen3-vl-8b"] and ["--identifier", "qwen/qwen3-vl-8b"] == load[2:4] and "-c" in load and "8192" in load and "3600" in load
    assert lmstudio.loaded(lms) == ["qwen/qwen3-vl-8b"]


def test_lm_studio_swap_does_nothing_without_the_program_or_a_loaded_model():
    empty = Lms([])

    async def work(run):
        async with lmstudio.freed(run) as held:
            return held
    assert asyncio.run(work(empty)) == [] and empty.calls == [["ps", "--json"]]

    def missing(args):
        raise FileNotFoundError("lms")
    assert asyncio.run(work(missing)) == [] and lmstudio.loaded(missing) == []


def test_catalog_matches_the_market_crew_and_the_master_reports_both_channels(env):
    spec = next(a for a in CATALOG["masters"]["youtube"]["agents"] if a["name"] == "Mani Market Tamil Director")
    agents = youtube.build_agents({"channels": [{}, RAW]}, Config())
    d = agents["Mani Market Tamil Director"]
    assert [a.name for a in d.members] == [c["name"] for c in spec["crew"]] and d.reporter == spec["crew_reporter"] == "Market Analytics"
    assert [[s.title, [a.name for a in s.agents]] for s in d.crew] == spec["crew_stages"]
    assert "Mani Market Tamil Director" in CATALOG["masters"]["youtube"]["stages"][0]["agents"]
    lead = agents["Confessions Everywhere Director"]
    assert isinstance(lead, youtube.Lead) and not isinstance(d, youtube.Lead)

    class Say(SubAgent):
        async def run(self, ctx):
            return AgentResult(summary="Confessions Everywhere: 2 public")
    env["store"].kv_put(youtube.LOG, "a", {"channel": "manimarket", "status": "awaiting"})
    env["store"].kv_put(youtube.LOG, "b", {"channel": "manimarket", "status": "scheduled"})
    small = youtube.Lead("Lead", [Stage("X", [Say(name="Say")])], reporter="Say", peers=[env["ch"]])
    res = asyncio.run(small.run({"store": env["store"], "bus": env["bus"], "master": "youtube"}))
    assert res.summary == "Confessions Everywhere: 2 public | Mani Market Tamil: 1 awaiting your approval, 1 scheduled"


def test_a_channel_with_a_timezone_gets_that_zones_slots_and_one_without_keeps_the_old_ones(tmp_path):
    store = Store(tmp_path / "s.db")
    now = datetime(2026, 10, 13, 12, 0, tzinfo=IST).timestamp()
    due = youtube.next_slot(store, youtube.channel(RAW), now=now, fmt="long")
    assert datetime.fromtimestamp(due, IST) == datetime(2026, 10, 14, 10, 0, tzinfo=IST)
    plain = youtube.channel({"id": "c", "long": {"publish_time": "20:00"}})
    local = datetime.fromtimestamp(youtube.next_slot(store, plain, now=now, fmt="long"))
    assert (local.hour, local.minute) == (20, 0)


@FFMPEG
def test_an_analysis_night_makes_a_video_from_the_filings_with_only_an_old_price(env_analysis):
    env = env_analysis
    report, log = made(env)
    crew = {a["name"]: a for a in env["bus"].state["masters"]["youtube"]["agents"]}
    assert [crew[n]["status"] for n in ("Results Scout", "Market Analyst", "Tanglish Writer", "Voice Clone", "Slide Editor", "Market Uploader")] == ["done"] * 6, crew
    rec, = log
    sym = rec["symbol"]
    assert rec["status"] == "awaiting" and rec["kind"] == "analysis" and rec["format"] == "long" and sym in ("SAMPLE", "OTHER") and rec["quarter"] == "Q1 FY27"
    assert rec["title"].startswith("Sample Fundamental Analysis | ROE ") and rec["title"].endswith("எப்படி? | தமிழில்") and Path(rec["thumb"]).exists()
    assert rec["summary"].endswith(market_crew.DISCLAIMER) and "Shareholding: NSE" in rec["summary"] and "nsearchives.test/f_jun26.xml" in rec["summary"]
    day = rec["price_date"]
    assert datetime.strptime(day, "%Y-%m-%d").date() <= datetime.now().date() - timedelta(days=31)
    assert f"Price as of {datetime.strptime(day, '%Y-%m-%d').strftime('%d %b %Y')} (Yahoo Finance), older than 30 days as SEBI's rule" in rec["summary"]
    assert "9999" not in rec["summary"] + rec["script"] and all(r["value"] < 9000 for r in rec["ratios"] if r["key"] in ("price", "high")) and "price" in {r["key"] for r in rec["ratios"]}
    assert env["yt"]["meta"]["snippet"]["description"] == rec["summary"] and env["store"].kv_has(market_crew.DONE, f"analysis:{sym}")
    assert sorted({p.parent.name for p in (env["tmp"] / "data" / "shorts" / "manimarket").glob("*/*")}) == ["analysis-SAMPLE-2026-06-30"] or sym == "OTHER"
    ap, = env["store"].pending_approvals()
    assert ap["payload"]["kind"] == "yt_publish" and ap["title"].startswith("Publish: Sample Fundamental Analysis")


def release_on(monkeypatch, year, month, day):
    """The next long release falls on this IST day at 10:00."""
    monkeypatch.setattr(youtube, "next_slot", lambda store, ch, now=None, fmt="short": datetime(year, month, day, 10, 0, tzinfo=IST).timestamp())


def test_the_scout_chooses_the_kind_by_the_weekday_of_the_release(env, monkeypatch):
    ch = youtube.channel({**RAW, "pattern": {"mon": "analysis", "tue": "topic"}})
    scout = market_crew.ResultsScout(ch, client_factory=web(env["yt"]))
    release_on(monkeypatch, 2026, 10, 19)                                          # a Monday
    ctx = scout_ctx(env, reason="manual")
    res = asyncio.run(scout.run(ctx))
    assert res.label == "FOUND" and ctx["job"]["kind"] == "analysis" and ctx["job"]["symbol"] in ("SAMPLE", "OTHER") and ctx["job"]["key"] == f"analysis:{ctx['job']['symbol']}"
    assert ctx["job"]["symbol"] == "SAMPLE" and ctx["job"]["more"] == ["OTHER"] and "2026-10-19" in res.summary          # the date's hash, pinned
    release_on(monkeypatch, 2026, 10, 20)                                          # a Tuesday: topic videos are not built, so a result
    ctx = scout_ctx(env, reason="manual")
    res = asyncio.run(scout.run(ctx))
    assert res.label == "FOUND" and ctx["job"]["kind"] == "result" and ctx["job"]["key"] == "SAMPLE:Q2 FY27" and "topic" in res.summary
    release_on(monkeypatch, 2026, 10, 21)                                          # a Wednesday, no pattern entry: a result
    ctx = scout_ctx(env, reason="manual")
    asyncio.run(scout.run(ctx))
    assert ctx["job"]["kind"] == "result"
    ctx = scout_ctx(env, reason="manual", force={"kind": "analysis", "symbol": "sample"})
    asyncio.run(scout.run(ctx))
    assert (ctx["job"]["kind"], ctx["job"]["symbol"], ctx["job"]["more"]) == ("analysis", "SAMPLE", [])


def test_a_company_is_not_analysed_twice_within_180_days_and_skipped_ones_count(env, monkeypatch):
    ch = youtube.channel({**RAW, "pattern": ANALYSIS})
    scout = market_crew.ResultsScout(ch, client_factory=web(env["yt"]))
    release_on(monkeypatch, 2026, 10, 19)
    now = time.time()
    env["store"].kv_put(market_crew.DONE, "analysis:SAMPLE", {"at": now - 10 * 86400})
    env["store"].kv_put(market_crew.DONE, "analysis:OTHER", {"skipped": "too few ratios", "at": now - 100 * 86400, "parser": nse.PARSER})
    ctx = scout_ctx(env, reason="manual")
    res = asyncio.run(scout.run(ctx))
    assert res.label == "NOTHING NEW" and "job" not in ctx and "180 days" in res.summary
    env["store"].kv_put(market_crew.DONE, "analysis:OTHER", {"at": now - 200 * 86400})            # over 180 days ago: eligible again, oldest first
    ctx = scout_ctx(env, reason="manual")
    asyncio.run(scout.run(ctx))
    assert ctx["job"]["symbol"] == "OTHER" and ctx["job"]["more"] == []


def test_a_company_with_too_few_ratios_is_skipped_and_the_next_one_is_tried(env, monkeypatch):
    thin = {"name": "Thin Limited", "ttm": {}, "ttm_to": "2026-06-30"}
    full = {"name": "Full Limited", "ttm": {}, "ttm_to": "2026-06-30"}

    async def gather(c, sym, lag=31):
        return (thin, [{}] * 7, None) if sym == "THIN" else (full, [{}] * 9, {"date": "2026-09-11"})
    monkeypatch.setattr(market_crew, "gather", gather)
    analyst = market_crew.MarketAnalyst(env["ch"], client_factory=web(env["yt"]))
    ctx = scout_ctx(env, job={"kind": "analysis", "symbol": "THIN", "key": "analysis:THIN", "more": ["FULL"], "dir": "x"})
    res = asyncio.run(analyst.run(ctx))
    assert res.label == "READ" and ctx["job"]["symbol"] == "FULL" and ctx["job"]["key"] == "analysis:FULL" and ctx["job"]["dir"].endswith("analysis-FULL-2026-06-30")
    assert env["store"].kv_get(market_crew.DONE, "analysis:THIN")["skipped"] == "too few ratios" and not env["store"].kv_has(market_crew.DONE, "analysis:FULL")
    ctx = scout_ctx(env, job={"kind": "analysis", "symbol": "THIN", "key": "analysis:THIN", "more": [], "dir": "x"})
    res = asyncio.run(analyst.run(ctx))
    assert (res.status, res.label) == ("wait", "TOO FEW FIGURES") and "job" not in ctx
    assert asyncio.run(market_crew.TanglishWriter(env["ch"]).run(ctx)).label == "IDLE"


@FFMPEG
def test_a_night_with_the_companys_press_release_and_the_news_backs_the_video_and_still_ends_awaiting(env):
    env["yt"]["backing"] = True
    env["m"].services["llm"] = Writer()
    SEEN.clear()
    report, log = made(env)
    crew = {a["name"]: a for a in env["bus"].state["masters"]["youtube"]["agents"]}
    assert [crew[n]["status"] for n in ("Results Scout", "Market Analyst", "Tanglish Writer", "Voice Clone", "Slide Editor", "Market Uploader")] == ["done"] * 6, crew
    rec, = log
    assert rec["status"] == "awaiting" and [r["metric"] for r in rec["reasons"]] == ["revenue"] and rec["reasons"][0]["doc"]["url"] == "https://nsearchives.test/pr.pdf"
    assert "Revenue grew 10 percent" in rec["reasons"][0]["quote"] and sorted(n["source"] for n in rec["news"]) == ["Hindu", "The Mint"]    # the share-price headline is gone
    assert "Company document: Press Release," in rec["summary"] and "(https://nsearchives.test/pr.pdf)" in rec["summary"] and "News: The Mint," in rec["summary"]
    assert rec["summary"].endswith(market_crew.DISCLAIMER) and env["yt"]["meta"]["snippet"]["description"] == rec["summary"]
    deck, = SEEN
    assert [s["kind"] for s in deck] == ["notice", "cover", "table", "quotes", "quotes", "points"] and [s["title"] for s in deck[3:5]] == ["ஏன் இப்படி? · Company சொன்னது", "News-ல"]
    assert "ஸாம்பிள் ரிசல்ட் பத்தி" in rec["script"] or "ஸாம்பிள் மார்ஜின் பத்தி" in rec["script"] and "Company சொல்ற காரணம் இது" in rec["script"]
    ap, = env["store"].pending_approvals()
    assert ap["payload"]["kind"] == "yt_publish" and any(b.startswith("revenue:") for b in ap["payload"]["backed"]) and any(b.startswith("news:") for b in ap["payload"]["backed"])


def test_the_listen_back_is_summed_up_for_the_record_and_a_failed_voice_is_held(tmp_path):
    (tmp_path / "qa.json").write_text(json.dumps([{"score": 0.9, "tries": 1, "gap": 0.2}, {"score": 0.7, "tries": 2, "gap": 0.4}]), encoding="utf-8")
    qa = market_crew.voice_qa(tmp_path)
    assert (qa["lines"], qa["lowest"], qa["mean"], qa["made_again"], qa["longest_gap"]) == (2, 0.7, 0.8, 1, 0.4) and qa["text"] == "heard 0.70 at worst, 1 made again"
    assert market_crew.voice_qa(tmp_path / "none") is None


# ---- the Scout's coverage, the candidates it lines up, and a result that cannot be read -----------------------------------------------------------

def paged(rows_by_page, calls):
    """NSE's market-wide list with paging: `size` rows a page, pages from 1 (the first needs no page). calls records (page, size) of each request."""
    def handler(req):
        u = str(req.url)
        if "index.csv" in u:
            return httpx.Response(200, text=CSV + "Third Ltd,Stuff,THIRD,EQ,INE000A01012\n")
        if "integrated-filing-results" in u and "symbol" not in req.url.params:
            page = int(req.url.params.get("page", 1))
            calls.append((page, req.url.params.get("size")))
            return httpx.Response(200, json={"data": rows_by_page.get(page, [])})
        return httpx.Response(404)
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def listed_row(symbol, hours_ago, end="30-SEP-2026", broadcast=True):
    when = time.strftime("%d-%b-%Y %H:%M:%S", time.localtime(time.time() - hours_ago * 3600))
    return {"symbol": symbol, "smName": symbol.title() + " Limited", "qe_Date": end, "consolidated": "Consolidated", "audited": "Audited",
            "broadcast_Date": when if broadcast else None, "creation_Date": when, "xbrl": f"https://nsearchives.test/{symbol}-{end}.xml"}


def test_the_scout_reads_the_filing_list_page_by_page_until_it_reaches_back_past_the_window(env):
    calls = []
    page1 = [listed_row(f"FILL{n}", 1) for n in range(100)]                                  # a full page, all filed within the window: ask for the next
    page2 = [listed_row("OTHER", 50, broadcast=False), listed_row("OLDONE", 24 * 9)]          # OTHER has no broadcast time yet (its creation time stands in); the last row is 9 days old
    scout = market_crew.ResultsScout(env["ch"], client_factory=paged({1: page1, 2: page2, 3: [listed_row("NEVER", 1)]}, calls))
    ctx = scout_ctx(env)
    res = asyncio.run(scout.run(ctx))
    assert calls == [(1, "100"), (2, "100")] and res.label == "FOUND" and ctx["job"]["symbol"] == "OTHER" and ctx["job"]["more"] == []        # page 3 is never asked for
    page = [listed_row("OTHER", 1), listed_row("OLDONE", 24 * 9)]                              # a short page ends the reading at once
    calls.clear()
    res = asyncio.run(market_crew.ResultsScout(env["ch"], client_factory=paged({1: page}, calls)).run(scout_ctx(env)))
    assert calls == [(1, "100")] and res.label == "FOUND"


def test_the_scout_lines_up_up_to_three_unfinished_results_newest_first_without_repeats(env):
    rows = [listed_row("OTHER", 1), {**listed_row("OTHER", 1), "consolidated": "Standalone", "xbrl": "https://nsearchives.test/o-s.xml"}, listed_row("SAMPLE", 2), listed_row("THIRD", 3),
            listed_row("OTHER", 30, end="30-JUN-2026"), listed_row("STRANGER", 1)]
    ctx = scout_ctx(env)
    res = asyncio.run(market_crew.ResultsScout(env["ch"], client_factory=paged({1: rows}, [])).run(ctx))
    job = ctx["job"]
    assert res.label == "FOUND" and [job["key"]] + [m["key"] for m in job["more"]] == ["OTHER:Q2 FY27", "SAMPLE:Q2 FY27", "THIRD:Q2 FY27"] and "more to try" in res.summary
    env["store"].kv_put(market_crew.DONE, "SAMPLE:Q2 FY27", {"at": 1, "file": "x"})
    ctx = scout_ctx(env)
    asyncio.run(market_crew.ResultsScout(env["ch"], client_factory=paged({1: rows}, [])).run(ctx))
    assert [ctx["job"]["key"]] + [m["key"] for m in ctx["job"]["more"]] == ["OTHER:Q2 FY27", "THIRD:Q2 FY27", "OTHER:Q1 FY27"]


def test_a_skip_made_by_an_older_parser_is_tried_again_and_one_by_the_current_parser_is_not(env):
    scout = market_crew.ResultsScout(env["ch"], client_factory=web(env["yt"]))
    old = {"skipped": "no figures", "at": time.time()}                                         # what last night wrote: no parser recorded
    env["store"].kv_put(market_crew.DONE, "SAMPLE:Q2 FY27", old)
    ctx = scout_ctx(env)
    assert asyncio.run(scout.run(ctx)).label == "FOUND" and ctx["job"]["key"] == "SAMPLE:Q2 FY27"
    env["store"].kv_put(market_crew.DONE, "SAMPLE:Q2 FY27", {**old, "parser": nse.PARSER})
    assert asyncio.run(scout.run(scout_ctx(env))).label == "NOTHING NEW"
    env["store"].kv_put(market_crew.DONE, "SAMPLE:Q2 FY27", {**old, "parser": nse.PARSER - 1})
    assert asyncio.run(scout.run(scout_ctx(env))).label == "FOUND"
    env["store"].kv_put(market_crew.DONE, "SAMPLE:Q2 FY27", {"at": time.time(), "file": "x.mp4"})        # a video that was made is never made again
    assert asyncio.run(scout.run(scout_ctx(env))).label == "NOTHING NEW"
    assert market_crew.done_at(env["store"], "NOBODY:Q1 FY27") is None


def good_result(sym):
    return {"symbol": sym, "name": f"{sym.title()} Limited", "quarter": "Q2 FY27", "rows": [{"key": "revenue", "label": "Revenue", "unit": "cr", "now": 1.0, "prev": 1.0, "year": 1.0}],
            "bank": False, "consolidated": True, "source": "u", "filed": "13-Oct-2026 04:04:30"}


def candidate(sym):
    return {"kind": "result", "symbol": sym, "quarter": "Q2 FY27", "key": f"{sym}:Q2 FY27", "name": f"{sym.title()} Limited", "end": "2026-09-30", "dir": f"d-{sym}"}


def test_a_result_that_cannot_be_read_is_marked_tried_and_the_next_candidate_is_taken_without_an_error(env, monkeypatch):
    async def latest(c, sym):
        return good_result(sym) if sym == "GOOD" else {**good_result(sym), "rows": []} if sym == "EMPTY" else None
    async def none(*a, **k):
        return None
    monkeypatch.setattr(market_crew.nse, "latest", latest)
    monkeypatch.setattr(market_crew.nse, "fundamentals", none)
    monkeypatch.setattr(market_crew, "documents", none)
    monkeypatch.setattr(market_crew, "headlines", none)
    analyst = market_crew.MarketAnalyst(env["ch"], client_factory=web(env["yt"]))
    ctx = scout_ctx(env, job={**candidate("BAD"), "more": [candidate("EMPTY"), candidate("GOOD")]})
    res = asyncio.run(analyst.run(ctx))
    assert (res.status, res.label) == ("done", "READ") and ctx["job"]["symbol"] == "GOOD" and ctx["job"]["key"] == "GOOD:Q2 FY27" and ctx["job"]["dir"] == "d-GOOD"
    assert "BAD Q2 FY27" in res.summary and "EMPTY Q2 FY27" in res.summary and ctx["job"]["more"] == []
    for sym in ("BAD", "EMPTY"):
        skipped = env["store"].kv_get(market_crew.DONE, f"{sym}:Q2 FY27")
        assert skipped["skipped"] == "no figures" and skipped["parser"] == nse.PARSER
    assert not env["store"].kv_has(market_crew.DONE, "GOOD:Q2 FY27")
    ctx = scout_ctx(env, job={**candidate("BAD"), "more": []})                                 # nothing readable: not an error, the rest of the crew idles
    res = asyncio.run(analyst.run(ctx))
    assert (res.status, res.label) == ("wait", "UNREADABLE") and "job" not in ctx and "BAD Q2 FY27" in res.summary
    assert asyncio.run(market_crew.TanglishWriter(env["ch"]).run(ctx)).label == "IDLE"


def test_an_insurer_or_a_lender_needs_one_ratio_fewer_than_a_company_before_it_is_filmed(env, monkeypatch):
    async def gather(c, sym, lag=31):
        return {"name": "Life Limited", "kind": "life", "ttm": {}, "ttm_to": "2026-06-30"}, [{}] * 7, None
    monkeypatch.setattr(market_crew, "gather", gather)
    ctx = scout_ctx(env, job={"kind": "analysis", "symbol": "LIFE", "key": "analysis:LIFE", "more": [], "dir": "x"})
    res = asyncio.run(market_crew.MarketAnalyst(env["ch"], client_factory=web(env["yt"])).run(ctx))
    assert res.label == "READ" and ctx["job"]["symbol"] == "LIFE"


def test_the_titles_name_what_each_form_shows():
    t = market_crew.SlideEditor.title
    assert "Premium, Profit, Solvency" in t({"name": "ICICI Life Limited", "quarter": "Q2 FY27", "kind": "life"})
    assert "Premium, Profit, Combined Ratio" in t({"name": "X Limited", "quarter": "Q2 FY27", "kind": "general"})
    assert "NII, Profit, Asset Quality" in t({"name": "X Limited", "quarter": "Q2 FY27", "kind": "nbfc", "lender": True})
    assert "Revenue, Profit, Margin" in t({"name": "X Limited", "quarter": "Q2 FY27", "bank": False}) and "NII, Profit, NPA" in t({"name": "X", "quarter": "Q1 FY27", "bank": True})
    assert "Revenue, Profit, EPS" in t({"name": "X Limited", "quarter": "Q2 FY27", "kind": "nbfc", "lender": False})
