"""Mani Market Tamil's pre-market and post-market Shorts: the index maths, freshness, the Indian-time windows, the script's rules, the slides, the release rules."""

import asyncio
import json
import re
import shutil
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from PIL import Image
from test_market_crew import RAW, tone

from vision.agents import Director, Master, Stage
from vision.bus import EventBus, Store
from vision.config import Config
from vision.masters import market, market_crew, slides, youtube
from vision.orchestrator import run_time
from vision.services import lmstudio, oauth, world
from vision.voice import clone

FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
IST, TORONTO = ZoneInfo("Asia/Kolkata"), ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 14, 7, 2, tzinfo=IST)               # a Wednesday, inside the pre-market window

OWNER_EN = ("Disclaimer: The content on Mani Market Tamil is for educational and informational purposes only, not investment advice. We are not SEBI-registered "
            "Investment Advisers or Research Analysts. Investments are subject to market risks. Please do your own research or consult a registered professional "
            "before investing. All investment decisions and their outcomes are your responsibility.")
OWNER_TA = ("மறுப்பு அறிவிப்பு: Mani Market Tamil சேனலில் பகிரப்படும் தகவல்கள் கல்வி மற்றும் தகவல் நோக்கத்திற்காக மட்டுமே; முதலீட்டு ஆலோசனை அல்ல. நாங்கள் SEBI-யில் "
            "பதிவு செய்யப்பட்ட முதலீட்டு ஆலோசகர்களோ அல்லது ஆராய்ச்சி ஆய்வாளர்களோ அல்ல. முதலீடுகள் சந்தை அபாயங்களுக்கு உட்பட்டவை. முதலீடு செய்வதற்கு முன் சொந்தமாக "
            "ஆராய்ச்சி செய்யவும் அல்லது பதிவு செய்யப்பட்ட நிபுணரின் ஆலோசனையைப் பெறவும். உங்கள் முதலீட்டு முடிவுகளுக்கு நீங்களே பொறுப்பு.")


def epoch(d: str, hm: str, tz: str) -> int:
    return int(datetime.fromisoformat(f"{d}T{hm}").replace(tzinfo=ZoneInfo(tz)).timestamp())


def chart(tz: str, bars: list[tuple[str, float]], rmt: int, start: int, end: int, price: float | None = None, prev_range: float = 1.0) -> dict:
    """A Yahoo chart answer. chartPreviousClose is the close before the range (prev_range): it must never be used."""
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price if price is not None else bars[-1][1], "regularMarketTime": rmt, "exchangeTimezoneName": tz,
                                           "chartPreviousClose": prev_range, "currentTradingPeriod": {"regular": {"start": start, "end": end}}},
                                  "timestamp": [epoch(d, "10:00", tz) for d, _ in bars], "indicators": {"quote": [{"close": [c for _, c in bars]}]}}]}}


def move(name="X", pct=1.0, day=date(2026, 10, 13), session="closed", key="spx", **more):
    return {"name": name, "last": 100 * (1 + pct / 100), "prev_close": 100.0, "change": pct, "pct": pct, "day": day, "as_of": datetime.combine(day, datetime.min.time(), IST),
            "session": session, "say": name, "key": key, **more}


# ---- the index maths -----------------------------------------------------------------------------------------------------------------------------

def test_a_closed_session_is_the_last_close_against_the_one_before_never_chart_previous_close():
    res = chart("America/New_York", [("2026-10-12", 7807.24), ("2026-10-13", 7805.45)], epoch("2026-10-13", "16:10", "America/New_York"),
                epoch("2026-10-14", "09:30", "America/New_York"), epoch("2026-10-14", "16:00", "America/New_York"), prev_range=7818.93)["chart"]["result"][0]
    m = world.index_move(res, "S&P 500", NOW.timestamp())
    assert (m["session"], m["day"], m["prev_close"], m["last"]) == ("closed", date(2026, 10, 13), 7807.24, 7805.45)
    assert m["change"] == pytest.approx(-1.79) and m["pct"] == pytest.approx(-0.0229, abs=1e-3)     # against 7818.93 it would be -0.17 %


def test_a_live_session_is_the_live_price_against_the_previous_daily_close():
    now = NOW.timestamp()
    res = chart("Asia/Tokyo", [("2026-10-13", 67777.5), ("2026-10-14", 68000.0)], int(now) - 300, int(now) - 3600, int(now) + 3600, price=68073.8, prev_range=70035.7)["chart"]["result"][0]
    m = world.index_move(res, "Nikkei 225", now)
    assert (m["session"], m["day"], m["prev_close"], m["last"]) == ("live", date(2026, 10, 14), 67777.5, 68073.8) and m["pct"] == pytest.approx(0.437, abs=1e-3)
    old = chart("Asia/Tokyo", [("2026-10-13", 67777.5), ("2026-10-14", 68000.0)], int(now) - 5000, int(now) - 9000, int(now) + 3600, price=68073.8)["chart"]["result"][0]
    assert world.index_move(old, "Nikkei 225", now)["session"] == "closed"          # a quote that old inside the hours is not live
    assert world.index_move({"meta": {"regularMarketTime": 1}, "timestamp": [], "indicators": {"quote": [{"close": []}]}}, "x", now) is None


def test_gift_nifty_and_nse_indices_are_read_from_nses_own_fields():
    g = world.gift_nifty({"giftnifty": {"LASTPRICE": 22757.5, "DAYCHANGE": -16, "PERCHANGE": -0.07, "TIMESTMP": "14-Oct-2026 07:14"}})
    assert (g["last"], g["change"], g["pct"], g["day"], g["as_of"].hour) == (22757.5, -16.0, -0.07, date(2026, 10, 14), 7) and g["prev_close"] == 22773.5
    assert world.gift_nifty({}) is None and world.gift_nifty({"giftnifty": {"TIMESTMP": "x"}}) is None
    allx = {"timestamp": "13-Oct-2026 15:30", "data": [{"index": "NIFTY 50", "last": 22721.95, "variation": 358.6, "percentChange": 1.6, "previousClose": 22363.35, "advances": "46", "declines": "4"},
                                                    {"index": "NIFTY BANK", "last": 55481.05, "variation": 563.05, "percentChange": 1.03, "previousClose": 54918, "advances": "12", "declines": "2"}]}
    n = world.nse_indices(allx)
    assert (n["nifty"]["advances"], n["nifty"]["declines"], n["nifty"]["session"], n["banknifty"]["pct"]) == (46, 4, "closed", 1.03) and world.nse_indices({}) == {}


