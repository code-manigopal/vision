"""The public transcripts of a few finance videos, read as raw material for a lesson's topic, angle and viewers' questions: never for wording, never for facts.

Mani's own call (2026-10-14), against YouTube's terms of service, on the same footing as his LinkedIn call. The limits are in code and stay (CLAUDE.md):
no cookies, no sign-in, no proxy; at most `cap` videos a day (default 10), at least `gap` seconds apart; any sign of a block (YouTube's request-blocked,
IP-blocked or too-many-requests answers, an HTTP 429) stops transcript reading for the rest of that day (kv `mm_state` `transcripts`), and nothing retries.
A video with no transcript is simply skipped. The `youtube-transcript-api` package does the fetching; tests pass their own `fetch`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

STATE = "mm_state"
GAP = 5.0                                    # seconds between two videos
LANGS = ("en", "en-IN", "ta", "hi")          # the transcript language preferred, in order
log = logging.getLogger("vision.market")


class Blocked(Exception):
    """YouTube refused (or rate-limited) the request: stop reading transcripts today."""


def fetch_library(video_id: str) -> str:
    """The transcript's text, joined. Raises Blocked on a block; returns "" when there is no transcript. No cookies, no proxy, no sign-in: the library's default."""
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        got = YouTubeTranscriptApi().fetch(video_id, languages=list(LANGS))
    except Exception as e:  # noqa: BLE001 - the library has many error types; only a block matters
        name = type(e).__name__.lower()
        if any(k in name for k in ("blocked", "toomanyrequests")) or "429" in str(e) or "too many requests" in str(e).lower() or "request blocked" in str(e).lower():
            raise Blocked(type(e).__name__) from e
        return ""
    return " ".join(s.text for s in got).strip()


def state(store, today: date) -> dict:
    got = store.kv_get(STATE, "transcripts") or {}
    return got if got.get("day") == today.isoformat() else {"day": today.isoformat(), "count": 0, "blocked": False}


async def read(store, videos: list[dict], cap: int = 10, today: date | None = None, fetch=None, gap: float = GAP, sleep=asyncio.sleep) -> list[dict]:
    """Transcripts of `videos` (most viewed first, as given), at most what is left of today's `cap`. Each result is the video dict plus "text" and "url".
    A block stops the day: the state is saved and what was read so far is returned."""
    today, fetch = today or date.today(), fetch or fetch_library
    st, out = state(store, today), []
    for v in videos:
        if st["blocked"] or st["count"] >= cap:
            break
        if out:
            await sleep(gap)
        st["count"] += 1
        try:
            text = await asyncio.to_thread(fetch, v["id"])
        except Blocked as e:
            st["blocked"] = True
            log.warning("market: YouTube blocked transcript reading (%s); none more today", e)
            break
        if text and text.strip():
            out.append({**v, "text": text, "url": f"https://www.youtube.com/watch?v={v['id']}"})
    store.kv_put(STATE, "transcripts", st)
    return out
