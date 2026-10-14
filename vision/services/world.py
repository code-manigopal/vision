"""World indices for Mani Market Tamil's pre-market and post-market Shorts (read-only, GET only, no account, no key).

    index_move(res, name, now)         one Yahoo chart answer -> last, previous close, change, percent, the day it is from and whether the session is live
    gift_nifty(status)                 GIFT Nifty from NSE's marketStatus;  nse_indices(all)  Nifty 50 / Bank Nifty and the advances / declines from NSE's allIndices
    fresh_day(kind, region, today)     the session day an index must be from to be shown;  assemble(...)  the regions, with every stale index left out
    trading_day(d, holidays)           Monday to Friday and not on NSE's holiday list (kept a week in kv);  collect(...)  fetches it all

Freshness is the rule that keeps the Shorts honest: an index whose newest figure is older than expected is LEFT OUT and named in `dropped`, never shown
as if current. Yahoo's `chartPreviousClose` is the close before the whole 5-day range, so it is never used: the change is the last close (or the live
price) against the previous daily close from the series itself.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from . import nse
from .markets import UA

IST = ZoneInfo("Asia/Kolkata")
HOLIDAYS = "mm_hol"
LIVE_AGE = 2100                         # a quote older than this (seconds) inside the session is not live (Yahoo delays Kospi by 20 minutes)
GIFT_AGE = 3 * 3600                     # GIFT Nifty's newest print must be this recent
FLAT = 0.05                             # percent: a move smaller than this is "about the same"
# key: (Yahoo symbol, name on the slide, name for the spoken line, region)
INDICES = {"spx": ("^GSPC", "S&P 500", "S&P 500", "us"), "dji": ("^DJI", "Dow Jones", "Dow Jones", "us"), "ixic": ("^IXIC", "Nasdaq", "Nasdaq", "us"),
           "ftse": ("^FTSE", "FTSE 100", "FTSE", "europe"), "dax": ("^GDAXI", "DAX", "DAX", "europe"), "cac": ("^FCHI", "CAC 40", "CAC", "europe"),
           "n225": ("^N225", "Nikkei 225", "Nikkei", "asia"), "ks11": ("^KS11", "Kospi", "Kospi", "asia"), "hsi": ("^HSI", "Hang Seng", "Hang Seng", "asia"),
           "nifty": ("^NSEI", "Nifty 50", "Nifty", "india"), "sensex": ("^BSESN", "Sensex", "Sensex", "india"), "banknifty": ("^NSEBANK", "Bank Nifty", "Bank Nifty", "india")}
REGIONS = {"pre": ["us", "europe", "asia", "india"], "post": ["india", "asia", "europe"]}      # the order they are told in
LABEL = {"us": "US", "europe": "Europe", "asia": "Asia", "india": "India"}
KINDS = {"premarket": "pre", "postmarket": "post"}


def index_move(res: dict, name: str, now: float) -> dict | None:
    """One Yahoo chart result (range 5d, interval 1d) as a move. None when the series cannot give a last and a previous close."""
    meta, rmt = res.get("meta") or {}, (res.get("meta") or {}).get("regularMarketTime")
    try:
        zone = ZoneInfo(meta["exchangeTimezoneName"])
    except (KeyError, ValueError, OSError):
        zone = timezone(timedelta(seconds=meta.get("gmtoffset") or 0))
    close = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    bars = [(datetime.fromtimestamp(t, zone).date(), c) for t, c in zip(res.get("timestamp") or [], close) if c is not None]
    if not bars or not rmt:
        return None
    reg, seen = (meta.get("currentTradingPeriod") or {}).get("regular") or {}, datetime.fromtimestamp(rmt, zone)
    live = reg.get("start", 1) <= rmt <= reg.get("end", 0) and 0 <= now - rmt <= LIVE_AGE
    if live:                                            # the live price against the last daily close before today's session
        before = [c for d, c in bars if d < seen.date()]
        if not before or not meta.get("regularMarketPrice"):
            return None
        last, prev, day, as_of = float(meta["regularMarketPrice"]), before[-1], seen.date(), seen
    else:                                               # the last two daily closes; chartPreviousClose is the close before the range, not this one
        if meta.get("regularMarketPrice") and bars[-1][0] < seen.date():
            # Yahoo leaves the day's own bar empty for hours after the close (seen 14 Oct 2026: Nikkei, Kospi, Hang Seng closed, their 14 Oct close
            # None, regularMarketPrice already the close): the day's close is regularMarketPrice, against the last bar before that day
            bars = bars + [(seen.date(), float(meta["regularMarketPrice"]))]
        if len(bars) < 2:
            return None
        (day, last), prev = bars[-1], bars[-2][1]
        as_of = seen if seen.date() == day else datetime.combine(day, datetime.min.time(), zone)
    return _move(name, last, prev, day, as_of, "live" if live else "closed")


def _move(name: str, last: float, prev: float, day: date, as_of: datetime, session: str, **more) -> dict:
    return {"name": name, "last": last, "prev_close": prev, "change": last - prev, "pct": (last / prev - 1) * 100 if prev else 0.0,
            "day": day, "as_of": as_of, "session": session, **more}


def gift_nifty(status: dict) -> dict | None:
    """GIFT Nifty from NSE's marketStatus (`giftnifty`: LASTPRICE, DAYCHANGE, PERCHANGE, TIMESTMP "14-Oct-2026 07:03")."""
    g = (status or {}).get("giftnifty") or {}
    try:
        at = datetime.strptime(g["TIMESTMP"].strip().title(), "%d-%b-%Y %H:%M").replace(tzinfo=IST)
        last, change = float(g["LASTPRICE"]), float(g["DAYCHANGE"])
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    return {"name": "GIFT Nifty (SGX Nifty)", "last": last, "prev_close": last - change, "change": change, "pct": float(g.get("PERCHANGE") or 0), "day": at.date(), "as_of": at, "session": "live"}


