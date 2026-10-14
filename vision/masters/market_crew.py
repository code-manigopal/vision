"""Mani Market Tamil: the crew that films one quarterly result a night, in Tanglish, and asks Mani before it goes anywhere.

    YouTube Manager -> Mani Market Tamil Director -> Results Scout -> Market Analyst -> Tanglish Writer -> Voice Clone
        -> Slide Editor -> Market Uploader (private, then your approval) -> Market Analytics (reports to the Director)

- Two kinds of long video, by the weekday of the release (channel option `pattern`, e.g. mon: analysis, tue: topic): "analysis" is one company's
  ratios from its filings (Scout picks a company not analysed in 180 days; Analyst reads fundamentals, shareholding, dividends and the price AT
  LEAST `price_lag_days` OLD, SEBI's rule for educational channels; fewer than 8 ratios (7 for a bank, lender or insurer) = skipped, the next company
  is tried), "result" is the quarterly result below. "topic" is a finance lesson (masters/lessons.py: official pages, every line checked against them) when the channel's
  `lessons` is on, and falls back to a result when none can be made; on a day the market is shut the two Short windows make a lesson Short (`lesson_shorts`). Lessons are always approved.
- Results Scout: only inside the making window (`make_after` to `make_before`, night time; a manual run ignores it). Reads every result NSE lists
  as filed in the last `within_days` (services/nse.py `recent`, paged) and takes up to three companies of the channel's index (`index_csv`) whose
  newest quarter has not been filmed (kv `mm_done`, key SYMBOL:quarter; a skip made by an older parser does not count). The Analyst makes the
  first one it can read; a filing with no figures for its form is marked tried and the next is taken. Nothing new = NOTHING NEW and the rest idle.
- The figures are the filing's, nothing else (masters/market.py builds the slides and the lines); the voice is Mani's cloned voice
  (voice/clone.py, about an hour a video, with LM Studio's model unloaded meanwhile) or Edge's Tamil voice (`voice_engine`).
- The upload is PRIVATE with no release time. An approval (kind `yt_publish`) is raised; approving schedules it for the next
  release slot (youtube.publish_decision), rejecting leaves it private. VISION never deletes a video.
- A crew member that fails does not block the later ones: the Uploader must still schedule what Mani approved.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

import httpx

from ..agents import AgentResult, Stage, request_approval
from ..config import secret
from ..services import filings_text, lmstudio, logos, markets, news, nse, oauth, world, yt_channels, yt_transcripts
from ..voice import clone
from . import fundamentals, lessons, market, slides, tamil_say, thumbs, youtube
from .tamil_say import numbers_as_words

log = logging.getLogger("vision")
DONE, INDEX = "mm_done", "mm_index"
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/ind_niftylargemidcap250list.csv"
BACKLOG = 2                      # videos finished or awaiting approval at which no new one is made
PAUSE = 0.15                     # seconds of silence after each spoken line
EDGE_VOICE, EDGE_RATE = "ta-IN-ValluvarNeural", "+14%"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
CANDIDATES = 3                   # results the Scout lines up in one run: the Analyst takes the first it can read, so one odd filing does not cost the night
REPEAT_DAYS = 180                # a company is not analysed twice within this many days (a skipped one counts)
TRIES = 4                        # more companies the Analyst may try when one has too few ratios
LAG_DAYS = 31                    # the price used is at least this old: SEBI bars an education-only creator from a stock's price of the last 30 days
DISCLAIMER = market.DISCLAIMER_EN + "\n\n" + market.DISCLAIMER_TA          # the end of every description on this channel, the owner's wording
IST = ZoneInfo("Asia/Kolkata")
REPORTS = {"premarket": "pre", "postmarket": "post"}                         # the two Shorts of a trading day, and how services/world.py names them
REPORT_WINDOWS = {"premarket": ("07:00", "08:15"), "postmarket": ("18:00", "20:30")}      # Indian time: when each is made
LEARN_MIN = 8                    # public videos of a kind before its own views change anything
LEARN_AGE = 2                    # days a public video must be old before its views a day count
LEARN_EXPLORE = 0.2              # the share of lessons the groups that do worse still get (held to 70% / groups, as youtube.choose does elsewhere)
LESSON_KINDS = ("lesson", "lesson_short")
SHORTS = (*REPORTS, "lesson_short")                                          # jobs that make a vertical Short (the two market reports, and a lesson on a day the market is shut)


def jobdir(ch: dict, name: str) -> str:
    """Where a job's files go. A review job (channel option `review`: one video of every kind uploaded private for Mani to watch) lives apart under `_review`, with a name
    of its own, so it never meets the real job of the same day (the log key is the folder's name)."""
    base = youtube.ROOT / "data" / "shorts" / ch["id"]
    return str(base / "_review" / f"review-{name}" if ch.get("review") else base / name)


def stamp(job: dict) -> dict:
    """The status of a finished video's record: `ready` (the Uploader asks Mani), or `review` for a review job (uploaded private, no release time, no approval)."""
    return {"status": "review", "review": True} if job.get("review") else {"status": "ready"}


def now_hm() -> str:
    return time.strftime("%H:%M")


def now_ist() -> datetime:
    return datetime.now(IST)


def report_window(now: datetime) -> str:
    """Which report Short is due at this moment by the Indian clock (the Mac's own clock changes with daylight saving, India's does not): premarket, postmarket or ""."""
    hm = now.astimezone(IST).strftime("%H:%M")
    return next((k for k, (after, before) in REPORT_WINDOWS.items() if in_window(after, before, hm)), "")


def in_window(after: str, before: str, now: str) -> bool:
    """Is `now` (HH:MM) between the two hours? The window may run through midnight (23:00 to 04:00)."""
    return (now >= after or now < before) if after > before else after <= now < before


def views_per_day(v: dict, now: float) -> float | None:
    """A public video's views a day since it went public (None: not public, or younger than LEARN_AGE days, or no figures yet)."""
    since = v.get("publish_at") or v.get("uploaded") or v.get("made")
    if v.get("status") != "public" or not since or "view" not in (v.get("stats") or {}) or (now - since) / 86400 <= LEARN_AGE:
        return None
    return v["stats"]["view"] / ((now - since) / 86400)


def learn(log: list[dict], now: float | None = None) -> dict:
    """What the channel's own public videos show, kept in kv yt_state `<channel>:insights`: average views a day per kind and per lesson topic group, and the top kind
    (among kinds with LEARN_MIN videos). Information for choosing between equal options; nothing here buys or fakes reach."""
    now, group = now or time.time(), {t["id"]: t["group"] for t in lessons.TOPICS}
    kinds: dict[str, list[float]] = {}
    groups: dict[str, list[float]] = {}
    for v in log:
        vpd = views_per_day(v, now)
        if vpd is None:
            continue
        kinds.setdefault(v.get("kind") or "result", []).append(vpd)
        if v.get("kind") in LESSON_KINDS and group.get(v.get("topic")):
            groups.setdefault(group[v["topic"]], []).append(vpd)
    avg = lambda d: {k: {"videos": len(x), "per_day": round(sum(x) / len(x), 1)} for k, x in sorted(d.items())}          # noqa: E731
    out = {"at": now, "kinds": avg(kinds), "groups": avg(groups), "top": None}
    best = [(k, e["per_day"]) for k, e in out["kinds"].items() if e["videos"] >= LEARN_MIN]
    if best:
        k, vpd = max(best, key=lambda x: x[1])
        out["top"] = {"kind": k, "per_day": vpd}
    return out


def by_own_views(order: list[tuple], insights: dict | None, log: list[dict], kind: str) -> list[tuple]:
    """The lesson topics in the order to try them: once LEARN_MIN public videos of this kind have views a day, the topic group chosen by youtube.choose (groups with more
    views a day first, LEARN_EXPLORE of the lessons going to the rest) comes first; inside a group the given order stands. Before that, or with no insights, unchanged."""
    ins = insights or {}
    groups = list(dict.fromkeys(o[0]["group"] for o in order))
    if not groups or (ins.get("kinds", {}).get(kind) or {}).get("videos", 0) < LEARN_MIN:
        return order
    group = {t["id"]: t["group"] for t in lessons.TOPICS}
    told: dict[str, int] = {}
    for v in log:
        if v.get("kind") in LESSON_KINDS and v.get("status") != "deleted" and group.get(v.get("topic")):
            told[group[v["topic"]]] = told.get(group[v["topic"]], 0) + 1
    first = youtube.choose(groups, told, {g: e["per_day"] for g, e in (ins.get("groups") or {}).items() if g in groups}, min(LEARN_EXPLORE, 0.7 / len(groups)))
    return [o for o in order if o[0]["group"] == first] + [o for o in order if o[0]["group"] != first]


async def edge_speak(lines: list[dict], work: Path, voice: str = EDGE_VOICE, rate: str = EDGE_RATE) -> list[Path]:
    """Edge's Tamil voice, one mp3 per line (fast and artificial: the stand-in until the cloned voice is chosen)."""
    import edge_tts
    work.mkdir(parents=True, exist_ok=True)
    out = []
    for n, ln in enumerate(lines):
        out.append(work / f"v{n:03d}.mp3")
        await edge_tts.Communicate(numbers_as_words(ln["say"]), voice, rate=rate).save(str(out[-1]))
    return out


async def optional(call):
    """A piece the video can do without (shareholding, dividends, price): None when it cannot be had."""
    try:
        return await call
    except Exception as e:  # noqa: BLE001
        log.warning("market: %s", e)
        return None


async def gather(c: httpx.AsyncClient, symbol: str, lag: int = LAG_DAYS) -> tuple[dict | None, list[dict], dict | None]:
    """A company's fundamentals, its ratios and the lagged price used (None when Yahoo gave none: the price ratios are then left out).
    The filings failing is an error; shareholding, dividends and price are optional. No filing with four quarters = (None, [], None)."""
    f = await nse.fundamentals(c, symbol)
    if not f or not f["ttm"]:
        return None, [], None
    today = min(date.today(), datetime.now(ZoneInfo("Asia/Kolkata")).date())          # the earlier of the two dates, so the lag is never shorter than it says
    f["shareholding"] = await optional(nse.shareholding(c, symbol))
    f["dividend"] = await optional(nse.dividends(c, symbol, today))
    price = fundamentals.lagged(await optional(markets.yahoo_closes(c, symbol + ".NS")) or [], today, lag)
    return f, fundamentals.ratios(f, price), price


async def documents(c: httpx.AsyncClient, symbol: str, result: dict) -> list[dict]:
    """The company's own documents filed with the result (press release, presentation, board outcome; at most two): each {subject, at, url, kind, text},
    `text` being the sentences about the figures and reasons. A file that will not download or holds no text (a scan) is left out."""
    out = []
    for a in filings_text.choose(await nse.announcements(c, symbol), result["filed"]):
        for _ in range(2):                                  # a slow or cut-off download is tried once more
            r = await optional(c.get(a["url"], headers={"User-Agent": nse.UA["User-Agent"]}, timeout=40.0))
            if r is not None and r.status_code == 200 and filings_text.pdf_text(r.content, 1):
                break
        text = filings_text.relevant(filings_text.pdf_text(r.content), 4500) if r is not None and r.status_code == 200 and len(r.content) < 8 << 20 else ""
        if text:
            out.append({**{k: a[k] for k in ("subject", "at", "url", "kind")}, "text": text})
    return out


async def headlines(c: httpx.AsyncClient, result: dict) -> list[dict]:
    """Headlines about the result from the days around its filing (Google News, India edition), at most 3, none about the share price or advice."""
    try:
        day = datetime.strptime(result["filed"][:11], "%d-%b-%Y").date()
    except ValueError:
        return []
    name = market.short(result["name"])
    url = news.google_news_between(f'("{name}" OR {result["symbol"]}) results', (day - timedelta(days=1)).isoformat(), (day + timedelta(days=4)).isoformat())
    items = await news.fetch_feed(c, url, 24 * 365)
    return market.news_pick(items, name, result["symbol"], near=market.filed_ts(result))


class MCrew(youtube.Crew):
    """A member of the market crew. It works on ctx["job"] and idles when the job is missing the earlier members' part."""
    blocking = False

    def client(self) -> httpx.AsyncClient:
        make = self.opts.get("client_factory")
        return make() if make else httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True)

    @staticmethod
    def job(ctx: dict, need: str = "") -> dict | None:
        j = ctx.get("job")
        return j if j and (not need or j.get(need)) else None


