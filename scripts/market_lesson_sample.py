#!/usr/bin/env python3
"""A finance lesson (or lesson Short) from the official pages, for Mani to judge before the crew's schedule makes one.

    .venv/bin/python scripts/market_lesson_sample.py fd-vs-rd               ->  data/shorts/_sample/lesson-fd-vs-rd.mp4 (+ .txt)
    .venv/bin/python scripts/market_lesson_sample.py mf-basics
    .venv/bin/python scripts/market_lesson_sample.py fd-vs-rd --short       ->  a lesson Short (vertical, 5-8 lines)
    .venv/bin/python scripts/market_lesson_sample.py fd-vs-rd --videos ID1,ID2     (also read these public videos' transcripts as raw material; no sign-in, no cookies)
    .venv/bin/python scripts/market_lesson_sample.py fd-vs-rd --model openai/gpt-oss-20b     (another Groq model for the English lesson: its daily allowance is separate)
    .venv/bin/python scripts/market_lesson_sample.py fd-vs-rd --tamil-model qwen/qwen3.8-27b  (the model that speaks the English lines as Tanglish; this is the default)
    .venv/bin/python scripts/market_lesson_sample.py fd-vs-rd --min-kept 6        (accept fewer kept lines than the crew would, to see a weaker model's lesson)
    .venv/bin/python scripts/market_lesson_sample.py fd-vs-rd --lenient           (do not refuse book Tamil: only to see what a weaker model writes)
    .venv/bin/python scripts/market_lesson_sample.py fd-vs-rd --no-captions        (without the English captions burned in)
    .venv/bin/python scripts/market_lesson_sample.py --list                (the topic ids)

Fetches the topic's official pages now (GET only, a few seconds apart), has the writer model (Groq, GROQ_API_KEY) plan the slides and write the lesson in English, keeps only the lines
that pass lessons.check_en, has the Tanglish model speak them (lessons.check_ta) and renders the video with Edge's Tamil voice (never the cloned one). Uploads nothing. Beside the video the .txt lists the sources, the transcripts read,
how many lines were proposed, kept and dropped (and why), and the script with each line's English caption and quote.
"""

from __future__ import annotations

import asyncio
import csv
import io
import sys
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.market_look_sample import PAUSE, draw, voice  # noqa: E402
from vision.bus import Store  # noqa: E402
from vision.config import load_config  # noqa: E402
from vision.masters import lessons, market, market_crew, slides  # noqa: E402
from vision.services import yt_transcripts  # noqa: E402
from vision.services.llm import LLM  # noqa: E402

OUT = ROOT / "data" / "shorts" / "_sample"


def cached(llm) -> None:
    """Answers the writer gave for a prompt are kept in data/shorts/_sample/_llm_cache.json and reused, so changing a check and running again costs no tokens (Groq's free day is 200,000)."""
    import hashlib
    import json
    path = OUT / "_llm_cache.json"
    store = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    real = llm.json

    async def json_(prompt, **kw):
        key = hashlib.sha1((prompt + str(kw.get("model"))).encode()).hexdigest()
        if key not in store:
            store[key] = await real(prompt, **kw)
            path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
        return store[key]
    llm.json = json_


async def patient(llm, *args, model=None, ta_model=None):
    """lessons.write, waiting out Groq's per-day allowance (shared with the running VISION) in two-minute steps for up to 40 minutes: a sample is worth the wait, the crew's own run is not."""
    for n in range(20):
        try:
            return await lessons.write(llm, *args, model=model, ta_model=ta_model)
        except lessons.Busy as e:
            print(f"writer allowance spent ({str(e)[:60]}); waiting 2 minutes ({n + 1}/20)", flush=True)
            await asyncio.sleep(120)
    raise SystemExit("the writer's allowance did not come back")


