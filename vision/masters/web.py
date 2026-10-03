"""Web Designer (live): Business Finder -> Information Collector + Competitor Analyst -> Images Downloader +
Color Theme Decider -> Website Builder -> Cloudflare Deployer -> Proposal Drafter (reporter) -> YOU.

- Leads: Google Places API (New), businesses near home with no website (GOOGLE_MAPS_API_KEY).
- Design brief (style, mood, image keywords) per lead drives the palette, the photos and the template look.
- Images: Pexels / Pixabay (PEXELS_API_KEY, PIXABAY_API_KEY; free stock) then Openverse (openly licensed), saved as
  local .webp next to the page; every image's credit is kept on the site.
- Deploy: Cloudflare Workers (CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID), one demo per lead.
- Nothing is sent to a business until you approve the pitch.
"""

from __future__ import annotations

import base64
import colorsys
import hashlib
import io
import json
import re
import time
import zlib
from pathlib import Path
from typing import Any

import httpx
from urllib.parse import urlparse

from ..agents import AgentResult, SubAgent, request_approval
from ..config import ROOT, secret
from ..services import weather
from ..services.llm import LLMUnavailable
from .site_copy import brief_prompt, write_copy
from .site_images import pick_images
from .site_qa import check_site, fixable_by_rebuild, summarize
from .site_template import STYLE_BY_TYPE, STYLES, city_of, render_site
from .site_style import choose, palette_moods
from .sitekit import styles_for

PLACES = "https://places.googleapis.com/v1/places:searchNearby"
FIELDS = "places.id,places.displayName,places.formattedAddress,places.websiteUri,places.nationalPhoneNumber,places.primaryType,places.primaryTypeDisplayName,places.rating,places.userRatingCount,places.location"
SOCIAL = re.compile(r"facebook\.com|instagram\.com|linktr\.ee|yelp\.|business\.site", re.I)
PALETTES = {
    "plumber": ("#0B4F8A", "#F2A541", "#F7F9FC", "#14212B"), "beauty_salon": ("#7A2E5C", "#E8B4C8", "#FFF8FB", "#2B1622"),
    "hair_care": ("#3D2C4E", "#D9A441", "#FBF8F3", "#211A29"), "restaurant": ("#8C2F1B", "#E9B44C", "#FFF9F2", "#2A1610"),
    "cafe": ("#5A3E2B", "#C9A27E", "#FBF6EF", "#2A1E15"), "car_repair": ("#1F2A36", "#E4572E", "#F5F6F8", "#11161C"),
    "dentist": ("#0F6F78", "#9ED9D6", "#F4FBFB", "#12302F"), "bakery": ("#A0522D", "#F3D29B", "#FFFAF2", "#2B1A10"),
}


# business type -> ColorHunt themes (see skills/color-palettes.md); config: options.palette_themes overrides per type
THEMES = {
    "plumber": ["cold", "sea", "sky", "light"], "beauty_salon": ["pastel", "skin", "wedding", "cream"],
    "hair_care": ["vintage", "dark", "gold", "retro"], "restaurant": ["warm", "food", "fall", "earth"],
    "cafe": ["coffee", "cream", "earth", "vintage"], "car_repair": ["dark", "night", "retro", "neon"],
    "dentist": ["light", "cold", "sky", "sea"], "bakery": ["cream", "food", "warm", "pastel"],
    "nail_salon": ["pastel", "wedding", "cream", "spring"], "hair_salon": ["pastel", "skin", "cream", "vintage"], "barber_shop": ["vintage", "dark", "gold", "retro"],
    "spa": ["cream", "nature", "sea", "light"], "florist": ["spring", "nature", "pastel", "happy"], "gym": ["neon", "dark", "night", "retro"],
    "child_care_agency": ["kids", "happy", "pastel"], "bed_and_breakfast": ["sea", "nature", "vintage", "earth"], "meal_takeaway": ["warm", "food", "fall", "earth"],
    "veterinary_care": ["nature", "happy", "light"], "pet_store": ["happy", "nature", "kids"], "jewelry_store": ["gold", "dark", "wedding"],
}
_palettes: list[dict] | None = None