async def members(c: httpx.AsyncClient, store, url: str) -> set[str]:
    """The symbols in the channel's index list (a CSV with a Symbol column), kept a week."""
    got = store.kv_get(INDEX, url)
    if got and time.time() - got["at"] < 7 * 86400 and got["symbols"] and "names" in got:
        return set(got["symbols"])
    r = await c.get(url, headers={"User-Agent": nse.UA["User-Agent"]}, timeout=30.0)
    r.raise_for_status()
    rows = [row for row in csv.DictReader(io.StringIO(r.text.lstrip("﻿"))) if (row.get("Symbol") or "").strip()]
    syms = sorted({row["Symbol"].strip().upper() for row in rows})
    if not syms:
        raise RuntimeError("the index list holds no symbols")
    store.kv_put(INDEX, url, {"at": time.time(), "symbols": syms, "names": sorted({(row.get("Company Name") or "").strip() for row in rows} - {""})})      # names: a lesson names no company
    return set(syms)


def index_terms(store, url: str) -> tuple[list[str], list[str]]:
    """(company names, symbols) of the channel's index as last read (members() keeps them a week); empty before the first read."""
    got = store.kv_get(INDEX, url) or {}
    return got.get("names") or [], got.get("symbols") or []


def release_kind(store, ch: dict) -> tuple[str, str]:
    """The kind of the next long video and the date it will be released: the channel's `pattern` for that weekday in its timezone, else "result"."""
    due = datetime.fromtimestamp(youtube.next_slot(store, ch, fmt="long"), ZoneInfo(ch["timezone"]) if ch.get("timezone") else None)
    return (ch.get("pattern") or {}).get(DAYS[due.weekday()]) or "result", due.date().isoformat()


def done_at(store, key: str) -> float | None:
    """When a result or analysis was made or looked at, or None if it has not been. A skip made by an older parser (nse.PARSER) does not count:
    the code reads more forms now, so a company skipped for "no figures" or "too few ratios" is tried again."""
    got = store.kv_get(DONE, key)
    if got is None or (got.get("skipped") and (got.get("parser") or 0) < nse.PARSER):
        return None
    return got.get("at") or 1


def skip(store, key: str, why: str) -> None:
    """Mark a result or analysis tried and not made (or it would be picked again every night), with the reason and the parser that failed it."""
    store.kv_put(DONE, key, {"skipped": why, "at": time.time(), "parser": nse.PARSER})


def analysis_order(store, symbols: set[str], day: str) -> list[str]:
    """Companies to analyse, best first: never analysed ones in a stable but not alphabetical order (a hash with the release date), then
    those analysed over REPEAT_DAYS ago, oldest first. Anyone analysed or skipped within REPEAT_DAYS is left out."""
    at = {s: done_at(store, f"analysis:{s}") for s in symbols}
    new = sorted((s for s in symbols if not at[s]), key=lambda s: hashlib.sha1(f"{day}:{s}".encode()).hexdigest())
    return new + sorted((s for s in symbols if at[s] and at[s] < time.time() - REPEAT_DAYS * 86400), key=lambda s: at[s])


