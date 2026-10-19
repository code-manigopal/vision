#!/usr/bin/env python3
"""A Know IDK Things Short made by the real crew (Scout -> Editor), for Mani to judge a look before it goes live.

    .venv/bin/python scripts/short_sample.py science        ->  data/shorts/_sample/short-science.mp4
    .venv/bin/python scripts/short_sample.py money
    .venv/bin/python scripts/short_sample.py story
    .venv/bin/python scripts/short_sample.py space cosmicroadster        (any channel: kind, then its id)
    .venv/bin/python scripts/short_sample.py space cosmicroadster --motion   (the fully animated style, `style: motion`; -> ...-motion.mp4)

Uses a throwaway database (data/shorts/_sample/sample.db), so nothing is counted, marked used, uploaded or scheduled; the channel's
own settings from config.yaml, with the day's mix set to the one kind asked for and its animated diagrams switched on. Needs
GROQ_API_KEY (writing), PEXELS_API_KEY (footage) and the local voices, like the channel itself.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision.bus import EventBus, Store  # noqa: E402
from vision.config import load_config  # noqa: E402
from vision.masters import youtube  # noqa: E402
from vision.services.llm import LLM  # noqa: E402

OUT = ROOT / "data" / "shorts" / "_sample"


async def main(kind: str, channel_id: str = "knowidk", style: str = "") -> None:
    cfg = load_config()
    raw = next(c for c in cfg.master("youtube").options["channels"] if c.get("id") == channel_id)
    ch = youtube.channel({**raw, "daily_mix": {kind: 1}, "mix_auto": False, "diagrams": [kind], "trends": False, "viewer_comments": False,
                          "drive_folder": "", **({"style": style} if style else {}), "classics": [] if kind != "story" else raw.get("classics", []), "quick": {"per_day": 0}})
    OUT.mkdir(parents=True, exist_ok=True)
    db = OUT / "sample.db"
    db.unlink(missing_ok=True)
    llm = (youtube.OwnWriter(LLM(cfg), ch["writer_model"], ch["id"], int(ch.get("groq_daily_cap") or 0), ch.get("light_tier") or "", ch.get("script_writer") or "")
           if ch.get("writer_model") else LLM(cfg))                       # writes exactly as the channel's Director does
    ctx = {"store": Store(db), "bus": EventBus(), "cfg": cfg, "llm": llm, "options": {}, "results": {}, "master": "youtube"}
    for stage in youtube.crew(ch)[:-2]:                 # everything up to the Editor: no upload, no analytics
        for agent in stage.agents:
            res = await agent.run(ctx)
            print(f"{agent.name}: {res.label} · {res.summary}")
            if res.status == "error" or (agent.name == "Story Scout" and not ctx.get("job")):
                return
    job = ctx["job"]
    dest = OUT / f"short-{channel_id + '-' if channel_id != 'knowidk' else ''}{kind}{'-' + style if style else ''}.mp4"
    shutil.copyfile(job["file"], dest)
    shutil.rmtree(job["dir"], ignore_errors=True)       # its working folder is under the channel's own; the sample keeps only the copy
    print(f"\n{dest}  ({job['seconds']} s)  diagrams: {job.get('diagrams')}  style: {job.get('style', 'footage')}")
    for sc in (job.get("motion") or {}).get("plan", []):
        print("  ", sc["beat"], sc["type"], {k: v for k, v in sc.items() if v and k not in ("beat", "type")})


if __name__ == "__main__":                              # short_sample.py <kind> [channel id]: e.g. "space cosmicroadster"
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    asyncio.run(main(args[0] if args else "science", args[1] if len(args) > 1 else "knowidk", "motion" if "--motion" in sys.argv else ""))
