"""Run the E-books Manager by hand (VISION itself does this every hour when it is running).

  .venv/bin/python scripts/ebook_run.py [runs]

Runs the master up to `runs` times (default 12), stopping early when the day's free Cloudflare allowance is used or
the book waits for your yes. Uses the real store (data/vision.db) and files (data/ebooks/).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vision.bus import EventBus, Store  # noqa: E402
from vision.config import ROOT, load_config  # noqa: E402
from vision.masters import build_masters  # noqa: E402
from vision.services import cfai  # noqa: E402
from vision.services.llm import LLM  # noqa: E402


async def main(runs: int) -> None:
    cfg = load_config()
    m = next(x for x in build_masters(cfg) if x.id == "ebooks")
    m.services.update(cfg=cfg, llm=LLM(cfg))
    store, bus = Store(ROOT / "data" / "vision.db"), EventBus()
    for i in range(runs):
        report = await m.cycle(bus, store, reason="manual")
        agents = {a["name"]: a for a in bus.state["masters"]["ebooks"]["agents"]}
        print(f"run {i + 1}: {report}  ·  neurons used today {cfai.used(store):.0f}", flush=True)
        for a in agents.values():
            if a["status"] == "error":
                print(f"   {a['name']}: {a['summary']}", flush=True)
        if any(a["label"] == "RESTING" for a in agents.values()) or "waiting for your yes" in report or any(a["status"] == "error" for a in agents.values()):
            break


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 12))
