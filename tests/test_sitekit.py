"""sitekit: the Web Designer's section library and recipes (no network; pages are rendered and inspected as text)."""

import itertools
import json
import re
from pathlib import Path

import pytest

from vision.masters import site_template
from vision.masters.sitekit import (CATEGORIES, CATEGORY_OF, RECIPES, STYLE_BY_TYPE, STYLES, category_of, color, css, recipes_for, render_site,
                                    signature)
from vision.masters.sitekit.sections import HEROES, NAVS, SECTIONS

THEME = {"primary": "#0B4F8A", "accent": "#F2A541", "bg": "#F7F9FC", "text": "#14212B"}
HOURS = ["Monday: 9:00 AM – 5:00 PM", "Tuesday: 9:00 AM – 5:00 PM", "Sunday: Closed"]
TYPES = {"trade": "roofing_contractor", "food": "cafe", "beauty": "nail_salon", "health": "dentist", "retail": "florist",
         "care": "child_care_agency", "stay": "bed_and_breakfast", "pro": "lawyer", "other": "zoo"}
MINIMAL = {"tagline": "Trusted local business", "about": "A local business serving the community.",
           "services": [{"name": "Service", "text": "Ask us about our services."}]}
FULL = {"headline": "Done right the first time", "tagline": "Careful work for homes nearby.", "about_title": "A local crew", "about": "We do careful work.",
        "services_title": "What we take care of", "gallery_title": "Some photos",
        "services": [{"name": f"Service {n}", "text": f"Details about service {n}."} for n in range(1, 7)],
        "highlights": ["Written quotes", "Tidy sites", "Local crew"],
        "steps": [{"title": "Call", "text": "Tell us what you need."}, {"title": "Visit", "text": "We take a look."}, {"title": "Quote", "text": "A clear price."}],
        "faq": [{"q": "Do you do small jobs?", "a": "Yes, they are welcome."}, {"q": "How do I book?", "a": "Call us."}],
        "cta_title": "Ready when you are", "cta_text": "Call and tell us what is going on.", "area": "Leamington, Kingsville and Essex County",
        "reviews_title": "Kind words", "visit_title": "Where to find us"}


def lead(kind="roofing_contractor", name="Sample Ridge Co"):
    return {"id": "x1", "name": name, "type": kind, "type_label": kind.replace("_", " ").capitalize(),
            "address": "1 Example St, Leamington, ON N8H 0A0, Canada", "phone": "(519) 555-0100", "rating": 4.7, "reviews": 31,
            "info": {"hours": HOURS, "reviews": [{"text": "Fast and fair, would call them again any time.", "author": "Ann", "rating": 5},
                                                 {"text": "Tidy work and clear communication throughout.", "author": "Bo", "rating": 5},
                                                 "They showed up on time and did what they said."]}}


def images(n=6):
    return [{"url": f"https://img.example/{i}.jpg", "file": f"img/{i}.webp", "credit": f"Photo {i} by A (BY 4.0)", "source": f"https://src.example/{i}"}
            for i in range(1, n + 1)]


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_every_recipe_renders_for_every_category(name):
    for cat, kind in TYPES.items():
        for copy, imgs in ((FULL, images()), (MINIMAL, images()), (FULL, []), (MINIMAL, []), ({}, images(1)), (FULL, images(2)), (FULL, images(3))):
            page = render_site(lead(kind), copy, THEME, imgs, name)
            assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
            assert 'href="tel:5195550100"' in page, (name, cat)
            assert "Demo site prepared for Sample Ridge Co. Not yet the business's official website." in page
            assert ("Photos: none." in page) if not imgs else ("Photo 1 by A (BY 4.0)" in page and 'href="https://src.example/1"' in page)
            assert page.count("<h1>") == 1 and "<main" in page and "<footer" in page and "<header" in page
            assert f"sitekit {name}" in page and RECIPES[name]["type"]["query"] in page
            assert "[[" not in page and "None" not in page
            used = sorted(set(re.findall(r'src="(img/\d\.webp)"', page)))
            assert len(used) <= len(imgs) and (not imgs or 'src="img/1.webp"' in page)      # first photo is the hero


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_everything_supplied_is_escaped(name):
    bad = '<script>alert("x")</script>'
    l = lead(name=f"O'Brien & Sons {bad}")
    l["type_label"], l["address"] = f"Roofer {bad}", f'9 "Quote" Rd {bad}, Leamington, ON N8H, Canada'
    l["info"]["reviews"] = [{"text": f"Lovely people and great work {bad}", "author": f"Al {bad}", "rating": 5}] * 2
    l["info"]["hours"] = [f"Monday: {bad}"]
    copy = {k: (f"{v} {bad}" if isinstance(v, str) else v) for k, v in FULL.items()}
    copy["services"] = [{"name": f"Fix {bad}", "text": f'Text "quoted" {bad}'}]
    copy["highlights"] = [f"Point {bad}"]
    copy["steps"] = [{"title": f"Step {bad}", "text": bad}]
    copy["faq"] = [{"q": f"Why {bad}?", "a": bad}]
    imgs = [{"file": f'img/1.webp"><script>x</script>', "url": "", "credit": f"Credit {bad}", "source": f'https://s.example/?a="{bad}', "alt": bad}]
    page = render_site(l, copy, THEME, imgs, name)
    body = re.sub(r"<script( type=\"application/ld\+json\")?>.*?</script>", "", page, flags=re.S)      # the page's own two scripts
    assert "<script" not in body and "alert(\"x\")" not in body
    assert "O&#x27;Brien &amp; Sons &lt;script&gt;" in page and "&quot;quoted&quot;" in page
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1)
    assert "</script" not in ld and json.loads(ld)["name"].startswith("O'Brien")


