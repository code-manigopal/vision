"""NASA Image and Video Library footage: file choice, rights skip, used ids, errors (no network)."""

import asyncio

import httpx

from vision.services import nasa_media


def item(nid, kind="video", title="Saturn rings", desc="rings of saturn", **extra):
    return {"href": f"https://images-assets.nasa.gov/{kind}/{nid}/collection.json",
            "data": [{"nasa_id": nid, "media_type": kind, "title": title, "description": desc, "keywords": ["saturn"], **extra}]}


MANIFESTS = {
    "V1": ["http://images-assets.nasa.gov/video/V1/V1~orig.mp4", "http://images-assets.nasa.gov/video/V1/V1~mobile.mp4", "http://images-assets.nasa.gov/video/V1/V1~thumb.jpg"],
    "I1": ["https://images-assets.nasa.gov/image/I1/I1~orig.jpg", "https://images-assets.nasa.gov/image/I1/I1~large.jpg"],
    "G1": ["https://images-assets.nasa.gov/image/G1/G1~large.jpg"],
}


def run(items, status=200):
    def handler(req):
        if status != 200:
            return httpx.Response(status)
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"collection": {"items": items}})
        nid = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"collection": {"items": [{"href": h} for h in MANIFESTS.get(nid, [])]}})

    async def go(fn):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fn(c)
    return go


def test_video_prefers_mobile_https():
    hits = asyncio.run(run([item("V1")])(lambda c: nasa_media.search(c, "saturn rings")))
    assert len(hits) == 1 and hits[0]["url"] == "https://images-assets.nasa.gov/video/V1/V1~mobile.mp4"
    assert hits[0]["id"] == "nasa-V1" and hits[0]["kind"] == "video" and hits[0]["page"].endswith("/details/V1") and hits[0]["credit"] == "NASA"


def test_image_prefers_large():
    hits = asyncio.run(run([item("I1", "image")])(lambda c: nasa_media.search(c, "saturn")))
    assert hits[0]["kind"] == "photo" and hits[0]["url"].endswith("I1~large.jpg")


def test_third_party_skipped():
    hits = asyncio.run(run([item("G1", "image", desc="© Getty Images")])(lambda c: nasa_media.search(c, "saturn")))
    assert hits == []


def test_used_is_honoured():
    go = run([item("V1"), item("I1", "image")])
    used = {"nasa-V1"}
    hit = asyncio.run(go(lambda c: nasa_media.find(c, "saturn rings", used)))
    assert hit["id"] == "nasa-I1" and "nasa-I1" in used
    assert asyncio.run(go(lambda c: nasa_media.find(c, "saturn rings", used))) is None


def test_error_gives_none():
    go = run([], status=500)
    assert asyncio.run(go(lambda c: nasa_media.search(c, "x"))) == []
    assert asyncio.run(go(lambda c: nasa_media.find(c, "x", set()))) is None
