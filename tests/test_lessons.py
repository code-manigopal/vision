"""Mani Market Tamil's finance lessons: topic choice, channel signals, transcript limits, the checks on every spoken line, the decks, the release rules, and a night of the crew
(no network, no Chrome, no voice model, no real writer; ffmpeg is real)."""

import asyncio
import json
import shutil
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from PIL import Image
from test_market_crew import RAW, tone

from vision.agents import Director, Master, Stage
from vision.bus import EventBus, Store
from vision.config import Config
from vision.masters import lessons, market, market_crew, slides, youtube
from vision.services import filings_text, oauth, yt_channels, yt_transcripts
from vision.voice import clone

FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
IST = ZoneInfo("Asia/Kolkata")
OFFICIAL = (
    "Frequently asked questions on deposits. A term deposit is a contract between the bank and the customer for a definite term. "
    "A term deposit can be paid prematurely at the request of the customer subject to the terms of the contract, including penalty, if any. "
    "Interest on term deposits is payable at quarterly or longer rests. Banks can pay interest monthly by discounting the quarterly interest accrued. "
    "Differential rates of interest can be paid on single term deposits of Rs.15 lakh and above. "
    "The Deposit Insurance and Credit Guarantee Corporation insures all types of deposits, such as savings, fixed and recurring. "
    "Each depositor in a bank is insured up to a maximum of Rs.5 lakh for both principal and interest amount held in the same right and same capacity. "
    "A recurring deposit lets the customer deposit a fixed amount every month for an agreed period. "
    "Banks may not normally refuse premature withdrawal of term deposits of individuals and Hindu Undivided Families. "
    "Banks are prohibited from paying commission for mobilising deposits except to agents collecting door-to-door deposits.")
TP = lessons.topic("fd-test", "Fixed deposit basics", "எஃப்டி பேசிக்ஸ்", "deposits", [{"label": "RBI FAQ on deposits", "url": "https://official.test/fd"}],
                   ["fixed deposit", "fd interest", "fd vs rd"], "bank")
TP2 = lessons.topic("rd-test", "Recurring deposit basics", "ஆர்டி பேசிக்ஸ்", "deposits", [{"label": "RBI FAQ on recurring deposits", "url": "https://official.test/fd"}], ["recurring deposit"], "calendar")
PAGE = f"<html><title>FAQ</title><body><h1>Deposits</h1><p>{OFFICIAL.replace('. ', '.</p><p>')}</p></body></html>"
DOC = [lessons.squash(OFFICIAL)]
Q_DEF = "A term deposit is a contract between the bank and the customer for a definite term"
Q_PRE = "A term deposit can be paid prematurely at the request of the customer subject to the terms of the contract, including penalty, if any"
Q_INS = "Each depositor in a bank is insured up to a maximum of Rs.5 lakh for both principal and interest amount held in the same right and same capacity"
Q_RD = "A recurring deposit lets the customer deposit a fixed amount every month for an agreed period"
Q_MON = "Banks can pay interest monthly by discounting the quarterly interest accrued"
Q_COM = "Banks are prohibited from paying commission for mobilising deposits except to agents collecting door-to-door deposits"
Q_BIG = "Differential rates of interest can be paid on single term deposits of Rs.15 lakh and above"


def line(say, en, *quotes, show=1):
    return {"show": show, "say": say, "en": en, "quotes": list(quotes)}


GOOD = {
    "def": line("டெர்ம் டெபாசிட்னா, பேங்குக்கும் கஸ்டமருக்கும் இடையில ஒரு குறிப்பிட்ட காலத்துக்கான ஒப்பந்தம்.", "A term deposit is a contract between the bank and the customer for a definite term.", Q_DEF),
    "rd": line("ரெக்கரிங் டெபாசிட்னா, ஒவ்வொரு மாசமும் ஒரு குறிப்பிட்ட தொகைய ஒப்புக்கிட்ட காலத்துக்கு டெபாசிட் பண்ணுறது.", "A recurring deposit lets the customer deposit a fixed amount every month for an agreed period.", Q_RD, show=2),
    "month": line("பேங்க் காலாண்டு இன்ட்ரெஸ்ட்ட டிஸ்கவுண்ட் பண்ணி, மாசா மாசமும் குடுக்க முடியும்.", "Banks can pay interest monthly by discounting the quarterly interest accrued.", Q_MON),
    "ins": line("ஒரு பேங்க்ல ஒரு டெபாசிட்டருக்கு பிரின்சிபல், இன்ட்ரெஸ்ட் ரெண்டுக்கும் சேர்த்து அதிகபட்சம் 5 லட்சம் ரூபாய் வரைக்கும் இன்ஷூரன்ஸ் உண்டு.",
                "Each depositor in a bank is insured up to a maximum of Rs.5 lakh for both principal and interest.", Q_INS),
    "pre": line("கஸ்டமர் கேட்டா, ஒப்பந்தத்தோட விதிகள்படி, பெனால்டி உட்பட, டெர்ம் டெபாசிட்ட சீக்கிரமே குடுக்கலாம்.", "A term deposit can be paid prematurely at the request of the customer, subject to the terms of the contract, including penalty.", Q_PRE, show=2),
    "rest": line("டெர்ம் டெபாசிட்டோட இன்ட்ரெஸ்ட் காலாண்டுக்கு ஒரு தடவையோ, இல்ல அதுக்கு மேலயோதான் குடுப்பாங்க.", "Interest on term deposits is payable at quarterly or longer rests.", "Interest on term deposits is payable at quarterly or longer rests"),
    "hindu": line("தனிநபர்களோட டெர்ம் டெபாசிட்ட சீக்கிரம் எடுக்க பேங்க் பொதுவா மறுக்காது.", "Banks do not normally refuse premature withdrawal of term deposits of individuals.", "Banks may not normally refuse premature withdrawal of term deposits of individuals and Hindu Undivided Families", show=3),
    "dicgc": line("சேவிங்ஸ், ஃபிக்ஸ்ட், ரெக்கரிங் எல்லா வகை டெபாசிட்டுக்கும் கார்ப்பரேஷன் இன்ஷூரன்ஸ் குடுக்கும்.", "The Corporation insures all types of deposits, such as savings, fixed and recurring.", "The Deposit Insurance and Credit Guarantee Corporation insures all types of deposits, such as savings, fixed and recurring", show=2),
    "comm": line("டெபாசிட் சேர்த்துக் குடுக்க கமிஷன் குடுக்கிறத பேங்க்குகளுக்கு தடை பண்ணிருக்காங்க, வீடு வீடா சேகரிக்கிற ஏஜென்ட்ஸ தவிர.",
                 "Banks are prohibited from paying commission for mobilising deposits except to agents collecting door-to-door deposits.", Q_COM),
    "big": line("15 லட்சம் ரூபாய்க்கும் மேல ஒரே டெர்ம் டெபாசிட்டுக்கு வித்தியாசமான இன்ட்ரெஸ்ட் ரேட் குடுக்கலாம்.", "Differential rates of interest can be paid on single term deposits of Rs.15 lakh and above.", Q_BIG),
}
PLAN = {"title": "How does a bank FD work?", "slides": [
    {"kind": "points", "heading": "What it is", "icon": "bank", "items": ["Term deposit is a contract with the bank", "Interest payable at quarterly or longer rests", "Banks pay interest monthly by discounting"]},
    {"kind": "points", "heading": "Safety and limits", "icon": "shield", "items": ["Depositor insured up to 5 lakh", "Premature withdrawal of term deposits"]},
    {"kind": "facts", "heading": "Figures", "rows": [{"label": "Insurance cover", "value": "Rs.5 lakh", "note": "per depositor"}, {"label": "Single term deposit", "value": "Rs.15 lakh", "note": "and above"}]}]}
