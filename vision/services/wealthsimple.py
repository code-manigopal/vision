"""Wealthsimple holdings from the CSV you export (Documents -> custom statement -> Holdings report, CSV).

Drop the file into  inbox/wealthsimple/  (any name). VISION uses the newest holdings CSV.
Prices are refreshed live between exports (Yahoo for stocks/ETFs, CoinGecko for crypto),
so the daily P&L stays current even if the CSV is a few days old.
Column names are matched loosely, so small changes in Wealthsimple's export don't break it.
"""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path

CRYPTO_HINT = {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "DOT", "AVAX", "LINK", "MATIC", "USDC"}


def _num(v: str | None) -> float:
    if v is None:
        return 0.0
    s = str(v).replace("$", "").replace(",", "").replace("CAD", "").replace("USD", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return 0.0


def _col(headers: list[str], *wanted: str, avoid: tuple[str, ...] = ()) -> str | None:
    low = {h: h.lower().strip() for h in headers}
    for w in wanted:
        for h, l in low.items():
            if w in l and not any(a in l for a in avoid):
                return h
    return None


def _rows(path: Path) -> tuple[list[str], list[dict]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    # some exports have a title line or two before the header row
    start = next((i for i, l in enumerate(lines[:10]) if "symbol" in l.lower() and "quantity" in l.lower()), 0)
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    return reader.fieldnames or [], [r for r in reader if any((v or "").strip() for v in r.values())]


def is_holdings_csv(path: Path) -> bool:
    try:
        headers, _ = _rows(path)
    except Exception:
        return False
    h = " ".join(headers).lower()
    return "symbol" in h and "quantity" in h and ("market value" in h or "book value" in h)


def latest_holdings_csv(folder: Path) -> Path | None:
    files = sorted(folder.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return next((p for p in files if is_holdings_csv(p)), None)


def read_holdings(path: Path) -> dict:
    headers, rows = _rows(path)
    c_sym = _col(headers, "symbol")
    c_name = _col(headers, "name", avoid=("account",))
    c_qty = _col(headers, "quantity")
    c_mv = _col(headers, "market value", avoid=("currency",))
    c_mv_ccy = _col(headers, "market value currency", "market price currency", "currency")
    c_bv = _col(headers, "book value (cad)", "book value", avoid=("currency",))
    c_acct = _col(headers, "account type", "account name", "account")
    c_type = _col(headers, "security type", "asset type", "type", avoid=("account",))
    c_exch = _col(headers, "exchange", "mic")
    out = []
    for r in rows:
        sym = (r.get(c_sym) or "").strip().upper()
        if not sym:
            continue
        acct = (r.get(c_acct) or "").strip()
        stype = (r.get(c_type) or "").strip().lower()
        crypto = "crypto" in stype or "crypto" in acct.lower() or sym in CRYPTO_HINT
        ccy = (r.get(c_mv_ccy) or "CAD").strip().upper()[:3] or "CAD"
        out.append({"symbol": sym, "name": (r.get(c_name) or "").strip(), "qty": _num(r.get(c_qty)),
                    "value": _num(r.get(c_mv)), "ccy": ccy, "book_cad": _num(r.get(c_bv)), "account": acct,
                    "exchange": (r.get(c_exch) or "").strip().upper(), "crypto": crypto})
    return {"file": path.name, "exported": path.stat().st_mtime, "age_days": (time.time() - path.stat().st_mtime) / 86400,
            "positions": out}


def yahoo_symbol(p: dict) -> str | None:
    """Wealthsimple symbol -> Yahoo symbol for live prices."""
    if p["crypto"]:
        return None
    if p["ccy"] == "CAD" or p["exchange"] in ("TSX", "XTSE", "TSXV", "XTSX", "NEO", "NEOE"):
        return p["symbol"].replace(".", "-") + ".TO"
    return p["symbol"].replace(".", "-")
