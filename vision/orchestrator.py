"""Orchestrator: boot roll call, per-master schedules, and the 6 AM / 6 PM briefs."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .agents import AgentResult, Master, SubAgent
from .bus import EventBus, Store
from .config import Config
from .masters import approval_handlers
from .services.llm import LLM

log = logging.getLogger("vision")


class Orchestrator:
    def __init__(self, cfg: Config, masters: list[Master], bus: EventBus, store: Store) -> None:
        self.cfg, self.masters, self.bus, self.store = cfg, masters, bus, store
        self.by_id = {m.id: m for m in masters}
        self.scheduler = AsyncIOScheduler(timezone=cfg.vision.timezone)
        self._boot_task: asyncio.Task | None = None
        self.channels: list = []  # Telegram (and later others) register here
        self.llm = LLM(cfg)
        for m in masters:
            m.services.update(cfg=cfg, llm=self.llm)
        self.handlers = approval_handlers()
        self._watch: asyncio.Task | None = None

    # ---------- state the dashboard sees before anything runs ----------
    def seed_state(self) -> None:
        for m in self.masters:
            self.bus.state["masters"][m.id] = {
                "name": m.name, "enabled": m.enabled, "trust": m.trust, "mode": m.mode, "reporter": m.reporter,
                "agents": [m.agent_state(a, "idle", "ON HOLD" if not m.enabled else "QUEUED") for a in m.agents],
            }
        for mid, summary in self.store.latest_reports().items():
            self.bus.state["reports"][mid] = summary

    # ---------- boot: every master runs its first cycle; the dashboard shows the roll call ----------
    async def boot(self) -> None:
        total = sum(len(m.agents) for m in self.masters)
        done = 0
        self.bus.publish({"type": "boot", "active": True, "done": 0, "total": total})
        self.bus.say("VISION booting · collecting reports from every master")

        async def tick(master: Master, agent: SubAgent, res: AgentResult | None) -> None:
            nonlocal done
            done += 1
            self.bus.publish({"type": "boot", "active": True, "done": done, "total": total,
                              "master": master.id, "agent": agent.name})

        for m in self.masters:
            try:
                await m.cycle(self.bus, self.store, reason="boot", on_agent=tick)
            except Exception as e:  # one broken master never stops the boot
                log.exception("boot failed for %s", m.id)
                self.bus.say(f"⚠ {m.name} failed to boot: {e}")
        self.bus.publish({"type": "boot", "active": False, "done": total, "total": total})
        self.bus.say("All masters reported · VISION online")

    def start_boot(self) -> None:
        if self._boot_task and not self._boot_task.done():
            return
        self._boot_task = asyncio.create_task(self.boot())

    # ---------- schedules ----------
    def start_schedules(self) -> None:
        for m in self.masters:
            if not m.enabled:
                continue
            minutes = self.cfg.cycle_minutes(m.id)
            self.scheduler.add_job(self.run_master, IntervalTrigger(minutes=minutes), args=[m.id, "schedule"],
                                   id=f"cycle:{m.id}", max_instances=1, coalesce=True, replace_existing=True)
        for hhmm in self.cfg.vision.brief_times:
            h, mnt = (int(x) for x in hhmm.split(":"))
            kind = "morning" if h < 12 else "evening"
            self.scheduler.add_job(self.brief, CronTrigger(hour=h, minute=mnt), args=[kind], id=f"brief:{hhmm}", replace_existing=True)
        self.scheduler.add_job(self.fire_reminders, IntervalTrigger(seconds=60), id="reminders", replace_existing=True)
        self.scheduler.start()
        self._watch = asyncio.create_task(self.watch_approvals())

    async def run_master(self, master_id: str, reason: str = "manual") -> str:
        return await self.by_id[master_id].cycle(self.bus, self.store, reason=reason)

    # ---------- briefs: only master reports go into it ----------
    def compose_brief(self) -> str:
        lines = [f"VISION brief for {self.cfg.vision.owner}"]
        for m in self.masters:
            if m.enabled:
                lines.append(f"• {m.name.title()}: {self.bus.state['reports'].get(m.id, 'no report yet')}")
        return "\n".join(lines)

    async def brief(self, kind: str = "now") -> str:
        text = self.compose_brief()
        self.bus.publish({"type": "brief", "kind": kind, "text": text})
        sent = [await ch.send_brief(kind) for ch in self.channels]
        self.bus.say(f"{kind.title()} brief compiled from master reports" + (" · sent to Telegram" if any(sent) else ""))
        return text

    # ---------- approvals: run the action once you decide ----------
    async def watch_approvals(self) -> None:
        q = self.bus.subscribe()
        try:
            while True:
                e = await q.get()
                if e.get("type") == "approval_decided":
                    await self.execute_approval(e["id"], e["decision"])
        finally:
            self.bus.unsubscribe(q)

    async def execute_approval(self, approval_id: int, decision: str) -> str | None:
        row = self.store.get_approval(approval_id)
        if not row or row["status"] != decision:  # only act on a decision that was actually recorded
            return None
        handler = self.handlers.get(row["payload"].get("kind"))
        if not handler:
            return None
        ctx = {"bus": self.bus, "store": self.store, "cfg": self.cfg, "llm": self.llm, "master": row["master"]}
        try:
            result = await handler(row, decision, ctx)
            self.bus.say(f"{row['title']} → {result}")
            return result
        except Exception as e:
            log.exception("approval action failed")
            self.bus.say(f"⚠ {row['master']} · approval action failed: {e}")
            return None

    # ---------- reminders (armed by the Calendar's Reminder Agent) ----------
    async def fire_reminders(self) -> None:
        import time as _t
        for r in self.store.kv_list("reminders", limit=200):
            if not r.get("fired") and r["at"] <= _t.time() < r["at"] + 900:
                key = r.pop("_key")
                r.pop("_ts", None)
                r["fired"] = True
                self.store.kv_put("reminders", key, r)
                self.bus.publish({"type": "reminder", "text": r["text"]})
                self.bus.say(r["text"])

    def shutdown(self) -> None:
        if self._watch:
            self._watch.cancel()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