SLIDE_LINES = [["def", "rd", "month", "rest"], ["ins", "pre", "hindu", "dicgc"], ["big", "comm"]]


class Model:
    """A stand-in for the writer: answers the angle, plan and per-slide requests it is configured for, and counts them."""
    def __init__(self, plan=PLAN, per_slide=None, angle=None):
        self.plan, self.per_slide, self.angle, self.calls, self.slide = plan, per_slide or [[GOOD[k] for k in ks] for ks in SLIDE_LINES], angle, [], 0

    def writer_available(self):
        return True

    async def json(self, prompt, **kw):
        if "Do NOT copy any wording" in prompt:
            self.calls.append("angle")
            return self.angle or {"angle": "Explain what an FD really is", "questions": ["Is my FD safe?", "Can I break it early?"], "misconceptions": ["An FD can never lose value"]}
        if "You plan a short lesson" in prompt:
            self.calls.append("plan")
            self.prompt = prompt
            return self.plan
        self.calls.append("lines")
        self.slide_prompt = prompt
        got = self.per_slide[min(self.slide, len(self.per_slide) - 1)]
        self.slide += 1
        return {"lines": got}


BAD = lessons.bad_pattern(["Sample Limited", "Hindustan Unilever Limited"], ["SAMPLE", "INFY"])
NO_TX: set = set()


# ---- the checks on one spoken line -------------------------------------------------------------------------------------------------------------

def why(item, tx=NO_TX):
    return lessons.check_line(item, DOC, BAD, tx)


def test_a_good_line_is_kept_and_each_rule_throws_out_its_own_kind_of_line():
    d, ta = GOOD["def"], GOOD["def"]["say"]
    assert all(why(g) == "" for g in GOOD.values())
    assert why(line("எஃப்டி பத்தி இது ஒரு நல்ல தகவல்.", "An FD is a fine thing to know about.", "this sentence is nowhere in the official page at all")) == "quote is not in the source"
    assert why(line("எஃப்டி பத்தி இது ஒரு நல்ல தகவல்.", "An FD is a fine thing to know about.", "A term deposit is a contract")) == "quote is not in the source"                 # under 30 characters
    assert why({**GOOD["ins"], "say": GOOD["ins"]["say"].replace("5", "6"), "en": GOOD["ins"]["en"].replace("5", "6")}) == "a number is not in the quotes"
    assert why({**GOOD["ins"], "en": GOOD["ins"]["en"] + " Rs.99 lakh."}) == "a number is not in the quotes"
    assert why({**GOOD["ins"], "en": GOOD["ins"]["en"].replace("Rs.5 lakh ", "")}) == "the Tamil and the English caption give different numbers"
    assert why({**d, "say": "எஃப்டினா bank-ல பணம் போட்டு வைக்கிற ஒப்பந்தம் தான்."}) == "spoken line is not all Tamil script"
    assert why({**d, "say": ta + " ₹"}) == "spoken line is not all Tamil script"
    assert why({**d, "say": ta + " இது இருக்கும் ஒப்பந்தம்."}) == "forecast wording"
    assert why({**d, "en": "You should buy a term deposit, a contract between the bank and the customer for a definite term."}) == "advice or rude wording"
    assert why({**GOOD["month"], "en": "Banks will pay interest monthly by discounting the quarterly interest accrued."}) == "forecast wording"
    assert why({**d, "en": "A term deposit is a contract between Sample Limited and the customer for a definite term."}) == "names a company or the market"
    assert why({**d, "en": "A term deposit is a contract between Axis Bank and the customer for a definite term."}) == "names a company or the market"          # a well-known bank is a name too
    assert why({**d, "en": d["en"][:-1] + ", whatever the Nifty does."}) == "names a company or the market"
    assert why({**d, "say": ta + " மோசடி."}) == "advice or rude wording"
    assert why({**d, "say": "டெர்ம் டெபாசிட் என்பது பேங்குக்கும் கஸ்டமருக்கும் இடையில ஒரு குறிப்பிட்ட காலத்துக்கான ஒப்பந்தம்."}) == "book Tamil, not the way the host speaks"
    assert why({**d, "en": "A term deposit is a contract where you keep money with the bank for a fixed term."}) == "the caption says more than its quotes do"
    assert why({**d, "en": "An FD is a contract between the bank and the customer for a definite term."}) == "the caption says more than its quotes do"         # FD is in no quote
    assert why({**d, "say": "ஒப்பந்தம் வித் வித் வித் டெர்ம் டெபாசிட் பேங்க்."}) == "a garbled line (a word repeated)"
    assert why({"say": "x", "en": "y"}) == "not a complete line" and why("nope") == "not a complete line"
    assert why({**d, "quotes": []}) == "no line, caption or quote" and why({**d, "say": "எஃப்டி"}) == "a line of the wrong length"


def test_two_quotes_cannot_be_stitched_into_a_claim_neither_makes():
    q_term, q_rd = "Term deposit with 5 years lock in period for tax saving", "Recurring deposits popularly known as RD are best if you wish to create a fund"
    assert lessons.backed_by("RD has a 5 year lock-in period", [q_term, q_rd]) is False                   # RD is in one quote, the lock-in in the other
    assert lessons.backed_by("A recurring deposit is best if you wish to create a fund", [q_term, q_rd]) is True and lessons.backed_by("RD is best if you wish to create a fund", [q_rd]) is True
    assert lessons.backed_by("A term deposit has a lock in period, RD is best to create a fund", [q_term, q_rd]) is True                         # two halves, each in its own quote
    assert lessons.backed_by("A term deposit with 5 years lock in period", [q_term]) is True
    assert lessons.backed_by("Fine.", [q_term]) is False and lessons.backed_by("It is good.", [q_term]) is False                                # too little to check


def test_a_line_sharing_eight_words_in_a_row_with_a_transcript_is_a_copy_and_seven_is_not():
    tx = lessons.shingles("so the thing is a term deposit is a contract between the bank and the customer for a definite term okay and then")
    assert why(GOOD["def"], tx) == "a near copy of a transcript"
    eight = lessons.shingles("deposit is a contract between the bank and the please subscribe now")                                  # 8 words in a row: a copy
    assert why(GOOD["def"], eight) == "a near copy of a transcript"
    seven = lessons.shingles("a contract between the bank and the please subscribe now")                                             # 7 words in a row: not a copy
    assert why(GOOD["def"], seven) == ""
    assert lessons.shingles("one two three four five six seven", 8) == set()


def test_the_transcript_is_scrubbed_of_companies_prices_advice_and_the_markets_direction():
    text = ("An FD pays fixed interest every quarter. Sample Limited share price will go up. Buy INFY now for a big target. The Nifty rally continues today. "
            "Banks insure deposits up to a limit. HDFC is a great bank. Always read the terms of the deposit.")
    got = lessons.scrub(text, BAD)
    assert got == "An FD pays fixed interest every quarter. Banks insure deposits up to a limit. Always read the terms of the deposit."
    run = " ".join(["word"] * 100) + " Sample Limited"
    assert "Sample" not in lessons.scrub(run, BAD)                                                                                    # an unpunctuated run is cut into pieces first
    assert lessons.est_tokens("a" * 400) == 100 and lessons.est_tokens("அ" * 130) == 100
    txt = lessons.transcript_text([{"text": ". ".join(f"Sentence number {i} about deposits and interest rates" for i in range(400))}], BAD)
    assert lessons.est_tokens(txt) <= lessons.TRANSCRIPT_TOKENS


