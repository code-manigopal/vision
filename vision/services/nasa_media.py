"""Free space footage from NASA's Image and Video Library (images-api.nasa.gov): clips and photos for the space Shorts.

Needs no key. A search lists items; each item's asset manifest gives the file (a small mp4 for a video, a large jpg for a photo),
and at most 6 manifests are asked for per search, videos first. Rights rule: NASA's own media is generally not copyrighted, but
third-party material appears in the library, so an item whose title, description or creator speaks of copyright, (c), "courtesy of"
a party that is not NASA, Getty, Reuters or AP Photo is skipped; when in doubt it is left out. Footage is optional: any error or
non-200 answer gives nothing and never raises.
"""

from __future__ import annotations

import re

import httpx

from .stock_video import relevance

API = "https://images-api.nasa.gov"
MANIFESTS = 6
VIDEO_PREF = ("~mobile.mp4", "~small.mp4", "~medium.mp4", "~orig.mp4")
IMAGE_PREF = ("~large.jpg", "~medium.jpg", "~orig.jpg")
THIRD_PARTY = re.compile(r"copyright|©|\(c\)|getty|reuters|ap photo|courtesy of(?! nasa)", re.I)


def third_party(d: dict) -> bool:
    """True when the item's own text points to material that is not NASA's to give."""
    text = " ".join(str(d.get(k) or "") for k in ("title", "description", "secondary_creator", "photographer"))
    return bool(THIRD_PARTY.search(text))


def pick(hrefs: list[str], kind: str) -> str | None:
    """The preferred file of a manifest, as an https address."""
    for suffix in VIDEO_PREF if kind == "video" else IMAGE_PREF:
        for h in hrefs:
            if h.lower().endswith(suffix):
                return re.sub(r"^http:", "https:", h)
    return None


async def _get(c: httpx.AsyncClient, url: str, **kw) -> dict:
    try:
        r = await c.get(url, **kw)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


async def search(c: httpx.AsyncClient, query: str, wide: bool = False) -> list[dict]:
    """Up to 6 hits for the query, videos first, each with a direct file address."""
    d = await _get(c, f"{API}/search", params={"q": query, "media_type": "video,image", "page_size": 12})
    items = []
    for it in ((d.get("collection") or {}).get("items") or [])[:12]:
        data = (it.get("data") or [{}])[0]
        if data.get("nasa_id") and data.get("media_type") in ("video", "image") and not third_party(data):
            items.append((data, it.get("links") or []))
    items.sort(key=lambda x: x[0]["media_type"] != "video")
    out = []
    for data, links in items[:MANIFESTS]:
        nid, kind = data["nasa_id"], "video" if data["media_type"] == "video" else "photo"
        m = await _get(c, f"{API}/asset/{nid}")
        url = pick([i.get("href") or "" for i in (m.get("collection") or {}).get("items") or []], kind)
        if not url:
            continue
        size = next((l for l in links if l.get("width") and l.get("height")), {})
        out.append({"id": f"nasa-{nid}", "kind": kind, "url": url, "w": int(size.get("width") or 0), "h": int(size.get("height") or 0), "duration": 0,
                    "credit": "NASA", "page": f"https://images.nasa.gov/details/{nid}", "source": "NASA",
                    "about": " ".join([data.get("title") or "", data.get("description") or "", " ".join(data.get("keywords") or [])]).strip()})
    return out


async def find(c: httpx.AsyncClient, query: str, used: set[str], wide: bool = False) -> dict | None:
    """The best match for the query not yet used in this video: a clip, else a photo."""
    hits = [h for h in await search(c, query, wide) if h["id"] not in used]
    hits = [h for h in hits if h["kind"] == "video"] or hits
    if not hits:
        return None
    best = max(hits, key=lambda h: relevance(h, query, wide))
    used.add(best["id"])
    return best
