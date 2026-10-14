#!/usr/bin/env python3
"""One video of every kind on the Mani Market Tamil channel, through the real production crew, uploaded PRIVATE for Mani to watch and judge (2026-10-14).

    nohup .venv/bin/python scripts/market_review_batch.py > data/shorts/_review/batch.out 2>&1 &

For each kind, shortest first: premarket Short, postmarket Short (the 14 Oct Indian session), lesson Short and lesson (mutual fund basics), a TCS result, an ITC analysis.
Each is made by ONE Director pass of the market crew with the channel's `review` option on: the real data, the cloned voice, the captions, cover, title and description as
production makes them; the Uploader puts the file up private with NO release time and raises NO approval (record status `review`). Nothing is scheduled, nothing is made
public, and the day's real jobs are not marked done. One line per video goes to data/shorts/_review/batch.log (and the screen).

Re-running continues: a kind already uploaded since the batch began is skipped, a finished video that failed to upload is uploaded without being made again, and the voice
of a half-made video comes from the crew's per-line cache. No new video is started between 20:45 and 07:00 local time (the service's own runs use the cloned voice at 21:32 and
23:00); the batch then logs "paused until the morning" and stops. A kind that cannot be made (TOO THIN, SKIPPED, data missing) is logged with the reason and the batch moves on;
the pre-market Short, which needs the US session closed, is tried again once at the end.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision.agents import Director  # noqa: E402
from vision.bus import EventBus, Store  # noqa: E402
from vision.config import load_config  # noqa: E402
from vision.masters import market_crew, youtube  # noqa: E402
from vision.services.llm import LLM  # noqa: E402

log = logging.getLogger("vision")
OUT = ROOT / "data" / "shorts" / "_review"
IST = market_crew.IST
KINDS = [("premarket", {"kind": "premarket"}), ("postmarket", {"kind": "postmarket"}), ("lesson_short", {"kind": "lesson_short", "topic": "mf-basics"}),
         ("lesson", {"kind": "lesson", "topic": "mf-basics"}), ("result", {"kind": "result", "symbol": "TCS"}), ("analysis", {"kind": "analysis", "symbol": "ITC"})]
SESSION = date(2026, 10, 14)                 # the Indian session the post-market Short is about
CUT_OFF, RESUME = dtime(20, 45), dtime(7, 0)


class LogBus(EventBus):
    """The bus of a script: what the crew says goes to the log."""

    def publish(self, event: dict) -> None:
        if event.get("type") in ("log", "notice"):
            log.info("bus: %s", event.get("msg") or event.get("text") or event)
        super().publish(event)


def stamp(text: str) -> str:
    line = f"{datetime.now():%Y-%m-%d %H:%M} | {text}"
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "batch.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)
    return line


def started() -> float:
    """When the batch began (kept in batch.json, so a re-run counts the videos already uploaded)."""
    p = OUT / "batch.json"
    if not p.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"start": time.time() - 60}))
    return json.loads(p.read_text())["start"]


def records(store, since: float, **want) -> list[dict]:
    return [v for v in store.kv_list(youtube.LOG) if v.get("channel") == "manimarket" and v.get("review") and (v.get("uploaded") or v.get("made") or 0) >= since
            and all(v.get(k) == x for k, x in want.items())]


def uploaded(store, since: float, kind: str) -> dict | None:
    return next((v for v in records(store, since, kind=kind) if v.get("video_id")), None)


def when_for(kind: str) -> datetime | None:
    """The clock the Scout and Analyst use. The post-market Short is about the 14 Oct session whatever the day it is made; the pre-market one is the next Indian morning's (07:10 IST),
    which is when its figures (US and Europe closed, Asia and GIFT Nifty fresh) are the news. None = the real clock."""
    if kind == "postmarket":
        return datetime.combine(SESSION, dtime(21, 30), IST)
    if kind == "premarket":
        now = datetime.now(IST)
        morning = datetime.combine(now.date(), dtime(7, 10), IST)
        return morning if morning > now else morning + timedelta(days=1)
    return None


def line_for(rec: dict, job: dict, notes: list[str]) -> str:
    dropped = [f"{d['name']} ({d['why']})" for d in (job.get("data") or {}).get("dropped") or []]
    if rec.get("lines_dropped"):
        dropped.append(f"{rec['lines_dropped']} of {rec.get('lines_proposed')} lesson lines dropped by the checks: {rec.get('dropped_why')}")
    qa = (rec.get("voice_qa") or {}).get("text") or "no voice check recorded"
    return (f"OK | {rec['kind']} | {rec['title']} | {youtube.clock(rec.get('seconds') or 0)} | https://youtu.be/{rec['video_id']} | "
            f"https://studio.youtube.com/video/{rec['video_id']}/edit | voice: {qa} | dropped/skipped: {'; '.join(dropped + notes) or 'none'}")


async def make(kind: str, force: dict, ch: dict, cfg, store, llm, bus, since: float, upload_only: bool = False) -> str:
    stages = market_crew.crew(ch)
    if upload_only:
        stages = [s for s in stages if s.name in ("UPLOAD", "REPORT")]
    director = Director(ch["director"], stages, reporter="Market Analytics")
    ctx = {"bus": bus, "store": store, "cfg": cfg, "llm": llm, "master": "youtube", "reason": "manual", "force": force}
    if when_for(kind):
        ctx["now"] = when_for(kind)
    try:
        res, sub = await director._pass(ctx)
    except Exception as e:  # noqa: BLE001
        log.exception("batch: %s", kind)
        return stamp(f"FAILED | {kind} | the crew raised {type(e).__name__}: {e}")
    rec = uploaded(store, since, kind)
    notes = [f"{n}: {r.label} {r.summary}" for n, r in sub["results"].items() if r.status in ("wait", "error") or r.label in ("SKIPPED", "NOTHING NEW")]
    if rec:
        return stamp(line_for(rec, sub.get("job") or {}, notes))
    why = "; ".join(notes) or "; ".join(f"{n}: {r.label}" for n, r in sub["results"].items())
    return stamp(f"NOT MADE | {kind} | {why}")


async def main() -> int:
    cfg = load_config()
    raw = next(c for c in cfg.master("youtube").options["channels"] if c.get("id") == "manimarket")
    ch = youtube.channel({**raw, "review": True, "voice_engine": "clone"})
    store, llm, bus, since = Store(ROOT / "data" / "vision.db"), LLM(cfg), LogBus(), started()
    todo, retried = list(KINDS), False
    stamp(f"batch started: {len(todo)} kinds, private uploads for review (no release time, no approval)")
    while todo:
        kind, force = todo.pop(0)
        if uploaded(store, since, kind):
            continue
        now = datetime.now().time()
        if now >= CUT_OFF or now < RESUME:
            left = [k for k, _ in [(kind, force), *todo] if not uploaded(store, since, k)]
            stamp(f"PAUSED | paused until the morning: not started: {', '.join(left)}; run the script again after {RESUME:%H:%M} to continue")
            return 0
        stamp(f"starting {kind}")
        pending = [v for v in records(store, since, kind=kind) if not v.get("video_id") and Path(v.get("file") or "").exists()]
        line = await make(kind, force, ch, cfg, store, llm, bus, since, upload_only=bool(pending))
        if kind == "premarket" and "NOT MADE" in line and not retried:
            retried = True
            todo.append((kind, force))                                  # the US session is still open: once more at the end
            stamp("premarket will be tried again at the end (it needs the US close)")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    sys.exit(asyncio.run(main()))
