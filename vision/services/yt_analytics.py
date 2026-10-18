"""YouTube Analytics API v2 (read-only): how each of the channel's own videos is really watched.

Views alone say little about a Short; what YouTube rewards is how much of it people watch. Per video this reads views,
engaged views (where the API has them), average view duration, average percentage viewed and subscribers gained.
Needs the `yt-analytics.readonly` permission on the channel's sign-in and "YouTube Analytics API" enabled on the Google app.
Figures lag by about two days.
"""

from __future__ import annotations

import time

import httpx

API = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPE = "yt-analytics.readonly"
FULL = "views,engagedViews,averageViewDuration,averageViewPercentage,subscribersGained,likes,shares"
BASIC = "views,averageViewDuration,averageViewPercentage,subscribersGained,likes,shares"       # if engagedViews is refused
NAMES = {"views": "views", "engagedViews": "engaged", "averageViewDuration": "avg_sec", "averageViewPercentage": "avg_pct",
         "subscribersGained": "subs", "likes": "likes", "shares": "shares"}


class AnalyticsError(Exception):
    pass


async def per_video(c: httpx.AsyncClient, token: str, ids: list[str], start: str = "2020-01-01", end: str | None = None) -> dict[str, dict]:
    """{video id: {views, engaged?, avg_sec, avg_pct, subs, likes, shares}} over start..end (lifetime by default), 200 ids a call."""
    end = end or time.strftime("%Y-%m-%d")
    out: dict[str, dict] = {}
    metrics = FULL
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        while True:
            r = await c.get(API, params={"ids": "channel==MINE", "startDate": start, "endDate": end, "metrics": metrics, "dimensions": "video",
                                         "filters": "video==" + ",".join(chunk), "maxResults": 200, "sort": "-views"},
                            headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 400 and metrics == FULL:           # engagedViews not offered here: the rest still tells the story
                metrics = BASIC
                continue
            break
        if r.status_code != 200:
            try:
                why = r.json()["error"]["message"]
            except Exception:
                why = r.text[:160]
            raise AnalyticsError(f"YouTube Analytics said {r.status_code}: {why}")
        d = r.json()
        cols = [h["name"] for h in d.get("columnHeaders", [])]
        for row in d.get("rows") or []:
            rec = dict(zip(cols, row))
            out[rec["video"]] = {NAMES[k]: (round(float(v), 1) if k == "averageViewPercentage" else int(v)) for k, v in rec.items() if k in NAMES}
    return out