# ---- freshness and the skip rules ---------------------------------------------------------------------------------------------------------------

TODAY = date(2026, 10, 14)
YEST = date(2026, 10, 13)


def moves_pre(**over):
    out = {k: move(v[1], 0.3, YEST, key=k) for k, v in world.INDICES.items() if v[3] in ("us", "europe")}
    out.update({k: move(v[1], 0.2, TODAY, "live", key=k) for k, v in world.INDICES.items() if v[3] == "asia"})
    out.update(over)
    return out


def gift(day=TODAY, at=NOW - timedelta(minutes=2)):
    return move("GIFT Nifty", -0.1, day, "live", key="gift", as_of=at)


def test_stale_indices_are_left_out_and_named_never_shown():
    d = world.assemble("pre", TODAY, moves_pre(spx=move("S&P 500", 1.0, date(2026, 10, 12)), n225=move("Nikkei 225", 0.5, YEST, "closed", key="n225"), ks11=None), gift(), NOW)
    names = {i["name"] for r in d["regions"] for i in r["items"]}
    assert "S&P 500" not in names and "Nikkei 225" not in names and "Kospi" not in names and "Dow Jones" in names and "GIFT Nifty" in names
    why = {x["name"]: x["why"] for x in d["dropped"]}
    assert "12 Oct" in why["S&P 500"] and "14 Oct" in why["Nikkei 225"] and why["Kospi"] == "no data" and d["skip"] == ""
    assert [r["id"] for r in d["regions"]] == ["us", "europe", "asia", "india"]


def test_the_us_and_europe_are_told_by_the_last_weekday_session_before_today():
    assert world.fresh_day("pre", "us", date(2026, 10, 12)) == date(2026, 10, 9) and world.fresh_day("pre", "europe", TODAY) == YEST
    assert world.fresh_day("pre", "asia", TODAY) == TODAY and all(world.fresh_day("post", r, TODAY) == TODAY for r in ("india", "asia", "europe"))
    monday = date(2026, 10, 12)                                     # on a Monday the US is told by Friday's session, a Saturday's would be stale
    d = world.assemble("pre", monday, {k: move(v[1], 0.1, date(2026, 10, 9), key=k) for k, v in world.INDICES.items() if v[3] in ("us", "europe")},
                       gift(monday, datetime(2026, 10, 12, 7, 0, tzinfo=IST)), datetime(2026, 10, 12, 7, 2, tzinfo=IST))
    assert {r["id"] for r in d["regions"]} == {"us", "europe", "india"}


def test_a_premarket_short_needs_a_fresh_gift_nifty_and_two_regions():
    assert world.assemble("pre", TODAY, moves_pre(), None, NOW)["skip"].startswith("GIFT Nifty")
    assert world.assemble("pre", TODAY, moves_pre(), gift(YEST), NOW)["skip"].startswith("GIFT Nifty")                                   # yesterday's print
    assert world.assemble("pre", TODAY, moves_pre(), gift(at=NOW - timedelta(hours=4)), NOW)["skip"].startswith("GIFT Nifty")           # today's, but hours old
    d = world.assemble("pre", TODAY, moves_pre(), gift(at=NOW - timedelta(hours=4)), NOW)
    assert any(x["name"] == "GIFT Nifty" for x in d["dropped"])
    only = world.assemble("pre", TODAY, {}, gift(), NOW)
    assert only["skip"] == "fewer than two regions have fresh figures" and len(only["regions"]) == 1
    two = world.assemble("pre", TODAY, {"spx": move("S&P 500", 0.5, YEST, key="spx")}, gift(), NOW)
    assert two["skip"] == "" and [r["id"] for r in two["regions"]] == ["us", "india"]


def test_a_postmarket_short_needs_nifty_and_sensex_from_today_and_drops_empty_regions():
    india = {"nifty": move("Nifty 50", 1.6, TODAY, key="nifty", advances=46, declines=4), "sensex": move("Sensex", 1.5, TODAY, key="sensex"), "banknifty": move("Bank Nifty", 1.0, TODAY, key="banknifty")}
    asia = {k: move(v[1], 0.4, TODAY, key=k) for k, v in world.INDICES.items() if v[3] == "asia"}
    ok = world.assemble("post", TODAY, {**india, **asia}, None, NOW)
    assert ok["skip"] == "" and [r["id"] for r in ok["regions"]] == ["india", "asia"] and {x["name"] for x in ok["dropped"]} == {"FTSE 100", "DAX", "CAC 40"}     # Europe has no figure today
    assert world.assemble("post", TODAY, {**india, "sensex": None, **asia}, None, NOW)["skip"].startswith("Nifty 50 or Sensex")
    assert world.assemble("post", TODAY, {**india, "nifty": move("Nifty 50", 1.6, YEST, key="nifty"), **asia}, None, NOW)["skip"].startswith("Nifty 50 or Sensex")
    assert world.assemble("post", TODAY, india, None, NOW)["skip"] == "fewer than two regions have fresh figures"


def test_a_trading_day_is_monday_to_friday_and_not_an_nse_holiday(tmp_path):
    hol = {date(2026, 1, 26)}
    assert world.trading_day(date(2026, 10, 14), hol) and not world.trading_day(date(2026, 1, 26), hol) and not world.trading_day(date(2026, 10, 10), hol) and not world.trading_day(date(2026, 10, 11), hol)
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, json={"CBM": [], "CM": [{"tradingDate": "26-Jan-2026"}, {"tradingDate": "25-Dec-2026"}, {"tradingDate": "junk"}]})
    store = Store(tmp_path / "h.db")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await world.trading_holidays(c, store), await world.trading_holidays(c, store)
    first, second = asyncio.run(go())
    assert first == second == {date(2026, 1, 26), date(2026, 12, 25)} and len(calls) == 1          # kept a week: one read


# ---- the Scout's windows (Indian time, across a Toronto daylight-saving change) ---------------------------------------------------------------------

