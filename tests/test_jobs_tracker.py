"""Mani, 2026-10-18: approve = Approved (not applied), packages go to Drive under Vision/ and leave the Mac, a tracker like
LinkedIn's My Jobs, and Telegram /agents, /agent, /jobs, /track."""
import asyncio
import hashlib
import json

import httpx
import pytest

from vision import desk
from vision.bus import EventBus, Store
from vision.masters import jobs
from vision.services import gdrive, oauth

from test_telegram import make


def fake_drive():
    drive = {"folders": {}, "files": {}, "corrupt": False, "moved": []}

    def handler(req):
        u = str(req.url)
        if req.method == "GET" and u.startswith(gdrive.API + "?"):
            q = req.url.params["q"]
            name = q.split("name = '")[1].split("'")[0]
            par = q.split("and '")[-1].split("'")[0] if "in parents" in q else None
            hits = [{"id": k, **v} for k, v in {**drive["folders"], **drive["files"]}.items()
                    if v["name"] == name and (par is None or (v.get("parents") or ["root"])[0] == par)]
            return httpx.Response(200, json={"files": hits})
        if req.method == "POST" and u.startswith(gdrive.UPLOAD):
            meta = json.loads(req.content)
            return httpx.Response(200, headers={"location": "https://upload.test/s?" + meta["name"]}, json={})
        if req.method == "POST" and u.startswith(gdrive.API):
            meta = json.loads(req.content)
            fid = f"f{len(drive['folders'])}"
            drive["folders"][fid] = {"name": meta["name"], "parents": meta.get("parents")}
            return httpx.Response(200, json={"id": fid})
        if req.method == "PUT" and u.startswith("https://upload.test/"):
            body = req.read()
            fid = f"d{len(drive['files'])}"
            drive["files"][fid] = {"name": __import__("urllib.parse").parse.unquote(req.url.query.decode()), "size": str(len(body)),
                                   "md5Checksum": "bad" if drive["corrupt"] else hashlib.md5(body).hexdigest()}
            return httpx.Response(200, json={"id": fid})
        if req.method == "GET" and u.startswith(gdrive.API + "/"):
            fid = req.url.path.rsplit("/", 1)[1]
            if fid in drive["folders"]:
                return httpx.Response(200, json={"parents": drive["folders"][fid].get("parents") or ["root"]})
            f = drive["files"][fid]
            return httpx.Response(200, json={"size": f["size"], "md5Checksum": f["md5Checksum"]})
        if req.method == "PATCH" and u.startswith(gdrive.API + "/"):
            fid = req.url.path.rsplit("/", 1)[1]
            meta = json.loads(req.content or b"{}")
            drive["folders"][fid].update(parents=[req.url.params["addParents"]], **({"name": meta["name"]} if meta.get("name") else {}))
            drive["moved"].append(fid)
            return httpx.Response(200, json={"id": fid})
        return httpx.Response(404)

    return drive, lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def signed_in(monkeypatch, on=True):
    async def token(account, provider, client=None):
        if not on:
            raise oauth.AuthNeeded(account, provider)
        return "tok"
    monkeypatch.setattr(oauth, "access_token", token)


def package(tmp_path, store, key="j1"):
    d = tmp_path / "applications" / "acme-dev"
    d.mkdir(parents=True)
    (d / "resume.docx").write_bytes(b"resume")
    (d / "cover_letter.md").write_text("Dear Acme")
    store.kv_put("jobs", key, {"id": key, "title": "Dev", "company": "Acme", "url": "https://acme.test/j", "status": "awaiting_ok", "folder": str(d)})
    return d


