"""World map for the 'map' scene (kind geography): Natural Earth 1:110m admin-0 countries (public domain), drawn as inline SVG.

The GeoJSON is fetched once into assets/maps/ (`fetch`); nothing is loaded from the internet at render time. Equirectangular
projection: x = (lon + 180) * K, y = (90 - lat) * K. Every function takes an optional `path` (tests use a tiny fixture).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "assets" / "maps" / "ne_110m_countries.geojson"
URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"
K = 10.0                                    # drawing units per degree
ALIASES = {"usa": "United States of America", "us": "United States of America", "u.s.": "United States of America",
           "america": "United States of America", "united states": "United States of America", "uk": "United Kingdom",
           "britain": "United Kingdom", "great britain": "United Kingdom", "england": "United Kingdom",
           "south korea": "South Korea", "north korea": "North Korea", "russia": "Russia", "czechia": "Czechia",
           "czech republic": "Czechia", "uae": "United Arab Emirates", "ivory coast": "Ivory Coast", "burma": "Myanmar",
           "drc": "Democratic Republic of the Congo", "congo": "Democratic Republic of the Congo", "holland": "Netherlands",
           "swaziland": "eSwatini", "eswatini": "eSwatini", "east timor": "Timor-Leste"}
_cache: dict[str, dict] = {}


class MapDataMissing(RuntimeError):
    pass


async def fetch(client: httpx.AsyncClient | None = None, path: Path | None = None) -> bool:
    """Download the country shapes once; True when the file is there afterwards."""
    path = Path(path or DATA)
    if path.is_file():
        return True
    own = client is None
    client = client or httpx.AsyncClient(timeout=60, follow_redirects=True)
    try:
        r = await client.get(URL)
        if r.status_code != 200 or '"features"' not in r.text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(r.text, encoding="utf-8")
        return True
    except httpx.HTTPError:
        return False
    finally:
        if own:
            await client.aclose()


def available(path: Path | None = None) -> bool:
    return Path(path or DATA).is_file()


def _polys(geom: dict) -> list[list[list[list[float]]]]:
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    return list(geom["coordinates"]) if geom["type"] == "MultiPolygon" else []


def _load(path: Path | None = None) -> dict:
    p = Path(path or DATA)
    if not p.is_file():
        raise MapDataMissing(f"map data missing: {p} (run maps.fetch)")
    key = f"{p}:{p.stat().st_mtime_ns}"
    if key not in _cache:
        feats, names = [], {}
        for i, f in enumerate(json.loads(p.read_text(encoding="utf-8"))["features"]):
            pr = f.get("properties") or {}
            canon = pr.get("NAME") or pr.get("ADMIN") or f"country {i}"
            iso = pr.get("ISO_A3") if pr.get("ISO_A3") not in (None, "-99") else (pr.get("ADM0_A3") or str(i))
            feats.append({"id": f"c-{iso}", "name": canon, "polys": _polys(f["geometry"])})
            for k in ("NAME", "NAME_LONG", "ADMIN", "NAME_EN"):
                if pr.get(k):
                    names[str(pr[k]).lower()] = canon
        by_canon = {x["name"].lower(): x["name"] for x in feats}
        for a, c in ALIASES.items():
            hit = by_canon.get(c.lower())
            if hit:
                names[a] = hit
        _cache[key] = {"feats": feats, "names": names}
    return _cache[key]


def names(path: Path | None = None) -> dict[str, str]:
    """lower-case alias -> canonical country name."""
    return dict(_load(path)["names"])


def known(name: str, path: Path | None = None) -> str | None:
    n = " ".join(str(name or "").lower().split())
    return _load(path)["names"].get(n) if n else None


def aliases_of(canon: str, path: Path | None = None) -> list[str]:
    return [a for a, c in _load(path)["names"].items() if c == canon]


def _xy(lon, lat):
    return (lon + 180) * K, (90 - lat) * K


def _path(poly) -> str:
    out = []
    for ring in poly:
        pts, last = [], None
        for lon, lat, *_ in ring:
            x, y = _xy(lon, lat)
            q = (round(x, 1), round(y, 1))
            if q != last:                     # drop points that round onto the previous one
                pts.append(q)
                last = q
        if len(pts) >= 3:
            out.append("M" + "L".join(f"{x:g} {y:g}" for x, y in pts) + "Z")
    return "".join(out)


def _bbox(poly):
    xs = [_xy(p[0], p[1])[0] for p in poly[0]]
    ys = [_xy(p[0], p[1])[1] for p in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


def _area(poly) -> float:
    x0, y0, x1, y1 = _bbox(poly)
    return (x1 - x0) * (y1 - y0)


def viewbox(highlight: list[str], width: int, height: int, focus: bool = True, path: Path | None = None) -> str:
    """viewBox string with the frame's aspect: the whole world (no Antarctica), or the highlighted countries plus padding."""
    d = _load(path)
    asp = width / height
    box = None
    if focus and highlight:
        want = {known(h, path) for h in highlight} - {None}
        pts = []
        for f in d["feats"]:
            if f["name"] in want and f["polys"]:
                big = max(f["polys"], key=_area)
                pts.append(_bbox(big))
                for p in f["polys"]:                       # islands and exclaves of a decent size count too
                    if _area(p) > 0.15 * _area(big):
                        pts.append(_bbox(p))
        if pts:
            x0, y0 = min(b[0] for b in pts), min(b[1] for b in pts)
            x1, y1 = max(b[2] for b in pts), max(b[3] for b in pts)
            w, h = max((x1 - x0) * 1.35, 25 * K), max((y1 - y0) * 1.35, 25 * K / asp)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if w / h < asp:
                w = h * asp
            else:
                h = w / asp
            w = min(w, 360 * K)
            h = w / asp
            box = (cx - w / 2, cy - h / 2, w, h)
    if box is None:                                        # the world, 60S to 85N, centred
        w = 360 * K
        h = w / asp
        cy = (90 - 12.5) * K
        box = (0, cy - h / 2, w, h)
    return " ".join(f"{v:.1f}" for v in box)


