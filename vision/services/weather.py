"""Weather from Open-Meteo. Free for non-commercial use, no key."""

from __future__ import annotations

import time

import httpx

PROVINCES = {"ON": "Ontario", "QC": "Quebec", "BC": "British Columbia", "AB": "Alberta", "MB": "Manitoba", "SK": "Saskatchewan",
             "NS": "Nova Scotia", "NB": "New Brunswick", "NL": "Newfoundland and Labrador", "PE": "Prince Edward Island"}


def wmo(code: int | None) -> tuple[str, str]:
    """WMO weather code -> (dashboard icon kind, words)."""
    c = code if code is not None else -1
    if c == 0: return "sun", "clear"
    if c == 1: return "sun", "mainly clear"
    if c == 2: return "cloud", "partly cloudy"
    if c == 3: return "cloud", "cloudy"
    if c in (45, 48): return "cloud", "fog"
    if 51 <= c <= 57: return "rain", "drizzle"
    if 61 <= c <= 67 or 80 <= c <= 82: return "rain", "rain"
    if 71 <= c <= 77 or c in (85, 86): return "cloud", "snow"
    if c >= 95: return "storm", "thunderstorms"
    return "cloud", "cloudy"


async def geocode(client: httpx.AsyncClient, city: str) -> dict:
    name, _, region = city.partition(",")
    r = await client.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": name.strip(), "count": 10, "language": "en", "format": "json"})
    r.raise_for_status()
    results = r.json().get("results") or []
    if not results:
        raise RuntimeError(f"Open-Meteo couldn't find {city!r}")
    region = region.strip()
    want = PROVINCES.get(region.upper(), region)
    if want:
        for x in results:
            if want.lower() in (x.get("admin1", "") + " " + x.get("country", "") + " " + x.get("country_code", "")).lower():
                return x
    return results[0]


async def forecast(city: str, timezone: str, lat: float | None = None, lon: float | None = None) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        if lat is None or lon is None:
            g = await geocode(client, city)
            lat, lon, label = g["latitude"], g["longitude"], g["name"]
        else:
            label = city.split(",")[0]
        r = await client.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "timezone": timezone, "forecast_days": 16,
            "current": "temperature_2m,weather_code,relative_humidity_2m,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        })
        r.raise_for_status()
        d = r.json()
    cur, day = d["current"], d["daily"]
    kind, words = wmo(cur.get("weather_code"))
    daily = []
    for i, date in enumerate(day["time"]):
        k, w = wmo(day["weather_code"][i])
        daily.append({"date": date, "kind": k, "words": w, "hi": round(day["temperature_2m_max"][i]),
                      "lo": round(day["temperature_2m_min"][i]), "rain": (day.get("precipitation_probability_max") or [None] * 99)[i]})
    return {"city": label, "temp": round(cur["temperature_2m"]), "kind": kind, "words": words,
            "humidity": cur.get("relative_humidity_2m"), "wind": cur.get("wind_speed_10m"), "daily": daily}


# ---- world grid for the globe: current conditions at ~100 points, one request, cached for an hour ----
GRID = [(la, lo) for la in range(-60, 61, 20) for lo in range(-168, 169, 24)]
_grid: dict = {"at": 0.0, "points": []}


def globe_kind(code: int | None) -> str | None:
    """WMO code -> the globe's icon: clear | cloud | fog | rain | snow | storm."""
    if code is None:
        return None
    if code <= 1: return "clear"
    if code <= 3: return "cloud"
    if code <= 48: return "fog"
    if 71 <= code <= 77 or code in (85, 86): return "snow"
    if code >= 95: return "storm"
    return "rain"


async def grid(max_age: float = 3600) -> dict:
    if _grid["points"] and time.time() - _grid["at"] < max_age:
        return _grid
    async with httpx.AsyncClient(timeout=25) as c:
        r = await c.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": ",".join(str(p[0]) for p in GRID), "longitude": ",".join(str(p[1]) for p in GRID), "current": "weather_code,is_day"})
        r.raise_for_status()
        rows = r.json()
    rows = rows if isinstance(rows, list) else [rows]
    pts = []
    for (la, lo), row in zip(GRID, rows):
        cur = row.get("current") or {}
        kind = globe_kind(cur.get("weather_code"))
        if kind:
            pts.append({"la": la, "lo": lo, "kind": kind, "day": bool(cur.get("is_day"))})
    _grid.update(at=time.time(), points=pts)
    return _grid
