"""Animated slides (HyperFrames): the page is built from the deck alone, a count-up ends on the deck's own figure, and any
render trouble leaves the video as it was (still pictures)."""
import json
import re
from pathlib import Path

from vision.masters import slides, slides_motion
from vision.services import hyperframes

DECK = [{"kind": "notice", "title": "", "items": ["Disclaimer: educational only.", "மறுப்பு."]},
        {"kind": "table", "title": "Q2 FY27 · Numbers", "cols": ["Q2 FY26", "Q2 FY27", "YoY"], "items": [
            {"key": "revenue", "label": "Revenue [₹ கோடி]", "was": "65,799", "now": "73,188", "change": "▲ 11.2%", "tone": "good", "note": "Q1 FY27: 72,275"},
            {"key": "opm", "label": "Operating margin [%]", "was": "27.3%", "now": "25.7%", "change": "▼ 1.6 pts", "tone": "bad", "note": ""},
            {"key": "profit", "label": "Net Profit [₹ கோடி]", "was": "—", "now": "n/a", "change": "", "tone": "flat", "note": ""}]},
        {"kind": "points", "title": "ஆக மொத்தம்", "items": [{"icon": "up", "text": "Revenue", "tone": "good"}], "note": "Company report numbers only"}]
LINES = [{"slide": 0, "show": 1, "say": "a", "hold": 6}, {"slide": 1, "show": 1, "say": "b"}, {"slide": 1, "show": 2, "say": "c"},
         {"slide": 1, "show": 3, "say": "d"}, {"slide": 2, "show": 2, "say": "e"}]


def test_count_up_steps_end_on_the_deck_text_and_keep_its_format():
    s = slides_motion.steps("65,799", "73,188")
    assert s[-1] == "73,188" and len(set(s)) == len(s) and all(re.fullmatch(r"\d{2},\d{3}", x) for x in s)
    assert all(65799 < int(x.replace(",", "")) <= 73188 for x in s)
    assert slides_motion.steps("27.3%", "25.7%")[-1] == "25.7%" and all(x.endswith("%") for x in slides_motion.steps("27.3%", "25.7%"))
    assert slides_motion.steps("1,23,456", "1,45,000")[-2:] == ["1,44,996", "1,45,000"]          # Indian grouping kept
    assert slides_motion.steps(None, "₹38.37")[-1] == "₹38.37" and slides_motion.steps("—", "n/a") == []


def test_the_page_shows_only_the_decks_figures_at_the_end_of_every_count():
    html = slides_motion.build(DECK, LINES, [6.0, 4.0, 3.0, 3.0, 4.0], channel="Mani Market Tamil", source="Source: NSE")
    assert 'data-duration="20.00"' in html and 'src="assets/gsap.min.js"' in html and "https://" not in html      # nothing from the internet
    sets = re.findall(r'tl\.set\("([^"]+)", \{textContent: "([^"]*)"\}, ([\d.]+)\);', html)
    last = {}
    for sel, text, t in sets:
        last[sel] = max(last.get(sel, (0, "")), (float(t), text))
    assert sorted(v[1] for v in last.values()) == ["25.7%", "73,188"]                              # "n/a" is shown as it is, never counted
    assert html.count('class="slide clip"') == 3 and "Disclaimer: educational only." in html
    notice = re.search(r'<section class="slide clip" id="s0".*?</section>', html, re.S).group(0)
    assert "bars" not in notice and 'id="s0b' not in html                                         # the disclaimer stays still
    assert 'id="s1b0"' in html and 'id="s1b2"' not in html                                       # bars only for rows with two figures


def test_a_failed_render_leaves_the_still_pictures(tmp_path, monkeypatch):
    calls = []

    def fail(*a, **k):
        raise hyperframes.RenderFailed("no node")

    monkeypatch.setattr(slides_motion, "render", fail)
    monkeypatch.setattr(slides, "probe", lambda p: 2.0)
    monkeypatch.setattr(slides, "run", lambda args: calls.append(args))
    pngs = [tmp_path / f"s{i}.png" for i in range(len(LINES))]
    slides.assemble(tmp_path, pngs, LINES, [tmp_path / "a.mp3"] * len(LINES), tmp_path / "final.mp4", motion={"deck": DECK, "channel": "x"})
    final = calls[-1]
    assert sum(1 for x in final if str(x).endswith(".png")) == len(LINES) and any("xfade" in str(x) for x in final)


def test_a_good_render_replaces_the_pictures(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(slides_motion, "render", lambda deck, lines, secs, out, **k: out)
    monkeypatch.setattr(slides, "probe", lambda p: 2.0)
    monkeypatch.setattr(slides, "run", lambda args: calls.append(args))
    slides.assemble(tmp_path, [tmp_path / "s.png"] * len(LINES), LINES, [tmp_path / "a.mp3"] * len(LINES), tmp_path / "final.mp4", motion={"deck": DECK})
    final = calls[-1]
    assert not any(str(x).endswith(".png") for x in final) and str(tmp_path / "motion.mp4") in final and f"{1}:a" in final


def test_render_refuses_without_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(hyperframes, "ready", lambda: False)
    try:
        hyperframes.render("<html></html>", tmp_path / "x.mp4")
    except hyperframes.RenderFailed as e:
        assert "not set up" in str(e)
    else:
        raise AssertionError("should refuse")


def test_the_presenter_is_in_the_page_with_his_mouth_on_the_voice_and_his_gestures(tmp_path):
    faces = {(m, e): tmp_path / f"f{m}{e}.png" for m in range(3) for e in range(2)}
    html = slides_motion.build(DECK, LINES, [6.0, 4.0, 3.0, 3.0, 4.0], channel="M", faces=faces, states=[0, 0, 1, 2, 2, 0])
    assert html.count('<img id="fc') == 6 and 'tl.set("#fc10", {opacity: 1}, 0.167);' in html and 'tl.set("#fc20", {opacity: 1}, 0.250);' in html
    assert html.count("point(") >= 3 and "rotation: -6" in html and "y: -14" in html          # points at rows; tilts at a bad figure, bounces at a good one
    assert 'id="pres" style="left:1580px;top:780px"' in html