def test_the_scouts_windows_follow_the_indian_clock_whatever_the_macs_daylight_saving_does():
    at = lambda *a: datetime(*a, tzinfo=TORONTO)
    # the US clocks go back on 1 Nov 2026: 07:02 IST is 21:32 EDT before it and 20:32 EST after it; 18:02 IST is 08:32 EDT, then 07:32 EST
    assert market_crew.report_window(at(2026, 10, 31, 21, 32)) == "premarket" and market_crew.report_window(at(2026, 11, 2, 20, 32)) == "premarket"
    assert market_crew.report_window(at(2026, 10, 31, 8, 32)) == "postmarket" and market_crew.report_window(at(2026, 11, 2, 7, 32)) == "postmarket"
    assert market_crew.report_window(at(2026, 11, 2, 22, 0)) == "" and market_crew.report_window(at(2026, 10, 31, 22, 0)) == "premarket"      # 22:00 Toronto is 08:30 IST after the change, 07:30 IST before it
    assert market_crew.report_window(at(2026, 11, 2, 12, 0)) == "" and market_crew.report_window(NOW.replace(hour=8, minute=15)) == "" and market_crew.report_window(NOW.replace(hour=7, minute=0)) == "premarket"
    assert [market_crew.report_window(NOW.replace(hour=h, minute=m)) for h, m in ((17, 59), (18, 0), (20, 29), (20, 30))] == ["", "postmarket", "postmarket", ""]


def test_run_at_takes_a_time_with_a_zone_and_keeps_the_old_form(tmp_path):
    assert run_time("05:00") == (5, 0, None) and run_time("07:02 Asia/Kolkata") == (7, 2, ZoneInfo("Asia/Kolkata")) and run_time(" 18:02  Asia/Kolkata ")[:2] == (18, 2)
    from vision.masters import build_masters
    from vision.orchestrator import Orchestrator
    cfg = Config(only_masters=["youtube"], masters={"youtube": {"mode": "live", "run_at": ["05:00", "07:02 Asia/Kolkata"], "cycle_minutes": 360}})

    async def jobs():
        orch = Orchestrator(cfg, build_masters(cfg), EventBus(), Store(tmp_path / "r.db"))
        orch.start_schedules()
        found = {j.id: j.trigger for j in orch.scheduler.get_jobs()}
        orch.scheduler.shutdown(wait=False)
        orch._watch.cancel()
        return found
    found = asyncio.run(jobs())
    assert "hour='5', minute='0'" in str(found["at:youtube:05:00"]) and "hour='7', minute='2'" in str(found["at:youtube:07:02 Asia/Kolkata"])
    assert str(found["at:youtube:07:02 Asia/Kolkata"].timezone) == "Asia/Kolkata" and str(found["at:youtube:05:00"].timezone) != "Asia/Kolkata"


# ---- the script: figures only, never a forecast -------------------------------------------------------------------------------------------------

def data_for(kind: str, pcts: dict[str, float], drop: tuple = (), session: str = "closed") -> dict:
    pre = kind == "premarket"
    day = TODAY
    mv = {}
    for k, (_, name, say, region) in world.INDICES.items():
        if k in drop or (pre and region == "india") or (not pre and region == "us") or (not pre and k in ("us",)):
            continue
        d = YEST if pre and region in ("us", "europe") else day
        mv[k] = move(name, pcts.get(k, pcts.get("all", 0.4)), d, "live" if region == "asia" and pre or region == "europe" and not pre else session, key=k)
        mv[k]["say"] = say
    if not pre:
        mv["nifty"].update(advances=30, declines=20)
    gf = gift() if pre and "gift" not in drop else None
    if gf:
        gf["pct"] = pcts.get("gift", pcts.get("all", 0.4))
        gf["change"] = gf["pct"] * 227
    d = world.assemble("pre" if pre else "post", day, {k: v for k, v in mv.items()}, gf, NOW)
    for r in d["regions"]:
        for i in r["items"]:
            i["say"] = i.get("say") or world.INDICES.get(i["key"], ("", "", i["name"]))[2]
    return d


SHAPES = {"all up": {"all": 0.8}, "all down": {"all": -0.9}, "flat": {"all": 0.01}, "big up": {"all": 2.1}, "big down": {"all": -3.2}, "mixed": {"spx": 1.7, "dji": -0.2, "ixic": 0.0, "n225": -1.8, "gift": 0.6}}


@pytest.mark.parametrize("kind", ["premarket", "postmarket"])
@pytest.mark.parametrize("shape", list(SHAPES))
def test_no_template_line_can_forecast_advise_or_hold_english_letters(kind, shape):
    data = data_for(kind, SHAPES[shape])
    assert data["skip"] == "" and data["regions"]
    deck = market.report_deck(kind, data)
    said = market.report_react(market.report_lines(kind, data, deck), turn=3)
    assert 5 <= len(said) <= 12 and said[0]["show"] == 0 and said[-1]["say"] == market.SIGN_OFF and said[-1]["show"] == len(deck[0]["items"])
    for ln in said:
        assert not market.FORECAST.search(ln["say"]) and not market.ADVICE.search(ln["say"]), ln["say"]
        assert clone.unspelt(ln["say"]) == [], (ln["say"], clone.unspelt(ln["say"]))
        assert 0 <= ln["show"] <= len(deck[0]["items"]) and ln["slide"] == 0
    shows = [ln["show"] for ln in said]
    assert shows == sorted(shows)                                  # the picture only ever adds blocks


def test_a_region_with_no_fresh_index_is_not_in_the_script_or_the_slide():
    data = data_for("premarket", {"all": 0.5}, drop=("spx", "dji", "ixic"))
    deck, said = market.report_deck("premarket", data), None
    assert [b["region"] for b in deck[0]["items"]] == ["Europe", "Asia", "India"]
    said = market.report_lines("premarket", data, deck)
    assert not any("US" in ln["say"] for ln in said)
    assert market.report_deck("postmarket", data_for("postmarket", {"all": 0.5}))[0]["title"] == "Post-Market · 14 Oct"
    assert deck[0]["title"] == "Pre-Market · 14 Oct"


