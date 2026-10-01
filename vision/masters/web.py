"""Web Designer (live): Business Finder -> Information Collector + Competitor Analyst -> Images Downloader +
Color Theme Decider -> Website Builder -> Cloudflare Deployer -> Proposal Drafter (reporter) -> YOU.

- Leads: Google Places API (New), businesses near home with no website (GOOGLE_MAPS_API_KEY).
- Images: Openverse (openly licensed images; every image's license and credit is kept on the site).
- Deploy: Cloudflare Workers (CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID), one demo per lead.
- Nothing is sent to a business until you approve the pitch.
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
from urllib.parse import urlparse

from ..agents import AgentResult, SubAgent, request_approval
from ..config import ROOT, secret
from ..services import weather
from ..services.llm import LLMUnavailable

PLACES = "https://places.googleapis.com/v1/places:searchNearby"
FIELDS = "places.id,places.displayName,places.formattedAddress,places.websiteUri,places.nationalPhoneNumber,places.primaryType,places.primaryTypeDisplayName,places.rating,places.userRatingCount,places.location"
SOCIAL = re.compile(r"facebook\.com|instagram\.com|linktr\.ee|yelp\.|business\.site", re.I)
PALETTES = {
    "plumber": ("#0B4F8A", "#F2A541", "#F7F9FC", "#14212B"), "beauty_salon": ("#7A2E5C", "#E8B4C8", "#FFF8FB", "#2B1622"),
    "hair_care": ("#3D2C4E", "#D9A441", "#FBF8F3", "#211A29"), "restaurant": ("#8C2F1B", "#E9B44C", "#FFF9F2", "#2A1610"),
    "cafe": ("#5A3E2B", "#C9A27E", "#FBF6EF", "#2A1E15"), "car_repair": ("#1F2A36", "#E4572E", "#F5F6F8", "#11161C"),
    "dentist": ("#0F6F78", "#9ED9D6", "#F4FBFB", "#12302F"), "bakery": ("#A0522D", "#F3D29B", "#FFFAF2", "#2B1A10"),
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


class BusinessFinder(SubAgent):
    name, tier, note = "Business Finder", "API", "no-website businesses nearby"

    async def run(self, ctx):
        key, opts, store = secret("GOOGLE_MAPS_API_KEY"), ctx["options"], ctx["store"]
        if not key:
            return AgentResult("idle", "NOT SET UP", "Web Designer: add GOOGLE_MAPS_API_KEY to .env")
        home = ctx["cfg"].vision.home_city
        async with httpx.AsyncClient(timeout=25) as c:
            g = await weather.geocode(c, home)
            found, competitors = [], []
            for t in opts.get("business_types", ["plumber", "beauty_salon", "restaurant", "cafe", "hair_care", "car_repair"]):
                r = await c.post(PLACES, headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS}, json={
                    "includedTypes": [t], "maxResultCount": 20, "locationRestriction": {"circle": {
                        "center": {"latitude": g["latitude"], "longitude": g["longitude"]}, "radius": float(opts.get("radius_km", 10)) * 1000}}})
                r.raise_for_status()
                for p in r.json().get("places", []):
                    site = p.get("websiteUri", "")
                    item = {"id": p["id"], "name": p["displayName"]["text"], "type": t, "type_label": (p.get("primaryTypeDisplayName") or {}).get("text", t),
                            "address": p.get("formattedAddress", ""), "phone": p.get("nationalPhoneNumber", ""), "rating": p.get("rating"),
                            "reviews": p.get("userRatingCount"), "website": site}
                    (found if not site or SOCIAL.search(site) else competitors).append(item)
        new = [p for p in found if not store.kv_has("leads", p["id"])][: int(opts.get("max_new_leads", 3))]
        for p in new:
            store.kv_put("leads", p["id"], {**p, "status": "new"})
        ctx["leads"] = [l for l in store.kv_list("leads") if l.get("status") in ("new", "researched")][:3]
        ctx["competitors"] = competitors
        return AgentResult("done", f"{len(new)} NEW", f"{len(found)} businesses without a site · {len(new)} new leads",
                           {"leads": [{"name": l["name"], "type": l["type_label"]} for l in ctx["leads"]]})


class InformationCollector(SubAgent):
    name, tier, note, blocking = "Information Collector", "API", "hours · reviews", False

    async def run(self, ctx):
        key, store = secret("GOOGLE_MAPS_API_KEY"), ctx["store"]
        async with httpx.AsyncClient(timeout=20) as c:
            for l in ctx.get("leads", []):
                if l.get("info"):
                    continue
                r = await c.get(f"https://places.googleapis.com/v1/places/{l['id']}", headers={"X-Goog-Api-Key": key,
                                "X-Goog-FieldMask": "regularOpeningHours.weekdayDescriptions,editorialSummary,reviews.text.text,reviews.rating"})
                d = r.json() if r.status_code == 200 else {}
                l["info"] = {"hours": (d.get("regularOpeningHours") or {}).get("weekdayDescriptions", []),
                             "summary": (d.get("editorialSummary") or {}).get("text", ""),
                             "reviews": [x.get("text", {}).get("text", "")[:300] for x in d.get("reviews", [])][:5]}
                store.kv_put("leads", l["id"], {k: v for k, v in l.items() if k not in ("_key", "_ts")})
        return AgentResult("done", "COLLECTED", f"Details for {len(ctx.get('leads', []))} leads")


class CompetitorAnalyst(SubAgent):
    name, tier, note, blocking = "Competitor Analyst", "DEEP", "what rivals' sites do well", False

    async def run(self, ctx):
        llm, notes = ctx.get("llm"), {}
        for l in ctx.get("leads", []):
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
        ctx["competitor_notes"] = notes
        return AgentResult("done", f"{len(notes)} ANALYSED", f"Competitor notes for {len(notes)} leads")


class ImagesDownloader(SubAgent):
    name, tier, note, blocking = "Images Downloader", "API", "Openverse · licensed + credited", False

    async def run(self, ctx):
        imgs = {}
        async with httpx.AsyncClient(timeout=20) as c:
            for l in ctx.get("leads", []):
                q = l["type_label"] or l["type"].replace("_", " ")
                r = await c.get("https://api.openverse.org/v1/images/", params={"q": q, "license_type": "commercial,modification", "page_size": 6, "aspect_ratio": "wide"})
                res = r.json().get("results", []) if r.status_code == 200 else []
                imgs[l["id"]] = [{"url": i["url"], "credit": f"{i.get('title') or 'Photo'} by {i.get('creator') or 'unknown'} ({(i.get('license') or '').upper()} {i.get('license_version') or ''})",
                                  "source": i.get("foreign_landing_url") or i.get("url")} for i in res[:4]]
        ctx["images"] = imgs
        return AgentResult("done", f"{sum(len(v) for v in imgs.values())} IMAGES", "Licensed images picked, credits recorded")


class ColorThemeDecider(SubAgent):
    name, tier, note, blocking = "Color Theme Decider", "QUICK", "palette by business type", False

    async def run(self, ctx):
        themes = {l["id"]: dict(zip(("primary", "accent", "bg", "text"), PALETTES.get(l["type"], ("#1E3A5F", "#F2B134", "#F8F9FB", "#16202B")))) for l in ctx.get("leads", [])}
        ctx["themes"] = themes
        return AgentResult("done", "PICKED", f"{len(themes)} palettes")


def render_site(lead: dict, copy: dict, theme: dict, images: list[dict]) -> str:
    e = lambda s: html.escape(str(s or ""))
    hero = images[0]["url"] if images else ""
    services = "".join(f"<div class='card'><h3>{e(s.get('name'))}</h3><p>{e(s.get('text'))}</p></div>" for s in copy.get("services", [])[:6])
    hours = "".join(f"<li>{e(h)}</li>" for h in (lead.get("info") or {}).get("hours", []))
    gallery = "".join(f"<img src='{e(i['url'])}' alt='' loading='lazy'>" for i in images[1:4])
    credits = " · ".join(f"<a href='{e(i['source'])}' rel='noopener'>{e(i['credit'])}</a>" for i in images)
    tel = re.sub(r"[^0-9+]", "", lead.get("phone", ""))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(lead['name'])}</title><meta name="description" content="{e(copy.get('tagline'))}">
<style>:root{{--p:{theme['primary']};--a:{theme['accent']};--bg:{theme['bg']};--t:{theme['text']}}}*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--t);line-height:1.55}}
header{{min-height:68vh;display:flex;align-items:flex-end;background:linear-gradient(180deg,rgba(0,0,0,.15),rgba(0,0,0,.65)),url('{e(hero)}') center/cover,var(--p);color:#fff}}
.wrap{{max-width:1040px;margin:0 auto;padding:32px 20px}}h1{{font-size:clamp(2rem,6vw,3.6rem);margin:0 0 8px}}.btn{{display:inline-block;background:var(--a);color:var(--t);padding:14px 22px;border-radius:10px;font-weight:700;text-decoration:none;margin-top:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}}.card{{background:#fff;border-radius:14px;padding:18px;box-shadow:0 2px 14px rgba(0,0,0,.06)}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}.gallery img{{width:100%;height:180px;object-fit:cover;border-radius:12px}}
section h2{{color:var(--p)}}footer{{font-size:.8rem;opacity:.75}}footer a{{color:inherit}}</style></head><body>
<header><div class="wrap"><h1>{e(lead['name'])}</h1><p style="font-size:1.2rem;max-width:640px">{e(copy.get('tagline'))}</p>
{f"<a class='btn' href='tel:{tel}'>Call {e(lead.get('phone'))}</a>" if tel else ""}</div></header>
<section class="wrap"><h2>What we do</h2><div class="grid">{services}</div></section>
<section class="wrap"><h2>About us</h2><p>{e(copy.get('about'))}</p></section>
{f"<section class='wrap'><div class='gallery'>{gallery}</div></section>" if gallery else ""}
<section class="wrap"><h2>Visit us</h2><p>{e(lead.get('address'))}</p>{f"<ul>{hours}</ul>" if hours else ""}</section>
<footer class="wrap">Demo site prepared for {e(lead['name'])}. Photos: {credits or 'placeholder'}.</footer></body></html>"""