def _lum(c: tuple) -> float:
    r, g, b = [(v / 255 / 12.92) if v / 255 <= 0.03928 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple, b: tuple) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _mix(c: tuple, to: tuple, k: float) -> tuple:
    return tuple(round(x + (y - x) * k) for x, y in zip(c, to))


def _until(c: tuple, to: tuple, ok) -> tuple:
    for _ in range(20):
        if ok(c):
            break
        c = _mix(c, to, 0.15)
    return c


def _sat(c: tuple) -> float:
    return colorsys.rgb_to_hls(*[v / 255 for v in c])[2]


def _shade(c: tuple, light: float, min_sat: float = 0.0) -> tuple:
    """The same hue at another lightness, so darkened colours stay colourful instead of turning grey."""
    h, _, s = colorsys.rgb_to_hls(*[v / 255 for v in c])
    return tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, light, max(s, min_sat) if s > 0.08 else s))


def _darken(c: tuple, ok, min_sat: float = 0.0) -> tuple:
    light = colorsys.rgb_to_hls(*[v / 255 for v in c])[1]
    while not ok(c) and light > 0.04:
        light -= 0.03
        c = _shade(c, light, min_sat)
    return c


def theme_from(colors: list) -> dict:
    """Four colours -> page roles: lightest = background, most colourful = primary, next = accent, text = a deep
    shade of the primary. Each is adjusted (hue kept) until text, headings and buttons are readable."""
    W = (255, 255, 255)
    cs = sorted((tuple(c) for c in colors), key=_lum)
    bg = _until(cs[3], W, lambda c: _lum(c) >= 0.8)
    primary, accent = sorted(cs[:3], key=lambda c: _sat(c) * (1 - abs(2 * _lum(c) - 0.5)), reverse=True)[:2]
    primary = _darken(primary, lambda c: _contrast(c, bg) >= 5.5, 0.4)
    text = _darken(_shade(primary, 0.16), lambda c: _contrast(c, bg) >= 10)
    if _contrast(accent, text) < 4.5:
        accent = _until(_shade(accent, 0.6, 0.5), W, lambda c: _contrast(c, text) >= 4.5)
    return {k: "#%02X%02X%02X" % v for k, v in (("primary", primary), ("accent", accent), ("bg", bg), ("text", text))}


def pick_theme(lead: dict, themes: list | None = None) -> dict:
    """A ColorHunt palette for this lead: top 40 of its themes by likes, the same lead always gets the same one."""
    global _palettes
    if _palettes is None:
        try:
            _palettes = json.loads((Path(__file__).parent / "palettes.json").read_text())
        except (OSError, ValueError):
            _palettes = []
    want = set(themes or THEMES.get(lead["type"], ["light", "cold"]))
    pool = [p for p in _palettes if want & set(p["tags"]) and max(_sat(c) for c in p["rgb"]) >= 0.3]
    pool = sorted(pool, key=lambda p: -len(want & set(p["tags"])))[:40]   # best theme fit first, then likes (file order)
    if not pool:
        return dict(zip(("primary", "accent", "bg", "text"), PALETTES.get(lead["type"], ("#1E3A5F", "#F2B134", "#F8F9FB", "#16202B"))))
    p = pool[zlib.crc32(lead["id"].encode()) % len(pool)]
    return {**theme_from(p["rgb"]), "palette": p["id"]}

# stock-photo searches per business type when the model gives no keywords
KEYWORDS = {
    "plumber": ["plumber working", "modern bathroom", "kitchen faucet", "copper pipes"], "beauty_salon": ["beauty salon interior", "manicure", "facial treatment", "makeup brushes"],
    "hair_care": ["barber shop", "hair stylist", "haircut", "salon chairs"], "restaurant": ["restaurant interior", "plated food", "chef cooking", "dinner table"],
    "cafe": ["coffee shop interior", "latte art", "pastry", "barista"], "car_repair": ["auto mechanic", "car workshop", "engine repair", "tire service"],
    "dentist": ["dental clinic", "dentist", "smile", "dental chair"], "bakery": ["bakery", "fresh bread", "pastries", "baker"],
}
MOODS = {"pastel", "vintage", "retro", "neon", "gold", "light", "dark", "warm", "cold", "summer", "fall", "winter", "spring", "happy", "nature", "earth",
         "night", "space", "sunset", "sky", "sea", "kids", "skin", "food", "cream", "coffee", "wedding"}