class ResultsScout(MCrew):
    name, tier, note = "Results Scout", "API", "finds tonight's company in the index"

    async def run(self, ctx: dict) -> AgentResult:
        res = await self.pick(ctx)
        if self.ch.get("review") and ctx.get("job"):                 # review mode: the video is uploaded private for Mani to watch, with no release time and no approval
            ctx["job"]["review"] = True
        return res

    async def pick(self, ctx: dict) -> AgentResult:
        ch, store = self.ch, ctx["store"]
        manual = ctx.get("reason") == "manual"                       # a manual run (the dashboard's Run) ignores the hours
        force = ctx.get("force") or {}                               # tests and scripts: {"kind": "analysis", "symbol": "ITC"}, {"kind": "result", "symbol": "TCS"}, {"kind": "premarket"} or {"kind": "lesson", "topic": "mf-basics"}
        now = ctx.get("now") or now_ist()
        if force.get("kind") == "lesson_short":                      # tests and scripts: a lesson Short for one topic, whatever the day
            win, day = force.get("window") or "premarket", now.astimezone(IST).date()
            ctx["job"] = {"kind": "lesson_short", "key": f"lesson_short:{win}:{day.isoformat()}", "window": win, "date": day.isoformat(), "name": f"lesson {win} {day:%d %b}",
                          "topic": force.get("topic"), "dir": jobdir(self.ch, f"{day.isoformat()}-lesson-{REPORTS[win]}")}
            return AgentResult("done", "FOUND", f"lesson Short ({win}) for {day:%d %b}")
        due = force["kind"] if force.get("kind") in REPORTS else "" if manual else report_window(now)
        if due and (found := await self.report(ctx, due, now, bool(force.get("kind")))) is not None:      # a report Short is due: it goes before the night's long video
            return found
        after, before = ch.get("make_after") or "23:00", ch.get("make_before") or "04:00"
        if not manual and not in_window(after, before, now_hm()):
            return AgentResult("idle", "NOT YET", f"Videos are made between {after} and {before}")
        mine = [v for v in store.kv_list(youtube.LOG) if v.get("channel") == ch["id"] and v.get("format") != "short"]       # the long videos; the report Shorts keep their own count
        waiting = sum(v.get("status") in ("ready", "awaiting") for v in mine)
        if waiting >= BACKLOG and not force:
            return AgentResult("idle", "BACKLOG", f"{waiting} finished videos are waiting to upload or for your approval; no new ones until they clear")
        per = int(ch.get("per_run") or 1)
        if not manual and sum((v.get("made") or 0) > time.time() - 12 * 3600 for v in mine) >= per:
            return AgentResult("idle", "DONE TONIGHT", f"{per} video made already tonight")
        kind, day = release_kind(store, ch)
        kind = force.get("kind") or kind
        lesson = kind == "lesson" or (kind == "topic" and bool(ch.get("lessons")))       # a topic day makes a finance lesson (lessons.py); a result is the fallback
        async with self.client() as c:
            symbols = await members(c, store, ch.get("index_csv") or INDEX_URL)
            if kind == "analysis":
                order = [force["symbol"].upper()] if force.get("symbol") else analysis_order(store, symbols, day)
                if not order:
                    return AgentResult("done", "NOTHING NEW", f"All {len(symbols)} companies in the index were analysed in the last {REPEAT_DAYS} days")
                ctx["job"] = {"kind": "analysis", "symbol": order[0], "key": f"analysis:{order[0]}", "name": order[0], "more": order[1:1 + TRIES],
                              "dir": jobdir(ch, f"analysis-{order[0]}")}
                return AgentResult("done", "FOUND", f"{order[0]}: fundamental analysis (release {day})")
            if lesson and force.get("topic"):                        # a script or test asked for one topic: no result to fall back on
                ctx["job"] = {"kind": "lesson", "key": f"lessonnight:{day}", "day": day, "name": "finance lesson", "topic": force["topic"], "fallback": None}
                return AgentResult("done", "FOUND", f"finance lesson: {force['topic']}")
            days = int(ch.get("within_days") or 4)
            named = kind == "result" and force.get("symbol")         # a script named the company: its newest result, however long ago and whether or not it was filmed
            filed = await nse.recent(c, 30 if named else days)
            days = 30 if named else days
        later = "" if lesson else " (a topic day; lessons are switched off, so a result)" if kind == "topic" else ""
        fresh = time.time() - days * 86400
        picks: list[dict] = []
        for f in filed:
            q, sym = nse.quarter(f["end"]), f["symbol"].upper()
            if named and sym != force["symbol"].upper():
                continue
            if sym in symbols and nse.filed_at(f["filed"]).timestamp() > fresh and (named or done_at(store, f"{sym}:{q}") is None) and not any(p["key"] == f"{sym}:{q}" for p in picks):
                picks.append({"kind": "result", "symbol": sym, "quarter": q, "key": f"{sym}:{q}", "name": f["name"], "end": f["end"].isoformat(),
                              "dir": jobdir(ch, f"{f['end'].isoformat()}-{sym}-{q.replace(' ', '')}")})
                if len(picks) == CANDIDATES:
                    break
        if lesson:                                                   # the Analyst picks the topic; if no lesson can be made it makes tonight's first result instead
            ctx["job"] = {"kind": "lesson", "key": f"lessonnight:{day}", "day": day, "name": "finance lesson", "topic": None, "fallback": {**picks[0], "more": picks[1:]} if picks else None}
            return AgentResult("done", "FOUND", f"a finance lesson (release {day})" + (f"; if none can be made, {market.short(picks[0]['name'])} {picks[0]['quarter']} results" if picks else ""))
        if picks:
            ctx["job"] = {**picks[0], "more": picks[1:]}
            return AgentResult("done", "FOUND", f"{market.short(picks[0]['name'])} {picks[0]['quarter']} results{later}" + (f" (and {len(picks) - 1} more to try if it cannot be read)" if len(picks) > 1 else ""))
        return AgentResult("done", "NOTHING NEW", f"No new result from the {len(symbols)} companies in the index ({len(filed)} filings read){later}")


    async def report(self, ctx: dict, due: str, now: datetime, forced: bool) -> AgentResult | None:
        """The job for a pre-market or post-market Short: only on an NSE trading day (a forced run skips that check), once per Indian date. None = nothing due."""
        store, day = ctx["store"], now.astimezone(IST).date()
        key, lkey = f"{due}:{day.isoformat()}", f"lesson_short:{due}:{day.isoformat()}"
        if not forced and (store.kv_has(DONE, key) or store.kv_has(DONE, lkey)):
            return None
        if not forced:
            holidays = set()
            if day.weekday() < 5:                                    # a weekend needs no list
                async with self.client() as c:
                    holidays = await world.trading_holidays(c, store)
            if not world.trading_day(day, holidays):
                if self.ch.get("lesson_shorts"):                     # the market is shut: a lesson Short takes the slot
                    ctx["job"] = {"kind": "lesson_short", "key": lkey, "window": due, "date": day.isoformat(), "name": f"lesson {due} {day:%d %b}", "topic": None,
                                  "dir": jobdir(self.ch, f"{day.isoformat()}-lesson-{REPORTS[due]}")}
                    return AgentResult("done", "FOUND", f"lesson Short for {day:%a %d %b} ({'morning' if due == 'premarket' else 'evening'}; the market is shut)")
                return AgentResult("idle", "NO MARKET", f"{day:%a %d %b} is not an NSE trading day: no {due} update")
        ctx["job"] = {"kind": due, "key": key, "date": day.isoformat(), "name": f"{due} {day:%d %b}", "dir": jobdir(self.ch, f"{day.isoformat()}-{due}")}
        return AgentResult("done", "FOUND", f"{due} update for {day:%d %b}")


