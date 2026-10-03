from pathlib import Path

import pytest
from PIL import Image

from vision.masters.site_qa import check_site, fixable_by_rebuild, summarize

LEAD = {"name": "Cedar Cafe", "phone": "(519) 555-0142", "address": "1 Main St, Windsor"}
CSS = ("html{scroll-behavior:smooth}:root{--bg:#ffffff;--text:#1a1a1a;--primary:#7a1f1f;--accent:#1f4f7a;"
       "--on-primary:#ffffff;--on-accent:#ffffff;--muted:#555555;--surface:#f4f4f4}"
       "body{background:var(--bg);color:var(--text);font-size:16px}.wrap{max-width:1100px;margin:auto}"
       ".js .rise{opacity:0}.js .rise.in{opacity:1}img{max-width:100%}")


def page(body_extra="", css=CSS, head_extra="", lead_name="Cedar Cafe", h1="Cedar Cafe in Windsor", footer=None):
    footer = footer if footer is not None else (
        "<p>Demo site prepared for Cedar Cafe. Not yet the business's official website.</p>"
        "<p>Photos: <a href='https://x.test/a'>Jane on Pexels</a>.</p>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{lead_name} - Windsor</title>
<meta name="description" content="Fresh coffee and baking in Windsor."><style>{css}</style>{head_extra}</head>
<body><header><h1>{h1}</h1><a href="tel:5195550142">Call (519) 555-0142</a></header>
<main><section><h2>About us</h2><p>We bake bread every morning and serve coffee all day long.</p>
<img src="img/1.webp" alt="Bread"></section>
<section><h2>Visit</h2><p>Find us on Main Street in Windsor, open daily.</p>
<a href="https://www.google.com/maps/search/?api=1&query=Cedar">Get directions</a></section>{body_extra}</main>
<footer>{footer}</footer><script>document.title=document.title;</script></body></html>"""


def mk_img(d, name="1.webp", size=(900, 600)):
    (d / "img").mkdir(exist_ok=True)
    Image.new("RGB", size, (120, 80, 40)).save(d / "img" / name)


@pytest.fixture
def site(tmp_path):
    mk_img(tmp_path)
    return tmp_path


def ids(r, sev=None):
    return {i["id"] for i in r["issues"] if sev is None or i["severity"] == sev}


def run(html, site, **kw):
    kw.setdefault("lead", LEAD)
    return check_site(html, site_dir=site, **kw)


def test_good_page_passes(site):
    r = run(page(), site, theme={"primary": "#7a1f1f", "accent": "#1f4f7a", "bg": "#ffffff", "text": "#1a1a1a"})
    assert r["ok"], r["issues"]
    assert r["score"] >= 90
    assert summarize(r) == "QA passed"


def test_placeholder_text(site):
    for bad in ("Lorem ipsum dolor", "{{name}}", "undefined", "Your Business", "{'name': 'x'}", "Hello,, world"):
        r = run(page(f"<section><h2>Extra</h2><p>{bad} more text here.</p></section>"), site)
        assert "placeholder-text" in ids(r, "fail"), bad


def test_markdown_artifact(site):
    r = run(page("<section><h2>X</h2><p>```json {} ``` and more text</p></section>"), site)
    assert "markdown-artifact" in ids(r, "fail")


def test_business_name_missing(site):
    r = check_site(page(lead_name="Other", h1="Welcome home", footer="<p>Demo site prepared for Other. Not yet the business's official website.</p><p>Photos: A.</p>"),
                   site_dir=site, lead=LEAD)
    assert "business-name-missing" in ids(r, "fail")


def test_duplicate_headings(site):
    r = run(page("<section><h2>About us</h2><p>Another block of enough text here.</p></section>"), site)
    assert "duplicate-headings" in ids(r, "fail")


def test_missing_tel(site):
    r = run(page().replace('href="tel:5195550142"', 'href="#"'), site)
    assert "missing-tel" in ids(r, "fail")


def test_missing_disclaimer(site):
    r = run(page(footer="<p>Photos: A.</p>"), site)
    assert "missing-disclaimer" in ids(r, "fail")


def test_two_h1(site):
    r = run(page("<section><h1>Second</h1><p>Plenty of text in this section.</p></section>"), site)
    assert "one-h1" in ids(r, "fail")


def test_empty_section(site):
    r = run(page("<section><h2>Hi</h2></section>"), site)
    assert "empty-section" in ids(r, "fail")


def test_unbalanced(site):
    r = run(page("<div><p>text that is long enough to be fine</p>"), site)
    assert "unbalanced-tags" in ids(r, "fail")


def test_missing_and_corrupt_image(tmp_path):
    r = run(page(), tmp_path)
    assert "img-missing" in ids(r, "fail")
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "1.webp").write_bytes(b"not an image")
    assert "img-corrupt" in ids(run(page(), tmp_path), "fail")


def test_tiny_image_and_alt(tmp_path):
    mk_img(tmp_path, size=(200, 100))
    assert "img-tiny" in ids(run(page(), tmp_path), "warn")
    mk_img(tmp_path)
    r = run(page().replace(' alt="Bread"', ""), tmp_path)
    assert "img-no-alt" in ids(r, "fail")


def test_duplicate_image_and_empty_gallery(site):
    extra = '<section><h2>Gallery</h2><div class="gallery"><p>Our shop in pictures soon.</p></div></section>' + \
            '<img src="img/1.webp" alt=""><img src="img/1.webp" alt="">'
    r = run(page(extra), site)
    assert {"img-duplicate", "gallery-empty"} <= ids(r, "warn")


def test_low_contrast_vars(site):
    css = CSS.replace("--text:#1a1a1a", "--text:#bbbbbb")
    r = run(page(css=css), site)
    assert "contrast-fail" in ids(r, "fail")
    r = check_site(page(), site_dir=site, lead=LEAD, theme={"primary": "#fff", "accent": "#eee", "bg": "#ffffff", "text": "#cccccc"})
    assert "contrast-fail" in ids(r, "fail")


def test_fixed_width(site):
    r = run(page(css=CSS + ".box{width:900px}", body_extra='<section><h2>Box</h2><div class="box">content for the box here</div></section>'), site)
    assert "fixed-width" in ids(r, "fail")
    r = run(page('<section><h2>B</h2><div style="width:700px">enough content inside the box</div></section>'), site)
    assert "fixed-width" in ids(r, "fail")


def test_nowrap_heading(site):
    r = run(page(css=CSS + "h2{white-space:nowrap}"), site)
    assert "nowrap-text" in ids(r, "fail")


def test_hidden_without_js(site):
    css = CSS.replace(".js .rise{opacity:0}", ".rise{opacity:0}")
    r = run(page('<section class="rise"><h2>Late</h2><p>Text that stays invisible.</p></section>', css=css), site)
    assert "hidden-without-js" in ids(r, "fail")
    ok = run(page('<section class="rise"><h2>Late</h2><p>Text is shown without js.</p></section>'), site)
    assert "hidden-without-js" not in ids(ok)


def test_http_and_external_script(site):
    r = run(page(head_extra='<link rel="stylesheet" href="http://fonts.example.org/x.css">'), site)
    assert "insecure-resource" in ids(r, "fail")
    r = run(page(head_extra='<script src="https://cdn.test/a.js"></script>'), site)
    assert "external-script" in ids(r, "fail")


def test_risky_claim(site):
    r = run(page("<section><h2>Why us</h2><p>Our award-winning team has 20 years of experience. Only $49.</p></section>"), site)
    w = [i for i in r["issues"] if i["id"] == "risky-claim"]
    assert w and all(i["severity"] == "warn" for i in w) and r["ok"]
    r = check_site(page("<section><h2>Why us</h2><p>Our award-winning team serves you daily.</p></section>"), site_dir=site,
                   lead={**LEAD, "info": "Award-winning bakery"})
    assert "risky-claim" not in ids(r)


def test_long_word(site):
    r = run(page("<section><h2>Long</h2><p>" + "a" * 40 + " is a very long word.</p></section>"), site)
    assert "long-word" in ids(r, "warn")


def test_fixable_by_rebuild(site):
    assert fixable_by_rebuild(run(page("<section><h2>Hi</h2></section>"), site))
    assert not fixable_by_rebuild(run(page(), site))
    assert not fixable_by_rebuild(run(page("<p>Lorem ipsum</p>"), site))
    mixed = run(page("<section><h2>Hi</h2></section><p>Lorem ipsum</p>"), site)
    assert not fixable_by_rebuild(mixed)
    assert not fixable_by_rebuild(run(page(), site.parent))  # missing image files


def test_summarize_failed(site):
    s = summarize(run(page("<section><h2>Hi</h2></section>"), site))
    assert s.startswith("QA failed: 1 problems:")


def test_existing_sites_well_formed():
    dirs = sorted(Path(__file__).resolve().parents[1].glob("data/sites/*/index.html"))
    if not dirs:
        pytest.skip("no generated sites")
    for f in dirs:
        r = check_site(f.read_text(errors="replace"), site_dir=f.parent)
        assert isinstance(r["ok"], bool) and 0 <= r["score"] <= 100
        assert all({"id", "severity", "message", "where"} <= set(i) for i in r["issues"])


def test_shown_by_a_media_query_is_not_hidden_content():
    from vision.masters.site_qa import check_site
    page = lambda css: ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Acme Roofing</title><meta name="description" content="Roofer">'
                        f'<meta name="viewport" content="width=device-width, initial-scale=1"><style>{css}</style></head><body><main><h1>Acme Roofing</h1>'
                        '<section><p>We repair and replace roofs across the county, large and small.</p></section>'
                        '<div class="callbar"><a href="tel:5195550100">Call (519) 555-0100 today</a></div></main>'
                        "<footer><p>Demo site prepared for Acme Roofing. Not yet the business's official website.</p></footer></body></html>")
    ids = lambda css: {i["id"] for i in check_site(page(css))["issues"]}
    assert "hidden-without-js" not in ids(".callbar{display:none}@media (max-width:700px){.callbar{display:flex}}")   # a mobile-only call bar
    assert "hidden-without-js" in ids(".callbar{display:none}")                                                        # never shown: still a fault


def test_excited_customer_reviews_are_not_placeholder_text():
    from vision.masters.site_qa import check_site
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Faspa Place</title><meta name="description" content="Bakery">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body><main><h1>Faspa Place</h1>'
            '<section><blockquote>The cake was amazing and the birthday girls will love it. Thank you!! Really??</blockquote></section></main>'
            "<footer><p>Demo site prepared for Faspa Place. Not yet the business's official website.</p></footer></body></html>")
    assert "placeholder-text" not in {i["id"] for i in check_site(page)["issues"]}
    assert "placeholder-text" in {i["id"] for i in check_site(page.replace("love it.", "love it,, truly."))["issues"]}
