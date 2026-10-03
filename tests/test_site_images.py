import asyncio

import httpx

from vision.masters import site_images as si

ROOFER = {"id": "1", "name": "Top Roofing", "type": "roofing_contractor", "type_label": "Roofing contractor", "address": "1 Main St, Windsor"}


def photo(n, alt, w=1920, h=1080, who="Sam", slug=None):
    return {"id": n, "width": w, "height": h, "photographer": who, "alt": alt, "url": f"https://www.pexels.com/photo/{slug or 'x'}-{n}/",
            "src": {"large2x": f"https://img/p{n}.jpg", "original": f"https://img/p{n}o.jpg"}}


PEXELS = [photo(1, "Aerial view of a house roof with new shingles", who="A"), photo(2, "Roofer installing shingles on a roof", 1600, 1200, "B"),
          photo(3, "Gas station at night", who="C"), photo(4, "Woman packing boxes", who="D"),
          photo(5, "Roof illustration with watermark", who="E"), photo(6, "Close up of roof shingles", 1400, 900, "F")]


def run(handler, lead=ROOFER, brief=None, want=6, **kw):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await si.pick_images(c, lead, brief, want, **kw)
    return asyncio.run(go())


def keys(monkeypatch, pexels="k", pixabay="k"):
    for n, v in (("PEXELS_API_KEY", pexels), ("PIXABAY_API_KEY", pixabay)):
        if v:
            monkeypatch.setenv(n, v)
        else:
            monkeypatch.delenv(n, raising=False)


def pexels_only(req):
    if "pexels" in req.url.host:
        return httpx.Response(200, json={"photos": PEXELS})
    return httpx.Response(200, json={})


def test_roofing_filters_junk_and_assigns_roles(monkeypatch):
    keys(monkeypatch, pixabay=None)
    out = run(pexels_only)
    urls = [i["url"] for i in out]
    assert set(urls) == {"https://img/p1.jpg", "https://img/p2.jpg", "https://img/p6.jpg"}
    assert out[0]["role"] == "hero" and out[0]["url"] == "https://img/p1.jpg"
    assert out[1]["role"] == "about" and out[1]["url"] == "https://img/p2.jpg"
    assert out[2]["role"] == "gallery"
    assert all(i["credit"].endswith("(Pexels)") and i["credit"].startswith("Photo by ") for i in out)
    assert len(out) < 6


def test_fallback_to_pixabay_then_openverse(monkeypatch):
    keys(monkeypatch)

    def h(req):
        if "pexels" in req.url.host:
            return httpx.Response(200, json={"photos": [photo(3, "Gas station at night")]})
        if "pixabay" in req.url.host:
            return httpx.Response(200, json={"hits": [{"tags": "roof, roofer, ladder", "user": "Pat", "pageURL": "u", "largeImageURL": "https://pix/1.jpg",
                                                      "imageWidth": 2000, "imageHeight": 1200}]})
        return httpx.Response(200, json={"results": [{"title": "Shingle roof", "tags": [{"name": "roof"}], "creator": "Lee", "license": "by", "license_version": "2.0",
                                                     "foreign_landing_url": "f", "url": "https://ov/1.jpg", "width": 2000, "height": 1000}]})
    out = run(h)
    assert {i["provider"] for i in out} == {"Pixabay", "Openverse"}
    credits = {i["url"]: i["credit"] for i in out}
    assert credits["https://pix/1.jpg"] == "Photo by Pat (Pixabay)"
    assert credits["https://ov/1.jpg"] == "Shingle roof by Lee (BY 2.0)"


def test_openverse_only_without_keys(monkeypatch):
    keys(monkeypatch, None, None)
    seen = []

    def h(req):
        seen.append(req.url.host)
        return httpx.Response(200, json={"results": [{"title": "Roof", "tags": [], "creator": "Lee", "license": "cc0", "license_version": "1.0", "url": "https://ov/2.jpg", "width": 1500, "height": 900}]})
    out = run(h)
    assert set(seen) == {"api.openverse.org"} and out and out[0]["credit"] == "Roof by Lee (CC0 1.0)"


def test_total_failure_returns_empty(monkeypatch):
    keys(monkeypatch)
    assert run(lambda r: httpx.Response(500)) == []

    def boom(r):
        raise httpx.ConnectError("x")
    assert run(boom) == []


def test_unknown_type_uses_label_phrases(monkeypatch):
    keys(monkeypatch, pixabay=None)
    qs = []

    def h(req):
        qs.append(req.url.params["query"])
        return httpx.Response(200, json={"photos": [photo(9, "Chimney sweep cleaning a chimney")]})
    lead = {"id": "2", "name": "Sweep", "type": "chimney_sweep", "type_label": "Chimney sweep", "address": "x"}
    out = run(h, lead=lead)
    assert "chimney sweep" in qs and "chimney sweep at work" in qs
    assert out and out[0]["url"] == "https://img/p9.jpg"


def test_people_trade_accepts_portrait(monkeypatch):
    keys(monkeypatch, pixabay=None)
    p = [photo(1, "Smiling portrait of a barber with scissors", 1800, 1200)]
    h = lambda r: httpx.Response(200, json={"photos": p}) if "pexels" in r.url.host else httpx.Response(200, json={})
    barber = {"id": "3", "name": "B", "type": "barber_shop", "type_label": "Barber shop", "address": "x"}
    assert run(h, lead=barber)
    assert si.score_text("Smiling portrait of a roofer on a roof", "roofing_contractor", "roofer") < si.score_text("Roofer on a roof", "roofing_contractor", "roofer")


def test_deterministic(monkeypatch):
    keys(monkeypatch, pixabay=None)
    assert run(pexels_only) == run(pexels_only)


def test_empty_alt_uses_url_slug(monkeypatch):
    keys(monkeypatch, pixabay=None)
    p = [photo(7, "", slug="roofer-working-on-roof")]
    h = lambda r: httpx.Response(200, json={"photos": p}) if "pexels" in r.url.host else httpx.Response(200, json={})
    assert [i["url"] for i in run(h)] == ["https://img/p7.jpg"]


def test_alt_clean_and_no_creator(monkeypatch):
    keys(monkeypatch, pixabay=None)
    p = [photo(8, "Roofer by Sam Smith on roof", who="Sam Smith")]
    h = lambda r: httpx.Response(200, json={"photos": p}) if "pexels" in r.url.host else httpx.Response(200, json={})
    out = run(h)
    assert out and "Sam" not in out[0]["alt"] and len(out[0]["alt"]) <= 110


def test_score_text_cases():
    s = si.score_text
    assert s("Roofer installing shingles on a roof", "roofing_contractor", "roofer installing shingles") > 4
    assert s("Gas station at night", "roofing_contractor", "roof") is None
    assert s("Beautiful sunset over the sea", "roofing_contractor", "roof") is None
    assert s("Roof vector illustration", "roofing_contractor", "roof") is None
    assert s("Roof with watermark", "roofing_contractor", "roof") is None
    assert s("Roofs", "roofing_contractor", "roof") is not None       # plural stripping
    assert s("Kitchen roof", "roofing_contractor", "roof") is None     # trade reject term
    assert s("", "plumber", "pipe") is None


def test_every_more_type_has_trade():
    from vision.masters import web
    missing = [t for t in web.MORE_TYPES if t not in si.TRADE]
    assert not missing
    assert len(si.TRADE) >= 35
    for t in list(web.KEYWORDS):
        assert t in si.TRADE
    assert all(4 <= len(v["queries"]) <= 6 and v["relevant"] for v in si.TRADE.values())
