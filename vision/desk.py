"""Read-only "desk" views: each master's pipeline items and local artifacts, built from what VISION already stores."""

from __future__ import annotations

import json
import mimetypes
import re
import time
from pathlib import Path

from .config import ROOT

ALLOWED = ("sites", "applications")   # folders under ROOT/data that /api/files may serve
LIMIT = 60
REPORT_MASTERS = ("invest", "news", "world", "traffic")
CATALOG = Path(__file__).parent / "masters" / "catalog.json"


# ---------- files ----------
def resolve_file(rel: str) -> Path | None:
    """URL path (relative to ROOT/data) -> a real file inside data/sites or data/applications, else None."""
    try:
        if not rel or rel.startswith(("/", "\\")) or "\x00" in rel or ".." in Path(rel).parts:
            return None
        base = ROOT / "data"
        p = (base / rel).resolve()
        for a in ALLOWED:
            root = (base / a).resolve()
            if p.is_relative_to(root) and p.is_file():
                return p
    except (OSError, ValueError):
        pass
    return None


def file_ref(path: str | Path | None, label: str = "") -> dict | None:
    """A served-file entry for a local path, or None when it isn't a servable artifact."""
    try:
        p = Path(path).resolve() if path else None
        if not p:
            return None
        rel = p.relative_to((ROOT / "data").resolve()).as_posix()
        if resolve_file(rel) is None:
            return None
        return {"label": label or p.name, "url": "/api/files/" + rel, "mime": mimetypes.guess_type(p.name)[0] or "application/octet-stream"}
    except (OSError, ValueError, TypeError):
        return None


def folder_files(folder: str | Path | None) -> list[dict]:
    try:
        d = Path(folder).resolve() if folder else None
        if not d or not d.is_dir():
            return []
        return [f for f in (file_ref(p) for p in sorted(d.rglob("*")) if p.is_file()) if f][:40]
    except (OSError, TypeError):
        return []


def _text_file(folder: str | None, *names: str) -> str:
    for n in names:
        try:
            p = Path(folder or "") / n
            if folder and p.is_file() and file_ref(p):
                return p.read_text(errors="replace")[:20000]
        except OSError:
            pass
    return ""


# ---------- helpers ----------
def _s(v) -> str:
    return "" if v is None else str(v)


def _rows(*pairs) -> list[list[str]]:
    return [[k, _s(v)] for k, v in pairs if v not in (None, "", [])]


def _links(*pairs) -> list[dict]:
    return [{"label": k, "url": u} for k, u in pairs if isinstance(u, str) and re.match(r"https?://", u)]


def _item(id, stage, title, sub="", ts=None, rows=None, body="", links=None, files=None) -> dict:
    return {"id": _s(id), "stage": stage, "title": _s(title), "sub": _s(sub), "ts": ts if isinstance(ts, (int, float)) else None,
            "rows": rows or [], "body": body or "", "links": links or [], "files": files or []}


def _approvals(store, master: str) -> list[dict]:
    try:
        with store._conn() as c:
            ids = [r["id"] for r in c.execute("SELECT id FROM approvals WHERE master = ? ORDER BY ts DESC LIMIT 200", (master,)).fetchall()]
            return [a for a in (store.get_approval(i, c) for i in ids) if a]
    except Exception:
        return []


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


def _kv(store, ns: str, limit: int = 500) -> list[dict]:
    return _safe(store.kv_list, ns, 0, limit) or []


def _each(rows, fn) -> list[dict]:
    out = []
    for r in rows:
        it = _safe(fn, r)
        if it:
            out.append(it)
    return out