def test_the_words_the_rule_forbids_do_match_and_every_reaction_used_is_safe():
    for bad in ("Nifty will open higher", "gap-up opening", "expect a rally", "the target is 23000", "watch the 22500 level", "நாளை open ஆகும்", "எதிர்பார்க்கலாம்", "support at 22000", "resistance near 23000", "அடுத்த வாரம்"):
        assert market.FORECAST.search(bad), bad
    for ok in (market.SIGN_OFF, "Nifty 22722-ல close ஆச்சு. 359 points ஏற்றம், அதாவது 1.6 percent.", "Dow Jones 0.35 percent இறங்கி close ஆச்சு."):
        assert not market.FORECAST.search(ok)
    for tone_ in ("good", "bad"):
        safe = [t for t in market.REACT[tone_] if not market.FORECAST.search(t) and not market.ADVICE.search(t) and not clone.unspelt(t.format(name="Hang Seng"))]
        assert safe
    base = [{"slide": 0, "show": 1, "say": "a", "mover": {"say": "Nifty", "pct": 1.4}}, {"slide": 0, "show": 2, "say": "b", "mover": {"say": "Dax".upper(), "pct": -1.6}}]
    out = market.report_react(base, turn=0)
    assert out[0]["say"] == "a" and out[1]["reaction"] == "bad" and out[1]["say"].startswith("b ")           # only the biggest mover, and only at 1.5 percent or more
    assert market.report_react([{**base[0], "mover": {"say": "Nifty", "pct": 1.4}}]) == [base[0]]


def test_the_new_spellings_are_in_the_table_and_the_sp500_is_not_read_as_a_number():
    from vision.masters.tamil_say import SOUNDS, voiced
    assert voiced("S&P 500 0.2 percent") == "எஸ் அண்ட் பி ஃபைவ் ஹண்ட்ரட் ஜீரோ பாயிண்ட் டூ பர்சன்ட்"
    assert voiced("GIFT Nifty, Bank Nifty, Nifty") == "கிஃப்ட் நிஃப்டி, பேங்க் நிஃப்டி, நிஃப்டி" and voiced("Hang Seng Dow Jones") == "ஹாங் செங் டவ் ஜோன்ஸ்"
    assert voiced("pre-market post-market") == "ப்ரீ மார்க்கெட் போஸ்ட் மார்க்கெட்" and SOUNDS["points"] == "பாயிண்ட்ஸ்"


# ---- the slides ------------------------------------------------------------------------------------------------------------------------------------

def test_the_disclaimer_card_shows_the_owners_words_and_a_short_has_only_the_small_line():
    assert market.DISCLAIMER_EN == OWNER_EN and market.DISCLAIMER_TA == OWNER_TA and market_crew.DISCLAIMER == OWNER_EN + "\n\n" + OWNER_TA
    page = slides.page([market.NOTICE], channel="Mani Market Tamil")
    plain = page.replace("<b>", "").replace("</b>", "")
    assert page.count("<b>Mani Market Tamil</b>") == 2 and OWNER_EN in plain and OWNER_TA in plain and 'class="top"' not in page and "Nunito" not in page
    data = data_for("premarket", {"all": 0.5})
    tall = slides.page(market.report_deck("premarket", data), channel="Mani Market Tamil", tall=True, top=market.SHORT_NOTE)
    assert f'<div class="top">{market.SHORT_NOTE}</div>' in tall and "1080px" in tall and tall.count('class="blk"') == 4 and "Educational purpose" not in tall and "Disclaimer" not in tall
    assert "Nunito Sans" in tall and "Not SEBI-registered." in tall
    assert market.NOTICE not in market.report_deck("premarket", data) and not any("educational" in ln["say"].lower() for ln in market.report_lines("premarket", data, market.report_deck("premarket", data)))


def test_the_notice_line_holds_its_card_and_the_long_video_keeps_its_size(tmp_path):
    """The spoken disclaimer is short; its line carries a hold, and assemble pads the line's audio to it."""
    out = tmp_path / "o"
    out.mkdir()
    pngs = [out / "a.png", out / "b.png"]
    for p in pngs:
        Image.new("RGB", (1920, 1080), (200, 200, 200)).save(p)
    spoken = []
    for n in range(2):
        spoken.append(out / f"t{n}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=1", str(spoken[-1])], check=True)
    lines = [{"slide": 0, "show": 1, "say": "x", "hold": 6.0}, {"slide": 1, "show": 1, "say": "y"}]
    final = slides.assemble(out, pngs, lines, spoken, out / "f.mp4", pause=0.15)
    assert 7.0 < slides.probe(final) < 7.6                                           # 6 s held + 1.15 s
    size = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(final)], capture_output=True, text=True).stdout.split()
    assert size[0] == "1920,1080"
    tall = out / "t.png"
    Image.new("RGB", (1080, 1920), (200, 200, 200)).save(tall)
    v = slides.assemble(out, [tall], [{"slide": 0, "show": 1, "say": "x"}], spoken[:1], out / "v.mp4", size=slides.TALL)
    assert subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(v)], capture_output=True, text=True).stdout.split()[0] == "1080,1920"


def test_the_long_videos_notice_line_carries_the_hold_and_its_page_is_still_1920_wide():
    deck = [market.NOTICE]
    assert "height:1920px" not in slides.page(deck) and "body{width:1920px;height:1080px" in slides.page(deck)
    said = market.lines({"name": "X Limited", "symbol": "X", "quarter": "Q2 FY27", "rows": [], "bank": False}, [market.NOTICE], [])
    assert said[0]["say"] == market.NOTICE_SAY and said[0]["hold"] >= 6 and market.NOTICE_SAY.startswith("தொடங்குறதுக்கு")


# ---- releasing -------------------------------------------------------------------------------------------------------------------------------------

def ts(d: str, hm: str) -> float:
    return datetime.fromisoformat(f"{d}T{hm}").replace(tzinfo=IST).timestamp()


def test_release_times_premarket_before_0910_postmarket_at_2100_else_same_day_else_stale():
    pre = lambda now: youtube.report_release("premarket", date(2026, 10, 14), now)
    assert pre(ts("2026-10-14", "07:20")) == ts("2026-10-14", "07:20") + 900
    assert pre(ts("2026-10-14", "08:54")) == ts("2026-10-14", "08:54") + 900 and pre(ts("2026-10-14", "08:55")) is None and pre(ts("2026-10-14", "09:11")) is None and pre(ts("2026-10-15", "07:00")) is None
    post = lambda now: youtube.report_release("postmarket", date(2026, 10, 14), now)
    assert post(ts("2026-10-14", "18:20")) == ts("2026-10-14", "21:00") and post(ts("2026-10-14", "20:44")) == ts("2026-10-14", "21:00")
    assert post(ts("2026-10-14", "20:50")) == ts("2026-10-14", "20:50") + 900 and post(ts("2026-10-14", "23:50")) is None and post(ts("2026-10-15", "00:30")) is None