def test_legacy_styles_unknown_styles_and_shim():
    assert set(RECIPES) | {"luxe", "sunny", "trade", "editorial"} == set(STYLES) == set(site_template.STYLES)
    assert site_template.render_site is render_site and site_template.city_of(lead()) == "Leamington"
    for old, new in (("luxe", "atelier"), ("sunny", "sprout"), ("trade", "foreman"), ("editorial", "gazette")):
        assert f"sitekit {new}" in render_site(lead(), MINIMAL, THEME, images(), old)
    for odd in ("nope", "", None, 7):
        assert "sitekit mainstreet" in render_site(lead(), MINIMAL, THEME, [], odd)
    assert "Manrope" in render_site(lead("plumber"), MINIMAL, THEME, [], "trade")
    assert all(v in RECIPES for v in STYLE_BY_TYPE.values()) and site_template.STYLE_BY_TYPE is STYLE_BY_TYPE
    page = render_site({"name": "Bare"}, None, None, None)                    # the least a caller can pass
    assert "Bare" in page and "tel:" not in page


def test_recipes_for_every_category_and_unknown_type():
    assert len(RECIPES) >= 12 and sum(r["mode"] == "dark" for r in RECIPES.values()) >= 3
    assert set(CATEGORY_OF.values()) | {"other"} == set(CATEGORIES)
    for kind in list(CATEGORY_OF) + ["", None, "space_station"]:
        names = recipes_for(kind)
        assert len(names) >= 4 and len(set(names)) == len(names) and all(n in RECIPES for n in names), kind
    assert category_of("roofing_contractor") == "trade" and category_of("cafe") == "food" and category_of("nail_salon") == "beauty"
    assert category_of("who_knows") == "other" and recipes_for("who_knows") == recipes_for(None)
    for cat in CATEGORIES:                                                    # every category has four recipes that call it home ground
        assert sum(cat in r["for"] for r in RECIPES.values()) >= 4, cat


def test_recipes_are_well_formed_and_pairwise_distinct():
    for name, r in RECIPES.items():
        assert r["label"] and r["for"] and all(c in CATEGORIES for c in r["for"]) and r["mode"] in ("light", "dark")
        assert r["nav"] in NAVS and r["hero"] in HEROES
        kinds = [k for k, _, _ in r["sections"]]
        assert sorted(kinds) == sorted(SECTIONS), name                        # every section kind, once
        assert all(v in SECTIONS[k] and t in ("bg", "alt", "band", "ink") for k, v, t in r["sections"])
        for key in ("type", "heading", "shape", "spacing", "button", "image", "background"):
            assert r[key], (name, key)
    for a, b in itertools.combinations(RECIPES, 2):
        assert signature(a) != signature(b), (a, b)
        layout = lambda n: (RECIPES[n]["nav"], RECIPES[n]["hero"], tuple(sorted((k, v) for k, v, _ in RECIPES[n]["sections"])))
        assert layout(a) != layout(b), (a, b)                                 # distinct even before fonts and colour
    assert len({r["type"]["pair"] for r in RECIPES.values()}) >= 10
    assert len({r["hero"] for r in RECIPES.values()}) >= 7 and len({r["nav"] for r in RECIPES.values()}) >= 3
    assert len(HEROES) >= 7 and len(NAVS) >= 3 and len(SECTIONS["services"]) >= 5 and len(SECTIONS["about"]) >= 3
    assert len(SECTIONS["gallery"]) >= 4 and len(SECTIONS["reviews"]) >= 3 and len(SECTIONS["visit"]) >= 2
    for k, variants in SECTIONS.items():                                      # every variant is used by some recipe
        assert set(variants) == {v for r in RECIPES.values() for kk, v, _ in r["sections"] if kk == k}, k