# ---------- masters ----------
def web(store):
    stages = [("building", "Building"), ("live", "Live"), ("awaiting", "Awaiting you"), ("pitched", "Pitched"), ("held", "Held back"), ("parked", "Parked")]
    of = {"new": "building", "researched": "building", "built": "building", "deployed": "live", "pitch_ready": "awaiting", "pitched": "pitched", "parked": "parked",
          "qa_failed": "held"}   # failed the quality check: never deployed, kept as a draft
    pitches = {p["_key"]: p for p in _kv(store, "pitches", 1000)}
    pending = {a["payload"].get("lead"): a for a in _approvals(store, "web") if a["status"] == "pending"}

    def one(l):
        st = of.get(l.get("status"))
        if not st:
            return None
        k = l.get("_key") or l.get("id")
        pitch = pitches.get(k) or {}
        body = pitch.get("message") or (pending.get(k) or {}).get("payload", {}).get("message") or ""
        qa = l.get("qa") or {}
        if st == "held":
            body = "Held back by the quality check:\n" + "\n".join("• " + str(x) for x in qa.get("issues") or [])
        phone = l.get("phone") or pitch.get("phone")
        rows = _rows(("Type", l.get("type_label") or l.get("type")), ("Phone", phone), ("Address", l.get("address")),
                     ("Rating", l.get("rating")), ("Status", l.get("status")), ("Style", l.get("style")), ("Why this style", l.get("style_why")),
                     ("Quality", f"{qa['score']} / 100" if qa.get("score") is not None else None))
        return _item(k, st, l.get("name") or k, l.get("type_label") or "", pitch.get("at") or l.get("_ts"), rows, body,
                     _links(("Live demo", l.get("url") or pitch.get("url"))), [f for f in [file_ref(l.get("site"), "Demo page"), file_ref(l.get("draft"), "Draft page")] if f])
    return stages, _each(_kv(store, "leads", 1000), one)


def jobs(store):
    stages = [("match", "Matched"), ("tailored", "Tailored"), ("awaiting_ok", "Awaiting you"), ("applied", "Applied"), ("interview", "Interview"), ("closed", "Closed")]
    of = {"match": "match", "tailored": "tailored", "awaiting_ok": "awaiting_ok", "applied": "applied", "interview": "interview", "rejected": "closed", "passed": "closed"}

    def one(j):
        st = of.get(j.get("status"))
        if not st:
            return None
        rows = _rows(("Company", j.get("company")), ("Location", j.get("location")), ("Fit", j.get("score")), ("Source", j.get("source")),
                     ("Why", j.get("why")), ("Status", j.get("status")))
        return _item(j.get("_key") or j.get("id"), st, j.get("title"), j.get("company") or j.get("source") or "", j.get("found") or j.get("_ts"), rows,
                     _text_file(j.get("folder"), "cover_letter.md", "cover_letter.txt"), _links(("Job posting", j.get("url"))), folder_files(j.get("folder")))
    return stages, _each(_kv(store, "jobs", 2000), one)


def email(store):
    stages = [("awaiting", "Drafts awaiting you"), ("sent", "Sent"), ("rejected", "Rejected")]
    of = {"pending": "awaiting", "sent": "sent", "rejected": "rejected"}
    seen = set()

    def one(d):
        st = of.get(d.get("status"))
        if not st:
            return None
        if st == "sent":
            seen.add((d.get("to"), d.get("subject")))
        return _item("draft:" + _s(d.get("_key")), st, d.get("subject"), d.get("to") or "", d.get("_ts"),
                     _rows(("To", d.get("to")), ("Subject", d.get("subject"))), _s(d.get("body")))
    items = _each(_kv(store, "drafts", 500), one)
    items += _each([s for s in _kv(store, "sent", 200) if (s.get("to"), s.get("subject")) not in seen],
                   lambda s: _item("sent:" + _s(s.get("_key")), "sent", s.get("subject"), s.get("to") or "", s.get("_ts"),
                                   _rows(("To", s.get("to")), ("Subject", s.get("subject")), ("Account", s.get("account")))))
    return stages, items


def calendar(store):
    stages = [("new", "Meeting requests"), ("proposed", "Awaiting you"), ("booked", "Booked"), ("declined", "Declined"), ("reminders", "Reminders")]

    def one(r):
        st, m = r.get("status"), r.get("email") or {}
        if st not in ("new", "proposed", "booked", "declined"):
            return None
        return _item("meet:" + _s(r.get("_key")), st, m.get("subject"), m.get("from_name") or m.get("from") or "", r.get("_ts"),
                     _rows(("From", m.get("from")), ("Subject", m.get("subject")), ("Status", st)), _s(m.get("snippet")))

    def rem(r):
        return _item("rem:" + _s(r.get("_key")), "reminders", r.get("text"), "done" if r.get("fired") else "upcoming", r.get("at") or r.get("_ts"),
                     _rows(("When", time.strftime("%Y-%m-%d %H:%M", time.localtime(r["at"])) if isinstance(r.get("at"), (int, float)) else None),
                           ("Fired", "yes" if r.get("fired") else "no")))
    return stages, _each(_kv(store, "meeting_requests", 500), one) + _each(_kv(store, "reminders", 200), rem)