def test_the_angle_from_transcripts_keeps_no_number_and_no_advice():
    got = asyncio.run(lessons.angle(Model(angle={"angle": "Show how an FD works in 3 steps", "questions": ["Is my FD safe?", "Should I buy an FD today?", "short"], "misconceptions": ["FD is risk free", "Rates are 7%"]}), TP, "some text"))
    assert got == {"angle": "", "questions": ["Is my FD safe?"], "misconceptions": ["FD is risk free"]}
    assert asyncio.run(lessons.angle(Model(), TP, "  ")) == {} and asyncio.run(lessons.angle(None, TP, "text")) == {}


# ---- the plan and the lesson -------------------------------------------------------------------------------------------------------------------

def pages():
    return [{"label": "RBI FAQ on deposits", "url": "https://official.test/fd", "text": OFFICIAL}]


def test_a_lesson_keeps_only_lines_that_pass_and_the_deck_and_lines_obey_the_channels_rules():
    model = Model()
    out = asyncio.run(lessons.write(model, TP, pages(), [{"title": "t", "channel": "c", "url": "u", "text": "An unrelated transcript about saving money regularly in a bank."}], BAD))
    assert not out["too_thin"] and out["kept"] == 10 and out["proposed"] == 10 and out["dropped"] == []
    assert model.calls[:2] == ["angle", "plan"] and model.calls.count("lines") == 3
    deck, said = out["deck"], out["lines"]
    assert deck[0] == market.NOTICE and deck[1]["kind"] == "cover" and [s["kind"] for s in deck[2:]] == ["points", "points", "facts"]
    assert said[0]["say"] == market.NOTICE_SAY and said[0]["hold"] == market.NOTICE_HOLD and said[1]["say"].startswith("வணக்கம்")
    assert said[-1]["say"] == market.SUBSCRIBE_LONG and said[-2]["say"] == lessons.CLOSE_SAY and said[-1]["slide"] == len(deck) - 1
    assert all(deck[2 + i]["note"].startswith("Source: RBI FAQ on deposits · official.test") for i in range(3))
    for ln in said:
        assert ln.get("en") and clone.unspelt(ln["say"]) == [], ln["say"]
        assert 0 <= ln["slide"] < len(deck) and 1 <= ln["show"] <= len(deck[ln["slide"]]["items"]) + 1 + (1 if deck[ln["slide"]]["kind"] == "notice" else 0) or deck[ln["slide"]]["kind"] in ("notice", "cover")
        if not ln.get("fixed"):
            assert not market.ADVICE.search(ln["en"] + ln["say"]) and not market.FORECAST.search(ln["en"] + ln["say"]) and not market.RUDE.search(ln["en"] + ln["say"])
            assert market.numbers(ln["say"]) == market.numbers(ln["en"])
    for s in range(2, len(deck)):                                                              # on every slide the last line shows everything, and the shows never go down
        shows = [ln["show"] for ln in said if ln["slide"] == s]
        assert shows == sorted(shows) and shows[-1] == len(deck[s]["items"]) + 1
    assert "Source: RBI FAQ on deposits" in slides.page(deck, channel="Mani Market Tamil", source="Finance basics")
    assert out["title"] == "How does a bank FD work?" and out["angle"]["questions"] == ["Is my FD safe?", "Can I break it early?"]


def test_a_lesson_Short_has_no_notice_no_spoken_disclaimer_and_ends_on_the_short_sign_off():
    plan = {"title": "What is an RD?", "concept": "recurring deposit", "slides": [{"kind": "points", "heading": "RD", "icon": "calendar", "items": ["Fixed amount monthly", "Agreed period", "Interest on it"]}]}
    model = Model(plan=plan, per_slide=[[GOOD["rd"], GOOD["month"], GOOD["def"], GOOD["pre"]]])
    out = asyncio.run(lessons.write(model, TP, pages(), [], BAD, short=True, covered=["fixed deposit"]))
    deck, said = out["deck"], out["lines"]
    assert not out["too_thin"] and deck[0]["kind"] == "points" and market.NOTICE not in deck and out["concept"] == "recurring deposit"
    assert said[-1]["say"] == market.SUBSCRIBE_SHORT and said[-1]["en"] == market.SUBSCRIBE_SHORT_EN and not any("educational" in ln["say"].lower() for ln in said)
    assert "fixed deposit" in model.prompt and "Do not use a facts slide" in model.prompt
    tall = slides.page(deck, channel="Mani Market Tamil", tall=True, top=market.SHORT_NOTE)
    assert 'class="top"' in tall and "Source: RBI FAQ on deposits" in tall and "1080px" in tall
    for ln in said:
        assert clone.unspelt(ln["say"]) == []


def test_too_few_kept_lines_is_too_thin_and_a_bad_plan_or_a_failing_model_makes_no_lesson():
    bad_lines = [[{**GOOD["def"], "quotes": ["nothing like the page, said in a long enough sentence"]}] * 3] * 3
    thin = asyncio.run(lessons.write(Model(per_slide=bad_lines), TP, pages(), [], BAD))
    assert thin["too_thin"] and thin["kept"] == 0 and thin["proposed"] == 18 and thin["dropped"][0]["why"] == "quote is not in the source" and "deck" not in thin
    nine = [[GOOD["def"], GOOD["rd"], GOOD["month"], GOOD["rest"]], [GOOD["ins"], GOOD["pre"], GOOD["hindu"], GOOD["dicgc"]], [GOOD["big"], {**GOOD["comm"], "en": "nope"}]]
    assert asyncio.run(lessons.write(Model(per_slide=nine), TP, pages(), [], BAD))["too_thin"] is True                                 # 8 kept: 9 kept: under MIN_KEPT
    assert asyncio.run(lessons.write(Model(plan={"title": "x"}), TP, pages(), [], BAD))["too_thin"] is True

    class Down(Model):
        async def json(self, prompt, **kw):
            raise RuntimeError("down")
    out = asyncio.run(lessons.write(Down(), TP, pages(), [], BAD))
    assert out["too_thin"] and out["title"].startswith("Fixed deposit basics")


def test_the_plan_keeps_nothing_it_cannot_stand_behind():
    have = OFFICIAL
    plan = {"title": "Earn 50,000 a month from FDs in 30 days", "slides": [
        {"kind": "points", "heading": "Good", "icon": "nonsense", "items": ["Fixed term", "Insured up to 5 lakh", "Buy now", "Rate of 9.9 percent"]},
        {"kind": "points", "heading": "Nifty view", "items": ["One", "Two"]}, {"kind": "points", "heading": "One only", "items": ["Just one"]},
        {"kind": "facts", "heading": "Figures", "rows": [{"label": "Cover", "value": "Rs.5 lakh", "note": ""}, {"label": "Rate", "value": "Rs.99 lakh", "note": ""}]}]}
    title, sl = lessons.plan_slides(plan, have, False)
    assert title == ""                                                                                    # a promise of earnings is no title
    assert [s["title"] for s in sl] == ["Good"] and [i["text"] for i in sl[0]["items"]] == ["Fixed term", "Insured up to 5 lakh"] and sl[0]["items"][0]["icon"] == "paper"
    assert lessons.plan_slides({"title": "Is an FD safe?", "slides": []}, have, False) == ("Is an FD safe?", [])
    assert lessons.plan_slides("junk", have, False) == ("", [])


