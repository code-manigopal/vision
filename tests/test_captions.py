"""Mani Market Tamil: the English captions (written by code beside each Tamil line, cut into chunks, timed to the audio, laid over the video) and the
two sign-off lines. No network, no browser; ffmpeg is real."""

import asyncio
import re
import subprocess

import pytest
from PIL import Image
from test_market import PRICE, bank_fund, fund, result
from test_market_backing import GOOD_MARGIN, GOOD_OUT, GOOD_REV, run
from test_market_report import SHAPES, data_for

from vision.masters import fundamentals, market, market_crew, slides, youtube
from vision.masters.tamil_say import voiced
from vision.voice import clone

NEWS = [{"title": "Sample Q2 results: net profit rises 6% to Rs 1,800 crore", "source": "The Mint", "link": "l", "at": "2026-10-08", "gist": "ஸாம்பிள் ப்ராஃபிட் ஏறிருக்கு."},
        {"title": "Sample wins a cloud deal", "source": "ET", "link": "l", "at": "2026-10-09", "gist": ""}]


def bank_result():
    r = result()
    row = lambda key, label, unit, now, prev, year, low=False: {"key": key, "label": label, "unit": unit, "now": now, "prev": prev, "year": year, "lower_is_better": low}      # noqa: E731
    return {**r, "bank": True, "name": "Sample Bank Limited", "rows": [
        row("nii", "NII", "cr", 4000e7, 3800e7, 3000e7), row("op", "Operating profit", "cr", 2500e7, 2400e7, 2300e7), row("profit", "Net profit", "cr", 1200e7, 1300e7, 1100e7),
        row("provisions", "Provisions", "cr", 300e7, 250e7, 100e7, True), row("gnpa", "Gross NPA", "pct", 1.17, 1.4, 1.9, True), row("nnpa", "Net NPA", "pct", 0.3, 0.4, 0.5, True),
        row("eps", "EPS", "rs", 38.37, 33.37, 30.1)]}


def big_moves():
    """A company result where the profit fell hard and the revenue rose hard: both reactions fire."""
    r = result()
    rows = [{**x, "now": x["year"] * 1.25} if x["key"] == "revenue" else {**x, "now": x["year"] * 0.6} if x["key"] == "profit" else x for x in r["rows"]]
    return {**r, "rows": rows}


def reasons_of(items):
    got, _ = run(items)
    return [{**g, "doc": {"subject": "Press Release", "at": "2026-10-08T15:43:32", "url": "https://nsearchives.test/pr.pdf"}} for g in got]


def result_decks():
    key_c, key_b = market.key_ratios(fundamentals.ratios(fund(), None), False), market.key_ratios(fundamentals.ratios(bank_fund(), None), True)
    out = []
    for r, key, reasons, news in ((result(), [], [], []), (result(), key_c, reasons_of([GOOD_REV, GOOD_MARGIN, GOOD_OUT]), NEWS), (big_moves(), key_c, [], []),
                                  (bank_result(), key_b, [], NEWS), (bank_result(), [], [], [])):
        deck = market.deck(r, reasons=reasons, ratios=key, news=news)
        said = market.lines(r, deck, key)
        out += [(deck, said, r), (deck, market.react(said, r, turn=1), r), (deck, market.react(said, r, turn=0), r)]
    return out


def analysis_decks():
    out = []
    for f in (fund(), bank_fund()):
        rows = fundamentals.ratios(f, PRICE)
        deck = market.analysis_deck(f, rows)
        said = market.analysis_lines(f, rows, deck)
        out += [(deck, said, f), (deck, market.react(said, f, turn=2), f)]
    return out


def report_decks():
    out = []
    for kind in ("premarket", "postmarket"):
        for shape in SHAPES:
            data = data_for(kind, SHAPES[shape])
            deck = market.report_deck(kind, data)
            out.append((deck, market.report_react(market.report_lines(kind, data, deck), turn=3), data))
    return out


ALL = result_decks() + analysis_decks() + report_decks()


def test_every_line_has_an_english_caption_with_the_same_figures_as_the_spoken_line():
    seen_reaction = set()
    for deck, said, _ in ALL:
        for ln in said:
            en = ln.get("en")
            assert en and en.strip(), ln["say"]
            seen_reaction.add(ln.get("reaction"))
            item_of_quotes = deck[ln["slide"]]["kind"] == "quotes" and ln["say"] not in (market.NEWS_INTRO,)
            if item_of_quotes:                                      # the company's own words / the headline as published may hold figures the spoken gist leaves out
                assert market.numbers(ln["say"]) <= market.numbers(en), (ln["say"], en)
            else:
                assert market.numbers(ln["say"]) == market.numbers(en), (ln["say"], en)
            assert not market.ADVICE.search(en) and not market.RUDE.search(en), en
            if not item_of_quotes:
                assert not market.FORECAST.search(en), en
            assert clone.unspelt(ln["say"]) == [] or ln["slide"] >= 0
    assert {"good", "bad", None} <= seen_reaction                    # reactions were exercised


