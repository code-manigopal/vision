"""Mani Market Tamil's covers and titles: the hook from a video's own figures (never advice or a promise), the Commons logo rules (Commons API mocked), the credit."""

import asyncio
import json

import httpx
import pytest

from vision.masters import market, market_crew, slides, thumbs, youtube
from vision.services import logos


def result(profit=(115.2, 100.0), margin=(24.0, 25.0), shape=None):
    rows = [{"key": "profit", "now": profit[0], "year": profit[1], "unit": "cr"}, {"key": "opm", "now": margin[0], "year": margin[1], "unit": "pct"}]
    return {"name": "Tata Consultancy Services Limited", "quarter": "Q2 FY27", "rows": rows, **(shape or {})}


def safe(text):
    return text and not market.ADVICE.search(text) and not market.FORECAST.search(text) and not market.RUDE.search(text) and not youtube.promises(text)


def test_a_results_hook_states_what_the_filed_profit_did_and_the_title_asks_about_a_falling_margin():
    assert thumbs.result_hook(result()) == ("Profit 15% ஏறிருக்கு!", "good")
    assert thumbs.result_hook(result(profit=(95.3, 100.0))) == ("Profit 4.7% இறங்கிருக்கு", "bad")
    assert thumbs.result_hook(result(profit=(100.0, 100.0))) == ("Profit அதே அளவு", "flat")
    assert thumbs.result_hook({"name": "X", "quarter": "Q1 FY27", "rows": []}) == ("", "flat")             # no comparison, no hook
    assert thumbs.result_title(result()) == "Tata Consultancy Services Q2 FY27 Results | Profit 15% ஏறிருக்கு, Margin ஏன் இறங்குச்சு? | தமிழில்"
    assert "Margin" not in thumbs.result_title(result(margin=(26.0, 25.0))) and "Margin" not in thumbs.result_title(result(profit=(90.0, 100.0)))
    long = {**result(), "name": "ICICI Prudential Life Insurance Company Limited"}
    assert len(thumbs.result_title(long)) <= 100 and "Margin" not in thumbs.result_title(long)                  # too long with the question: without it
    assert thumbs.result_title({"name": "X", "quarter": "Q1 FY27", "rows": []}) == ""


def test_a_bank_or_insurer_without_a_profit_row_uses_its_headline_figure():
    r = {"name": "X Bank", "quarter": "Q2 FY27", "bank": True, "rows": [{"key": "nii", "now": 130.0, "year": 100.0, "unit": "cr"}]}
    assert thumbs.result_hook(r) == ("NII 30% ஏறிருக்கு!", "good")


def test_an_analysis_hook_asks_about_the_ratio_it_has_and_a_lesson_hook_asks_about_its_subject():
    rows = [{"key": "de", "label": "Debt to equity", "value": 0.4, "unit": "x"}, {"key": "roe", "label": "ROE", "value": 18.24, "unit": "pct"}]
    assert thumbs.analysis_hook(rows) == ("ROE 18.2% எப்படி?", "flat") and thumbs.analysis_hook(rows[:1]) == ("Debt-equity 0.4x எப்படி?", "flat")
    assert thumbs.analysis_hook([]) == ("", "flat")
    assert thumbs.analysis_title({"name": "ITC Limited"}, rows) == "ITC Fundamental Analysis | ROE 18.2% எப்படி? | தமிழில்"
    assert thumbs.lesson_hook("Fixed deposit vs recurring deposit") == ("FD vs RD: எது?", "flat")
    assert thumbs.lesson_hook("What is a mutual fund?") == ("Mutual fund: தெரியுமா?", "flat")
    assert thumbs.lesson_hook("How a bank fixed deposit works")[0] == "Bank fixed deposit: தெரியுமா?"
    assert thumbs.hook_for({"kind": "lesson", "tp": {"title": "Fixed deposit vs recurring deposit"}})[0] == "FD vs RD: எது?"
    assert thumbs.hook_for({"kind": "analysis", "ratios": rows})[0].startswith("ROE") and thumbs.hook_for({"kind": "result", "result": result()})[0].startswith("Profit")


