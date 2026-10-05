"""Background music: a small library on disk, one folder per mood, filled from Openverse.

    assets/bgm/<mood>/<track>.mp3   the track (drop your own files in too)
    assets/bgm/<mood>/<track>.json  its credit: title, creator, licence, page (written for fetched tracks)

`fetch` searches Openverse for music whose licence allows commercial use and adaptation without share-alike
(CC0, public domain, CC BY) and keeps instrumental tracks only: nothing sung goes under a narration.
`pick` gives the Editor a track for a mood, a different one each time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from ..config import ROOT

DIR = ROOT / "assets" / "bgm"
API = "https://api.openverse.org/v1/audio/"
UA = {"User-Agent": "vision-assistant/1.0 (personal)"}
QUERIES = {"dark": ["dark ambient", "suspense", "mystery"], "sad": ["sad piano", "melancholy", "emotional strings"],
           "warm": ["hopeful piano", "warm acoustic", "peaceful"], "light": ["playful", "happy ukulele", "quirky"],
           "dramatic": ["dramatic cinematic", "tension", "epic orchestral"]}
SUNG = {"vocal", "vocals", "male", "female", "voice", "singer", "lyrics", "rap", "choir"}
AUDIO = (".mp3", ".m4a", ".wav", ".ogg", ".flac")


def instrumental(hit: dict) -> bool:
    tags = {str(t.get("name", "")).lower() for t in hit.get("tags") or [] if isinstance(t, dict)}
    return "instrumental" in tags and not tags & SUNG


def credit(hit: dict) -> dict:
    lic = f"CC {hit.get('license', '').upper()} {hit.get('license_version') or ''}".strip().replace("CC CC0", "CC0").replace("CC PDM", "Public domain")
    return {"title": hit.get("title") or "Untitled", "creator": hit.get("creator") or "unknown", "license": lic,
            "license_url": hit.get("license_url") or "", "page": hit.get("foreign_landing_url") or "", "openverse_id": hit.get("id")}


def line(c: dict | None) -> str:
    """The credit as it goes in a video description."""
    return f"“{c['title']}” by {c['creator']} ({c['license']}) {c.get('page', '')}".strip() if c else ""


async def search(c: httpx.AsyncClient, query: str, page_size: int = 20) -> list[dict]:
    r = await c.get(API, params={"q": query + " instrumental", "license": "cc0,pdm,by", "category": "music", "page_size": page_size}, headers=UA)
    if r.status_code != 200:
        raise RuntimeError(f"Openverse said {r.status_code}: {r.text[:120]}")
    return [h for h in r.json().get("results", []) if instrumental(h) and 60_000 <= (h.get("duration") or 0) <= 600_000 and h.get("url")]


async def fetch(mood: str, count: int = 3, client: httpx.AsyncClient | None = None) -> list[dict]:
    """Add up to `count` new tracks to a mood's folder. Returns the credits of what was saved."""
    folder = DIR / mood
    folder.mkdir(parents=True, exist_ok=True)
    have = {json.loads(p.read_text()).get("openverse_id") for p in folder.glob("*.json")}
    saved: list[dict] = []
    async with (client or httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True)) as c:
        for q in QUERIES.get(mood, [mood]):
            for hit in await search(c, q):
                if len(saved) >= count:
                    return saved
                if hit["id"] in have:
                    continue
                r = await c.get(hit["url"], headers=UA)
                if r.status_code != 200 or len(r.content) < 100_000:
                    continue
                cr = credit(hit)
                stem = re.sub(r"[^a-z0-9]+", "-", f"{cr['title']} {cr['creator']}".lower()).strip("-")[:60] or hit["id"]
                (folder / f"{stem}.mp3").write_bytes(r.content)
                (folder / f"{stem}.json").write_text(json.dumps(cr, indent=1, ensure_ascii=False))
                have.add(hit["id"])
                saved.append(cr)
    return saved


def tracks(mood: str) -> list[Path]:
    folder = DIR / mood
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO) if folder.exists() else []


def pick(mood: str, turn: int = 0) -> tuple[Path, dict | None] | None:
    """A track for the mood; `turn` (how many Shorts have used this mood) moves through the folder so two in a row differ."""
    found = tracks(mood)
    if not found:
        return None
    p = found[turn % len(found)]
    side = p.with_suffix(".json")
    try:
        return p, json.loads(side.read_text()) if side.exists() else None
    except json.JSONDecodeError:
        return p, None
