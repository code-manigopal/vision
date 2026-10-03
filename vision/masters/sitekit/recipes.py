"""Recipes: curated page designs. Each fixes the navigation, the hero, the sections (variant + panel tone, in the
order used for the recipe's home category = for[0]), a type pairing, shape language, spacing, heading treatment,
button style, image treatment, background treatment and the colour mode.

Section entries are (kind, variant, tone); tone is bg | alt | band | ink (see css.py). For a business outside the
recipe's home category the same variants are laid out in that category's order (categories.ORDER).
"""

from __future__ import annotations

SANS = '"Avenir Next","Segoe UI",system-ui,-apple-system,sans-serif'
SERIF = '"Iowan Old Style","Palatino Linotype",Georgia,serif'

SPACING = {
    "compact": {"section": "clamp(3.25rem,7vw,5rem)", "wrap": "1160px", "size": "1.0625rem"},
    "regular": {"section": "clamp(3.75rem,8vw,6rem)", "wrap": "1120px", "size": "1.0625rem"},
    "airy": {"section": "clamp(4.5rem,10vw,8rem)", "wrap": "1080px", "size": "1.09rem"},
    "wide": {"section": "clamp(3.5rem,7.5vw,5.75rem)", "wrap": "1240px", "size": "1.0625rem"},
}


def _type(pair: str, query: str, display: str, body: str) -> dict:
    return {"pair": pair, "query": query, "display": display, "body": body}


def _head(weight, case="none", tracking="-.01em", leading="1.1", h1="clamp(2.5rem,6vw,4.4rem)", h2="clamp(1.9rem,4vw,2.9rem)",
          align="left", eyebrow="caps") -> dict:
    return {"weight": str(weight), "case": case, "tracking": tracking, "leading": leading, "h1": h1, "h2": h2, "align": align, "eyebrow": eyebrow}


def _shape(radius, image_radius, border="1px", shadow="none", divider="none", gap=".85rem") -> dict:
    return {"radius": radius, "image_radius": image_radius, "border": border, "shadow": shadow, "divider": divider, "gap": gap}


def _btn(radius, weight="600", case="none", tracking="0", size="1rem") -> dict:
    return {"radius": radius, "weight": str(weight), "case": case, "tracking": tracking, "size": size}


