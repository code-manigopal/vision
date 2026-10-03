"""The original Web Designer page, kept as the style "classic": one layout in four looks (luxe, sunny, trade,
editorial), picked by business type as it always was. The look comes from the variant (fonts, hero layout, services
layout, corner radius), the colours from the ColorHunt theme, the words from the copy JSON.
Only real facts are shown: sections with no data (reviews, hours, gallery, rating) are left out.

Two things differ from the original: content is visible even when the page's script doesn't run, and the gallery
heading fits the kind of business.
"""

from __future__ import annotations

import html
import json
import re
from urllib.parse import quote_plus

from .categories import WORDS, category_of

# fonts = Google Fonts css2 families; hero: split (text + framed photo) | full (photo behind text);
# services: menu (ruled list) | cards (numbered cards); frame = border-radius of the hero photo
STYLES = {
    "luxe": {"fonts": "Marcellus&family=Jost:wght@300;400;500", "display": '"Marcellus","Didot",Georgia,serif', "body": '"Jost","Avenir Next","Segoe UI",system-ui,sans-serif',
             "weight": "400", "hero": "split", "services": "menu", "radius": "22px", "btn": "999px", "frame": "50% 50% 14px 14px / 34% 34% 14px 14px", "script": ""},
    "sunny": {"fonts": "Yellowtail&family=Nunito+Sans:wght@400;600;800", "display": '"Nunito Sans","Segoe UI",Arial,sans-serif', "body": '"Nunito Sans","Segoe UI",Arial,sans-serif',
              "weight": "800", "hero": "full", "services": "cards", "radius": "22px", "btn": "999px", "frame": "28px", "script": '"Yellowtail","Brush Script MT",cursive'},
    "trade": {"fonts": "Manrope:wght@400;600;800", "display": '"Manrope","Avenir Next","Segoe UI",system-ui,sans-serif', "body": '"Manrope","Avenir Next","Segoe UI",system-ui,sans-serif',
              "weight": "800", "hero": "split", "services": "cards", "radius": "12px", "btn": "10px", "frame": "18px", "script": ""},
    "editorial": {"fonts": "Fraunces:opsz,wght@9..144,400;9..144,600&family=Source+Sans+3:wght@400;600", "display": '"Fraunces","Iowan Old Style",Georgia,serif',
                  "body": '"Source Sans 3","Segoe UI",system-ui,sans-serif', "weight": "500", "hero": "full", "services": "menu", "radius": "6px", "btn": "4px", "frame": "6px", "script": ""},
}
STYLE_BY_TYPE = {"beauty_salon": "luxe", "hair_care": "editorial", "restaurant": "editorial", "cafe": "sunny", "bakery": "sunny",
                 "plumber": "trade", "car_repair": "trade", "dentist": "trade",
                 "nail_salon": "luxe", "hair_salon": "luxe", "spa": "luxe", "jewelry_store": "luxe", "barber_shop": "editorial", "bed_and_breakfast": "editorial",
                 "meal_takeaway": "sunny", "florist": "sunny", "child_care_agency": "sunny", "pet_store": "sunny", "gift_shop": "sunny"}

