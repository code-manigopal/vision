"""Traffic agents of World Watch (Traffic Desk merged into it, Mani, 2026-10-14):
City Geocoder (GATHER, beside the news) -> Traffic Poller (ROADS) -> Incident Scout (INCIDENTS) -> the News Summarizer reports.
None of them blocks: roads down never holds back the news, weather and flights.

Watches the cities listed in config.yaml -> masters.world.options.watch_cities.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..agents import AgentResult, SubAgent
from ..services import traffic_api as tt


class CityGeocoder(SubAgent):
    name, tier, note = "City Geocoder", "API", "Dynamic city input"
    blocking = False

    async def run(self, ctx: dict[str, Any]) -> AgentResult:
        cities: list[str] = self.opts.get("cities") or []
        async with httpx.AsyncClient(timeout=tt.TIMEOUT) as client:
            places = [await tt.geocode(client, c) for c in cities]
        ctx["places"] = places
        return AgentResult("done", "MAPPED", f"Mapped {len(places)} cities", {"cities": [p.name for p in places]})


class TrafficPoller(SubAgent):
    name, tier, note = "Traffic Poller", "API", "Live congestion"
    blocking = False

    async def run(self, ctx: dict[str, Any]) -> AgentResult:
        if not ctx.get("places"):
            return AgentResult("idle", "WAITING", "No cities mapped")
        out = []
        async with httpx.AsyncClient(timeout=tt.TIMEOUT) as client:
            for place in ctx.get("places", []):
                bbox, clamped = tt.clamp_bbox(place)
                incidents = await tt.fetch_incidents(client, bbox)
                out.append(tt.summarise(place, bbox, clamped, incidents))
        ctx["traffic"] = out
        total = sum(x["totalActive"] for x in out)
        return AgentResult("done", f"{total} ACTIVE", f"{total} active incidents across {len(out)} cities", {"cities": out})


class IncidentScout(SubAgent):
    name, tier, note = "Incident Scout", "DEEP", "Active roadworks & jams"
    blocking = False

    async def run(self, ctx: dict[str, Any]) -> AgentResult:
        if "traffic" not in ctx:
            return AgentResult("idle", "WAITING", "No traffic polled")
        parts, major = [], 0
        for c in ctx.get("traffic", []):
            city = c["city"].split(",")[0]
            ms = c.get("mostSevere")
            if c["majorDelay"] and ms:
                major += 1
                what = f"major delay {ms['delayMinutes']} min" if ms["delayMinutes"] else "a closure" if ms["magnitude"] >= 4 else "a major slowdown"
                parts.append(f"{city} {c['totalActive']} incidents, {what}" + (f" on {ms['road']}" if ms.get("road") else ""))
            else:
                parts.append(f"{city} {c['totalActive']} incidents, no major delays")
        summary = " · ".join(parts) or "No cities configured"
        return AgentResult("done", f"{major} MAJOR" if major else "CLEAR", summary,
                           {"cities": ctx.get("traffic", [])})


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    cities = options.get("watch_cities") or ["Leamington, ON", "Windsor, ON"]
    return {
        "City Geocoder": CityGeocoder(cities=cities),
        "Traffic Poller": TrafficPoller(),
        "Incident Scout": IncidentScout(),
    }