def default_brief(lead: dict) -> dict:
    label = (lead.get("type_label") or lead["type"].replace("_", " ")).lower()
    return {"style": STYLE_BY_TYPE.get(lead["type"], "trade"), "mood": [], "keywords": KEYWORDS.get(lead["type"], [label, f"{label} interior", f"{label} at work", "small business owner"])}


def clean_brief(raw: Any, lead: dict) -> dict:
    """The model's brief, kept only where it is usable."""
    b, raw = default_brief(lead), raw if isinstance(raw, dict) else {}
    if raw.get("style") in STYLES:
        b["style"] = raw["style"]
    b["mood"] = [m for m in raw.get("mood") or [] if m in MOODS][:3]
    kw = [str(k)[:40] for k in raw.get("keywords") or [] if isinstance(k, str) and k.strip()][:5]
    return {**b, "keywords": kw or b["keywords"]}


def unique_headings(copy: dict) -> dict:
    """No two headings on a page may read the same: a repeated section title is dropped (the layout's own wording is
    used instead) and a repeated step, service or question is removed."""
    seen, out = set(), dict(copy)
    key = lambda t: re.sub(r"\W+", " ", str(t or "")).strip().lower()
    for k in ("headline", "about_title", "services_title", "gallery_title", "reviews_title", "visit_title", "cta_title"):
        if key(out.get(k)) in seen:
            out.pop(k, None)
        elif key(out.get(k)):
            seen.add(key(out[k]))
    for k, field in (("services", "name"), ("steps", "title"), ("faq", "q")):
        kept = []
        for item in out.get(k) or []:
            if isinstance(item, dict) and key(item.get(field)) and key(item[field]) not in seen:
                seen.add(key(item[field]))
                kept.append(item)
        if k in out:
            out[k] = kept
    return out


def choose_style(lead: dict, wanted: str | None, used: set) -> str:
    """The style that best matches what is known about this business (reviews, summary, name), among those that suit
    its kind and aren't already used by another demo in play. The model's pick counts as one signal. See site_style.py."""
    return choose(lead, wanted, used)["style"]


# other kinds of local business the finder moves on to (Places API type names)
MORE_TYPES = ["plumber", "beauty_salon", "hair_care", "restaurant", "cafe", "car_repair", "bakery", "electrician", "roofing_contractor", "painter", "locksmith",
              "moving_company", "barber_shop", "hair_salon", "nail_salon", "spa", "florist", "laundry", "car_wash", "veterinary_care", "pet_store", "dentist",
              "physiotherapist", "gym", "clothing_store", "jewelry_store", "furniture_store", "hardware_store", "bicycle_store", "book_store", "gift_shop",
              "child_care_agency", "tailor", "real_estate_agency", "insurance_agency", "accounting", "lawyer", "travel_agency", "bed_and_breakfast",
              "meal_takeaway", "funeral_home", "storage"]
def places_budget(store, opts: dict, kind: str, peek: bool = False) -> int:
    """Count one Google Places call of this kind ("search" | "details") against this month's budget.
    Returns 0 when the budget is spent (don't call); with peek, just the budget."""
    cap = int(opts.get("places_monthly_budget", 800))
    if peek:
        return cap
    key = f"places-{kind}-{time.strftime('%Y-%m')}"
    n = int((store.kv_get("web_state", key) or {}).get("n", 0))
    if n >= cap:
        return 0
    store.kv_put("web_state", key, {"n": n + 1})
    return n + 1


ACTIVE = ("new", "researched", "built", "deployed", "pitch_ready")   # leads that hold a place in the stack


def todo(ctx: dict) -> list[dict]:
    """Leads that still need a site built."""
    return [l for l in ctx.get("leads", []) if not l.get("site")]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