async def main(tid: str, short: bool, videos: list[str], captions: bool, model: str | None, min_kept: int = 0, ta_model: str | None = lessons.TA_MODEL) -> int:
    tp = next((t for t in lessons.TOPICS if t["id"] == tid), None)
    if not tp:
        print("no such topic; try --list")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as c:
        pages = await lessons.fetch_sources(c, tp)
        r = await c.get(market_crew.INDEX_URL, headers={"User-Agent": "Mozilla/5.0"})
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿")))) if r.status_code == 200 else []
    bad = lessons.bad_pattern([x.get("Company Name", "") for x in rows], [x.get("Symbol", "").upper() for x in rows if x.get("Symbol")])
    print(f"sources: {[(p['label'], len(p['text'])) for p in pages]} of {len(tp['sources'])}")
    if not pages:
        print("NO SOURCE")
        return 1
    transcripts = []
    if videos:
        db = OUT / "lesson-state.db"
        db.unlink(missing_ok=True)
        transcripts = await yt_transcripts.read(Store(db), [{"id": v, "title": v, "channel": "?"} for v in videos], cap=len(videos))
        db.unlink(missing_ok=True)
        print(f"transcripts: asked {len(videos)}, read {len(transcripts)}")
    llm = LLM(load_config())
    if not llm.writer_available():
        print("no writer model (GROQ_API_KEY)")
        return 1
    cached(llm)
    if "--lenient" in sys.argv:
        import re
        lessons.BOOKISH = re.compile(r"(?!x)x")                                  # a weaker model cannot speak the host's Tamil: show what it writes, the crew would refuse these lines
    if min_kept:
        lessons.MIN_KEPT = lessons.MIN_KEPT_SHORT = min_kept                  # a sample may be judged on fewer lines than the crew would accept
    out = await patient(llm, tp, pages, transcripts, bad, short, model=model, ta_model=ta_model)
    why = Counter(d["why"] for d in out["dropped"])
    print(f"title: {out['title']}\nwriter tokens used: {out['tokens']}\nEnglish lines proposed {out['proposed']}, verified {out['kept_en']}; Tanglish kept {out['steps']}; final {out['kept']}, "
          f"dropped {len(out['dropped'])}: {dict(why.most_common(6))}\nnew words for the voice: {out['new_words']}")
    for d in out["dropped"]:
        print(f"  DROPPED ({d['why']}): {d['en']}" + (f"\n      {d['say']}" if d["say"] else ""))
    print("angle:", out["angle"] or "none")
    if out["too_thin"]:
        print("TOO THIN (or no plan): no video")
        return 1
    deck, said = out["deck"], out["lines"]
    name = f"lesson-{tid}{'-short' if short else ''}"
    work = OUT / name
    frame = {"top": market.SHORT_NOTE} if short else {"source": "Finance basics"}
    pngs, faces, caps = draw(deck, said, work, tall=short, captions=captions, channel="Mani Market Tamil", **frame)
    spoken = await voice(said, work)                                       # Edge's voice only
    final = slides.assemble(work, pngs, said, spoken, OUT / f"{name}.mp4", faces=faces, pause=PAUSE, captions=caps, **({"size": slides.TALL} if short else {}))
    (OUT / f"{name}.txt").write_text(
        f"{tp['title']} · sources:\n" + "\n".join(f"  {p['label']}: {p['url']}" for p in pages)
        + f"\n\ntranscripts read: {[(t['id'], t['title']) for t in transcripts] or 'none'}\nEnglish lines proposed {out['proposed']}, verified {out['kept_en']}, {out['steps']}, kept {out['kept']}, "
        f"dropped {len(out['dropped'])}: {dict(why)}\nwriter tokens: {out['tokens']}\nnew words for the voice (check by ear): {out['new_words']}\n"
        + "\nDropped:\n" + "\n".join(f"  ({d['why']}) {d['en']}" + (f"  /  {d['say']}" if d["say"] else "") for d in out["dropped"])
        + "\n\nScript:\n" + "\n".join(f"{ln['say']}\n    EN: {ln.get('en', '')}" + (f"\n    QUOTE: {' | '.join(ln['quotes'])}" if ln.get("quotes") else "") for ln in said) + "\n", encoding="utf-8")
    print(f"{final}  ({slides.probe(final):.1f} s, {len(said)} lines)")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("\n".join(f"{t['id']:22} {t['title']}" for t in lessons.TOPICS))
        sys.exit(0)
    args = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] not in ("--videos", "--model", "--min-kept", "--tamil-model")]
    if not args:
        sys.exit("usage: market_lesson_sample.py <topic id> [--short] [--videos ID,ID] [--no-captions]  (--list shows the ids)")
    vids = sys.argv[sys.argv.index("--videos") + 1].split(",") if "--videos" in sys.argv else []
    sys.exit(asyncio.run(main(args[0], "--short" in sys.argv, vids, "--no-captions" not in sys.argv, sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else None,
                             int(sys.argv[sys.argv.index("--min-kept") + 1]) if "--min-kept" in sys.argv else 0,
                             sys.argv[sys.argv.index("--tamil-model") + 1] if "--tamil-model" in sys.argv else lessons.TA_MODEL)))
