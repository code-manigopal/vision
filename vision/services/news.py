"""News gathering from RSS. Free, no keys.

Default source is Google News RSS search, which mixes many outlets per topic (good for balance).
Add any publisher's RSS feed per category in config.yaml -> masters.news.options.extra_feeds.
"""

from __future__ import annotations

import asyncio
import calendar
import re
import time
from urllib.parse import quote_plus

import feedparser
import httpx

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) VISION/0.3"}
EDITIONS = {"IN": ("en-IN", "IN", "IN:en"), "CA": ("en-CA", "CA", "CA:en"), "US": ("en-US", "US", "US:en")}


def google_news_url(query: str, edition: str = "CA") -> str:
    hl, gl, ceid = EDITIONS.get(edition, EDITIONS["CA"])
    return f"https://news.google.com/rss/search?q={quote_plus(query + ' when:1d')}&hl={hl}&gl={gl}&ceid={ceid}"


def _clean_title(title: str, source: str) -> str:
    # Google News titles look like "Headline - Source"
    if source and title.endswith(" - " + source):
        title = title[: -len(source) - 3]
    return re.sub(r"\s+", " ", title).strip()


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower())[:70]


async def fetch_feed(client: httpx.AsyncClient, url: str, max_age_hours: float) -> list[dict]:
    r = await client.get(url, headers=UA, follow_redirects=True)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    cutoff = time.time() - max_age_hours * 3600
    items = []
    for e in feed.entries:
        ts = calendar.timegm(e.published_parsed) if e.get("published_parsed") else time.time()
        if ts < cutoff:
            continue
        src = (e.get("source") or {}).get("title") or feed.feed.get("title", "")
        items.append({"title": _clean_title(e.get("title", ""), src), "source": src, "link": e.get("link", ""), "ts": ts})
    return items


async def gather(query: str | None, edition: str, extra_feeds: list[str] | None = None,
                 *, max_age_hours: float = 30, limit: int = 6) -> list[dict]:
    urls = ([google_news_url(query, edition)] if query else []) + list(extra_feeds or [])
    if not urls:
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        results = await asyncio.gather(*(fetch_feed(client, u, max_age_hours) for u in urls), return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    if len(errors) == len(results):
        raise RuntimeError(f"all feeds failed ({errors[0]})")
    seen, out = set(), []
    for item in sorted((i for r in results if not isinstance(r, Exception) for i in r), key=lambda x: -x["ts"]):
        k = _key(item["title"])
        if k and k not in seen:
            seen.add(k)
            out.append(item)
    return out[:limit]