class BusinessFinder(SubAgent):
    name, tier, note = "Business Finder", "API", "no-website businesses nearby"

    async def run(self, ctx):
        key, opts, store = secret("GOOGLE_MAPS_API_KEY"), ctx["options"], ctx["store"]
        if not key:
            return AgentResult("idle", "NOT SET UP", "Web Designer: add GOOGLE_MAPS_API_KEY to .env")
        home, bus = ctx["cfg"].vision.home_city, ctx.get("bus")
        # keep `stack` demos in play (being built, live, or waiting for a decision); a decided pitch frees a slot.
        # At most builds_per_day new leads are taken in a day, however fast pitches are decided.
        active = [l for l in store.kv_list("leads", limit=1000) if l.get("status") in ACTIVE]
        today = "taken-" + time.strftime("%Y-%m-%d")
        taken = int((store.kv_get("web_state", today) or {}).get("n", 0))
        need = max(0, min(int(opts.get("stack", 5)) - len(active), int(opts.get("builds_per_day", 5)) - taken))
        # business_types are tried first; then any other kind of local business, unless any_type is false
        types = list(opts.get("business_types") or [])
        types += [t for t in MORE_TYPES if t not in types] if opts.get("any_type", True) else []
        # Places calls are billed past a free monthly allowance, so: every no-website business a search returns is kept
        # in a pool (`candidates`) and the stack refills from the pool first; a (type, radius) search isn't repeated
        # for research_days; and searching stops at places_monthly_budget calls a month.
        pool = lambda: store.kv_list("candidates", limit=5000)
        radius, top, fresh_for = float(opts.get("radius_km", 10)), float(opts.get("max_radius_km", 50)), float(opts.get("research_days", 30)) * 86400
        calls, capped = 0, False
        async with httpx.AsyncClient(timeout=25) as c:
            g = None
            while len(pool()) < need and not capped:
                for t in types:
                    seen = store.kv_get("web_searched", f"{t}@{radius:g}")
                    if seen and time.time() - seen["at"] < fresh_for:
                        continue
                    if not places_budget(store, opts, "search"):
                        capped = True
                        break
                    g = g or await weather.geocode(c, home)
                    r = await c.post(PLACES, headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS}, json={
                        "includedTypes": [t], "maxResultCount": 20, "locationRestriction": {"circle": {
                            "center": {"latitude": g["latitude"], "longitude": g["longitude"]}, "radius": radius * 1000}}})
                    calls += 1
                    store.kv_put("web_searched", f"{t}@{radius:g}", {"at": time.time()})
                    if r.status_code == 400:      # a type this API doesn't know: skip it
                        continue
                    r.raise_for_status()
                    for p in r.json().get("places", []):
                        site = p.get("websiteUri", "")
                        item = {"id": p["id"], "name": p["displayName"]["text"], "type": t, "type_label": (p.get("primaryTypeDisplayName") or {}).get("text", t),
                                "address": p.get("formattedAddress", ""), "phone": p.get("nationalPhoneNumber", ""), "rating": p.get("rating"),
                                "reviews": p.get("userRatingCount"), "website": site}
                        if site and not SOCIAL.search(site):
                            store.kv_put("rivals", p["id"], item)
                        elif not store.kv_has("leads", p["id"]) and not store.kv_has("candidates", p["id"]):
                            store.kv_put("candidates", p["id"], item)
                    if len(pool()) >= need:
                        break
                if len(pool()) >= need or radius >= top:
                    break
                radius = min(radius * 2, top)
        if bus:
            if capped:
                bus.notice("web:places-budget", f"Web Designer paused its search: this month's Google Places budget ({places_budget(store, opts, 'search', peek=True)} calls) is used up. It resumes next month.")
            else:
                bus.clear_notice("web:places-budget")
        waiting = pool()
        new = [{k: v for k, v in p.items() if k not in ("_key", "_ts")} for p in waiting[::-1][:need]]   # oldest finds first
        for p in new:
            store.kv_delete("candidates", p["id"])
        if new:
            store.kv_put("web_state", today, {"n": taken + len(new)})
        found, competitors = waiting, store.kv_list("rivals", limit=2000)
        for p in new:
            store.kv_put("leads", p["id"], {**p, "status": "new"})
        # unfinished leads go down the chain again, so one built before Cloudflare was set up still gets deployed
        ctx["leads"] = [l for l in store.kv_list("leads", limit=1000) if l.get("status") in ("new", "researched", "built")]
        ctx["competitors"] = competitors
        return AgentResult("done", f"{len(new)} NEW", f"{len(new)} new leads · {len(active) + len(new)} in the stack · {len(found) - len(new)} more in the pool · {calls} Places searches",
                           {"leads": [{"name": l["name"], "type": l["type_label"]} for l in ctx["leads"]]})