class MarketAnalyst(MCrew):
    name, tier, note = "Market Analyst", "API", "reads the filing's figures"

    async def run(self, ctx: dict) -> AgentResult:
        job = self.job(ctx)
        if not job:
            return self.idle()
        if job.get("kind") in ("lesson", "lesson_short"):
            done = await self.lesson(ctx, job)
            if done is not None:
                return done
            job = ctx["job"]                                           # no lesson could be made: the first result of tonight, if the Scout found one
        if job.get("kind") in REPORTS:
            return await self.report(ctx, job)
        if job.get("kind") == "analysis":
            return await self.analyse(ctx, job)
        result, unread = None, []
        for cand in [dict(job), *job.get("more", [])]:                  # the first result that has figures for its form; one that has none is marked tried, not an error
            async with self.client() as c:
                got = await nse.latest(c, cand["symbol"])
            if got and got["rows"]:
                result = got
                job.update(cand, more=[])
                break
            skip(ctx["store"], cand["key"], "no figures")
            unread.append(f"{cand['symbol']} {cand['quarter']}")
        if not result:
            ctx.pop("job", None)
            return AgentResult("wait", "UNREADABLE", f"NSE lists no figures for {', '.join(unread)}; marked tried, the next night looks again at others")
        job["result"] = result
        async with self.client() as c:                      # what backs the numbers; each is optional, the video is made without it
            f = await optional(nse.fundamentals(c, job["symbol"]))
            if f and f["ttm"]:
                job["key_ratios"] = market.key_ratios(fundamentals.ratios(f, None), nse.shape(f))      # filings only: no price here, SEBI's 30-day rule
            job["docs"] = await optional(documents(c, job["symbol"], result)) or []
            job["news"] = await optional(headlines(c, result)) or []
        extra = [f"{len(job.get('key_ratios') or [])} ratios", f"{len(job['docs'])} documents", f"{len(job['news'])} headlines"]
        return AgentResult("done", "READ", f"{result['name']} {result['quarter']}: {len(result['rows'])} figures from the filing, " + ", ".join(extra)
                           + (f"; no figures for {', '.join(unread)}, marked tried" if unread else ""))


    async def signals(self, ctx: dict) -> list[dict]:
        """Recent videos of the channels named in `lesson_channels` with their views (yt_channels, at most once a day), using YOUTUBE_API_KEY when set, else this channel's own
        sign-in. No names, no sign-in or any failure gives []: the topics then go by how long since each was made."""
        names = self.ch.get("lesson_channels") or []
        if not names:
            return []
        try:
            key, token = secret("YOUTUBE_API_KEY"), None
            if not key:
                token = await oauth.access_token(youtube.account(self.ch), "youtube")
            async with self.client() as c:
                return (await yt_channels.signals(c, ctx["store"], names, token, key))["videos"]
        except (oauth.AuthNeeded, httpx.HTTPError, ValueError, KeyError) as e:
            log.info("market: no channel signals (%s)", e)
            return []

    async def lesson(self, ctx: dict, job: dict) -> AgentResult | None:
        """Researches tonight's lesson (or lesson Short): the topics in order (signals first), each one's official pages, and the transcripts of the videos that matched.
        Up to MAX_TOPICS topics with sources are lined up for the Writer; a topic whose pages are all dead is skipped for a few days (NO SOURCE). None = nothing could be
        lined up and the Scout had a result to fall back on (ctx["job"] is now that result)."""
        store, ch = ctx["store"], self.ch
        short, sleep = job["kind"] == "lesson_short", self.opts.get("sleep", asyncio.sleep)
        videos = await self.signals(ctx)
        now = time.time()
        order = ([(t, *yt_channels.score(t, videos, now)) for t in lessons.TOPICS if t["id"] == job["topic"]] if job.get("topic")
                 else by_own_views(lessons.rank(store, lessons.TOPICS, videos, now, short), store.kv_get(youtube.STATE, f"{ch['id']}:insights"),
                                   [v for v in store.kv_list(youtube.LOG) if v.get("channel") == ch["id"]], job["kind"]))
        cands, tried = [], []
        async with self.client() as c:
            for tp, score, hit in order:
                if len(cands) >= lessons.MAX_TOPICS or len(tried) >= 6:
                    break
                pages = await lessons.fetch_sources(c, tp, sleep=sleep)
                if not pages:
                    lessons.skip(store, tp["id"], "no source")
                    tried.append(tp["id"])
                    continue
                cands.append({"topic": tp, "pages": pages, "videos": hit, "score": score, "transcripts": []})
        if not cands:
            if job.get("fallback"):
                ctx["job"] = job["fallback"]
                return None
            ctx.pop("job", None)
            return AgentResult("wait", "NO SOURCE", "No topic had an official page to read" + (f" (tried {', '.join(tried)})" if tried else "") + "; no lesson tonight")
        cap = int(ch.get("transcripts_per_day") or 10)
        for cand in cands:                                             # raw material only; a block stops it for the day (yt_transcripts)
            cand["transcripts"] = await yt_transcripts.read(store, cand["videos"], cap=cap, fetch=self.opts.get("transcript_fetch"), sleep=sleep)
        job.update(cands=cands, tried=tried)
        tx = yt_transcripts.state(store, date.today())
        return AgentResult("done", "READ", f"{', '.join(c['topic']['id'] for c in cands)}: {sum(len(c['pages']) for c in cands)} official pages, {len(videos)} channel videos seen, "
                           f"{sum(len(c['transcripts']) for c in cands)} transcripts read" + (" (YouTube blocked; no more today)" if tx["blocked"] else "") + (f"; no source for {', '.join(tried)}" if tried else ""))

    async def report(self, ctx: dict, job: dict) -> AgentResult:
        """The indices for a report Short (services/world.py). An index that is not from the expected session is left out; too few left = no Short today."""
        async with self.client() as c:
            data = await world.collect(c, REPORTS[job["kind"]], ctx.get("now") or now_ist())
        left = ", ".join(f"{d['name']} ({d['why']})" for d in data["dropped"])
        if data["skip"]:
            ctx.pop("job", None)
            return AgentResult("wait", "SKIPPED", f"No {job['kind']} update: {data['skip']}" + (f"; left out: {left}" if left else ""))
        job["data"] = data
        return AgentResult("done", "READ", f"{sum(len(r['items']) for r in data['regions'])} indices in {len(data['regions'])} regions" + (f"; left out: {left}" if left else ""))

    async def analyse(self, ctx: dict, job: dict) -> AgentResult:
        """The company's ratios. One with fewer than fundamentals.minimum(f) is marked skipped for REPEAT_DAYS and the next of `more` is tried."""
        store, lag, tried = ctx["store"], int(self.ch.get("price_lag_days") or LAG_DAYS), []
        async with self.client() as c:
            for sym in [job["symbol"], *job.get("more", [])]:
                f, rows, price = await gather(c, sym, lag)
                if f and len(rows) >= fundamentals.minimum(f):
                    job.update(symbol=sym, key=f"analysis:{sym}", name=f["name"], fundamentals=f, ratios=rows, price=price,
                               dir=jobdir(self.ch, f"analysis-{sym}-{f['ttm_to']}"))
                    return AgentResult("done", "READ", f"{f['name']}: {len(rows)} ratios from the filings" + ("" if price else ", no price"))
                skip(store, f"analysis:{sym}", "too few ratios")
                tried.append(sym)
        ctx.pop("job", None)
        return AgentResult("wait", "TOO FEW FIGURES", f"{', '.join(tried)}: too few ratios from the filings ({fundamentals.MIN_RATIOS}, or {fundamentals.MIN_FINANCIAL} for a bank, lender or insurer); skipped for {REPEAT_DAYS} days")


