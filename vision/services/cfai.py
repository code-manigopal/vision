"""Cloudflare Workers AI: drawing (FLUX.2 klein) and looking at a picture (a vision model), inside the free allowance.

The free plan gives 10,000 neurons a day, reset at 00:00 UTC; past that Cloudflare answers 429 (no bill on the free
plan). Every call here is costed from Cloudflare's price table and written to kv `cfai` `neurons:<UTC date>`, so a
caller can stop before the allowance runs out (`left`). A 429 marks the day spent.

Credentials: CLOUDFLARE_API_TOKEN (with Workers AI permission) and CLOUDFLARE_ACCOUNT_ID, the same ones the Web
Designer uses for Pages.
"""

from __future__ import annotations

import base64
import io
import math
from datetime import datetime, timezone

import httpx

from ..config import secret

DRAW = "@cf/black-forest-labs/flux-2-klein-4b"
LOOK = "@cf/meta/llama-3.2-11b-vision-instruct"
FREE = 10_000
NS = "cfai"
TILE = 26.05                 # neurons per 512x512 output tile, flux-2-klein-4b (Cloudflare pricing page, 2026-10-14)
LOOK_COST = 20               # a 768 px picture (~1,600 tokens in) and a short answer, rounded up


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


def left(store, budget: int = FREE) -> float:
    return max(0.0, budget - used(store))


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
        _spend(store, FREE)
        raise Spent("Cloudflare says today's free allowance is used up")
    if r.status_code != 200:
        raise CFError(f"draw {r.status_code}: {r.text[:200]}")
    _spend(store, cost)
    img = ((r.json().get("result") or {}).get("image")) if "json" in r.headers.get("content-type", "") else None
    if img is None:
        return r.content
    return base64.b64decode(img)


def _jpeg(png: bytes, side: int = 768) -> str:
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im.thumbnail((side, side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


async def look(store, png: bytes, question: str, *, budget: int = FREE, client: httpx.AsyncClient | None = None) -> str:
    """Ask the vision model about a picture; returns its text answer."""
    if left(store, budget) < LOOK_COST:
        raise Spent(f"{used(store):.0f} of {budget} neurons used today")
    body = {"model": LOOK, "max_tokens": 300, "temperature": 0,
            "messages": [{"role": "user", "content": [{"type": "text", "text": question},
                                                      {"type": "image_url", "image_url": {"url": _jpeg(png)}}]}]}
    async with client or httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{_base()}/v1/chat/completions", headers=_h(), json=body)
        if r.status_code != 200 and "agree" in r.text.lower():
            # Meta's licence for this model is accepted once per account by sending "agree"
            await c.post(f"{_base()}/run/{LOOK}", headers=_h(), json={"prompt": "agree"})
            r = await c.post(f"{_base()}/v1/chat/completions", headers=_h(), json=body)
    if r.status_code == 429:
        _spend(store, FREE)
        raise Spent("Cloudflare says today's free allowance is used up")
    if r.status_code != 200:
        raise CFError(f"look {r.status_code}: {r.text[:200]}")
    _spend(store, LOOK_COST)
    return ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