class InformationCollector(SubAgent):
    name, tier, note, blocking = "Information Collector", "API", "hours · reviews", False

    async def run(self, ctx):
        key, store = secret("GOOGLE_MAPS_API_KEY"), ctx["store"]
        async with httpx.AsyncClient(timeout=20) as c:
            for l in todo(ctx):
                if l.get("info") or not places_budget(store, ctx["options"], "details"):
                    continue
                r = await c.get(f"https://places.googleapis.com/v1/places/{l['id']}", headers={"X-Goog-Api-Key": key,
                                "X-Goog-FieldMask": "regularOpeningHours.weekdayDescriptions,editorialSummary,googleMapsUri,reviews.text.text,reviews.rating,reviews.authorAttribution.displayName"})
                d = r.json() if r.status_code == 200 else {}
                l["info"] = {"hours": (d.get("regularOpeningHours") or {}).get("weekdayDescriptions", []),
                             "summary": (d.get("editorialSummary") or {}).get("text", ""),
                             "maps_url": d.get("googleMapsUri", ""),
                             "reviews": [{"text": x.get("text", {}).get("text", "")[:400], "rating": x.get("rating"),
                                          "author": (x.get("authorAttribution") or {}).get("displayName", "")} for x in d.get("reviews", [])][:5]}
                store.kv_put("leads", l["id"], {k: v for k, v in l.items() if k not in ("_key", "_ts")})
        return AgentResult("done", "COLLECTED", f"Details for {len(todo(ctx))} leads")


class CompetitorAnalyst(SubAgent):
    name, tier, note, blocking = "Competitor Analyst", "DEEP", "rivals' sites · design brief", False

    async def run(self, ctx):
        llm, notes, briefs = ctx.get("llm"), {}, {}
        mine = {l["id"] for l in todo(ctx)}
        used = {l["style"] for l in ctx["store"].kv_list("leads", limit=1000) if l.get("status") in ACTIVE and l.get("style") and l.get("id") not in mine}
        for l in todo(ctx):
            rivals = [c for c in ctx.get("competitors", []) if c["type"] == l["type"] and c["website"]][:3]
            texts = []
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                for r in rivals:
                    try:
                        page = (await c.get(r["website"])).text
                        texts.append(f"{r['name']}: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", "", page, flags=re.S)))[:1500])
                    except Exception:
                        pass
            if llm and texts:
                try:
                    notes[l["id"]] = await llm.complete("From these competitor websites, list 5 short things a great site for this kind of business should have:\n" + "\n".join(texts), tier="cloud", max_tokens=300)
                except LLMUnavailable:
                    pass
            raw, fits = None, styles_for(l["type"])
            if llm:
                try:
                    raw = await llm.json(brief_prompt(l, fits, {r: f"{STYLES[r]['label']} ({STYLES[r].get('mode', 'light')})" for r in fits}), tier="cloud", max_tokens=250)
                except LLMUnavailable:
                    pass
            brief = clean_brief(raw, l)
            picked = choose(l, (raw or {}).get("style") if isinstance(raw, dict) else None, used)   # reasoned from the business itself; distinct per demo
            brief.update(style=picked["style"], why=picked["why"], ranked=picked["ranked"])
            used.add(brief["style"])
            briefs[l["id"]] = brief
        ctx["competitor_notes"], ctx["briefs"] = notes, briefs
        return AgentResult("done", f"{len(notes)} ANALYSED", f"Competitor notes for {len(notes)} leads · {len(briefs)} design briefs")


async def save_image(c: httpx.AsyncClient, url: str, dest: Path) -> bool:
    """Download a photo and store it as a .webp at most 1600 px wide. False (keep the remote link) if that fails."""
    try:
        from PIL import Image
        r = await c.get(url, follow_redirects=True)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((1600, 1600))
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "WEBP", quality=80, method=4)
        return True
    except Exception:
        return False