class TanglishWriter(MCrew):
    name, tier, note = "Tanglish Writer", "CLOUD", "slides and spoken lines from the figures"

    async def lesson(self, ctx: dict) -> AgentResult:
        """Writes the lesson (lessons.write: the slides and English lines checked against the official pages, then the same lines in spoken Tanglish). A topic that keeps fewer than lessons.MIN_KEPT lines
        (a Short: MIN_KEPT_SHORT) is skipped for a few days and the next lined-up one is tried."""
        job, store, llm = ctx["job"], ctx["store"], ctx.get("llm")
        if not job.get("cands"):
            return self.idle()
        if not llm or not llm.writer_available():
            ctx.pop("job", None)
            return AgentResult("wait", "NO WRITER", "The writer model is not available: no lesson tonight")
        short = job["kind"] == "lesson_short"
        names, symbols = index_terms(store, self.ch.get("index_csv") or INDEX_URL)
        bad, thin = lessons.bad_pattern(names, symbols), []
        for cand in job["cands"][:lessons.MAX_TOPICS]:
            tp = cand["topic"]
            covered = (store.kv_get(DONE, f"lessonshort:{tp['id']}") or {}).get("concepts") or []
            try:
                out = await lessons.write(llm, tp, cand["pages"], cand["transcripts"], bad, short, covered, self.ch.get("lesson_model") or None,
                                    self.ch.get("lesson_tamil_model") or None, int(self.ch.get("lesson_min_lines") or 0) or None)
            except lessons.Busy as e:                                    # the daily allowance is spent: nothing is wrong with the topic, so it is not skipped; the next run tries again
                ctx.pop("job", None)
                return AgentResult("wait", "WRITER BUSY", f"The writer's allowance is used up for now ({e}); no lesson on this run")
            for d in out["dropped"]:
                log.info("lessons: %s: line dropped (%s): %s", tp["id"], d["why"], d["en"])
            if out["too_thin"]:
                lessons.skip(store, tp["id"], "too thin")
                thin.append(f"{tp['id']} ({out['kept']} of {out['proposed']} lines kept)")
                continue
            title = out["title"] + (" #Shorts" if short and "#shorts" not in out["title"].lower() else "")
            job.update(topic=tp["id"], tp=tp, pages=cand["pages"], inspired=[{k: t.get(k) for k in ("title", "channel", "url")} for t in cand["transcripts"]], title=title[:100],
                       deck=out["deck"], lines=out["lines"], kept=out["kept"], proposed=out["proposed"], dropped=out["dropped"], concept=out["concept"], angle=out["angle"],
                       new_words=out["new_words"], steps=out["steps"])
            if not short:
                job["dir"] = jobdir(self.ch, f"lesson-{tp['id']}-{job['day']}")
            if self.ch.get("voice_engine", "clone") == "clone":              # the same safety net as every video: a fixed line the voice would garble is a bug to see in the test, not here
                back = [ln["say"] for ln in job["lines"] if clone.unspelt(ln["say"])]
                if back:
                    log.warning("lessons: the voice would garble: %s", back)
            return AgentResult("done", "WRITTEN", f"{tp['title']}: {out['kept']} of {out['proposed']} lines kept, {len(out['dropped'])} dropped")
        ctx.pop("job", None)
        return AgentResult("wait", "TOO THIN", f"Too few lines passed the checks: {', '.join(thin)}; skipped for {lessons.SKIP_DAYS} days")

    async def run(self, ctx: dict) -> AgentResult:
        if (ctx.get("job") or {}).get("kind") in ("lesson", "lesson_short"):
            return await self.lesson(ctx)
        if (ctx.get("job") or {}).get("kind") in REPORTS:                # a report Short: templates only, no model anywhere
            job = self.job(ctx, "data")
            if not job:
                return self.idle()
            deck = market.report_deck(job["kind"], job["data"])
            said = market.report_react(market.report_lines(job["kind"], job["data"], deck), turn=sum(v.get("channel") == self.ch["id"] for v in ctx["store"].kv_list(youtube.LOG)))
            job.update(deck=deck, lines=said, kept=0)
            return AgentResult("done", "WRITTEN", f"{len(said)} lines from templates")
        job = self.job(ctx, "ratios") if (ctx.get("job") or {}).get("kind") == "analysis" else self.job(ctx, "result")
        if not job:
            return self.idle()
        result, llm = job.get("fundamentals") or job["result"], ctx.get("llm")
        said, kept = [], 0
        if job["kind"] == "analysis":
            deck = market.analysis_deck(result, job["ratios"])
            plain = market.analysis_lines(result, job["ratios"], deck)
        else:
            model = llm and llm.writer_available()
            job["reasons"] = await self.reasons(llm, result, job.get("docs") or []) if model else []
            for n, g in zip(job.get("news") or [], await market.news_gists(llm, job.get("news") or [], market.said_name(result)) if model else []):
                n["gist"] = g
            deck = market.deck(result, reasons=job["reasons"], ratios=job.get("key_ratios") or [], news=job.get("news") or [])
            plain = market.lines(result, deck, job.get("key_ratios") or [])
        said = plain
        if self.ch.get("reword") and llm and llm.writer_available():     # off by default: the template wording is what Mani approved
            said, kept = await market.reword(llm, plain, result)
        if self.ch.get("voice_engine", "clone") == "clone":              # the cloned voice garbles English letters: such a line stays as the plain one
            back = [i for i, ln in enumerate(said) if clone.unspelt(ln["say"])]
            said = [plain[i] if i in back else ln for i, ln in enumerate(said)]
            kept = max(0, kept - len(back))
        said = market.react(said, result, turn=sum(v.get("channel") == self.ch["id"] for v in ctx["store"].kv_list(youtube.LOG)))
        job.update(deck=deck, lines=said, kept=kept)
        return AgentResult("done", "WRITTEN", f"{len(said)} lines, {kept} reworded by the model")

    @staticmethod
    async def reasons(llm, result: dict, docs: list[dict]) -> list[dict]:
        """The company's reasons that pass the checks (market.reasons), each with the document its quote is in."""
        text = "\n\n".join(f"[{d['subject']}, {market.dmy(d['at'][:10])}]\n{d['text']}" for d in docs)
        got = await market.reasons(llm, result, text)
        out = [{**r, "doc": {k: d[k] for k in ("subject", "at", "url")}} for r in got for d in [filings_text.source_of(r["quote"], docs)] if d]
        return out