def nse_indices(all_indices: dict) -> dict[str, dict]:
    """Nifty 50 and Bank Nifty from NSE's allIndices (last, variation, percentChange, previousClose, advances, declines) under keys nifty / banknifty."""
    try:
        at = datetime.strptime(all_indices["timestamp"].strip().title(), "%d-%b-%Y %H:%M").replace(tzinfo=IST)
    except (KeyError, ValueError, TypeError, AttributeError):
        return {}
    out = {}
    for key, nse_name in (("nifty", "NIFTY 50"), ("banknifty", "NIFTY BANK")):
        x = next((r for r in all_indices.get("data") or [] if r.get("index") == nse_name), None)
        if x:
            out[key] = {"name": INDICES[key][1], "last": float(x["last"]), "prev_close": float(x["previousClose"]), "change": float(x["variation"]), "pct": float(x["percentChange"]),
                        "day": at.date(), "as_of": at, "session": "closed" if (at.hour, at.minute) >= (15, 30) else "live",
                        "advances": int(x["advances"]) if str(x.get("advances", "")).isdigit() else None, "declines": int(x["declines"]) if str(x.get("declines", "")).isdigit() else None}
    return out


def previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d


def fresh_day(kind: str, region: str, today: date) -> date:
    """The session day an index of this region must be from. Before India opens the US and Europe are told by their last weekday session; Asia (open by
    then) and, in the evening, India, Asia and Europe (mid-session) by today's."""
    return previous_weekday(today) if kind == "pre" and region in ("us", "europe") else today


def assemble(kind: str, today: date, moves: dict[str, dict | None], gift: dict | None = None, now: datetime | None = None) -> dict:
    """The regions to tell, in order, each {id, label, session, as_of, items}; `dropped` names every index left out and why; `skip` is why there is no Short.

    `moves` holds the index moves by key (INDICES). Pre-market needs a fresh GIFT Nifty; post-market needs Nifty 50 and Sensex. A region with no fresh index
    is dropped and fewer than two regions means no Short."""
    now, dropped, regions = now or datetime.now(IST), [], []
    pre = kind == "pre"
    if pre:
        keep = gift if gift and gift["day"] == today and timedelta(0) <= now - gift["as_of"] <= timedelta(seconds=GIFT_AGE) else None
        if gift and not keep:
            dropped.append({"name": "GIFT Nifty", "why": f"last print {gift['as_of']:%d %b %H:%M} IST is not recent"})
        gift = keep
    for rid in REGIONS[kind]:
        if rid == "india" and pre:
            items = [{**gift, "key": "gift", "say": "GIFT Nifty"}] if gift else []
        else:
            items = []
            for key, (_, name, say, region) in INDICES.items():
                if region != rid:
                    continue
                m = moves.get(key)
                if m and m["day"] == fresh_day(kind, rid, today):
                    items.append({**m, "key": key, "say": say})
                else:
                    dropped.append({"name": name, "why": "no data" if not m else f"latest figure is from {m['day']:%d %b}, not {fresh_day(kind, rid, today):%d %b}"})
        if items:
            regions.append({"id": rid, "label": LABEL[rid], "session": "live" if any(i["session"] == "live" for i in items) else "closed",
                            "as_of": max(i["as_of"] for i in items), "items": items})
    have = {i["key"] for r in regions for i in r["items"]}
    skip = ""
    if pre and "gift" not in have:
        skip = "GIFT Nifty is missing or not recent"
    elif not pre and not {"nifty", "sensex"} <= have:
        skip = "Nifty 50 or Sensex is missing or not from today"
    elif len(regions) < 2:
        skip = "fewer than two regions have fresh figures"
    return {"kind": "premarket" if pre else "postmarket", "date": today, "regions": regions, "dropped": dropped, "skip": skip}


