"""Market data. All free.

- Indices and US/Canadian stock prices: Yahoo Finance chart endpoint (unofficial; no key; can change).
- Bitcoin and other crypto: CoinGecko (free Demo key optional: COINGECKO_API_KEY).
- FX for CAD conversion: Bank of Canada Valet API (official, no key).
"""

from __future__ import annotations

import asyncio

import httpx

from ..config import secret

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) VISION/0.4"}
INDICES = [("NIFTY 50", "^NSEI"), ("BANK NIFTY", "^NSEBANK"), ("NIFTY IT", "^CNXIT"), ("NYSE Composite", "^NYA"), ("NASDAQ Composite", "^IXIC")]
COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin",
                 "LTC": "litecoin", "DOT": "polkadot", "AVAX": "avalanche-2", "LINK": "chainlink", "MATIC": "matic-network", "USDC": "usd-coin"}


async def yahoo_change(client: httpx.AsyncClient, symbol: str) -> dict:
    """Last price and the change of the latest session vs the previous close."""
    r = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                         params={"range": "5d", "interval": "1d"}, headers=UA)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    closes = [c for c in (res["indicators"]["quote"][0].get("close") or []) if c is not None]
    price = res["meta"].get("regularMarketPrice") or (closes[-1] if closes else None)
    prev = closes[-2] if len(closes) >= 2 else res["meta"].get("chartPreviousClose")
    pct = (price / prev - 1) * 100 if price and prev else None
    return {"symbol": symbol, "price": price, "prev": prev, "pct": pct, "currency": res["meta"].get("currency")}


async def indices() -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await asyncio.gather(*(yahoo_change(client, s) for _, s in INDICES), return_exceptions=True)
    out = []
    for (name, sym), r in zip(INDICES, res):
        out.append({"name": name, "symbol": sym, "pct": None if isinstance(r, Exception) else r["pct"],
                    "price": None if isinstance(r, Exception) else r["price"]})
    if all(x["pct"] is None for x in out):
        raise RuntimeError("index prices unavailable")
    return out


async def stock_changes(symbols: list[str]) -> dict[str, float | None]:
    if not symbols:
        return {}
    async with httpx.AsyncClient(timeout=15) as client:
        res = await asyncio.gather(*(yahoo_change(client, s) for s in symbols), return_exceptions=True)
    return {s: (None if isinstance(r, Exception) else r["pct"]) for s, r in zip(symbols, res)}


async def crypto(ids: list[str]) -> dict[str, dict]:
    headers = dict(UA)
    key = secret("COINGECKO_API_KEY")
    if key:
        headers["x-cg-demo-api-key"] = key
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get("https://api.coingecko.com/api/v3/simple/price", headers=headers,
                             params={"ids": ",".join(ids), "vs_currencies": "usd,cad", "include_24hr_change": "true"})
        r.raise_for_status()
        return r.json()


async def fx_to_cad() -> dict[str, float]:
    """CAD per 1 unit of USD and INR, latest Bank of Canada daily rate (last good rate is cached)."""
    import json
    from ..config import ROOT
    cache = ROOT / "data" / "fx.json"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://www.bankofcanada.ca/valet/observations/FXUSDCAD,FXINRCAD/json", params={"recent": 1}, headers=UA)
            r.raise_for_status()
            obs = r.json()["observations"][0]
        fx = {"CAD": 1.0, "USD": float(obs["FXUSDCAD"]["v"]), "INR": float(obs["FXINRCAD"]["v"])}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(fx))
        return fx
    except Exception:
        if cache.exists():
            return json.loads(cache.read_text())
        raise
