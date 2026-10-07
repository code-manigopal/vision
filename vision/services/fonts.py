"""Caption fonts: ten bold display faces on disk, and caption looks (font + colours) by content mood.

    assets/fonts/<File>.ttf   static fonts from the official Google Fonts repository (all SIL OFL or Apache 2.0)

`fetch` downloads the ones missing; `style_for` gives the Editor a look for a Short's mood or kind, a different one
each time (`turn`). Colours are light enough to read over video with a black outline; the highlight is for the
word being spoken. `font` is None when the file isn't on disk, so the Editor can keep its own default.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from ..config import ROOT

DIR = ROOT / "assets" / "fonts"
BASE = "https://github.com/google/fonts/raw/main/"
# name: (file, path in the repo, licence)
_F = {"Anton": ("Anton-Regular.ttf", "ofl/anton", "SIL OFL 1.1"),
      "Bebas Neue": ("BebasNeue-Regular.ttf", "ofl/bebasneue", "SIL OFL 1.1"),
      "Luckiest Guy": ("LuckiestGuy-Regular.ttf", "apache/luckiestguy", "Apache 2.0"),
      "Bangers": ("Bangers-Regular.ttf", "ofl/bangers", "SIL OFL 1.1"),
      "Permanent Marker": ("PermanentMarker-Regular.ttf", "apache/permanentmarker", "Apache 2.0"),
      "Archivo Black": ("ArchivoBlack-Regular.ttf", "ofl/archivoblack", "SIL OFL 1.1"),
      "Alfa Slab One": ("AlfaSlabOne-Regular.ttf", "ofl/alfaslabone", "SIL OFL 1.1"),
      "Titan One": ("TitanOne-Regular.ttf", "ofl/titanone", "SIL OFL 1.1"),
      "Black Ops One": ("BlackOpsOne-Regular.ttf", "ofl/blackopsone", "SIL OFL 1.1"),
      "Abril Fatface": ("AbrilFatface-Regular.ttf", "ofl/abrilfatface", "SIL OFL 1.1")}
FONTS = [{"name": n, "file": f, "url": f"{BASE}{p}/{f}", "license": lic} for n, (f, p, lic) in _F.items()]

_L = lambda font, fill, highlight: {"font": font, "fill": fill, "highlight": highlight}
STYLES: dict[str, list[dict]] = {
    "dark": [_L("Bebas Neue", "#EAF2FF", "#7FD6FF"), _L("Black Ops One", "#F2F2F2", "#E01E2D"), _L("Anton", "#E8EEF5", "#FF3B3B")],
    "sad": [_L("Abril Fatface", "#F4F1FA", "#B8C7FF"), _L("Archivo Black", "#F3F6FA", "#C9B6F2")],
    "warm": [_L("Alfa Slab One", "#FFF4DC", "#FFB627"), _L("Abril Fatface", "#FFF1D6", "#FF8A3D")],
    "light": [_L("Luckiest Guy", "#FFFFFF", "#FFE600"), _L("Bangers", "#FFFFFF", "#FF4FA3"), _L("Titan One", "#FFFFFF", "#A6FF00"),
              _L("Permanent Marker", "#FFFFFF", "#FF4FA3")],
    "dramatic": [_L("Anton", "#FFFFFF", "#FF2D2D"), _L("Bebas Neue", "#FFFFFF", "#FF7A00")],
    "money": [_L("Archivo Black", "#FFFFFF", "#2EE06F"), _L("Alfa Slab One", "#FFFFFF", "#FFD21F")],
    "science": [_L("Bebas Neue", "#FFFFFF", "#27E6FF"), _L("Archivo Black", "#FFFFFF", "#3D8BFF")],
}
DEFAULT = [_L("Anton", "#FFFFFF", "#FFD21F"), _L("Archivo Black", "#FFFFFF", "#FF4FA3")]   # unknown or empty mood


def path(name: str) -> str | None:
    f = next((x["file"] for x in FONTS if x["name"] == name), None)
    return str(DIR / f) if f and (DIR / f).exists() else None


async def fetch(client: httpx.AsyncClient | None = None) -> list[str]:
    """Download the fonts not yet on disk. Returns the names newly saved; one failure doesn't stop the rest."""
    DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    async with (client or httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True)) as c:
        for f in FONTS:
            if (DIR / f["file"]).exists():
                continue
            try:
                r = await c.get(f["url"])
            except httpx.HTTPError:
                continue
            if r.status_code == 200 and len(r.content) > 5_000:
                (DIR / f["file"]).write_bytes(r.content)
                saved.append(f["name"])
    return saved


def style_for(mood: str, kind: str = "", turn: int = 0) -> dict:
    """The caption look for a Short: kind (money, science) beats mood; `turn` moves through the list."""
    looks = STYLES.get(kind) or STYLES.get(mood) or DEFAULT
    s = looks[turn % len(looks)]
    return {"font": path(s["font"]), "font_name": s["font"], "fill": s["fill"], "highlight": s["highlight"], "stroke": "#000000", "position": "center"}