def when(r: dict) -> str:
    """Where a region's figures are from: the close's day, or the time of the live figure in Indian time."""
    return f"closed · {r['as_of']:%d %b}" if r["session"] == "closed" else f"live · {r['as_of'].astimezone(IST):%d %b %H:%M} IST"


def plain(data: dict) -> dict:
    """The assembled figures as plain JSON for the video's record (dates as text)."""
    return {"date": data["date"].isoformat(), "skip": data["skip"], "dropped": data["dropped"], "regions": [
        {"id": r["id"], "label": r["label"], "session": r["session"], "when": when(r), "items": [
            {"name": i["name"], "last": round(i["last"], 2), "pct": round(i["pct"], 2), "day": i["day"].isoformat(), "as_of": i["as_of"].isoformat(), "session": i["session"]}
            for i in r["items"]]} for r in data["regions"]]}


def trading_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def _holiday_dates(rows: list[dict]) -> set[date]:
    out = set()
    for r in rows or []:
        try:
            out.add(datetime.strptime(str(r["tradingDate"]).strip().title(), "%d-%b-%Y").date())
        except (KeyError, ValueError):
            continue
    return out


async def _nse(client: httpx.AsyncClient, path: str, **params) -> dict:
    r = await client.get(nse.API + path, params=params or None, headers=nse.UA, timeout=30.0)
    r.raise_for_status()
    return r.json()


async def trading_holidays(client: httpx.AsyncClient, store=None) -> set[date]:
    """NSE's equity (CM) trading holidays, kept a week in kv. A failed read gives the last list kept, else none (weekends still count)."""
    got = store.kv_get(HOLIDAYS, "CM") if store else None
    if got and time.time() - got["at"] < 7 * 86400:
        return {date.fromisoformat(d) for d in got["days"]}
    try:
        days = _holiday_dates((await _nse(client, "holiday-master", type="trading")).get("CM"))
    except (httpx.HTTPError, ValueError):
        return {date.fromisoformat(d) for d in got["days"]} if got else set()
    if store and days:
        store.kv_put(HOLIDAYS, "CM", {"at": time.time(), "days": sorted(d.isoformat() for d in days)})
    return days


async def collect(client: httpx.AsyncClient, kind: str, now: datetime) -> dict:
    """Fetch what the Short needs and assemble it (`kind` is "pre" or "post"). A failed read is a missing index, never an error."""
    async def yahoo(key: str):
        sym = INDICES[key][0]
        try:
            r = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"range": "5d", "interval": "1d"}, headers=UA, timeout=20.0)
            r.raise_for_status()
            return key, index_move(r.json()["chart"]["result"][0], INDICES[key][1], now.timestamp())
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return key, None

    async def get_nse(path: str, **params):
        try:
            return await _nse(client, path, **params)
        except (httpx.HTTPError, ValueError):
            return {}
    pre = kind == "pre"
    keys = [k for k, v in INDICES.items() if v[3] in (["us", "europe", "asia"] if pre else ["asia", "europe"])] + ([] if pre else ["sensex"])
    try:
        await client.get("https://www.nseindia.com/", headers=nse.UA, timeout=20.0)       # the cookies a browser would hold
    except httpx.HTTPError:
        pass
    status, all_idx, got = await asyncio.gather(get_nse("marketStatus") if pre else asyncio.sleep(0, {}), get_nse("allIndices") if not pre else asyncio.sleep(0, {}),
                                                asyncio.gather(*(yahoo(k) for k in keys)))
    moves = dict(got)
    gift = gift_nifty(status) if pre else None
    if not pre:
        moves.update(nse_indices(all_idx))
        for key in ("nifty", "banknifty"):
            if key not in moves:                        # NSE did not answer: Yahoo's level will do, without the advances and declines
                moves[key] = (await yahoo(key))[1]
    return assemble(kind, now.astimezone(IST).date(), moves, gift, now)