def test_the_figures_in_a_caption_are_written_for_reading():
    r = result()
    en = " ".join(ln["en"] for ln in market.lines(r, market.deck(r)))
    assert "₹10,000 crore" in en and "₹11,000 crore" in en and "10% growth" in en and "₹8.5" in en and "₹9" in en
    assert market.fig_en(73188e7, "cr") == "₹73,188 crore" and market.fig_en(11.2, "pct") == "11.2%" and market.fig_en(38.37, "rs") == "₹38.37" and market.fig_en(1.6, "x") == "1.6 times"
    assert market.fig_en(-12e7, "cr") == "-₹12 crore" and market.fig_en(1234567e7, "cr") == "₹12,34,567 crore"


def test_the_reasons_and_headlines_are_captioned_with_the_verified_english_and_the_headline_as_published():
    r = result()
    reasons = reasons_of([GOOD_REV, GOOD_MARGIN, GOOD_OUT])
    deck = market.deck(r, reasons=reasons, news=NEWS)
    said = [ln for ln in market.lines(r, deck) if deck[ln["slide"]]["kind"] == "quotes"]
    why = [ln["en"] for ln in said[:3]]
    assert why[0] == "Why did margin fall? The company's reason: " + GOOD_MARGIN["point"] and why[1].startswith("Why did revenue rise? The company's reason: " + GOOD_REV["point"])
    assert why[2].startswith("What happens next? As per the company's guidance: ")
    assert said[3]["en"] == market.NEWS_INTRO_EN and said[4]["en"] == "The first headline says: " + NEWS[0]["title"] and len(said) == 5      # the headline with no sentence has no line of its own
    assert all(not market.FORECAST.search(market.lead_en(m, w)) for m in market.WORD_EN for w in ("up", "down", "none")) and not market.FORECAST.search(market.NEWS_INTRO_EN)


def test_a_line_without_an_english_caption_is_made_without_one_and_a_reaction_never_adds_to_nothing():
    slide = {"kind": "quotes", "title": "t", "items": [{"label": "a", "text": "b", "say": "ஒன்று", "tone": "flat"}], "intro": "அறிமுகம்"}
    out = market.quote_lines(0, slide)
    assert [("en" in ln) for ln in out] == [False, False]
    assert slides.caption_plan(out) == [[], []]
    said = [{"slide": 0, "show": 1, "say": "x", "tone": "good", "weight": 99.0}]
    assert "en" not in market.react(said, result(), turn=0)[0] and market.react(said, result(), turn=0)[0]["reaction"] == "good"


def test_each_reaction_has_an_english_twin_that_is_safe_and_keeps_its_name_slot():
    assert {k: len(v) for k, v in market.REACT_EN.items()} == {k: len(v) for k, v in market.REACT.items()}
    for tone in market.REACT:
        for ta, en in zip(market.REACT[tone], market.REACT_EN[tone]):
            assert ("{name}" in ta) == ("{name}" in en) and not re.search(r"\d", en)
            assert not market.ADVICE.search(en) and not market.RUDE.search(en) and not market.FORECAST.search(en), en


def test_the_two_sign_off_lines_are_word_for_word_fixed_and_come_last():
    assert market.SUBSCRIBE_LONG == ("நம்ம channel-அ subscribe பண்ணாம பாக்குறீங்கன்னா, subscribe பண்ணிட்டு bell icon-அ click பண்ணுங்க. "
                                     "அப்போதான் நம்ம channel videos உங்களுக்கு notification-ல time-க்கு வரும், miss பண்ணாம பார்ப்பீங்க.")
    assert market.SUBSCRIBE_SHORT == "இந்த மாதிரி Market and Finance related contents daily-உம் தெரிஞ்சிக்க, நம்ம channel-அ subscribe பண்ணுங்க."
    for deck, said, _ in ALL:
        if deck[0]["kind"] == "board":
            assert said[-1]["say"] == market.SUBSCRIBE_SHORT and said[-1]["en"] == market.SUBSCRIBE_SHORT_EN and said[-1]["slide"] == 0
        else:
            assert said[-1]["say"] == market.SUBSCRIBE_LONG and said[-1]["fixed"] and said[-2]["say"] == market.CLOSING and said[-1]["slide"] == len(deck) - 1 == said[-2]["slide"]
            assert said[-1]["show"] == said[-2]["show"]                                   # no new slide
    for t in (market.SUBSCRIBE_LONG, market.SUBSCRIBE_SHORT):
        assert clone.unspelt(t) == []
    assert "டெய்லியும்" in voiced(market.SUBSCRIBE_SHORT) and "டைமுக்கு" in voiced(market.SUBSCRIBE_LONG)


