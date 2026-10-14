#!/usr/bin/env python3
"""A company-analysis video from real filings, for Mani to judge.

    .venv/bin/python scripts/market_analysis_sample.py ITC          ->  data/shorts/_sample/analysis-ITC.mp4
    .venv/bin/python scripts/market_analysis_sample.py HDFCBANK --reword    (let the writer model rephrase the lines; the default is the template wording)
    .venv/bin/python scripts/market_analysis_sample.py ITC --no-captions    (without the English captions burned in)
    .venv/bin/python scripts/market_analysis_sample.py ITC --mani    (Mani's cloned voice: about an hour, unload LM Studio's model first)
(--plain is still accepted and does nothing: plain is the default now.)

Reads the company's filings, shareholding and dividends from NSE and the share price from Yahoo (only a close at least 31 days old: SEBI's
rule for educational channels), works out the ratios (vision/masters/fundamentals.py), builds the slides and Tanglish lines
(vision/masters/market.py) and renders the video (vision/masters/slides.py) with Edge's Tamil voice. Uploads nothing. The figures,
sources and script are written beside the video as analysis-<SYMBOL>.txt.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.market_look_sample import PAUSE, draw, voice  # noqa: E402
from vision.config import load_config  # noqa: E402
from vision.masters import market, market_crew, slides  # noqa: E402
from vision.services.llm import LLM  # noqa: E402

OUT = ROOT / "data" / "shorts" / "_sample"


async def main(symbol: str, reword: bool) -> None:
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as c:
        f, rows, price = await market_crew.gather(c, symbol)
    if not f or len(rows) < market_crew.fundamentals.MIN_RATIOS:
        sys.exit(f"{symbol}: NSE gives too few figures for an analysis ({len(rows)} ratios)")
    deck = market.analysis_deck(f, rows)
    said, kept = market.analysis_lines(f, rows, deck), 0
    llm = LLM(load_config())
    if reword and llm.writer_available():
        said, kept = await market.reword(llm, said, f)
    said = market.react(said, f)
    work = OUT / f"analysis-{symbol}"
    pngs, faces, caps = draw(deck, said, work, captions="--no-captions" not in sys.argv, channel="Mani Market Tamil", source=market.analysis_source(f))
    mani = "--mani" in sys.argv
    final = slides.assemble(work, pngs, said, await voice(said, work, mani), OUT / f"analysis-{symbol}{'-mani' if mani else ''}.mp4", faces=faces, pause=PAUSE, captions=caps)
    (OUT / f"analysis-{symbol}.txt").write_text(
        f"{f['name']} · last 12 months to {f['ttm_to']} · balance sheet {f['as_of']} · {market.analysis_source(f)}\n"
        + "\n".join(f"{r['label']}: {market.shown(r['value'], r['unit'])} {r['unit']}  ({r['note']})" for r in rows)
        + "\n\nSources:\n" + "\n".join(f["sources"]) + "\nShareholding: NSE\n" + (f"Price as of {price['date']} (Yahoo Finance)\n" if price else "")
        + f"\nModel lines kept: {kept} of {len(said)}\n\n" + "\n".join(f"{ln['say']}\n    EN: {ln.get('en', '')}" for ln in said) + "\n", encoding="utf-8")
    print(f"{final}  ({slides.probe(final):.1f} s, {len(rows)} ratios, model lines kept: {kept} of {len(said)})")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    asyncio.run(main((args or ["ITC"])[0].upper(), "--reword" in sys.argv))