class ImagesDownloader(SubAgent):
    name, tier, note, blocking = "Images Downloader", "API", "Pexels · Pixabay · Openverse, credited", False

    async def run(self, ctx):
        imgs, want, thin = {}, int(ctx["options"].get("images_per_site", 6)), []
        async with httpx.AsyncClient(timeout=30) as c:
            for l in todo(ctx):
                # only photos whose description matches the trade; fewer photos rather than unrelated ones
                picked = await pick_images(c, l, ctx.get("briefs", {}).get(l["id"]) or default_brief(l), want)
                if len(picked) < 3:
                    thin.append(l["name"])
                for n, i in enumerate(picked, 1):
                    if await save_image(c, i["url"], ROOT / "data" / "sites" / slug(l["name"]) / "img" / f"{n}.webp"):
                        i["file"] = f"img/{n}.webp"
                imgs[l["id"]] = picked
        ctx["images"] = imgs
        note = "Relevant stock photos picked and saved, credits recorded" + (f" · few good photos for: {', '.join(thin)}" if thin else "")
        if thin and not (secret("PEXELS_API_KEY") or secret("PIXABAY_API_KEY")):
            note += " (add PEXELS_API_KEY or PIXABAY_API_KEY to .env for more choice)"
        return AgentResult("done", f"{sum(len(v) for v in imgs.values())} IMAGES", note)


class ColorThemeDecider(SubAgent):
    name, tier, note, blocking = "Color Theme Decider", "QUICK", "ColorHunt palette by business type", False

    async def run(self, ctx):
        over = ctx["options"].get("palette_themes") or {}
        brief = lambda l: ctx.get("briefs", {}).get(l["id"]) or {}
        # the colours follow the look: the chosen style's palette moods first, then the model's
        themes = {l["id"]: pick_theme(l, over.get(l["type"]) or palette_moods(brief(l).get("style"), brief(l).get("mood"))) for l in todo(ctx)}
        ctx["themes"] = themes
        return AgentResult("done", "PICKED", f"{len(themes)} palettes")


class WebsiteBuilder(SubAgent):
    name, tier, note = "Website Builder", "CLOUD", "copy + styled template"

    async def run(self, ctx):
        llm, store, built, failed = ctx.get("llm"), ctx["store"], 0, []
        for l in ctx.get("leads", []):
            if l.get("site") or l.get("status") == "qa_failed":
                continue
            copy = unique_headings(await write_copy(llm, l, ctx.get("competitor_notes", {}).get(l["id"], "")))
            theme = ctx.get("themes", {}).get(l["id"]) or dict(zip(("primary", "accent", "bg", "text"), PALETTES["plumber"]))
            images = ctx.get("images", {}).get(l["id"], [])
            brief = ctx.get("briefs", {}).get(l["id"]) or default_brief(l)
            first, order = brief["style"], brief.get("ranked") or styles_for(l["type"])
            d = ROOT / "data" / "sites" / slug(l["name"])
            d.mkdir(parents=True, exist_ok=True)
            # quality gate: a page that fails for a layout reason is rebuilt in the next style that suits the business
            for style in [first] + [r for r in order if r != first][:3]:
                page = render_site(l, copy, theme, images, style)
                qa = check_site(page, site_dir=d, lead=l, copy=copy)   # colours are judged from the page's own roles, not the raw palette
                if qa["ok"] or not fixable_by_rebuild(qa):
                    break
            why = brief.get("why") or f"{first}: the usual fit for this kind of business"
            l.update(style=style, style_why=why if style == first else f"{why}. Rebuilt as {style} after the layout check", qa={"ok": qa["ok"], "score": qa["score"], "issues": [f"{x['severity']}: {x['message']}" for x in qa["issues"]][:8]})
            if qa["ok"]:
                (d / "index.html").write_text(page)
                l.update(site=str(d / "index.html"), status="built")
                built += 1
            else:   # never deployed or pitched; kept as a draft so the problem can be looked at, and its place in the stack is freed
                (d / "draft.html").write_text(page)
                l.update(status="qa_failed", draft=str(d / "draft.html"))
                failed.append(l["name"])
                if ctx.get("bus"):
                    ctx["bus"].say(f"Web Designer · {l['name']} held back: {summarize(qa)}")
            store.kv_put("leads", l["id"], {k: v for k, v in l.items() if k not in ("_key", "_ts")})
        if failed:
            return AgentResult("done", f"{built} BUILT", f"Built {built} demo sites · {len(failed)} held back by the quality check: {', '.join(failed)}")
        return AgentResult("done", f"{built} BUILT", f"Built {built} demo sites")