class Web:
    def __init__(self):
        self.updates, self.metas, self.puts, self.thumbs, self.items = [], [], 0, 0, []

    def __call__(self):
        def handler(req):
            u = str(req.url)
            if "upload/youtube/v3/videos" in u:
                self.metas.append(json.loads(req.content))
                return httpx.Response(200, headers={"Location": "https://upload.test/s1"})
            if u.startswith("https://upload.test/"):
                return httpx.Response(200, json={"id": "vid" + str(len(self.metas))})
            if "youtube/v3/videos" in u and req.method == "PUT":
                self.updates.append(json.loads(req.content))
                return httpx.Response(200, json={"id": "x"})
            if "youtube/v3/videos" in u and req.method == "GET":
                return httpx.Response(200, json={"items": self.items})
            if "thumbnails/set" in u:
                self.thumbs += 1
                return httpx.Response(200, json={})
            return httpx.Response(404)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def uploader_env(tmp_path, monkeypatch, mode: str, now: str = "2026-10-14T07:20"):
    monkeypatch.setattr(oauth, "TOKENS", tmp_path / "tokens.json")

    async def token(account, provider, client=None):
        return "tok"
    monkeypatch.setattr(oauth, "access_token", token)
    monkeypatch.setattr(youtube, "_now", lambda: datetime.fromisoformat(now).replace(tzinfo=IST).timestamp())
    monkeypatch.setattr(youtube, "ROOT", tmp_path)
    ch = youtube.channel({**RAW, "report_privacy": mode})
    cfg = Config(masters={"youtube": {"mode": "live", "options": {"channels": [{**RAW, "report_privacy": mode}]}}})
    web = Web()
    return ch, cfg, web, EventBus(), Store(tmp_path / "u.db")


def put_record(tmp_path, store, kind: str, day: str, key: str = "r1") -> str:
    f = tmp_path / f"{key}.mp4"
    f.write_bytes(b"x" * 2000)
    store.kv_put(youtube.LOG, key, {"channel": "manimarket", "status": "ready", "format": "short", "kind": kind, "made": time.time(), "title": f"{kind} {day} #Shorts",
                                    "summary": "s", "hashtags": ["#Nifty"], "script": "", "seconds": 40, "file": str(f), "source": {"url": "https://www.nseindia.com/", "title": "NSE"},
                                    "date": day, "report": {}, "keywords": [], "credits": []})
    return key


def upload(ch, cfg, web, bus, store):
    ctx = {"bus": bus, "store": store, "cfg": cfg, "reason": "schedule", "master": "youtube"}
    return asyncio.run(market_crew.MarketUploader(ch, client_factory=web).run(ctx))


def test_scheduled_mode_publishes_a_fresh_report_by_itself_and_holds_a_stale_one_private(tmp_path, monkeypatch):
    ch, cfg, web, bus, store = uploader_env(tmp_path, monkeypatch, "scheduled")
    put_record(tmp_path, store, "premarket", "2026-10-14", "fresh")
    put_record(tmp_path, store, "premarket", "2026-10-13", "old")
    put_record(tmp_path, store, "postmarket", "2026-10-14", "eve")
    upload(ch, cfg, web, bus, store)
    recs = {v["_key"]: v for v in store.kv_list(youtube.LOG)}
    assert recs["fresh"]["status"] == "scheduled" and recs["fresh"]["publish_at"] == ts("2026-10-14", "07:35")
    assert recs["eve"]["status"] == "scheduled" and recs["eve"]["publish_at"] == ts("2026-10-14", "21:00")
    assert recs["old"]["status"] == "stale" and recs["old"]["publish_at"] is None and store.pending_approvals() == []
    by_title = {m["snippet"]["title"]: m["status"] for m in web.metas}
    assert all(s["privacyStatus"] == "private" for s in by_title.values()) and sum("publishAt" in s for s in by_title.values()) == 2
    assert not any("publishAt" in m["status"] for m in web.metas if "2026-10-13" in m["snippet"]["title"])
    assert not any(v["publish_at"] == ts("2026-10-15", "10:00") for v in recs.values() if v["publish_at"])          # the long video's slot is never taken