def voice_qa(work: Path) -> dict | None:
    """What the listen-back found for a video's lines (voice/listen.py, left by clone.speak in qa.json), in short."""
    try:
        qa = json.loads((work / "qa.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scores = [q["score"] for q in qa if q.get("score") is not None]
    if not scores:
        return None
    out = {"lines": len(qa), "lowest": min(scores), "mean": round(sum(scores) / len(scores), 2), "made_again": sum(q.get("tries", 1) > 1 for q in qa),
           "longest_gap": max(q.get("gap", 0) for q in qa)}
    return {**out, "text": f"heard {out['lowest']:.2f} at worst, {out['made_again']} made again"}


class VoiceClone(MCrew):
    name, tier, note = "Voice Clone", "GPU", "Mani's voice (or Edge's) for every line"

    async def run(self, ctx: dict) -> AgentResult:
        job = self.job(ctx, "lines")
        if not job:
            return self.idle()
        ch, lines, work = self.ch, job["lines"], Path(job["dir"]) / "voice"
        work.mkdir(parents=True, exist_ok=True)
        synth, engine = self.opts.get("synth"), ch.get("voice_engine", "clone")
        if synth:                                                         # tests: a stand-in voice
            files = [(await synth(ln["say"], work / f"v{n:03d}"))[0] for n, ln in enumerate(lines)]
        elif engine == "edge":
            files = await edge_speak(lines, work)
        else:                                                             # an hour of work: in a thread, with the local model out of the memory
            def speak() -> list[Path]:
                return clone.speak(lines, work, log=log.info, speed=float(ch.get("short_voice_speed") or clone.SHORT_SPEED) if job.get("kind") in SHORTS else clone.SPEED)
            try:
                if ch.get("free_memory") and job.get("kind") not in SHORTS:       # only a long video's hour of voice needs the memory; a 40-second Short fits beside the local model
                    async with lmstudio.freed():
                        files = await asyncio.to_thread(speak)
                else:
                    files = await asyncio.to_thread(speak)
            except clone.VoiceFailed as e:                                # a line that never sounded right: no video tonight, and Mani is told why
                what = f"today's {job['kind']} Short" if job.get("kind") in SHORTS else "tonight's video"
                ctx["bus"].notice(f"voice:{ch['id']}", f"{ch['name']}: {what} was held back, the voice check failed ({e})", "")
                return AgentResult("error", "VOICE HELD", str(e))
            ctx["bus"].clear_notice(f"voice:{ch['id']}")
            job["voice_qa"] = voice_qa(work)
        job["spoken"] = files
        return AgentResult("done", "VOICED", f"{len(files)} lines, voice: {'test' if synth else engine}" + (f", {job['voice_qa']['text']}" if job.get("voice_qa") else ""))


class SlideEditor(MCrew):
    name, tier, note = "Slide Editor", "LOCAL", "slides, presenter and voice into the video"

    @staticmethod
    def title(result: dict) -> str:
        figures = {"bank": "NII, Profit, NPA", "lender": "NII, Profit, Asset Quality", "life": "Premium, Profit, Solvency", "general": "Premium, Profit, Combined Ratio",
                   "plain": "Revenue, Profit, EPS"}.get(nse.shape(result), "Revenue, Profit, Margin")
        return thumbs.result_title(result) or f"{market.short(result['name'])} {result['quarter']} Results தமிழில் | {figures} என்ன சொல்லுது?"[:100]

    @staticmethod
    def result_summary(result: dict, tags: list[str], docs: list[dict], headlines: list[dict], logo: str = "") -> str:
        """The description: what it is, the hashtags, every source used (the filing, each company document, each news item, the logo's page), the disclaimer last."""
        seen = [f"Source: NSE filing ({result['source']})"]
        seen += [f"Company document: {d['subject']}, {market.dmy(d['at'][:10])}, filed with NSE ({d['url']})" for d in docs]
        seen += [f"News: {n['source']}, {market.dmy(n['at'])} ({n['link']})" for n in headlines] + [logo] * bool(logo)
        return (f"{market.short(result['name'])} {result['quarter']} results explained in Tanglish: the figures as the company filed them, nothing more.\n\n"
                + " ".join(tags) + "\n\n" + "\n".join(seen) + f"\n{DISCLAIMER}")

    @staticmethod
    def analysis_title(f: dict, rows: list[dict] = ()) -> str:
        figures = {"bank": "ROE, NII, Profit", "lender": "ROE, NII, Profit", "life": "ROE, Premium, Solvency", "general": "ROE, Premium, Solvency",
                   "plain": "ROE, Profit, Margin"}.get(nse.shape(f), "ROE, Debt, Margin")
        return thumbs.analysis_title(f, rows) or f"{market.short(f['name'])} Fundamental Analysis தமிழில் | {figures} என்ன சொல்லுது?"[:100]

    @staticmethod
    def analysis_summary(f: dict, price: dict | None, tags: list[str], logo: str = "") -> str:
        """The description: what it is, the hashtags, every source (and the logo's page), the price's date and why it is old, and the disclaimer last."""
        seen = [f"NSE filing: {u}" for u in f["sources"]] + ["Shareholding: NSE"] + [logo] * bool(logo)
        if price:
            seen.append(f"Price as of {market.dmy(price['date'])} (Yahoo Finance), older than 30 days as SEBI's rule for educational content requires")
        return (f"{market.short(f['name'])} fundamental analysis in Tanglish: ratios worked out from the company's own NSE filings, information only.\n\n"
                + " ".join(tags) + "\n\nSources:\n" + "\n".join(seen) + f"\n\n{DISCLAIMER}")

    @staticmethod
    def report_title(kind: str, day: date) -> str:
        d = f"{day.day} {day:%b}"
        return (f"Pre-Market Update {d} | US, Asia, GIFT Nifty என்ன சொல்லுது? #Shorts" if kind == "premarket" else f"Post-Market Update {d} | Nifty, Sensex எப்படி close ஆச்சு? #Shorts")[:100]

    @staticmethod
    def report_summary(kind: str, data: dict) -> str:
        """The description: one line of what it covers, where the figures are from and as of when, then the two disclaimer paragraphs."""
        day, names = data["date"], ", ".join(r["label"] if r["id"] != "india" or kind == "postmarket" else "GIFT Nifty" for r in data["regions"])
        covers = f"{'Pre' if kind == 'premarket' else 'Post'}-market update for {day.day} {day:%b}: {names}. Figures only, nothing about what comes next."
        asof = "; ".join(f"{'GIFT Nifty' if r['id'] == 'india' and kind == 'premarket' else r['label']} {world.when(r)}" for r in data["regions"])
        return f"{covers}\n\nData: NSE, Yahoo Finance, as of {asof}.\n\n{DISCLAIMER}"

    async def film(self, job: dict, tall: bool = False, **frame) -> Path:
        """The slides, presenter, voice and (channel option `captions`) the English captions as final.mp4 in the job's folder. A line with no caption shows none."""
        work, lines, caps = Path(job["dir"]), job["lines"], None
        pictures = self.opts.get("pictures") or slides.pictures
        plan = slides.caption_plan(lines, tall) if self.ch.get("captions") else None
        if plan and (missing := [n for n, c in enumerate(plan) if not c]):
            log.info("market: %s line(s) have no English caption: %s", len(missing), missing)
        got = await asyncio.to_thread(pictures, job["deck"], lines, work, tall=tall, channel=self.ch["name"], **({"captions": slides.caption_texts(plan)} if plan else {}), **frame)
        pngs, faces = got[0], got[1]
        if plan and len(got) > 2:
            caps = {"plan": plan, "pngs": got[2]}
        return await asyncio.to_thread(slides.assemble, work, pngs, lines, job["spoken"], work / "final.mp4", faces=faces, pause=PAUSE, captions=caps,
                                       **({"size": slides.TALL} if tall else {}))

    async def cover(self, job: dict, name: str, symbol: str = "", label: str = "") -> tuple[str, dict | None]:
        """thumb.jpg for a long video: the hook from its own figures on the channel's slide look, with the company's Commons logo when it has one (services/logos.py).
        Returns (path, the logo used or None); a failure gives ("", None) and the video goes out without a cover."""
        hook, tone = thumbs.hook_for(job)
        if not hook:
            return "", None
        work, logo = Path(job["dir"]), None
        try:
            if symbol:
                async with self.client() as c:
                    logo = await logos.find(c, symbol, market.short(name), **{k: self.opts[o] for k, o in (("root", "logo_root"), ("sleep", "sleep")) if self.opts.get(o)})
            make = self.opts.get("thumbnailer") or slides.thumbnail
            out = await asyncio.to_thread(make, work, work / "thumb.jpg", hook, market.short(name), (logo or {}).get("path", ""), self.ch["name"], label, tone)
            (work / "thumb.html").unlink(missing_ok=True)
            return str(out), logo
        except Exception as e:  # noqa: BLE001
            log.warning("market: no thumbnail (%s)", e)
            return "", None

    async def report(self, ctx: dict, job: dict) -> AgentResult:
        """A pre-market or post-market Short: the vertical slides with the small disclaimer line on top, no disclaimer card or spoken disclaimer."""
        ch, work, data, kind = self.ch, Path(job["dir"]), job["data"], job["kind"]
        final = await self.film(job, tall=True, top=market.SHORT_NOTE)
        seconds = await asyncio.to_thread(slides.probe, final)
        for f in work.iterdir():
            if f != final and f.name != "captions.srt":
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink(missing_ok=True)
        has = {i["key"] for r in data["regions"] for i in r["items"]}
        tags = ["#StockMarketTamil", "#TamilFinance", "#Nifty", "#GIFTNifty" if kind == "premarket" else "#Sensex"]
        ctx["store"].kv_put(youtube.LOG, Path(job["dir"]).name, {
            "channel": ch["id"], **stamp(job), "format": "short", "kind": kind, "made": time.time(), "title": self.report_title(kind, data["date"]),
            "summary": self.report_summary(kind, data), "hashtags": tags, "script": " ".join(ln["say"] for ln in job["lines"]), "seconds": round(seconds, 1), "file": str(final),
            "source": {"url": "https://www.nseindia.com/", "title": "NSE, Yahoo Finance"}, "date": data["date"].isoformat(), "report": world.plain(data), "keywords": [], "credits": [],
            "music": "", "original": False, "classic": None, "voice": ch.get("voice_engine", "clone"), "voice_qa": job.get("voice_qa"), "model_lines": 0, "indices": sorted(has)})
        if not job.get("review"):                                    # a review video is not "the day's": the real job of the day is still to be made
            ctx["store"].kv_put(DONE, job["key"], {"at": time.time(), "file": str(final)})
        return AgentResult("done", "CUT", f"{youtube.clock(seconds)} {kind} Short for {data['date']:%d %b}")

    async def lesson(self, ctx: dict, job: dict) -> AgentResult:
        """A finance lesson (wide, with the disclaimer card) or lesson Short (vertical, the small disclaimer line on top). The record carries the topic, the official pages used,
        the videos whose transcripts were read ("inspired", never shown in the video or the description) and what the checks dropped."""
        ch, work, short, tp = self.ch, Path(job["dir"]), job["kind"] == "lesson_short", job["tp"]
        final = await self.film(job, tall=True, top=market.SHORT_NOTE) if short else await self.film(job, source="Finance basics")
        seconds = await asyncio.to_thread(slides.probe, final)
        for f in work.iterdir():
            if f != final and f.name != "captions.srt":
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink(missing_ok=True)
        thumb = "" if short else (await self.cover(job, tp["group"].title(), label="FINANCE BASICS"))[0]          # a Short has no custom cover
        tags = lessons.tags(tp, short) + (["#Shorts"] if short else [])
        why: dict[str, int] = {}
        for d in job["dropped"]:
            why[d["why"]] = why.get(d["why"], 0) + 1
        ctx["store"].kv_put(youtube.LOG, work.name, {
            "channel": ch["id"], **stamp(job), "format": "short" if short else "long", "kind": job["kind"], "made": time.time(), "title": job["title"],
            "summary": lessons.summary(tp, job["pages"], job["title"], short, DISCLAIMER), "hashtags": tags, "script": " ".join(ln["say"] for ln in job["lines"]),
            "source": {"url": job["pages"][0]["url"], "title": job["pages"][0]["label"]}, "seconds": round(seconds, 1), "file": str(final), "keywords": [], "credits": [], "music": "",
            "original": False, "classic": None, "voice": ch.get("voice_engine", "clone"), "voice_qa": job.get("voice_qa"), "model_lines": job["kept"], "topic": tp["id"],
            "topic_title": tp["title"], "concept": job.get("concept") or None, "sources": [{"label": p["label"], "url": p["url"]} for p in job["pages"]], "inspired": job["inspired"],
            "lines_proposed": job["proposed"], "lines_dropped": len(job["dropped"]), "dropped_why": why, "angle": job.get("angle") or None, "new_words": job.get("new_words") or {},
            **({"date": job["date"], "window": job["window"]} if short else {"thumb": thumb})})
        if job.get("review"):
            pass
        elif short:
            ctx["store"].kv_put(DONE, job["key"], {"at": time.time(), "file": str(final)})
            old = ctx["store"].kv_get(DONE, f"lessonshort:{tp['id']}") or {}
            ctx["store"].kv_put(DONE, f"lessonshort:{tp['id']}", {"at": time.time(), "concepts": [*(old.get("concepts") or []), job.get("concept") or tp["title"]]})
        else:
            ctx["store"].kv_put(DONE, f"lesson:{tp['id']}", {"at": time.time(), "file": str(final)})
        return AgentResult("done", "CUT", f"{youtube.clock(seconds)} {'Short' if short else 'lesson'} on {tp['title']}")

    async def run(self, ctx: dict) -> AgentResult:
        job = self.job(ctx, "spoken")
        if not job:
            return self.idle()
        if job.get("kind") in ("lesson", "lesson_short"):
            return await self.lesson(ctx, job)
        if job.get("kind") in REPORTS:
            return await self.report(ctx, job)
        ch, work, analysis = self.ch, Path(job["dir"]), job.get("kind") == "analysis"
        result = job["fundamentals"] if analysis else job["result"]
        final = await self.film(job, source=market.analysis_source(result) if analysis else market.source(result))
        seconds = await asyncio.to_thread(slides.probe, final)
        for f in work.iterdir():                                          # the pictures and working audio are large; the video, its captions file and its log entry stay
            if f != final and f.name != "captions.srt":
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink(missing_ok=True)
        quarter = nse.quarter(date.fromisoformat(result["ttm_to"])) if analysis else job["quarter"]
        thumb, logo = await self.cover(job, result["name"], job["symbol"], "FUNDAMENTALS" if analysis else f"{quarter} RESULTS")
        credit = logos.credit(logo)
        if analysis:
            tags = ["#" + job["symbol"], "#FundamentalAnalysis", "#StockMarketTamil", "#NSE", "#TamilFinance"]
            title, summary = self.analysis_title(result, job["ratios"]), self.analysis_summary(result, job.get("price"), tags, credit)
            source = {"url": result["sources"][0], "title": market.analysis_source(result)}
            extra = {"ratios": [{k: r[k] for k in ("key", "label", "value", "unit")} for r in job["ratios"]], "price_date": (job.get("price") or {}).get("date")}
        else:
            tags = ["#" + job["symbol"], "#" + result["quarter"].replace(" ", "") + "Results", "#StockMarketTamil", "#NSE", "#TamilFinance"]
            title = self.title(result)
            used = {r["doc"]["url"]: r["doc"] for r in job.get("reasons") or []}               # only a document a reason came from is credited
            news_kept = [{k: n.get(k) for k in ("title", "source", "link", "at")} for n in job.get("news") or []]
            summary = self.result_summary(result, tags, list(used.values()), news_kept, credit)
            source, extra = {"url": result["source"], "title": market.source(result)}, {
                "reasons": [{k: r[k] for k in ("metric", "direction", "point", "quote", "doc")} for r in job.get("reasons") or []], "news": news_kept,
                "key_ratios": [{k: r[k] for k in ("key", "label", "value", "unit", "note")} for r in job.get("key_ratios") or []]}
        ctx["store"].kv_put(youtube.LOG, Path(job["dir"]).name, {
            "channel": ch["id"], **stamp(job), "format": "long", "kind": job.get("kind", "result"), "made": time.time(), "title": title, "summary": summary,
            "hashtags": tags, "script": " ".join(ln["say"] for ln in job["lines"]), "source": source, "seconds": round(seconds, 1),
            "file": str(final), "symbol": job["symbol"], "quarter": quarter, "keywords": [], "credits": [], "music": "", "original": False, "classic": None,
            "voice": ch.get("voice_engine", "clone"), "voice_qa": job.get("voice_qa"), "model_lines": job["kept"], "thumb": thumb,
            "new_words": tamil_say.learned_in(" ".join(ln["say"] for ln in job["lines"])),
            "logo": {k: logo[k] for k in ("source", "licence", "artist") if logo.get(k)} if logo else None, **extra})
        if not job.get("review"):
            ctx["store"].kv_put(DONE, job["key"], {"at": time.time(), "file": str(final)})
        return AgentResult("done", "CUT", f"{youtube.clock(seconds)} video for {job['symbol']} {quarter}")


class MarketUploader(youtube.Uploader):
    """Uploads a finished video as PRIVATE with no release time, then asks Mani. Approved ones (decided while YouTube was not signed in
    included) are scheduled here on the next run."""
    name, tier, note = "Market Uploader", "API", "uploads private, asks you, schedules the release"
    blocking = False

    async def run(self, ctx: dict) -> AgentResult:
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        mine = [v for v in store.kv_list(youtube.LOG) if v.get("channel") == ch["id"]]
        ready = [v for v in mine if (v.get("status") == "ready" or (v.get("status") == "review" and v.get("review") and not v.get("video_id"))) and Path(v.get("file") or "").exists()]
        owed = [v for v in mine if v.get("status") == "awaiting" and v.get("approved") and v.get("video_id")]
        if not ready and not owed:
            return AgentResult("idle", "IDLE", "Nothing to upload")
        acct = youtube.account(ch)
        try:
            token = await youtube.oauth.access_token(acct, "youtube")
        except youtube.oauth.AuthNeeded:
            port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
            bus.notice(f"auth:{acct}", f"Sign in to YouTube for {ch['name']}", f"http://127.0.0.1:{port}/auth/youtube/login?account={acct}")
            return AgentResult("wait", "SIGN IN", f"{len(ready) + len(owed)} video(s) waiting: sign in to YouTube for {ch['name']}")
        bus.clear_notice(f"auth:{acct}")
        done = []
        for rec in owed:
            key = rec.pop("_key")
            rec.pop("_ts", None)
            done.append(f"“{rec['title']}”: " + await youtube.publish_approved(ctx, ch, key, rec, self.opts.get("client_factory")))
        async with self.client() as c:
            for rec in sorted(ready, key=lambda v: v["made"])[:ch["uploads_per_run"]]:
                try:
                    out = await self._upload(ctx, c, token, rec)
                except youtube.UploadLimit:
                    bus.notice(f"youtube-limit-{ch['id']}", f"{ch['name']}: YouTube itself is refusing uploads for now (its own cap per channel per day). "
                                                            "The finished video is kept and goes up on a later run. Nothing to do.")
                    return AgentResult("wait", "UPLOAD LIMIT", "YouTube's daily upload limit reached; the video waits")
                bus.clear_notice(f"youtube-limit-{ch['id']}")
                if rec.get("format") == "long" and Path(rec.get("thumb") or "-").exists():          # a long video's cover (a Short cannot take one); a refusal is a note
                    try:
                        bus.say(f"{ch['name']} · “{rec['title']}”: " + await youtube.set_thumbnail(c, {"Authorization": f"Bearer {token}"}, {**rec, "video_id": out["id"]}))
                    except (httpx.HTTPError, OSError) as e:
                        log.warning("market: thumbnail upload failed (%s)", e)
                key = rec.pop("_key")
                rec.pop("_ts", None)
                if rec.get("review"):                          # for Mani to watch: private, no release time, no approval; it stays `review` until he deletes it on YouTube
                    rec.update(status="review", video_id=out["id"], url=f"https://youtu.be/{out['id']}", uploaded=time.time(), publish_at=None)
                    store.kv_put(youtube.LOG, key, rec)
                    bus.say(f"{ch['name']} · “{rec['title']}” is uploaded as private for your review")
                    done.append(f"“{rec['title']}” uploaded private for review")
                    continue
                if rec.get("kind") in youtube.SHORT_KINDS:     # a report Short: `report_privacy` scheduled goes public by itself; one too late for its news stays private, "stale"
                    stale = youtube.short_when(rec, youtube._now()) is None        # (a lesson Short is never published without approval, only held back when it is stale)
                    if stale or (ch["report_privacy"] == "scheduled" and rec["kind"] in youtube.REPORT_KINDS):
                        rec.update(status="stale" if stale else "scheduled", stale=stale, video_id=out["id"], url=f"https://youtu.be/{out['id']}", uploaded=time.time(),
                                   publish_at=None if stale else out["publish_at"])
                        store.kv_put(youtube.LOG, key, rec)
                        if stale:
                            bus.say(f"{ch['name']} · “{rec['title']}” was too late to publish; it stays private")
                        else:
                            bus.say(f"{ch['name']} · “{rec['title']}” goes public " + datetime.fromtimestamp(rec["publish_at"], IST).strftime("%H:%M IST"))
                        done.append(f"“{rec['title']}” uploaded private, {'stale' if stale else 'goes public by itself'}")
                        continue
                rec.update(status="awaiting", video_id=out["id"], url=f"https://youtu.be/{out['id']}", uploaded=time.time(), publish_at=None)
                store.kv_put(youtube.LOG, key, rec)
                if ch["privacy"] == "scheduled" and rec.get("format") == "long" and rec.get("kind") not in youtube.LESSON_KINDS:
                    # Mani, 2026-10-14, after reviewing one of every kind: results and analysis go out with no review, at the next 10:00 IST slot
                    said = await youtube.publish_approved(ctx, ch, key, rec, self.opts.get("client_factory"))
                    bus.say(f"{ch['name']} · “{rec['title']}”: {said}")
                    done.append(f"“{rec['title']}” uploaded, {said[0].lower() + said[1:]}")
                    continue
                request_approval(ctx, self.name, f"Publish: {rec['title']}", {
                    "kind": "yt_publish", "key": f"yt_publish:{out['id']}", "channel": ch["id"], "record": key, "video_id": out["id"],
                    "url": f"https://studio.youtube.com/video/{out['id']}/edit", "watch": f"https://youtu.be/{out['id']}", "title": rec["title"], "summary": rec["summary"], "seconds": rec["seconds"],
                    "source": rec["source"]["url"], "video": rec.get("kind"), "new_words": rec.get("new_words") or {}, "sources": rec.get("sources") or [],
                    "backed": [f"{r['metric']}: {r['point']} (\u201c{r['quote']}\u201d, {r['doc']['subject']})" for r in rec.get("reasons") or []] + [f"news: {n['title']} ({n['source']})" for n in rec.get("news") or []]
                    + [f"source: {x['label']} {x['url']}" for x in rec.get("sources") or []] + [f"inspired by: {i['title']} ({i['channel']})" for i in rec.get("inspired") or []]
                    + ([f"new words for the voice (check by ear): {', '.join(f'{k} = {v}' for k, v in rec['new_words'].items())}"] if rec.get("new_words") else [])})
                bus.say(f"{ch['name']} · “{rec['title']}” is uploaded as private: your approval schedules it")
                done.append(f"“{rec['title']}” uploaded private, awaiting your approval")
        return AgentResult("done", "UPLOADED", "; ".join(done))


class MarketAnalytics(youtube.AnalyticsManager):
    """Follows the channel's videos (scheduled ones going public, deleted ones) and reports one line to the Director."""
    name, tier, note = "Market Analytics", "API", "follows each video, reports the channel"
    blocking = False

    async def run(self, ctx: dict) -> AgentResult:
        ch, store = self.ch, ctx["store"]
        mine = [v for v in store.kv_list(youtube.LOG) if v.get("channel") == ch["id"]]
        if mine:
            await self._refresh(ctx, mine)          # an awaiting video is left alone: it is not in the statuses followed until it is scheduled
        mine = [v for v in store.kv_list(youtube.LOG) if v.get("channel") == ch["id"]]
        insights = learn(mine)
        store.kv_put(youtube.STATE, f"{ch['id']}:insights", insights)
        top = insights["top"]
        line = youtube.peer_line(store, ch) + (f"; best kind: {top['kind']}, {top['per_day']:g} views a day" if top else "")
        return AgentResult("done", "LOGGED", line, {"channel": ch["id"], "made": len(mine), "awaiting": sum(v.get("status") == "awaiting" for v in mine), "insights": insights,
                                                    "videos": [{k: v.get(k) for k in ("title", "status", "url", "seconds", "stats", "source")} for v in mine[:20]]})


def crew(ch: dict, **opts: Any) -> list[Stage]:
    return [Stage("PLAN", [ResultsScout(ch, **opts)]), Stage("DATA", [MarketAnalyst(ch, **opts)]), Stage("SCRIPT", [TanglishWriter(ch, **opts)]),
            Stage("VOICE", [VoiceClone(ch, **opts)]), Stage("EDIT", [SlideEditor(ch, **opts)]), Stage("UPLOAD", [MarketUploader(ch, **opts)]),
            Stage("REPORT", [MarketAnalytics(ch, **opts)])]