# ---- the topic bank and the choice -----------------------------------------------------------------------------------------------------------

def test_the_bank_is_wellformed():
    ids = [t["id"] for t in lessons.TOPICS]
    assert len(ids) >= 40 and len(set(ids)) == len(ids) and "fd-vs-rd" in ids
    for t in lessons.TOPICS:
        assert 1 <= len(t["sources"]) <= 4 and t["words"] and t["icon"] in lessons.ICONS and t["group"]
        assert all(s["url"].startswith("https://") and s["label"] for s in t["sources"])
        assert not [w for w in [t["ta"]] if lessons.LATIN.search(w) or clone.unspelt(w)], (t["id"], t["ta"])
        assert not market.ADVICE.search(t["title"]) and not lessons.MARKET_DIR.search(t["title"])
    assert lessons.CLOSE_SAY and clone.unspelt(lessons.CLOSE_SAY) == [] and clone.unspelt(lessons.OPEN_SAY.format(ta=TP["ta"])) == []


def video(title, views, days_ago=5, now=None):
    now = now or time.time()
    return {"id": title[:5], "title": title, "channel": "X", "views": views, "published": (datetime.fromtimestamp(now - days_ago * 86400, timezone.utc)).isoformat()}


def test_topics_with_a_signal_come_first_then_the_one_made_longest_ago_and_the_rules_block(tmp_path):
    store, now = Store(tmp_path / "t.db"), time.time()
    topics = [lessons.topic(i, i, "x", "g", [], [w]) for i, w in (("a", "alpha"), ("b", "beta"), ("c", "gamma"), ("d", "delta"))]
    ids = lambda **kw: [t["id"] for t, _, _ in lessons.rank(store, topics, **kw)]      # noqa: E731
    assert ids() == ["a", "b", "c", "d"]                                                          # nothing known: the bank's order
    vids = [video("Gamma explained", 9000, 3), video("Beta vs more", 1000, 2), video("old gamma video", 900000, 200), video("Beta again", 500, 10)]
    got = lessons.rank(store, topics, vids, now)
    assert [t["id"] for t, _, _ in got] == ["c", "b", "a", "d"] and got[0][1] == pytest.approx(3000.0, rel=0.05) and got[0][2][0]["title"] == "Gamma explained"
    store.kv_put(lessons.DONE, "lesson:c", {"at": now - 10 * 86400})                               # made 10 days ago: out
    store.kv_put(lessons.DONE, "lesson:a", {"at": now - 200 * 86400})                              # 200 days ago: back, but after the never-made ones
    assert lessons.rank(store, topics, vids, now)[0][0]["id"] == "b" and [t["id"] for t, _, _ in lessons.rank(store, topics, vids, now)] == ["b", "d", "a"]
    assert ids(now=now) == ["b", "d", "a"]
    lessons.skip(store, "b", "no source")
    assert ids(now=now) == ["d", "a"]
    assert ids(now=now + 4 * 86400)[0] == "b" and "c" in ids(now=now + 171 * 86400)           # a skip lasts SKIP_DAYS, a made lesson REPEAT_DAYS
    store.kv_put(lessons.DONE, "lessonshort:d", {"at": now - 5 * 86400, "concepts": ["one"]})
    assert "d" not in ids(now=now, short=True) and "d" in ids(now=now + 31 * 86400, short=True)
    store.kv_put(lessons.DONE, "lessonshort:a", {"at": now - 100 * 86400, "concepts": ["1", "2", "3"]})
    assert "a" not in ids(now=now, short=True)                                                    # three concepts told: that topic is done for Shorts


def test_a_title_matches_a_topic_only_by_whole_words():
    assert yt_channels.matches("RD vs FD: which is better?", ["fd vs rd"]) and not yt_channels.matches("Standard fdr report", ["fd"])
    assert yt_channels.matches("Index Funds for Beginners", ["index fund", "index funds"]) and not yt_channels.matches("Indexing the funded", ["index fund"])
    assert yt_channels.words("SIP vs Lumpsum 2026!") == ["sip", "vs", "lumpsum", "2026"]


# ---- channel signals (mocked API) ---------------------------------------------------------------------------------------------------------------

def yt_api(calls, known=("Good Channel",)):
    now = datetime.now(timezone.utc).isoformat()

    def handler(req):
        path = req.url.path.rsplit("/", 1)[-1]
        calls.append((path, req.headers.get("authorization"), req.url.params.get("key")))
        if path == "search":
            q = req.url.params["q"]
            return httpx.Response(200, json={"items": [{"id": {"channelId": "UC" + q[:3]}, "snippet": {"channelTitle": q}}] if q in known else []})
        if path == "channels":
            return httpx.Response(200, json={"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU" + req.url.params["id"][2:]}}}]})
        if path == "playlistItems":
            return httpx.Response(200, json={"items": [{"snippet": {"title": "FD vs RD explained", "publishedAt": now, "resourceId": {"videoId": "v1"}}},
                                                       {"snippet": {"title": "Fixed deposit rates explained", "publishedAt": now, "resourceId": {"videoId": "v2"}}}]})
        if path == "videos":
            return httpx.Response(200, json={"items": [{"id": "v1", "statistics": {"viewCount": "5000"}}, {"id": "v2", "statistics": {"viewCount": "100"}}]})
        return httpx.Response(404)
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_channel_signals_cost_one_name_lookup_ever_and_one_cheap_read_a_day(tmp_path):
    store, calls = Store(tmp_path / "t.db"), []
    make = yt_api(calls)

    async def go(now, **kw):
        async with make() as c:
            return await yt_channels.signals(c, store, ["Good Channel", "Missing One"], now=now, **kw)
    first = asyncio.run(go(1_000_000.0, token="tok"))
    assert [p for p, _, _ in calls].count("search") == 2 and calls[0][1] == "Bearer tok" and first["missing"] == ["Missing One"]
    assert [(v["id"], v["views"], v["channel"]) for v in first["videos"]] == [("v1", 5000, "Good Channel"), ("v2", 100, "Good Channel")]
    n = len(calls)
    asyncio.run(go(1_000_000.0 + 3600, token="tok"))
    assert len(calls) == n                                                                         # the same day: nothing is asked
    asyncio.run(go(1_000_000.0 + 90000, token="tok"))
    later = [p for p, _, _ in calls[n:]]
    assert later == ["playlistItems", "videos"]       # a new day: one page of uploads and one statistics call, no name lookup
    asyncio.run(go(1_000_000.0 + 3 * 90000, key="K"))
    assert calls[-1][2] == "K" and calls[-1][1] is None


