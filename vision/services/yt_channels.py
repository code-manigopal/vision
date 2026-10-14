"""What the top Indian finance channels published lately and how it is doing: the signal for which lesson topic to make first.

Read-only, the official YouTube Data API. Each call is cheap except a name lookup:
    search.list (100 units)  a channel's name -> its id, once per name, kept forever in kv `mm_state` (never hard-coded)
    channels.list (1)        the channel's uploads playlist, kept with the id
    playlistItems.list (1)   the newest uploads (one page of 50)
    videos.list (1)          their view counts (50 ids a call)
Read at most once a day (`signals`). Auth is an API key when YOUTUBE_API_KEY is set, else the channel's own sign-in token that the caller passes.
Titles are matched to the topic bank with whole-word search words; a topic's score is the recent views per day of the videos that match it.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import httpx

API = "https://www.googleapis.com/youtube/v3"
STATE = "mm_state"
DAY = 86400
RECENT_DAYS = 120                       # a video older than this says little about what people want now
log = logging.getLogger("vision.market")


def words(text: str) -> list[str]:
    """Lower-case whole words (Latin letters and digits, and Tamil letters); punctuation and case do not matter."""
    return re.findall(r"[a-z0-9]+|[஀-௿]+", (text or "").lower())


def matches(title: str, phrases: list[str]) -> bool:
    """Does the title hold, as whole words and in any order, every word of at least one of the search phrases? ("fd vs rd" is found in "RD vs FD: which is better")."""
    have = set(words(title))
    return any(words(p) and set(words(p)) <= have for p in phrases)


def _auth(token: str | None, key: str | None) -> tuple[dict, dict]:
    return ({"key": key}, {}) if key else ({}, {"Authorization": f"Bearer {token}"})


async def _get(c: httpx.AsyncClient, path: str, params: dict, token: str | None, key: str | None) -> dict:
    q, h = _auth(token, key)
    r = await c.get(f"{API}/{path}", params={**params, **q}, headers=h)
    r.raise_for_status()
    return r.json()


async def resolve(c: httpx.AsyncClient, store, name: str, token: str | None = None, key: str | None = None) -> dict | None:
    """{"id", "title", "uploads"} for a channel name, from kv when known (a lookup costs 100 units, so it is made once and the answer kept, a miss too)."""
    slot = f"channel:{name.lower()}"
    got = store.kv_get(STATE, slot)
    if got is not None:
        return got if got.get("id") else None
    hit = (await _get(c, "search", {"part": "snippet", "type": "channel", "q": name, "maxResults": 1}, token, key)).get("items") or []
    if not hit:
        store.kv_put(STATE, slot, {"id": None, "name": name, "at": time.time()})
        return None
    cid = hit[0].get("id", {}).get("channelId") or ""
    title = (hit[0].get("snippet") or {}).get("channelTitle") or name
    det = (await _get(c, "channels", {"part": "contentDetails", "id": cid}, token, key)).get("items") or []
    uploads = (((det[0] if det else {}).get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
    rec = {"id": cid, "name": name, "title": title, "uploads": uploads, "at": time.time()}
    store.kv_put(STATE, slot, rec)
    return rec if cid and uploads else None


async def recent(c: httpx.AsyncClient, ch: dict, token: str | None = None, key: str | None = None) -> list[dict]:
    """The channel's newest uploads with their views: [{id, title, channel, published (ISO), views}]."""
    items = (await _get(c, "playlistItems", {"part": "snippet", "playlistId": ch["uploads"], "maxResults": 50}, token, key)).get("items") or []
    vids = [{"id": (i.get("snippet") or {}).get("resourceId", {}).get("videoId"), "title": (i.get("snippet") or {}).get("title") or "",
             "published": (i.get("snippet") or {}).get("publishedAt") or ""} for i in items]
    vids = [v for v in vids if v["id"]]
    stats = {}
    for n in range(0, len(vids), 50):
        got = await _get(c, "videos", {"part": "statistics", "id": ",".join(v["id"] for v in vids[n:n + 50])}, token, key)
        stats.update({i["id"]: int((i.get("statistics") or {}).get("viewCount") or 0) for i in got.get("items") or []})
    return [{**v, "channel": ch.get("title") or ch["name"], "views": stats.get(v["id"], 0)} for v in vids]


async def signals(c: httpx.AsyncClient, store, names: list[str], token: str | None = None, key: str | None = None, now: float | None = None) -> dict:
    """{"at", "videos": [...], "missing": [names that did not resolve]} for the listed channels, read at most once a day (kv `mm_state` `signals`).
    One channel that fails is skipped (logged), not an error: the topic order then simply has less to go on."""
    now = now or time.time()
    old = store.kv_get(STATE, "signals")
    if old and now - old["at"] < DAY:
        return old
    videos, missing = [], []
    for name in names:
        try:
            ch = await resolve(c, store, name, token, key)
            if not ch:
                missing.append(name)
                continue
            videos += await recent(c, ch, token, key)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            log.warning("market: channel signal for %s failed (%s)", name, e)
    out = {"at": now, "videos": videos, "missing": missing}
    store.kv_put(STATE, "signals", out)
    return out


def per_day(v: dict, now: float) -> float:
    """Views a day since the video came out (at least a day), 0 for one older than RECENT_DAYS or with no readable date."""
    try:
        age = (datetime.fromtimestamp(now, timezone.utc) - datetime.fromisoformat(v["published"].replace("Z", "+00:00"))).total_seconds() / DAY
    except (KeyError, ValueError):
        return 0.0
    return 0.0 if age > RECENT_DAYS else v["views"] / max(age, 1.0)


def score(topic: dict, videos: list[dict], now: float | None = None) -> tuple[float, list[dict]]:
    """(the topic's score, the matching videos most viewed first): the sum of recent views per day of every video whose title matches the topic's search words."""
    now = now or time.time()
    hit = [v for v in videos if matches(v["title"], topic["words"]) and per_day(v, now) > 0]
    return sum(per_day(v, now) for v in hit), sorted(hit, key=lambda v: -v["views"])
