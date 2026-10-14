"""Company results as filed with the NSE (read-only, GET only, no account).

    filings(client, "TCS")   the company's results filings, newest first (NSE's integrated-filing list, from March 2025 on)
    parse(xml)               one filing (XBRL) -> the period and every figure it states, in rupees as filed
    latest(client, "TCS")    the newest result with the quarter before and the same quarter a year ago, as rows to show
    recent(client)           the results filed market-wide most recently, newest first (the same list with no symbol asked for)
    calendar(client)         board meetings announced to consider results (what is coming, and when)
    fundamentals(client, s)  the last four quarters summed, the balance sheet, the fiscal years and the year's cash flow, from the filings
    shareholding(client, s)  the newest promoter / public holding;  dividends(client, s, today)  dividend per share declared in the last year
    announcements(client, s) what the company filed with the exchange (press releases, presentations, board outcomes), newest first

A filing states one period only, so a comparison means reading the earlier filings too. Nothing here is computed
beyond what the filing gives, except: a bank's net interest income (interest earned less interest expended), a
company's operating profit (profit before exceptional items and tax, plus finance costs and depreciation, less
other income) and its margin. A company is read from its consolidated filing; a bank from its standalone one, the
only one that states its bad loans. NSE's own site is what a person would read in a browser; this asks it a few times a
day, never in a loop.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import httpx

API = "https://www.nseindia.com/api/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "application/json", "Referer": "https://www.nseindia.com/companies-listing/corporate-integrated-filing"}
CRORE = 1e7

# (key, label, unit, tags tried in order); unit cr = rupees shown in crore, pct = a percentage as filed, rs = rupees
COMPANY = [("revenue", "Revenue", "cr", ("RevenueFromOperations",)),
           ("opm", "Operating margin", "pct", ()),
           # the owners' share of the profit is the figure the company, the press and its EPS go by; the whole period's profit only when a filing lacks it
           ("profit", "Net Profit", "cr", ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForPeriod")),
           ("eps", "EPS", "rs", ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsLossPerShareFromContinuingOperations"))]
BANK = [("nii", "Net Interest Income", "cr", ()),
        ("op", "Operating Profit", "cr", ("OperatingProfitBeforeProvisionAndContingencies",)),
        ("provisions", "Provisions", "cr", ("ProvisionsOtherThanTaxAndContingencies",)),
        ("profit", "Net Profit", "cr", ("ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates", "ProfitLossForThePeriod")),
        ("gnpa", "Gross NPA", "pct", ("PercentageOfGrossNpa",)),
        ("nnpa", "Net NPA", "pct", ("PercentageOfNpa",))]
LOWER_IS_BETTER = {"provisions", "gnpa", "nnpa"}


def quarter(end: date) -> str:
    """30 Sep 2026 -> "Q2 FY27" (the Indian financial year ends in March)."""
    return f"Q{(end.month - 4) % 12 // 3 + 1} FY{(end.year + (1 if end.month > 3 else 0)) % 100:02d}"


def _day(text: str) -> date:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip().title() if "-" in text and not text[:4].isdigit() else text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {text!r}")


async def _get(client: httpx.AsyncClient, url: str, **params) -> httpx.Response:
    r = await client.get(url, params=params or None, headers=UA, timeout=30.0)
    r.raise_for_status()
    return r


async def filings(client: httpx.AsyncClient, symbol: str) -> list[dict]:
    r = await _get(client, API + "integrated-filing-results", index="equities", symbol=symbol.upper(), type="Integrated Filing- Financials")
    return _listed(r, symbol)


def _listed(r: httpx.Response, symbol: str = "") -> list[dict]:
    rows = (r.json() or {}).get("data") or []
    out = [{"symbol": x.get("symbol") or symbol.upper(), "name": x.get("smName") or x.get("cmName") or symbol, "end": _day(x["qe_Date"]),
            "consolidated": (x.get("consolidated") or "").lower().startswith("consol"), "audited": x.get("audited") or "",
            "filed": x.get("broadcast_Date") or "", "xbrl": x.get("xbrl") or ""}
           for x in rows if x.get("qe_Date") and str(x.get("xbrl") or "").endswith(".xml")]
    return sorted(out, key=lambda f: (f["end"], f["filed"]), reverse=True)


async def recent(client: httpx.AsyncClient) -> list[dict]:
    """Results filed market-wide lately (NSE answers the same list with no symbol: about the last day's filings), newest first by filing time."""
    r = await _get(client, API + "integrated-filing-results", index="equities", type="Integrated Filing- Financials")
    out = _listed(r)
    return sorted(out, key=lambda f: filed_at(f["filed"]), reverse=True)


def filed_at(text: str) -> datetime:
    try:
        return datetime.strptime(text[:20].strip().title(), "%d-%b-%Y %H:%M:%S")
    except ValueError:
        return datetime.min


def parse(xml: str) -> dict:
    """The figures a filing states for its own period: {bank, name, start, end, v: {tag: number}}."""
    plain = {i: dict(re.findall(r"<xbrli:(startDate|endDate|instant)>([\d-]+)", body))
             for i, body in re.findall(r'<xbrli:context id="([\w-]+)">(.*?)</xbrli:context>', xml, re.S) if "Member" not in body}
    facts = re.findall(r'<[\w-]+:(\w+)\s[^>]*contextRef="([\w-]+)"[^>]*>([^<]+)<', xml)
    spans = [i for i, p in plain.items() if "startDate" in p]
    if not spans:
        return {"bank": False, "name": "", "start": None, "end": None, "v": {}}
    # the quarter itself, not the year so far: the period that ends last and starts latest (the first such in the file)
    one = max(spans, key=lambda i: (plain[i]["endDate"], plain[i]["startDate"], -spans.index(i)))
    start, end = plain[one]["startDate"], plain[one]["endDate"]
    text = {t: v.strip() for t, c, v in facts if c == one}
    v: dict[str, float] = {}
    for t, c, raw in facts:
        if c == one or plain.get(c, {}).get("instant") == end:
            try:
                v.setdefault(t, float(raw))
            except ValueError:
                pass
    if (ex := excise(xml, start, end)) is not None:
        v["ExciseDuty"] = ex
    return {"bank": "NameOfBank" in text or "InterestEarned" in v, "name": text.get("NameOfBank") or text.get("NameOfTheCompany") or "",
            "start": start, "end": end, "v": v}


def excise(xml: str, start: str, end: str) -> float | None:
    """Excise duty for the period start..end, which a filing lists as a described line inside "other expenses" (a company that pays it, like ITC),
    or None when it lists none. Revenue from operations is stated gross of it."""
    spans = {i: tuple(re.findall(r"<xbrli:(?:startDate|endDate)>([\d-]+)", body)) for i, body in re.findall(r'<xbrli:context id="([\w-]+)">(.*?)</xbrli:context>', xml, re.S)}
    facts = re.findall(r'<[\w-]+:(\w+)\s[^>]*contextRef="([\w-]+)"[^>]*>([^<]+)<', xml)
    num = {(t, c): v for t, c, v in facts}
    total = None
    for t, c, v in facts:
        if t == "DescriptionOfOtherExpenses" and re.search(r"excise", v, re.I) and spans.get(c) == (start, end):
            try:
                total = (total or 0.0) + float(num[("OtherExpenses", c)])
            except (KeyError, ValueError):
                pass
    return total


def _op(v: dict) -> float:
    """Operating profit: profit before exceptional items and tax, plus finance costs and depreciation, less other income."""
    return v["ProfitBeforeExceptionalItemsAndTax"] + v.get("FinanceCosts", 0.0) + v.get("DepreciationDepletionAndAmortisationExpense", 0.0) - v.get("OtherIncome", 0.0)


def _value(f: dict | None, key: str, tags: tuple) -> float | None:
    if not f:
        return None
    v = f["v"]
    if key == "nii":
        return v["InterestEarned"] - v["InterestExpended"] if {"InterestEarned", "InterestExpended"} <= v.keys() else None
    if key == "opm":
        need = ("ProfitBeforeExceptionalItemsAndTax", "RevenueFromOperations")
        if not all(k in v for k in need) or not v["RevenueFromOperations"]:
            return None
        return round(100 * _op(v) / v["RevenueFromOperations"], 1)
    got = next((v[t] for t in tags if t in v), None)
    if key in ("gnpa", "nnpa"):                       # filed as a fraction (0.0117); a consolidated bank filing leaves it at zero
        return round(got * 100, 2) if got else None
    return got


def rows(now: dict, prev: dict | None, year: dict | None) -> list[dict]:
    """The figures to show, each with the quarter before and the same quarter a year ago where those filings were read."""
    out = []
    for key, label, unit, tags in (BANK if now["bank"] else COMPANY):
        cur = _value(now, key, tags)
        if cur is None:
            continue
        out.append({"key": key, "label": label, "unit": unit, "now": cur, "prev": _value(prev, key, tags), "year": _value(year, key, tags),
                    "lower_is_better": key in LOWER_IS_BETTER})
    return out


async def latest(client: httpx.AsyncClient, symbol: str) -> dict | None:
    """The newest result for a company, or None when NSE lists no filing for it."""
    listed = await filings(client, symbol)
    if not listed:
        return None
    head = next((f for f in listed if f["end"] == listed[0]["end"] and f["consolidated"]), listed[0])
    same = [f for f in listed if f["consolidated"] == head["consolidated"]]
    back = {12: date(head["end"].year - 1, head["end"].month, head["end"].day)}
    m = head["end"].month - 3
    back[3] = date(head["end"].year - (m <= 0), m + 12 * (m <= 0), 31 if (m + 12 * (m <= 0)) in (3, 12) else 30)

    async def read(f: dict | None) -> dict | None:
        return parse((await _get(client, f["xbrl"])).text) if f else None
    now = await read(head)
    alone = next((f for f in listed if f["end"] == head["end"] and not f["consolidated"]), None)
    if now["bank"] and head["consolidated"] and alone:  # a bank states its bad loans only in the standalone filing
        head, same = alone, [f for f in listed if not f["consolidated"]]
        now = await read(head)
    prev, year = [await read(next((f for f in same if f["end"] == back[k]), None)) for k in (3, 12)]
    return {"symbol": head["symbol"], "name": now["name"] or head["name"], "bank": now["bank"], "end": head["end"].isoformat(),
            "quarter": quarter(head["end"]), "year_ago": quarter(back[12]), "before": quarter(back[3]), "consolidated": head["consolidated"],
            "audited": head["audited"], "filed": head["filed"], "source": head["xbrl"], "rows": rows(now, prev, year)}


async def calendar(client: httpx.AsyncClient) -> list[dict]:
    r = await _get(client, API + "event-calendar")
    return [{"symbol": x.get("symbol"), "name": x.get("company"), "date": _day(x["date"]).isoformat(), "purpose": x.get("purpose") or ""}
            for x in r.json() or [] if "result" in (x.get("purpose") or "").lower() and x.get("date")]



# ---- fundamentals: what the filings say about a whole company, not one quarter -------------------------------------------------

EPS_TAGS = COMPANY[3][3]
PROFIT_TAGS = ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForPeriod") + BANK[3][3]       # owners' share first, else the whole profit
# balance-sheet names -> the tags that state them (instant figures at the period end); a bank has no "Equity" tag, it states Capital and ReservesAndSurplus
BALANCE = {"equity": ("Equity",), "owners": ("EquityAttributableToOwnersOfParent",), "capital": ("EquityShareCapital", "Capital"),
           "reserves": ("OtherEquity", "ReservesAndSurplus"), "borrow_nc": ("BorrowingsNoncurrent",), "borrow_c": ("BorrowingsCurrent",),
           "assets": ("Assets",), "cash": ("CashAndCashEquivalents",), "paid": ("PaidUpValueOfEquityShareCapital",), "face": ("FaceValueOfEquityShareCapital",)}
CAPEX = ("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
         "PurchaseOfIntangibleAssetsUnderDevelopment")
_FACT = re.compile(r'<[\w-]+:(\w+)\s[^>]*contextRef="([\w-]+)"[^>]*>([^<]+)<')
DPS = re.compile(r"dividend\b[^-]*-\s*(?:rs|re)\.?\s*([\d.]+)", re.I)


def _contexts(xml: str) -> dict:
    return {i: dict(re.findall(r"<xbrli:(startDate|endDate|instant)>([\d-]+)", body))
            for i, body in re.findall(r'<xbrli:context id="([\w-]+)">(.*?)</xbrli:context>', xml, re.S) if "Member" not in body}


def parse_year(xml: str) -> dict | None:
    """The figures a filing states for its whole financial year (a context of a year or so, ending when the filing's period does), or None
    when it states none (a quarter or half-year filing): {start, end, v}. v also holds the instant figures at that date."""
    plain = _contexts(xml)
    spans = [i for i, p in plain.items() if "startDate" in p and (_day(p["endDate"]) - _day(p["startDate"])).days >= 350]
    if not spans:
        return None
    one = max(spans, key=lambda i: (plain[i]["endDate"], -spans.index(i)))
    end = plain[one]["endDate"]
    v: dict[str, float] = {}
    for t, c, raw in _FACT.findall(xml):
        if c == one or plain.get(c, {}).get("instant") == end:
            try:
                v.setdefault(t, float(raw))
            except ValueError:
                pass
    if (ex := excise(xml, plain[one]["startDate"], end)) is not None:
        v["ExciseDuty"] = ex
    return {"start": plain[one]["startDate"], "end": end, "v": v}


def leases(xml: str) -> float | None:
    """Lease liabilities, which a filing lists inside "other financial liabilities" under a description line, not under a tag of their own."""
    facts = _FACT.findall(xml)
    num = {(t, c): v for t, c, v in facts}
    total = None
    for t, c, v in facts:
        if t.startswith("DescriptionOf") and "lease liabilit" in v.lower() and not c.startswith("PY"):
            try:
                total = (total or 0.0) + float(num[(t[len("DescriptionOf"):], c)])
            except (KeyError, ValueError):
                pass
    return total


def _get_any(v: dict, tags: tuple) -> float | None:
    return next((v[t] for t in tags if t in v), None)


def _figures(p: dict) -> dict:
    """What one quarter adds to a twelve-month sum (None for a figure the filing does not state)."""
    v = p["v"]
    if p["bank"]:
        return {"nii": _value(p, "nii", ()), "profit": _get_any(v, BANK[3][3]), "eps": _get_any(v, EPS_TAGS),
                "pbt": _get_any(v, ("ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitBeforeExtraordinaryItemsAndTax"))}
    ok = "ProfitBeforeExceptionalItemsAndTax" in v
    return {"revenue": v.get("RevenueFromOperations"), "excise": v.get("ExciseDuty"), "op": _op(v) if ok else None, "profit": _get_any(v, PROFIT_TAGS), "eps": _get_any(v, EPS_TAGS),
            "pbt": _get_any(v, ("ProfitBeforeTax", "ProfitBeforeExceptionalItemsAndTax")), "fin": v.get("FinanceCosts"),
            "dep": v.get("DepreciationDepletionAndAmortisationExpense"), "tax": v.get("TaxExpense")}


def _sum(quarters: list[dict]) -> dict:
    return {k: (sum(q[k] for q in quarters) if all(q.get(k) is not None for q in quarters) else None) for k in quarters[0]}


def _balance(v: dict, bank: bool) -> dict:
    b = {k: _get_any(v, tags) for k, tags in BALANCE.items()}
    if b["owners"] is None:                             # no minority interest is stated: the equity is the owners'
        b["owners"] = b["equity"] if b["equity"] is not None else (b["capital"] + b["reserves"] if None not in (b["capital"], b["reserves"]) else None)
    if b["equity"] is None:
        b["equity"] = b["owners"]
    if bank:
        b["borrow_nc"] = b["borrow_c"] = None
    b["shares"] = b["paid"] / b["face"] if b["paid"] and b["face"] else None
    return b


def _has_balance(p: dict) -> bool:
    return "Equity" in p["v"] or ("Capital" in p["v"] and "ReservesAndSurplus" in p["v"])


async def fundamentals(client: httpx.AsyncClient, symbol: str) -> dict | None:
    """Everything the filings say about a company as a whole, or None when NSE lists none. Missing pieces are None, never guessed.

    ttm / prev: the last four quarters summed, and the four before them when eight consecutive quarters are listed. bs: the balance sheet of
    the newest filing that has one (the half-year or annual one), bs_open the same a year earlier. years: fiscal years from the annual
    (March) filings, newest first. cf: operating cash flow and capital spending of the newest year. A company is read from its consolidated
    filings, as latest() does."""
    listed = await filings(client, symbol)
    if not listed:
        return None
    flag = next((f for f in listed if f["end"] == listed[0]["end"] and f["consolidated"]), listed[0])["consolidated"]
    by_end: dict[date, dict] = {}
    for f in listed:
        if f["consolidated"] == flag:
            by_end.setdefault(f["end"], f)
    ends = sorted(by_end, reverse=True)
    chain = [ends[0]]
    for e in ends[1:]:                                    # consecutive quarters only: a gap ends the run
        if (chain[-1].year - e.year) * 12 + chain[-1].month - e.month != 3:
            break
        chain.append(e)
    read: dict[date, tuple[str, dict]] = {}

    async def get(end: date) -> dict:
        if end not in read:
            xml = (await _get(client, by_end[end]["xbrl"])).text
            read[end] = (xml, parse(xml))
        return read[end][1]
    for e in chain[:4]:
        await get(e)
    head = read[ends[0]][1]
    bank = head["bank"]
    quarters = [_figures(read[e][1]) for e in chain[:4]]
    ttm = _sum(quarters) if len(chain) >= 4 else None
    prev = None
    if len(chain) >= 8:
        for e in chain[4:8]:
            await get(e)
        prev = _sum([_figures(read[e][1]) for e in chain[4:8]])
    as_of = None
    for e in ends[:8]:                                    # the newest filing that states a balance sheet
        if _has_balance(await get(e)):
            as_of = e
            break
    bs = _balance(read[as_of][1]["v"], bank) if as_of else {}
    if as_of and not bank:
        bs["leases"] = leases(read[as_of][0])
    if bs.get("shares") is None and ttm:                  # the newest quarter states the share capital too
        bs["shares"] = _balance(head["v"], bank)["shares"]
    opened = None
    before = date(as_of.year - 1, as_of.month, as_of.day) if as_of else None
    if before in by_end and await get(before) and _has_balance(read[before][1]):
        opened = {"owners": _balance(read[before][1]["v"], bank)["owners"], "end": before.isoformat()}
    years, cf = [], None
    for e in [e for e in ends if e.month == 3][:4]:
        got = parse_year(read[e][0]) if e in read or await get(e) else None
        if not got:
            continue
        v = got["v"]
        years.append({"end": got["end"], "revenue": v.get("RevenueFromOperations"), "excise": v.get("ExciseDuty"), "profit": _get_any(v, PROFIT_TAGS),
                      "disc": v.get("ProfitLossFromDiscontinuedOperationsAfterTax")})
        if cf is None and "CashFlowsFromUsedInOperatingActivities" in v:
            capex = [v[t] for t in CAPEX if t in v]
            cf = {"end": got["end"], "cfo": v["CashFlowsFromUsedInOperatingActivities"], "capex": sum(capex) if capex and CAPEX[0] in v else None}
    return {"symbol": by_end[ends[0]]["symbol"], "name": head["name"] or by_end[ends[0]]["name"], "bank": bank, "consolidated": flag,
            "as_of": as_of.isoformat() if as_of else None, "ttm_to": chain[0].isoformat() if len(chain) >= 4 else None, "ttm": ttm, "prev": prev,
            "bs": bs, "bs_open": opened, "years": years, "cf": cf,
            "sources": [by_end[e]["xbrl"] for e in sorted(read, reverse=True)]}


async def announcements(client: httpx.AsyncClient, symbol: str) -> list[dict]:
    """Everything the company has filed as an announcement, newest first: {subject, text, url, at (ISO), kb (attachment size, None when NSE gives none)}.
    `subject` is NSE's category ("Press Release", "Investor Presentation", "Outcome of Board Meeting"); `text` is the filing's own one-line description."""
    r = await _get(client, API + "corporate-announcements", index="equities", symbol=symbol.upper())
    out = []
    for x in r.json() or []:
        at = filed_at(x.get("an_dt") or "")
        size = re.match(r"([\d.]+)\s*(KB|MB)", x.get("attFileSize") or "", re.I)
        if at == datetime.min or not str(x.get("attchmntFile") or "").startswith("http"):
            continue
        out.append({"subject": (x.get("desc") or "").strip(), "text": re.sub(r"\s+", " ", x.get("attchmntText") or "").strip(), "url": x["attchmntFile"],
                    "at": at.isoformat(), "kb": float(size[1]) * (1024 if size[2].upper() == "MB" else 1) if size else None})
    return sorted(out, key=lambda a: a["at"], reverse=True)


async def shareholding(client: httpx.AsyncClient, symbol: str) -> dict | None:
    """The newest shareholding pattern: {promoter, public} in percent and its date."""
    r = await _get(client, API + "corporate-share-holdings-master", index="equities", symbol=symbol.upper())
    rows = [x for x in r.json() or [] if x.get("date") and x.get("pr_and_prgrp") not in (None, "")]
    if not rows:
        return None
    top = max(rows, key=lambda x: _day(x["date"]))
    try:
        return {"promoter": float(top["pr_and_prgrp"]), "public": float(top.get("public_val") or 0), "date": _day(top["date"]).isoformat()}
    except ValueError:
        return None


async def dividends(client: httpx.AsyncClient, symbol: str, today: date, days: int = 365) -> dict | None:
    """Dividend per share declared (ex-date) in the last `days`: {per_share, count}. None when NSE answers with no corporate actions at all."""
    r = await _get(client, API + "corporates-corporateActions", index="equities", symbol=symbol.upper())
    rows = r.json() or []
    if not rows:
        return None
    total, n = 0.0, 0
    for x in rows:
        try:
            ex = _day(x.get("exDate") or "")
        except ValueError:
            continue
        if 0 <= (today - ex).days < days:
            for amount in DPS.findall(x.get("subject") or ""):
                try:
                    total, n = total + float(amount.rstrip(".")), n + 1
                except ValueError:
                    pass
    return {"per_share": total, "count": n}
