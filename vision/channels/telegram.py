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
    "Or just type: <i>what's up</i>"
)


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
        owner = esc(self.orch.cfg.vision.owner)
        head = {"morning": f"☀️ <b>VISION · Good morning, {owner}</b>", "evening": f"🌙 <b>VISION · Evening wrap, {owner}</b>"}
        lines = [head.get(kind, f"🛰 <b>VISION · Status for {owner}</b>")]
        reports = self.bus.state["reports"]
        for m in self.orch.masters:
            if not m.enabled:
                continue
            r = reports.get(m.id, "no report yet")
            flag = "⚠️ " if r.lower().startswith("blocked") else ""
            lines.append(f"{flag}<b>{esc(m.name.title())}</b>: {esc(r)}")
        pend = self.store.pending_approvals()
        if pend:
            lines.append(f"\n🔴 <b>{len(pend)} need you:</b> " + esc(", ".join(a["title"] for a in pend[:5])))
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
        if t.startswith("/start") or t.startswith("/help"):
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
        elif t.startswith("/traffic") or t.startswith("traffic in "):
            city = text.split(" ", 1)[1].replace("in ", "", 1).strip() if " " in text else self.orch.cfg.vision.home_city
            await self.send(await self._traffic(city))
        else:
            await self.send("I can do /brief, /traffic &lt;city&gt; and /approvals for now. Full conversation arrives with the Ask engine.")

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