def test_approval_mode_asks_first_and_a_late_premarket_is_never_published(tmp_path, monkeypatch):
    ch, cfg, web, bus, store = uploader_env(tmp_path, monkeypatch, "approval")
    put_record(tmp_path, store, "premarket", "2026-10-14", "fresh")
    put_record(tmp_path, store, "postmarket", "2026-10-14", "eve")
    put_record(tmp_path, store, "premarket", "2026-10-13", "old")
    upload(ch, cfg, web, bus, store)
    recs = {v["_key"]: v for v in store.kv_list(youtube.LOG)}
    assert (recs["fresh"]["status"], recs["eve"]["status"], recs["old"]["status"]) == ("awaiting", "awaiting", "stale") and len(store.pending_approvals()) == 2
    assert not any("publishAt" in m["status"] for m in web.metas)
    ctx = {"store": store, "cfg": cfg, "bus": bus, "client_factory": web}

    def decide(key, now):
        monkeypatch.setattr(youtube, "_now", lambda: datetime.fromisoformat(now).replace(tzinfo=IST).timestamp())
        ap = next(a for a in store.pending_approvals() if a["payload"]["record"] == key)
        store.decide_approval(ap["id"], "approved")
        return asyncio.run(youtube.publish_decision(store.get_approval(ap["id"]), "approved", ctx))
    said = decide("fresh", "2026-10-14T09:30")                                              # approved after 09:10: stale, not published
    assert said.startswith("stale") and store.kv_get(youtube.LOG, "fresh")["status"] == "stale" and web.updates == []
    said = decide("eve", "2026-10-14T19:00")
    assert said.startswith("Scheduled for") and "21:00" in said and datetime.strptime(web.updates[-1]["status"]["publishAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(IST).hour == 21
    assert store.kv_get(youtube.LOG, "eve")["status"] == "scheduled"


def test_an_approved_postmarket_after_2100_takes_fifteen_minutes_while_it_is_the_same_date_else_is_stale(tmp_path, monkeypatch):
    ch, cfg, web, bus, store = uploader_env(tmp_path, monkeypatch, "approval", "2026-10-14T19:00")
    put_record(tmp_path, store, "postmarket", "2026-10-14", "eve")
    upload(ch, cfg, web, bus, store)
    ctx = {"store": store, "cfg": cfg, "bus": bus, "client_factory": web}
    ap, = store.pending_approvals()
    monkeypatch.setattr(youtube, "_now", lambda: ts("2026-10-14", "22:10"))
    store.decide_approval(ap["id"], "approved")
    said = asyncio.run(youtube.publish_decision(store.get_approval(ap["id"]), "approved", ctx))
    assert said.startswith("Scheduled") and web.updates[-1]["status"]["publishAt"] == datetime.fromtimestamp(ts("2026-10-14", "22:25"), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.kv_put(youtube.LOG, "eve", {**{k: v for k, v in store.kv_get(youtube.LOG, "eve").items()}, "status": "awaiting"})
    monkeypatch.setattr(youtube, "_now", lambda: ts("2026-10-14", "23:50"))
    assert asyncio.run(youtube.publish_decision(store.get_approval(ap["id"]), "approved", ctx)).startswith("stale")


# ---- the crew end to end ---------------------------------------------------------------------------------------------------------------------------

def world_handler(yt):
    def handler(req):
        u = str(req.url)
        yt.setdefault("urls", []).append(u)
        if "finance/chart/" in u:
            sym = u.split("/chart/")[1].split("?")[0].replace("%5E", "^")
            info = {k: v for k, v in world.INDICES.items() if v[0] == sym}
            if not info:
                return httpx.Response(404)
            region = next(iter(info.values()))[3]
            tz = {"us": "America/New_York", "europe": "Europe/London", "asia": "Asia/Tokyo", "india": "Asia/Kolkata"}[region]
            if region == "asia":
                return httpx.Response(200, json=chart(tz, [("2026-10-13", 100.0), ("2026-10-14", 100.5)], int(NOW.timestamp()) - 300, int(NOW.timestamp()) - 3600, int(NOW.timestamp()) + 3600))
            return httpx.Response(200, json=chart(tz, [("2026-10-12", 100.0), ("2026-10-13", 99.0)], epoch("2026-10-13", "20:00", "UTC"), epoch("2026-10-14", "09:00", "UTC"), epoch("2026-10-14", "20:00", "UTC")))
        if u.endswith("api/marketStatus"):
            return httpx.Response(200, json={"giftnifty": {"LASTPRICE": 22757.5, "DAYCHANGE": -16, "PERCHANGE": -0.07, "TIMESTMP": "14-Oct-2026 07:00"}})
        if u.endswith("index.csv"):
            return httpx.Response(200, text="Company Name,Industry,Symbol,Series,ISIN Code\nSample Limited,Things,SAMPLE,EQ,INE000A01010\n")
        if "integrated-filing-results" in u:
            return httpx.Response(200, json={"data": []})
        if "holiday-master" in u:
            return httpx.Response(200, json={"CM": [{"tradingDate": "26-Jan-2026"}]})
        if u.startswith("https://www.nseindia.com/") and "api" not in u:
            return httpx.Response(200, text="ok")
        if "upload/youtube/v3/videos" in u:
            yt["meta"] = json.loads(req.content)
            return httpx.Response(200, headers={"Location": "https://upload.test/s1"})
        if u.startswith("https://upload.test/"):
            return httpx.Response(200, json={"id": "vid1"})
        if "youtube/v3/videos" in u and req.method == "PUT":
            yt["update"] = json.loads(req.content)
            return httpx.Response(200, json={"id": "vid1"})
        if "youtube/v3/videos" in u:
            st = (yt.get("meta") or {}).get("status") or {}
            return httpx.Response(200, json={"items": [{"id": "vid1", "status": {"privacyStatus": "private", **({"publishAt": st["publishAt"]} if "publishAt" in st else {})}, "statistics": {}}] if yt.get("meta") else []})
        return httpx.Response(404)
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


SEEN = {}


def tall_pictures(deck, lines, work, **frame):
    SEEN.update(frame=frame, deck=deck)
    work.mkdir(parents=True, exist_ok=True)
    out = []
    for n, _ in enumerate(lines):
        out.append(work / f"s{n:03d}.png")
        Image.new("RGB", (1080, 1920), (20 + n, 30, 60)).save(out[-1])
    return out, None


def crew_env(tmp_path, monkeypatch, mode: str, now: datetime = NOW):
    monkeypatch.setattr(youtube, "ROOT", tmp_path)
    monkeypatch.setattr(oauth, "TOKENS", tmp_path / "tokens.json")
    monkeypatch.setattr(market_crew, "now_ist", lambda: now)
    monkeypatch.setattr(market_crew, "now_hm", lambda: "12:00")
    monkeypatch.setattr(youtube, "_now", lambda: now.timestamp() + 1200)

    async def token(account, provider, client=None):
        return "tok"
    monkeypatch.setattr(oauth, "access_token", token)
    raw = {**RAW, "report_privacy": mode}
    yt = {}
    ch = youtube.channel(raw)
    d = Director(ch["director"], market_crew.crew(ch, client_factory=world_handler(yt), synth=tone, pictures=tall_pictures), reporter="Market Analytics")
    m = Master("youtube", "YOUTUBE MANAGER", [Stage("CHANNELS", [d])], reporter=ch["director"], mode="live")
    cfg = Config(masters={"youtube": {"mode": "live", "options": {"channels": [raw]}}})

    class NoWriter:
        def writer_available(self):
            return False

        async def json(self, *a, **k):
            raise AssertionError("a report Short must not call the model")
    m.services.update(llm=NoWriter(), cfg=cfg)
    return m, yt, EventBus(), Store(tmp_path / f"c{time.time_ns()}.db")


@FFMPEG
@pytest.mark.parametrize("mode", ["approval", "scheduled"])
def test_a_premarket_run_makes_the_short_without_the_model_and_releases_it_by_the_mode(tmp_path, monkeypatch, mode):
    m, yt, bus, store = crew_env(tmp_path, monkeypatch, mode)
    asyncio.run(m.cycle(bus, store))
    crew = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}
    assert [crew[n]["status"] for n in ("Results Scout", "Market Analyst", "Tanglish Writer", "Voice Clone", "Slide Editor", "Market Uploader")] == ["done"] * 6, crew
    rec, = store.kv_list(youtube.LOG)
    assert rec["format"] == "short" and rec["kind"] == "premarket" and rec["date"] == "2026-10-14" and "#Shorts" in rec["title"] and rec["title"].startswith("Pre-Market Update 14 Oct | US, Asia, GIFT Nifty")
    assert rec["summary"].endswith(OWNER_EN + "\n\n" + OWNER_TA) and "Data: NSE, Yahoo Finance, as of US closed · 13 Oct" in rec["summary"] and "GIFT Nifty live · 14 Oct 07:00 IST" in rec["summary"]
    assert yt["meta"]["snippet"]["description"] == rec["summary"] and yt["meta"]["status"]["privacyStatus"] == "private"
    assert SEEN["frame"]["tall"] is True and SEEN["frame"]["top"] == market.SHORT_NOTE and SEEN["deck"][0]["kind"] == "board"
    assert not any("educational" in ln.lower() for ln in rec["script"].split("\n")) and market.SUBSCRIBE_SHORT in rec["script"]
    assert store.kv_has(market_crew.DONE, "premarket:2026-10-14")
    if mode == "scheduled":
        assert rec["status"] == "scheduled" and abs(rec["publish_at"] - (NOW.timestamp() + 1200 + 900)) < 2 and "publishAt" in yt["meta"]["status"] and store.pending_approvals() == []
    else:
        assert rec["status"] == "awaiting" and "publishAt" not in yt["meta"]["status"] and store.pending_approvals()[0]["payload"]["kind"] == "yt_publish"
    again = asyncio.run(m.cycle(bus, store))                                               # once per Indian date
    assert len(store.kv_list(youtube.LOG)) == 1


@FFMPEG
def test_no_report_on_a_holiday_or_a_weekend_and_a_skipped_one_is_not_marked_done(tmp_path, monkeypatch):
    m, yt, bus, store = crew_env(tmp_path, monkeypatch, "approval", datetime(2026, 10, 17, 7, 2, tzinfo=IST))            # a Saturday
    asyncio.run(m.cycle(bus, store))
    scout = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}["Results Scout"]
    assert scout["label"] == "NO MARKET" and store.kv_list(youtube.LOG) == [] and not any("holiday" in u for u in yt.get("urls", []))
    m, yt, bus, store = crew_env(tmp_path, monkeypatch, "approval")
    store.kv_put(world.HOLIDAYS, "CM", {"at": time.time(), "days": ["2026-10-14"]})                                       # a weekday holiday
    asyncio.run(m.cycle(bus, store))
    assert {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}["Results Scout"]["label"] == "NO MARKET"
    m, yt, bus, store = crew_env(tmp_path, monkeypatch, "approval")                                                        # GIFT Nifty with yesterday's time: no Short, and it may be tried again
    monkeypatch.setattr(world, "gift_nifty", lambda status: {**gift(YEST), "as_of": NOW - timedelta(days=1)})
    asyncio.run(m.cycle(bus, store))
    analyst = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}["Market Analyst"]
    assert analyst["label"] == "SKIPPED" and "GIFT Nifty" in analyst["summary"] and not store.kv_has(market_crew.DONE, "premarket:2026-10-14") and store.kv_list(youtube.LOG) == []