def test_a_channel_that_fails_is_skipped_and_recent_views_a_day_score_the_topic(tmp_path):
    store = Store(tmp_path / "t.db")

    def handler(req):
        return httpx.Response(500)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await yt_channels.signals(c, store, ["Good Channel"], token="t")
    assert asyncio.run(go())["videos"] == []
    now = time.time()
    t = {"words": ["fd vs rd"]}
    s, hit = yt_channels.score(t, [video("FD vs RD", 6000, 2, now), video("FD vs RD old", 99999, 400, now), video("Other", 5, 1, now)], now)
    assert s == pytest.approx(3000, rel=0.05) and [v["title"] for v in hit] == ["FD vs RD"]


# ---- transcripts: the owner's limits ---------------------------------------------------------------------------------------------------------

def test_transcripts_stop_at_the_days_cap_and_for_the_day_on_any_block(tmp_path):
    store, asked, slept = Store(tmp_path / "t.db"), [], []
    vids = [{"id": f"v{i}", "title": f"t{i}", "channel": "c"} for i in range(6)]

    def fetch(vid):
        asked.append(vid)
        if vid == "v1":
            return ""                                           # no transcript: simply skipped
        if vid == "v4":
            raise yt_transcripts.Blocked("IpBlocked")
        return f"text of {vid}"

    async def nap(s):
        slept.append(s)
    day = date(2026, 10, 14)
    got = asyncio.run(yt_transcripts.read(store, vids, cap=3, today=day, fetch=fetch, sleep=nap))
    assert [g["id"] for g in got] == ["v0", "v2"] and asked == ["v0", "v1", "v2"] and all(s == yt_transcripts.GAP for s in slept) and len(slept) == 2
    assert got[0]["url"] == "https://www.youtube.com/watch?v=v0"
    assert asyncio.run(yt_transcripts.read(store, vids, cap=3, today=day, fetch=fetch, sleep=nap)) == [] and asked == ["v0", "v1", "v2"]      # today's three are spent
    asyncio.run(yt_transcripts.read(store, vids[3:], cap=10, today=date(2026, 10, 15), fetch=fetch, sleep=nap))                                 # tomorrow: v3 read, v4 blocks
    assert asked[3:] == ["v3", "v4"] and yt_transcripts.state(store, date(2026, 10, 15))["blocked"] is True
    assert asyncio.run(yt_transcripts.read(store, vids[5:], cap=10, today=date(2026, 10, 15), fetch=fetch, sleep=nap)) == [] and asked[-1] == "v4"   # blocked: no retry that day
    assert yt_transcripts.state(store, date(2026, 10, 16)) == {"day": "2026-10-16", "count": 0, "blocked": False}


def test_the_library_is_called_with_no_cookies_no_proxy_and_a_block_is_recognised(monkeypatch):
    import youtube_transcript_api as lib
    seen = {}

    class IpBlocked(Exception):
        pass

    class Api:
        def __init__(self, *a, **kw):
            seen["init"] = (a, kw)

        def fetch(self, vid, languages=()):
            seen["fetch"] = (vid, list(languages))
            if vid == "blocked":
                raise IpBlocked("YouTube is blocking requests from your IP")
            if vid == "none":
                raise RuntimeError("no transcript")
            return [type("S", (), {"text": "hello"})(), type("S", (), {"text": "world"})()]
    monkeypatch.setattr(lib, "YouTubeTranscriptApi", Api)
    assert yt_transcripts.fetch_library("abc") == "hello world" and seen["init"] == ((), {}) and seen["fetch"] == ("abc", list(yt_transcripts.LANGS))
    assert yt_transcripts.fetch_library("none") == ""
    with pytest.raises(yt_transcripts.Blocked):
        yt_transcripts.fetch_library("blocked")


# ---- the pages -------------------------------------------------------------------------------------------------------------------------------

def test_sources_that_are_dead_empty_or_off_topic_are_left_out_and_a_page_is_read_as_paragraphs():
    def handler(req):
        u = str(req.url)
        if u.endswith("/ok"):
            return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})
        if u.endswith("/off"):
            return httpx.Response(200, text="<p>" + "The weather today is pleasant in the hills. " * 40 + "</p>", headers={"content-type": "text/html"})
        if u.endswith("/tiny"):
            return httpx.Response(200, text="<p>Just a few words here</p>")
        return httpx.Response(404)
    tp = lessons.topic("t", "Fixed deposit basics", "x", "g", [{"label": n, "url": f"https://official.test/{n}"} for n in ("gone", "ok", "off", "tiny")], ["fixed deposit"])
    slept = []

    async def nap(s):
        slept.append(s)
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await lessons.fetch_sources(c, tp, sleep=nap)
    got = asyncio.run(go())
    assert [p["label"] for p in got] == ["ok"] and slept == [lessons.GAP] * 3
    assert "A term deposit is a contract between the bank and the customer for a definite term." in got[0]["text"].splitlines()


def test_passages_pick_the_sentences_about_the_subject_and_tag_each_page():
    p = [{"label": "RBI FAQ", "url": "https://www.rbi.org.in/x", "text": OFFICIAL.replace(". ", ".\n") + "\nThe weather is nice today in the hills of the south."}]
    got = lessons.passages(p, lessons.keywords("Recurring deposit", "recurring deposit"), 300)
    assert got.startswith("[S1] RBI FAQ (rbi.org.in)") and "recurring deposit lets the customer" in got and "weather" not in got and len(got) < 400


def test_html_text_drops_menus_scripts_and_short_lines():
    t = filings_text.html_text("<script>var x=1</script><nav>Home About Us Contact Now Please</nav><div>Menu</div><p>Interest on term deposits is payable at\nquarterly or longer rests.</p>"
                               "<p>Interest on term deposits is payable at quarterly or longer rests.</p><li>Banks pay interest.</li>")
    assert t == "Interest on term deposits is payable at quarterly or longer rests."                  # the menu, the script and the two-word item are gone; the repeated paragraph is kept once


# ---- release timing -------------------------------------------------------------------------------------------------------------------------

def at(h, m, day=date(2026, 10, 17)):
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST).timestamp()


def test_a_lesson_short_goes_out_at_9_or_21_ist_and_is_stale_once_its_indian_date_is_over():
    d = date(2026, 10, 17)
    assert youtube.lesson_release("premarket", d, at(7, 30)) == at(9, 0) and youtube.lesson_release("postmarket", d, at(19, 0)) == at(21, 0)
    assert youtube.lesson_release("premarket", d, at(8, 50)) == at(8, 50) + youtube.REPORT_LEAD                           # too close to 09:00 for YouTube: 15 minutes on
    assert youtube.lesson_release("premarket", d, at(11, 0)) == at(11, 0) + youtube.REPORT_LEAD                           # more than an hour late, still the same date
    assert youtube.lesson_release("postmarket", d, at(22, 30)) == at(22, 30) + youtube.REPORT_LEAD
    assert youtube.lesson_release("postmarket", d, at(23, 50)) is None and youtube.lesson_release("premarket", d, at(7, 0, date(2026, 10, 18))) is None
    rec = {"kind": "lesson_short", "window": "postmarket", "date": "2026-10-17"}
    assert youtube.short_when(rec, at(19, 0)) == at(21, 0) and youtube.short_when({"kind": "premarket", "date": "2026-10-17"}, at(7, 30)) == at(7, 30) + youtube.REPORT_LEAD
    assert "lesson" in youtube.LESSON_KINDS and "lesson_short" in youtube.SHORT_KINDS and "lesson" not in youtube.SHORT_KINDS


# ---- a night of the crew ---------------------------------------------------------------------------------------------------------------------

SEEN = {}


