"""LLM router.

- local: LM Studio's OpenAI-compatible server (config.yaml -> llm.local_base_url / local_model).
- cloud: Anthropic Messages API (ANTHROPIC_API_KEY in .env; config llm.cloud_model).
- writer: an OpenAI-compatible hosted model for long-form writing (GROQ_API_KEY in .env; config llm.writer_model).
  Falls back to cloud, then local.

Every caller asks for a tier ("local" for high-volume work, "cloud" for deep reasoning) and gets
automatic fallback: cloud -> local if no key, local -> cloud if LM Studio is down. If neither is
available, calls raise LLMUnavailable and agents fall back to their rule-based behaviour.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

import httpx

from . import groq_budget
from ..config import Config, secret

log = logging.getLogger("vision.llm")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class LLMUnavailable(Exception):
    pass


class LLM:
    def __init__(self, cfg: Config, client_factory=None) -> None:
        self.cfg = cfg
        self._client = client_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(120.0)))
        self._local_ok: tuple[float, bool] | None = None
        self.used = 0                                    # tokens the hosted writer has counted for this process (Groq's free day is 200,000): callers can compare before and after

    # ---------- availability ----------
    async def local_available(self) -> bool:
        from . import lmstudio
        if lmstudio.set_aside():                         # unloaded for a video's voice: any request would make LM Studio load it again
            return False
        if self._local_ok and time.time() - self._local_ok[0] < 60:
            return self._local_ok[1]
        ok = False
        try:
            async with self._client() as c:
                r = await c.get(self.cfg.llm.local_base_url.rstrip("/") + "/models", timeout=3)
                ok = r.status_code == 200
        except Exception:
            ok = False
        self._local_ok = (time.time(), ok)
        return ok

    def cloud_available(self) -> bool:
        return bool(secret("ANTHROPIC_API_KEY") and self.cfg.llm.cloud_model)

    def writer_available(self) -> bool:
        return bool(secret("GROQ_API_KEY") and self.cfg.llm.writer_model)

    async def pick(self, tier: str) -> str:
        order = ["writer", "cloud", "local"] if tier == "writer" else ["cloud", "local"] if tier == "cloud" else ["local", "cloud"]
        for t in order:
            if t == "writer" and self.writer_available():
                return "writer"
            if t == "cloud" and self.cloud_available():
                return "cloud"
            if t == "local" and await self.local_available():
                return "local"
        raise LLMUnavailable("No model available: start LM Studio's server, or add ANTHROPIC_API_KEY and llm.cloud_model")

    # ---------- plain text ----------
    async def complete(self, prompt: str, *, system: str = "", tier: str = "local", max_tokens: int = 800, temperature: float = 0.3, model: str | None = None,
                       who: str = "", cap: int = 0, light: bool = False) -> str:
        """`who` / `cap`: the caller (a channel) and its share of Groq's daily tokens (services/groq_budget.py). `light` marks a small structured step
        a channel may send to the local model (youtube.OwnWriter); here it changes nothing."""
        msgs = [{"role": "user", "content": prompt}]
        out = await self.chat(msgs, system=system, tier=tier, max_tokens=max_tokens, temperature=temperature, model=model, who=who, cap=cap)
        return out["text"]

    async def json(self, prompt: str, *, system: str = "", tier: str = "local", max_tokens: int = 800, model: str | None = None,
                   who: str = "", cap: int = 0, light: bool = False) -> Any:
        text = await self.complete(prompt + "\n\nReply with JSON only, no prose.", system=system, tier=tier, max_tokens=max_tokens, temperature=0, model=model,
                                   who=who, cap=cap)
        return parse_json(text)

    # ---------- chat with tools (OpenAI-style tool schemas) ----------
    async def chat(self, messages: list[dict], *, system: str = "", tools: list[dict] | None = None, tier: str = "local",
                   max_tokens: int = 800, temperature: float = 0.3, model: str | None = None, who: str = "", cap: int = 0) -> dict:
        """`model` names another model on the hosted writer tier (Groq keeps a separate daily allowance per model). Returns {"text": str, "tool_calls": [{"id", "name", "args"}], "raw_assistant": message to append}."""
        which = await self.pick(tier)
        if which == "local":
            return await self._openai(messages, system, tools, max_tokens, temperature)
        if which == "writer":
            # a reasoning model left to itself can spend the whole answer on hidden thinking and return nothing: cap the effort
            extra = {"reasoning_effort": self.cfg.llm.writer_reasoning} if self.cfg.llm.writer_reasoning else {}
            if "qwen" in (model or ""):                  # Qwen3 takes "none" or "default", not "low": left on, its hidden thinking uses the whole answer
                extra = {"reasoning_effort": "none"}
            name = model or self.cfg.llm.writer_model
            need = max_tokens + sum(len(str(m.get("content") or "")) for m in messages) // 4 + len(system) // 4
            stop = groq_budget.why_not(name, need, who, cap, daily=getattr(self.cfg.llm, "groq_daily_tokens", groq_budget.DAILY) or groq_budget.DAILY)
            if stop:                                     # never spend the last of the free allowance (a refused request mid-Short wastes the rest)
                raise LLMUnavailable(stop)
            return await self._openai(messages, system, tools, max_tokens, temperature, base=self.cfg.llm.writer_base_url,
                                      model=name, key=secret("GROQ_API_KEY"), extra=extra, who=who)
        return await self._anthropic(messages, system, tools, max_tokens, temperature)

    async def _openai(self, messages, system, tools, max_tokens, temperature, *, base: str | None = None, model: str | None = None, key: str | None = None, extra: dict | None = None,
                      who: str = "") -> dict:
        body: dict[str, Any] = {"model": model or self.cfg.llm.local_model or "local-model", "max_tokens": max_tokens, "temperature": temperature,
                                "messages": ([{"role": "system", "content": system}] if system else []) + _to_openai(messages)}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        body.update(extra or {})
        for attempt in range(4):
            async with self._client() as c:
                r = await c.post((base or self.cfg.llm.local_base_url).rstrip("/") + "/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {key}"} if key else None)
            if r.status_code != 429 or not key or attempt == 3:
                break
            try:                                   # a hosted model's per-minute allowance: wait as long as it says, then ask again
                wait = float(r.headers.get("retry-after") or 20)
            except ValueError:
                wait = 20
            await asyncio.sleep(min(max(wait, 1), 65))
        r.raise_for_status()
        body_out = r.json()
        if key:
            spent = int((body_out.get("usage") or {}).get("total_tokens") or 0)
            self.used += spent
            groq_budget.record(body["model"], spent, who)
        msg = body_out["choices"][0]["message"]
        calls = [{"id": tc.get("id") or f"call_{i}", "name": tc["function"]["name"],
                  "args": parse_json(tc["function"].get("arguments") or "{}") or {}}
                 for i, tc in enumerate(msg.get("tool_calls") or [])]
        return {"text": (msg.get("content") or "").strip(), "tool_calls": calls, "raw_assistant": {"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls}}

    async def _anthropic(self, messages, system, tools, max_tokens, temperature) -> dict:
        body: dict[str, Any] = {"model": self.cfg.llm.cloud_model, "max_tokens": max_tokens, "temperature": temperature,
                                "messages": _to_anthropic(messages)}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [{"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("parameters", {"type": "object", "properties": {}})} for t in tools]
        headers = {"x-api-key": secret("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"}
        async with self._client() as c:
            r = await c.post(ANTHROPIC_URL, json=body, headers=headers)
        r.raise_for_status()
        content = r.json().get("content", [])
        text = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        calls = [{"id": b["id"], "name": b["name"], "args": b.get("input") or {}} for b in content if b.get("type") == "tool_use"]
        return {"text": text, "tool_calls": calls, "raw_assistant": {"role": "assistant", "content": text, "tool_calls": calls}}


# ---------- message format conversion (one internal format, two providers) ----------
# internal: {"role": "user"|"assistant", "content": str, "tool_calls": [...]} and {"role": "tool", "id", "name", "content"}

def _to_openai(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        if m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["id"], "content": m["content"]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or "",
                        "tool_calls": [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}} for c in m["tool_calls"]]})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def _to_anthropic(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["id"], "content": m["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            blocks = ([{"type": "text", "text": m["content"]}] if m.get("content") else []) + \
                     [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m["tool_calls"]]
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def parse_json(text: str) -> Any:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                return None
    return None