CSS = """
:root{--p:[[primary]];--a:[[accent]];--bg:[[bg]];--t:[[text]];
--surface:color-mix(in srgb,var(--bg) 45%,#fff);--soft:color-mix(in srgb,var(--t) 6%,var(--bg));
--line:color-mix(in srgb,var(--t) 14%,var(--bg));--muted:color-mix(in srgb,var(--t) 70%,var(--bg));
--on-dark:color-mix(in srgb,var(--bg) 82%,var(--t));
--display:[[display]];--body:[[body]];--script:[[script]];--r:[[radius]];--rb:[[btn]];--frame:[[frame]];--wrap:min(1120px,100% - 2.5rem)}
*{box-sizing:border-box;margin:0}
html{scroll-behavior:smooth;scroll-padding-top:5rem}
body{background:var(--bg);color:var(--t);font:400 1.0625rem/1.65 var(--body);-webkit-font-smoothing:antialiased}
img{max-width:100%;display:block}a{color:inherit}
:focus-visible{outline:2px solid var(--a);outline-offset:3px}
h1,h2,h3{font-family:var(--display);font-weight:[[weight]];line-height:1.1;letter-spacing:-.01em;text-wrap:balance}
.wrap{width:var(--wrap);margin-inline:auto}
.eyebrow{font-size:.8rem;letter-spacing:.18em;text-transform:uppercase;font-weight:600;color:var(--p)}
.script .eyebrow{font:400 1.7rem/1 var(--script);letter-spacing:0;text-transform:none}
.btn{display:inline-flex;align-items:center;gap:.55rem;padding:.85rem 1.5rem;border-radius:var(--rb);font:600 1rem var(--body);text-decoration:none;border:1.5px solid transparent;transition:transform .2s,box-shadow .2s,background .2s}
.btn svg{width:1.05em;height:1.05em;flex:none}
.btn-main{background:var(--a);color:var(--t);box-shadow:0 10px 24px -14px var(--t)}
.btn-main:hover{transform:translateY(-2px);box-shadow:0 16px 30px -14px var(--t)}
.btn-line{border-color:currentColor}.btn-line:hover{background:color-mix(in srgb,currentColor 12%,transparent)}

.top{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding-top:env(safe-area-inset-top,0px)}
.bar{display:flex;align-items:center;justify-content:space-between;gap:1rem;height:4.25rem}
.brand{font:[[weight]] 1.3rem var(--display);text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.script .brand{font:400 1.75rem var(--script)}
nav{display:flex;align-items:center;gap:1.75rem}
nav a.link{text-decoration:none;font-size:.95rem;color:var(--muted)}nav a.link:hover{color:var(--t)}
nav .btn{padding:.55rem 1.1rem;font-size:.92rem}
@media (max-width:820px){nav a.link{display:none}}
@media (max-width:600px){.nav-call{display:none}}
nav .btn{white-space:nowrap}

.hero{position:relative;overflow:hidden;color:#fff;background:var(--p)}
.hero::before{content:"";position:absolute;inset:0;background:radial-gradient(60rem 30rem at 85% -10%,color-mix(in srgb,var(--a) 55%,transparent),transparent 70%),linear-gradient(160deg,transparent 40%,color-mix(in srgb,var(--t) 55%,transparent))}
.hero-in{position:relative;display:grid;grid-template-columns:1.1fr .9fr;gap:3.5rem;align-items:center;padding-block:5rem 5.5rem}
.hero .eyebrow{color:color-mix(in srgb,var(--a) 70%,#fff)}
.hero h1{font-size:clamp(2.5rem,6vw,4.5rem);margin-top:1rem}
.lede{font-size:1.2rem;max-width:36ch;margin:1.25rem 0 2rem;color:color-mix(in srgb,#fff 88%,var(--p))}
.ctas{display:flex;flex-wrap:wrap;gap:.75rem}
.rating{margin-top:2.25rem;display:flex;align-items:center;gap:.7rem;font-size:.95rem}
.stars{color:var(--a);letter-spacing:.12em}
.hero-photo{justify-self:end;width:min(400px,100%);aspect-ratio:4/5;border-radius:var(--frame);overflow:hidden;border:6px solid color-mix(in srgb,var(--a) 60%,#fff);box-shadow:0 40px 70px -35px rgba(0,0,0,.6)}
.hero-photo img,.hero-bg img{width:100%;height:100%;object-fit:cover}
.hero.full{min-height:min(88vh,760px);display:flex;align-items:flex-end;background:var(--t)}
.hero.full::before{z-index:1;background:linear-gradient(180deg,color-mix(in srgb,var(--t) 25%,transparent),color-mix(in srgb,var(--t) 88%,transparent) 85%)}
.hero-bg{position:absolute;inset:0}
.hero.full .hero-in{z-index:2;grid-template-columns:1fr;width:var(--wrap);padding-block:9rem 4.5rem}
.hero.full .lede{color:#fff}
@media (max-width:860px){.hero-in{grid-template-columns:1fr;padding-block:3.25rem 3.75rem;gap:2.5rem}.hero-photo{justify-self:center;width:min(300px,82%)}}

section{padding-block:5.5rem}
.head{max-width:42rem;margin-bottom:3rem}
.head h2{font-size:clamp(2rem,4vw,2.9rem);margin-top:.6rem}
.head p{margin-top:.9rem;color:var(--muted)}

.menu{display:grid;grid-template-columns:repeat(2,1fr);gap:0 4rem}
.item{padding:1.6rem 0;border-top:1px solid var(--line)}
.item h3{font-size:1.45rem;display:flex;align-items:baseline;gap:.75rem}
.item h3::after{content:"";flex:1;border-bottom:1px dotted var(--p);transform:translateY(-.3rem)}
.item p{margin-top:.45rem;color:var(--muted);max-width:46ch}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1.25rem}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:1.75rem;transition:transform .25s,box-shadow .25s}
.card:hover{transform:translateY(-4px);box-shadow:0 24px 40px -30px var(--t)}
.card .n{font:600 .85rem var(--body);letter-spacing:.14em;color:var(--p)}
.card h3{font-size:1.3rem;margin:.9rem 0 .5rem}.card p{color:var(--muted)}
@media (max-width:760px){.menu{grid-template-columns:1fr}}

.about{background:var(--soft)}
.about-grid{display:grid;grid-template-columns:.9fr 1.1fr;gap:4rem;align-items:center}
.about-grid.solo{grid-template-columns:1fr;max-width:46rem}
.about img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:var(--r);box-shadow:0 30px 50px -35px var(--t)}
.about p.body{font-size:1.15rem;margin-top:1.1rem}
.facts{display:flex;flex-wrap:wrap;gap:2.5rem;margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--line)}
.facts b{display:block;font:[[weight]] 2.2rem/1 var(--display);color:var(--p)}.facts span{font-size:.9rem;color:var(--muted)}
@media (max-width:860px){.about-grid{grid-template-columns:1fr;gap:2.25rem}}

.mosaic{display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:210px;gap:.85rem}
.mosaic img{width:100%;height:100%;object-fit:cover;border-radius:var(--r)}
.mosaic img:first-child{grid-column:span 2;grid-row:span 2}
.mosaic.n4 img:last-child{grid-column:span 2}.mosaic.n3 img:first-child{grid-row:span 1}.mosaic.n2{grid-template-columns:repeat(2,1fr)}.mosaic.n2 img:first-child{grid-column:span 1;grid-row:span 1}
@media (max-width:760px){.mosaic{grid-template-columns:repeat(2,1fr);grid-auto-rows:150px}}

.reviews{background:var(--t);color:var(--on-dark)}
.reviews .eyebrow{color:var(--a)}
.rev-top{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:end;gap:1.5rem;margin-bottom:2.5rem}
.rev-top .head{margin:0}
.score{display:flex;align-items:baseline;gap:.75rem}.score b{font:[[weight]] 3.5rem/1 var(--display);color:#fff}
.rev-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1.25rem}
.rev{padding:1.75rem;border-radius:var(--r);background:color-mix(in srgb,#fff 7%,var(--t));border:1px solid color-mix(in srgb,#fff 14%,var(--t))}
.rev blockquote{margin:.8rem 0 1rem;font-size:1.03rem;color:#fff}
.rev footer{font-size:.9rem;opacity:.8}
.rev-more{margin-top:2rem}

.visit-grid{display:grid;grid-template-columns:1fr 1fr;gap:3.5rem;align-items:start}
.hours{width:100%;border-collapse:collapse;margin-top:.5rem}
.hours td{padding:.7rem 0;border-bottom:1px solid var(--line)}.hours td:last-child{text-align:right;color:var(--muted)}
.hours tr.today td{font-weight:600;color:var(--p)}
.where{display:flex;gap:.8rem;align-items:flex-start;margin-bottom:1.1rem}.where svg{width:1.25rem;height:1.25rem;flex:none;margin-top:.25rem;color:var(--p)}
.where a{text-decoration-color:var(--a);text-underline-offset:.2em}
.map{margin-top:1.75rem;border-radius:var(--r);overflow:hidden;aspect-ratio:4/3;border:1px solid var(--line)}
.map iframe{width:100%;height:100%;border:0}
.visit .ctas{margin-top:1.5rem}.visit .btn-line{color:var(--p)}
@media (max-width:860px){.visit-grid{grid-template-columns:1fr;gap:2.5rem}}

.foot{padding:2.25rem 0 calc(2.25rem + env(safe-area-inset-bottom,0px));border-top:1px solid var(--line);font-size:.82rem;color:var(--muted)}
.foot p+p{margin-top:.5rem}
.callbar{display:none}
@media (max-width:600px){section{padding-block:4rem}.foot{padding-bottom:6rem}
.callbar{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:30;padding:.6rem .75rem calc(.6rem + env(safe-area-inset-bottom,0px));background:color-mix(in srgb,var(--bg) 94%,transparent);backdrop-filter:blur(10px);border-top:1px solid var(--line)}
.callbar .btn{flex:1;justify-content:center}}
.js .rise{opacity:0;transform:translateY(18px);transition:opacity .7s ease,transform .7s ease}.js .rise.in{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){.js .rise{opacity:1;transform:none;transition:none}html{scroll-behavior:auto}.btn,.card{transition:none}}
"""

