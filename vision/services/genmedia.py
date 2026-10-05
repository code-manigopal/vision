"""Footage Generator providers: the place where an online AI image or video API plugs in.

A provider is one async function registered under a name:

    @provider("myservice")
    async def myservice(c, spec, prompt, out, kind, seconds) -> Path: ...   # writes the file at `out`, returns it

and is chosen per channel in config.yaml (masters.youtube.options.channels[].generator):

    generator: { provider: myservice, kind: image, model: "...", key_env: MYSERVICE_API_KEY }

`spec` is that dict; the key itself stays in .env and is read with spec_key(spec). No provider is set by default,
so nothing is generated and stock footage is all a video uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

import httpx

from ..config import secret

PROVIDERS: dict[str, Callable[..., Awaitable[Path]]] = {}


class NotConfigured(Exception):
    pass


def provider(name: str):
    def register(fn):
        PROVIDERS[name] = fn
        return fn
    return register


def spec_key(spec: dict) -> str | None:
    return secret(spec.get("key_env") or "")


def ready(spec: dict | None) -> bool:
    spec = spec or {}
    return bool(spec.get("provider") in PROVIDERS and (not spec.get("key_env") or spec_key(spec)))


async def generate(c: httpx.AsyncClient, spec: dict | None, prompt: str, out: Path, *, kind: str = "image", seconds: float = 5) -> Path:
    """Make one vertical (9:16) image or clip for the prompt and save it at `out`."""
    if not ready(spec):
        raise NotConfigured("No AI footage provider is set (channel option generator.provider)")
    return await PROVIDERS[spec["provider"]](c, spec, prompt, out, kind, seconds)