async def remove_demo(url: str) -> bool:
    """Take a rejected demo offline: delete its Worker. True when it is gone (or was never there)."""
    tok, acct = secret("CLOUDFLARE_API_TOKEN"), secret("CLOUDFLARE_ACCOUNT_ID")
    name = (urlparse(url).hostname or "").split(".")[0]
    if not (tok and acct and name.startswith("demo-")):
        return False
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.delete(f"https://api.cloudflare.com/client/v4/accounts/{acct}/workers/scripts/{name}",
                           headers={"Authorization": f"Bearer {tok}"}, params={"force": "true"})
    return r.status_code in (200, 404)


async def upload_assets(c: httpx.AsyncClient, base: str, h: dict, name: str, folder: Path) -> str | None:
    """Upload the site's images as Worker static assets; returns the token the script upload needs (None: no images)."""
    files = {"/" + f.relative_to(folder).as_posix(): f.read_bytes() for f in sorted((folder / "img").glob("*.webp"))} if (folder / "img").is_dir() else {}
    if not files:
        return None
    hashes = {p: hashlib.sha256(b + p.encode()).hexdigest()[:32] for p, b in files.items()}
    r = await c.post(f"{base}/scripts/{name}/assets-upload-session", headers=h, json={"manifest": {p: {"hash": hashes[p], "size": len(b)} for p, b in files.items()}})
    r.raise_for_status()
    res = r.json().get("result") or {}
    token, by_hash = res.get("jwt"), {hashes[p]: b for p, b in files.items()}
    for bucket in res.get("buckets") or []:
        r = await c.post(f"{base}/assets/upload", params={"base64": "true"}, headers={"Authorization": f"Bearer {res['jwt']}"},
                         files={x: (x, base64.b64encode(by_hash[x]).decode(), "image/webp") for x in bucket if x in by_hash})
        r.raise_for_status()
        token = (r.json().get("result") or {}).get("jwt") or token
    return token


class CloudflareDeployer(SubAgent):
    name, tier, note = "Cloudflare Deployer", "API", "Workers demo URL"

    async def run(self, ctx):
        tok, acct, store = secret("CLOUDFLARE_API_TOKEN"), secret("CLOUDFLARE_ACCOUNT_ID"), ctx["store"]
        for l in [l for l in store.kv_list("leads", limit=1000) if l.get("status") == "parked" and l.get("url")]:
            if await remove_demo(l["url"]):   # rejected earlier, or the removal failed at the time
                store.kv_put("leads", l["_key"], {k: v for k, v in l.items() if k not in ("_key", "_ts", "url")})
        todo = [l for l in ctx.get("leads", []) if l.get("site") and not l.get("url")]
        if not todo:
            return AgentResult("done", "UP TO DATE", "Nothing new to deploy")
        if not (tok and acct):
            return AgentResult("idle", "NOT SET UP", "Add CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID to .env")
        base, h = f"https://api.cloudflare.com/client/v4/accounts/{acct}/workers", {"Authorization": f"Bearer {tok}"}
        async with httpx.AsyncClient(timeout=40) as c:
            sub = (await c.get(f"{base}/subdomain", headers=h)).json()["result"]["subdomain"]
            for l in todo:
                name = ("demo-" + slug(l["name"]))[:60]
                page = Path(l["site"]).read_text()
                worker = "export default { fetch() { return new Response(" + json.dumps(page) + ", { headers: { 'content-type': 'text/html; charset=utf-8' } }); } };"
                assets = await upload_assets(c, base, h, name, Path(l["site"]).parent)   # /img/* is served from assets, the rest by the worker
                meta = {"main_module": "worker.js", "compatibility_date": "2025-01-01", **({"assets": {"jwt": assets}} if assets else {})}
                files = {"metadata": (None, json.dumps(meta), "application/json"),
                         "worker.js": ("worker.js", worker, "application/javascript+module")}
                r = await c.put(f"{base}/scripts/{name}", headers=h, files=files)
                r.raise_for_status()
                await c.post(f"{base}/scripts/{name}/subdomain", headers=h, json={"enabled": True})
                l.update(url=f"https://{name}.{sub}.workers.dev", status="deployed")
                store.kv_put("leads", l["id"], {k: v for k, v in l.items() if k not in ("_key", "_ts")})
        return AgentResult("done", f"{len(todo)} LIVE", "Deployed: " + ", ".join(l["url"] for l in todo))


