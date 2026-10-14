#!/usr/bin/env python3
"""A long video's thumbnail for a few companies, to judge the look before the crew makes one.

    .venv/bin/python scripts/market_thumb_sample.py TCS HDFCBANK ICICIPRULI BAJFINANCE     ->  data/shorts/_sample/thumb-<SYMBOL>.jpg
    .venv/bin/python scripts/market_thumb_sample.py --lesson "Fixed deposit vs recurring deposit"      ->  data/shorts/_sample/thumb-lesson.jpg

The figures are MADE UP (profit +15.2 %, margin down) so the hook can be seen; only the logo is real: Wikimedia Commons' API is asked for it (GET, one second apart) and
the file is cached under data/logos/ with its licence. Uploads nothing.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision.masters import slides, thumbs  # noqa: E402
from vision.services import logos  # noqa: E402

NAMES = {"TCS": "Tata Consultancy Services Limited", "HDFCBANK": "HDFC Bank Limited", "ICICIPRULI": "ICICI Prudential Life Insurance Company Limited", "BAJFINANCE": "Bajaj Finance Limited"}
OUT = ROOT / "data" / "shorts" / "_sample"


def fake_result(name: str) -> dict:
    return {"name": name, "quarter": "Q2 FY27", "rows": [{"key": "profit", "now": 115.2, "year": 100.0, "unit": "cr"}, {"key": "opm", "now": 24.0, "year": 25.0, "unit": "pct"}]}


async def one(symbol: str) -> None:
    name = NAMES.get(symbol, symbol)
    result = fake_result(name)
    hook, tone = thumbs.result_hook(result)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as c:
        logo = await logos.find(c, symbol, name.replace(" Limited", ""))
    print(symbol, "|", thumbs.result_title(result), "|", f"logo: {logo['title']} {logo['licence']} {logo['source']}" if logo else "no logo")
    OUT.mkdir(parents=True, exist_ok=True)
    slides.thumbnail(OUT / f"_thumb-{symbol}", OUT / f"thumb-{symbol}.jpg", hook, name.replace(" Limited", ""), (logo or {}).get("path", ""), "Mani Market Tamil", "Q2 FY27 RESULTS", tone)
    print("  ->", OUT / f"thumb-{symbol}.jpg", (OUT / f"thumb-{symbol}.jpg").stat().st_size, "bytes", "| credit:", logos.credit(logo) or "-")


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["--lesson"]:
        title = args[1] if len(args) > 1 else "Fixed deposit vs recurring deposit"
        hook, tone = thumbs.lesson_hook(title)
        OUT.mkdir(parents=True, exist_ok=True)
        slides.thumbnail(OUT / "_thumb-lesson", OUT / "thumb-lesson.jpg", hook, "Deposits", "", "Mani Market Tamil", "FINANCE BASICS", tone)
        print(hook, "->", OUT / "thumb-lesson.jpg")
        return
    for n, sym in enumerate(args or list(NAMES)):
        if n:
            import time
            time.sleep(1)
        asyncio.run(one(sym.upper()))


if __name__ == "__main__":
    main()