JS = """document.documentElement.classList.add('js');
const d=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][new Date().getDay()];
document.querySelectorAll('.hours tr').forEach(r=>{if(r.dataset.day===d)r.classList.add('today')});
const io='IntersectionObserver' in window?new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{threshold:.12}):null;
document.querySelectorAll('.rise').forEach(el=>io?io.observe(el):el.classList.add('in'));
"""

ICON = {
    "phone": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/></svg>',
    "pin": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/></svg>',
}


def _e(s) -> str:
    return html.escape(str(s or ""))


def city_of(lead: dict) -> str:
    parts = [p.strip() for p in (lead.get("address") or "").split(",")]
    return parts[-3] if len(parts) >= 3 else ""


def _reviews(info: dict) -> list[dict]:
    """Up to three good reviews; older leads stored plain strings."""
    out = []
    for r in info.get("reviews", []):
        r = {"text": r} if isinstance(r, str) else r
        text = re.sub(r"\s+", " ", r.get("text") or "").strip()
        if len(text) < 12 or (r.get("rating") or 5) < 4:
            continue
        if len(text) > 230:
            text = text[:230].rsplit(" ", 1)[0] + "…"
        out.append({"text": text, "author": r.get("author") or "Google review", "rating": int(r.get("rating") or 5)})
    return out[:3]


