#!/usr/bin/env python3
"""A Know IDK Things Short made by the real crew (Scout -> Editor), for Mani to judge a look before it goes live.

    .venv/bin/python scripts/short_sample.py science        ->  data/shorts/_sample/short-science.mp4
    .venv/bin/python scripts/short_sample.py money
    .venv/bin/python scripts/short_sample.py story

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


async def main(kind: str) -> None:
    cfg = load_config()
    raw = next(c for c in cfg.master("youtube").options["channels"] if c.get("id") == "confessions")
    ch = youtube.channel({**raw, "daily_mix": {kind: 1}, "mix_auto": False, "diagrams": [kind], "trends": False, "viewer_comments": False,
                          "drive_folder": "", "classics": [] if kind != "story" else raw.get("classics", []), "quick": {"per_day": 0}})
    OUT.mkdir(parents=True, exist_ok=True)
    db = OUT / "sample.db"
    db.unlink(missing_ok=True)
    ctx = {"store": Store(db), "bus": EventBus(), "cfg": cfg, "llm": LLM(cfg), "options": {}, "results": {}, "master": "youtube"}
    for stage in youtube.crew(ch)[:-2]:                 # everything up to the Editor: no upload, no analytics
        for agent in stage.agents:
            res = await agent.run(ctx)
            print(f"{agent.name}: {res.label} · {res.summary}")
            if res.status == "error" or (agent.name == "Story Scout" and not ctx.get("job")):
                return
    job = ctx["job"]
    dest = OUT / f"short-{kind}.mp4"
    shutil.copyfile(job["file"], dest)
    shutil.rmtree(job["dir"], ignore_errors=True)       # its working folder is under the channel's own; the sample keeps only the copy
    print(f"\n{dest}  ({job['seconds']} s)  diagrams: {job.get('diagrams')}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "science"))
