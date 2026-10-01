"""Agent contract.

- A SubAgent does one job: run(ctx) -> AgentResult.
- A Master runs its sub-agents stage by stage. Each stage's output is passed down
  the chain in ctx. Agents in the same stage run in parallel.
- Only the master's REPORTER sends status up; the master reports that to VISION.
- If any sub-agent fails, it alerts the master directly and later stages are blocked.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any

from .bus import EventBus, Store


@dataclass
class AgentResult:
    status: str = "done"          # idle | work | done | wait | off | error
    label: str = "DONE"           # short tag shown on the dashboard
    summary: str = ""             # one line; the reporter's summary becomes the master's report
    data: dict[str, Any] = field(default_factory=dict)


class SubAgent:
    name: str = "Agent"
    tier: str = "QUICK"           # QUICK | DEEP | API | LOCAL | CLOUD | CSV | MCP | GPU
    note: str = ""
    blocking: bool = True         # False: a failure alerts the master but doesn't block later stages

    def __init__(self, name: str | None = None, tier: str | None = None, note: str | None = None, **opts: Any) -> None:
        self.name = name or self.name
        self.tier = tier or self.tier
        self.note = note or self.note
        self.opts = opts

    async def run(self, ctx: dict[str, Any]) -> AgentResult:  # pragma: no cover - overridden
        raise NotImplementedError


def request_approval(ctx: dict, agent: str, title: str, payload: dict) -> dict:
    """Raise a YOU-gate approval once per payload['key'] (dashboard + Telegram show it)."""
    store, bus = ctx["store"], ctx["bus"]
    existing = store.find_pending(ctx["master"], payload["key"])
    if existing:
        return existing
    a = store.add_approval(ctx["master"], agent, title, payload)
    bus.publish({"type": "approval", "approval": a})
    return a


class StubAgent(SubAgent):
    """Placeholder until a master is built for real: reports the dashboard's demo status."""

    def __init__(self, *, status: str, label: str, summary: str = "", **kw: Any) -> None:
        super().__init__(**kw)
        self._status, self._label, self._summary = status, label, summary

    async def run(self, ctx: dict[str, Any]) -> AgentResult:
        await asyncio.sleep(random.uniform(0.12, 0.45))
        return AgentResult(self._status, self._label, self._summary or f"{self.name}: {self._label.lower()} (stub)")


@dataclass
class Stage:
    title: str
    agents: list[SubAgent]
    approval: bool = False        # the YOU gate: approvals are raised by agents, not run as a stage


class Master:
    def __init__(self, id: str, name: str, stages: list[Stage], reporter: str, *, trust: str = "OBSERVE",
                 enabled: bool = True, mode: str = "stub") -> None:
        self.id, self.name, self.stages, self.reporter = id, name, stages, reporter
        self.trust, self.enabled, self.mode = trust, enabled, mode
        self._lock = asyncio.Lock()
        self.services: dict[str, Any] = {}   # cfg, llm, options: injected by the orchestrator/registry
        names = [a.name for a in self.agents]
        if reporter not in names:
            raise ValueError(f"{name}: reporter {reporter!r} is not one of its sub-agents")

    @property
    def agents(self) -> list[SubAgent]:
        return [a for s in self.stages for a in s.agents]

    def agent_state(self, a: SubAgent, status: str, label: str, summary: str = "") -> dict:
        return {"name": a.name, "status": status, "label": label, "summary": summary, "tier": a.tier,
                "reporter": a.name == self.reporter}

    async def cycle(self, bus: EventBus, store: Store, *, reason: str = "schedule", on_agent=None) -> str:
        """Run the chain once. Returns the master's report (the reporter's summary)."""
        if not self.enabled:
            for a in self.agents:
                bus.publish({"type": "agent", "master": self.id, "agent": self.agent_state(a, "idle", "ON HOLD")})
                if on_agent:
                    await on_agent(self, a, None)
            return "On hold"

        async with self._lock:  # a scheduled run never overlaps a manual one
            ctx: dict[str, Any] = {"master": self.id, "reason": reason, "results": {}, "bus": bus, "store": store, "options": {}, **self.services}
            blocked_by: str | None = None
            report, report_data = "", {}

            for stage in self.stages:
                if stage.approval:
                    continue
                if blocked_by:
                    for a in stage.agents:
                        bus.publish({"type": "agent", "master": self.id, "agent": self.agent_state(a, "idle", "BLOCKED", f"Waiting on {blocked_by}")})
                        await store.record_run(self.id, a.name, "idle", "BLOCKED", "", f"blocked by {blocked_by}", 0)
                        if on_agent:
                            await on_agent(self, a, None)
                    continue

                for a in stage.agents:
                    bus.publish({"type": "agent", "master": self.id, "agent": self.agent_state(a, "work", "RUNNING")})
                results = await asyncio.gather(*(self._run_one(a, ctx, bus, store, on_agent) for a in stage.agents))
                for a, res in zip(stage.agents, results):
                    ctx["results"][a.name] = res
                    if res.status == "error" and not blocked_by and a.blocking:
                        blocked_by = a.name
                    if a.name == self.reporter:
                        report = res.summary
                        report_data = res.data

            if not report:
                report = f"Blocked: {blocked_by} failed" if blocked_by else "No report"
            bus.publish({"type": "master_report", "master": self.id, "summary": report, "data": report_data})
            bus.say(f"{self.name} → reported to VISION")
            await store.record_report(self.id, report, {k: v.data for k, v in ctx["results"].items()})
            return report

    async def _run_one(self, a: SubAgent, ctx: dict, bus: EventBus, store: Store, on_agent) -> AgentResult:
        t0 = time.perf_counter()
        try:
            res = await a.run(ctx)
            err = None
        except Exception as e:  # errors skip the chain and alert the master directly
            res = AgentResult("error", "ERROR", f"{a.name} failed: {e}")
            err = str(e)
            bus.say(f"⚠ {self.name} · {a.name} failed: {e}")
        ms = int((time.perf_counter() - t0) * 1000)
        bus.publish({"type": "agent", "master": self.id, "agent": self.agent_state(a, res.status, res.label, res.summary)})
        await store.record_run(self.id, a.name, res.status, res.label, res.summary, err, ms)
        if on_agent:
            await on_agent(self, a, res)
        return res
