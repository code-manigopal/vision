import asyncio
import io
import json
from pathlib import Path

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


def test_a_title_that_only_resembles_the_subject_is_refused():
    assert visuals.score("HALO fabrication - 2022", "fabric") is None                       # whole words only
    assert visuals.score("Liquid oxygen tank installed at A-3 Test Stand", "oxygen tank") is None
    assert visuals.score("NASA insignia on the hangar", "hangar") is None                    # a logo for a thing
    assert visuals.score("Saturn true color", "Saturn") is not None
    assert visuals.score("Rocky Mountains", "mountain") is not None                          # a plural still counts


def test_a_picture_the_judge_refuses_is_dropped_and_a_yes_is_remembered(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    seen = []

    async def no(rec, subject):
        seen.append(rec["path"])
        return False

    async def yes(rec, subject):
        seen.append(rec["path"])
        return True
    c = httpx.AsyncClient(transport=httpx.MockTransport(nasa_handler([])))
    assert run(visuals.picture(c, "space", "Ceres", judge=no)) is None and not Path(seen[0]).exists()     # the only candidate refused: no picture
    setup(tmp_path / "again", monkeypatch)
    rec = run(visuals.picture(c, "space", "Ceres", judge=yes))
    assert rec["checked"] is True
    assert run(visuals.picture(c, "space", "Ceres", judge=no)) == rec and len(seen) == 2                 # checked once: not looked at again


def test_a_place_is_a_real_photo_never_a_map_or_flag():
    assert visuals.title_score("File:Kolyma-river 01.jpg", "Kolyma River", "geography") is not None
    assert visuals.title_score("File:MapOfOymyakonRussia.png", "Oymyakon", "geography") is None
    assert visuals.title_score("File:Oymyakon map.jpg", "Oymyakon", "geography") is None
    assert visuals.title_score("File:Oymyakon banner Warmly dressed person.jpg", "Oymyakon", "geography") is None


def test_cfai_look_uses_workers_ai_own_endpoint(monkeypatch, tmp_path):
    from vision.services import cfai

    class Kv(dict):
        def kv_get(self, ns, k, default=None):
            return self.get((ns, k), default)

        def kv_put(self, ns, k, v):
            self[(ns, k)] = v
    monkeypatch.setattr(cfai, "secret", lambda n: "x")
    sent = []

    def h(req):
        sent.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"result": {"response": "YES, Saturn.", "usage": {"neurons": 15.5}}})
    out = run(cfai.look(Kv(), png(), "Is it Saturn?", client=httpx.AsyncClient(transport=httpx.MockTransport(h))))
    assert out == "YES, Saturn." and sent[0][0].endswith("/run/" + cfai.LOOK)
    assert sent[0][1]["prompt"] == "Is it Saturn?" and isinstance(sent[0][1]["image"], list)


def test_a_black_and_white_photo_of_a_place_is_refused():
    grey, colour = io.BytesIO(), io.BytesIO()
    Image.new("RGB", (800, 800), (120, 120, 120)).save(grey, "JPEG")
    Image.new("RGB", (800, 800), (40, 120, 200)).save(colour, "JPEG")
    assert visuals.colourless(grey.getvalue()) and not visuals.colourless(colour.getvalue())
    assert visuals.title_score("File:Rhine Crossing - US Navy ferrying troops across the Rhine River.jpg", "Rhine River", "geography") is None