RECIPES: dict[str, dict] = {
    "foreman": {
        "label": "Bold trade", "for": ["trade", "other"], "mode": "light", "nav": "bar", "hero": "diagonal", "hero_tone": "band",
        "sections": [("highlights", "strip", "alt"), ("services", "cards", "bg"), ("steps", "row", "alt"), ("area", "line", "band"),
                     ("gallery", "grid", "bg"), ("about", "stats", "alt"), ("reviews", "badge", "bg"), ("faq", "details", "alt"),
                     ("cta", "band", "band"), ("visit", "split", "bg")],
        "type": _type("Barlow Condensed + Manrope", "Barlow+Condensed:wght@600;700&family=Manrope:wght@400;600;800",
                      '"Barlow Condensed","Arial Narrow",Impact,sans-serif', '"Manrope",' + SANS),
        "heading": _head(700, "uppercase", ".01em", "1", "clamp(3rem,7.4vw,5.5rem)", "clamp(2.2rem,4.6vw,3.4rem)", eyebrow="rule"),
        "shape": _shape("4px", "4px", "2px", "hard", gap=".6rem"), "spacing": "compact",
        "button": _btn("4px", 800, "uppercase", ".06em", ".92rem"), "image": "plain", "background": "flat",
    },
    "forge": {
        "label": "Dark industrial", "for": ["trade", "health"], "mode": "dark", "nav": "minimal", "hero": "full", "hero_tone": "ink",
        "sections": [("highlights", "strip", "band"), ("services", "index", "bg"), ("gallery", "strip", "alt"), ("steps", "row", "bg"),
                     ("area", "line", "band"), ("about", "quote", "bg"), ("reviews", "wall", "alt"), ("faq", "details", "bg"),
                     ("cta", "band", "band"), ("visit", "stack", "bg")],
        "type": _type("Oswald + Work Sans", "Oswald:wght@500;600&family=Work+Sans:wght@400;500;600",
                      '"Oswald","Arial Narrow",Impact,sans-serif', '"Work Sans",' + SANS),
        "heading": _head(600, "uppercase", ".025em", "1.05", "clamp(2.7rem,6.6vw,5rem)", "clamp(2rem,4.2vw,3.1rem)", eyebrow="num"),
        "shape": _shape("0px", "0px", "1px", "none", "line", ".5rem"), "spacing": "compact",
        "button": _btn("0px", 600, "uppercase", ".1em", ".88rem"), "image": "mono", "background": "grid",
    },
    "clinic": {
        "label": "Clean clinical", "for": ["health", "pro", "care", "trade"], "mode": "light", "nav": "bar", "hero": "split", "hero_tone": "alt",
        "sections": [("highlights", "strip", "bg"), ("services", "tiles", "bg"), ("about", "media", "alt"), ("steps", "row", "bg"),
                     ("reviews", "badge", "alt"), ("gallery", "grid", "bg"), ("faq", "details", "alt"), ("area", "line", "bg"),
                     ("cta", "band", "band"), ("visit", "split", "bg")],
        "type": _type("Sora + Inter", "Sora:wght@500;600&family=Inter:wght@400;500;600", '"Sora",' + SANS, '"Inter",' + SANS),
        "heading": _head(600, "none", "-.03em", "1.12", "clamp(2.3rem,5.2vw,3.9rem)", "clamp(1.8rem,3.6vw,2.6rem)"),
        "shape": _shape("16px", "22px", "1px", "soft"), "spacing": "regular",
        "button": _btn("12px", 600), "image": "soft", "background": "flat",
    },
    "artisan": {
        "label": "Warm handmade", "for": ["food", "retail", "stay"], "mode": "light", "nav": "center", "hero": "collage", "hero_tone": "bg",
        "sections": [("highlights", "strip", "alt"), ("gallery", "mosaic", "bg"), ("services", "menu", "alt"), ("visit", "stack", "bg"),
                     ("about", "quote", "alt"), ("reviews", "lead", "bg"), ("faq", "details", "alt"), ("area", "line", "bg"),
                     ("steps", "row", "bg"), ("cta", "band", "band")],
        "type": _type("Young Serif + Karla", "Young+Serif&family=Karla:wght@400;500;700", '"Young Serif",' + SERIF, '"Karla",' + SANS),
        "heading": _head(400, "none", "-.015em", "1.08", "clamp(2.5rem,5.8vw,4.3rem)", "clamp(1.9rem,4vw,2.9rem)"),
        "shape": _shape("14px", "18px", "1px", "none", gap="1rem"), "spacing": "regular",
        "button": _btn("999px", 700), "image": "blob", "background": "dots",
    },
    "gazette": {
        "label": "Editorial magazine", "for": ["food", "beauty", "stay", "retail", "pro"], "mode": "light", "nav": "center", "hero": "type", "hero_tone": "bg",
        "sections": [("highlights", "strip", "bg"), ("gallery", "feature", "bg"), ("services", "rows", "bg"), ("visit", "split", "alt"),
                     ("about", "quote", "bg"), ("reviews", "lead", "ink"), ("faq", "details", "bg"), ("area", "line", "bg"),
                     ("steps", "row", "bg"), ("cta", "band", "alt")],
        "type": _type("Playfair Display + Source Serif 4", "Playfair+Display:ital,wght@0,500;0,700;1,500&family=Source+Serif+4:wght@400;600",
                      '"Playfair Display",' + SERIF, '"Source Serif 4",' + SERIF),
        "heading": _head(500, "none", "-.02em", "1.05", "clamp(2.6rem,6.4vw,4.8rem)", "clamp(2rem,4.4vw,3.2rem)", eyebrow="plain"),
        "shape": _shape("0px", "0px", "1px", "none", "double", ".5rem"), "spacing": "regular",
        "button": _btn("0px", 600, "uppercase", ".12em", ".8rem"), "image": "plain", "background": "flat",
    },
    "atelier": {
        "label": "Luxe minimal", "for": ["beauty", "retail", "stay"], "mode": "light", "nav": "center", "hero": "centered", "hero_tone": "bg",
        "sections": [("about", "media", "bg"), ("highlights", "strip", "alt"), ("services", "menu", "bg"), ("gallery", "feature", "alt"),
                     ("reviews", "lead", "bg"), ("steps", "row", "alt"), ("faq", "details", "bg"), ("area", "line", "bg"),
                     ("cta", "band", "alt"), ("visit", "stack", "bg")],
        "type": _type("Cormorant Garamond + Jost", "Cormorant+Garamond:ital,wght@0,400;0,500;1,400&family=Jost:wght@300;400;500",
                      '"Cormorant Garamond","Didot",' + SERIF, '"Jost",' + SANS),
        "heading": _head(400, "none", "0", "1.04", "clamp(2.9rem,7vw,5.4rem)", "clamp(2.2rem,4.8vw,3.5rem)", "center", "wide"),
        "shape": _shape("2px", "2px", "1px", "none", "none", "1rem"), "spacing": "airy",
        "button": _btn("0px", 500, "uppercase", ".2em", ".76rem"), "image": "arch", "background": "flat",
    },
    "sprout": {
        "label": "Playful rounded", "for": ["care", "food", "retail"], "mode": "light", "nav": "bar", "hero": "card", "hero_tone": "bg",
        "sections": [("highlights", "strip", "bg"), ("about", "media", "bg"), ("services", "tiles", "alt"), ("steps", "row", "bg"),
                     ("reviews", "wall", "alt"), ("gallery", "grid", "bg"), ("faq", "details", "alt"), ("area", "line", "bg"),
                     ("cta", "band", "band"), ("visit", "split", "bg")],
        "type": _type("Baloo 2 + Nunito", "Baloo+2:wght@600;700&family=Nunito:wght@400;600;800", '"Baloo 2","Trebuchet MS",' + SANS, '"Nunito",' + SANS),
        "heading": _head(700, "none", "-.01em", "1.08", "clamp(2.4rem,5.6vw,4.1rem)", "clamp(1.9rem,4vw,2.8rem)"),
        "shape": _shape("26px", "30px", "2px", "soft", gap="1rem"), "spacing": "regular",
        "button": _btn("999px", 800, size="1.02rem"), "image": "soft", "background": "grad",
    },
    "noir": {
        "label": "Dark premium", "for": ["beauty", "food", "retail", "stay"], "mode": "dark", "nav": "center", "hero": "full", "hero_tone": "ink",
        "sections": [("about", "quote", "bg"), ("highlights", "strip", "alt"), ("services", "index", "bg"), ("gallery", "strip", "alt"),
                     ("reviews", "lead", "bg"), ("steps", "row", "alt"), ("faq", "details", "bg"), ("area", "line", "bg"),
                     ("cta", "band", "band"), ("visit", "split", "alt")],
        "type": _type("Bodoni Moda + Figtree", "Bodoni+Moda:ital,wght@0,400;0,500;1,400&family=Figtree:wght@300;400;600",
                      '"Bodoni Moda","Didot",' + SERIF, '"Figtree",' + SANS),
        "heading": _head(400, "none", "-.01em", "1.08", "clamp(2.6rem,6.2vw,4.8rem)", "clamp(2rem,4.4vw,3.2rem)", eyebrow="plain"),
        "shape": _shape("0px", "0px", "1px", "none", "line", ".6rem"), "spacing": "airy",
        "button": _btn("0px", 600, "uppercase", ".16em", ".78rem"), "image": "plain", "background": "flat",
    },
    "mainstreet": {
        "label": "Neighbourhood classic", "for": ["other", "retail", "food", "trade", "care", "pro", "health"], "mode": "light", "nav": "bar",
        "hero": "strip", "hero_tone": "bg",
        "sections": [("highlights", "strip", "alt"), ("services", "cards", "bg"), ("about", "media", "alt"), ("gallery", "mosaic", "bg"),
                     ("reviews", "wall", "ink"), ("steps", "row", "bg"), ("faq", "details", "alt"), ("area", "line", "bg"),
                     ("cta", "band", "band"), ("visit", "split", "bg")],
        "type": _type("Libre Baskerville + Lato", "Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Lato:wght@400;700",
                      '"Libre Baskerville",' + SERIF, '"Lato",' + SANS),
        "heading": _head(700, "none", "-.015em", "1.15", "clamp(2.2rem,4.8vw,3.6rem)", "clamp(1.75rem,3.4vw,2.5rem)"),
        "shape": _shape("8px", "8px", "1px", "soft"), "spacing": "regular",
        "button": _btn("6px", 700), "image": "frame", "background": "flat",
    },
    "swiss": {
        "label": "Modern grid", "for": ["pro", "health", "trade", "retail", "other"], "mode": "light", "nav": "minimal", "hero": "type", "hero_tone": "bg",
        "sections": [("highlights", "strip", "bg"), ("services", "index", "bg"), ("about", "stats", "bg"), ("steps", "row", "bg"),
                     ("reviews", "badge", "bg"), ("faq", "details", "bg"), ("area", "line", "bg"), ("gallery", "grid", "bg"),
                     ("cta", "band", "ink"), ("visit", "stack", "bg")],
        "type": _type("Space Grotesk + IBM Plex Sans", "Space+Grotesk:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600",
                      '"Space Grotesk",' + SANS, '"IBM Plex Sans",' + SANS),
        "heading": _head(500, "none", "-.035em", "1.02", "clamp(2.5rem,6vw,4.4rem)", "clamp(1.9rem,4vw,2.9rem)", eyebrow="num"),
        "shape": _shape("0px", "0px", "1px", "none", "thick", ".4rem"), "spacing": "wide",
        "button": _btn("0px", 600, size=".98rem"), "image": "duo", "background": "grid",
    },
    "bloom": {
        "label": "Soft organic", "for": ["beauty", "health", "care"], "mode": "light", "nav": "minimal", "hero": "split", "hero_tone": "bg",
        "sections": [("about", "quote", "bg"), ("highlights", "strip", "alt"), ("services", "rows", "bg"), ("gallery", "mosaic", "alt"),
                     ("reviews", "wall", "bg"), ("steps", "row", "alt"), ("faq", "details", "bg"), ("area", "line", "bg"),
                     ("cta", "band", "band"), ("visit", "stack", "bg")],
        "type": _type("DM Serif Display + DM Sans", "DM+Serif+Display:ital@0;1&family=DM+Sans:wght@400;500;700", '"DM Serif Display",' + SERIF, '"DM Sans",' + SANS),
        "heading": _head(400, "none", "-.01em", "1.08", "clamp(2.5rem,5.8vw,4.3rem)", "clamp(1.95rem,4.2vw,3rem)", eyebrow="plain"),
        "shape": _shape("28px", "28px", "1px", "none", gap="1rem"), "spacing": "airy",
        "button": _btn("999px", 500), "image": "blob", "background": "grad",
    },
    "chalkboard": {
        "label": "Menu board", "for": ["food"], "mode": "dark", "nav": "bar", "hero": "centered", "hero_tone": "bg",
        "sections": [("highlights", "strip", "alt"), ("gallery", "strip", "bg"), ("services", "menu", "alt"), ("visit", "split", "bg"),
                     ("about", "media", "alt"), ("reviews", "badge", "bg"), ("faq", "details", "alt"), ("area", "line", "bg"),
                     ("steps", "row", "bg"), ("cta", "band", "band")],
        "type": _type("Yeseva One + Josefin Sans", "Yeseva+One&family=Josefin+Sans:wght@400;600", '"Yeseva One",' + SERIF, '"Josefin Sans",' + SANS),
        "heading": _head(400, "none", "0", "1.1", "clamp(2.5rem,6vw,4.5rem)", "clamp(1.95rem,4.2vw,3rem)", "center", "wide"),
        "shape": _shape("6px", "6px", "1px", "none", gap=".75rem"), "spacing": "regular",
        "button": _btn("6px", 600, "uppercase", ".1em", ".86rem"), "image": "frame", "background": "lines",
    },
    "harbour": {
        "label": "Calm and airy", "for": ["stay", "retail", "food", "health", "pro", "care", "other"], "mode": "light", "nav": "bar", "hero": "card", "hero_tone": "bg",
        "sections": [("gallery", "feature", "bg"), ("about", "stats", "alt"), ("services", "rows", "bg"), ("highlights", "strip", "band"),
                     ("reviews", "lead", "alt"), ("steps", "row", "bg"), ("faq", "details", "bg"), ("area", "line", "alt"),
                     ("cta", "band", "band"), ("visit", "stack", "bg")],
        "type": _type("Lora + Outfit", "Lora:ital,wght@0,500;0,600;1,500&family=Outfit:wght@300;400;600", '"Lora",' + SERIF, '"Outfit",' + SANS),
        "heading": _head(500, "none", "-.015em", "1.12", "clamp(2.3rem,5.2vw,3.9rem)", "clamp(1.85rem,3.8vw,2.75rem)", eyebrow="plain"),
        "shape": _shape("12px", "14px", "1px", "soft"), "spacing": "regular",
        "button": _btn("10px", 600), "image": "soft", "background": "flat",
    },
    "parlour": {
        "label": "Dark vintage", "for": ["beauty", "retail", "food"], "mode": "dark", "nav": "center", "hero": "strip", "hero_tone": "bg",
        "sections": [("about", "media", "bg"), ("highlights", "strip", "alt"), ("services", "cards", "alt"), ("gallery", "mosaic", "bg"),
                     ("reviews", "wall", "alt"), ("steps", "row", "bg"), ("faq", "details", "bg"), ("area", "line", "bg"),
                     ("cta", "band", "band"), ("visit", "split", "bg")],
        "type": _type("Abril Fatface + Libre Franklin", "Abril+Fatface&family=Libre+Franklin:wght@400;500;700", '"Abril Fatface",' + SERIF, '"Libre Franklin",' + SANS),
        "heading": _head(400, "none", ".005em", "1.08", "clamp(2.5rem,5.8vw,4.3rem)", "clamp(1.95rem,4.2vw,3rem)", "center", "wide"),
        "shape": _shape("2px", "2px", "1px", "none", "double", ".75rem"), "spacing": "regular",
        "button": _btn("2px", 700, "uppercase", ".12em", ".82rem"), "image": "offset", "background": "dots",
    },
}

DEFAULT = "mainstreet"
# the four pre-sitekit style names keep working
LEGACY = {"luxe": "atelier", "sunny": "sprout", "trade": "foreman", "editorial": "gazette"}


def recipe(style) -> tuple:
    """(name, recipe) for a recipe or legacy style name; the safe default for anything else."""
    name = LEGACY.get(style, style) if isinstance(style, str) else DEFAULT
    return (name, RECIPES[name]) if name in RECIPES else (DEFAULT, RECIPES[DEFAULT])
