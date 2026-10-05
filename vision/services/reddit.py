"""Reddit through its official API (app-only sign-in): the top text posts of a subreddit.

Needs a free "script" app from https://www.reddit.com/prefs/apps -> REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET in .env.
Read-only; no scraping of the website.
"""

from __future__ import annotations

import time

import httpx

from ..config import secret

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
UA = "vision-assistant/1.0 (personal, read-only)"
_token: tuple[float, str] | None = None


class RedditNotConfigured(Exception):
    pass


def configured() -> bool:
    return bool(secret("REDDIT_CLIENT_ID") and secret("REDDIT_CLIENT_SECRET"))


async def _access(c: httpx.AsyncClient) -> str:
    global _token
    if _token and _token[0] > time.time():
        return _token[1]
    if not configured():
        raise RedditNotConfigured("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET missing in .env")
    r = await c.post(TOKEN_URL, data={"grant_type": "client_credentials"}, headers={"User-Agent": UA},
                     auth=(secret("REDDIT_CLIENT_ID"), secret("REDDIT_CLIENT_SECRET")))
    r.raise_for_status()
    d = r.json()
    _token = (time.time() + int(d.get("expires_in", 3600)) - 60, d["access_token"])
    return _token[1]


async def top(c: httpx.AsyncClient, sub: str, period: str = "week", limit: int = 25) -> list[dict]:
    """Text posts only, best first: {id, title, text, url, score, sub, nsfw}."""
    tok = await _access(c)
    r = await c.get(f"{API}/r/{sub}/top", params={"t": period, "limit": limit, "raw_json": 1},
                    headers={"Authorization": f"Bearer {tok}", "User-Agent": UA})
    r.raise_for_status()
    out = []
    for ch in r.json().get("data", {}).get("children", []):
        p = ch.get("data", {})
        if p.get("stickied") or not (p.get("selftext") or "").strip() or p.get("selftext") in ("[removed]", "[deleted]"):
            continue
        out.append({"id": p["id"], "title": p.get("title", ""), "text": p["selftext"].strip(), "score": p.get("score", 0),
                    "url": "https://www.reddit.com" + p.get("permalink", ""), "sub": p.get("subreddit", sub), "nsfw": bool(p.get("over_18"))})
    return out