class WebsiteBuilder(SubAgent):
    name, tier, note = "Website Builder", "CLOUD", "copy + responsive template"

    async def run(self, ctx):
        llm, store, built = ctx.get("llm"), ctx["store"], 0
        for l in ctx.get("leads", []):
            if l.get("site"):
                continue
            info = l.get("info") or {}
            copy = {"tagline": f"Trusted {l['type_label'].lower()} in {l['address'].split(',')[-3:-2][0].strip() if l['address'].count(',') >= 2 else 'your area'}",
                    "about": info.get("summary") or f"{l['name']} is a local {l['type_label'].lower()} serving the community.",
                    "services": [{"name": l["type_label"], "text": "Ask us about our services."}]}
            if llm:
                try:
                    copy = await llm.json("Write website copy as JSON {tagline, about (60 words), services:[{name,text}] (4 items)} for this local business. "
                                          "Only use facts given; keep claims modest.\n" + json.dumps({"name": l["name"], "type": l["type_label"], "address": l["address"],
                                          "rating": l.get("rating"), "reviews": info.get("reviews", [])[:3], "rival_tips": ctx.get("competitor_notes", {}).get(l["id"], "")}),
                                          tier="cloud", max_tokens=700) or copy
                except LLMUnavailable:
                    pass
            page = render_site(l, copy, ctx.get("themes", {}).get(l["id"]) or dict(zip(("primary", "accent", "bg", "text"), PALETTES["plumber"])), ctx.get("images", {}).get(l["id"], []))
            d = ROOT / "data" / "sites" / slug(l["name"])
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(page)
            l.update(site=str(d / "index.html"), status="built")
            store.kv_put("leads", l["id"], {k: v for k, v in l.items() if k not in ("_key", "_ts")})
            built += 1
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
                files = {"metadata": (None, json.dumps({"main_module": "worker.js", "compatibility_date": "2025-01-01"}), "application/json"),
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
        return "parked · demo site removed" if gone else "parked · demo site still up, will retry"
    l["status"] = "pitched"
    store.kv_put("leads", p["lead"], l)
    ctx["bus"].notice(f"pitch:{p['lead']}", f"Pitch for {l.get('name', 'the business')} is approved: call {p.get('phone') or 'them'} or drop by. Message is on the dashboard.", p["url"])
    store.kv_put("pitches", p["lead"], {"message": p["message"], "url": p["url"], "phone": p.get("phone"), "at": time.time()})
    return "approved: message ready to send by phone or in person"


APPROVAL_HANDLERS = {"proposal": approve_pitch}


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    return {"Business Finder": BusinessFinder(), "Information Collector": InformationCollector(), "Competitor Analyst": CompetitorAnalyst(),
            "Images Downloader": ImagesDownloader(), "Color Theme Decider": ColorThemeDecider(), "Website Builder": WebsiteBuilder(),
            "Cloudflare Deployer": CloudflareDeployer(), "Proposal Drafter": ProposalDrafter()}