def test_every_hook_and_title_is_free_of_advice_forecasts_and_promises(monkeypatch):
    seen = [thumbs.result_hook(result(p, m))[0] for p in ((130, 100), (70, 100), (100, 100)) for m in ((24, 25), (26, 25))] + [thumbs.analysis_hook([{"key": k, "label": k, "value": 9.0, "unit": u}])[0]
            for k, u in (("roe", "pct"), ("roce", "pct"), ("npm", "pct"), ("de", "x"), ("bv", "rs"))]
    from vision.masters import lessons
    seen += [thumbs.lesson_hook(t["title"])[0] for t in lessons.TOPICS]
    titles = [thumbs.result_title(result(p, m)) for p in ((130, 100), (70, 100)) for m in ((24, 25), (26, 25))]
    assert all(safe(h) for h in seen) and all(safe(t) and len(t) <= 100 for t in titles)
    assert all(2 <= len(h.split()) <= 6 for h in seen)
    assert thumbs.clean("Buy this stock now | தமிழில்") == "" and thumbs.clean("Profit 15% ஏறும்; will rise") == "" and thumbs.clean("Get rich in 3 days") == ""      # the guard itself
    assert thumbs.clean("Can you get rich in 3 days?") == "Can you get rich in 3 days?" and thumbs.clean("x" * 101) == ""


def test_the_thumbnail_page_is_the_channels_slide_look_with_the_hook_the_logo_and_the_presenter(tmp_path):
    logo = tmp_path / "L.svg"
    logo.write_text("<svg/>")
    page = slides.thumb_page("Profit 15% ஏறிருக்கு!", "Tata Consultancy Services", str(logo), "Mani Market Tamil", "Q2 FY27 RESULTS", "good")
    assert "Baloo Thambi 2" in page and "#14532d" in page and '<b class="good">15%</b>' in page and logo.as_uri() in page and "Mani Market Tamil" in page and "<svg viewBox=\"0 0 300 300\"" in page
    assert 'class="logo"' not in slides.thumb_page("Profit அதே அளவு", "X") and "<img" not in slides.thumb_page("Profit அதே அளவு", "X")      # no logo: the name in text only
    assert "Company</div>" not in slides.thumb_page("h", "ICICI Prudential Life Insurance Company")


@pytest.mark.parametrize("title,ok", [
    ("File:HDFC Bank Logo.svg", True), ("File:HDFC-Bank-Logo.svg", True), ("File:TATA Consultancy Services Logo.png", True),
    ("File:Tata Consultancy Services old logo.svg", False),            # an old logo is not used
    ("File:TCS Logo.svg", False),                                      # the company's name is not in the title
    ("File:HDFC Bank branch.svg", False), ("File:HDFC Bank Logo.jpg", False), ("File:HDFC Bank Logo.gif", False),
    ("File:HDB Financial Services logo.svg", False), ("File:Tata Consultancy Services Logo 2014.svg", False)])
def test_a_commons_file_is_accepted_only_when_its_title_has_the_name_and_logo_in_svg_or_png(title, ok):
    name = "Tata Consultancy Services" if "Tata" in title.title() or "TATA" in title else "HDFC Bank"
    assert logos.accept(title, name) is ok
    assert logos.accept("File:Tata Consultancy Services Logo.svg", "Tata Consultancy Services Limited") and logos.rank(["File:A Logo.png", "File:A Logo.svg"])[0].endswith(".svg")


def commons(calls, mime="image/svg+xml", size=500, search=("File:Sample old logo.svg", "File:Sample Logo.png", "File:Sample Logo.svg", "File:Unrelated.svg")):
    def handler(req):
        calls.append(str(req.url))
        assert "VISION" in req.headers["User-Agent"]
        if "commons.wikimedia.org" in str(req.url) and req.url.params.get("list") == "search":
            assert req.url.params["srsearch"] == "Sample logo" and req.url.params["srnamespace"] == "6"
            return httpx.Response(200, json={"query": {"search": [{"title": t} for t in search]}})
        if "commons.wikimedia.org" in str(req.url):
            assert "File:Sample old logo.svg" not in req.url.params["titles"] and "File:Unrelated.svg" not in req.url.params["titles"]
            ok = {"File:Sample Logo.svg": ("image/svg+xml", size), "File:Sample Logo.png": ("image/png", size)}
            return httpx.Response(200, json={"query": {"pages": {str(n): {"title": t, "imageinfo": [{
                "url": f"https://upload.wikimedia.org/{t[5:].replace(' ', '_')}", "descriptionurl": "https://commons.wikimedia.org/wiki/" + t.replace(" ", "_"), "mime": ok[t][0], "size": ok[t][1],
                "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": '<a href="x">Jane &amp; Co</a>'}}}]} for n, t in enumerate(req.url.params["titles"].split("|"))}}})
        return httpx.Response(200, content=b"<svg/>" if "Logo.svg" in str(req.url) else b"\x89PNG")
    return handler


