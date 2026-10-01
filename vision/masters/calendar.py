"""Calendar Manager (live): Calendar Reader -> Conflict Checker -> Scheduler (reporter) + Reminder Agent
-> Email Liaison -> YOU.

Works with the Email Manager: meeting requests the Email Categorizer finds are turned into a proposed
slot; when you approve, the event is created (invites go out) and a short reply is sent.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..agents import AgentResult, SubAgent, request_approval
from ..services import mailcal, oauth
from .email import accounts, login_notice


def _dt(s: str, tz: ZoneInfo) -> datetime:
    if len(s) == 10:  # all-day date
        return datetime.fromisoformat(s).replace(tzinfo=tz)
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=tz)


def free_slot(events: list[dict], tz: ZoneInfo, *, minutes: int = 30, start_hour: int = 9, end_hour: int = 17, days: int = 7) -> datetime | None:
    busy = [(_dt(e["start"], tz), _dt(e["end"], tz)) for e in events if not e.get("all_day")]
    now = datetime.now(tz)
    day = (now + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
    for _ in range(days):
        if day.weekday() < 5:
            t = day
            while t + timedelta(minutes=minutes) <= day.replace(hour=end_hour):
                end = t + timedelta(minutes=minutes)
                if all(end <= b0 or t >= b1 for b0, b1 in busy):
                    return t
                t += timedelta(minutes=30)
        day += timedelta(days=1)
    return None


class CalendarReader(SubAgent):
    name, tier, note = "Calendar Reader", "API", "all calendars · 5 weeks"

    async def run(self, ctx):
        accts = accounts(ctx["options"], "calendar")
        if not accts:
            return AgentResult("idle", "NOT SET UP", "Calendar: add accounts in config.yaml")
        tz = ZoneInfo(ctx["cfg"].vision.timezone)
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
        end = start + timedelta(days=42)
        events, waiting = [], []
        for a in accts:
            try:
                events += await mailcal.list_events(a, start, end, ctx["cfg"].vision.timezone)
                ctx["bus"].clear_notice(f"auth:{a['id']}")
            except oauth.AuthNeeded as e:
                login_notice(ctx, e)
                waiting.append(a["id"])
        events.sort(key=lambda e: _dt(e["start"], tz))
        ctx["events"], ctx["tz"] = events, tz
        ctx["store"].kv_put("calendar", "events", {"events": events, "at": time.time()})
        if waiting and not events:
            return AgentResult("wait", "SIGN IN", "Waiting for you to sign in: " + ", ".join(waiting))
        return AgentResult("done", f"{len(events)} EVENTS", f"{len(events)} events loaded")


class ConflictChecker(SubAgent):
    name, tier, note = "Conflict Checker", "QUICK", "overlaps"

    async def run(self, ctx):
        tz, now = ctx.get("tz"), time.time()
        timed = [e for e in ctx.get("events", []) if not e.get("all_day") and _dt(e["end"], tz).timestamp() > now]
        clashes = []
        for i, a in enumerate(timed):
            for b in timed[i + 1:]:
                if _dt(b["start"], tz) < _dt(a["end"], tz) and _dt(a["start"], tz) < _dt(b["end"], tz):
                    clashes.append(f"{a['title']} ↔ {b['title']} ({_dt(a['start'], tz):%a %H:%M})")
        ctx["clashes"] = clashes
        return AgentResult("done", f"{len(clashes)} CLASHES" if clashes else "CLEAR", "; ".join(clashes[:3]) or "no conflicts", {"clashes": clashes})


class Scheduler(SubAgent):
    name, tier, note = "Scheduler", "QUICK", "today + requests"

    async def run(self, ctx):
        tz = ctx.get("tz") or ZoneInfo(ctx["cfg"].vision.timezone)
        now = datetime.now(tz)
        today = [e for e in ctx.get("events", []) if _dt(e["start"], tz).date() == now.date()]
        upcoming = [e for e in today if not e.get("all_day") and _dt(e["end"], tz) > now]
        pend = [a for a in ctx["store"].pending_approvals() if a["payload"].get("kind") == "meeting_accept"]
        pend += [r for r in ctx["store"].kv_list("meeting_requests") if r.get("status") == "new"]  # the Liaison proposes these next
        parts = [f"{len(today)} today" if today else "nothing today"]
        if upcoming:
            parts.append(f"next {_dt(upcoming[0]['start'], tz):%H:%M} {upcoming[0]['title']}")
        if pend:
            parts.append(f"{len(pend)} request{'s' if len(pend) > 1 else ''} waiting")
        if ctx.get("clashes"):
            parts.append(f"{len(ctx['clashes'])} clash")
        if ctx["results"].get("Calendar Reader") and ctx["results"]["Calendar Reader"].status != "done":
            parts = [ctx["results"]["Calendar Reader"].summary]
        events = [{"title": e["title"], "start": e["start"], "end": e["end"], "all_day": e.get("all_day", False)} for e in ctx.get("events", [])]
        return AgentResult("wait" if pend else "done", f"{len(pend)} WAITING" if pend else "PLANNED", " · ".join(parts),
                           {"events": events, "today": len(today), "pending": len(pend)})


class ReminderAgent(SubAgent):
    name, tier, note = "Reminder Agent", "QUICK", "heads-up before events"

    async def run(self, ctx):
        tz, store = ctx.get("tz"), ctx["store"]
        lead = int(ctx["options"].get("reminder_minutes", 15))
        now, armed = time.time(), 0
        for e in ctx.get("events", []):
            if e.get("all_day"):
                continue
            st = _dt(e["start"], tz).timestamp()
            if now < st - lead * 60 < now + 86400:
                key = f"{e['id']}:{e['start']}"
                if not store.kv_has("reminders", key):
                    store.kv_put("reminders", key, {"at": st - lead * 60, "text": f"⏰ {e['title']} in {lead} min ({_dt(e['start'], tz):%H:%M})", "fired": False})
                armed += 1
        return AgentResult("done", f"{armed} ARMED", f"{armed} reminders set for the next 24h")


class EmailLiaison(SubAgent):
    name, tier, note = "Email Liaison", "QUICK", "meeting requests ↔ Email Manager"

    async def run(self, ctx):
        store, tz = ctx["store"], ctx.get("tz") or ZoneInfo(ctx["cfg"].vision.timezone)
        mins = int(ctx["options"].get("default_meeting_minutes", 30))
        proposed = 0
        for req in store.kv_list("meeting_requests"):
            if req.get("status") != "new":
                continue
            m = req["email"]
            slot = free_slot(ctx.get("events", []), tz, minutes=mins,
                             start_hour=int(ctx["options"].get("work_start", 9)), end_hour=int(ctx["options"].get("work_end", 17)))
            if not slot:
                continue
            end = slot + timedelta(minutes=mins)
            title = f"{m['subject'][:60]}"
            request_approval(ctx, self.name, f"Meeting with {m['from_name'] or m['from']}: {slot:%a %b %d, %H:%M}",
                             {"key": f"meet:{m['id']}", "kind": "meeting_accept", "account": m["account"], "title": title,
                              "start": slot.strftime("%Y-%m-%dT%H:%M:00"), "end": end.strftime("%Y-%m-%dT%H:%M:00"),
                              "attendees": [m["from"]], "email": m})
            req["status"] = "proposed"
            store.kv_put("meeting_requests", m["id"], req)
            proposed += 1
        return AgentResult("wait" if proposed else "done", f"{proposed} PROPOSED" if proposed else "LINKED", f"{proposed} meeting slots proposed")


async def approve_meeting(row: dict, decision: str, ctx: dict) -> str:
    p, cfg = row["payload"], ctx["cfg"]
    req = ctx["store"].kv_get("meeting_requests", p["email"]["id"]) or {"email": p["email"]}
    if decision != "approved":
        req["status"] = "declined"
        ctx["store"].kv_put("meeting_requests", p["email"]["id"], req)
        return "left unscheduled"
    accts = {a["id"]: a for a in accounts(cfg.master("calendar").options, "calendar")}
    acct = accts.get(p["account"]) or next(iter(accts.values()))
    await mailcal.create_event(acct, title=p["title"], start=p["start"], end=p["end"], tz=cfg.vision.timezone, attendees=p["attendees"],
                               description=f"Scheduled by VISION for {cfg.vision.owner}")
    from .email import _send
    when = datetime.fromisoformat(p["start"]).strftime("%A %B %d at %H:%M")
    await _send(ctx, p["account"], p["email"]["from"], "Re: " + p["email"]["subject"],
                f"Hi {p['email']['from_name'].split(' ')[0] if p['email']['from_name'] else ''},\n\n{when} works for me. I've sent you a calendar invite.\n\nBest,\n{cfg.vision.owner}", reply_to=p["email"])
    req["status"] = "booked"
    ctx["store"].kv_put("meeting_requests", p["email"]["id"], req)
    return f"booked {when} and replied"


APPROVAL_HANDLERS = {"meeting_accept": approve_meeting}


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    return {"Calendar Reader": CalendarReader(), "Conflict Checker": ConflictChecker(), "Scheduler": Scheduler(),
            "Reminder Agent": ReminderAgent(), "Email Liaison": EmailLiaison()}
