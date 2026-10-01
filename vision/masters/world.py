"""World Watch (live): Flight Tracker (reporter).

Positions: OpenSky Network (free for non-commercial use; OPENSKY_CLIENT_ID/SECRET in .env gives
higher limits, anonymous works with lower limits). Routes: adsbdb (free, no key), cached for a week.
ETA is estimated from remaining distance and ground speed.
"""

from __future__ import annotations

import math
import time
from typing import Any

import httpx

from ..agents import AgentResult, SubAgent
from ..config import secret

TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
STATES_URL = "https://opensky-network.org/api/states/all"
_token: dict = {}


def km(a_lat, a_lon, b_lat, b_lon) -> float:
    p = math.pi / 180
    h = math.sin((b_lat - a_lat) * p / 2) ** 2 + math.cos(a_lat * p) * math.cos(b_lat * p) * math.sin((b_lon - a_lon) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


async def _headers(c: httpx.AsyncClient) -> dict:
    cid, cs = secret("OPENSKY_CLIENT_ID"), secret("OPENSKY_CLIENT_SECRET")
    if not (cid and cs):
        return {}
    if _token.get("exp", 0) < time.time():
        r = await c.post(TOKEN_URL, data={"grant_type": "client_credentials", "client_id": cid, "client_secret": cs})
        r.raise_for_status()
        d = r.json()
        _token.update(tok=d["access_token"], exp=time.time() + int(d.get("expires_in", 1800)) - 60)
    return {"Authorization": f"Bearer {_token['tok']}"}


async def _route(c: httpx.AsyncClient, store, cs: str) -> dict | None:
    cached = store.kv_get("routes", cs)
    if cached and time.time() - cached.get("at", 0) < 7 * 86400:
        return cached.get("route")
    route = None
    try:
        r = await c.get(f"https://api.adsbdb.com/v0/callsign/{cs}")
        fr = (r.json().get("response") or {}).get("flightroute") if r.status_code == 200 else None
        if isinstance(fr, dict):
            o, d = fr.get("origin") or {}, fr.get("destination") or {}
            route = {"airline": (fr.get("airline") or {}).get("name", ""), "from": o.get("iata_code"), "from_city": o.get("municipality"),
                     "to": d.get("iata_code"), "to_city": d.get("municipality"), "dest": [d.get("latitude"), d.get("longitude")]}
    except Exception:
        route = None
    store.kv_put("routes", cs, {"route": route, "at": time.time()})
    return route


class FlightTracker(SubAgent):
    name, tier, note = "Flight Tracker", "API", "OpenSky + adsbdb"

    def __init__(self, home: tuple[float, float] | None, max_flights: int, near_km: int, lookups: int) -> None:
        super().__init__()
        self.home, self.max_flights, self.near_km, self.lookups = home, max_flights, near_km, lookups

    async def run(self, ctx):
        store = ctx["store"]
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.get(STATES_URL, headers=await _headers(c))
            r.raise_for_status()
            states = [s for s in (r.json().get("states") or []) if s[5] is not None and s[6] is not None and not s[8] and (s[1] or "").strip()]
            near = [s for s in states if self.home and km(self.home[0], self.home[1], s[6], s[5]) <= self.near_km]
            step = max(1, len(states) // max(1, self.max_flights - len(near[: self.max_flights // 2])))
            picked = near[: self.max_flights // 2] + states[::step]
            seen, flights, looked = set(), [], 0
            for s in picked:
                cs = s[1].strip()
                if cs in seen:
                    continue
                seen.add(cs)
                route = store.kv_get("routes", cs)
                route = route.get("route") if route else None
                if route is None and looked < self.lookups:
                    route = await _route(c, store, cs)
                    looked += 1
                f = {"cs": cs, "lat": s[6], "lon": s[5], "alt": s[7], "spd": s[9], "trk": s[10], "country": s[2]}
                if route:
                    f.update({k: route[k] for k in ("airline", "from", "from_city", "to", "to_city")})
                    dest = route.get("dest") or [None, None]
                    f["dest"] = dest if dest[0] is not None else None
                    if dest[0] is not None and s[9]:
                        f["eta_min"] = round(km(s[6], s[5], dest[0], dest[1]) / (s[9] * 3.6) * 60)
                flights.append(f)
                if len(flights) >= self.max_flights:
                    break
        n_near = sum(1 for f in flights if self.home and km(self.home[0], self.home[1], f["lat"], f["lon"]) <= self.near_km)
        return AgentResult("done", f"{len(flights)} TRACKED", f"{len(states):,} in the air · showing {len(flights)} · {n_near} near home",
                           {"flights": flights, "total_airborne": len(states), "at": time.time()})


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    home = tuple(options["home"]) if options.get("home") else (42.05, -82.6)
    return {"Flight Tracker": FlightTracker(home, int(options.get("max_flights", 60)), int(options.get("near_km", 400)), int(options.get("route_lookups", 25)))}
