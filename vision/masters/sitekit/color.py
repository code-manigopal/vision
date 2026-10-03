"""Colour roles for a page: the 4-colour theme (primary, accent, bg, text) -> a full, readable role set.

roles(theme, "light" | "dark") returns hex strings for every role the CSS uses. Every pair in PAIRS is tuned
until it reaches its WCAG ratio (4.5 for text, 3 for UI fills), keeping the hue so colours do not turn grey.
60/30/10: bg/surface/alt are the neutrals, band/ink the secondary panels, a/ia only fill calls to action.
"""

from __future__ import annotations

import colorsys

W, K = (255, 255, 255), (0, 0, 0)
DEFAULT = {"primary": "#1E3A5F", "accent": "#F2B134", "bg": "#F8F9FB", "text": "#16202B"}

# (foreground role, background role, minimum ratio) - the only combinations the stylesheet uses
PAIRS = [
    ("text", "bg", 4.5), ("text", "surface", 4.5), ("text", "alt", 4.5),
    ("muted", "bg", 4.5), ("muted", "surface", 4.5), ("muted", "alt", 4.5),
    ("p", "bg", 4.5), ("p", "surface", 4.5), ("p", "alt", 4.5), ("on-p", "p", 4.5),
    ("on-a", "a", 4.5), ("a", "bg", 3.0), ("a", "surface", 3.0), ("a", "alt", 3.0),
    ("on-band", "band", 4.5), ("band-muted", "band", 4.5), ("ia", "band", 4.5),
    ("on-ink", "ink", 4.5), ("ink-muted", "ink", 4.5), ("ia", "ink", 4.5), ("on-ia", "ia", 4.5),
]


def rgb(value, default: tuple = K) -> tuple:
    s = str(value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) if len(s) == 6 else default
    except ValueError:
        return default


def hx(c: tuple) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(v))) for v in c)


def lum(c: tuple) -> float:
    r, g, b = [(v / 255 / 12.92) if v / 255 <= 0.03928 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple, b: tuple) -> float:
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def mix(c: tuple, to: tuple, k: float) -> tuple:
    return tuple(round(x + (y - x) * k) for x, y in zip(c, to))


def _hls(c: tuple) -> tuple:
    return colorsys.rgb_to_hls(*[v / 255 for v in c])


def shade(c: tuple, light: float, min_sat: float = 0.0, max_sat: float = 1.0) -> tuple:
    """The same hue at another lightness (greys stay grey)."""
    h, _, s = _hls(c)
    s = min(max(s, min_sat), max_sat) if s > 0.08 else s
    return tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, min(max(light, 0.0), 1.0), s))


def tone(c: tuple, ok, to: str = "dark", min_sat: float = 0.0) -> tuple:
    """Step the lightness (hue kept) until ok(c); black or white as the last resort."""
    light, step = _hls(c)[1], (-0.02 if to == "dark" else 0.02)
    for _ in range(60):
        if ok(c):
            return c
        light += step
        if not 0.0 <= light <= 1.0:
            break
        c = shade(c, light, min_sat)
    return c if ok(c) else (K if to == "dark" else W)


def pull(c: tuple, to: tuple, ok) -> tuple:
    """Mix towards another colour until ok(c)."""
    for _ in range(40):
        if ok(c):
            return c
        c = mix(c, to, 0.1)
    return to


def on(c: tuple, dark: tuple = K) -> tuple:
    """Readable text colour on a fill: white, else the page's dark tone, else black."""
    if contrast(W, c) >= 4.5:
        return W
    return dark if contrast(dark, c) >= 4.5 else K


def _all(c: tuple, against: list, ratio: float) -> bool:
    return all(contrast(c, b) >= ratio for b in against)


def roles(theme: dict | None, mode: str = "light") -> dict:
    t = theme or {}
    P, A, BG, T = (rgb(t.get(k), rgb(DEFAULT[k])) for k in ("primary", "accent", "bg", "text"))
    if mode == "dark":
        h, _, s = _hls(P)
        s = min(s, 0.42) * 0.7 if s > 0.08 else s
        flat = lambda light, k=1.0: tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, light, s * k))
        bg, alt, surface, ink = flat(0.075), flat(0.105), flat(0.14), flat(0.04, 1.1)
        text = tone(mix(BG, W, 0.2), lambda c: contrast(c, surface) >= 11, "light")
        p = tone(shade(P, 0.7, 0.35, 0.8), lambda c: _all(c, [surface], 5.0), "light")
        band = tone(shade(P, 0.22, 0.35, 0.7), lambda c: contrast(text, c) >= 7 and contrast(c, bg) >= 1.25, "dark")
        if contrast(text, band) < 7:
            band = tone(band, lambda c: contrast(text, c) >= 7, "dark")
        on_band, on_ink, dark = text, text, ink
        a = tone(A, lambda c: _all(c, [bg, alt, surface], 3.2), "light", 0.3)
    else:
        bg = pull(BG, W, lambda c: lum(c) >= 0.78)
        surface, alt = mix(bg, W, 0.6), mix(bg, P, 0.07)
        text = tone(T, lambda c: contrast(c, alt) >= 11, "dark")
        p = tone(P, lambda c: _all(c, [alt, bg], 5.0), "dark", 0.4)
        on_band = on_ink = surface
        band = tone(P, lambda c: contrast(on_band, c) >= 6.5, "dark", 0.4)
        ink = tone(text, lambda c: contrast(on_ink, c) >= 13, "dark")
        dark = ink
        a = tone(A, lambda c: contrast(W, c) >= 4.6 and _all(c, [bg, alt, surface], 3.2), "dark", 0.55)   # white label on a saturated fill
    muted = pull(mix(text, bg, 0.36), text, lambda c: _all(c, [bg, alt, surface], 5.2))
    band_muted = pull(mix(on_band, band, 0.26), on_band, lambda c: contrast(c, band) >= 4.8)
    ink_muted = pull(mix(on_ink, ink, 0.3), on_ink, lambda c: contrast(c, ink) >= 4.8)
    ia = tone(A, lambda c: _all(c, [band, ink], 4.8), "light")
    out = {"bg": bg, "surface": surface, "alt": alt, "text": text, "muted": muted, "p": p, "on-p": on(p, dark),
           "a": a, "on-a": on(a, dark), "line": mix(bg, text, 0.16 if mode != "dark" else 0.2),
           "band": band, "on-band": on_band, "band-muted": band_muted,
           "ink": ink, "on-ink": on_ink, "ink-muted": ink_muted, "ia": ia, "on-ia": on(ia, dark)}
    return {k: hx(v) for k, v in out.items()}


def check(r: dict) -> list:
    """Pairs below their ratio, as (fg, bg, ratio, wanted) - empty when the role set is sound."""
    return [(f, b, round(contrast(rgb(r[f]), rgb(r[b])), 2), want) for f, b, want in PAIRS
            if contrast(rgb(r[f]), rgb(r[b])) < want]
