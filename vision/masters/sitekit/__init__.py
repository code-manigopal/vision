"""sitekit: the Web Designer's section library.

render_site(lead, copy, theme, images, style) -> one self-contained HTML page (inline CSS, a tiny script, a Google
Fonts link). `style` is a recipe name (see RECIPES) or one of the four legacy names. The model only supplies words
(copy JSON) and the theme's four colours; layout, type and colour roles all come from here.
"""

from __future__ import annotations

import json

from . import color
from .categories import CATEGORIES, CATEGORY_OF, ORDER, WORDS, category_of, recipes_for
from .css import sheet
from .recipes import DEFAULT, LEGACY, RECIPES, SPACING, recipe
from .sections import ALLOCATION, HEROES, NAVS, SECTIONS, Page, city_of, e

__all__ = ["RECIPES", "CATEGORY_OF", "CATEGORIES", "STYLES", "STYLE_BY_TYPE", "recipes_for", "render_site", "category_of", "city_of", "signature"]

# every name render_site accepts: the recipes plus the four legacy styles
STYLES = {**RECIPES, **{old: RECIPES[new] for old, new in LEGACY.items()}}
# default look per Google Places type (the first recipe that suits it)
STYLE_BY_TYPE = {t: recipes_for(t)[0] for t in CATEGORY_OF}

JS = """document.documentElement.classList.add('js');
const d=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][new Date().getDay()];
document.querySelectorAll('.hours tr').forEach(r=>{if(r.dataset.day===d)r.classList.add('today')});
const io='IntersectionObserver' in window?new IntersectionObserver(es=>es.forEach(x=>{if(x.isIntersecting){x.target.classList.add('in');io.unobserve(x.target)}}),{threshold:.08}):null;
document.querySelectorAll('.rise').forEach(el=>io?io.observe(el):el.classList.add('in'));"""


def signature(name: str) -> tuple:
    """What makes a recipe structurally itself: nav, hero, each section's variant, and the type pairing."""
    r = RECIPES[name]
    return (r["nav"], r["hero"], tuple(sorted((k, v) for k, v, _ in r["sections"])), r["type"]["pair"], r["mode"])


def _order(r: dict, cat: str) -> list:
    """(kind, variant, tone) in page order: the recipe's own order in its home category, else the category's."""
    own = {k: (k, v, t) for k, v, t in r["sections"]}
    kinds = [k for k, _, _ in r["sections"]] if cat == r["for"][0] else ORDER[cat]
    return [own[k] for k in kinds if k in own]


def _skin(r: dict, roles: dict) -> str:
    h, s, b, sp, t = r["heading"], r["shape"], r["button"], SPACING[r["spacing"]], r["type"]
    soft = s["shadow"] == "soft"
    v = {**roles, "display": t["display"], "body": t["body"], "fs": sp["size"], "sp": sp["section"], "wrap": sp["wrap"],
         "hw": h["weight"], "hls": h["tracking"], "hcase": h["case"], "hlh": h["leading"], "h1": h["h1"], "h2": h["h2"],
         "r": s["radius"], "ri": s["image_radius"], "bw": s["border"], "bw1": f"max({s['border']},1px)", "gap": s["gap"],
         "shadow": "0 24px 46px -34px rgb(0 0 0/.4)" if soft else "none", "bsh": "0 12px 24px -16px rgb(0 0 0/.55)" if soft else "none",
         "rb": b["radius"], "bwt": b["weight"], "bcase": b["case"], "bls": b["tracking"], "bfs": b["size"], "bbw": "2px" if s["shadow"] == "hard" else "1.5px"}
    return ":root{" + ";".join(f"--{k}:{val}" for k, val in v.items()) + (";color-scheme:dark" if r["mode"] == "dark" else "") + "}"


def _build(lead: dict, copy: dict, images: list, r: dict, order: list, hero_tone: str) -> tuple:
    page = Page(lead, copy, images, r)
    hero = HEROES[r["hero"]](page, hero_tone)
    spec = {k: (v, t) for k, v, t in order}
    parts = {k: SECTIONS[k][spec[k][0]](page, spec[k][1]) for k in ALLOCATION if k in spec}
    return page, hero, parts


def _settle(order: list, parts: dict) -> list:
    """Two neighbouring panels of the same tinted tone read as one block: the second goes back to the page background."""
    out, prev = [], None
    for k, v, t in order:
        if not parts.get(k):
            out.append((k, v, t))
            continue
        if t == prev and t != "bg":
            t = "bg"
        out.append((k, v, t))
        prev = t
    return out


def render_site(lead: dict, copy: dict, theme: dict, images: list, style: str = DEFAULT) -> str:
    name, r = recipe(style)
    cat = category_of(lead.get("type"))
    order = _order(r, cat)
    page, hero, parts = _build(lead, copy, images, r, order, r["hero_tone"])
    settled = _settle(order, parts)
    if settled != order:
        order = settled
        page, hero, parts = _build(lead, copy, images, r, order, r["hero_tone"])
    body = "".join(parts[k] for k, _, _ in order if parts.get(k))
    present = [k for k, _, _ in order if parts.get(k) and k in page.words["nav"]]
    nav = NAVS[r["nav"]](page, present)
    fab = r["nav"] == "minimal" and page.tel
    roles = color.roles(theme if isinstance(theme, dict) else None, r["mode"])
    h, s = r["heading"], r["shape"]
    classes = [f"m-{r['mode']}", f"r-{name}", f"eb-{h['eyebrow']}", f"ha-{h['align']}", f"img-{r['image']}", f"bgp-{r['background']}", f"div-{s['divider']}"]
    classes += (["hard"] if s["shadow"] == "hard" else []) + (["has-fab"] if fab else ["has-callbar"] if page.tel else [])
    credits = " · ".join((f'<a href="{e(i["source"])}" rel="noopener">{e(i["credit"])}</a>' if i.get("source") else e(i["credit"])) for i in page.credits)
    ld = json.dumps({"@context": "https://schema.org", "@type": "LocalBusiness", "name": page.name, "telephone": lead.get("phone") or None,
                     "address": lead.get("address") or None}).replace("</", "<\\/")
    title = e(page.name) + (f" | {e(page.label)} in {e(page.city)}" if page.city else "")
    float_call = (page.call("btn btn-main fab") if fab else f'<div class="callbar">{page.call()}</div>') if page.tel else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{title}</title><meta name="description" content="{e(page.tagline)}"><meta name="robots" content="noindex"><meta name="generator" content="sitekit {e(name)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family={r['type']['query']}&display=swap" rel="stylesheet">
<script type="application/ld+json">{ld}</script><style>{_skin(r, roles)}{sheet(page.used)}</style></head><body class="{' '.join(classes)}">
<a class="skip" href="#main">Skip to content</a>
{nav}
<main id="main">{hero}
{body}</main>
<footer class="foot"><div class="wrap"><p class="fname">{e(page.name)}</p><p>Demo site prepared for {e(page.name)}. Not yet the business's official website.</p><p>Photos: {credits or 'none'}.</p></div></footer>
{float_call}<script>{JS}</script></body></html>"""
