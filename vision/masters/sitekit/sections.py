"""Section variants: each function takes the Page and a tone and returns HTML ("" when it has nothing real to show).

Nothing here invents facts: sections only arrange the lead's data and the copy JSON, plus neutral UI wording.
Everything supplied from outside goes through e() (HTML-escaped).
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote_plus

from .categories import WORDS, category_of

_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
ICON = {
    "phone": _SVG + '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/></svg>',
    "pin": _SVG + '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/></svg>',
    "check": _SVG + '<path d="M20 6 9 17l-5-5"/></svg>',
}


def e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def city_of(lead: dict) -> str:
    parts = [p.strip() for p in (lead.get("address") or "").split(",")]
    return parts[-3] if len(parts) >= 3 else ""


def _text(v, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", str(v)).strip()[:limit] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _good_reviews(info: dict) -> list:
    """Up to three good reviews; older leads stored plain strings."""
    out = []
    for r in info.get("reviews") or []:
        r = {"text": r} if isinstance(r, str) else r if isinstance(r, dict) else {}
        text = re.sub(r"\s+", " ", str(r.get("text") or "")).strip()
        try:
            stars = int(r.get("rating") or 5)
        except (TypeError, ValueError):
            stars = 5
        if len(text) < 12 or stars < 4:
            continue
        if len(text) > 230:
            text = text[:230].rsplit(" ", 1)[0] + "…"
        out.append({"text": text, "author": r.get("author") or "Google review", "rating": min(stars, 5)})
    return out[:3]


def stars(n) -> str:
    n = max(0, min(5, int(round(n))))
    return "★" * n + "☆" * (5 - n)


class Page:
    """Everything a section needs: the cleaned lead and copy, the recipe, image allocation and the CSS it used."""

    def __init__(self, lead: dict, copy: dict, images: list, recipe: dict):
        copy = copy if isinstance(copy, dict) else {}
        self.lead, self.copy, self.R = lead, copy, recipe
        self.info = lead.get("info") if isinstance(lead.get("info"), dict) else {}
        self.name = str(lead.get("name") or "")
        self.city = city_of(lead)
        self.label = lead.get("type_label") or str(lead.get("type") or "").replace("_", " ").title()
        self.cat = category_of(lead.get("type"))
        self.words = WORDS[self.cat]
        self.phone = str(lead.get("phone") or "")
        self.tel = re.sub(r"[^0-9+]", "", self.phone)
        self.address = str(lead.get("address") or "")
        q = quote_plus(f"{self.name} {self.address}".strip())
        self.maps = self.info.get("maps_url") or ("https://www.google.com/maps/search/?api=1&query=" + q
                                                  + (f"&query_place_id={quote_plus(str(lead['id']))}" if lead.get("id") else ""))
        self.embed = "https://www.google.com/maps?output=embed&q=" + q
        try:
            self.rating = float(lead.get("rating") or 0) or None
        except (TypeError, ValueError):
            self.rating = None
        self.count = lead.get("reviews") if isinstance(lead.get("reviews"), int) and lead.get("reviews") > 0 else None
        self.revs = _good_reviews(self.info)
        self.headline = _text(copy.get("headline"), 120) or self.name
        self.tagline = _text(copy.get("tagline"), 240)
        self.services = [{"name": _text(s.get("name"), 80), "text": _text(s.get("text"), 240)}
                         for s in (copy.get("services") if isinstance(copy.get("services"), list) else [])
                         if isinstance(s, dict) and _text(s.get("name"))][:6]
        lst = lambda k: copy.get(k) if isinstance(copy.get(k), list) else []
        self.highlights = [t for t in (_text(h, 90) for h in lst("highlights")) if t][:3]
        self.steps = [{"title": _text(s.get("title"), 60), "text": _text(s.get("text"), 220)} for s in lst("steps")
                      if isinstance(s, dict) and _text(s.get("title"))][:4]
        self.faq = [{"q": _text(f.get("q"), 140), "a": _text(f.get("a"), 500)} for f in lst("faq")
                    if isinstance(f, dict) and _text(f.get("q")) and _text(f.get("a"))][:5]
        self.area = _text(copy.get("area"), 160)
        self.used: list = []
        self.hl_done = False
        # images: honour roles, else list order (first = hero, second = about, rest = gallery)
        imgs = [i for i in images or [] if isinstance(i, dict) and (i.get("file") or i.get("url"))]
        self.credits = [i for i in images or [] if isinstance(i, dict) and i.get("credit")]
        role = lambda r: next((i for i in imgs if i.get("role") == r), None)
        hero, about = role("hero"), role("about")
        rest = [i for i in imgs if i is not hero and i is not about]
        free = [i for i in rest if not i.get("role")]
        if hero is None and rest:
            hero = (free or rest)[0]
            rest.remove(hero)
        wants_about = dict((k, v) for k, v, _ in recipe["sections"]).get("about") == "media"
        if about is None and wants_about:
            free = [i for i in rest if not i.get("role")]
            if free:
                about = free[0]
                rest.remove(about)
        elif about is not None and not wants_about:
            rest.insert(0, about)
            about = None
        self.hero_img, self.about_img, self.pool = hero, about, rest

    # -- helpers
    def use(self, key: str) -> None:
        if key not in self.used:
            self.used.append(key)

    def take(self, n: int) -> list:
        """Photos for a section other than the gallery, taken from the end of the pool."""
        n = max(0, min(n, len(self.pool)))
        out = self.pool[len(self.pool) - n:] if n else []
        self.pool = self.pool[:len(self.pool) - n]
        return out

    def word(self, key: str) -> str:
        return _text(self.copy.get(key), 90) or self.words[key]

    def call(self, cls: str = "btn btn-main", short: bool = False) -> str:
        if not self.tel:
            return ""
        return f'<a class="{cls}" href="tel:{e(self.tel)}">{ICON["phone"]}<span>{"Call" if short else "Call " + e(self.phone)}</span></a>'

    def directions(self, cls: str = "btn btn-line") -> str:
        return f'<a class="{cls}" href="{e(self.maps)}" rel="noopener">{ICON["pin"]}<span>Get directions</span></a>'

    def rating_line(self) -> str:
        if not self.rating:
            return ""
        return (f'<p class="rating"><span class="stars" aria-hidden="true">{stars(self.rating)}</span><span>{self.rating:.1f} on Google'
                + (f" · {e(self.count)} reviews" if self.count else "") + "</span></p>")

    def ph(self, img: dict, cls: str = "", alt: str = "", eager: bool = False) -> str:
        alt = img.get("alt") if img.get("alt") else alt
        return (f'<figure class="ph {cls}"><img src="{e(img.get("file") or img.get("url"))}" alt="{e(alt)}"'
                + ("" if eager else ' loading="lazy"') + ' decoding="async"></figure>')

    def head(self, eyebrow: str, title: str, sub: str = "", cls: str = "head rise") -> str:
        return (f'<div class="{cls}"><p class="eyebrow">{e(eyebrow)}</p><h2>{e(title)}</h2>'
                + (f"<p>{e(sub)}</p>" if sub else "") + "</div>")

    def hours_table(self) -> str:
        rows = ""
        for h in self.info.get("hours") or []:
            day, _, when = str(h).partition(": ")
            rows += f'<tr data-day="{e(day)}"><th scope="row">{e(day)}</th><td>{e(when)}</td></tr>'
        return f'<table class="hours"><caption class="vh">Opening hours</caption>{rows}</table>' if rows else ""

    def facts(self) -> list:
        return [(v, k) for k, v in (("Google rating", f"{self.rating:.1f}" if self.rating else ""), ("Google reviews", self.count)) if v]


# ---------------------------------------------------------------- navigation
def _links(c: Page, present: list) -> list:
    return [f'<a class="link" href="#{i}">{e(c.words["nav"][i])}</a>' for i in present if i in c.words["nav"]]


def nav_bar(c: Page, present: list) -> str:
    c.use("nav.bar")
    return (f'<header class="top"><div class="wrap bar"><a class="brand" href="#top">{e(c.name)}</a>'
            f'<nav class="links" aria-label="Sections">{"".join(_links(c, present))}{c.call("btn btn-main nav-call")}</nav></div></header>')


def nav_center(c: Page, present: list) -> str:
    c.use("nav.center")
    links = _links(c, present)
    half = (len(links) + 1) // 2
    return (f'<header class="top nav-center"><div class="wrap bar"><nav class="links l" aria-label="Sections">{"".join(links[:half])}</nav>'
            f'<a class="brand" href="#top">{e(c.name)}</a>'
            f'<nav class="links r" aria-label="More sections">{"".join(links[half:])}{c.call("btn btn-main nav-call", short=True)}</nav></div></header>')


def nav_minimal(c: Page, present: list) -> str:
    c.use("nav.minimal")
    tel = f'<a class="tel tlink" href="tel:{e(c.tel)}">{e(c.phone)}</a>' if c.tel else ""
    return (f'<header class="top nav-min"><div class="wrap bar"><a class="brand" href="#top">{e(c.name)}</a>'
            f'<nav class="links" aria-label="Sections">{"".join(_links(c, present)[:4])}{tel}</nav></div></header>')


NAVS = {"bar": nav_bar, "center": nav_center, "minimal": nav_minimal}


# ---------------------------------------------------------------- heroes
def _hero_copy(c: Page, lede: bool = True, ctas: bool = True) -> str:
    eyebrow = " · ".join(x for x in (c.label, c.city) if x)
    return ((f'<p class="eyebrow">{e(eyebrow)}</p>' if eyebrow else "") + f"<h1>{e(c.headline)}</h1>"
            + (f'<p class="lede">{e(c.tagline)}</p>' if lede and c.tagline else "")
            + (f'<div class="ctas">{c.call()}{c.directions()}</div>{c.rating_line()}' if ctas else ""))


def _hero(c: Page, key: str, cls: str, tone: str, inner: str, after: str = "", before: str = "") -> str:
    c.use(key)
    return (f'<section class="hero sec {cls} t-{tone}{"" if c.hero_img else " noimg"}" id="top">{before}'
            f'<div class="wrap hero-in">{inner}</div>{after}</section>')


def hero_split(c: Page, tone: str) -> str:
    side = c.ph(c.hero_img, "fr port", c.label, True) if c.hero_img else ""
    return _hero(c, "hero.split", "h-split", tone, f'<div class="hero-txt">{_hero_copy(c)}</div>{side}',
                 before="" if c.hero_img else '<div class="deco" aria-hidden="true"></div>')


def hero_full(c: Page, tone: str) -> str:
    bg = c.ph(c.hero_img, "bgph", "", True) if c.hero_img else '<div class="deco" aria-hidden="true"></div>'
    return _hero(c, "hero.full", "h-full", "ink" if c.hero_img else "band", f'<div class="hero-txt">{_hero_copy(c)}</div>', before=bg)


def hero_type(c: Page, tone: str) -> str:
    eyebrow = " · ".join(x for x in (c.label, c.city) if x)
    inner = ((f'<p class="eyebrow">{e(eyebrow)}</p>' if eyebrow else "") + f"<h1>{e(c.headline)}</h1>"
             + '<div class="hero-row"><div>' + (f'<p class="lede">{e(c.tagline)}</p>' if c.tagline else "") + c.rating_line() + "</div>"
             + f'<div class="ctas">{c.call()}{c.directions()}</div></div>'
             + (c.ph(c.hero_img, "land", c.label, True) if c.hero_img else ""))
    return _hero(c, "hero.type", "h-type", tone, inner)


def hero_collage(c: Page, tone: str) -> str:
    side = ""
    if c.hero_img:
        shots = [c.hero_img] + c.take(min(2, max(0, len(c.pool) - 2)))
        side = (f'<div class="stack n{len(shots)}">'
                + "".join(c.ph(i, f"s{n}", c.label if n == 1 else "", True) for n, i in enumerate(shots, 1)) + "</div>")
    return _hero(c, "hero.collage", "h-collage", tone, f'<div class="hero-txt">{_hero_copy(c)}</div>{side}',
                 before="" if c.hero_img else '<div class="deco" aria-hidden="true"></div>')


def hero_card(c: Page, tone: str) -> str:
    bg = c.ph(c.hero_img, "bgph", c.label, True) if c.hero_img else '<div class="ph bgph" aria-hidden="true"></div>'
    return _hero(c, "hero.card", "h-card", tone, f'<div class="hcard t-bg">{_hero_copy(c)}</div>', before=bg)


def hero_diagonal(c: Page, tone: str) -> str:
    side = c.ph(c.hero_img, "dph", c.label, True) if c.hero_img else '<div class="ph dph" aria-hidden="true"></div>'
    return _hero(c, "hero.diagonal", "h-diag", tone, f'<div class="hero-txt">{_hero_copy(c)}</div><div></div>', after=side)


def hero_centered(c: Page, tone: str) -> str:
    return _hero(c, "hero.centered", "h-center", tone, f'<div class="hero-txt">{_hero_copy(c)}</div>'
                 + (c.ph(c.hero_img, "fr land", c.label, True) if c.hero_img else ""),
                 before="" if c.hero_img else '<div class="deco" aria-hidden="true"></div>')


def hero_strip(c: Page, tone: str) -> str:
    """Split hero closed by a strip of the copy's highlights (else the facts we have: rating, reviews, town)."""
    items = c.highlights
    if items:
        c.hl_done = True
    else:
        items = [x for x in (f"{c.rating:.1f} rating on Google" if c.rating else "", f"{c.count} Google reviews" if c.count else "", c.city) if x]
        items = items if len(items) >= 2 else []
    strip = (f'<div class="hstrip t-{"band" if tone != "band" else "ink"}"><div class="wrap"><ul>'
             + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul></div></div>") if items else ""
    side = c.ph(c.hero_img, "fr land", c.label, True) if c.hero_img else ""
    return _hero(c, "hero.strip", "h-strip", tone, f'<div class="hero-txt">{_hero_copy(c)}</div>{side}', after=strip,
                 before="" if c.hero_img else '<div class="deco" aria-hidden="true"></div>')


HEROES = {"split": hero_split, "full": hero_full, "type": hero_type, "collage": hero_collage, "card": hero_card,
          "diagonal": hero_diagonal, "centered": hero_centered, "strip": hero_strip}


# ---------------------------------------------------------------- services
def _services(c: Page, tone: str, key: str, body: str) -> str:
    c.use(key)
    return (f'<section class="sec svc t-{tone}" id="services"><div class="wrap">'
            f'{c.head(c.words["services_eyebrow"], c.word("services_title"))}{body}</div></section>')


def services_cards(c: Page, tone: str) -> str:
    if not c.services:
        return ""
    return _services(c, tone, "svc.cards", '<ul class="cards rise">' + "".join(
        f'<li class="card"><span class="n" aria-hidden="true">{n:02d}</span><h3>{e(s["name"])}</h3><p>{e(s["text"])}</p></li>'
        for n, s in enumerate(c.services, 1)) + "</ul>")


def services_menu(c: Page, tone: str) -> str:
    if not c.services:
        return ""
    return _services(c, tone, "svc.menu", '<ul class="menu rise">' + "".join(
        f'<li><h3>{e(s["name"])}</h3><p>{e(s["text"])}</p></li>' for s in c.services) + "</ul>")


def services_index(c: Page, tone: str) -> str:
    if not c.services:
        return ""
    return _services(c, tone, "svc.index", '<ul class="index rise">' + "".join(
        f'<li><span class="n" aria-hidden="true">{n:02d}</span><h3>{e(s["name"])}</h3><p>{e(s["text"])}</p></li>'
        for n, s in enumerate(c.services, 1)) + "</ul>")


def services_rows(c: Page, tone: str) -> str:
    if not c.services:
        return ""
    items = lambda group: "<ul>" + "".join(f'<li><h3>{e(s["name"])}</h3><p>{e(s["text"])}</p></li>' for s in group) + "</ul>"
    shots = c.take(2 if len(c.services) >= 4 and len(c.pool) >= 4 else 1 if len(c.pool) >= 3 else 0)
    if not shots:
        return _services(c, tone, "svc.rows", f'<div class="rows rise"><div class="srow solo">{items(c.services)}</div></div>')
    half = (len(c.services) + 1) // 2 if len(shots) == 2 else len(c.services)
    groups = [g for g in (c.services[:half], c.services[half:]) if g]
    rows = "".join(f'<div class="srow{" flip" if n % 2 else ""} rise">{c.ph(shots[n], "fr land")}{items(g)}</div>' for n, g in enumerate(groups))
    return _services(c, tone, "svc.rows", f'<div class="rows">{rows}</div>')


def services_tiles(c: Page, tone: str) -> str:
    if not c.services:
        return ""
    return _services(c, tone, "svc.tiles", '<ul class="tiles rise">' + "".join(
        f'<li><h3>{e(s["name"])}</h3><p>{e(s["text"])}</p></li>' for s in c.services) + "</ul>")


# ---------------------------------------------------------------- about
def _about_text(c: Page, facts: bool = True) -> str:
    about = _text(c.copy.get("about"), 900)
    fx = "".join(f"<div><b>{e(v)}</b><span>{e(k)}</span></div>" for v, k in c.facts()) if facts else ""
    return (f'<p class="eyebrow">{e(c.words["about_eyebrow"])}</p><h2>{e(_text(c.copy.get("about_title"), 90) or c.name)}</h2>'
            + (f'<p class="body">{e(about)}</p>' if about else "") + (f'<div class="facts">{fx}</div>' if fx else ""))


def about_media(c: Page, tone: str) -> str:
    c.use("about.media")
    port = c.R["image"] in ("arch", "blob")
    img = c.ph(c.about_img, "fr rise " + ("port" if port else "land")) if c.about_img else ""
    return (f'<section class="sec about t-{tone}" id="about"><div class="wrap ab-media{"" if img else " solo"}">{img}'
            f'<div class="rise">{_about_text(c)}</div></div></section>')


def about_quote(c: Page, tone: str) -> str:
    """The about text beside a pull-quote from a real review (only when another review is left for the reviews section)."""
    c.use("about.quote")
    quote = ""
    if len(c.revs) >= 2:
        r = c.revs.pop(0)
        quote = (f'<figure class="pull rise"><blockquote>{e(r["text"])}</blockquote>'
                 f'<figcaption>{e(r["author"])} · Google review</figcaption></figure>')
    return (f'<section class="sec about t-{tone}" id="about"><div class="wrap ab-quote{"" if quote else " solo"}">'
            f'<div class="rise">{_about_text(c, facts=not quote)}</div>{quote}</div></section>')


def about_stats(c: Page, tone: str) -> str:
    c.use("about.stats")
    rows = [(v, k, "") for v, k in c.facts()] + ([(c.city, "Where we are", "w")] if c.city else [])
    band = ('<div class="statband rise">' + "".join(f'<div><b class="{w}">{e(v)}</b><span>{e(k)}</span></div>' for v, k, w in rows) + "</div>") if len(rows) >= 2 else ""
    return (f'<section class="sec about t-{tone}" id="about"><div class="wrap ab-stats{"" if band else " solo"}">'
            f'<div class="rise">{_about_text(c, facts=False)}</div>{band}</div></section>')


# ---------------------------------------------------------------- gallery
def _gallery(c: Page, tone: str, key: str, build) -> str:
    """0 photos: no section. 1: one wide photo. 2: a pair. 3+: the variant."""
    shots = c.pool[:6]
    if not shots:
        return ""
    c.use("gal")
    pics = lambda group: "".join(c.ph(i) for i in group)
    full = False
    if len(shots) == 1:
        body = f'<div class="g-one rise">{pics(shots)}</div>'
    elif len(shots) == 2:
        body = f'<div class="g-two rise">{pics(shots)}</div>'
    else:
        c.use(key)
        body, full = build(shots, pics)
    head = c.head(c.words["gallery_eyebrow"], c.word("gallery_title"))
    inner = f'<div class="wrap">{head}</div>{body}' if full else f'<div class="wrap">{head}{body}</div>'
    return f'<section class="sec gal t-{tone}" id="gallery">{inner}</section>'


def gallery_mosaic(c: Page, tone: str) -> str:
    def build(shots, pics):
        shots = shots[:5]
        return f'<div class="mosaic n{len(shots)} rise">{pics(shots)}</div>', False
    return _gallery(c, tone, "gal.mosaic", build)


def gallery_grid(c: Page, tone: str) -> str:
    def build(shots, pics):
        shots = shots[:6 if len(shots) >= 6 else 4 if len(shots) >= 4 else 3]
        return f'<div class="ggrid n{len(shots)} rise">{pics(shots)}</div>', False
    return _gallery(c, tone, "gal.grid", build)


def gallery_strip(c: Page, tone: str) -> str:
    def build(shots, pics):
        return f'<div class="film" tabindex="0" role="region" aria-label="Photo gallery, scroll sideways">{pics(shots)}</div>', True
    return _gallery(c, tone, "gal.strip", build)


def gallery_feature(c: Page, tone: str) -> str:
    def build(shots, pics):
        return f'<div class="feat rise">{pics(shots[:3])}</div>', False
    return _gallery(c, tone, "gal.feature", build)


# ---------------------------------------------------------------- reviews
def _rev(r: dict, cls: str = "rev") -> str:
    return (f'<figure class="{cls}"><span class="stars" aria-hidden="true">{stars(r["rating"])}</span>'
            f'<blockquote>“{e(r["text"])}”</blockquote><figcaption>{e(r["author"])} · Google</figcaption></figure>')


def _more(c: Page) -> str:
    return f'<a class="btn btn-line" href="{e(c.maps)}" rel="noopener">Read more on Google</a>'


def _score(c: Page) -> str:
    return (f'<div class="score"><b>{c.rating:.1f}</b><span class="stars" aria-hidden="true">{stars(c.rating)}</span>'
            f'<span class="vh">out of 5 on Google</span></div>') if c.rating else ""


def reviews_wall(c: Page, tone: str) -> str:
    if not c.revs:
        return ""
    c.use("rev.wall")
    return (f'<section class="sec reviews t-{tone}" id="reviews"><div class="wrap"><div class="rev-top rise">'
            f'{c.head(c.words["reviews_eyebrow"], c.word("reviews_title"), cls="head")}{_score(c)}</div>'
            f'<div class="wall rise">{"".join(_rev(r, "rev card") for r in c.revs)}</div><p class="rev-more rise">{_more(c)}</p></div></section>')


def reviews_lead(c: Page, tone: str) -> str:
    if not c.revs:
        return ""
    c.use("rev.lead")
    first, rest = c.revs[0], c.revs[1:]
    big = (f'<figure class="rev big rise"><span class="stars" aria-hidden="true">{stars(first["rating"])}</span>'
           f'<blockquote>“{e(first["text"])}”</blockquote><figcaption>{e(first["author"])} · Google</figcaption></figure>')
    small = f'<div class="rsmall rise">{"".join(_rev(r) for r in rest)}</div>' if rest else ""
    return (f'<section class="sec reviews t-{tone}" id="reviews"><div class="wrap"><div class="rev-top rise">'
            f'{c.head(c.words["reviews_eyebrow"], c.word("reviews_title"), cls="head")}{_score(c)}</div>'
            f'<div class="rlead">{big}{small}</div><p class="rev-more rise">{_more(c)}</p></div></section>')


def reviews_badge(c: Page, tone: str) -> str:
    if not c.revs:
        return ""
    c.use("rev.badge")
    badge = (f'<aside class="badge card rise"><b>{c.rating:.1f}</b><span class="stars" aria-hidden="true">{stars(c.rating)}</span>'
             f'<p>{f"{e(c.count)} reviews on Google" if c.count else "Rating on Google"}</p>{_more(c)}</aside>') if c.rating else ""
    return (f'<section class="sec reviews t-{tone}" id="reviews"><div class="wrap">{c.head(c.words["reviews_eyebrow"], c.word("reviews_title"))}'
            f'<div class="rbadge{"" if badge else " solo"}">{badge}<div class="rquotes rise">{"".join(_rev(r) for r in c.revs)}'
            + ("" if badge else f'<p class="rev-more">{_more(c)}</p>') + "</div></div></div></section>")


# ---------------------------------------------------------------- extras (only when the copy provides them)
def highlights(c: Page, tone: str) -> str:
    if not c.highlights or c.hl_done:
        return ""
    c.use("x.hl")
    return (f'<section class="sec hl t-{tone}" id="highlights" aria-label="Highlights"><div class="wrap"><ul class="rise">'
            + "".join(f'<li>{ICON["check"]}<span>{e(h)}</span></li>' for h in c.highlights) + "</ul></div></section>")


def steps(c: Page, tone: str) -> str:
    if not c.steps:
        return ""
    c.use("x.steps")
    return (f'<section class="sec t-{tone}" id="steps"><div class="wrap">{c.head(c.words["steps_eyebrow"], c.words["steps_title"])}'
            '<ol class="steps rise">'
            + "".join(f'<li><h3>{e(s["title"])}</h3>' + (f'<p>{e(s["text"])}</p>' if s["text"] else "") + "</li>" for s in c.steps)
            + "</ol></div></section>")


def faq(c: Page, tone: str) -> str:
    if not c.faq:
        return ""
    c.use("x.faq")
    return (f'<section class="sec t-{tone}" id="faq"><div class="wrap faq">{c.head(c.words["faq_eyebrow"], c.words["faq_title"])}<div class="rise">'
            + "".join(f'<details><summary>{e(f["q"])}</summary><p>{e(f["a"])}</p></details>' for f in c.faq)
            + "</div></div></section>")


def cta(c: Page, tone: str) -> str:
    title, text = _text(c.copy.get("cta_title"), 90), _text(c.copy.get("cta_text"), 240)
    if not (title or text):
        return ""
    c.use("x.cta")
    return (f'<section class="sec cta t-{tone}" id="cta"><div class="wrap rise">'
            + (f"<h2>{e(title)}</h2>" if title else "") + (f"<p>{e(text)}</p>" if text else "")
            + f'<div class="ctas">{c.call()}{c.directions()}</div></div></section>')


def area(c: Page, tone: str) -> str:
    if not c.area:
        return ""
    c.use("x.area")
    return (f'<section class="sec area t-{tone}" id="area"><div class="wrap rise"><p class="eyebrow">{e(c.words["area_eyebrow"])}</p>'
            f'<p class="big">{e(c.words["area_prefix"])} {e(c.area)}</p></div></section>')


# ---------------------------------------------------------------- visit
def _where(c: Page) -> str:
    return ((f'<p class="where">{ICON["pin"]}<a class="tlink" href="{e(c.maps)}" rel="noopener">{e(c.address)}</a></p>' if c.address else "")
            + (f'<p class="where">{ICON["phone"]}<a class="tlink" href="tel:{e(c.tel)}">{e(c.phone)}</a></p>' if c.tel else ""))


def _map(c: Page) -> str:
    return (f'<div class="map rise"><iframe src="{e(c.embed)}" loading="lazy" title="Map showing {e(c.name)}" '
            'referrerpolicy="no-referrer-when-downgrade"></iframe></div>')


def visit_split(c: Page, tone: str) -> str:
    c.use("visit.split")
    return (f'<section class="sec visit t-{tone}" id="visit"><div class="wrap v-split"><div class="rise">'
            f'{c.head(c.words["visit_eyebrow"], c.word("visit_title"), cls="head")}{_where(c)}{c.hours_table()}'
            f'<div class="ctas">{c.call()}{c.directions()}</div></div>{_map(c)}</div></section>')


def visit_stack(c: Page, tone: str) -> str:
    c.use("visit.stack")
    hours = c.hours_table()
    cards = (f'<div class="card"><h3 class="sm">{e(c.words["where_label"])}</h3>{_where(c)}<div class="ctas">{c.call()}{c.directions()}</div></div>'
             + (f'<div class="card"><h3 class="sm">Hours</h3>{hours}</div>' if hours else ""))
    return (f'<section class="sec visit t-{tone}" id="visit"><div class="wrap v-stack">{c.head(c.words["visit_eyebrow"], c.word("visit_title"))}'
            f'<div class="v-cards rise">{cards}</div>{_map(c)}</div></section>')


SECTIONS = {
    "services": {"cards": services_cards, "menu": services_menu, "index": services_index, "rows": services_rows, "tiles": services_tiles},
    "about": {"media": about_media, "quote": about_quote, "stats": about_stats},
    "gallery": {"mosaic": gallery_mosaic, "grid": gallery_grid, "strip": gallery_strip, "feature": gallery_feature},
    "reviews": {"wall": reviews_wall, "lead": reviews_lead, "badge": reviews_badge},
    "highlights": {"strip": highlights}, "steps": {"row": steps}, "faq": {"details": faq}, "cta": {"band": cta}, "area": {"line": area},
    "visit": {"split": visit_split, "stack": visit_stack},
}
# photos are handed out in this order, so the gallery gets what the other sections left
ALLOCATION = ["services", "about", "highlights", "steps", "faq", "cta", "area", "reviews", "visit", "gallery"]