def run_find(tmp_path, handler, name="Sample", symbol="SAMPLE"):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await logos.find(c, symbol, name, tmp_path, gap=0, sleep=lambda s: asyncio.sleep(0))
    return asyncio.run(go())


def test_the_logo_is_fetched_once_cached_with_its_licence_and_never_downloaded_again(tmp_path):
    calls = []
    got = run_find(tmp_path, commons(calls))
    assert got["title"] == "File:Sample Logo.svg" and got["path"].endswith("SAMPLE.svg") and (tmp_path / "SAMPLE.svg").read_bytes() == b"<svg/>"          # SVG before PNG
    meta = json.loads((tmp_path / "SAMPLE.json").read_text())
    assert meta["licence"] == "CC BY-SA 4.0" and meta["artist"] == "Jane & Co" and meta["source"] == "https://commons.wikimedia.org/wiki/File:Sample_Logo.svg"
    assert logos.credit(got) == "Logo: https://commons.wikimedia.org/wiki/File:Sample_Logo.svg (CC BY-SA 4.0)" and logos.credit(None) == ""
    n = len(calls)
    again = run_find(tmp_path, commons(calls))
    assert len(calls) == n and again["path"] == got["path"]                           # no request the second time


def test_no_accepted_file_or_a_failing_api_gives_no_logo_and_the_search_is_not_repeated(tmp_path):
    calls = []
    assert run_find(tmp_path, commons(calls, search=("File:Sample old logo.svg", "File:Unrelated.svg"))) is None
    n = len(calls)
    assert run_find(tmp_path, commons(calls)) is None and len(calls) == n and json.loads((tmp_path / "SAMPLE.json").read_text())["none"] is True      # remembered for 30 days
    assert logos.cached("SAMPLE", tmp_path) == {}
    assert run_find(tmp_path / "x", lambda req: httpx.Response(403, text="robot policy"), symbol="OTHER") is None and logos.cached("OTHER", tmp_path / "x") is None      # an error is not remembered
    assert run_find(tmp_path / "y", commons([], size=9 << 20), symbol="BIG") is None                                    # a file over 3 MB is not used


def test_the_description_credits_the_logo_before_the_disclaimer():
    r = {"name": "Sample Limited", "quarter": "Q2 FY27", "source": "https://nse.test/f.xml"}
    text = market_crew.SlideEditor.result_summary(r, ["#SAMPLE"], [], [], "Logo: https://commons.wikimedia.org/wiki/File:Sample_Logo.svg (Public domain)")
    assert text.endswith("Logo: https://commons.wikimedia.org/wiki/File:Sample_Logo.svg (Public domain)\n" + market_crew.DISCLAIMER)
    assert "Logo:" not in market_crew.SlideEditor.result_summary(r, ["#SAMPLE"], [], [])
    f = {"name": "Sample Limited", "sources": ["https://nse.test/a.xml"]}
    assert market_crew.SlideEditor.analysis_summary(f, None, ["#S"], "Logo: https://c.test/x (CC0)").count("Logo: https://c.test/x (CC0)") == 1


def test_the_existing_titles_remain_when_there_are_no_figures_to_make_a_hook_from():
    t = market_crew.SlideEditor.title
    assert t({"name": "X Limited", "quarter": "Q2 FY27", "bank": False}) == "X Q2 FY27 Results தமிழில் | Revenue, Profit, Margin என்ன சொல்லுது?"
    assert market_crew.SlideEditor.analysis_title({"name": "X Limited"}) == "X Fundamental Analysis தமிழில் | ROE, Debt, Margin என்ன சொல்லுது?"
