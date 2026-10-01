"""VISION · Traffic Desk service (TomTom / Google)

get_city_traffic(city_name): geocode a city to a bounding box, then pull live
TomTom incidents inside it and summarise them.

Environment (read from ~/VISION/.env by the core, never from the dashboard):
    TOMTOM_API_KEY        required (geocoding + traffic)
    GOOGLE_MAPS_API_KEY   optional, only if GEOCODER=google
    GEOCODER              "tomtom" (default) or "google"

Requires: httpx, fastapi (for the route).  pip install httpx fastapi
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

ICON_JAM = 6          # TomTom iconCategory: Jam
ICON_ROADWORKS = 9    # TomTom iconCategory: RoadWorks
MAGNITUDE = ["unknown", "minor", "moderate", "major", "indefinite"]
MAJOR_DELAY_SEC = 600  # 10 min or more counts as a major delay
MAX_BBOX_KM2 = 9800    # TomTom caps the incident bbox at 10,000 km²
CACHE_SECONDS = 60     # one poll per city per minute keeps us inside the free tier
TIMEOUT = httpx.Timeout(10.0)

FIELDS = (
    "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,"
    "events{description,code,iconCategory},startTime,endTime,from,to,length,delay,roadNumbers}}}"
)

_cache: dict[str, tuple[float, dict]] = {}


class TrafficError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class Place:
    name: str
    lat: float
    lon: float
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


def _keys() -> tuple[str | None, str | None, str]:
    return (
        os.getenv("TOMTOM_API_KEY"),
        os.getenv("GOOGLE_MAPS_API_KEY"),
        os.getenv("GEOCODER", "tomtom").lower(),
    )


async def _get_json(client: httpx.AsyncClient, url: str, what: str, params: dict | None = None) -> dict:
    try:
        res = await client.get(url, params=params)
    except httpx.TimeoutException:
        raise TrafficError(f"{what} request timed out")
    except httpx.HTTPError as e:
        raise TrafficError(f"{what} request failed: {e}")
    if res.status_code in (401, 403):
        raise TrafficError(f"{what}: API key rejected")
    if res.status_code == 429:
        raise TrafficError(f"{what}: rate limit reached, try again shortly", 429)
    if res.status_code >= 400:
        raise TrafficError(f"{what}: HTTP {res.status_code}")
    return res.json()


# ---------- Step 1: geocoding ----------

async def _geocode_tomtom(client: httpx.AsyncClient, city: str, key: str) -> Place:
    url = f"https://api.tomtom.com/search/2/geocode/{quote(city)}.json"
    data = await _get_json(client, url, "TomTom geocoding", {"key": key, "limit": 1})
    results = data.get("results") or []
    if not results:
        raise TrafficError(f'Couldn\'t find a city called "{city}"', 404)
    r = results[0]
    box = r.get("boundingBox") or r["viewport"]
    a = r.get("address", {})
    name = (
        ", ".join(x for x in (a.get("municipality"), a.get("countrySubdivision") or a.get("country")) if x)
        if a.get("municipality") else a.get("freeformAddress", city)
    )
    return Place(
        name=name,
        lat=r["position"]["lat"], lon=r["position"]["lon"],
        min_lon=box["topLeftPoint"]["lon"], max_lat=box["topLeftPoint"]["lat"],
        max_lon=box["btmRightPoint"]["lon"], min_lat=box["btmRightPoint"]["lat"],
    )


async def _geocode_google(client: httpx.AsyncClient, city: str, key: str) -> Place:
    data = await _get_json(
        client, "https://maps.googleapis.com/maps/api/geocode/json", "Google geocoding",
        {"address": city, "key": key},
    )
    status = data.get("status")
    if status == "ZERO_RESULTS":
        raise TrafficError(f'Couldn\'t find a city called "{city}"', 404)
    if status != "OK":
        raise TrafficError(f"Google geocoding: {status}")
    top = data["results"][0]
    g = top["geometry"]
    box = g.get("bounds") or g["viewport"]
    return Place(
        name=top["formatted_address"],
        lat=g["location"]["lat"], lon=g["location"]["lng"],
        min_lon=box["southwest"]["lng"], min_lat=box["southwest"]["lat"],
        max_lon=box["northeast"]["lng"], max_lat=box["northeast"]["lat"],
    )


def _clamp_bbox(p: Place) -> tuple[tuple[float, float, float, float], bool]:
    """Big metro boxes can exceed TomTom's limit: shrink to a square around the city centre."""
    mid_lat = (p.min_lat + p.max_lat) / 2
    km_lat = (p.max_lat - p.min_lat) * 111.32
    km_lon = (p.max_lon - p.min_lon) * 111.32 * math.cos(math.radians(mid_lat))
    if km_lat * km_lon <= MAX_BBOX_KM2:
        return (p.min_lon, p.min_lat, p.max_lon, p.max_lat), False
    half_km = math.sqrt(MAX_BBOX_KM2) / 2
    d_lat = half_km / 111.32
    d_lon = half_km / (111.32 * math.cos(math.radians(p.lat)))
    return (p.lon - d_lon, p.lat - d_lat, p.lon + d_lon, p.lat + d_lat), True


# ---------- Step 2: TomTom Incident Details ----------

async def _fetch_incidents(client: httpx.AsyncClient, bbox: tuple[float, float, float, float], key: str) -> list[dict]:
    data = await _get_json(
        client, "https://api.tomtom.com/traffic/services/5/incidentDetails", "TomTom traffic",
        {
            "key": key,
            "bbox": ",".join(f"{v:.6f}" for v in bbox),
            "fields": FIELDS,
            "language": "en-GB",
            "timeValidityFilter": "present",
        },
    )
    return data.get("incidents") or []


