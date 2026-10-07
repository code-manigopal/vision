"""What people type into YouTube's search box: its own suggestions for a phrase.

The public suggestion endpoint behind the search box (no key). It shows real demand: the phrases YouTube completes
a search with are the ones people search most. Unofficial, so a failure simply returns nothing.
"""

from __future__ import annotations

import httpx

URL = "https://suggestqueries.google.com/complete/search"


async def suggest(c: httpx.AsyncClient, phrase: str) -> list[str]:
    try:
        r = await c.get(URL, params={"client": "firefox", "ds": "yt", "q": phrase})
        d = r.json() if r.status_code == 200 else []
        return [str(s) for s in d[1]][:10] if isinstance(d, list) and len(d) > 1 and isinstance(d[1], list) else []
    except (httpx.HTTPError, ValueError):
        return []
