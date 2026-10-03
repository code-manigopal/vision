#!/usr/bin/env python3
"""Contact sheet for the Web Designer's sitekit: every recipe rendered for a few made-up businesses.

    .venv/bin/python scripts/site_contact_sheet.py        ->  data/sites/_contact/index.html

Writes data/sites/_contact/<recipe>-<sample>.html plus an overview page with scaled live previews (desktop and
phone width). The businesses are fictional. Photos are not copied: pages point at stock photos already saved
under data/sites/*/img (picked at run time); with none on disk the pages render without photos.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision.masters.sitekit import RECIPES, recipes_for, render_site  # noqa: E402

OUT = ROOT / "data" / "sites" / "_contact"
HOURS = ["Monday: 8:00 AM – 5:00 PM", "Tuesday: 8:00 AM – 5:00 PM", "Wednesday: 8:00 AM – 5:00 PM", "Thursday: 8:00 AM – 6:00 PM",
         "Friday: 8:00 AM – 5:00 PM", "Saturday: 9:00 AM – 1:00 PM", "Sunday: Closed"]

SAMPLES = {
    # full copy: every optional key
    "roofer": {
        "photos": ("improvement", "electric", "plumb", "mechanical", "tire"), "count": 6,
        "theme": {"primary": "#1F4E79", "accent": "#F2A541", "bg": "#F6F8FB", "text": "#14212B"},
        "lead": {"id": "sample-roofer", "name": "Sample Ridgeline Roofing", "type": "roofing_contractor", "type_label": "Roofing contractor",
                 "address": "120 Example Line, Leamington, ON N8H 0A0, Canada", "phone": "(519) 555-0142", "rating": 4.8, "reviews": 64,
                 "info": {"hours": HOURS, "reviews": [
                     {"text": "They replaced our whole roof in two days and left the yard cleaner than they found it. Clear quote, no surprises.", "author": "Dana P.", "rating": 5},
                     {"text": "Called about a leak on a Sunday night and someone was out first thing Monday. Fair price and tidy work.", "author": "Marcus L.", "rating": 5},
                     {"text": "Good communication from start to finish. The crew was polite and on time every day.", "author": "Priya S.", "rating": 4}]}},
        "copy": {"headline": "Roofs done right, start to finish", "tagline": "Repairs, replacements and inspections for homes across Essex County.",
                 "about_title": "A local crew you can reach", "about": "Sample Ridgeline Roofing is a Leamington roofing contractor. Customers mention clear quotes, tidy job sites and crews that show up when they say they will. Call to talk through a repair or a full replacement.",
                 "services_title": "What we take care of", "services": [
                     {"name": "Roof replacement", "text": "Full tear-off and re-roofing in asphalt shingle or steel."},
                     {"name": "Leak repair", "text": "Finding the source and fixing it, not just the stain on the ceiling."},
                     {"name": "Inspections", "text": "A written look at the roof's condition before you buy, sell or renew."},
                     {"name": "Eavestrough and fascia", "text": "Repairs and replacement so water goes where it should."},
                     {"name": "Flat roofs", "text": "Membrane repairs and replacements for garages and additions."},
                     {"name": "Storm damage", "text": "Missing shingles and lifted flashing put right quickly."}],
                 "highlights": ["Written quotes before any work", "Site left clean every day", "Repairs and full replacements"],
                 "steps": [{"title": "Call or message", "text": "Tell us what you are seeing and where."},
                           {"title": "Roof visit", "text": "We look at the roof and take photos for you."},
                           {"title": "Written quote", "text": "A clear price and scope, with options where they exist."},
                           {"title": "The work", "text": "A tidy crew, and a walk-through when it is done."}],
                 "faq": [{"q": "Do you handle small repairs?", "a": "Yes. Many calls are for a few shingles or one leak, and those are welcome."},
                         {"q": "How long does a replacement take?", "a": "It depends on the roof's size and the weather; we give an estimate with the quote."},
                         {"q": "Can you work with my insurer?", "a": "We can provide photos and a written scope for your claim."}],
                 "cta_title": "Seen a leak or a missing shingle?", "cta_text": "Call and tell us what is going on. We will book a time to look at it.",
                 "area": "Leamington, Kingsville and Essex County", "gallery_title": "Roofs and details"},
    },
    # typical copy: what the builder writes today, plus highlights
    "cafe": {
        "photos": ("cafe", "coffee", "bakery", "carajillo"), "count": 6,
        "theme": {"primary": "#5A3E2B", "accent": "#C9864A", "bg": "#FBF6EF", "text": "#2A1E15"},
        "lead": {"id": "sample-cafe", "name": "Sample Lantern Cafe", "type": "cafe", "type_label": "Cafe",
                 "address": "8 Placeholder Street, Kingsville, ON N9Y 0A0, Canada", "phone": "(519) 555-0177", "rating": 4.6, "reviews": 212,
                 "info": {"hours": [h.replace("8:00 AM", "7:00 AM").replace("Sunday: Closed", "Sunday: 8:00 AM – 2:00 PM") for h in HOURS], "reviews": [
                     {"text": "The best flat white in town and the butter tarts sell out for a reason. Friendly faces behind the counter every time.", "author": "Jo M.", "rating": 5},
                     {"text": "Cozy corner tables, quick service and a breakfast sandwich I keep coming back for.", "author": "Elena R.", "rating": 5},
                     "Lovely spot to sit with a book. Great coffee."]}},
        "copy": {"headline": "Coffee, bakes and a slow morning", "tagline": "A small cafe on the main street, open early every day of the week.",
                 "about_title": "Your corner table is waiting", "about": "Sample Lantern Cafe serves espresso drinks, fresh bakes and simple breakfasts in Kingsville. Regulars mention the flat whites, the butter tarts and the friendly counter.",
                 "services": [{"name": "Espresso bar", "text": "Flat whites, lattes, cortados and drip, hot or iced."},
                              {"name": "Fresh bakes", "text": "Butter tarts, scones and loaves baked in the morning."},
                              {"name": "Breakfast", "text": "Egg sandwiches, toast and oats until they run out."},
                              {"name": "Lunch", "text": "Soup, grilled sandwiches and a daily salad."},
                              {"name": "Beans to go", "text": "Whole beans by the bag, ground if you ask."}],
                 "highlights": ["Open from 7 on weekdays", "Baked fresh each morning", "Dine in or take away"]},
    },
    # minimal copy and three photos: the fallbacks
    "nails": {
        "photos": ("barber", "salon", "nail", "kyla"), "count": 3,
        "theme": {"primary": "#7A2E5C", "accent": "#E8B4C8", "bg": "#FFF8FB", "text": "#2B1622"},
        "lead": {"id": "sample-nails", "name": "Sample Petal & Polish Nail Studio", "type": "nail_salon", "type_label": "Nail salon",
                 "address": "45 Demo Avenue, Leamington, ON N8H 0B0, Canada", "phone": "(519) 555-0109", "rating": 4.9, "reviews": 38,
                 "info": {"hours": HOURS[:6], "reviews": [
                     {"text": "My gel manicure lasted three full weeks. Spotless studio and such a calm atmosphere.", "author": "Sam T.", "rating": 5}]}},
        "copy": {"tagline": "Trusted nail salon in Leamington",
                 "about": "Sample Petal & Polish Nail Studio is a local nail salon serving the community.",
                 "services": [{"name": "Manicures", "text": "Classic, gel and shellac."}, {"name": "Pedicures", "text": "Soak, shape and polish."},
                              {"name": "Nail art", "text": "Simple accents to full sets."}]},
    },
    # no photos at all: the type-led pages
    "plain": {
        "photos": (), "count": 0,
        "theme": {"primary": "#22577A", "accent": "#57CC99", "bg": "#F7FAF9", "text": "#12262F"},
        "lead": {"id": "sample-books", "name": "Sample Ledger & Co. Accounting", "type": "accounting", "type_label": "Accountant",
                 "address": "300 Fictional Road, Essex, ON N8M 0A0, Canada", "phone": "(519) 555-0188", "info": {}},
        "copy": {"headline": "Books kept straight, all year", "tagline": "Bookkeeping and tax filing for small businesses and households.",
                 "about": "Sample Ledger & Co. Accounting is a local accountant serving the community.",
                 "services": [{"name": "Bookkeeping", "text": "Monthly books kept tidy and up to date."}, {"name": "Tax returns", "text": "Personal and small-business filing."},
                              {"name": "Payroll", "text": "Pay runs and remittances handled on schedule."}, {"name": "Year-end", "text": "Statements prepared for your records."}],
                 "area": "Essex, Leamington and Kingsville"},
    },
}


def photos(words: tuple, count: int) -> list:
    """Stock photos already on disk, by relative path from data/sites/_contact (nothing is copied)."""
    if not count:
        return []
    dirs = sorted(d for d in (ROOT / "data" / "sites").glob("*/img") if d.parent.name != "_contact" and any(d.glob("*.webp")))
    if not dirs:
        return []
    best = next((d for w in words for d in dirs if w in d.parent.name), dirs[0])
    files = sorted(best.glob("*.webp"))[:count]
    return [{"file": f"../{best.parent.name}/img/{f.name}", "url": "", "credit": f"Stock photo {n} (sample)", "source": "https://example.com/"}
            for n, f in enumerate(files, 1)]


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>sitekit contact sheet</title><style>
*{box-sizing:border-box;margin:0}body{background:#0b0d10;color:#e8eaed;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:2rem clamp(1rem,3vw,2.5rem) 4rem}
h1{font-size:1.5rem;font-weight:650}h1+p{color:#9aa3ad;margin:.4rem 0 1rem;max-width:70ch}
.toc{display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:2.5rem}.toc a{color:#e8eaed;text-decoration:none;border:1px solid #2a3038;border-radius:999px;padding:.2rem .75rem;font-size:.85rem}.toc a:hover{background:#1a1f26}
section{margin-bottom:3.25rem;padding-top:1.25rem;border-top:1px solid #23282f}
h2{font-size:1.15rem;font-weight:650;display:flex;flex-wrap:wrap;gap:.6rem;align-items:baseline}
h2 small{font-weight:400;color:#9aa3ad;font-size:.85rem}.tag{font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;border:1px solid #3a424d;border-radius:4px;padding:.05rem .4rem;color:#c9d1d9}
.meta{color:#9aa3ad;font-size:.82rem;margin:.3rem 0 1rem}
.row{display:flex;flex-wrap:wrap;gap:1.1rem;align-items:flex-start}
figure{margin:0}figcaption{font-size:.8rem;color:#9aa3ad;margin-top:.35rem}figcaption a{color:#8ab4f8}
.shot{display:block;position:relative;overflow:hidden;border:1px solid #2a3038;border-radius:8px;background:#fff}
.shot iframe{border:0;transform-origin:0 0;pointer-events:none}
.d{width:320px;height:430px}.d iframe{width:1280px;height:1720px;transform:scale(.25)}
.m{width:150px;height:430px}.m iframe{width:375px;height:1075px;transform:scale(.4)}
</style></head><body><h1>sitekit contact sheet</h1><p>__INTRO__</p><nav class="toc">__TOC__</nav>__BODY__</body></html>"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    esc, body, toc, total = html.escape, "", "", 0
    for name, r in RECIPES.items():
        cells = {"d": "", "m": ""}
        for key, s in SAMPLES.items():
            page = render_site(s["lead"], s["copy"], s["theme"], photos(s["photos"], s["count"]), name)
            file = f"{name}-{key}.html"
            (OUT / file).write_text(page, encoding="utf-8")
            total += 1
            for size in ("d", "m"):
                cells[size] += (f'<figure><a class="shot {size}" href="{file}" target="_blank" rel="noopener"><iframe src="{file}" loading="lazy" tabindex="-1" '
                                f'title="{esc(name)} {esc(key)} {"desktop" if size == "d" else "phone"}"></iframe></a>'
                                f'<figcaption><a href="{file}" target="_blank" rel="noopener">{esc(key)}</a> · {"1280" if size == "d" else "375"}px</figcaption></figure>')
        variants = " · ".join(f"{k}: {v}" for k, v, _ in r["sections"] if k in ("services", "about", "gallery", "reviews", "visit"))
        toc += f'<a href="#{name}">{esc(name)}</a>'
        body += (f'<section id="{name}"><h2>{esc(name)} <small>{esc(r["label"])}</small> <span class="tag">{r["mode"]}</span></h2>'
                 f'<p class="meta">for {esc(", ".join(r["for"]))} · nav: {r["nav"]} · hero: {r["hero"]} · {esc(variants)} · {esc(r["type"]["pair"])}</p>'
                 f'<div class="row">{cells["d"]}</div><div class="row" style="margin-top:1.1rem">{cells["m"]}</div></section>')
    intro = (f"{len(RECIPES)} recipes × {len(SAMPLES)} fictional businesses (roofer: full copy · cafe: typical copy · nails: minimal copy, three photos · "
             "plain: no photos). Click a preview for the full page. Best recipes per type: "
             + "; ".join(f"{s['lead']['type']} → {', '.join(recipes_for(s['lead']['type'])[:4])}" for s in SAMPLES.values()) + ".")
    (OUT / "index.html").write_text(PAGE.replace("__INTRO__", esc(intro)).replace("__TOC__", toc).replace("__BODY__", body), encoding="utf-8")
    print(f"{total} pages + index -> {OUT / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