def _summarise(place: Place, bbox, clamped: bool, incidents: list[dict]) -> dict:
    jams = roadworks = 0
    worst: tuple[int, int, dict] | None = None  # (delay, magnitude, properties)
    for inc in incidents:
        p = inc.get("properties") or {}
        if p.get("iconCategory") == ICON_JAM:
            jams += 1
        elif p.get("iconCategory") == ICON_ROADWORKS:
            roadworks += 1
        delay = p.get("delay") or 0            # null for roadworks
        mag = p.get("magnitudeOfDelay") or 0
        if worst is None or (delay, mag) > (worst[0], worst[1]):
            worst = (delay, mag, p)

    most_severe = None
    if worst and (worst[0] > 0 or worst[1] > 0):
        delay, mag, p = worst
        events = p.get("events") or [{}]
        most_severe = {
            "delaySeconds": delay,
            "delayMinutes": round(delay / 60),
            "magnitude": mag,
            "magnitudeLabel": MAGNITUDE[mag] if 0 <= mag < len(MAGNITUDE) else "unknown",
            "road": " / ".join(p.get("roadNumbers") or []) or None,
            "from": p.get("from"),
            "to": p.get("to"),
            "description": events[0].get("description"),
        }

    return {
        "city": place.name,
        "totalActive": len(incidents),
        "jams": jams,
        "roadworks": roadworks,
        "mostSevere": most_severe,
        "majorDelay": bool(most_severe) and (most_severe["magnitude"] >= 3 or most_severe["delaySeconds"] >= MAJOR_DELAY_SEC),
        "bbox": {"minLon": bbox[0], "minLat": bbox[1], "maxLon": bbox[2], "maxLat": bbox[3], "clamped": clamped},
        "source": "tomtom",
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------- Helpers used by the Traffic Desk agents ----------

async def geocode(client: httpx.AsyncClient, city: str) -> Place:
    tomtom_key, google_key, geocoder = _keys()
    if not tomtom_key:
        raise TrafficError("TOMTOM_API_KEY is not set in .env", 500)
    if geocoder == "google":
        if not google_key:
            raise TrafficError("GEOCODER=google but GOOGLE_MAPS_API_KEY is not set", 500)
        return await _geocode_google(client, city, google_key)
    return await _geocode_tomtom(client, city, tomtom_key)


def clamp_bbox(place: Place):
    return _clamp_bbox(place)


async def fetch_incidents(client: httpx.AsyncClient, bbox) -> list[dict]:
    tomtom_key, _, _ = _keys()
    if not tomtom_key:
        raise TrafficError("TOMTOM_API_KEY is not set in .env", 500)
    return await _fetch_incidents(client, bbox, tomtom_key)


def summarise(place: Place, bbox, clamped: bool, incidents: list[dict]) -> dict:
    return _summarise(place, bbox, clamped, incidents)


# ---------- Public function ----------

async def get_city_traffic(city_name: str, client: httpx.AsyncClient | None = None) -> dict:
    city = (city_name or "").strip()
    if not city:
        raise TrafficError("City name is required", 400)
    tomtom_key, google_key, geocoder = _keys()
    if not tomtom_key:
        raise TrafficError("TOMTOM_API_KEY is not set on the VISION backend", 500)
    if geocoder == "google" and not google_key:
        raise TrafficError("GEOCODER=google but GOOGLE_MAPS_API_KEY is not set", 500)

    hit = _cache.get(city.lower())
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        place = (
            await _geocode_google(client, city, google_key) if geocoder == "google"
            else await _geocode_tomtom(client, city, tomtom_key)
        )
        bbox, clamped = _clamp_bbox(place)
        incidents = await _fetch_incidents(client, bbox, tomtom_key)
    finally:
        if owns_client:
            await client.aclose()

    result = _summarise(place, bbox, clamped, incidents)
    _cache[city.lower()] = (time.monotonic(), result)
    return result


# ---------- FastAPI route used by the dashboard's ASK bar ----------
# In the VISION core:  from traffic import router as traffic_router;  app.include_router(traffic_router)

try:
    from fastapi import APIRouter, Query
    from fastapi.responses import JSONResponse

    router = APIRouter()

    @router.get("/api/traffic")
    async def traffic_endpoint(city: str = Query(..., min_length=1)):
        try:
            return await get_city_traffic(city)
        except TrafficError as e:
            return JSONResponse({"error": str(e)}, status_code=e.status)
except ImportError:  # FastAPI not installed: the function still works standalone
    router = None


# ---------- Route with live traffic (used by the Ask engine) ----------

async def route(origin: str, destination: str) -> dict:
    tomtom_key, _, _ = _keys()
    if not tomtom_key:
        raise TrafficError("TOMTOM_API_KEY is not set in .env", 500)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        a = await geocode(client, origin)
        b = await geocode(client, destination)
        data = await _get_json(client, f"https://api.tomtom.com/routing/1/calculateRoute/{a.lat},{a.lon}:{b.lat},{b.lon}/json",
                               "TomTom routing", {"key": tomtom_key, "traffic": "true", "travelMode": "car", "routeType": "fastest"})
    s = data["routes"][0]["summary"]
    return {"from": a.name, "to": b.name, "km": round(s["lengthInMeters"] / 1000), "minutes": round(s["travelTimeInSeconds"] / 60),
            "usual_minutes": round(s.get("noTrafficTravelTimeInSeconds", s["travelTimeInSeconds"]) / 60),
            "delay_minutes": round(s.get("trafficDelayInSeconds", 0) / 60)}