def test_only_a_long_videos_voice_unloads_lm_studios_model(tmp_path, monkeypatch):
    entered = []

    class Freed:
        def __init__(self):
            entered.append(1)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(lmstudio, "freed", Freed)
    speeds = []
    monkeypatch.setattr(clone, "speak", lambda lines, work, log=None, speed=None: speeds.append(speed) or [work / "a.wav"])
    ch = youtube.channel({**RAW, "free_memory": True})
    for kind, expect in (("premarket", 0), ("postmarket", 0), ("result", 1)):
        entered.clear()
        job = {"kind": kind, "lines": [{"say": "x"}], "dir": str(tmp_path / kind)}
        asyncio.run(market_crew.VoiceClone(ch).run({"job": job, "bus": EventBus()}))
        assert len(entered) == expect, kind
    assert speeds == [1.2, 1.2, 1.3]                 # Shorts a little slower; the long video at the pace Mani approved


def test_reports_do_not_count_toward_the_long_videos_backlog(tmp_path, monkeypatch):
    m, yt, bus, store = crew_env(tmp_path, monkeypatch, "approval", datetime(2026, 10, 14, 23, 30, tzinfo=IST))
    monkeypatch.setattr(market_crew, "now_hm", lambda: "23:30")
    for n in range(2):
        store.kv_put(youtube.LOG, f"x{n}", {"channel": "manimarket", "status": "awaiting", "made": 1, "format": "short", "kind": "premarket"})
    res = asyncio.run(market_crew.ResultsScout(youtube.channel(RAW), client_factory=world_handler(yt)).run({"store": store, "bus": bus, "reason": "schedule", "now": datetime(2026, 10, 14, 12, 0, tzinfo=IST)}))
    assert res.label != "BACKLOG"


def test_run_at_label_after_a_bar_is_ignored_by_run_time():
    from vision.orchestrator import run_spec
    assert run_time("07:02 Asia/Kolkata | Pre-market Short") == (7, 2, ZoneInfo("Asia/Kolkata"))
    assert run_time("05:00 | Shorts") == (5, 0, None)
    assert run_spec("05:00 | Shorts")[3] == "Shorts" and run_spec("05:00")[3] == ""
    assert run_spec("03:00 | Long videos | both")[3:] == ("Long videos", "both") and run_spec("03:00 | Long videos")[4] == ""


# ---- review mode: one video of every kind, uploaded private for Mani to watch -----------------------------------------------------------------------

