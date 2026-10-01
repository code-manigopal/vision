"""Builds every master from the shared catalog (the same one the dashboard uses).

A master in mode "live" uses its real agents module; any agent it doesn't provide yet,
and every master still in mode "stub", runs as a StubAgent with the dashboard's demo status.
Adding a real master later = write masters/<id>.py with build_agents() and set mode: live.
"""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from ..agents import Master, Stage, StubAgent, SubAgent
from ..config import Config

CATALOG = json.loads((Path(__file__).parent / "catalog.json").read_text())
LIVE_MODULES = {"traffic": "vision.masters.traffic", "news": "vision.masters.news", "invest": "vision.masters.invest",
                "email": "vision.masters.email", "calendar": "vision.masters.calendar", "jobs": "vision.masters.jobs",
                "web": "vision.masters.web", "world": "vision.masters.world", "trading": "vision.masters.trading"}


def approval_handlers() -> dict:
    """kind -> async handler(row, decision, ctx), collected from every live master module."""
    handlers = {}
    for mod in LIVE_MODULES.values():
        try:
            handlers.update(getattr(import_module(mod), "APPROVAL_HANDLERS", {}))
        except ImportError:
            pass
    return handlers


def build_masters(cfg: Config) -> list[Master]:
    masters = []
    for mid in CATALOG["order"]:
        spec = CATALOG["masters"][mid]
        mc = cfg.master(mid)
        live: dict[str, SubAgent] = {}
        if mc.mode == "live" and mid in LIVE_MODULES:
            live = import_module(LIVE_MODULES[mid]).build_agents(mc.options, cfg)
        by_name = {a["name"]: a for a in spec["agents"]}

        def make(name: str) -> SubAgent:
            if name in live:
                return live[name]
            a = by_name[name]
            summary = spec["demo_report"] if name == spec["reporter"] else ""
            return StubAgent(name=name, tier=a["tier"], note=a["note"], status=a["status"], label=a["label"], summary=summary)

        stages = [Stage(s["title"], [make(n) for n in s["agents"]], approval=s.get("approval", False)) for s in spec["stages"]]
        m = Master(mid, spec["name"], stages, spec["reporter"], trust=mc.trust, enabled=mc.enabled,
                   mode=mc.mode if mid in LIVE_MODULES else "stub")
        m.services["options"] = mc.options
        masters.append(m)
    return masters
