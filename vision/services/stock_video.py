"""Free stock footage for vertical video: Pexels videos, then Pixabay videos, then a Pexels photo (for pan and zoom).

PEXELS_API_KEY / PIXABAY_API_KEY in .env. Every result keeps its credit and page URL.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from ..config import secret

W, H = 1080, 1920


def configured() -> bool:
    return bool(secret("PEXELS_API_KEY") or secret("PIXABAY_API_KEY"))


def crop_width(w: int, h: int, wide: bool = False) -> float:
    """Width of the region a w x h frame can give: 9:16 for a Short, 16:9 for a wide video."""
    return (min(w, h * 16 / 9) if wide else min(w, h * W / H)) if w and h else 0


def best_file(files: list[dict], wide: bool = False) -> dict | None:
    """The smallest file that still fills the frame's width after the crop (1080 upright, 1920 wide); else the largest usable one."""
    need, least = (1920, 1200) if wide else (W, 700)
    usable = sorted((f for f in files if crop_width(f.get("width") or 0, f.get("height") or 0, wide) >= least),
                    key=lambda f: crop_width(f["width"], f["height"], wide))
    if not usable:
        return None
    return next((f for f in usable if crop_width(f["width"], f["height"], wide) >= need), usable[-1])


async def _get(c: httpx.AsyncClient, url: str, **kw) -> dict:
    try:
        r = await c.get(url, **kw)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


async def _pexels_videos(c, q: str, wide: bool = False) -> list[dict]:
    key = secret("PEXELS_API_KEY")
    if not key:
        return []
    d = await _get(c, "https://api.pexels.com/videos/search", headers={"Authorization": key},
                   params={"query": q, "per_page": 6, "orientation": "landscape" if wide else "portrait"})
    out = []
    for v in d.get("videos", []):
        f = best_file([x for x in v.get("video_files", []) if "mp4" in (x.get("file_type") or "mp4")], wide)
        if f:
            out.append({"id": f"pexels-v{v['id']}", "kind": "video", "url": f["link"], "w": f["width"], "h": f["height"], "duration": v.get("duration") or 0,
                        "credit": f"Video by {(v.get('user') or {}).get('name') or 'unknown'} (Pexels)", "page": v.get("url") or "", "source": "Pexels",
                        "about": re.sub(r"[-/]", " ", (v.get("url") or "").rstrip("/").rsplit("/video/", 1)[-1])})
    return out


async def _pixabay_videos(c, q: str, wide: bool = False) -> list[dict]:
    key = secret("PIXABAY_API_KEY")
    if not key:
        return []
    d = await _get(c, "https://pixabay.com/api/videos/", params={"key": key, "q": q, "per_page": 6, "safesearch": "true"})
    out = []
    for v in d.get("hits", []):
        f = best_file([x for x in (v.get("videos") or {}).values() if x.get("url")], wide)
        if f:
            out.append({"id": f"pixabay-v{v['id']}", "kind": "video", "url": f["url"], "w": f["width"], "h": f["height"], "duration": v.get("duration") or 0,
                        "credit": f"Video by {v.get('user') or 'unknown'} (Pixabay)", "page": v.get("pageURL") or "", "source": "Pixabay", "about": v.get("tags") or ""})
    return out


async def _pexels_photos(c, q: str, wide: bool = False) -> list[dict]:
    key = secret("PEXELS_API_KEY")
    if not key:
        return []
    d = await _get(c, "https://api.pexels.com/v1/search", headers={"Authorization": key}, params={"query": q, "per_page": 6, "orientation": "landscape" if wide else "portrait"})
    return [{"id": f"pexels-p{p['id']}", "kind": "photo", "url": p["src"]["original"] + ("?auto=compress&cs=tinysrgb&w=2600" if wide else "?auto=compress&cs=tinysrgb&h=2400"), "w": p.get("width") or 0,
             "h": p.get("height") or 0, "duration": 0, "credit": f"Photo by {p.get('photographer') or 'unknown'} (Pexels)", "page": p.get("url") or "", "source": "Pexels", "about": p.get("alt") or ""}
            for p in d.get("photos", []) if (p.get("src") or {}).get("original")]


def relevance(hit: dict, query: str, wide: bool = False) -> tuple[int, bool]:
    """How many of the query's words the result's own description has; a frame of the right shape breaks a tie."""
    about = hit.get("about", "").lower()
    return sum(w in about for w in set(re.findall(r"[a-z]{3,}", query.lower()))), (hit["w"] > hit["h"]) if wide else (hit["h"] > hit["w"])


async def find(c: httpx.AsyncClient, query: str, used: set[str], min_seconds: float = 3, wide: bool = False) -> dict | None:
    """The best match for the query not yet used in this video: a clip from either library, else a photo."""
    videos = [h for h in await _pexels_videos(c, query, wide) + await _pixabay_videos(c, query, wide)
              if h["id"] not in used and not (h["duration"] and h["duration"] < min_seconds)]
    hits = videos or [h for h in await _pexels_photos(c, query, wide) if h["id"] not in used]
    if not hits:
        return None
    best = max(hits, key=lambda h: relevance(h, query, wide))
    used.add(best["id"])
    return best


async def photo(c: httpx.AsyncClient, query: str, wide: bool = True) -> dict | None:
    """One photo for the query (a thumbnail's background)."""
    hits = await _pexels_photos(c, query, wide)
    return max(hits, key=lambda h: relevance(h, query, wide)) if hits else None


async def download(c: httpx.AsyncClient, url: str, path: Path) -> Path:
    async with c.stream("GET", url, follow_redirects=True) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            async for chunk in r.aiter_bytes():
                f.write(chunk)
    return path
