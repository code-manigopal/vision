"""Ask engine: you talk, the model decides which masters to call, VISION answers like a person.

POST /api/ask {"text": "...", "session": "..."} ->
  {"say": spoken reply, "steps": [[master, agent, action, result], ...], "chips": [...], "fallback": bool}

The model only reads what the masters already report (fast, no extra API cost) except for a few
live lookups (route traffic, city traffic, weather for other cities). Approving something by voice
works only when your own words clearly say so ("yes, send it", "approve").
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .services import traffic_api, weather
from .services.llm import LLMUnavailable

log = logging.getLogger("vision.ask")

SYSTEM = """You are VISION, {owner}'s personal assistant. You are talking out loud, so:
- Sound like a person: warm, relaxed, short. Contractions. Round numbers ("about 50 minutes", "up a little").
- 1 to 3 sentences unless asked for detail. No lists, no markdown, no emoji, no percent signs read out awkwardly.
- Lead with what needs {owner}. Skip routine things unless asked.
- Never guess facts: use the tools. If a tool says something isn't set up, say so plainly and briefly.
- End with a question only when there's a natural next step (e.g. "Want me to read the draft?").
- {greet}
Home: {home}. Local time: {now}."""

TOOLS = [
    {"name": "status_overview", "description": "What every master reported, plus what needs the user (approvals, logins). Use for 'how are we doing', 'what's up', 'what did I miss'.", "parameters": {"type": "object", "properties": {}}},
    {"name": "route_traffic", "description": "Live drive time between two places.", "parameters": {"type": "object", "properties": {"origin": {"type": "string"}, "destination": {"type": "string"}}, "required": ["destination"]}},
    {"name": "city_traffic", "description": "Live traffic incidents in a city.", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}},
    {"name": "weather", "description": "Weather now and forecast. day_offset 0=today, 1=tomorrow, up to 15.", "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "day_offset": {"type": "integer"}}}},
    {"name": "calendar_day", "description": "Events on a day. day_offset 0=today, 1=tomorrow.", "parameters": {"type": "object", "properties": {"day_offset": {"type": "integer"}}}},
    {"name": "email_summary", "description": "Inbox digest: what needs attention, drafts waiting.", "parameters": {"type": "object", "properties": {}}},
    {"name": "read_draft", "description": "The text of a reply draft waiting for approval.", "parameters": {"type": "object", "properties": {"index": {"type": "integer"}}}},
    {"name": "portfolio", "description": "Yesterday's portfolio P&L per account and total in CAD.", "parameters": {"type": "object", "properties": {}}},
    {"name": "markets", "description": "NIFTY, BANK NIFTY, NIFTY IT, NYSE, NASDAQ, Bitcoin moves.", "parameters": {"type": "object", "properties": {}}},
    {"name": "news", "description": "Top headlines. topic: india_markets, global_markets, cricket, politics, or all.", "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}}},
    {"name": "master_report", "description": "Latest report from one master: jobs, web, world, trading, email, calendar, invest, news, traffic.", "parameters": {"type": "object", "properties": {"master": {"type": "string"}}, "required": ["master"]}},
    {"name": "pending_approvals", "description": "Things waiting for the user's OK, with ids.", "parameters": {"type": "object", "properties": {}}},
    {"name": "decide_approval", "description": "Approve or reject a pending item. Only when the user's latest message explicitly says so.", "parameters": {"type": "object", "properties": {"id": {"type": "integer"}, "decision": {"type": "string", "enum": ["approved", "rejected"]}}, "required": ["id", "decision"]}},
]

STEP = {"status_overview": ("VISION", "Router"), "route_traffic": ("TRAFFIC DESK", "Traffic Poller"), "city_traffic": ("TRAFFIC DESK", "Incident Scout"),
        "weather": ("NEWS DESK", "Weather Agent"), "calendar_day": ("CALENDAR MANAGER", "Calendar Reader"), "email_summary": ("EMAIL MANAGER", "Summarizer"),
        "read_draft": ("EMAIL MANAGER", "Writer"), "portfolio": ("INVESTMENTS", "Daily P&L Reporter"), "markets": ("INVESTMENTS", "Index Tracker"),
        "news": ("NEWS DESK", "News Summarizer"), "master_report": ("VISION", "Master report"), "pending_approvals": ("VISION", "Approvals"),
        "decide_approval": ("VISION", "Approval gate")}
EXPLICIT_OK = re.compile(r"\b(approve|approved|send it|go ahead|yes|yep|yeah|accept|confirm|do it|reject|decline|don't send|cancel)\b", re.I)


class AskEngine:
    def __init__(self, orch) -> None:
        self.orch, self.bus, self.store, self.cfg, self.llm = orch, orch.bus, orch.store, orch.cfg, orch.llm
        self.sessions: dict[str, dict] = {}

    def _session(self, sid: str) -> dict:
        s = self.sessions.get(sid)
        if not s or time.time() - s["at"] > 1800:  # 30 min of silence starts a fresh conversation
            s = {"messages": [], "at": time.time(), "greeted": False}
            self.sessions[sid] = s
        s["at"] = time.time()
        return s

    async def ask(self, text: str, sid: str = "default") -> dict:
        s = self._session(sid)
        tz = ZoneInfo(self.cfg.vision.timezone)
        now = datetime.now(tz)
        greet = "Start with a short greeting for the time of day using his name." if not s["greeted"] else "Don't greet again; you're mid-conversation."
        system = SYSTEM.format(owner=self.cfg.vision.owner, greet=greet, home=self.cfg.vision.home_city, now=now.strftime("%A %H:%M"))
        msgs = s["messages"][-12:] + [{"role": "user", "content": text}]
        steps: list[list[str]] = []
        try:
            for _ in range(4):  # up to 4 rounds of tool use
                out = await self.llm.chat(msgs, system=system, tools=TOOLS, tier="local", max_tokens=400)
                if not out["tool_calls"]:
                    break
                msgs.append(out["raw_assistant"])
                for call in out["tool_calls"]:
                    result = await self._run_tool(call["name"], call["args"], text)
                    m, a = STEP.get(call["name"], ("VISION", call["name"]))
                    steps.append([m, a, call["name"].replace("_", " "), _short(result)])
                    msgs.append({"role": "tool", "id": call["id"], "name": call["name"], "content": json.dumps(result, default=str)[:3000]})
            else:
                out = await self.llm.chat(msgs, system=system, tier="local", max_tokens=300)
        except LLMUnavailable:
            return {"fallback": True}
        except Exception as e:
            log.exception("ask failed")
            return {"fallback": True, "error": str(e)}
        say = re.sub(r"[*_#`]", "", out["text"]).strip() or "Sorry, I lost my train of thought. Could you say that again?"
        s["messages"] = (msgs + [{"role": "assistant", "content": say}])[-14:]
        s["greeted"] = True
        chips = sorted({st[0] for st in steps}) or ["VISION"]
        return {"say": say, "steps": steps, "chips": chips, "fallback": False}

    # ---------- tools ----------
    async def _run_tool(self, name: str, args: dict, user_text: str) -> Any:
        st, rd = self.bus.state, self.bus.state.get("report_data", {})
        tz = ZoneInfo(self.cfg.vision.timezone)
        try:
            if name == "status_overview":
                return {"reports": {m.name: st["reports"].get(m.id, "no report yet") for m in self.orch.masters if m.enabled},
                        "needs_you": [a["title"] for a in self.store.pending_approvals()] + [n["text"] for n in st.get("notices", {}).values()]}
            if name == "route_traffic":
                return await traffic_api.route(args.get("origin") or self.cfg.vision.home_city, args["destination"])
            if name == "city_traffic":
                return await traffic_api.get_city_traffic(args["city"])
            if name == "weather":
                off = int(args.get("day_offset") or 0)
                city = args.get("city") or self.cfg.vision.home_city
                w = (rd.get("news") or {}).get("weather")
                if not w or (args.get("city") and args["city"].split(",")[0].lower() not in w["city"].lower()):
                    w = await weather.forecast(city, self.cfg.vision.timezone)
                d = w["daily"][min(off, len(w["daily"]) - 1)] if w.get("daily") else {}
                return {"city": w["city"], "now": f"{w['temp']}°C {w['words']}" if off == 0 else None, "day": d}
            if name == "calendar_day":
                evs = (self.store.kv_get("calendar", "events") or {}).get("events", [])
                day = (datetime.now(tz) + timedelta(days=int(args.get("day_offset") or 0))).date()
                out = [e for e in evs if _local(e["start"], tz).date() == day]
                return {"date": str(day), "events": [{"title": e["title"], "start": "all day" if e.get("all_day") else _local(e["start"], tz).strftime("%H:%M")} for e in out]} \
                    if self.store.kv_get("calendar", "events") else {"note": "Calendar isn't connected yet"}
            if name == "email_summary":
                return rd.get("email") or {"note": "Email isn't connected yet"}
            if name == "read_draft":
                drafts = (rd.get("email") or {}).get("drafts") or []
                i = int(args.get("index") or 0)
                return drafts[i] if i < len(drafts) else {"note": "No drafts waiting"}
            if name == "portfolio":
                return {"ports": (rd.get("invest") or {}).get("ports"), "report": st["reports"].get("invest")}
            if name == "markets":
                return {"markets": (rd.get("invest") or {}).get("mkts")}
            if name == "news":
                hl = (rd.get("news") or {}).get("headlines") or []
                topic = (args.get("topic") or "all").lower()
                tag = {"india_markets": "INDIA MKT", "global_markets": "GLOBAL", "cricket": "CRICKET", "politics": "POLITICS"}.get(topic)
                return [h for h in hl if not tag or h["tag"] == tag][:4]
            if name == "master_report":
                mid = args["master"].lower().split()[0]
                return {"report": st["reports"].get(mid, "no report yet"), "data": rd.get(mid)}
            if name == "pending_approvals":
                return [{"id": a["id"], "master": a["master"], "title": a["title"]} for a in self.store.pending_approvals()]
            if name == "decide_approval":
                if not EXPLICIT_OK.search(user_text):
                    return {"error": "Not done: ask the user to confirm explicitly first."}
                row = self.store.decide_approval(int(args["id"]), args["decision"])
                if not row:
                    return {"error": "Already decided or not found"}
                self.bus.publish({"type": "approval_decided", "id": row["id"], "decision": args["decision"]})
                return {"ok": True, "title": row["title"], "decision": args["decision"]}
        except Exception as e:
            return {"error": str(e)}
        return {"error": f"unknown tool {name}"}


def _local(s: str, tz: ZoneInfo) -> datetime:
    if len(s) == 10:
        return datetime.fromisoformat(s).replace(tzinfo=tz)
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d.astimezone(tz) if d.tzinfo else d.replace(tzinfo=tz)


def _short(result: Any) -> str:
    if isinstance(result, dict):
        if "error" in result:
            return "unavailable"
        if "note" in result:
            return "not set up"
        if "minutes" in result:
            return f"{result['minutes']} min"
    if isinstance(result, list):
        return f"{len(result)} items"
    return "done"
