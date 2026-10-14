"""A company's logo from Wikimedia Commons, for a video's thumbnail (read-only, a few GETs the first time, then the cached file).

Commons' own API: a file search ("<name> logo", files only), then each candidate's url, licence and description page. A file is accepted only when its title
holds the company's name (every significant word of it) and "logo", is an SVG or PNG, and is not marked old or former. The file goes to data/logos/<SYMBOL>.<ext> with
a <SYMBOL>.json beside it (licence, artist, source page, the time); it is never fetched again. No match is remembered for NONE_DAYS so the search is not repeated each night.
The thumbnail shows the logo as a small identifying mark on the channel's own design; it never imitates the company's material, and the description credits the source page.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
from pathlib import Path

import httpx

log = logging.getLogger("vision.logos")
API = "https://commons.wikimedia.org/w/api.php"
ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "logos"
UA = {"User-Agent": "VISION-personal-assistant/1.0 (personal, non-commercial, a few requests per company, cached; https://commons.wikimedia.org/wiki/Commons:API) python-httpx"}
NONE_DAYS = 30                 # a company with no accepted logo is searched again after this long
MAX_BYTES = 3 << 20
EXT = {"image/svg+xml": "svg", "image/png": "png"}
LEGAL = {"limited", "ltd", "company", "co", "corporation", "corp", "the", "of", "and", "&", "inc", "plc", "pvt", "private"}
OLD = re.compile(r"\b(old|former|previous|legacy|obsolete|historic\w*)\b|\b(19|20)\d\d\b", re.I)      # a logo the company no longer uses (or a dated one)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def accept(title: str, name: str) -> bool:
    """Does a Commons file title hold the company's name (every word of it that is not a legal tail) and "logo", in an SVG or PNG, and not an old logo?"""
    t = re.sub(r"^File:", "", title, flags=re.I)
    ext = t.rsplit(".", 1)[-1].lower() if "." in t else ""
    need = [w for w in words(name) if w not in LEGAL]
    have = set(words(t.rsplit(".", 1)[0]))
    return ext in ("svg", "png") and bool(need) and "logo" in have and all(w in have for w in need) and not OLD.search(t.rsplit(".", 1)[0])


def rank(titles: list[str]) -> list[str]:
    """SVG before PNG, then the search's own order."""
    return sorted(titles, key=lambda t: (not t.lower().endswith(".svg"), titles.index(t)))


def plain(value: object) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).split())


def cached(symbol: str, root: Path | None = None) -> dict | None:
    """The logo already fetched for a symbol: {path, source, licence, artist, title}; {} when the search found none recently; None when nothing is known."""
    root = root or ROOT
    try:
        meta = json.loads((root / f"{symbol}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if meta.get("none"):
        return {} if time.time() - meta.get("at", 0) < NONE_DAYS * 86400 else None
    path = root / f"{symbol}.{meta.get('ext', 'svg')}"
    return {**meta, "path": str(path)} if path.exists() else None


async def find(c: httpx.AsyncClient, symbol: str, name: str, root: Path | None = None, gap: float = 1.0, sleep=asyncio.sleep) -> dict | None:
    """The company's logo as {path, source, licence, artist, title, ext}, or None. Cached; GETs spaced `gap` seconds apart; any failure is None (the thumbnail then carries
    the name in text)."""
    root = root or ROOT
    hit = cached(symbol, root)
    if hit is not None:
        return hit or None
    try:
        r = await c.get(API, params={"action": "query", "list": "search", "srsearch": " ".join(w for w in re.findall(r"[A-Za-z0-9]+", name) if w.lower() not in LEGAL) + " logo", "srnamespace": 6, "srlimit": 10, "format": "json"}, headers=UA)
        r.raise_for_status()
        titles = rank([s["title"] for s in r.json().get("query", {}).get("search", []) if accept(s["title"], name)])[:5]
        meta = None
        if titles:
            await sleep(gap)
            r = await c.get(API, params={"action": "query", "titles": "|".join(titles), "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size", "format": "json"}, headers=UA)
            r.raise_for_status()
            pages = {p["title"]: p for p in r.json().get("query", {}).get("pages", {}).values() if p.get("imageinfo")}
            for t in titles:
                info = (pages.get(t) or {}).get("imageinfo", [{}])[0]
                if info.get("mime") in EXT and info.get("url") and (info.get("size") or 0) <= MAX_BYTES:
                    em = info.get("extmetadata") or {}
                    meta = {"title": t, "ext": EXT[info["mime"]], "url": info["url"], "source": info.get("descriptionurl") or "", "licence": plain((em.get("LicenseShortName") or {}).get("value")),
                            "artist": plain((em.get("Artist") or {}).get("value"))[:120], "symbol": symbol}
                    break
        if meta:
            await sleep(gap)
            r = await c.get(meta["url"], headers=UA)
            r.raise_for_status()
            if len(r.content) > MAX_BYTES:
                meta = None
            else:
                root.mkdir(parents=True, exist_ok=True)
                (root / f"{symbol}.{meta['ext']}").write_bytes(r.content)
                (root / f"{symbol}.json").write_text(json.dumps({**meta, "at": time.time()}, ensure_ascii=False, indent=1), encoding="utf-8")
                return {**meta, "path": str(root / f"{symbol}.{meta['ext']}")}
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{symbol}.json").write_text(json.dumps({"none": True, "at": time.time(), "symbol": symbol}), encoding="utf-8")
    except (httpx.HTTPError, ValueError, KeyError, OSError) as e:
        log.info("logo for %s: %s", symbol, e)
    return None


def credit(logo: dict | None) -> str:
    """The description line crediting a logo (its Commons page and licence); empty when there is none."""
    return f"Logo: {logo['source']}" + (f" ({logo['licence']})" if logo.get("licence") else "") if logo and logo.get("source") else ""
