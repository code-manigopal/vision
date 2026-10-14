#!/usr/bin/env python3
"""A pre-market or post-market Short from live figures, for Mani to judge before the crew's schedule runs it.

    .venv/bin/python scripts/market_report_sample.py premarket            ->  data/shorts/_sample/report-premarket.mp4 (+ .txt)
    .venv/bin/python scripts/market_report_sample.py postmarket --any-time
    .venv/bin/python scripts/market_report_sample.py postmarket --any-time --date 2026-10-13     (judge the figures as they stood at 18:00 IST that day)
    .venv/bin/python scripts/market_report_sample.py premarket --any-time --no-captions            (without the English captions burned in)
    .venv/bin/python scripts/market_report_sample.py premarket --any-time --mani                   (Mani's cloned voice: unload LM Studio's model first)

Fetches the indices now (services/world.py: Yahoo Finance and NSE, GET only), applies the freshness rule (an index older than expected is LEFT OUT and
named below), builds the tall slides and the template lines (masters/market.py, no model) and renders the video with Edge's Tamil voice (slides.py).
Without --any-time it keeps the real window (07:00-08:15 / 18:00-20:30 IST) and the NSE trading-day check, like the crew. Uploads nothing.
The .txt beside the video holds the figures with their as-of times, the indices dropped as stale, and the script.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.market_look_sample import PAUSE, draw, voice  # noqa: E402
from vision.masters import market, market_crew, slides  # noqa: E402
from vision.services import world  # noqa: E402

OUT = ROOT / "data" / "shorts" / "_sample"


async def main(kind: str, any_time: bool, day: date | None) -> int:
    now = datetime.combine(day, time(18, 0), world.IST) if day else datetime.now(world.IST)
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as c:
        if not any_time:
            if market_crew.report_window(now) != kind:
                print(f"not the {kind} window now ({now:%H:%M} IST); use --any-time for a sample")
                return 1
            if not world.trading_day(now.date(), await world.trading_holidays(c)):
                print(f"{now:%a %d %b} is not an NSE trading day; use --any-time for a sample")
                return 1
        data = await world.collect(c, market_crew.REPORTS[kind], now)
    print("dropped as stale:", [f"{d['name']}: {d['why']}" for d in data["dropped"]] or "none")
    for r in data["regions"]:
        print(f"{r['label']:7} {world.when(r)}: " + ", ".join(f"{i['name']} {i['last']:,.2f} ({i['pct']:+.2f}%, {i['session']}, {i['day']:%d %b})" for i in r["items"]))
    if data["skip"]:
        print("NO SHORT:", data["skip"])
        return 1
    deck = market.report_deck(kind, data)
    said = market.report_react(market.report_lines(kind, data, deck))
    work = OUT / f"report-{kind}"
    pngs, faces, caps = draw(deck, said, work, tall=True, captions="--no-captions" not in sys.argv, channel="Mani Market Tamil", top=market.SHORT_NOTE)
    mani = "--mani" in sys.argv
    from vision.voice import clone                                   # a Short is spoken a little slower; --speed tries another pace
    speed = float(sys.argv[sys.argv.index("--speed") + 1]) if "--speed" in sys.argv else clone.SHORT_SPEED
    spoken = await voice(said, work, mani, speed)
    final = slides.assemble(work, pngs, said, spoken, OUT / f"report-{kind}{'-mani' if mani else ''}.mp4", faces=faces, pause=PAUSE, size=slides.TALL, captions=caps)
    (OUT / f"report-{kind}.txt").write_text(
        f"{kind} · {data['date']} · generated {now:%Y-%m-%d %H:%M} IST\n\n"
        + "\n".join(f"{r['label']} ({world.when(r)}): " + "; ".join(f"{i['name']} {i['last']:,.2f} {i['pct']:+.2f}% [{i['session']}, {i['day']}, as of {i['as_of']:%d %b %H:%M %z}]" for i in r["items"]) for r in data["regions"])
        + "\n\nLeft out as stale:\n" + ("\n".join(f"  {d['name']}: {d['why']}" for d in data["dropped"]) or "  none")
        + "\n\nScript:\n" + "\n".join(f"{ln['say']}\n    EN: {ln.get('en', '')}" for ln in said) + "\n", encoding="utf-8")
    print(f"{final}  ({slides.probe(final):.1f} s, {len(said)} lines)")
    return 0


if __name__ == "__main__":
    args = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] not in ("--date", "--speed")]
    given = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else ""
    kind = next((a for a in args if a in market_crew.REPORTS), "")
    if not kind:
        sys.exit("usage: market_report_sample.py premarket|postmarket [--any-time] [--date YYYY-MM-DD]")
    sys.exit(asyncio.run(main(kind, "--any-time" in sys.argv, date.fromisoformat(given) if given else None)))
