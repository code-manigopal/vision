"""Cloudflare Workers AI: drawing (FLUX.2 klein) and looking at a picture (a vision model), inside the free allowance.

The free plan gives 10,000 neurons a day, reset at 00:00 UTC; past that Cloudflare answers 429 (no bill on the free
plan). Every call here is costed from Cloudflare's price table and written to kv `cfai` `neurons:<UTC date>`, so a
caller can stop before the allowance runs out (`left`). A 429 pauses every call for PAUSE seconds (kv `cfai` `pause`):
Cloudflare's reset was seen to lag past 00:00 UTC, so a refusal is asked again later rather than written off for the day.

Credentials: CLOUDFLARE_API_TOKEN (with Workers AI permission) and CLOUDFLARE_ACCOUNT_ID, the same ones the Web
Designer uses for Pages.
"""

from __future__ import annotations

import base64
import io
import math
import time
from datetime import datetime, timezone

import httpx

from ..config import secret

DRAW = "@cf/black-forest-labs/flux-2-klein-4b"
LOOK = "@cf/meta/llama-3.2-11b-vision-instruct"
FREE = 10_000
NS = "cfai"
TILE = 26.05                 # neurons per 512x512 output tile, flux-2-klein-4b (Cloudflare pricing page, 2026-10-14)
LOOK_COST = 20               # a 768 px picture (~1,600 tokens in) and a short answer, rounded up
PAUSE = 30 * 60


class Spent(Exception):
    """Today's free allowance is used up (or would be by this call)."""


class CFError(Exception):
    pass


def _base() -> str:
    acc = secret("CLOUDFLARE_ACCOUNT_ID")
    if not (acc and secret("CLOUDFLARE_API_TOKEN")):
        raise CFError("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID are not set")
    return f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai"


def _h() -> dict:
    return {"Authorization": f"Bearer {secret('CLOUDFLARE_API_TOKEN')}"}


def day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def used(store) -> float:
    return float((store.kv_get(NS, f"neurons:{day()}") or {}).get("n", 0))


def paused(store) -> bool:
    return (store.kv_get(NS, "pause") or {}).get("until", 0) > time.time()


def left(store, budget: int = FREE) -> float:
    return 0.0 if paused(store) else max(0.0, budget - used(store))


def _refused(store) -> None:
    store.kv_put(NS, "pause", {"until": time.time() + PAUSE})


def _spend(store, n: float) -> None:
    store.kv_put(NS, f"neurons:{day()}", {"n": used(store) + n})


def draw_cost(w: int, h: int) -> float:
    return math.ceil(w / 512) * math.ceil(h / 512) * TILE


async def draw(store, prompt: str, w: int, h: int, seed: int, *, budget: int = FREE, client: httpx.AsyncClient | None = None) -> bytes:
    """One picture from FLUX.2 klein -> PNG/JPEG bytes. Raises Spent before a call the allowance can't cover."""
    cost = draw_cost(w, h)
    if left(store, budget) < cost:
        raise Spent(f"{used(store):.0f} of {budget} neurons used today")
    form = {"prompt": (None, prompt), "width": (None, str(w)), "height": (None, str(h)), "seed": (None, str(seed))}
    async with client or httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{_base()}/run/{DRAW}", headers=_h(), files=form)
    if r.status_code == 429:
        _refused(store)
        raise Spent("Cloudflare says the free allowance is used up; asking again in 30 minutes")
    if r.status_code != 200:
        raise CFError(f"draw {r.status_code}: {r.text[:200]}")
    _spend(store, cost)
    img = ((r.json().get("result") or {}).get("image")) if "json" in r.headers.get("content-type", "") else None
    if img is None:
        return r.content
    return base64.b64decode(img)


def _jpeg(png: bytes, side: int = 768) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im.thumbnail((side, side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


async def look(store, png: bytes, question: str, *, budget: int = FREE, client: httpx.AsyncClient | None = None) -> str:
    """Ask the vision model about a picture (any format PIL reads); returns its text answer. Workers AI's own endpoint with `prompt` and the
    JPEG's bytes: the OpenAI-style one answers 400 "Unable to add image" to an image_url message (found 2026-10-19, never run live before)."""
    if left(store, budget) < LOOK_COST:
        raise Spent(f"{used(store):.0f} of {budget} neurons used today")
    body = {"prompt": question, "image": list(_jpeg(png)), "max_tokens": 300, "temperature": 0}
    async with client or httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{_base()}/run/{LOOK}", headers=_h(), json=body)
        if r.status_code != 200 and "agree" in r.text.lower():
            # Meta's licence for this model is accepted once per account by sending "agree"
            await c.post(f"{_base()}/run/{LOOK}", headers=_h(), json={"prompt": "agree"})
            r = await c.post(f"{_base()}/run/{LOOK}", headers=_h(), json=body)
    if r.status_code == 429:
        _refused(store)
        raise Spent("Cloudflare says the free allowance is used up; asking again in 30 minutes")
    if r.status_code != 200:
        raise CFError(f"look {r.status_code}: {r.text[:200]}")
    res = r.json().get("result") or {}
    _spend(store, float((res.get("usage") or {}).get("neurons") or LOOK_COST))
    return str(res.get("response") or "")