def test_approving_marks_the_job_approved_moves_the_package_to_drive_and_only_then_clears_the_mac(tmp_path, monkeypatch):
    store, bus = Store(tmp_path / "t.db"), EventBus()
    d = package(tmp_path, store)
    drive, client = fake_drive()
    monkeypatch.setattr(jobs, "_client", client)
    row = {"payload": {"job": "j1", "url": "https://acme.test/j", "folder": str(d)}}

    signed_in(monkeypatch, False)                                                   # no Drive sign-in: approved, files stay, asked to sign in
    asyncio.run(jobs.approve_package(row, "approved", {"store": store, "bus": bus}))
    j = store.kv_get("jobs", "j1")
    assert j["status"] == "approved" and not j.get("applied_at") and d.exists() and "gdrive-backup" in bus.state["notices"]

    signed_in(monkeypatch)
    drive["corrupt"] = True                                                         # Drive's copy doesn't match: kept
    assert "does not match" in asyncio.run(jobs.to_drive({"store": store, "bus": bus}, client))
    assert d.exists() and not store.kv_get("jobs", "j1").get("drive")

    drive.update(corrupt=False, files={})
    assert asyncio.run(jobs.to_drive({"store": store, "bus": bus}, client)) == "1 packages moved to Drive"
    j = store.kv_get("jobs", "j1")
    assert not d.exists() and j["local_removed"] and j["drive"]["folder"] == "Vision/Jobs/acme-dev" and j["status"] == "approved"
    assert sorted(f["name"] for f in drive["files"].values()) == ["cover_letter.md", "resume.docx"]
    assert {v["name"] for v in drive["folders"].values()} == {"Vision", "Jobs", "acme-dev"}
    item = next(i for i in desk.build(store, "jobs")["items"] if i["id"] == "j1")
    assert item["stage"] == "approved" and [a["status"] for a in item["actions"]] == ["applied", "archived"]
    assert any(l["label"] == "Files in Drive" and l["url"].startswith("https://drive.google.com/") for l in item["links"])


def test_rejecting_keeps_the_package_on_the_mac(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.db")
    d = package(tmp_path, store)
    signed_in(monkeypatch)
    asyncio.run(jobs.approve_package({"payload": {"job": "j1", "url": "u", "folder": str(d)}}, "rejected", {"store": store, "bus": EventBus()}))
    assert store.kv_get("jobs", "j1")["status"] == "passed" and d.exists()


def test_tracker_moves_and_applied_date(tmp_path):
    store = Store(tmp_path / "t.db")
    store.kv_put("jobs", "j1", {"id": "j1", "title": "Dev", "company": "Acme", "status": "approved"})
    j = jobs.set_status(store, "j1", "applied", "sent via their site")
    assert j["applied_at"] and j["note"] == "sent via their site" and [h["status"] for h in j["history"]] == ["applied"]
    first = j["applied_at"]
    assert jobs.set_status(store, "j1", "interview")["applied_at"] == first
    with pytest.raises(ValueError):
        jobs.set_status(store, "j1", "hired")
    with pytest.raises(ValueError):
        jobs.set_status(store, "nope", "applied")


def test_tracking_a_job_applied_elsewhere_reads_its_title_and_never_indeed(tmp_path):
    store = Store(tmp_path / "t.db")
    page = lambda req: httpx.Response(200, text='<html><head><meta property="og:title" content="Data Analyst &amp; BI"></head></html>')
    client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(page))
    j = asyncio.run(jobs.track(store, "https://boards.greenhouse.io/x/jobs/1", company="X", client=client))
    assert j["title"] == "Data Analyst & BI" and j["status"] == "applied" and j["applied_at"] and j["source"] == "added by you"
    with pytest.raises(ValueError, match="already"):
        asyncio.run(jobs.track(store, "https://boards.greenhouse.io/x/jobs/1", client=client))
    with pytest.raises(ValueError, match="Indeed"):
        asyncio.run(jobs.track(store, "https://ca.indeed.com/viewjob?jk=1", client=client))
    with pytest.raises(ValueError):
        asyncio.run(jobs.track(store, "not a link"))