def test_after_a_front_vowel_the_glide_is_ya_and_elsewhere_va():
    assert voiced("daily-உம்") == "டெய்லியும்" and voiced("hero-ஓட level-அ") == "ஹீரோவோட லெவல" and voiced("bank-ஓட") == "பேங்கோட"


def test_the_writer_does_not_reword_unless_the_channel_says_so():
    ch = youtube.channel({"name": "Mani Market Tamil", "crew": "market"})
    assert not ch.get("reword") and not ch.get("captions")
    from vision.masters.market_crew import TanglishWriter

    class Boom:
        def writer_available(self):
            return True

        async def json(self, prompt, **kw):
            raise AssertionError("asked the model to reword")
    r = result()
    job = {"kind": "result", "result": r, "symbol": "SAMPLE", "key": "k", "docs": [], "news": []}

    class Store:
        def kv_list(self, name):
            return []
    out = asyncio.run(TanglishWriter(ch).run({"job": job, "llm": Boom(), "store": Store()}))
    assert out.status == "done" and job["kept"] == 0 and all(ln.get("en") for ln in job["lines"])


# ---- chunks, timing, rendering -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tall", [False, True])
def test_chunks_fit_the_screen_and_never_part_a_number_from_its_unit(tall):
    box = slides.CAP[tall]
    for _, said, _ in ALL:
        for ln in said:
            chunks = slides.caption_chunks(ln["en"], tall)
            assert " ".join(chunks) == " ".join(ln["en"].split())                          # nothing lost, nothing added
            for c in chunks:
                assert len(c) <= box["chars"] * 1.35 and len(c.split()) <= box["words"] + 3, c
                assert not re.match(r"^(crore|lakh|points|percent|times)\b", c), c        # a unit never starts a chunk
    assert slides.caption_chunks("Now it is ₹73,188 crore. That is 11.2% growth.", True) == ["Now it is ₹73,188 crore.", "That is 11.2% growth."]
    assert slides.caption_chunks("The profit was ₹12,075 crore in the same quarter last year.", True)[0].endswith("₹12,075 crore") or "₹12,075 crore" in " ".join(slides.caption_chunks("x ₹12,075 crore", True))
    for c in slides.caption_chunks("It is 1,234 points up, that is 1.6 percent higher than the day before, which is a lot.", False):
        assert not c.endswith("1,234") and not c.endswith("1.6")
    assert slides.caption_chunks("", False) == [] and slides.caption_chunks("Hello friends!", True) == ["Hello friends!"]
    assert slides.caption_chunks("All in all, revenue has grown 11.2% compared with last year.")[0].startswith("All in all, revenue")     # a short lead keeps its sentence


def test_chunk_times_share_the_speech_by_characters_and_the_last_chunk_takes_the_pause_and_hold():
    secs = slides.caption_times(["abcd", "abcdefgh"], 3.0, 3.15)
    assert secs[0] == pytest.approx(1.0) and secs[1] == pytest.approx(2.15) and sum(secs) == pytest.approx(3.15)
    assert sum(slides.caption_times(["a", "bb", "ccc"], 1.2, 7.2)) == pytest.approx(7.2)
    assert slides.srt_time(3725.5) == "01:02:05,500"


