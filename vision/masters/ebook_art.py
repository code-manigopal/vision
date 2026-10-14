"""Coloring-page checks and print preparation for the E-books Manager. Plain measurement, no model.

measure(png) reads a drawn page at a fixed 1024x1328 working size:
  grey   share of the page that stays mid-grey after a median filter (thin lines and their soft edges vanish,
         shading and grey fills stay). Line pages score up to ~0.17 (dense detail), shaded pages 0.4-0.97.
  solid  share still black after shrinking dark areas by 7 px: solid black fills (a black stage, a black sky).
  thin   share of line pixels that survive a 1 px erosion: low = hairlines a crayon can't follow.
  ink    share of the page that is black at all: too low = an empty page, too high = a page with no room to colour.
  tiny   white spaces too small for a child's crayon (under ~0.1 in across at print size), counted.
issues(m, ages) turns those into reasons a page is refused; the limits are tighter for the youngest children.
to_print() makes the page pure black and white at 300 DPI, fitted inside KDP's safe area.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

W, H = 1024, 1328          # working size (8.5 x 11 in shape)
DPI = 300

# per age band: (max tiny spaces, max ink share)
AGES = {"2-4": (150, 0.22), "4-8": (600, 0.32), "8-12": (1500, 0.42)}


def _gray(png: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(png)).convert("L")
    return im.resize((W, H), Image.LANCZOS)


def measure(png: bytes) -> dict:
    im = _gray(png)
    a = np.asarray(im)
    flat = np.asarray(im.filter(ImageFilter.MedianFilter(7)))
    grey = float(((flat > 70) & (flat < 215)).mean())
    solid = float((np.asarray(im.filter(ImageFilter.MaxFilter(15))) < 80).mean())
    black = a < 128
    ink = float(black.mean())
    eroded = ndimage.binary_erosion(black, iterations=1)
    thin = float(eroded.sum() / max(1, black.sum()))
    white, n = ndimage.label(~black)
    sizes = np.bincount(white.ravel())[1:] if n else np.array([])
    tiny = int(((sizes > 0) & (sizes < 90)).sum())       # ~9 px across at 1024 wide = under 0.1 in printed
    return {"grey": round(grey, 3), "solid": round(solid, 3), "thin": round(thin, 3), "ink": round(ink, 3), "tiny": tiny}


def issues(m: dict, ages: str = "4-8") -> list[str]:
    tiny_max, ink_max = AGES.get(ages, AGES["4-8"])
    out = []
    if m["grey"] > 0.30:
        out.append(f"grey shading ({m['grey']:.0%} of the page)")
    if m["solid"] > 0.03:
        out.append(f"solid black fill ({m['solid']:.0%} of the page)")
    if m["thin"] < 0.25:
        out.append("lines too thin to colour along")
    if m["ink"] < 0.04:
        out.append("almost empty page")
    if m["ink"] > ink_max:
        out.append(f"too much black for ages {ages} ({m['ink']:.0%})")
    if m["tiny"] > tiny_max:
        out.append(f"{m['tiny']} spaces too small to colour for ages {ages}")
    return out


def dhash(png: bytes) -> int:
    im = Image.open(io.BytesIO(png)).convert("L").resize((17, 16), Image.LANCZOS)
    a = np.asarray(im, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).ravel()
    return int("".join("1" if b else "0" for b in bits), 2)


def alike(a: int, b: int, limit: int = 40) -> bool:
    """Two pages are near-copies when their 256-bit difference hashes differ in fewer than `limit` bits."""
    return bin(a ^ b).count("1") < limit


def to_print(png: bytes, trim=(8.5, 11.0), inside: float = 0.625, outside: float = 0.5, odd: bool = True) -> Image.Image:
    """Pure black-and-white page at 300 DPI, the picture fitted inside the safe area (gutter `inside`, other edges
    `outside`, in inches; KDP's minimums for 24-150 pages without bleed are 0.375 in and 0.25 in)."""
    pw, ph = round(trim[0] * DPI), round(trim[1] * DPI)
    left = round((inside if odd else outside) * DPI)
    right = round((outside if odd else inside) * DPI)
    top = bottom = round(outside * DPI)
    bw, bh = pw - left - right, ph - top - bottom
    im = Image.open(io.BytesIO(png)).convert("L")
    s = min(bw / im.width, bh / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS).filter(ImageFilter.SMOOTH)
    im = im.point(lambda p: 255 if p > 150 else 0).convert("1")
    page = Image.new("1", (pw, ph), 1)
    page.paste(im, (left + (bw - im.width) // 2, top + (bh - im.height) // 2))
    return page
