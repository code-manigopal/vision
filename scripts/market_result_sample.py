#!/usr/bin/env python3
"""A results video from a real filing, for Mani to judge before the channel's crew is wired in.

    .venv/bin/python scripts/market_result_sample.py TCS          ->  data/shorts/_sample/result-TCS.mp4
    .venv/bin/python scripts/market_result_sample.py TCS --reword    (let the writer model rephrase the lines; the default is the template wording, as the channel runs it)
    .venv/bin/python scripts/market_result_sample.py TCS --plain-mood    (no comic reactions)
    .venv/bin/python scripts/market_result_sample.py TCS --no-captions    (without the English captions burned in)
    .venv/bin/python scripts/market_result_sample.py HDFCBANK --mani    (Mani's cloned voice: about an hour, unload LM Studio's model first)
(--plain is still accepted and does nothing: plain is the default now.)

Reads the company's newest result from NSE (vision/services/nse.py) and what backs it (the company's press release or presentation, key ratios from the
filings, headlines about the result), builds the slides and the Tanglish lines (vision/masters/market.py), has the writer model find the company's reasons
and reword the lines when GROQ_API_KEY is set (code checks every reason), and renders the video
(vision/masters/slides.py). Uploads nothing. The voice is Edge's Tamil voice until Mani's own is cloned. The script
and the figures are written beside the video as result-<SYMBOL>.txt.
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
from datetime import datetime, timedelta  # noqa: E402

from vision.masters import fundamentals, market, market_crew, slides  # noqa: E402
from vision.services import filings_text, news, nse  # noqa: E402
from vision.services.llm import LLM  # noqa: E402

OUT = ROOT / "data" / "shorts" / "_sample"


async def main(symbol: str, reword: bool) -> None:
    async with httpx.AsyncClient(follow_redirects=True) as c:
        result = await nse.latest(c, symbol)
    if not result or not result["rows"]:
        sys.exit(f"NSE lists no result for {symbol}")
    llm = LLM(load_config())
    model = llm.writer_available()
    async with httpx.AsyncClient(follow_redirects=True) as c:
        f = await market_crew.optional(nse.fundamentals(c, symbol))
        key = market.key_ratios(fundamentals.ratios(f, None), bool(f["bank"])) if f and f["ttm"] else []
        docs = await market_crew.optional(market_crew.documents(c, symbol, result)) or []
        day = datetime.strptime(result["filed"][:11], "%d-%b-%Y").date()
        raw = await market_crew.optional(news.fetch_feed(c, news.google_news_between(f'("{market.short(result["name"])}" OR {symbol}) results', (day - timedelta(days=1)).isoformat(),
                                                                                   (day + timedelta(days=4)).isoformat()), 24 * 365)) or []
    heads = market.news_pick(raw, market.short(result["name"]), symbol, near=market.filed_ts(result))
    dropped, reasons = [], []
    if model and docs:
        text = "\n\n".join(f"[{d['subject']}, {market.dmy(d['at'][:10])}]\n{d['text']}" for d in docs)
        reasons = [{**r, "doc": {k: d[k] for k in ("subject", "at", "url")}} for r in await market.reasons(llm, result, text, dropped=dropped)
                   for d in [filings_text.source_of(r["quote"], docs)] if d]
    if model:
        for n, g in zip(heads, await market.news_gists(llm, heads, market.said_name(result))):
            n["gist"] = g
    print(f"documents: {[(d['kind'], d['subject'], d['at'][:10], d['url'], len(d['text'])) for d in docs]}")
    print(f"reasons kept: {len(reasons)}; dropped: {len(dropped)}")
    for r in reasons:
        print(f"  KEPT {r['metric']} {r['direction']}: {r['point']}\n       quote: {r['quote']}\n       say: {r['say']}")
    for it, why in dropped:
        print(f"  DROPPED ({why}): {it.get('metric') if isinstance(it, dict) else it} {str(it.get('point') if isinstance(it, dict) else '')[:90]}")
    print("ratios:", [(r["key"], round(r["value"], 2), r["note"]) for r in key])
    print(f"headlines: {len(raw)} read, kept: {[(n['source'], n['title'], bool(n.get('gist'))) for n in heads]}")
    print("  dropped:", [(i['source'], i['title'][:80]) for i in raw if i['title'] not in {n['title'] for n in heads}][:12])
    deck = market.deck(result, reasons=reasons, ratios=key, news=heads)
    said, kept = market.lines(result, deck, key), 0
    if reword and model:
        said, kept = await market.reword(llm, said, result)
    if "--plain-mood" not in sys.argv:                  # a comic reaction after the worst and the best figure
        said = market.react(said, result)
    work = OUT / f"result-{symbol}"
    pngs, faces, caps = draw(deck, said, work, captions="--no-captions" not in sys.argv, channel="Mani Market Tamil", source=market.source(result))
    spoken = await voice(said, work, "--mani" in sys.argv)
    final = slides.assemble(work, pngs, said, spoken, OUT / f"result-{symbol}{'-mani' if '--mani' in sys.argv else ''}.mp4", faces=faces, pause=PAUSE, captions=caps)
    (OUT / f"result-{symbol}.txt").write_text(
        f"{result['name']} · {result['quarter']} · {market.source(result)}\n{result['source']}\n\n"
        + "\n".join(f"{x['label']}: {market.shown(x['year'], x['unit'])} -> {market.shown(x['now'], x['unit'])}  (before: {market.shown(x['prev'], x['unit'])})" for x in result["rows"])
        + f"\n\nModel lines kept: {kept} of {len(said)}\n\n" + "\n".join(f"{ln['say']}\n    EN: {ln.get('en', '')}" for ln in said) + "\n", encoding="utf-8")
    for n, sl in enumerate(deck):                       # the slide numbers, so the frames can be found
        print(" slide", n, sl["kind"], sl["title"])
    print(f"{final}  ({slides.probe(final):.1f} s, model lines kept: {kept} of {len(said)})")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    asyncio.run(main((args or ["TCS"])[0].upper(), "--reword" in sys.argv))
