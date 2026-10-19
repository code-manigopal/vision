import asyncio
import io
import json

import httpx
from PIL import Image

from vision.services import visuals


def png(w=1000, h=800):
    b = io.BytesIO()
    Image.new("RGB", (w, h), "blue").save(b, "PNG")
    return b.getvalue()


def run(coro):
    return asyncio.run(coro)


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(visuals, "ROOT_DIR", tmp_path / "v")
    monkeypatch.setattr(visuals, "ICON_DIR", tmp_path / "icons")
    monkeypatch.setattr(visuals, "GAP", 0)


def nasa_handler(calls):
    def h(req):
        calls.append(str(req.url))
        u = req.url.path
        if u == "/search":
            items = [
                {"data": [{"nasa_id": "art", "media_type": "image", "title": "Artist concept of Ceres"}]},
                {"data": [{"nasa_id": "vid", "media_type": "video", "title": "Ceres global view video"}]},
                {"data": [{"nasa_id": "glob", "media_type": "image", "title": "Ceres global view"}]},
            ]
            return httpx.Response(200, json={"collection": {"items": items}})
        if u.startswith("/asset/"):
            n = u.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"collection": {"items": [{"href": f"https://x.test/{n}~thumb.jpg"}, {"href": f"https://x.test/{n}~large.jpg"}]}})
        if req.url.host == "x.test":
            calls.append("dl:" + u)
            return httpx.Response(200, content=png())
        return httpx.Response(404)
    return h


def test_nasa_picks_global_view_not_video_or_artist(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    calls = []

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(nasa_handler(calls))) as c:
            return await visuals.picture(c, "space", "Ceres")
    rec = run(go())
    assert rec["page"].endswith("/glob") and rec["source"] == "NASA" and rec["w"] == 1000
    assert not any("vid" in x for x in calls if x.startswith("dl:") or "/asset/" in x)


def test_cache_hit_makes_no_request(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    calls = []

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(nasa_handler(calls))) as c:
            a = await visuals.picture(c, "space", "Ceres")
            n = len(calls)
            b = await visuals.picture(c, "space", "ceres")
            return a, b, n
    a, b, n = run(go())
    assert a == b and len(calls) == n


def commons_handler(req):
    q = req.url.params
    if req.url.host == "up.test":
        return httpx.Response(200, content=png())
    if q.get("list") == "search":
        return httpx.Response(200, json={"query": {"search": [{"title": "File:Heart sa anatomy.png"}, {"title": "File:Heart anatomy.png"}]}})
    def page(t, lic):
        return {"title": t, "imageinfo": [{"thumburl": "https://up.test/" + t.split(":")[1].replace(" ", "_") + ".png", "descriptionurl": "https://commons/" + t,
                                           "extmetadata": {"LicenseShortName": {"value": lic}, "Artist": {"value": "<a href='x'>Ann</a>"}}}]}
    return httpx.Response(200, json={"query": {"pages": {"1": page("File:Heart sa anatomy.png", "CC BY-SA 4.0"), "2": page("File:Heart anatomy.png", "CC BY 4.0")}}})


def test_commons_drops_sa_keeps_by(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(commons_handler)) as c:
            return await visuals.picture(c, "body", "heart")
    rec = run(go())
    assert rec["license"] == "CC BY 4.0" and rec["credit"] == "Ann (Wikimedia Commons)" and "Heart anatomy" in rec["title"]
    assert "sa" not in rec["title"].lower().split()


def test_flag(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)

    def h(req):
        if req.url.host == "up.test":
            return httpx.Response(200, content=png(600, 400))
        return httpx.Response(200, json={"query": {"pages": {"1": {"title": "File:Flag of Japan.svg", "imageinfo": [{"thumburl": "https://up.test/j.png", "descriptionurl": "https://c/j",
                         "extmetadata": {"LicenseShortName": {"value": "Public domain"}}}]}}}})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as c:
            return await visuals.flag(c, "Japan")
    rec = run(go())
    assert rec and rec["license"] == "Public domain" and rec["w"] == 600


def test_icon_refuses_unknown(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)

    def h(req):
        return httpx.Response(200, content=b"<svg></svg>")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as c:
            return await visuals.icon(c, "not-an-icon"), await visuals.icon(c, "rocket")
    bad, ok = run(go())
    assert bad is None and ok.name == "rocket.svg" and ok.exists()


def test_a_main_body_gets_its_hand_picked_photo_first():
    assert visuals.curated("Jupiter's Great Red Spot") == "PIA02873" and visuals.curated("Ceres") is None
