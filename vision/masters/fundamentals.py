"""Ratios for a company analysis: plain arithmetic on what services/nse.fundamentals read from the filings (no I/O, no model).

    ratios(f, price)      the ratios a company (or a bank) has figures for, each {key, group, label, value, unit, note}
    lagged(closes, today) the closing price SEBI's rule allows, and the year's high and low ending on that same day

`value` is in the unit's own terms: cr = rupees as filed (market.shown divides by a crore), pct = a percentage, x = times, rs = rupees.
A ratio whose inputs are missing is left out, never filled in. Screener's own constructs (intrinsic value, industry PE, PEG) are not here.
SEBI's rule (from 1 July 2026): an education-only creator may not use a named stock's price data from the preceding 30 days. The price here
is always `price_lag_days` (31) or more old, and so are its 52-week high and low.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..services.nse import shape

GROUPS = {"size": "Size & Profit", "efficiency": "Efficiency", "balance": "Balance Sheet", "valuation": "Valuation"}
MIN_RATIOS = 8                  # fewer than this and the company is not filmed
MIN_FINANCIAL = 7               # a bank, lender or insurer has fewer kinds of ratio to give (no debt, margin or cash readings), so the bar is one lower
MIN_YEAR_DAYS = 150             # a high and a low need about this many trading days behind them


def lagged(closes: list[tuple[date, float]], today: date, lag_days: int = 31) -> dict | None:
    """The close on the last trading day at or before today - lag_days, with its date, and the high and low of the year ending that day.
    Nothing newer than the lag is read: those closes are dropped before anything else is done."""
    old = [(d, c) for d, c in closes if d <= today - timedelta(days=lag_days) and c]
    if not old:
        return None
    day, price = max(old)
    year = [c for d, c in old if day - timedelta(days=365) < d <= day]
    return {"price": price, "date": day.isoformat(), "high": max(year) if len(year) >= MIN_YEAR_DAYS else None,
            "low": min(year) if len(year) >= MIN_YEAR_DAYS else None}


def minimum(f: dict) -> int:
    """How many ratios a company needs before it is filmed: MIN_RATIOS, or MIN_FINANCIAL for a bank, lender, insurer or other NBFC-form company."""
    return MIN_RATIOS if shape(f) == "company" else MIN_FINANCIAL


def _div(a: float | None, b: float | None) -> float | None:
    return None if a is None or not b else a / b


def _fy(end: str) -> str:
    return f"FY{int(end[2:4]) + (end[5:7] > '03'):02d}"


def net_revenue(p: dict) -> tuple[float | None, bool]:
    """Revenue from operations less the excise duty the filing lists, and whether that was taken off. Revenue is stated gross of excise duty, a
    cost that passes through for a company like ITC, so a margin or a growth rate on the gross figure is not comparable with one on net sales."""
    rev = p.get("revenue")
    return (rev - p["excise"], True) if rev is not None and p.get("excise") else (rev, False)


def growth(f: dict, key: str) -> tuple[float | None, str]:
    """Percent change of a figure: the last twelve months against the twelve before when eight quarters are listed, else the latest fiscal year
    against the one before. The note says which, and that revenue is as filed or net of excise duty (when both periods list it). key is revenue, premium or profit."""
    t, p, y = f.get("ttm") or {}, f.get("prev") or {}, f.get("years") or []
    if t.get(key) is not None and p.get(key):
        net = key == "revenue" and net_revenue(t)[1] and net_revenue(p)[1]
        a, b = (net_revenue(t)[0], net_revenue(p)[0]) if net else (t[key], p[key])
        return 100 * (a - b) / abs(b), "last 12 months vs the 12 before" + (", net of excise duty" if net else ", as filed" if key == "revenue" else "")
    ykey = key if key in ("revenue", "premium") else "profit"
    if len(y) >= 2 and y[0].get(ykey) is not None and y[1].get(ykey):
        net = ykey == "revenue" and net_revenue(y[0])[1] and net_revenue(y[1])[1]
        a, b = (net_revenue(y[0])[0], net_revenue(y[1])[0]) if net else (y[0][ykey], y[1][ykey])
        extra = ", net of excise duty" if net else ", as filed" if ykey == "revenue" else ""
        if ykey == "profit" and (y[0].get("disc") or y[1].get("disc")):
            extra = ", includes profit from discontinued operations"
        return 100 * (a - b) / abs(b), f"{_fy(y[0]['end'])} vs {_fy(y[1]['end'])}{extra}"
    return None, ""


def ratios(f: dict, price: dict | None = None) -> list[dict]:
    """The ratios a company has figures for, by how its form is read (nse.shape): company | plain | bank | lender | life | general.

    A company gets everything. An NBFC-form company that does not lend (plain) gets no operating margin, ROCE, debt, EV/EBITDA: its finance costs are not
    a cost to add back. A bank or lender: net interest income, ROE, ROA, book value, no ROCE, debt or margin (net interest margin is left out: the filings
    state no average earning assets to divide by). An insurer: premium, profit, ROE, book value and the solvency ratio (a general insurer also its combined
    ratio), no ROCE, ROA, debt, margin or EV/EBITDA, since its assets and borrowings are policyholders' funds and its trade."""
    t, b, sh = f.get("ttm") or {}, f.get("bs") or {}, shape(f)
    bank, ins = sh in ("bank", "lender"), sh in ("life", "general")
    out: list[dict] = []

    def add(key, group, label, value, unit, note=""):
        if value is not None:
            out.append({"key": key, "group": group, "label": label, "value": value, "unit": unit, "note": note})
    shares, owners = b.get("shares"), b.get("owners")
    profit, assets = t.get("profit"), b.get("assets")
    # size and profit
    if bank:
        add("nii" if sh == "bank" else "lnii", "size", "Net interest income", t.get("nii" if sh == "bank" else "lnii"), "cr",
            "last 12 months" if sh == "bank" else "interest income less finance costs, last 12 months")
    elif ins:
        add("ttm_premium", "size", "Net premium income" if sh == "life" else "Gross premium written", t.get("premium"), "cr",
            ("net premium income" if sh == "life" else "gross premium written") + ", last 12 months")
    else:
        add("ttm_revenue", "size", "Revenue", t.get("revenue"), "cr", "as filed, last 12 months" + (", before excise duty is taken off" if t.get("excise") else ""))
    add("ttm_profit", "size", "Net profit", profit, "cr", "last 12 months, owners' share")
    if sh in ("company", "plain"):
        rev, net = net_revenue(t)                       # a margin on revenue that is net of excise duty where the filings list it
        basis = ("operating profit / revenue net of excise duty" if net else "operating profit / revenue as filed") + ", last 12 months"
        if sh == "company":
            add("opm", "size", "Operating margin", _pct(t.get("op"), rev), "pct", basis)
        add("npm", "size", "Net margin", _pct(profit, rev), "pct", basis.replace("operating profit", "profit"))
    add("eps", "size", "EPS", t.get("eps") if t.get("eps") is not None else _div(profit, shares), "rs", "last 12 months")
    if sh in ("company", "plain"):
        g, note = growth(f, "revenue")
        add("rev_growth", "size", "Revenue growth", g, "pct", note)
    elif ins:
        g, note = growth(f, "premium")
        add("prem_growth", "size", "Premium growth", g, "pct", note)
    g, note = growth(f, "profit")
    add("profit_growth", "size", "Profit growth", g, "pct", note + (", includes one-offs" if g is not None and "discontinued" not in note else ""))
    # efficiency
    opening = (f.get("bs_open") or {}).get("owners")
    equity = (owners + opening) / 2 if owners is not None and opening is not None else owners
    add("roe", "efficiency", "ROE", _pct(profit, equity), "pct", "profit / " + ("average equity" if opening is not None and owners is not None else "closing equity"))
    debt = b["borrow_nc"] + b["borrow_c"] if b.get("borrow_nc") is not None and b.get("borrow_c") is not None else None
    if sh == "company":
        ebit = t["pbt"] + t["fin"] if t.get("pbt") is not None and t.get("fin") is not None else None
        add("roce", "efficiency", "ROCE", _pct(ebit, b["equity"] + debt) if b.get("equity") is not None and debt is not None else None, "pct",
            "EBIT / (equity + borrowings)")
    if not ins:
        add("roa", "efficiency", "Return on assets", _pct(profit, assets), "pct", "profit / total assets")
    if sh in ("company", "plain"):
        add("turnover", "efficiency", "Asset turnover", _div(t.get("revenue"), assets), "x", "revenue / total assets")
    last = f.get("latest") or {}                        # an insurer's regulatory figures are the newest quarter's, as filed (a figure outside a real one's range is already left out)
    if ins:
        add("solvency", "efficiency", "Solvency ratio", last.get("solvency"), "pct", f"as filed, as on {f.get('latest_end')}")
        add("combined", "efficiency", "Combined ratio", last.get("combined"), "pct", "as filed, latest quarter")
    # balance sheet
    add("reserves", "balance", "Reserves", b.get("reserves"), "cr", f"as on {f.get('as_of')}")
    if sh == "company":
        add("debt", "balance", "Total debt", debt, "cr", "borrowings; lease liabilities not added")
        add("leases", "balance", "Lease liabilities", b.get("leases"), "cr", "shown apart from debt")
        add("de", "balance", "Debt to equity", _div(debt, owners), "x", "borrowings / equity")
        add("cash", "balance", "Cash", b.get("cash"), "cr", "cash and equivalents")
    bv = _div(owners, shares)
    add("bv", "balance", "Book value per share", bv, "rs", "equity / number of shares")
    sh_ = f.get("shareholding") or {}
    add("promoter", "balance", "Promoter holding", sh_.get("promoter"), "pct", f"as of {sh_.get('date')}")
    cf = f.get("cf") or {}
    if sh in ("company", "plain") and cf.get("cfo") is not None:
        add("cfo", "balance", "Operating cash flow", cf["cfo"], "cr", f"year to {cf['end']}")
        add("fcf", "balance", "Free cash flow", cf["cfo"] - cf["capex"] if cf.get("capex") is not None else None, "cr", "operating cash flow less capital spending")
    # valuation: the lagged price only
    if price:
        p, day = price["price"], price["date"]
        mcap = p * shares if shares else None
        add("price", "valuation", "Share price", p, "rs", f"close on {day}")
        add("mcap", "valuation", "Market cap", mcap, "cr", f"price on {day} x shares")
        eps = out_value(out, "eps")
        add("pe", "valuation", "P/E", _div(p, eps) if eps and eps > 0 else None, "x", "price / last 12 months EPS")
        add("pb", "valuation", "Price to book", _div(p, bv) if bv and bv > 0 else None, "x", "price / book value")
        dps = (f.get("dividend") or {}).get("per_share")
        add("dyield", "valuation", "Dividend yield", 100 * dps / p if dps is not None and p else None, "pct", "dividends declared in the last year / price")
        add("high", "valuation", "52-week high", price.get("high"), "rs", f"year to {day}")
        add("low", "valuation", "52-week low", price.get("low"), "rs", f"year to {day}")
        ebitda = t.get("op")
        if sh == "company" and mcap and debt is not None and b.get("cash") is not None and ebitda and ebitda > 0:
            add("ev", "valuation", "EV / EBITDA", (mcap + debt - b["cash"]) / ebitda, "x", "(market cap + debt - cash) / operating profit")
    return out


def _pct(a: float | None, b: float | None) -> float | None:
    r = _div(a, b)
    return None if r is None else 100 * r


def out_value(rows: list[dict], key: str) -> float | None:
    return next((r["value"] for r in rows if r["key"] == key), None)
