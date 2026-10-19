"""How much of Groq's free daily allowance VISION has used, per model and per user (a channel), so it never runs out.

Groq's free tier gives each model its own daily token allowance (about 200,000) shared by every caller in VISION. A refused
request in the middle of a Short wastes the work already done and can starve the writers that matter most (Know IDK Things,
Mani Market's lessons). So every Groq answer's `usage.total_tokens` is added here (data/groq_usage.json, one UTC day at a
time), and a request is refused before it is sent when it would take the model past `stop_at` of its daily limit, or a
channel past its own `cap` (Mani, 2026-10-19: "make sure groq free limit not exhausted"). A refusal is a wait, not a fault:
callers see LLMUnavailable and the channel's Scout makes no new Short until the next UTC day.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..config import ROOT

FILE = ROOT / "data" / "groq_usage.json"
DAILY = 200_000            # Groq's free tokens a day per model (llm.groq_daily_tokens overrides)


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _load(path: Path | None = None) -> dict:
    p = path or FILE
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        d = {}
    if d.get("day") != _today():                       # a new UTC day: the allowance is back
        d = {"day": _today(), "models": {}, "who": {}}
    return d


def record(model: str, tokens: int, who: str = "", path: Path | None = None) -> None:
    d = _load(path)
    d["models"][model] = d["models"].get(model, 0) + int(tokens)
    if who:
        d["who"][who] = d["who"].get(who, 0) + int(tokens)
    p = path or FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))


def used(model: str, path: Path | None = None) -> int:
    return _load(path)["models"].get(model, 0)


def used_by(who: str, path: Path | None = None) -> int:
    return _load(path)["who"].get(who, 0)


def why_not(model: str, need: int, who: str = "", cap: int = 0, daily: int = DAILY, stop_at: float = 0.95, path: Path | None = None) -> str:
    """"" when a request of about `need` tokens may go; else the reason it may not."""
    d = _load(path)
    if d["models"].get(model, 0) + need > daily * stop_at:
        return f"Groq's daily allowance for {model} is nearly used ({d['models'].get(model, 0):,} of {daily:,}); back after 00:00 UTC"
    if who and cap and d["who"].get(who, 0) + need > cap:
        return f"{who} has used its Groq share for today ({d['who'].get(who, 0):,} of {cap:,} tokens); back after 00:00 UTC"
    return ""