class ProposalDrafter(SubAgent):
    name, tier, note = "Proposal Drafter", "CLOUD", "pitch waits for your OK"

    async def run(self, ctx):
        store, llm, opts = ctx["store"], ctx.get("llm"), ctx["options"]
        for l in [l for l in store.kv_list("leads") if l.get("status") == "deployed"]:
            msg = (f"Hi {l['name']} team,\n\nI'm {ctx['cfg'].vision.owner}, a local web developer. I noticed you don't have a website yet, so I put together "
                   f"a quick demo: {l['url']}\n\nIf you like it, I can make it yours for {opts.get('price', 'a one-time fee')}, with your photos and details. "
                   f"Happy to drop by or chat.\n\nThanks,\n{ctx['cfg'].vision.owner}")
            if llm:
                try:
                    msg = await llm.complete("Rewrite this pitch to be warm, short and local. Keep the link and price exactly.\n\n" + msg, tier="cloud", max_tokens=300)
                except LLMUnavailable:
                    pass
            request_approval(ctx, self.name, f"Pitch to {l['name']} ({l['type_label']}) · demo {l['url']}",
                             {"key": f"pitch:{l['_key']}", "kind": "proposal", "lead": l["_key"], "message": msg, "url": l["url"], "phone": l.get("phone")})
            l["status"] = "pitch_ready"
            store.kv_put("leads", l.pop("_key"), {k: v for k, v in l.items() if k != "_ts"})
        leads = store.kv_list("leads", limit=1000)
        st = {s: sum(1 for l in leads if l.get("status") == s) for s in ("new", "built", "deployed", "pitch_ready", "pitched")}
        waiting = st["pitch_ready"]
        summary = f"{len(leads)} leads · {st['deployed'] + st['pitch_ready'] + st['pitched']} sites live" + (f" · {waiting} pitch waiting" if waiting else "")
        finder = ctx["results"].get("Business Finder")
        if finder and finder.status == "idle" and not leads:
            summary = finder.summary
        return AgentResult("wait" if waiting else "done", f"{waiting} WAITING" if waiting else "CLEAR", summary, {"stages": st})


async def approve_pitch(row: dict, decision: str, ctx: dict) -> str:
    store, p = ctx["store"], row["payload"]
    l = store.kv_get("leads", p["lead"]) or {}
    if decision != "approved":
        l["status"] = "parked"
        try:
            gone = await remove_demo(l.get("url") or p["url"])
        except httpx.HTTPError:
            gone = False
        if gone:
            l.pop("url", None)
        store.kv_put("leads", p["lead"], l)   # a demo that couldn't be removed keeps its url; the deployer retries
        ctx["rerun"] = True                   # a slot is free: build the next demo now
        return "parked · demo site removed" if gone else "parked · demo site still up, will retry"
    l["status"] = "pitched"
    store.kv_put("leads", p["lead"], l)
    ctx["bus"].notice(f"pitch:{p['lead']}", f"Pitch for {l.get('name', 'the business')} is approved: call {p.get('phone') or 'them'} or drop by. Message is on the dashboard.", p["url"])
    ctx["rerun"] = True
    store.kv_put("pitches", p["lead"], {"message": p["message"], "url": p["url"], "phone": p.get("phone"), "at": time.time()})
    return "approved: message ready to send by phone or in person"


APPROVAL_HANDLERS = {"proposal": approve_pitch}


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    return {"Business Finder": BusinessFinder(), "Information Collector": InformationCollector(), "Competitor Analyst": CompetitorAnalyst(),
            "Images Downloader": ImagesDownloader(), "Color Theme Decider": ColorThemeDecider(), "Website Builder": WebsiteBuilder(),
            "Cloudflare Deployer": CloudflareDeployer(), "Proposal Drafter": ProposalDrafter()}
