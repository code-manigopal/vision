"""Map scene and the new channel kinds (space, body, geography): country aliases, the SVG, and the checks."""
import json

import pytest

from vision.masters import maps, scenes

POLY = lambda x, y: [[[x, y], [x + 10, y], [x + 10, y + 10], [x, y + 10], [x, y]]]
FAKE = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"NAME": "United States of America", "NAME_LONG": "United States", "ADMIN": "United States of America", "ISO_A3": "USA"},
     "geometry": {"type": "Polygon", "coordinates": POLY(-120, 30)}},
    {"type": "Feature", "properties": {"NAME": "Brazil", "NAME_LONG": "Brazil", "ADMIN": "Brazil", "ISO_A3": "BRA"},
     "geometry": {"type": "MultiPolygon", "coordinates": [POLY(-60, -20)]}},
    {"type": "Feature", "properties": {"NAME": "Peru", "NAME_LONG": "Peru", "ADMIN": "Peru", "ISO_A3": "PER"},
     "geometry": {"type": "Polygon", "coordinates": POLY(-80, -15)}},
    {"type": "Feature", "properties": {"NAME": "Antarctica", "NAME_LONG": "Antarctica", "ADMIN": "Antarctica", "ISO_A3": "ATA"},
     "geometry": {"type": "Polygon", "coordinates": POLY(0, -80)}},
]}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    p = tmp_path / "c.geojson"
    p.write_text(json.dumps(FAKE))
    monkeypatch.setattr(maps, "DATA", p)
    return p


def test_aliases_resolve(fake):
    assert maps.known("usa") == "United States of America" and maps.known("US") == "United States of America"
    assert maps.known("United States") == "United States of America" and maps.known("brazil") == "Brazil"
    assert maps.known("Atlantis") is None


def test_svg_marks_highlights_in_order(fake):
    s = maps.svg(["Peru", "Brazil"], 1000, 700)
    assert s.index('data-order="0"') < s.index('data-order="1"')
    assert s.count("land hl") == 2 and 'id="c-PER"' in s and "c-ATA" not in s
    assert 'id="c-ATA"' in maps.svg(["Antarctica"], 1000, 700)
    assert len(maps.viewbox(["Peru"], 1000, 700, True).split()) == 4 and maps.viewbox(["Peru"], 1000, 700, True) != maps.viewbox([], 1000, 700, False)


def test_missing_data_raises_and_check_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(maps, "DATA", tmp_path / "none.geojson")
    with pytest.raises(maps.MapDataMissing):
        maps.svg(["Peru"], 100, 100)
    assert scenes.check({"template": "map", "highlight": ["Peru"]}, "Peru is long.", {"geography"}) is None


def test_map_check(fake):
    line = "The Amazon crosses Brazil and Peru."
    ok = scenes.check({"template": "map", "highlight": ["brazil", "Peru"], "label": "Where the Amazon flows"}, line, {"geography"})
    assert ok and ok["highlight"] == ["Brazil", "Peru"]
    assert scenes.check({"template": "map", "highlight": ["Brazil", "United States"]}, line, {"geography"}) is None     # not named in the line
    assert scenes.check({"template": "map", "highlight": ["Narnia"]}, "Narnia is far.", {"geography"}) is None          # unknown country
    assert scenes.check({"template": "map", "highlight": ["usa"]}, "The USA is big.", {"geography"})["highlight"] == ["United States of America"]
    assert scenes.check({"template": "map", "highlight": ["Brazil"], "label": "In 1999 only"}, "Brazil.", {"geography"}) is None
    assert scenes.check({"template": "map", "highlight": ["Brazil"]}, "Brazil.", {"science"}) is None


def test_new_kinds_and_body_advice():
    assert set(scenes.TEMPLATES["space"]) == set(scenes.TEMPLATES["science"])
    assert {"compare", "flow", "cycle", "number", "myth", "checklist"} == set(scenes.TEMPLATES["body"])
    assert {"compare", "number", "flow", "map"} == set(scenes.TEMPLATES["geography"])
    assert scenes.check({"template": "checklist", "items": ["Take a magnesium supplement", "Sleep"]}, "x", {"body"}) is None
    assert scenes.check({"template": "flow", "steps": ["Food", "Stomach", "Intestine", "Blood"]}, "x", {"body"})
    assert scenes.check({"template": "myth", "myth": "We only use 10% of our brain", "fact": "We use virtually all of it"},
                        "People say we use 10% of the brain.", {"body"})
    assert scenes.check({"template": "flow", "steps": ["Rest", "Detox", "Heal"]}, "x", {"body"}) is None
    assert scenes.check({"template": "orbit", "center": "Earth", "body": "Moon"}, "x", {"space"})
