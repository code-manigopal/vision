"""Pictures for animated Shorts: a free, legally safe image of the thing being talked about (NASA, Wikimedia Commons), a country's flag, and Tabler icons.

space / geography: NASA Image Library, photos only, third-party items skipped. body: Wikimedia Commons, only licences usable in a video without share-alike
(public domain, CC0, CC BY). Results are cached under data/visuals/<kind>/ with an index (a miss is remembered MISS_DAYS). Commons gets at most one request a second
and a User-Agent naming VISION. Any network error gives None, never an exception.
"""

from __future__ import annotations

import asyncio
import html
import io
import json
import re
import time
from pathlib import Path

import httpx

from . import nasa_media

ROOT = Path(__file__).resolve().parent.parent.parent
ROOT_DIR = ROOT / "data" / "visuals"
ICON_DIR = ROOT / "assets" / "icons"
UA = {"User-Agent": "VISION/1.0 (personal YouTube channels; contact via the channel; https://commons.wikimedia.org/wiki/Commons:API) python-httpx"}
COMMONS = "https://commons.wikimedia.org/w/api.php"
MISS_DAYS = 14
MIN_SIDE = 600
GAP = 1.0
STOP = {"the", "a", "an", "of", "and", "in", "on", "from", "to", "for", "with", "how", "why", "what", "is", "are", "human"}
GOOD = ("global", "full", "view", "true color", "true colour", "natural color", "enhanced color", "portrait", "juno", "hubble", "cassini", "webb")
BAD = ("voyager", "pioneer", "galileo", "black and white", "filter", "infrared", "ultraviolet", "spectr", "artist", "concept", "illustration", "diagram", "chart", "conference", "briefing", "launch", "team")
NO_PERSON = re.compile(r"patient|surgery|surgeon|operation|autopsy|corpse|cadaver", re.I)
OK_LICENCE = re.compile(r"^(public domain|pd\b|pd-|cc0|cc[- ]by[- ](1\.0|2\.0|2\.5|3\.0|4\.0)\b)", re.I)
IMG_EXT = ("jpg", "jpeg", "png", "webp")

ICONS = tuple("""sun moon moon-stars planet rocket flame snowflake temperature temperature-sun temperature-snow droplet droplets heart heartbeat brain lungs eye ear bone dna virus
microscope atom cloud cloud-rain cloud-storm wind mountain world map-pin map compass ruler clock hourglass bolt magnet telescope question-mark exclamation-mark arrow-up arrow-down
arrow-right arrow-left arrows-exchange scale star stars satellite ufo meteor comet sunrise sunset sparkles flask test-pipe vaccine pill stethoscope bandage first-aid-kit
heart-rate-monitor activity ear-off mood-smile mood-sad mood-happy bulb zzz bed moon-2 barbell run walk apple salad meat egg bread cookie cup glass-full hand-stop hand-finger
fingerprint baby-carriage man woman users user globe building-skyscraper home tree trees leaf plant flower seeding ripple sailboat ship plane car train beach flag flag-3 route
directions navigation location pin radar-2 battery plug sun-high sun-low sunset-2 haze mist rainbow tornado umbrella ruler-measure calculator percentage chart-bar chart-line
trending-up trending-down math-function infinity number-1 number-2 number-3 gauge weight lock key shield check x plus minus alert-triangle info-circle bug biohazard radioactive
lamp flare circle-dashed""".split())


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]