def pictures(deck, lines, work, tall=False, **frame):
    SEEN.update(deck=deck, lines=lines, tall=tall, frame=frame)
    work.mkdir(parents=True, exist_ok=True)
    out = []
    for n, _ in enumerate(lines):
        out.append(work / f"s{n:03d}.png")
        Image.new("RGB", (1080, 1920) if tall else (1920, 1080), (20 + n, 30, 60)).save(out[-1])
    return out, None


def web(state):
    """The index list, no results, the holiday list, one official page, the YouTube API for the signals, and the upload."""
    api = yt_api(state.setdefault("api", []))().__dict__["_transport"].handler

    def handler(req):
        u = str(req.url)
        if "index.csv" in u:
            return httpx.Response(200, text="Company Name,Industry,Symbol,Series,ISIN Code\nSample Limited,Things,SAMPLE,EQ,INE000A01010\n")
        if "integrated-filing-results" in u:
            return httpx.Response(200, json={"data": []})
        if "holiday-master" in u:
            return httpx.Response(200, json={"CM": []})
        if u.startswith("https://official.test/"):
            state.setdefault("gets", []).append(u)
            return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"}) if not u.endswith("/gone") else httpx.Response(404)
        if "googleapis.com/youtube/v3/search" in u or "youtube/v3/channels" in u or "youtube/v3/playlistItems" in u or ("youtube/v3/videos" in u and "statistics" in u):
            return api(req)
        if "upload/youtube/v3/videos" in u:
            state["meta"] = json.loads(req.content)
            return httpx.Response(200, headers={"Location": "https://upload.test/s1"})
        if u.startswith("https://upload.test/"):
            return httpx.Response(200, json={"id": "vid1"})
        if "youtube/v3/videos" in u and req.method == "PUT":
            state["update"] = json.loads(req.content)
            return httpx.Response(200, json={"id": "vid1"})
        return httpx.Response(404)
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def crew_env(tmp_path, monkeypatch, now, kind="topic", model=None, topics=(TP, TP2), **raw):
    monkeypatch.setattr(youtube, "ROOT", tmp_path)
    monkeypatch.setattr(oauth, "TOKENS", tmp_path / "tokens.json")
    monkeypatch.setattr(market_crew, "now_ist", lambda: now)
    monkeypatch.setattr(market_crew, "now_hm", lambda: "23:30")
    monkeypatch.setattr(youtube, "_now", lambda: now.timestamp())
    monkeypatch.setattr(lessons, "TOPICS", list(topics))
    monkeypatch.setattr(youtube, "next_slot", lambda store, ch, now_=None, fmt="short": datetime(2026, 10, 20, 10, 0, tzinfo=IST).timestamp())          # a Tuesday release

    async def token(account, provider, client=None):
        return "tok"
    monkeypatch.setattr(oauth, "access_token", token)
    state = {}
    full = {**RAW, "pattern": {"tue": "topic"}, "lessons": True, "lesson_shorts": True, "lesson_channels": ["Good Channel"], "transcripts_per_day": 2, **raw}
    ch = youtube.channel(full)
    fetched = []

    def tx(vid):
        fetched.append(vid)
        return f"Everyone asks whether an FD is safe, in transcript {vid}. Sample Limited share price will rise, they say. Please like and subscribe."

    async def nap(s):
        return None
    d = Director(ch["director"], market_crew.crew(ch, client_factory=web(state), synth=tone, pictures=pictures, transcript_fetch=tx, sleep=nap), reporter="Market Analytics")
    m = Master("youtube", "YOUTUBE MANAGER", [Stage("CHANNELS", [d])], reporter=ch["director"], mode="live")
    cfg = Config(masters={"youtube": {"mode": "live", "options": {"channels": [full]}}})
    m.services.update(llm=model or Model(), cfg=cfg)
    return m, state, EventBus(), Store(tmp_path / f"c{time.time_ns()}.db"), fetched, ch


def agents(bus):
    return {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}


@FFMPEG
def test_a_topic_night_makes_a_lesson_from_the_official_page_and_it_always_waits_for_approval(tmp_path, monkeypatch):
    for privacy in ("approval", "scheduled"):                                         # even a channel set to publish by itself never publishes a lesson without a yes
        m, state, bus, store, fetched, ch = crew_env(tmp_path, monkeypatch, datetime(2026, 10, 17, 12, 0, tzinfo=IST), privacy=privacy, report_privacy="scheduled")
        asyncio.run(m.cycle(bus, store))
        crew = agents(bus)
        assert [crew[n]["status"] for n in ("Results Scout", "Market Analyst", "Tanglish Writer", "Voice Clone", "Slide Editor", "Market Uploader")] == ["done"] * 6, crew
        rec, = store.kv_list(youtube.LOG)
        assert rec["kind"] == "lesson" and rec["format"] == "long" and rec["status"] == "awaiting" and rec["topic"] == "fd-test" and rec["title"] == "How does a bank FD work?"
        assert rec["sources"] == [{"label": "RBI FAQ on deposits", "url": "https://official.test/fd"}] and rec["lines_dropped"] == 0 and rec["voice"] == "clone"
        assert [i["title"] for i in rec["inspired"]] == ["FD vs RD explained", "Fixed deposit rates explained"] and fetched == ["v1", "v2"] and len(state["gets"]) == 2
        assert rec["summary"].endswith(market_crew.DISCLAIMER) and "Sources:\nRBI FAQ on deposits: https://official.test/fd" in rec["summary"]
        assert "FD vs RD explained" not in rec["summary"] and "Good Channel" not in rec["summary"] and all("FD vs RD" not in ln["say"] for ln in SEEN["lines"])
        meta = state["meta"]
        assert meta["status"]["privacyStatus"] == "private" and "publishAt" not in meta["status"] and meta["snippet"]["description"] == rec["summary"]
        ap, = store.pending_approvals()
        assert ap["payload"]["kind"] == "yt_publish" and any(b.startswith("source: RBI FAQ on deposits") for b in ap["payload"]["backed"]) \
            and any(b.startswith("inspired by: FD vs RD explained") for b in ap["payload"]["backed"])
        assert store.kv_has(market_crew.DONE, "lesson:fd-test") and SEEN["tall"] is False and SEEN["deck"][0] == market.NOTICE
        assert not youtube.promises(rec["title"]) and not market.ADVICE.search(rec["title"])
        again = asyncio.run(m.cycle(bus, store))                                       # the same night again: the lesson awaits approval, nothing more is made
        assert len(store.kv_list(youtube.LOG)) == 1
        store.close() if hasattr(store, "close") else None
        shutil.rmtree(tmp_path / "data", ignore_errors=True)


@FFMPEG
def test_a_night_whose_topics_all_lack_a_source_makes_nothing_and_skips_them_for_days(tmp_path, monkeypatch):
    dead = lessons.topic("dead", "Fixed deposit basics", "x", "g", [{"label": "gone", "url": "https://official.test/gone"}], ["fixed deposit"])
    m, state, bus, store, fetched, ch = crew_env(tmp_path, monkeypatch, datetime(2026, 10, 17, 12, 0, tzinfo=IST), topics=(dead,))
    asyncio.run(m.cycle(bus, store))
    crew = agents(bus)
    assert crew["Market Analyst"]["label"] == "NO SOURCE" and store.kv_get(lessons.DONE, "lessonskip:dead")["skipped"] == "no source" and crew["Results Scout"]["label"] == "FOUND"
    assert [v for v in store.kv_list(youtube.LOG) if v.get("kind") == "lesson"] == []


