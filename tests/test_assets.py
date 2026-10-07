"""Caption fonts and sound effects: downloads, the caption looks by mood, and the sfx library (HTTP mocked)."""

import asyncio
import re

import httpx

from vision.services import fonts, sfx


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_fonts_fetch_saves_missing_skips_present_and_survives_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts, "DIR", tmp_path)
    bad, have = fonts.FONTS[0], fonts.FONTS[1]
    (tmp_path / have["file"]).write_bytes(b"old")
    calls = []

    def handler(req):
        calls.append(str(req.url))
        if str(req.url) == bad["url"]:
            return httpx.Response(404)
        return httpx.Response(200, content=b"f" * 10_000)

    saved = asyncio.run(fonts.fetch(_client(handler)))
    assert bad["name"] not in saved and have["name"] not in saved and len(saved) == len(fonts.FONTS) - 2
    assert have["url"] not in calls and (tmp_path / have["file"]).read_bytes() == b"old" and not (tmp_path / bad["file"]).exists()
    assert asyncio.run(fonts.fetch(_client(handler))) == []        # the failed one is retried: still 404, nothing new
    assert fonts.path(have["name"]) == str(tmp_path / have["file"]) and fonts.path(bad["name"]) is None and fonts.path("nope") is None


def test_style_for_precedence_rotation_fallback_and_font_path(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts, "DIR", tmp_path)
    s = fonts.style_for("dark", "money")
    assert s["font_name"] in {x["font"] for x in fonts.STYLES["money"]} and s["stroke"] == "#000000" and s["position"] == "center"
    assert s["font"] is None                                          # not on disk
    n = len(fonts.STYLES["dark"])
    assert fonts.style_for("dark", turn=0) != fonts.style_for("dark", turn=1) and fonts.style_for("dark", turn=n) == fonts.style_for("dark", turn=0)
    assert fonts.style_for("weird")["fill"] in {x["fill"] for x in fonts.DEFAULT} and fonts.style_for("")["font_name"] == fonts.DEFAULT[0]["font"]
    assert fonts.style_for("", "unknown-kind")["font_name"] == fonts.DEFAULT[0]["font"]
    f = next(x for x in fonts.FONTS if x["name"] == fonts.STYLES["sad"][0]["font"])
    (tmp_path / f["file"]).write_bytes(b"x")
    assert fonts.style_for("sad")["font"] == str(tmp_path / f["file"])


def test_styles_are_well_formed():
    names = {f["name"] for f in fonts.FONTS}
    assert len(fonts.FONTS) == 10 and len(names) == 10 and all(f["url"].startswith("https://github.com/google/fonts/raw/main/") for f in fonts.FONTS)
    assert {"dark", "sad", "warm", "light", "dramatic", "money", "science"} <= set(fonts.STYLES)
    looks = [x for v in [*fonts.STYLES.values(), fonts.DEFAULT] for x in v]
    assert {x["font"] for x in looks} == names                        # every font is used
    for x in looks:
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", x["fill"]) and re.fullmatch(r"#[0-9A-Fa-f]{6}", x["highlight"]) and x["fill"] != x["highlight"]
    assert all(2 <= len(v) <= 4 for v in fonts.STYLES.values())


def test_sfx_fetch_filters_licence_duration_and_known_ids_and_pick_rotates(tmp_path, monkeypatch):
    monkeypatch.setattr(sfx, "DIR", tmp_path)
    monkeypatch.setattr(sfx, "probe", lambda p: 0.0 if p.read_bytes() == b"bad" else 1.0)
    hit = lambda i, ms, **kw: {"id": i, "title": f"S{i}", "creator": "C", "license": "cc0", "license_version": "1.0", "duration": ms,
                               "url": f"https://audio.test/{i}.mp3", "foreign_landing_url": f"https://page.test/{i}", **kw}
    results = [hit("a", 1000), hit("short", 100), hit("long", 5000), hit("nourl", 1000, url=None), hit("bad", 800), hit("b", 900), hit("c", 2000)]
    seen = []

    def handler(req):
        if "openverse" in str(req.url):
            seen.append(dict(req.url.params))
            return httpx.Response(200, json={"results": results})
        return httpx.Response(200, content=b"bad" if "bad" in str(req.url) else b"sound")

    saved = asyncio.run(sfx.fetch("whoosh", 5, _client(handler)))
    assert all(p["license"] == "cc0,pdm" for p in seen)
    assert [c["title"] for c in saved] == ["Sa", "Sb", "Sc"]          # too short, too long, no url and undecodable files are left out
    assert saved[0]["license"] == "CC0 1.0" and saved[0]["seconds"] == 1.0 and not list(tmp_path.glob("whoosh/*bad*"))
    assert asyncio.run(sfx.fetch("whoosh", 5, _client(handler))) == []     # already in the library
    assert [c["title"] for c in asyncio.run(sfx.fetch("riser", 1, _client(handler)))] == ["Sa"]
    assert [c["title"] for c in asyncio.run(sfx.fetch("riser", 5, _client(handler)))] == ["Slong", "Sb", "Sc"]   # a riser may run to 6 s
    a, b, c = sfx.tracks("whoosh")
    assert [sfx.pick("whoosh", t) for t in (0, 1, 2, 3)] == [a, b, c, a] and sfx.pick("ding") is None