def slug(text: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", text.lower()))[:60] or "x"


def plain(v: object) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", str(v or ""))).split())


# ---- cache -------------------------------------------------------------------------------------------------------------
def _index() -> dict:
    try:
        return json.loads((ROOT_DIR / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(key: str, rec: dict | None) -> None:
    try:
        idx = _index()
        idx[key] = rec if rec else {"miss": time.time()}
        ROOT_DIR.mkdir(parents=True, exist_ok=True)
        (ROOT_DIR / "index.json").write_text(json.dumps(idx, indent=1), encoding="utf-8")
    except OSError:
        pass


def _cached(key: str) -> tuple[bool, dict | None]:
    rec = _index().get(key)
    if not rec:
        return False, None
    if "miss" in rec:
        return (True, None) if time.time() - rec["miss"] < MISS_DAYS * 86400 else (False, None)
    return (True, rec) if Path(rec.get("path", "")).exists() else (False, None)


def _size(data: bytes) -> tuple[int, int]:
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def _store(kind: str, name: str, data: bytes, ext: str, **meta) -> dict | None:
    try:
        w, h = _size(data)
        d = ROOT_DIR / kind
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{slug(name)}.{ext}"
        p.write_bytes(data)
        return {"path": str(p), "w": w, "h": h, **meta}
    except Exception:
        return None


async def _download(c: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        r = await c.get(url, headers=UA, follow_redirects=True)
        return r.content if r.status_code == 200 and r.content else None
    except Exception:
        return None


# ---- NASA --------------------------------------------------------------------------------------------------------------
def score(title: str, subject: str) -> float | None:
    """None when the title lacks a significant word of the subject; else a points total (higher is better)."""
    t = title.lower()
    need = words(subject)
    if need and not all(w in t for w in need):
        return None
    s = sum(2 for g in GOOD if g in t) - sum(4 for b in BAD if re.search(rf"\b{b}", t))
    return s - len(t) / 400


async def _nasa_candidates(c: httpx.AsyncClient, subject: str) -> list[tuple[float, dict]]:
    try:
        r = await c.get(f"{nasa_media.API}/search", params={"q": subject, "media_type": "image", "page_size": 30}, headers=UA)
        items = (r.json().get("collection") or {}).get("items") or [] if r.status_code == 200 else []
    except Exception:
        return []
    out = []
    for it in items:
        d = (it.get("data") or [{}])[0]
        if d.get("media_type") != "image" or not d.get("nasa_id") or nasa_media.third_party(d):
            continue
        s = score(d.get("title") or "", subject)
        if s is not None:
            out.append((s, d))
    out.sort(key=lambda x: -x[0])
    return out


# The best NASA photo of the main bodies, picked by eye (2026-10-19): searched titles alone gave a black-and-white Jupiter and a Saturn chart.
# A subject naming one of these words gets that photo first; anything else is searched as before.
CURATED = {"sun": "GSFC_20171208_Archive_e001936", "mercury": "PIA10398", "venus": "S91-50688", "earth": "GSFC_20171208_Archive_e001386",
           "mars": "PIA00407", "jupiter": "PIA02873", "saturn": "PIA05983", "uranus": "PIA18182", "neptune": "PIA01492", "io": "PIA01063"}


def curated(subject: str) -> str | None:
    mine = set(words(subject))
    return next((nid for name, nid in CURATED.items() if name in mine), None)


async def _nasa(c: httpx.AsyncClient, kind: str, subject: str, queries: list[str]) -> dict | None:
    pool = [(1e9, {"nasa_id": curated(subject), "title": subject})] if curated(subject) else []
    for q in queries:
        pool += await _nasa_candidates(c, q)
    seen = set()
    pool = [x for x in sorted(pool, key=lambda x: -x[0]) if not (x[1]["nasa_id"] in seen or seen.add(x[1]["nasa_id"]))]
    for _ in [0]:
        for _, d in pool[:8]:
            nid = d["nasa_id"]
            try:
                r = await c.get(f"{nasa_media.API}/asset/{nid}", headers=UA)
                hrefs = [i.get("href") or "" for i in (r.json().get("collection") or {}).get("items") or []] if r.status_code == 200 else []
            except Exception:
                continue
            url = nasa_media.pick(hrefs, "photo")
            if not url or any(x in url for x in ("~thumb", "~small")):
                continue
            data = await _download(c, url)
            if not data:
                continue
            ext = url.rsplit(".", 1)[-1].lower()
            rec = await asyncio.to_thread(_store, kind, subject, data, ext, credit="NASA", page=f"https://images.nasa.gov/details/{nid}",
                                          source="NASA", license="Public domain (NASA)", title=plain(d.get("title")))
            if rec and min(rec["w"], rec["h"]) >= MIN_SIDE:
                return rec
    return None


# ---- Wikimedia Commons -------------------------------------------------------------------------------------------------
async def _commons(c: httpx.AsyncClient, params: dict, last: list) -> dict:
    wait = GAP - (time.monotonic() - last[0])
    if wait > 0:
        await asyncio.sleep(wait)
    last[0] = time.monotonic()
    try:
        r = await c.get(COMMONS, params={**params, "format": "json"}, headers=UA)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def licence_ok(short: str) -> bool:
    s = short.strip()
    return bool(OK_LICENCE.match(s)) and not re.search(r"-sa\b|\bsa\b|share|gfdl|\bnc\b|non", s, re.I)


async def _imageinfo(c, titles: list[str], width: int, last) -> list[dict]:
    d = await _commons(c, {"action": "query", "titles": "|".join(titles), "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
                           "iiurlwidth": width}, last)
    pages = list((d.get("query") or {}).get("pages", {}).values())
    return pages


LIKE = ("diagram", "anatomy", "illustration", "bioart", "labeled", "labelled", "scheme", "en.svg", "-en.")
UNLIKE = ("autopsy", "model", "wellcome", "veterinary", "canid", "porpoise", "frog", "snail", "dog", "cat", "pig", "cow", "x-ray", "xray", "ct ", "mri", "histology", "pathological", "museum", "stamp", "painting")
LANG = re.compile(r"[-_ ](fa|ar|et|zh|ru|de|fr|es|it|ja|ko|pl|pt|tr|uk|he|hi|bn|sv|nl|cs|id|vi|th)\.(svg|png|jpg)$", re.I)


def title_score(title: str, subject: str) -> float | None:
    t = title.lower()
    if t.rsplit(".", 1)[-1] not in ("svg", "png", "jpg", "jpeg") or NO_PERSON.search(t) or LANG.search(t):
        return None
    if not all(w in t for w in words(subject)):
        return None
    return sum(2 for k in LIKE if k in t) - sum(3 for k in UNLIKE if re.search(rf"\b{re.escape(k.strip())}", t))


async def _from_commons(c, kind: str, name: str, queries: list[str], subject: str, width: int = 1080) -> dict | None:
    last = [0.0]
    pool: dict[str, float] = {}
    for q in queries:
        d = await _commons(c, {"action": "query", "list": "search", "srsearch": q, "srnamespace": 6, "srlimit": 12}, last)
        for i, s in enumerate((d.get("query") or {}).get("search", [])):
            sc = title_score(s["title"], subject)
            if sc is not None and s["title"] not in pool:
                pool[s["title"]] = sc - i * 0.05
    order = sorted(pool, key=lambda t: -pool[t])[:8]
    if not order:
        return None
    for p in sorted(await _imageinfo(c, order, width, last), key=lambda p: -pool.get(p.get("title"), -99)):
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        lic = plain((meta.get("LicenseShortName") or {}).get("value"))
        if not ii.get("thumburl") or not licence_ok(lic):
            continue
        data = await _download(c, ii["thumburl"])
        if not data:
            continue
        ext = ii["thumburl"].split("?")[0].rsplit(".", 1)[-1].lower()
        if ext not in IMG_EXT:
            continue
        artist = plain((meta.get("Artist") or {}).get("value")) or "Unknown author"
        rec = await asyncio.to_thread(_store, kind, name, data, ext, credit=f"{artist} (Wikimedia Commons)", page=ii.get("descriptionurl") or "",
                                      source="Wikimedia Commons", license=lic, title=p.get("title", ""))
        if rec and min(rec["w"], rec["h"]) >= 300:
            return rec
    return None


# ---- public API --------------------------------------------------------------------------------------------------------
async def picture(c: httpx.AsyncClient, kind: str, subject: str) -> dict | None:
    key = f"{kind}|{' '.join(words(subject))}"
    hit, rec = _cached(key)
    if hit:
        return rec
    try:
        if kind == "space":
            rec = await _nasa(c, kind, subject, [subject, f"{subject} true color"])
        elif kind == "geography":
            rec = await _nasa(c, kind, subject, [subject, f"{subject} from space", f"{subject} astronaut photograph"])
        elif kind == "body":
            rec = await _from_commons(c, kind, subject, [f"{subject} anatomy", f"{subject} diagram", f"{subject} illustration"], subject)
        else:
            return None
    except Exception:
        return None
    _save(key, rec)
    return rec


async def flag(c: httpx.AsyncClient, country: str) -> dict | None:
    key = f"flag|{' '.join(words(country))}"
    hit, rec = _cached(key)
    if hit:
        return rec
    try:
        last = [0.0]
        title = f"File:Flag of {country.strip()}.svg"
        for p in await _imageinfo(c, [title], 600, last):
            ii = (p.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata") or {}
            lic = plain((meta.get("LicenseShortName") or {}).get("value"))
            if ii.get("thumburl") and licence_ok(lic):
                data = await _download(c, ii["thumburl"])
                if data:
                    rec = await asyncio.to_thread(_store, "flag", country, data, "png", credit=f"{plain((meta.get('Artist') or {}).get('value')) or 'Unknown author'} (Wikimedia Commons)",
                                                  page=ii.get("descriptionurl") or "", source="Wikimedia Commons", license=lic, title=p.get("title", ""))
                    break
    except Exception:
        rec = None
    _save(key, rec)
    return rec


async def icon(c: httpx.AsyncClient, name: str) -> Path | None:
    if name not in ICONS:
        return None
    p = ICON_DIR / f"{name}.svg"
    if p.exists():
        return p
    data = await _download(c, f"https://cdn.jsdelivr.net/npm/@tabler/icons@3.19.0/icons/outline/{name}.svg")
    if not data or b"<svg" not in data:
        return None
    try:
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p
    except OSError:
        return None
