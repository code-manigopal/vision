"""Telegram channel.

- Sends the 6 AM / 6 PM briefs (built only from master reports).
- Sends instant alerts: agent errors and new approvals (with Approve / Reject buttons).
- Answers commands: /brief /status /traffic <city> /approvals /help.
- Talks ONLY to TELEGRAM_CHAT_ID. Everyone else is ignored.
- With no token in .env it stays off and VISION runs normally. Add the token later and restart.

Uses the Bot API directly over HTTPS with long polling, so no public server or open port is needed.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from typing import Any

import httpx

from ..bus import EventBus, Store
from ..config import secret

log = logging.getLogger("vision.telegram")
API = "https://api.telegram.org/bot{token}/{method}"
ALERT_REPEAT_SECONDS = 1800  # the same error is sent at most once per 30 min

HELP = (
    "<b>VISION commands</b>\n"
    "/brief – brief from every master now\n"
    "/status – same, short form\n"
    "/traffic &lt;city&gt; – live traffic (e.g. /traffic Windsor)\n"
    "/approvals – what's waiting for you\n"
    "/agents – every master, one line each; /agents &lt;master&gt; – its agents (e.g. /agents youtube)\n"
    "/agent &lt;name&gt; – one agent in detail (e.g. /agent resume tailor)\n"
    "/jobs – the jobs you're tracking, with buttons to move them\n"
    "/track &lt;link&gt; [| title | company] – track a job you applied to elsewhere\n"
    "/say &lt;word&gt; = &lt;Tamil spelling&gt; – fix how the voice says a word (/say &lt;word&gt; shows it; /say! forces)\n"
    "Or just type: <i>what's up</i>"
)


GROUPS = [("📬 Inbox & day", ["email", "calendar"]), ("💰 Money", ["invest", "trading"]), ("🌍 World", ["world"]),
          ("🎬 Creators", ["youtube", "ebooks", "web"]), ("💼 Career & life", ["jobs", "visa"])]
NAMES = {"youtube": "YouTube Manager", "ebooks": "E-books Manager"}
ICONS = {"email": "📧", "calendar": "📅", "invest": "💼", "trading": "📈", "world": "🌍", "youtube": "🎬", "ebooks": "📚", "web": "🌐",
         "jobs": "🧑‍💻", "visa": "🛂"}
PART_ICONS = [(r"°C", "🌤"), (r"in the air", "✈️"), (r"\bincidents?\b", "🚦"), (r"topics? updated|headlines", "📰"),
              (r"^Portfolio", "💼"), (r"^Overall", "📊"), (r"^Top gainer", "🟢"), (r"^Top loser", "🔻"), (r"^(Fyers|Zerodha|Kite|WS )", "🏦"),
              (r"^(NIFTY|SENSEX|NASDAQ|S&P|DOW|BTC)", "🌐"), (r"^Consider|^Idea", "💡"), (r"waiting on|sign-?in|log ?in", "⏳"),
              (r"need you|waiting for your|awaiting", "👉"), (r"backed up|freed", "🗄"), (r"^latest", "🆕")]


DOTS = {"error": "🔴", "done": "🟢", "wait": "🟡", "work": "🔵", "idle": "⚪"}
COMMANDS = [("brief", "brief from every master now"), ("agents", "masters, or one master's agents"), ("agent", "one agent in detail"),
            ("jobs", "jobs you're tracking"), ("track", "track a job you applied to elsewhere"), ("approvals", "what's waiting for you"),
            ("traffic", "live traffic for a city"), ("say", "fix how the voice says a word"), ("help", "all commands")]


def _icon(part: str) -> str | None:
    return next((e for pat, e in PART_ICONS if re.search(pat, part, re.I)), None)


def report_lines(m, report: str) -> list[str]:
    """One master's report: a short one on its own line; a long one as its name, then one line per part (" · "-separated).
    A part with no icon of its own joins the line before it (\"9,725 in the air · showing 60 · 13 near home\" stays one line).
    YouTube's channels (" | ") each get a line."""
    icon, name = ICONS.get(m.id, "▪️"), esc(NAMES.get(m.id) or m.name.title())
    flag = "⚠️ " if report.lower().startswith("blocked") else ""
    if " | " in report:
        return [f"{flag}{icon} <b>{name}</b>"] + [f"  ▸ {esc(ch.strip())}" for ch in report.split(" | ")]
    parts = [p.strip() for p in report.split(" · ") if p.strip()]
    if len(parts) <= 3 and len(report) <= 70:
        return [f"{flag}{icon} <b>{name}</b>: {esc(report)}"]
    out: list[str] = []
    for p in parts:
        e = _icon(p)
        if out and (not e or e == out[-1][0]) and e not in ("🚦",):      # same kind (three brokers, three indices) or no icon: one line
            out[-1][1] += " · " + p
        else:
            out.append([e or "•", p])
    return [f"{flag}{icon} <b>{name}</b>"] + [f"  {e} {esc(t)}" for e, t in out]


def esc(s: Any) -> str:
    return html.escape(str(s), quote=False)


class TelegramChannel:
    def __init__(self, bus: EventBus, store: Store, orch, *, client: httpx.AsyncClient | None = None) -> None:
        self.bus, self.store, self.orch = bus, store, orch
        self.token = secret("TELEGRAM_BOT_TOKEN")
        self.chat_id = secret("TELEGRAM_CHAT_ID")
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(40.0))
        self.offset = 0
        self.tasks: list[asyncio.Task] = []
        self.last_alert: dict[str, float] = {}
        self.last_sent: str | None = None

    # ---------- lifecycle ----------
    @property
    def ready(self) -> bool:
        return bool(self.token and self.chat_id)

    def status(self, connected: bool, reason: str = "") -> None:
        self.bus.publish({"type": "telegram", "status": {"connected": connected, "reason": reason, "last_sent": self.last_sent}})

    async def start(self) -> None:
        if not self.token:
            self.status(False, "add TELEGRAM_BOT_TOKEN to .env")
            log.info("Telegram off: no TELEGRAM_BOT_TOKEN")
            return
        try:
            me = await self._call("getMe")
        except Exception as e:
            self.status(False, f"token rejected or offline: {e}")
            log.warning("Telegram getMe failed: %s", e)
            return
        name = me.get("username", "bot")
        if not self.chat_id:
            self.status(False, f"send /start to @{name} to get your chat ID")
        else:
            self.status(True, f"@{name}")
        try:                                     # the bot's command menu in Telegram
            await self._call("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
        except Exception as e:
            log.warning("Telegram setMyCommands failed: %s", e)
        self.tasks.append(asyncio.create_task(self._poll()))
        if self.chat_id and self.orch.cfg.telegram.get("alerts", True):
            self.tasks.append(asyncio.create_task(self._watch_bus()))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.client.aclose()

    # ---------- Bot API ----------
    async def _call(self, method: str, **params: Any) -> Any:
        r = await self.client.post(API.format(token=self.token, method=method), json=params)
        data = r.json()
        if not data.get("ok"):
            if data.get("error_code") == 429:  # Telegram rate limit: wait as told, then retry once
                await asyncio.sleep(data.get("parameters", {}).get("retry_after", 3))
                r = await self.client.post(API.format(token=self.token, method=method), json=params)
                data = r.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("description", "Telegram error"))
        return data["result"]

    async def send(self, text: str, *, buttons: list[list[dict]] | None = None, chat_id: str | None = None) -> bool:
        target = chat_id or self.chat_id
        if not (self.token and target):
            return False
        params: dict[str, Any] = {"chat_id": target, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        try:
            await self._call("sendMessage", **params)
            self.last_sent = time.strftime("%H:%M")
            self.status(True, "sending")
            return True
        except Exception as e:
            log.warning("Telegram send failed: %s", e)
            return False

    # ---------- briefs ----------
    async def send_brief(self, kind: str = "now") -> bool:
        return await self.send(self.format_brief(kind))

    def format_brief(self, kind: str = "now") -> str:
        """Grouped by area, one emoji per master, a long report split into short lines (Mani, 2026-10-15: "it just writes like a
        paragraph... not readable")."""
        owner = esc(self.orch.cfg.vision.owner)
        head = {"morning": f"☀️ <b>Good morning, {owner}</b>", "evening": f"🌙 <b>Evening wrap, {owner}</b>"}
        lines = [head.get(kind, f"🛰 <b>VISION status, {owner}</b>")]
        reports = self.bus.state["reports"]
        live = [m for m in self.orch.masters if m.enabled]
        placed = set()
        for title, ids in GROUPS + [("🧩 Other", [m.id for m in live])]:
            block = []
            for m in live:
                if m.id in ids and m.id not in placed:
                    placed.add(m.id)
                    block += report_lines(m, reports.get(m.id, "no report yet"))
            if block:
                lines += ["", f"<b>{title}</b>", *block]
        pend = self.store.pending_approvals()
        if pend:
            lines += ["", f"🔴 <b>Needs you ({len(pend)})</b>"] + [f"  • {esc(a['title'])}" for a in pend[:6]] + ([f"  • …and {len(pend) - 6} more"] if len(pend) > 6 else [])
        return "\n".join(lines)

    # ---------- alerts from the bus ----------
    async def _watch_bus(self) -> None:
        q = self.bus.subscribe()
        try:
            while True:
                e = await q.get()
                if e.get("type") == "log" and e["msg"].startswith("⚠"):
                    key = e["msg"].split(":")[0]
                    if time.time() - self.last_alert.get(key, 0) > ALERT_REPEAT_SECONDS:
                        self.last_alert[key] = time.time()
                        await self.send(f"⚠️ <b>Alert</b>\n{esc(e['msg'][1:].strip())}")
                elif e.get("type") == "reminder":
                    await self.send(esc(e["text"]))
                elif e.get("type") == "notice":
                    link = f"\n<a href=\"{esc(e['url'])}\">Open login link</a>" if e.get("url") else ""
                    await self.send(f"🔑 <b>Action needed</b>\n{esc(e['text'])}{link}")
                elif e.get("type") == "approval":
                    a = e["approval"]
                    await self.send(f"🔴 <b>Approval needed</b> · {esc(a['master'])} / {esc(a['agent'])}\n{esc(a['title'])}",
                                    buttons=[[{"text": "✅ Approve", "callback_data": f"ap:{a['id']}:approved"},
                                              {"text": "✖ Reject", "callback_data": f"ap:{a['id']}:rejected"}]])
        finally:
            self.bus.unsubscribe(q)

    # ---------- incoming: commands and button taps ----------
    async def _poll(self) -> None:
        backoff = 2
        while True:
            try:
                updates = await self._call("getUpdates", offset=self.offset, timeout=25, allowed_updates=["message", "callback_query"])
                backoff = 2
                for u in updates:
                    self.offset = u["update_id"] + 1
                    await self.handle_update(u)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Telegram poll error: %s (retry in %ss)", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def handle_update(self, u: dict) -> None:
        if "callback_query" in u:
            cq = u["callback_query"]
            chat = str(cq.get("message", {}).get("chat", {}).get("id", ""))
            if chat != self.chat_id:
                return
            await self._on_button(cq)
            return
        msg = u.get("message") or {}
        chat = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not self.chat_id:
            # setup mode: tell the person their chat ID so they can put it in .env
            if text.startswith("/start"):
                await self.send(f"Your chat ID is <code>{esc(chat)}</code>.\nAdd it to .env as TELEGRAM_CHAT_ID and restart VISION.", chat_id=chat)
            return
        if chat != self.chat_id:
            return  # strangers are ignored
        await self.on_command(text)

    async def on_command(self, text: str) -> None:
        t = text.lower()
        if re.match(r"/say!?(\s|$)", t):
            await self.send(self._say(text))
        elif t.startswith("/start") or t.startswith("/help"):
            await self.send(HELP)
        elif t.startswith("/brief") or t.startswith("/status") or any(w in t for w in ("what's up", "whats up", "how are we doing", "status")):
            await self.send_brief("now")
        elif t.startswith("/approvals"):
            pend = self.store.pending_approvals()
            if not pend:
                await self.send("Nothing is waiting for you. ✅")
            for a in pend:
                await self.send(f"🔴 {esc(a['master'])} / {esc(a['agent'])}\n{esc(a['title'])}",
                                buttons=[[{"text": "✅ Approve", "callback_data": f"ap:{a['id']}:approved"},
                                          {"text": "✖ Reject", "callback_data": f"ap:{a['id']}:rejected"}]])
        elif re.match(r"/agents(\s|$|@)", t):
            arg = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
            await self.send(self.agents_text(arg))
        elif re.match(r"/agent(\s|$|@)", t):
            arg = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
            await self.send(self.agent_text(arg))
        elif re.match(r"/jobs(\s|$|@)", t):
            await self._jobs()
        elif re.match(r"/track(\s|$|@)", t):
            await self.send(await self._track(text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""))
        elif t.startswith("/traffic") or t.startswith("traffic in "):
            city = text.split(" ", 1)[1].replace("in ", "", 1).strip() if " " in text else self.orch.cfg.vision.home_city
            await self.send(await self._traffic(city))
        else:
            await self.send("I can do /brief, /agents, /agent, /jobs, /track, /traffic &lt;city&gt; and /approvals for now. /help lists them all.")

    # ---------- agents, one by one ----------
    def _master(self, q: str):
        q = q.lower().strip()
        ms = [m for m in self.orch.masters]
        return next((m for m in ms if m.id == q), None) or next((m for m in ms if q in m.name.lower() or q in NAMES.get(m.id, "").lower()), None)

    def agents_text(self, q: str = "") -> str:
        """/agents: one line per master; /agents <master>: that master's agents, crews marked ›, each with its status and summary."""
        live = self.bus.state["masters"]
        if not q:
            lines = ["🤖 <b>Masters</b>"]
            for m in self.orch.masters:
                ags = (live.get(m.id) or {}).get("agents") or []
                errs = sum(1 for a in ags if a.get("status") == "error")
                state = "on hold" if not m.enabled else f"{len(ags)} agents" + (f" · {errs} 🔴" if errs else " · all fine" if ags else " · not run yet")
                lines.append(f"{ICONS.get(m.id, '🧩')} <b>{esc(NAMES.get(m.id, m.name))}</b> <code>{esc(m.id)}</code> · {state}")
            return "\n".join(lines + ["", "Send /agents &lt;id&gt; for one master's agents."])
        m = self._master(q)
        if not m:
            return f"No master matches “{esc(q)}”. Send /agents for the list."
        ags = (live.get(m.id) or {}).get("agents") or []
        lines = [f"{ICONS.get(m.id, '🧩')} <b>{esc(NAMES.get(m.id, m.name))}</b>" + ("" if m.enabled else " · on hold")]
        if not ags:
            return "\n".join(lines + ["No agent has run since VISION started."])
        for a in ags:
            crew = "  › " if a.get("director") else ""
            rep = " 📣" if a.get("reporter") else ""
            summ = (a.get("summary") or "").strip()
            lines.append(f"{crew}{DOTS.get(a.get('status'), '⚪')} <b>{esc(a['name'])}</b>{rep} · {esc(a.get('label') or a.get('status') or '')}"
                         + (f"\n{crew}    {esc(summ[:160] + ('…' if len(summ) > 160 else ''))}" if summ else ""))
        return "\n".join(lines)

    def agent_text(self, q: str) -> str:
        """/agent <name>: status, last summary, last run time and any error of one agent (first match across masters)."""
        if not q:
            return "Use /agent &lt;name&gt;, e.g. /agent resume tailor."
        ql = q.lower().strip()
        hits = [(mid, a) for mid, m in self.bus.state["masters"].items() for a in m.get("agents") or [] if ql in a["name"].lower()]
        hits.sort(key=lambda h: h[1]["name"].lower() != ql)
        if not hits:
            return f"No agent matches “{esc(q)}”. Send /agents &lt;master&gt; to see names."
        mid, a = hits[0]
        m = self.orch.by_id.get(mid)
        lines = [f"{DOTS.get(a.get('status'), '⚪')} <b>{esc(a['name'])}</b> · {esc(NAMES.get(mid, m.name if m else mid))}"
                 + (f" › {esc(a['director'])}" if a.get("director") else ""),
                 f"Status: {esc(a.get('label') or a.get('status') or '')}" + (" · reports for the master" if a.get("reporter") else ""),
                 f"Tier: {esc(a.get('tier') or '')}"]
        if a.get("summary"):
            lines.append(f"Says: {esc(a['summary'][:600])}")
        try:
            r = self.store.last_run(mid, a["name"])
        except Exception:
            r = None
        if r:
            lines.append(f"Last run: {time.strftime('%d %b %H:%M', time.localtime(r['ts']))}" + (f" · {r['ms'] / 1000:.1f} s" if r.get("ms") else ""))
            if r.get("error"):
                lines.append(f"Error: {esc(str(r['error'])[:400])}")
        if len(hits) > 1:
            lines.append("Also matches: " + ", ".join(esc(h[1]["name"]) for h in hits[1:6]))
        return "\n".join(lines)

    # ---------- the job tracker ----------
    async def _jobs(self) -> None:
        from ..masters.jobs import KEPT, NEXT, TRACK
        js = sorted((j for j in self.store.kv_list("jobs", limit=2000) if j.get("status") in KEPT),
                    key=lambda j: -(j.get("applied_at") or j.get("found") or 0))
        if not js:
            await self.send("No jobs tracked yet. Approve a package, or /track &lt;link&gt; one you applied to.")
            return
        counts = " · ".join(f"{sum(1 for j in js if j['status'] == k)} {TRACK[k].lower()}" for k in KEPT if any(j["status"] == k for j in js))
        await self.send(f"💼 <b>Tracked jobs</b> · {counts}" + (f"\nShowing the latest 10 of {len(js)}." if len(js) > 10 else ""))
        for j in js[:10]:
            key = j["_key"]
            when = j.get("applied_at") and time.strftime("%d %b", time.localtime(j["applied_at"]))
            link = f"\n<a href=\"{esc(j['url'])}\">Posting</a>" if j.get("url") else ""
            drive = f" · <a href=\"{esc(j['drive']['url'])}\">Files</a>" if (j.get("drive") or {}).get("url") else ""
            btns = [{"text": TRACK[n], "callback_data": f"jb:{key}:{n}"} for n in NEXT.get(j["status"], ()) if len(f"jb:{key}:{n}") <= 64]
            await self.send(f"<b>{esc(TRACK[j['status']])}</b> · {esc(j.get('title'))} @ {esc(j.get('company') or j.get('source') or '')}"
                            + (f" · applied {when}" if when else "") + link + drive, buttons=[btns] if btns else None)

    async def _track(self, arg: str) -> str:
        from ..masters import jobs
        url, title, company = ([p.strip() for p in arg.split("|")] + ["", ""])[:3]
        try:
            j = await jobs.track(self.store, url, title, company)
        except ValueError as e:
            return f"Not tracked: {esc(e)}. Use /track &lt;link&gt; [| title | company]."
        return f"💼 Tracking <b>{esc(j['title'])}</b> as applied. /jobs shows it."

    def _say(self, text: str) -> str:
        """/say word = Tamil spelling saves Mani's fix (data/voice_fixes.json); /say word shows what the voice uses and where it comes from; /say! forces a word of the approved reference."""
        from ..masters import tamil_say
        force = text.lower().startswith("/say!")
        body = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
        word, eq, spelling = body.partition("=")
        if not word.strip():
            return "Use /say &lt;word&gt; = &lt;Tamil spelling&gt;, or /say &lt;word&gt; to see it."
        if not eq:
            src, sp = tamil_say.source(word)
            return f"<b>{esc(word.strip())}</b> → {esc(sp)} ({src})" if sp else f"<b>{esc(word.strip())}</b>: no spelling set ({src}); the voice reads it as written."
        return esc(tamil_say.set_fix(word, spelling, force)["message"])

    async def _traffic(self, city: str) -> str:
        from ..services.traffic_api import TrafficError, get_city_traffic
        try:
            d = await get_city_traffic(city)
        except TrafficError as e:
            return f"🚦 Traffic for {esc(city)} unavailable: {esc(e)}"
        ms = d.get("mostSevere")
        worst = (f"\n⚠️ Major delay {ms['delayMinutes']} min" + (f" on {esc(ms['road'])}" if ms.get("road") else "")) if d["majorDelay"] and ms else "\nNo major delays."
        return f"🚦 <b>{esc(d['city'])}</b>\n{d['totalActive']} active · {d['jams']} jams · {d['roadworks']} roadworks{worst}"

    async def _on_button(self, cq: dict) -> None:
        data = cq.get("data", "")
        if data.startswith("jb:"):
            await self._on_job_button(cq, data)
            return
        try:
            _, sid, decision = data.split(":")
            row = self.store.decide_approval(int(sid), decision)
        except ValueError:
            row = None
        note = "Already decided" if row is None else ("Approved ✅" if decision == "approved" else "Rejected ✖")
        try:
            await self._call("answerCallbackQuery", callback_query_id=cq["id"], text=note)
            if row:
                m = cq["message"]
                await self._call("editMessageText", chat_id=m["chat"]["id"], message_id=m["message_id"],
                                 text=esc(m.get("text", "")) + f"\n\n<b>{note}</b>", parse_mode="HTML")
        except Exception as e:
            log.warning("Telegram button reply failed: %s", e)
        if row:
            self.bus.publish({"type": "approval_decided", "id": row["id"], "decision": decision})
            self.bus.say(f"{row['title']} → {decision} via Telegram")

    async def _on_job_button(self, cq: dict, data: str) -> None:
        from ..masters import jobs
        _, rest = data.split(":", 1)
        key, _, status = rest.rpartition(":")
        try:
            j = jobs.set_status(self.store, key, status)
            note = f"Marked {jobs.TRACK[status].lower()}"
        except ValueError as e:
            j, note = None, str(e)
        try:
            await self._call("answerCallbackQuery", callback_query_id=cq["id"], text=note)
            if j:
                m = cq["message"]
                await self._call("editMessageText", chat_id=m["chat"]["id"], message_id=m["message_id"],
                                 text=esc(m.get("text", "")) + f"\n\n<b>{esc(note)}</b>", parse_mode="HTML")
        except Exception as e:
            log.warning("Telegram button reply failed: %s", e)
        if j:
            self.bus.say(f"Job: {j['title']} → {jobs.TRACK[status]} via Telegram")