def trading(store):
    stages = [("awaiting", "Calls awaiting you"), ("executed", "Executed"), ("rejected", "Rejected / expired")]
    apps = [a for a in _approvals(store, "trading") if a["payload"].get("kind") == "trade"]
    trades = _kv(store, "trades", 200)

    def facts(p):
        return _rows(("Instrument", _s(p.get("instrument")).replace("_", "/")), ("Units", p.get("units")), ("Price", p.get("price")),
                     ("Stop", p.get("stop")), ("Target", p.get("tp")), ("Rating", p.get("rating")))

    def call(a):
        p = a["payload"]
        st = {"pending": "awaiting", "rejected": "rejected"}.get(a["status"])
        if a["status"] == "approved" and not any(t.get("instrument") == p.get("instrument") and abs((t.get("at") or 0) - (a.get("decided_ts") or 0)) < 300 for t in trades):
            st = "rejected"   # approved but refused or never filled
        return _item("call:" + _s(a["id"]), st, a.get("title"), a["status"], a.get("decided_ts") or a.get("ts"), facts(p), _s(p.get("reason"))) if st else None

    def done(t):
        return _item("trade:" + _s(t.get("trade_id") or t.get("_key")), "executed", f"{_s(t.get('instrument')).replace('_', '/')} {t.get('units')}", "filled",
                     t.get("at") or t.get("_ts"), facts(t) + _rows(("Trade ID", t.get("trade_id"))), _s(t.get("reason")))
    return stages, _each(apps, call) + _each(trades, done)


def youtube(store):
    stages = [("ready", "Waiting for upload"), ("review", "Unlisted · your review"), ("scheduled", "Scheduled"), ("public", "Public"), ("gone", "Deleted / private")]
    of = {"ready": "ready", "unlisted": "review", "scheduled": "scheduled", "public": "public", "deleted": "gone", "private": "gone"}

    def one(v):
        st, stats, src = of.get(v.get("status")), v.get("stats") or {}, v.get("source") or {}
        if not st:
            return None
        vid = v.get("video_id")
        return _item("short:" + _s(v.get("_key")), st, v.get("title"), f"{round(v.get('seconds') or 0)} s · {v.get('status')}", v.get("uploaded") or v.get("made") or v.get("_ts"),
                     _rows(("Channel", v.get("channel")), ("Format", "long video" if v.get("format") == "long" else "Short"), ("Kind", v.get("kind")),
                           ("Goes public", time.strftime("%a %d %b %H:%M", time.localtime(v["publish_at"])) if v.get("publish_at") and v.get("status") == "scheduled" else None), ("Views", stats.get("view") if vid else None), ("Likes", stats.get("like") if vid else None),
                           ("Comments", stats.get("comment") if vid else None), ("Mood", v.get("mood")), ("Voice", v.get("voice")), ("Music", v.get("music")),
                           ("Hashtags", " ".join(v.get("hashtags") or [])),
                           ("Story from", "original (fiction)" if v.get("original") else f"{v['classic']['title']} by {v['classic']['author']}" if v.get("classic") else src.get("from")), ("Footage", "; ".join(v.get("credits") or []))),
                     _s(v.get("script")), _links(("Watch", v.get("url")), ("YouTube Studio", f"https://studio.youtube.com/video/{vid}/edit" if vid else None), ("Source", src.get("url"))))
    return stages, _each(_kv(store, "yt_videos", 500), one)


def reports(store, master: str):
    try:
        with store._conn() as c:
            rows = [dict(r) for r in c.execute("SELECT id, ts, summary FROM master_reports WHERE master = ? ORDER BY ts DESC LIMIT 10", (master,)).fetchall()]
    except Exception:
        rows = []
    return [("reports", "Reports")], _each(rows, lambda r: _item("report:" + _s(r["id"]), "reports", r.get("summary"), "", r.get("ts")))


BUILDERS = {"web": web, "jobs": jobs, "email": email, "calendar": calendar, "trading": trading, "youtube": youtube}


def build(store, master_id: str) -> dict | None:
    try:
        cat = json.loads(CATALOG.read_text())["masters"]
    except Exception:
        cat = {}
    if master_id not in cat:
        return None
    if master_id in BUILDERS:
        stages, items = _safe(BUILDERS[master_id], store) or ([], [])
    elif master_id in REPORT_MASTERS:
        stages, items = reports(store, master_id)
    else:
        stages, items = [], []
    items = sorted(items, key=lambda i: i["ts"] or 0, reverse=True)[:LIMIT]
    return {"master": master_id, "name": cat[master_id].get("name", master_id),
            "stages": [{"id": i, "label": l, "count": sum(1 for it in items if it["stage"] == i)} for i, l in stages], "items": items}