def render(lead: dict, copy: dict, theme: dict, images: list[dict]) -> str:
    st = STYLES[STYLE_BY_TYPE.get(lead.get("type"), "trade")]
    images = [i for i in images or [] if isinstance(i, dict)]
    info, name, city = lead.get("info") or {}, lead["name"], city_of(lead)
    label = lead.get("type_label") or lead.get("type", "").replace("_", " ").title()
    src = lambda i: _e(i.get("file") or i["url"])
    tel = re.sub(r"[^0-9+]", "", lead.get("phone") or "")
    maps = info.get("maps_url") or "https://www.google.com/maps/search/?api=1&query=" + quote_plus(f"{name} {lead.get('address', '')}") + (f"&query_place_id={quote_plus(lead['id'])}" if lead.get("id") else "")
    call = f'<a class="btn btn-main" href="tel:{tel}">{ICON["phone"]}Call {_e(lead.get("phone"))}</a>' if tel else ""
    directions = f'<a class="btn btn-line" href="{_e(maps)}" rel="noopener">{ICON["pin"]}Get directions</a>'
    rating, count = lead.get("rating"), lead.get("reviews")
    stars = lambda n: "★" * n + "☆" * (5 - n)
    rating_line = (f'<div class="rating"><span class="stars" aria-hidden="true">{stars(round(rating))}</span><span>{rating:.1f} on Google'
                   + (f" · {count} reviews" if count else "") + "</span></div>") if rating else ""

    full = st["hero"] == "full" and images
    hero_img = (f'<div class="hero-bg"><img src="{src(images[0])}" alt=""></div>' if full
                else f'<div class="hero-photo"><img src="{src(images[0])}" alt="{_e(label)}"></div>' if images else "")
    hero = f"""<section class="hero{' full' if full else ''}" id="top-hero" style="padding:0">{hero_img if full else ''}<div class="wrap hero-in"><div>
<p class="eyebrow">{_e(' · '.join(x for x in (label, city) if x))}</p><h1>{_e(copy.get('headline') or name)}</h1>
<p class="lede">{_e(copy.get('tagline'))}</p><div class="ctas">{call}{directions}</div>{rating_line}</div>{'' if full else hero_img}</div></section>"""

    svc = copy.get("services", [])[:6]
    if st["services"] == "menu":
        services = '<div class="menu rise">' + "".join(f'<div class="item"><h3>{_e(s.get("name"))}</h3><p>{_e(s.get("text"))}</p></div>' for s in svc) + "</div>"
    else:
        services = '<div class="cards rise">' + "".join(f'<div class="card"><span class="n">{n:02d}</span><h3>{_e(s.get("name"))}</h3><p>{_e(s.get("text"))}</p></div>' for n, s in enumerate(svc, 1)) + "</div>"

    facts = "".join(f"<div><b>{_e(v)}</b><span>{_e(k)}</span></div>" for k, v in (("Google rating", f"{rating:.1f}" if rating else ""), ("Reviews", count)) if v)
    about_img = f'<img class="rise" src="{src(images[1])}" alt="{_e(images[1].get("alt"))}" loading="lazy">' if len(images) > 1 else ""
    about = f"""<section class="about" id="about"><div class="wrap about-grid{'' if about_img else ' solo'}">{about_img}<div class="rise">
<p class="eyebrow">About</p><h2 style="font-size:clamp(2rem,4vw,2.9rem);margin-top:.6rem">{_e(copy.get('about_title') or name)}</h2>
<p class="body">{_e(copy.get('about'))}</p>{f'<div class="facts">{facts}</div>' if facts else ''}</div></div></section>"""

    shots = images[2:6]
    gallery = (f'<section id="gallery"><div class="wrap"><div class="head rise"><p class="eyebrow">Gallery</p><h2>{_e(copy.get("gallery_title") or WORDS[category_of(lead.get("type"))].get("gallery_title") or "Gallery")}</h2></div>'
               f'<div class="mosaic n{len(shots)} rise">' + "".join(f'<img src="{src(i)}" alt="{_e(i.get("alt"))}" loading="lazy">' for i in shots) + "</div></div></section>") if len(shots) >= 2 else ""

    revs = _reviews(info)
    reviews = (f"""<section class="reviews" id="reviews"><div class="wrap"><div class="rev-top rise"><div class="head"><p class="eyebrow">Reviews</p><h2>What customers say</h2></div>
{f'<div class="score"><b>{rating:.1f}</b><span class="stars" aria-hidden="true">{stars(round(rating))}</span></div>' if rating else ''}</div><div class="rev-list rise">"""
               + "".join(f'<article class="rev"><span class="stars" aria-hidden="true">{stars(r["rating"])}</span><blockquote>“{_e(r["text"])}”</blockquote><footer>{_e(r["author"])} · Google</footer></article>' for r in revs)
               + f'</div><p class="rev-more rise"><a class="btn btn-line" href="{_e(maps)}" rel="noopener">Read more on Google</a></p></div></section>') if revs else ""

    rows = ""
    for h in info.get("hours", []):
        day, _, when = str(h).partition(": ")
        rows += f'<tr data-day="{_e(day)}"><td>{_e(day)}</td><td>{_e(when)}</td></tr>'
    embed = "https://www.google.com/maps?output=embed&q=" + quote_plus(f"{name} {lead.get('address', '')}")
    visit = f"""<section class="visit" id="visit"><div class="wrap visit-grid"><div class="rise"><div class="head" style="margin-bottom:1.75rem"><p class="eyebrow">Visit</p><h2>{_e(copy.get('visit_title') or 'Come and see us')}</h2></div>
<p class="where">{ICON['pin']}<a href="{_e(maps)}" rel="noopener">{_e(lead.get('address'))}</a></p>
{f'<p class="where">{ICON["phone"]}<a href="tel:{tel}">{_e(lead.get("phone"))}</a></p>' if tel else ''}
{f'<table class="hours">{rows}</table>' if rows else ''}<div class="ctas">{call}{directions}</div></div>
<div class="map rise"><iframe src="{_e(embed)}" loading="lazy" title="Map" referrerpolicy="no-referrer-when-downgrade"></iframe></div></div></section>"""

    credits = " · ".join(f'<a href="{_e(i["source"])}" rel="noopener">{_e(i["credit"])}</a>' for i in images)
    ld = json.dumps({"@context": "https://schema.org", "@type": "LocalBusiness", "name": name, "telephone": lead.get("phone") or None,
                     "address": lead.get("address") or None}).replace("</", "<\\/")
    css = CSS
    for k, v in {**theme, **st}.items():
        css = css.replace(f"[[{k}]]", str(v) or "inherit")
    links = "".join(f'<a class="link" href="#{i}">{t}</a>' for i, t, on in (("services", "Services", svc), ("about", "About", True), ("gallery", "Gallery", gallery),
                                                                              ("reviews", "Reviews", reviews), ("visit", "Visit", True)) if on)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{_e(name)}{f' | {_e(label)} in {_e(city)}' if city else ''}</title><meta name="description" content="{_e(copy.get('tagline'))}"><meta name="robots" content="noindex">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family={st['fonts']}&display=swap" rel="stylesheet">
<script type="application/ld+json">{ld}</script><style>{css}</style></head><body class="{'script' if st['script'] else ''}">
<header class="top"><div class="wrap bar"><a class="brand" href="#top-hero">{_e(name)}</a><nav>{links}{call.replace('btn btn-main', 'btn btn-main nav-call') if tel else ''}</nav></div></header>
<main>{hero}
{f'<section id="services"><div class="wrap"><div class="head rise"><p class="eyebrow">Services</p><h2>{_e(copy.get("services_title") or "What we do")}</h2></div>{services}</div></section>' if svc else ''}
{about}
{gallery}
{reviews}
{visit}</main>
<footer class="foot"><div class="wrap"><p>Demo site prepared for {_e(name)}. Not yet the business's official website.</p><p>Photos: {credits or 'none'}.</p></div></footer>
{f'<div class="callbar">{call}</div>' if tel else ''}<script>{JS}</script></body></html>"""