def test_youtube_backups_move_the_old_top_level_folder_under_vision(tmp_path, monkeypatch):
    drive, client = fake_drive()
    drive["folders"]["old"] = {"name": "confessions_everywhere_yt", "parents": ["root"]}
    drive["folders"]["oldS"] = {"name": "Shorts", "parents": ["old"]}

    async def go():
        async with client() as c:
            return await gdrive.vision_path(c, "tok", "YouTube", "Confessions Everywhere", legacy="confessions_everywhere_yt"), \
                   await gdrive.vision_path(c, "tok", "YouTube", "Confessions Everywhere", legacy="confessions_everywhere_yt")

    first, again = asyncio.run(go())
    assert first == again == "old" and drive["moved"] == ["old"]                   # moved and renamed once, with its Shorts inside
    assert drive["folders"]["old"]["name"] == "Confessions Everywhere"
    yt = drive["folders"]["old"]["parents"][0]
    assert drive["folders"][yt]["name"] == "YouTube" and drive["folders"][drive["folders"][yt]["parents"][0]]["name"] == "Vision"


def test_telegram_lists_masters_one_masters_agents_and_one_agent(tmp_path, monkeypatch):
    bus, store, orch, tg, fake = make(tmp_path, monkeypatch)
    bus.publish({"type": "agent", "master": "jobs", "agent": {"name": "Resume Tailor", "status": "error", "label": "ERROR", "summary": "Groq said 429", "tier": "CLOUD"}})
    bus.publish({"type": "agent", "master": "jobs", "agent": {"name": "Application Tracker", "status": "done", "label": "TRACKING", "summary": "2 approved", "reporter": True}})
    asyncio.run(store.record_run("jobs", "Resume Tailor", "error", "ERROR", "Groq said 429", "429 Too Many Requests", 1200))
    top = tg.agents_text()
    assert "Job Hunt" in top or "jobs" in top
    one = tg.agents_text("jobs")
    assert "🔴 <b>Resume Tailor</b>" in one and "Groq said 429" in one and "Application Tracker</b> 📣" in one
    assert "No master matches" in tg.agents_text("nothing")
    a = tg.agent_text("resume")
    assert "Resume Tailor" in a and "Status: ERROR" in a and "Says: Groq said 429" in a and "Error: 429 Too Many Requests" in a and "1.2 s" in a
    assert "No agent matches" in tg.agent_text("zzz")


def test_telegram_jobs_buttons_move_a_job(tmp_path, monkeypatch):
    bus, store, orch, tg, fake = make(tmp_path, monkeypatch)
    store.kv_put("jobs", "j1", {"id": "j1", "title": "Dev", "company": "Acme", "url": "https://acme.test/j", "status": "approved"})
    asyncio.run(tg.on_command("/jobs"))
    msgs = fake.sent()
    assert "1 approved" in msgs[0]["text"]
    btns = json.loads(msgs[1]["reply_markup"])["inline_keyboard"][0] if isinstance(msgs[1].get("reply_markup"), str) else msgs[1]["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in btns] == ["jb:j1:applied", "jb:j1:archived"]
    asyncio.run(tg._on_button({"id": "q", "data": "jb:j1:applied", "message": {"chat": {"id": 42}, "message_id": 1, "text": "Dev"}}))
    assert store.kv_get("jobs", "j1")["status"] == "applied"
    asyncio.run(tg.on_command("/track https://ca.indeed.com/viewjob?jk=1"))
    assert "never touches Indeed" in fake.sent()[-1]["text"]


def test_jobs_the_old_code_marked_applied_on_approval_become_approved(tmp_path):
    store = Store(tmp_path / "t.db")
    store.kv_put("jobs", "old", {"id": "old", "title": "Dev", "status": "applied", "applied_at": 5, "followups": 1, "followup_at": 6})
    store.kv_put("jobs", "mine", {"id": "mine", "title": "QA", "status": "applied", "source": "added by you"})
    store.kv_put("jobs", "real", {"id": "real", "title": "BA", "status": "applied", "applied_at": 7, "history": [{"status": "applied", "at": 7}]})
    assert jobs.legacy_approved(store) == 1 and jobs.legacy_approved(store) == 0
    old = store.kv_get("jobs", "old")
    assert old["status"] == "approved" and old["approved_at"] == 5 and "applied_at" not in old and "followups" not in old
    assert store.kv_get("jobs", "mine")["status"] == "applied" and store.kv_get("jobs", "real")["status"] == "applied"
