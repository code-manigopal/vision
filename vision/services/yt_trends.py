"""What is being watched most on YouTube today: the "most popular" chart for a region, overall and for a few categories.

Read with the channel's own sign-in (one quota unit a call). Most of the chart is music and gaming, so it is context to
draw on when something truly connects, never a list to imitate.
"""

from __future__ import annotations

import httpx

URL = "https://www.googleapis.com/youtube/v3/videos"
CATEGORIES = (None, "28", "22", "26")      # overall, Science & Technology, People & Blogs, Howto & Style


async def popular(c: httpx.AsyncClient, token: str, region: str = "US", per: int = 15) -> list[dict]:
    """[{title, tags, category}] without repeats; a category the region has no chart for is skipped."""
    out, seen = [], set()
    for cat in CATEGORIES:
        params = {"part": "snippet", "chart": "mostPopular", "regionCode": region, "maxResults": per}
        if cat:
            params["videoCategoryId"] = cat
        try:
            r = await c.get(URL, params=params, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError:
            continue
        if r.status_code != 200:
            continue
        for i in r.json().get("items", []):
            sn = i.get("snippet") or {}
            if i.get("id") in seen or sn.get("defaultAudioLanguage", "en")[:2] not in ("en",):
                continue
            seen.add(i.get("id"))
            out.append({"title": " ".join(str(sn.get("title") or "").split())[:120], "tags": [str(t)[:40] for t in (sn.get("tags") or [])[:12]], "category": cat or "all"})
    return out
