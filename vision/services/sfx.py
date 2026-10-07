"""Sound effects: a small library on disk, one folder per kind, filled from Openverse.

    assets/sfx/<kind>/<name>.<ext>   the effect (drop your own files in too)
    assets/sfx/<kind>/<name>.json    its credit (written for fetched files)

Only CC0 / public-domain effects are fetched, so no credit line is needed. Each download is checked with ffprobe
(it must decode and have a length) and thrown away if not. `pick` gives the Editor an effect, a different one each time.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import httpx

from ..config import ROOT

DIR = ROOT / "assets" / "sfx"
API = "https://api.openverse.org/v1/audio/"
UA = {"User-Agent": "vision-assistant/1.0 (personal)"}
KINDS = {"ding": ["notification ding", "bell ding", "bright chime"], "whoosh": ["whoosh", "swish", "fast swoosh"],
         "riser": ["riser", "build up", "tension rise"], "pop": ["pop", "click pop", "bubble pop"],
         "impact": ["cinematic impact", "deep boom hit", "dramatic hit"], "heartbeat": ["heartbeat", "heart beat slow"],
         "tick": ["clock ticking", "clock tick"], "drone": ["dark drone", "ominous drone", "suspense drone"],
         "coin": ["coins", "cash register", "coin drop"], "notification": ["phone notification", "message tone", "phone buzz"]}
MAX_SECONDS = {"riser": 6.0, "heartbeat": 6.0, "tick": 6.0, "drone": 8.0}      # the others stop at 4 s
MIN_SECONDS = 0.15
AUDIO = (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aif", ".aiff")


def probe(p: Path) -> float:
    """Length in seconds by ffprobe; 0 if the file doesn't decode."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def credit(hit: dict) -> dict:
    lic = f"CC {hit.get('license', '').upper()} {hit.get('license_version') or ''}".strip().replace("CC CC0", "CC0").replace("CC PDM", "Public domain")
    return {"title": hit.get("title") or "Untitled", "creator": hit.get("creator") or "unknown", "license": lic,
            "page": hit.get("foreign_landing_url") or "", "openverse_id": hit.get("id")}


async def search(c: httpx.AsyncClient, kind: str, query: str) -> list[dict]:
    """Short CC0 / public-domain hits. Openverse leaves most effects uncategorised, so with no result for the
    `sound_effect` category the same search runs without it (the length window keeps music out)."""
    hits: list[dict] = []
    for cat in ({"category": "sound_effect"}, {}):
        r = await c.get(API, params={"q": query, "license": "cc0,pdm", **cat, "page_size": 20}, headers=UA)
        if r.status_code != 200:
            raise RuntimeError(f"Openverse said {r.status_code}: {r.text[:120]}")
        hits = r.json().get("results", [])
        if hits:
            break
    hi = MAX_SECONDS.get(kind, 4.0) * 1000
    return [h for h in hits if MIN_SECONDS * 1000 <= (h.get("duration") or 0) <= hi and h.get("url")]


def _ext(hit: dict) -> str:
    e = (hit.get("filetype") or Path(hit["url"].split("?")[0]).suffix.lstrip(".") or "mp3").lower()
    return "." + e.lstrip(".")


async def fetch(kind: str, count: int = 3, client: httpx.AsyncClient | None = None) -> list[dict]:
    """Add up to `count` new effects to a kind's folder. Returns the credits (with `seconds`) of what was saved."""
    folder = DIR / kind
    folder.mkdir(parents=True, exist_ok=True)
    have = {json.loads(p.read_text()).get("openverse_id") for p in folder.glob("*.json")}
    saved: list[dict] = []
    async with (client or httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True)) as c:
        for q in KINDS.get(kind, [kind]):
            for hit in await search(c, kind, q):
                if len(saved) >= count:
                    return saved
                if hit["id"] in have:
                    continue
                try:
                    r = await c.get(hit["url"], headers=UA)
                except httpx.HTTPError:
                    continue
                if r.status_code != 200 or not r.content:
                    continue
                cr = credit(hit)
                stem = re.sub(r"[^a-z0-9]+", "-", f"{cr['title']} {cr['creator']}".lower()).strip("-")[:60] or hit["id"]
                f = folder / f"{stem}{_ext(hit)}"
                f.write_bytes(r.content)
                secs = probe(f)
                if secs <= 0:
                    f.unlink(missing_ok=True)
                    continue
                cr["seconds"] = round(secs, 2)
                f.with_suffix(".json").write_text(json.dumps(cr, indent=1, ensure_ascii=False))
                have.add(hit["id"])
                saved.append(cr)
    return saved


def tracks(kind: str) -> list[Path]:
    folder = DIR / kind
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO) if folder.exists() else []


def pick(kind: str, turn: int = 0) -> Path | None:
    """An effect of the kind; `turn` moves through the folder so two in a row differ."""
    found = tracks(kind)
    return found[turn % len(found)] if found else None