@FFMPEG
def test_too_thin_skips_the_topic_and_the_next_one_is_tried_but_never_more_than_two(tmp_path, monkeypatch):
    class First(Model):
        """Everything the first topic's requests return is thin; the second topic's lessons are good."""
        async def json(self, prompt, **kw):
            if "You plan a short lesson" in prompt:
                self.which = "second" if "Recurring deposit basics" in prompt else "first"
                self.slide = 0
                return self.plan
            if "ONE slide" in prompt and getattr(self, "which", "") == "first":
                return {"lines": [GOOD["def"]]}
            return await super().json(prompt, **kw)
    m, state, bus, store, fetched, ch = crew_env(tmp_path, monkeypatch, datetime(2026, 10, 17, 12, 0, tzinfo=IST), model=First())
    asyncio.run(m.cycle(bus, store))
    rec, = store.kv_list(youtube.LOG)
    assert rec["topic"] == "rd-test" and store.kv_get(lessons.DONE, "lessonskip:fd-test")["skipped"] == "too thin" and store.kv_has(market_crew.DONE, "lesson:rd-test")
    assert agents(bus)["Tanglish Writer"]["label"] == "WRITTEN"


@FFMPEG
def test_a_saturday_morning_makes_a_lesson_short_that_waits_for_approval_and_goes_out_at_9(tmp_path, monkeypatch):
    now = datetime(2026, 10, 17, 7, 20, tzinfo=IST)                                    # a Saturday inside the morning window
    plan = {"title": "What is an RD?", "concept": "recurring deposit", "slides": [{"kind": "points", "heading": "RD", "icon": "calendar", "items": ["Fixed amount monthly", "Agreed period"]}]}
    model = Model(plan=plan, per_slide=[[GOOD["rd"], GOOD["month"], GOOD["def"], GOOD["pre"]]])
    m, state, bus, store, fetched, ch = crew_env(tmp_path, monkeypatch, now, model=model, report_privacy="scheduled")
    asyncio.run(m.cycle(bus, store))
    crew = agents(bus)
    assert crew["Results Scout"]["label"] == "FOUND" and "lesson Short" in crew["Results Scout"]["summary"]
    rec, = store.kv_list(youtube.LOG)
    assert rec["kind"] == "lesson_short" and rec["format"] == "short" and rec["status"] == "awaiting" and rec["window"] == "premarket" and rec["date"] == "2026-10-17"
    assert rec["title"] == "What is an RD? #Shorts" and "#Shorts" in rec["hashtags"] and rec["concept"] == "recurring deposit" and rec["summary"].endswith(market_crew.DISCLAIMER)
    assert SEEN["tall"] is True and SEEN["frame"]["top"] == market.SHORT_NOTE and market.NOTICE not in SEEN["deck"] and SEEN["lines"][-1]["say"] == market.SUBSCRIBE_SHORT
    assert state["meta"]["status"]["privacyStatus"] == "private" and "publishAt" not in state["meta"]["status"]
    assert store.pending_approvals()[0]["payload"]["kind"] == "yt_publish" and store.kv_has(market_crew.DONE, "lesson_short:premarket:2026-10-17")
    assert store.kv_get(market_crew.DONE, "lessonshort:fd-test")["concepts"] == ["recurring deposit"]
    asyncio.run(m.cycle(bus, store))                                                   # once per window per date
    assert len(store.kv_list(youtube.LOG)) == 1
    ap = store.pending_approvals()[0]
    store.decide_approval(ap["id"], "approved")
    said = asyncio.run(youtube.publish_decision(store.get_approval(ap["id"]), "approved", {"store": store, "cfg": m.services["cfg"], "bus": bus, "client_factory": web(state)}))
    assert datetime.fromtimestamp(state["update"]["status"]["publishAt"] and datetime.strptime(state["update"]["status"]["publishAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp(), IST).strftime("%H:%M") == "09:00"
    assert said.startswith("Scheduled for ")


@FFMPEG
def test_a_lesson_short_that_misses_its_day_stays_private_and_the_market_days_keep_their_reports(tmp_path, monkeypatch):
    now = datetime(2026, 10, 17, 7, 20, tzinfo=IST)
    m, state, bus, store, fetched, ch = crew_env(tmp_path, monkeypatch, now)
    monkeypatch.setattr(youtube, "_now", lambda: datetime(2026, 10, 18, 1, 0, tzinfo=IST).timestamp())                 # the next Indian date
    asyncio.run(m.cycle(bus, store))
    rec, = store.kv_list(youtube.LOG)
    assert rec["kind"] == "lesson_short" and rec["status"] == "stale" and store.pending_approvals() == []
    m, state, bus, store, fetched, ch = crew_env(tmp_path, monkeypatch, datetime(2026, 10, 16, 12, 0, tzinfo=IST), lesson_shorts=False)          # lesson_shorts off, a Friday noon
    assert market_crew.report_window(datetime(2026, 10, 17, 7, 20, tzinfo=IST)) == "premarket"
    scout = market_crew.ResultsScout(ch, client_factory=web(state))
    ctx = {"store": store, "bus": bus, "reason": "schedule", "now": datetime(2026, 10, 17, 7, 20, tzinfo=IST)}
    res = asyncio.run(scout.run(ctx))
    assert res.label == "NO MARKET" and "job" not in ctx


def test_no_usable_page_hands_the_night_back_to_the_scouts_fallback_result(tmp_path, monkeypatch):
    dead = lessons.topic("dead", "Fixed deposit basics", "x", "g", [{"label": "gone", "url": "https://official.test/gone"}], ["fixed deposit"])
    m, state, bus, store, fetched, ch = crew_env(tmp_path, monkeypatch, datetime(2026, 10, 17, 12, 0, tzinfo=IST), topics=(dead,))
    analyst = market_crew.MarketAnalyst(ch, client_factory=web(state), sleep=lambda s: asyncio.sleep(0))
    fallback = {"kind": "result", "symbol": "SAMPLE", "key": "SAMPLE:Q2 FY27", "more": []}
    ctx = {"store": store, "bus": bus, "job": {"kind": "lesson", "topic": None, "day": "2026-10-20", "fallback": fallback}}
    assert asyncio.run(analyst.lesson(ctx, ctx["job"])) is None and ctx["job"] is fallback                               # the result flow carries on
    assert store.kv_get(lessons.DONE, "lessonskip:dead")["skipped"] == "no source"
    ctx = {"store": store, "bus": bus, "job": {"kind": "lesson", "topic": "dead", "day": "2026-10-20", "fallback": None}}
    res = asyncio.run(analyst.lesson(ctx, ctx["job"]))
    assert (res.status, res.label) == ("wait", "NO SOURCE") and "job" not in ctx


def test_lines_the_checks_throw_out_are_asked_for_again_with_the_reason_for_each():
    plan = {"title": "FD basics", "slides": [PLAN["slides"][0]]}
    english = line("டெர்ம் டெபாசிட் ஒரு lump sum ஒப்பந்தம் ஒரு குறிப்பிட்ட காலத்துக்கு தான்.", GOOD["def"]["en"], Q_DEF)
    future = line(GOOD["def"]["say"] + " அது இருக்கும்.", GOOD["def"]["en"][:-1] + ", so the bank will keep the money.", Q_DEF)
    model = Model(plan=plan, per_slide=[[english, future, GOOD["def"]], [GOOD["rd"], GOOD["month"], GOOD["rest"]]])
    out = asyncio.run(lessons.write(model, TP, pages(), [], BAD, short=True))
    assert [l["say"] for l in out["lines"][:-1]] == [GOOD[k]["say"] for k in ("def", "rd", "month", "rest")] and out["kept"] == 4 and out["proposed"] == 6
    assert [d["why"] for d in out["dropped"]] == ["spoken line is not all Tamil script", "forecast wording"]
    assert model.calls.count("lines") == 2 and "these are not in Tamil letters: lump, sum" in model.slide_prompt and 'the word "இருக்கும்" is not allowed' in model.slide_prompt


def test_a_spent_writer_allowance_is_a_wait_not_a_reason_to_skip_the_topic(tmp_path, monkeypatch):
    class Spent(Model):
        async def json(self, prompt, **kw):
            raise httpx.HTTPStatusError("429 Too Many Requests", request=httpx.Request("POST", "https://api.groq.com/x"), response=httpx.Response(429))
    with pytest.raises(lessons.Busy):
        asyncio.run(lessons.write(Spent(), TP, pages(), [], BAD))
    m, state, bus, store, fetched, ch = crew_env(tmp_path, monkeypatch, datetime(2026, 10, 17, 12, 0, tzinfo=IST), model=Spent())
    asyncio.run(m.cycle(bus, store))
    assert agents(bus)["Tanglish Writer"]["label"] == "WRITER BUSY" and store.kv_get(lessons.DONE, "lessonskip:fd-test") is None and store.kv_list(youtube.LOG) == []


def test_a_company_name_or_symbol_of_the_index_is_caught_but_a_plain_word_like_bank_is_not():
    bad = lessons.bad_pattern(["Bank of India Limited", "Tata Consultancy Services Limited", "Bank Limited", "Power Limited"], ["TCS", "SBIN", "AB"])
    for hit in ("Bank of India pays 4 percent.", "tata consultancy services is large", "TCS reported results", "Open an account with HDFC", "Buy it", "Sensex fell"):
        assert bad.search(hit), hit
    for fine in ("A bank pays interest on a deposit.", "Banks insure deposits up to Rs.5 lakh.", "Power of compounding", "The ab test", "A fixed deposit is a contract."):
        assert not bad.search(fine), fine
    assert lessons.trim("Tata Consultancy Services Limited") == "Tata Consultancy Services" and lessons.trim("Page Industries Ltd.") == "Page Industries"


def test_indian_amounts_are_compared_as_figures():
    assert lessons.figs("insured up to Rs.5,00,000") == lessons.figs("insured up to 5 lakh") == lessons.figs("5 லட்சம் ரூபாய்") == {"500000"}
    assert lessons.figs("Rs. 2 crore and 75 %") == {"20000000", "75"} and lessons.figs("1.5 lakh") == {"150000"}
    assert why({**GOOD["ins"], "en": GOOD["ins"]["en"].replace("Rs.5 lakh", "Rs.5,00,000")}) == ""


def test_english_words_left_in_latin_letters_are_written_as_a_tamil_speaker_says_them_and_unknown_ones_stay():
    assert lessons.tamilise("NAV-ல FD-யில் lock-in unit loan SIP, SEBI") == "என்ஏவி-ல எஃப்டி-யில் லாக்-இன் யூனிட் லோன் எஸ்ஐபி, செபி"
    assert clone.unspelt(lessons.tamilise("NAV-ல FD-யில் lock-in unit loan SIP")) == []
    assert lessons.tamilise("exit load a quokka") == "எக்ஸிட் லோட் a quokka"                       # a word it does not know stays, and check_line then refuses the line
    line_in_latin = {**GOOD["def"], "say": GOOD["def"]["say"].replace("டெர்ம் டெபாசிட்னா", "FD டெபாசிட்னா")}
    assert why(line_in_latin) == "spoken line is not all Tamil script" and why({**line_in_latin, "say": lessons.tamilise(line_in_latin["say"])}) == ""


def test_a_quote_is_found_even_when_the_writer_left_out_a_parenthetical_or_wrote_the_rupee_another_way():
    page = lessons.squash("Each depositor in a bank is insured upto a maximum of ₹ 5,00,000 (Rupees Five Lakhs) for both principal and interest amount held by him.")
    q = "Each depositor in a bank is insured upto a maximum of Rs. 5,00,000 for both principal and interest amount held by him."
    assert lessons.squash(q) in page and lessons.squash("Each depositor in a bank is insured upto a maximum of `5,00,000 for both principal and interest") in page
    assert lessons.squash("Each depositor is insured upto a maximum of Rs. 6,00,000 for both principal and interest") not in page
    assert lessons.figs("up to ₹ five lakhs") == {"500000"} and lessons.figs("two crore") == {"20000000"}


def test_every_reason_a_line_can_be_thrown_out_for_has_an_explanation_for_the_writer():
    seen = set()
    for item in ({"say": "ஒரு ஒப்பந்தம் வித் வித் வித் டெர்ம் டெபாசிட் பேங்க்.", "en": "x"}, {"say": "டெர்ம் டெபாசிட் என்பது இடையில ஒரு ஒப்பந்தம் பேங்க் கஸ்டமர்.", "en": "x"}, {"say": "bank டெபாசிட் ஒப்பந்தம் இது ஒரு", "en": "x"}):
        seen.add(lessons.explain(item, why(item) or "a garbled line (a word repeated)"))
    for reason in ("spoken line is not all Tamil script", "the voice would garble an English word", "forecast wording", "advice or rude wording", "quote is not in the source", "a number is not in the quotes",
                   "the Tamil and the English caption give different numbers", "names a company or the market", "the caption says more than its quotes do", "book Tamil, not the way the host speaks",
                   "a garbled line (a word repeated)", "a line of the wrong length", "a near copy of a transcript"):
        item = {"say": "டெர்ம் டெபாசிட் என்பது bank ₹ ஒப்பந்தம் இது ஒரு இருக்கும்", "en": "You should buy it, it will help"}
        assert lessons.explain(item, reason), reason


def test_a_slide_shows_only_items_a_sentence_of_the_pages_holds():
    sets = lessons.sentence_sets(pages())
    plan = {"title": "FD", "slides": [
        {"kind": "points", "heading": "Good", "items": ["Term deposit is a contract with the bank", "RD has no withdrawal until the term ends", "Interest payable at quarterly or longer rests", "Money is always safe"]},
        {"kind": "facts", "heading": "Figures", "rows": [{"label": "RD lock", "value": "no withdrawal", "note": "penalty if early"}, {"label": "Interest", "value": "fixed", "note": "as per bank"}]},
        {"kind": "points", "heading": "Invented", "items": ["Monthly deposits earn most interest", "Lock-in of seven years"]}]}
    _, got = lessons.plan_slides(plan, OFFICIAL, False, sets)
    assert [s["title"] for s in got] == ["Good"] and [i["text"] for i in got[0]["items"]] == ["Term deposit is a contract with the bank", "Interest payable at quarterly or longer rests"]
    assert lessons.fit("Fixed deposit vs recurring deposit", 26) == "Fixed deposit vs recurring" and lessons.fit("SIP vs lump sum", 26) == "SIP vs lump sum"