def svg(highlight: list[str], width: int, height: int, focus: bool = True, path: Path | None = None) -> str:
    """Inline <svg> of the world; highlighted countries (in order) have class 'land hl' and data-order 0..n."""
    d = _load(path)
    order = {}
    for h in highlight:
        c = known(h, path)
        if c and c not in order:
            order[c] = len(order)
    parts = []
    for f in d["feats"]:
        if f["name"] == "Antarctica" and f["name"] not in order:
            continue
        dd = "".join(_path(p) for p in f["polys"])
        if not dd:
            continue
        if f["name"] in order:
            parts.append(f'<path id="{f["id"]}" class="land hl" data-order="{order[f["name"]]}" d="{dd}"/>')
        else:
            parts.append(f'<path id="{f["id"]}" class="land" d="{dd}"/>')
    # highlighted countries are drawn last so their outline sits on top
    parts.sort(key=lambda s: ("hl" in s.split('class="')[1].split('"')[0], s.count("data-order") and int(re.search(r'data-order="(\d+)"', s).group(1))))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" id="worldmap" width="{width}" height="{height}" viewBox="{viewbox(highlight, width, height, focus, path)}" '
            'preserveAspectRatio="xMidYMid slice"><style>.land{fill:#1c2a3f;stroke:#2e4566;stroke-width:1.2;vector-effect:non-scaling-stroke}'
            '.land.hl{fill:#FBCA03;stroke:#fff3b0;stroke-width:1.5;opacity:0}</style>' + "".join(parts) + "</svg>")


def label_point(name: str, path: Path | None = None) -> tuple[float, float] | None:
    """Centre of a country's biggest piece, in drawing units (for a name tag)."""
    c = known(name, path)
    for f in _load(path)["feats"]:
        if f["name"] == c and f["polys"]:
            x0, y0, x1, y1 = _bbox(max(f["polys"], key=_area))
            return (x0 + x1) / 2, (y0 + y1) / 2
    return None