def test_colour_roles_meet_aa_for_many_palettes():
    from vision.masters import web
    palettes = json.loads((Path(web.__file__).parent / "palettes.json").read_text())
    picks = palettes[::max(1, len(palettes) // 120)][:120]
    themes = [web.theme_from(p["rgb"]) for p in picks]
    themes += [web.pick_theme({"id": f"lead-{n}", "type": t}) for n, t in enumerate(list(web.THEMES) * 2)]
    themes += [dict(zip(("primary", "accent", "bg", "text"), v)) for v in web.PALETTES.values()]
    themes += [{}, {"primary": "#000", "accent": "#FFF", "bg": "#000000", "text": "#ffffff"}, {"primary": "junk", "accent": None}]
    assert len(themes) >= 30
    for theme in themes:
        for mode in ("light", "dark"):
            roles = color.roles(theme, mode)
            assert color.check(roles) == [], (theme, mode, color.check(roles))
            assert all(re.fullmatch(r"#[0-9A-F]{6}", v) for v in roles.values())
        dark = color.roles(theme, "dark")
        assert color.lum(color.rgb(dark["bg"])) < 0.03 and dark["bg"] != "#000000"       # dark, but not pure black
    # the stylesheet only colours text with the role variables that PAIRS covers
    sheet = css.minify(css.BASE + "".join(css.CHUNKS.values()))
    allowed = {"fg", "mut", "hl", "on-cta", "sbg", "text", "muted"}
    assert set(re.findall(r"[;{]color:var\(--([a-z-]+)\)", sheet)) <= allowed
    assert not re.search(r"[;{]color:#", sheet)
    for name, r in RECIPES.items():                                           # and each recipe's page carries its mode's passing roles
        page = render_site(lead(), FULL, THEME, images(), name)
        roles = color.roles(THEME, r["mode"])
        assert all(f"--{k}:{v}" in page for k, v in roles.items()), name


def test_optional_sections_only_with_their_copy():
    marks = {"highlights": 'id="highlights"', "steps": 'id="steps"', "faq": 'id="faq"', "cta": 'id="cta"', "area": 'id="area"'}
    for name in RECIPES:
        bare = render_site(lead(), MINIMAL, THEME, images(), name)
        assert not any(m in bare for m in marks.values()) and "<details" not in bare, name
        full = render_site(lead(), FULL, THEME, images(), name)
        for key, mark in marks.items():
            if key == "highlights" and RECIPES[name]["hero"] == "strip":
                assert 'class="hstrip' in full and "Written quotes" in full   # the strip hero shows them itself
            else:
                assert mark in full, (name, key)
        assert "Serving Leamington, Kingsville and Essex County" in full and "Do you do small jobs?" in full and "Ready when you are" in full
        assert "Kind words" in full and "Where to find us" in full and "What we take care of" in full
        for key, mark in marks.items():                                       # one key at a time
            one = render_site(lead(), {**MINIMAL, **{k: FULL[k] for k in FULL if k.startswith(key[:3])}}, THEME, images(), name)
            others = [m for k, m in marks.items() if k != key]
            assert not any(m in one for m in others), (name, key)
    junk = {**MINIMAL, "highlights": "nope", "steps": [1, None, {"text": "no title"}], "faq": [{"q": "only a question"}], "services": "x", "area": ["a"]}
    assert not any(m in render_site(lead(), junk, THEME, [], "foreman") for m in marks.values())


def test_headings_fit_the_business():
    for name in RECIPES:
        trade = render_site(lead("roofing_contractor"), MINIMAL, THEME, images(), name)
        assert "A look inside" not in trade and "Come and see us" not in trade and "Get in touch" in trade, name
        assert "The kind of work we do" in trade or 'id="gallery"' not in trade
        food = render_site(lead("cafe"), MINIMAL, THEME, images(), name)
        assert "What we serve" in food and "On the table" in food and "What guests say" in food and "The kind of work we do" not in food
        beauty = render_site(lead("nail_salon"), MINIMAL, THEME, images(), name)
        assert "Treatments and services" in beauty and "What clients say" in beauty
    # order follows the category: a trade leads with services, food with photos, beauty with the about story
    pos = lambda page, *ids: [page.index(f'id="{i}"') for i in ids]
    for name in RECIPES:
        t = pos(render_site(lead("plumber"), FULL, THEME, images(), name), "services", "steps", "about", "visit")
        assert t == sorted(t), name
        f = pos(render_site(lead("restaurant"), FULL, THEME, images(), name), "gallery", "services", "visit", "about")
        assert f == sorted(f), name
        b = pos(render_site(lead("hair_care"), FULL, THEME, images(), name), "about", "services", "reviews", "visit")
        assert b == sorted(b), name


def test_images_roles_gallery_degrades_and_no_invented_facts():
    roled = [{"file": "img/a.webp", "credit": "A", "source": "https://s/a", "role": "gallery"},
             {"file": "img/h.webp", "credit": "H", "source": "https://s/h", "role": "hero", "alt": "Our front door"},
             {"file": "img/b.webp", "credit": "B", "source": "https://s/b", "role": "about"},
             {"file": "img/c.webp", "credit": "C", "source": "https://s/c", "role": "gallery"}]
    page = render_site(lead(), MINIMAL, THEME, roled, "mainstreet")
    hero = page[page.index('id="top"'):page.index('id="services"')]
    assert 'src="img/h.webp"' in hero and 'alt="Our front door"' in hero
    about = page[page.index('id="about"'):]
    assert 'src="img/b.webp"' in about[:about.index("</section>")]
    for name in RECIPES:
        for n in range(0, 8):
            p = render_site(lead("cafe"), MINIMAL, THEME, images(n), name)
            gallery = p[p.index('id="gallery"'):].split("</section>")[0] if 'id="gallery"' in p else ""
            shots = gallery.count("<img")
            assert shots <= 6 and (shots == 0) == ('id="gallery"' not in p), (name, n)
            assert len(re.findall(r'src="img/(\d)\.webp"', p)) == len(set(re.findall(r'src="img/(\d)\.webp"', p)))     # no photo twice
    # no reviews, rating or hours: those sections and figures are simply absent
    quiet = {"id": "q", "name": "Quiet Co", "type": "plumber", "address": "2 Side St, Essex, ON N8M, Canada", "phone": "519-555-0111", "info": {}}
    for name in RECIPES:
        p = render_site(quiet, MINIMAL, THEME, [], name)
        assert 'id="reviews"' not in p and "on Google" not in p and "★" not in p and '<table class="hours"' not in p, name
        assert not re.search(r"\b(years|award|guarantee|licen[cs]ed|insured|since \d)", p, re.I), name


def test_page_is_lean_and_safe_without_script():
    whole = css.minify(css.BASE + "".join(css.CHUNKS.values()))
    assert len(whole) < 30_000
    for name in RECIPES:
        page = render_site(lead(), FULL, THEME, images(), name)
        style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
        assert len(style) < 22_000, (name, len(style))
        assert style.count("{") == style.count("}")
        assert ".rise{opacity:0" not in style.replace(".js .rise{opacity:0", "")           # hidden only once the script has run
        assert "prefers-reduced-motion" in style and ":focus-visible" in style and 'class="skip"' in page
        assert page.count("<script") == 2 and "<link" in page and "fonts.googleapis.com/css2?family=" in page
        assert not re.search(r"<img(?![^>]*\balt=)", page) and 'lang="en"' in page
    long = lead(name="Bartholomew Featherstonehaugh-Cholmondeley Plumbing & Heating Services Incorporated")
    assert "overflow-wrap:anywhere" in render_site(long, MINIMAL, THEME, [], "swiss")