def put_review(tmp_path, store, kind: str, key: str, fmt: str = "short") -> str:
    put_record(tmp_path, store, kind, "2026-10-14", key)
    rec = store.kv_get(youtube.LOG, key)
    thumb = tmp_path / f"{key}.jpg"
    thumb.write_bytes(b"j" * 100)
    store.kv_put(youtube.LOG, key, {**rec, "status": "review", "review": True, "format": fmt, **({"thumb": str(thumb)} if fmt == "long" else {})})
    return key


def test_a_review_video_goes_up_private_with_no_release_time_and_no_approval_whatever_the_channel_mode(tmp_path, monkeypatch):
    for mode in ("scheduled", "approval"):
        ch, cfg, web, bus, store = uploader_env(tmp_path, monkeypatch, mode)
        put_review(tmp_path, store, "premarket", "short1")
        put_review(tmp_path, store, "lesson", "long1", "long")
        put_review(tmp_path, store, "lesson_short", "short2")
        upload(ch, cfg, web, bus, store)
        recs = {v["_key"]: v for v in store.kv_list(youtube.LOG)}
        assert {k: v["status"] for k, v in recs.items()} == {"short1": "review", "long1": "review", "short2": "review"} and all(v["video_id"] and v["publish_at"] is None for v in recs.values())
        assert len(web.metas) == 3 and all(m["status"]["privacyStatus"] == "private" and "publishAt" not in m["status"] for m in web.metas)
        assert store.pending_approvals() == [] and web.updates == [] and web.thumbs == 1          # the long video's cover is still set
        upload(ch, cfg, web, bus, store)                                                          # nothing is uploaded twice
        assert len(web.metas) == 3
        for k in recs:
            store.kv_put(youtube.LOG, k, {"channel": "other"})


def test_analytics_leaves_a_review_status_alone_until_youtube_says_the_video_is_gone(tmp_path, monkeypatch):
    ch, cfg, web, bus, store = uploader_env(tmp_path, monkeypatch, "approval")
    put_review(tmp_path, store, "premarket", "short1")
    upload(ch, cfg, web, bus, store)
    vid = store.kv_get(youtube.LOG, "short1")["video_id"]
    web.items = [{"id": vid, "status": {"privacyStatus": "private"}, "statistics": {"viewCount": "7"}}]
    ctx = {"bus": bus, "store": store, "cfg": cfg, "reason": "schedule", "master": "youtube"}
    asyncio.run(market_crew.MarketAnalytics(ch, client_factory=web).run(ctx))
    rec = store.kv_get(youtube.LOG, "short1")
    assert rec["status"] == "review" and rec["stats"]["view"] == 7 and web.updates == []
    web.items = [{"id": vid, "status": {"privacyStatus": "private", "publishAt": "2030-01-01T00:00:00Z"}, "statistics": {}}]
    asyncio.run(market_crew.MarketAnalytics(ch, client_factory=web).run(ctx))
    assert store.kv_get(youtube.LOG, "short1")["status"] == "review"
    web.items = []
    asyncio.run(market_crew.MarketAnalytics(ch, client_factory=web).run(ctx))
    assert store.kv_get(youtube.LOG, "short1")["status"] == "deleted"


def test_a_review_job_lives_apart_and_marks_nothing_done(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "ROOT", tmp_path)
    ch = youtube.channel({**RAW, "review": True})
    assert market_crew.jobdir(ch, "2026-10-14-premarket") == str(tmp_path / "data" / "shorts" / "manimarket" / "_review" / "review-2026-10-14-premarket")
    assert market_crew.jobdir(youtube.channel(RAW), "2026-10-14-premarket") == str(tmp_path / "data" / "shorts" / "manimarket" / "2026-10-14-premarket")
    assert market_crew.stamp({"review": True}) == {"status": "review", "review": True} and market_crew.stamp({}) == {"status": "ready"}


def test_a_closed_session_whose_daily_bar_is_still_empty_takes_the_regular_market_price():
    """14 Oct 2026, evening IST: Yahoo's 14 Oct bar for the Nikkei had close None, regularMarketPrice was the close. The index is fresh, not stale."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _Z
    tz = _Z("Asia/Tokyo")
    d13, d14 = _dt(2026, 10, 13, 9, 0, tzinfo=tz).timestamp(), _dt(2026, 10, 14, 9, 0, tzinfo=tz).timestamp()
    closed = _dt(2026, 10, 14, 15, 45, tzinfo=tz).timestamp()
    res = {"meta": {"exchangeTimezoneName": "Asia/Tokyo", "regularMarketTime": closed, "regularMarketPrice": 67744.29,
                    "currentTradingPeriod": {"regular": {"start": _dt(2026, 10, 15, 9, 0, tzinfo=tz).timestamp(), "end": _dt(2026, 10, 15, 15, 30, tzinfo=tz).timestamp()}}},
           "timestamp": [d13, d14], "indicators": {"quote": [{"close": [67777.5, None]}]}}
    m = world.index_move(res, "Nikkei 225", closed + 4 * 3600)
    assert m["day"].isoformat() == "2026-10-14" and m["last"] == 67744.29 and m["prev_close"] == 67777.5 and m["session"] == "closed"


def test_a_review_video_made_by_day_does_not_count_as_the_nights_video(tmp_path, monkeypatch):
    ch = youtube.channel(RAW)
    store = Store(tmp_path / "t.db")
    monkeypatch.setattr(market_crew, "now_hm", lambda: "23:00")
    monkeypatch.setattr(market_crew, "report_window", lambda now: "")

    class Next(Exception):
        pass

    def stop(store_, ch_):
        raise Next                                                                     # past the night count: the Scout goes on to choose the video

    monkeypatch.setattr(market_crew, "release_kind", stop)
    scout = market_crew.ResultsScout(ch)
    ctx = {"store": store, "bus": EventBus(), "reason": "schedule", "now": datetime(2026, 10, 14, 23, 0, tzinfo=ZoneInfo("America/Toronto"))}
    base = {"channel": ch["id"], "format": "long", "kind": "result", "made": time.time() - 7 * 3600}
    store.kv_put(youtube.LOG, "tcs", {**base, "status": "review", "review": True})         # Mani's review video from the afternoon
    with pytest.raises(Next):
        asyncio.run(scout.pick(ctx))
    store.kv_put(youtube.LOG, "night", {**base, "status": "scheduled"})                    # a real video already made tonight
    assert asyncio.run(scout.pick(ctx)).label == "DONE TONIGHT"