def srt_secs(t):
    h, m, rest = t.split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def tone(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=220:d={seconds}", str(path)], check=True)
    return path


def strips_for(plan, work, tall):
    h = slides.CAP[tall]["height"]
    w = slides.TALL[0] if tall else slides.W
    out = {}
    for n, text in enumerate(["", *slides.caption_texts(plan)]):
        out[text] = work / f"c{n:03d}.png"
        Image.new("RGBA", (w, h), (0, 0, 0, 0) if not text else (255, 0, 0, 200)).save(out[text])
    return out


@pytest.mark.parametrize("tall", [False, True])
def test_assemble_lays_the_captions_over_the_video_and_writes_the_srt(tmp_path, tall):
    size = slides.TALL if tall else (slides.W, slides.H)
    lines = [{"slide": 0, "show": 1, "say": "x", "en": "Now it is ₹73,188 crore. That is 11.2% growth.", "hold": 3.0}, {"slide": 0, "show": 1, "say": "y"}, {"slide": 1, "show": 1, "say": "z", "en": "See you!"}]
    pngs = []
    for n in range(3):
        pngs.append(tmp_path / f"s{n}.png")
        Image.new("RGB", size, (200, 200 - 20 * n, 200)).save(pngs[-1])
    spoken = [tone(tmp_path / f"t{n}.wav", 1.0) for n in range(3)]
    plan = slides.caption_plan(lines, tall)
    assert plan[1] == []
    final = slides.assemble(tmp_path, pngs, lines, spoken, tmp_path / "final.mp4", pause=0.15, size=size, captions={"plan": plan, "pngs": strips_for(plan, tmp_path, tall)})
    assert slides.probe(final) == pytest.approx(3.0 + 1.15 + 1.15, abs=0.2)           # the hold line stays 3 s, as without captions
    srt = (tmp_path / "captions.srt").read_text(encoding="utf-8")
    assert "Now it is ₹73,188 crore." in srt and "That is 11.2% growth." in srt and "See you!" in srt and "00:00:00,000 -->" in srt
    stamps = [tuple(srt_secs(t) for t in m) for m in re.findall(r"(\d\d:\d\d:\d\d,\d{3}) --> (\d\d:\d\d:\d\d,\d{3})", srt)]
    assert len(stamps) == sum(map(len, plan)) and all(a < b for a, b in stamps) and all(stamps[i][1] <= stamps[i + 1][0] + 1e-6 for i in range(len(stamps) - 1))     # in order, never overlapping
    assert stamps[0][0] == 0 and max(b for a, b in stamps if b < 4) == pytest.approx(3.0, abs=0.01)                                                      # the hold line's last chunk runs to the end of the hold
    last = re.findall(r"(\d\d:\d\d:\d\d,\d{3}) --> (\d\d:\d\d:\d\d,\d{3})\nSee you!", srt)[0]
    assert last[0] == "00:00:04,150"                                                  # starts where the third line starts: 3.0 + 1.15, nothing shown across a line boundary
    frame = tmp_path / "f.png"                                                        # the strip is really on the picture: red pixels appear where the band is
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", str(final), "-frames:v", "1", str(frame)], check=True)
    px = Image.open(frame).convert("RGB")
    assert any(abs(px.getpixel((x, slides.CAP[tall]["top"] + 20))[0] - 200) > 15 or px.getpixel((x, slides.CAP[tall]["top"] + 20))[1] < 190 for x in range(0, size[0], 40))


def test_without_captions_nothing_is_written_and_the_srt_name_follows_the_video(tmp_path):
    pngs = [tmp_path / "a.png"]
    Image.new("RGB", (slides.W, slides.H), (200, 200, 200)).save(pngs[0])
    lines = [{"slide": 0, "show": 1, "say": "x", "en": "Hi there."}]
    spoken = [tone(tmp_path / "t.wav", 1.0)]
    slides.assemble(tmp_path, pngs, lines, spoken, tmp_path / "plain.mp4")
    assert not list(tmp_path.glob("*.srt"))
    plan = slides.caption_plan(lines)
    slides.assemble(tmp_path, pngs, lines, spoken, tmp_path / "result-X.mp4", captions={"plan": plan, "pngs": strips_for(plan, tmp_path, False)})
    assert (tmp_path / "result-X.srt").exists()


def test_the_slide_editor_asks_for_captions_only_when_the_channel_wants_them(tmp_path):
    calls = []

    def pictures(deck, lines, work, **frame):
        calls.append(frame)
        work.mkdir(parents=True, exist_ok=True)
        pngs = []
        for n, _ in enumerate(lines):
            pngs.append(work / f"s{n:03d}.png")
            Image.new("RGB", (slides.W, slides.H), (20, 30, 60)).save(pngs[-1])
        if "captions" in frame:
            return pngs, None, strips_for(slides.caption_plan(lines), work, False)
        return pngs, None

    lines = [{"slide": 0, "show": 1, "say": "x", "en": "Hello friends!"}, {"slide": 0, "show": 1, "say": "y"}]
    for want in (True, False):
        work = tmp_path / str(want)
        work.mkdir()
        job = {"dir": str(work), "deck": [{"kind": "cover", "title": "t", "items": []}], "lines": lines, "spoken": [tone(work / f"t{n}.wav", 1.0) for n in range(2)]}
        editor = market_crew.SlideEditor(youtube.channel({"name": "M", "captions": want}), pictures=pictures)
        final = asyncio.run(editor.film(job, source="s"))
        assert final.exists() and (work / "captions.srt").exists() == want
    assert "captions" in calls[0] and "captions" not in calls[1]
