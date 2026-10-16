"""Mani Market Tamil: NSE filings -> figures -> slides and Tanglish lines. No network, no browser, no ffmpeg."""

import asyncio
from datetime import date

import httpx

from vision.masters import market, slides
from vision.masters.tamil_say import number_said, number_words, voiced
from vision.services import nse


def filing(start, end, facts, ytd=None, instant=None, bank=False):
    """A cut-down XBRL filing: the quarter (OneD), optionally the year so far (FourD) and figures at the period's end (OneI)."""
    ctx = f'<xbrli:context id="OneD"><xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>'
    ctx += f'<xbrli:context id="OneI"><xbrli:period><xbrli:instant>{end}</xbrli:instant></xbrli:period></xbrli:context>'
    ctx += f'<xbrli:context id="SegD"><xbrli:entity><xbrldi:explicitMember>x</xbrldi:explicitMember></xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>'
    body = f'<in-capmkt:{"NameOfBank" if bank else "NameOfTheCompany"} contextRef="OneD">Sample {"Bank " if bank else ""}Limited</in-capmkt:{"NameOfBank" if bank else "NameOfTheCompany"}>'
    body += "".join(f'<in-capmkt:{k} contextRef="OneD" decimals="-7" unitRef="INR">{v}</in-capmkt:{k}>' for k, v in facts.items())
    body += "".join(f'<in-capmkt:{k} contextRef="OneI" decimals="4">{v}</in-capmkt:{k}>' for k, v in (instant or {}).items())
    body += '<in-capmkt:RevenueFromOperations contextRef="SegD" decimals="-7" unitRef="INR">1</in-capmkt:RevenueFromOperations>'
    if ytd:
        ctx += f'<xbrli:context id="FourD"><xbrli:period><xbrli:startDate>{ytd[0]}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>'
        body += "".join(f'<in-capmkt:{k} contextRef="FourD" decimals="-7" unitRef="INR">{v}</in-capmkt:{k}>' for k, v in ytd[1].items())
    return f"<xbrli:xbrl>{ctx}{body}</xbrli:xbrl>"


def company(rev, pbt, profit, eps, other=100e7, fin=50e7, dep=150e7):
    return {"RevenueFromOperations": rev, "OtherIncome": other, "FinanceCosts": fin, "DepreciationDepletionAndAmortisationExpense": dep,
            "ProfitBeforeExceptionalItemsAndTax": pbt, "ProfitLossForPeriod": profit, "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": eps}


NOW = filing("2026-07-01", "2026-09-30", company(11000e7, 2400e7, 1800e7, 9.0), ytd=("2026-04-01", company(21000e7, 4600e7, 3400e7, 17.0)))
PREV = filing("2026-04-01", "2026-06-30", company(10000e7, 2200e7, 1600e7, 8.0))
YEAR = filing("2025-07-01", "2025-09-30", company(10000e7, 2300e7, 1700e7, 8.5))
FILES = {"now.xml": NOW, "prev.xml": PREV, "year.xml": YEAR}


def listing():
    def row(day, name, kind="Consolidated"):
        return {"symbol": "SAMPLE", "smName": "Sample Limited", "qe_Date": day, "consolidated": kind, "audited": "Audited",
                "broadcast_Date": "08-Oct-2026 22:07:33", "xbrl": f"https://nsearchives.test/{name}"}
    return {"data": [row("30-JUN-2026", "prev.xml"), row("30-SEP-2026", "alone.xml", "Standalone"), row("30-SEP-2026", "now.xml"), row("30-SEP-2025", "year.xml")]}


def client():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        if "integrated-filing-results" in str(req.url):
            return httpx.Response(200, json=listing())
        return httpx.Response(200, text=FILES[str(req.url).rsplit("/", 1)[-1]])
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def result():
    async def go():
        async with client() as c:
            return await nse.latest(c, "sample")
    return asyncio.run(go())


def test_quarter_names_follow_the_indian_financial_year():
    assert [nse.quarter(d) for d in (date(2026, 6, 30), date(2026, 9, 30), date(2026, 12, 31), date(2027, 3, 31))] == ["Q1 FY27", "Q2 FY27", "Q3 FY27", "Q4 FY27"]


def test_a_filing_is_read_for_the_quarter_not_the_year_so_far_and_not_a_segment():
    f = nse.parse(NOW)
    assert (f["start"], f["end"], f["bank"], f["name"]) == ("2026-07-01", "2026-09-30", False, "Sample Limited")
    assert f["v"]["RevenueFromOperations"] == 11000e7 and f["v"]["ProfitLossForPeriod"] == 1800e7


def test_latest_result_compares_with_the_quarter_before_and_a_year_ago():
    r = result()
    assert (r["quarter"], r["year_ago"], r["before"], r["consolidated"]) == ("Q2 FY27", "Q2 FY26", "Q1 FY27", True)
    rev, opm = r["rows"][0], r["rows"][1]
    assert (rev["key"], rev["now"], rev["prev"], rev["year"]) == ("revenue", 11000e7, 10000e7, 10000e7)
    assert opm["now"] == round(100 * (2400 + 50 + 150 - 100) / 11000, 1)          # profit before tax + finance costs + depreciation - other income


def test_a_bank_states_bad_loans_as_a_fraction_and_lower_is_better():
    bank = nse.parse(filing("2026-07-01", "2026-09-30", {"InterestEarned": 900e7, "InterestExpended": 500e7, "ProfitLossForThePeriod": 120e7},
                            instant={"PercentageOfGrossNpa": 0.0117}, bank=True))
    rows = {x["key"]: x for x in nse.rows(bank, None, None)}
    assert bank["bank"] and rows["nii"]["now"] == 400e7 and rows["gnpa"]["now"] == 1.17 and rows["gnpa"]["lower_is_better"]
    assert market.change({**rows["gnpa"], "year": 1.4})["tone"] == "good"


def test_numbers_are_shown_the_indian_way():
    assert [market.grouped(n) for n in (999, 73188, 123456, 12345678)] == ["999", "73,188", "1,23,456", "1,23,45,678"]
    assert market.shown(73188e7, "cr") == "73,188" and market.shown(25.7, "pct") == "25.7%" and market.shown(None, "cr") == "–"


def test_slides_and_lines_follow_the_filing():
    r = result()
    deck = market.deck(r)
    said = market.lines(r, deck)
    assert [s["kind"] for s in deck] == ["notice", "cover", "table", "points"] and deck[2]["cols"] == ["Q2 FY26", "Q2 FY27", "YoY"]
    assert deck[2]["items"][0]["was"] == "10,000" and deck[2]["items"][0]["now"] == "11,000" and deck[2]["items"][0]["change"] == "▲ 10%"
    assert len(said) == 3 + 4 + len(deck[3]["items"]) + 2 and all(ln["show"] >= 1 for ln in said)
    assert said[0]["say"] == market.NOTICE_SAY and "investment recommendation இல்ல" in said[0]["say"]     # the disclaimer card comes first
    assert "11000 கோடி" in said[3]["say"] and "10 percent வளர்ச்சி" in said[3]["say"]
    assert "advisor" in said[-2]["say"] and said[-1]["say"] == market.SUBSCRIBE_LONG and not market.ADVICE.search(" ".join(ln["say"] for ln in said))
    page = slides.page(deck, channel="Mani Market Tamil", source=market.source(r))
    assert "Source: NSE filing · 08 Oct 2026 · Consolidated · Audited" in page and page.count('<section class="slide">') == 4 and market.DISCLAIMER_EN in page.replace("<b>", "").replace("</b>", "") and "<b>Mani Market Tamil</b>" in page


def test_no_word_about_costs_when_the_margin_went_the_other_way():
    r = result()
    r["rows"][2] = {**r["rows"][2], "now": 2100e7}         # profit now grows faster than revenue, while the margin still fell
    assert r["rows"][1]["now"] < r["rows"][1]["year"]
    assert not any("செலவு" in t["say"] for t in market.takeaways(r))
    r["rows"][1] = {**r["rows"][1], "now": r["rows"][1]["year"] + 1}
    assert any("செலவு கட்டுக்குள்ள" in t["say"] for t in market.takeaways(r))


class Model:
    def __init__(self, answer):
        self.answer = answer

    async def json(self, prompt, **kw):
        return self.answer(prompt) if callable(self.answer) else self.answer


def test_a_reworded_line_must_keep_its_numbers_and_give_no_advice():
    r = result()
    said = market.lines(r, market.deck(r))
    plain = said[3]["say"]
    new = [ln["say"] for ln in said]
    new[3] = plain.replace("அதாவது", "பாருங்க,")              # same numbers: kept
    new[4] = said[4]["say"] + " அடுத்த quarter 30 percent வரும்."  # a new number: refused
    new[5] = said[5]["say"] + " இத buy பண்ணலாம்."              # advice: refused
    out, kept = asyncio.run(market.reword(Model({"lines": new}), said, r))
    assert out[3]["say"] == new[3] and out[4]["say"] == said[4]["say"] and out[5]["say"] == said[5]["say"] and kept == len(said) - 5      # two refused, and the three fixed lines are never the model's
    assert asyncio.run(market.reword(Model({"lines": new[:-1]}), said, r)) == (said, 0)     # a line short: none used
    keyed = {str(i + 1): n for i, n in enumerate(new) if i != 6}                             # numbered answers: a missing one costs only its line
    out, kept = asyncio.run(market.reword(Model({"lines": keyed}), said, r))
    assert out[6] == said[6] and out[3]["say"] == new[3] and kept == len(said) - 6
    assert asyncio.run(market.reword(Model(None), said, r)) == (said, 0)


def test_a_reaction_follows_only_the_biggest_bad_and_good_figures_and_is_never_rude():
    r = result()
    calm = {**r, "rows": [{**x, "now": x["year"] * 1.03} for x in r["rows"]]}
    said = market.lines(calm, market.deck(calm))
    assert market.react(said, calm) == said                # nothing moved enough: no jokes
    r["rows"][1] = {**r["rows"][1], "now": r["rows"][1]["year"]}
    r["rows"][2] = {**r["rows"][2], "now": 900e7}          # net profit nearly halves
    r["rows"][0] = {**r["rows"][0], "now": 13000e7}        # revenue up 30 percent
    said = market.lines(r, market.deck(r))
    out = market.react(said, r, turn=1)
    hit = {ln.get("reaction"): ln for ln in out if ln.get("reaction")}
    assert set(hit) == {"bad", "good"} and "Net profit" in hit["bad"]["say"] and "Revenue" in hit["good"]["say"]
    assert hit["bad"]["say"].endswith(market.REACT["bad"][1].format(name="Sample"))
    assert sum(1 for a, b in zip(said, out) if a != b) == 2
    for tone, bank in market.REACT.items():
        for line in bank:
            assert not market.RUDE.search(line) and not market.ADVICE.search(line) and not market.numbers(line), line


def test_the_voice_gets_tamil_letters_and_number_words_while_the_slide_keeps_digits():
    assert number_words(73188) == "எழுபத்து மூவாயிரத்து நூற்று எண்பத்து எட்டு" and number_words(3060) == "மூவாயிரத்து அறுபது"
    assert number_words(145463) == "ஒரு லட்சத்து நாற்பத்து ஐந்தாயிரத்து நானூற்று அறுபத்து மூன்று" and number_words(900) == "தொள்ளாயிரம்"
    assert number_words(21000) == "இருபத்து ஒன்று ஆயிரம்" and number_words(10_000_000) == "ஒரு கோடி" and number_words(0) == "பூஜ்ஜியம்"
    assert number_said("25.7") == "ட்வென்டி ஃபைவ் பாயிண்ட் செவன்" and number_said("0.07") == "ஜீரோ பாயிண்ட் ஜீரோ செவன்"      # a decimal in English (Mani)
    assert number_said("1,23,456") == number_words(123456)
    said = voiced("Net profit இதே quarter-ல 221 கோடி, 14.9 percent. HDFC Bank-ஓட Q1 result. இது FY27-ஓட முதல் quarter. Profitable இல்ல.")
    assert "நெட் ப்ராஃபிட்" in said and "குவார்ட்டர்ல இருநூற்று இருபத்து ஒன்று கோடி" in said and "பர்சன்ட்" in said
    assert "ஹெச்டிஎஃப்சி பேங்கோட க்யூ ஒன் ரிசல்ட்" in said and "ட்வென்டி சிக்ஸ் ட்வென்டி செவன் ஃபைனான்ஷியல் இயரோட முதல் குவார்ட்டர்" in said
    assert "Profitable" in said and not any(c.isdigit() for c in said) and "-" not in said and ".டி" not in said
    assert voiced("hero-ஓட level-அ") == "ஹீரோவோட லெவல"


# ---- company analysis: fundamentals from filings, ratios, the price lag, slides and lines -------------------------------------------------

from datetime import timedelta  # noqa: E402

from vision.masters import fundamentals  # noqa: E402
from vision.voice import clone  # noqa: E402

CR = 1e7


def quarter_facts(**extra):
    """Every quarter alike (crore): revenue 1000, other income 20, finance 10, depreciation 40, profit before exceptional items 300, after 290, owners' profit 210."""
    return {**company(1000 * CR, 300 * CR, 220 * CR, 2.1, other=20 * CR, fin=10 * CR, dep=40 * CR), "ProfitBeforeTax": 290 * CR, "TaxExpense": 70 * CR,
            "ProfitOrLossAttributableToOwnersOfParent": 210 * CR, **extra}


def annual(end_year, revenue, profit, equity, owners, cfo=None):
    """A March filing: the quarter, the whole year (FourD) and the balance sheet at 31 March."""
    year = {"RevenueFromOperations": revenue * CR, "ProfitOrLossAttributableToOwnersOfParent": profit * CR}
    if cfo:
        year.update(CashFlowsFromUsedInOperatingActivities=cfo * CR, PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities=300 * CR,
                    PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities=20 * CR)
    inst = {"Equity": equity * CR, "EquityAttributableToOwnersOfParent": owners * CR, "EquityShareCapital": 100 * CR, "OtherEquity": (owners - 100) * CR,
            "BorrowingsNoncurrent": 200 * CR, "BorrowingsCurrent": 300 * CR, "Assets": 8000 * CR, "CashAndCashEquivalents": 400 * CR}
    xml = filing(f"{end_year}-01-01", f"{end_year}-03-31", {**quarter_facts(), "PaidUpValueOfEquityShareCapital": 100 * CR, "FaceValueOfEquityShareCapital": 1},
                 ytd=(f"{end_year - 1}-04-01", year), instant=inst)
    lease = ('<in-capmkt:DescriptionOfOtherCurrentFinancialLiabilities contextRef="I_Other1">Lease liabilities</in-capmkt:DescriptionOfOtherCurrentFinancialLiabilities>'
             f'<in-capmkt:OtherCurrentFinancialLiabilities contextRef="I_Other1">{50 * CR}</in-capmkt:OtherCurrentFinancialLiabilities>'
             '<in-capmkt:DescriptionOfOtherNoncurrentFinancialLiabilities contextRef="I_Other2">Lease liabilities</in-capmkt:DescriptionOfOtherNoncurrentFinancialLiabilities>'
             f'<in-capmkt:OtherNoncurrentFinancialLiabilities contextRef="I_Other2">{30 * CR}</in-capmkt:OtherNoncurrentFinancialLiabilities>')
    return xml.replace("</xbrli:xbrl>", lease + "</xbrli:xbrl>")


FUND_FILES = {"f_jun26.xml": filing("2026-04-01", "2026-06-30", quarter_facts()), "f_mar26.xml": annual(2026, 3800, 760, 5000, 4800, cfo=900),
              "f_dec25.xml": filing("2025-10-01", "2025-12-31", quarter_facts()), "f_sep25.xml": filing("2025-07-01", "2025-09-30", quarter_facts()),
              "f_mar25.xml": annual(2025, 3040, 608, 4200, 4000)}


def fund_listing(symbol="SAMPLE"):
    ends = [("30-JUN-2026", "f_jun26.xml"), ("31-MAR-2026", "f_mar26.xml"), ("31-DEC-2025", "f_dec25.xml"), ("30-SEP-2025", "f_sep25.xml"), ("31-MAR-2025", "f_mar25.xml")]
    return {"data": [{"symbol": symbol, "smName": "Sample Limited", "qe_Date": d, "consolidated": "Consolidated", "audited": "Audited",
                      "broadcast_Date": "08-Oct-2026 22:07:33", "xbrl": f"https://nsearchives.test/{n}"} for d, n in ends]}


def fund_client():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        if "integrated-filing-results" in str(req.url):
            return httpx.Response(200, json=fund_listing())
        return httpx.Response(200, text=FUND_FILES[str(req.url).rsplit("/", 1)[-1]])
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def fund():
    async def go():
        async with fund_client() as c:
            return await nse.fundamentals(c, "sample")
    f = asyncio.run(go())
    f["shareholding"] = {"promoter": 55.5, "public": 44.5, "date": "2026-09-30"}
    f["dividend"] = {"per_share": 6.0, "count": 2}
    return f


PRICE = {"price": 240.0, "date": "2026-09-11", "high": 300.0, "low": 200.0}


def by_key(rows):
    return {r["key"]: r["value"] for r in rows}


def test_fundamentals_sum_four_quarters_and_read_the_balance_sheet_the_years_and_the_cash_flow():
    f = fund()
    assert (f["symbol"], f["bank"], f["consolidated"], f["as_of"], f["ttm_to"], f["prev"]) == ("SAMPLE", False, True, "2026-03-31", "2026-06-30", None)
    t = f["ttm"]
    assert (t["revenue"], t["profit"], t["eps"], t["pbt"], t["fin"], t["tax"]) == (4000 * CR, 840 * CR, 8.4, 1160 * CR, 40 * CR, 280 * CR)
    assert t["op"] == 4 * (300 + 10 + 40 - 20) * CR                             # the same definition as the quarter's operating margin
    b = f["bs"]
    assert (b["equity"], b["owners"], b["reserves"], b["shares"], b["leases"]) == (5000 * CR, 4800 * CR, 4700 * CR, 1e9, 80 * CR)
    assert f["bs_open"] == {"owners": 4000 * CR, "end": "2025-03-31"}
    assert [(y["end"], y["revenue"], y["profit"]) for y in f["years"]] == [("2026-03-31", 3800 * CR, 760 * CR), ("2025-03-31", 3040 * CR, 608 * CR)]
    assert f["cf"] == {"end": "2026-03-31", "cfo": 900 * CR, "capex": 320 * CR} and len(f["sources"]) == 5 and f["sources"][0].endswith("f_jun26.xml")
    assert nse.parse_year(FUND_FILES["f_jun26.xml"]) is None                      # a quarter filing states no year


def test_every_ratio_matches_the_hand_computed_figure():
    r = by_key(fundamentals.ratios(fund(), PRICE))
    ok = {"ttm_revenue": 4000 * CR, "ttm_profit": 840 * CR, "opm": 33.0, "npm": 21.0, "eps": 8.4, "rev_growth": 25.0, "profit_growth": 25.0,
          "roe": 100 * 840 / 4400, "roce": 100 * 1200 / 5500, "roa": 10.5, "turnover": 0.5, "reserves": 4700 * CR, "debt": 500 * CR, "leases": 80 * CR,
          "de": 500 / 4800, "cash": 400 * CR, "bv": 48.0, "promoter": 55.5, "cfo": 900 * CR, "fcf": 580 * CR,
          "price": 240.0, "mcap": 24000 * CR, "pe": 240 / 8.4, "pb": 5.0, "dyield": 2.5, "high": 300.0, "low": 200.0, "ev": (24000 + 500 - 400) * CR / (1320 * CR)}
    assert set(r) == set(ok)
    for k, v in ok.items():
        assert abs(r[k] - v) < 1e-6 * max(1, abs(v)), k
    rows = {x["key"]: x for x in fundamentals.ratios(fund(), PRICE)}
    assert "average equity" in rows["roe"]["note"] and rows["rev_growth"]["note"] == "FY26 vs FY25, as filed" and "not added" in rows["debt"]["note"]
    assert not {"price", "mcap", "pe", "pb", "dyield", "high", "low", "ev"} & set(by_key(fundamentals.ratios(fund())))      # no price, no valuation


def test_ratios_leave_out_what_the_filing_does_not_state():
    f = fund()
    f["bs"] = {**f["bs"], "borrow_c": None, "cash": None}
    f["bs_open"] = None
    r = {x["key"]: x for x in fundamentals.ratios(f, PRICE)}
    assert not {"debt", "de", "roce", "cash", "ev"} & set(r) and "closing equity" in r["roe"]["note"] and abs(r["roe"]["value"] - 100 * 840 / 4800) < 1e-9
    f["prev"] = {"revenue": 3000 * CR, "profit": 700 * CR}                       # eight quarters listed: twelve months against the twelve before
    r = {x["key"]: x for x in fundamentals.ratios(f, PRICE)}
    assert r["rev_growth"]["note"].startswith("last 12 months") and abs(r["rev_growth"]["value"] - 100 * 1000 / 3000) < 1e-9 and abs(r["profit_growth"]["value"] - 20.0) < 1e-9


def bank_fund():
    q = {"InterestEarned": 900 * CR, "InterestExpended": 500 * CR, "ProfitLossForThePeriod": 120 * CR, "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": 2.4,
         "PaidUpValueOfEquityShareCapital": 50 * CR, "FaceValueOfEquityShareCapital": 1}
    inst = {"Capital": 50 * CR, "ReservesAndSurplus": 1950 * CR, "Assets": 20000 * CR}
    files = {"b1.xml": filing("2026-04-01", "2026-06-30", q, bank=True), "b2.xml": filing("2026-01-01", "2026-03-31", q, instant=inst, bank=True),
             "b3.xml": filing("2025-10-01", "2025-12-31", q, bank=True), "b4.xml": filing("2025-07-01", "2025-09-30", q, bank=True)}
    rows = [{"symbol": "BANKY", "smName": "Sample Bank Limited", "qe_Date": d, "consolidated": "Consolidated", "audited": "Audited", "broadcast_Date": "08-Oct-2026 22:07:33",
             "xbrl": f"https://nsearchives.test/{n}"} for d, n in (("30-JUN-2026", "b1.xml"), ("31-MAR-2026", "b2.xml"), ("31-DEC-2025", "b3.xml"), ("30-SEP-2025", "b4.xml"))]

    def handler(req):
        return httpx.Response(200, json={"data": rows}) if "integrated-filing-results" in str(req.url) else httpx.Response(200, text=files[str(req.url).rsplit("/", 1)[-1]])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await nse.fundamentals(c, "banky")
    f = asyncio.run(go())
    f["shareholding"], f["dividend"] = {"promoter": 26.0, "public": 74.0, "date": "2026-09-30"}, {"per_share": 4.0, "count": 1}
    return f


def test_a_bank_gets_only_the_ratios_that_make_sense_for_a_bank():
    f = bank_fund()
    assert f["bank"] and f["bs"]["owners"] == 2000 * CR and f["bs"]["shares"] == 5e8
    r = by_key(fundamentals.ratios(f, PRICE))
    assert set(r) == {"nii", "ttm_profit", "eps", "roe", "roa", "reserves", "bv", "promoter", "price", "mcap", "pe", "pb", "dyield", "high", "low"}
    assert r["nii"] == 1600 * CR and r["ttm_profit"] == 480 * CR and abs(r["roe"] - 24.0) < 1e-9 and abs(r["roa"] - 2.4) < 1e-9 and r["bv"] == 40.0
    assert len(fundamentals.ratios(f)) == 8 and not {"opm", "roce", "de", "debt", "turnover", "ev"} & set(r)


def test_the_price_is_never_newer_than_the_lag():
    today = date(2026, 10, 13)
    closes = [(today - timedelta(days=n), 100.0 + (n % 7)) for n in range(1, 500)]            # a close for every day, the newest 30 deliberately wild
    closes = [(d, 9999.0 if (today - d).days <= 30 else c) for d, c in closes]
    p = fundamentals.lagged(closes, today, 31)
    assert p["date"] == (today - timedelta(days=31)).isoformat() and p["price"] < 200 and p["high"] < 200
    assert fundamentals.lagged(closes, today, 31)["low"] > 0 and fundamentals.lagged([(today - timedelta(days=3), 5.0)], today, 31) is None
    sparse = [(date(2026, 9, 11), 50.0), (date(2026, 9, 14), 60.0)]                           # 11 Sep was a Friday; 14 Sep is inside the lag
    assert fundamentals.lagged(sparse, today, 31) == {"price": 50.0, "date": "2026-09-11", "high": None, "low": None}
    year = [(date(2026, 9, 11) - timedelta(days=n), 100.0 + n) for n in range(0, 300)] + [(date(2025, 9, 1), 5.0)]       # a close more than a year before the day is no part of its year
    p = fundamentals.lagged(year + [(date(2026, 10, 1), 7.0)], today, 31)
    assert (p["price"], p["high"], p["low"]) == (100.0, 399.0, 100.0)


def test_nse_shareholding_and_dividends_read_the_newest_row_and_the_last_twelve_months():
    def handler(req):
        if "share-holdings" in str(req.url):
            return httpx.Response(200, json=[{"date": "30-JUN-2026", "pr_and_prgrp": "50", "public_val": "50"}, {"date": "30-SEP-2026", "pr_and_prgrp": "0", "public_val": "100"}])
        return httpx.Response(200, json=[{"exDate": "27-May-2026", "subject": "Dividend - Rs 8 Per Share"}, {"exDate": "04-Feb-2026", "subject": "Interim Dividend - Rs 6.50 Per Share"},
                                         {"exDate": "28-May-2025", "subject": "Dividend - Rs 7.85 Per Share"}, {"exDate": "06-Jan-2025", "subject": "Demerger"}])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await nse.shareholding(c, "x"), await nse.dividends(c, "x", date(2026, 10, 13))
    assert asyncio.run(go()) == ({"promoter": 0.0, "public": 100.0, "date": "2026-09-30"}, {"per_share": 14.5, "count": 2})


def test_advice_words_for_a_valuation_are_refused_and_the_templates_use_none():
    for bad in ("This share is undervalued", "looks cheap", "it is expensive now", "overvalued", "மலிவா இருக்கு", "காஸ்ட்லி ஆகிடுச்சு"):
        assert market.ADVICE.search(bad), bad
    assert not market.ADVICE.search("Debt to equity ஒண்ணுக்கு கீழ இருந்தா, கடன் சொந்த பணத்த விட கம்மின்னு அர்த்தம்.")


def analysis(f, price=PRICE):
    rows = fundamentals.ratios(f, price)
    deck = market.analysis_deck(f, rows)
    return rows, deck, market.analysis_lines(f, rows, deck)


def test_the_analysis_slides_and_lines_follow_the_ratios_and_say_the_price_date_once():
    f = fund()
    rows, deck, said = analysis(f)
    assert [s["kind"] for s in deck][:2] == ["notice", "cover"] and deck[-1]["kind"] == "points" and said[0]["say"] == market.NOTICE_SAY
    tables = [s for s in deck if s["kind"] == "facts"]
    assert tables and all(1 <= len(s["items"]) <= 4 for s in tables) and sum(len(s["items"]) for s in tables) == len(rows)
    assert [s["title"] for s in tables if s["title"].startswith("Valuation")] == ["Valuation 1/2 · 11 Sep 2026 price", "Valuation 2/2 · 11 Sep 2026 price"]
    assert [bool(s.get("note")) for s in tables if s["title"].startswith("Valuation")] == [False, True] and 1 <= len(deck[-1]["items"]) <= 3
    page = slides.page(deck, channel="Mani Market Tamil", source=market.analysis_source(f))
    assert 'class="facts"' in page and "Source: NSE filings · Consolidated · to 30 Jun 2026" in page
    for ln in said:                                          # every line points at a slide and an item count that exist
        n = len(deck[ln["slide"]].get("items") or []) + (1 if deck[ln["slide"]].get("note") else 0)
        assert 1 <= ln["show"] <= n
    text = " ".join(ln["say"] for ln in said)
    assert text.count("தேதி நிலவரம்") == 1 and text.count("SEBI விதிப்படி") == 1 and "11 செப்டம்பர் 2026" in text
    assert "ROE-னா" in text and text.count("ROE-னா") == 1 and "19.09 percent" in text and "பொதுவா நல்லதுன்னு சொல்லுவாங்க" in text
    assert not market.ADVICE.search(text) and not market.RUDE.search(text) and "advisor" in said[-2]["say"] and said[-1]["say"] == market.SUBSCRIBE_LONG
    assert market.analysis_deck(f, fundamentals.ratios(f))[-2]["title"] == "Balance Sheet 3/3" and "Valuation" not in " ".join(s.get("title", "") for s in market.analysis_deck(f, fundamentals.ratios(f)))


def test_asset_turnover_is_said_as_two_lines_the_meaning_then_the_figure():
    """As one line the cloned voice garbled it (NH and PIIND, 2026-10-15); the words are unchanged, only split."""
    rows, deck, said = analysis(fund())
    at = next(i for i, ln in enumerate(said) if ln["say"] == market.MEANS["turnover"])
    meaning, figure = said[at], said[at + 1]
    assert meaning["en"] == market.MEANS_EN["turnover"] and (meaning["slide"], meaning["show"]) == (figure["slide"], figure["show"])
    assert figure["say"].startswith("Asset turnover ") and market.MEANS["turnover"] not in figure["say"] and "tone" in figure
    assert not market.numbers(meaning["say"]) and market.numbers(figure["say"]) == market.numbers(figure["en"])
    assert sum(ln["say"].count("Asset turnover-னா") for ln in said) == 1


def test_every_english_word_the_voice_is_given_is_in_the_sounds_table():
    allowed = {"Sample"}                                      # a company's own name is not in the table
    for f in (fund(), bank_fund()):
        _, _, said = analysis(f)
        left = {w for ln in said for w in clone.unspelt(ln["say"])}
        assert left <= allowed, left


def test_the_takeaways_follow_plain_rules_and_a_reaction_follows_the_best_and_worst_figures():
    f = fund()
    rows, deck, said = analysis(f)
    assert [t["tone"] for t in deck[-1]["items"]] == ["good", "good", "flat"] and "Revenue-உம் profit-உம்" in deck[-1]["items"][0]["say"]      # ROE 19.1 is under the rule's 20
    out = market.react(said, f, turn=1)
    assert {ln.get("reaction") for ln in out} == {None, "good"} and sum(1 for a, b in zip(said, out) if a != b) == 1
    hit = next(ln for ln in out if ln.get("reaction"))
    assert hit["say"].startswith("Operating margin-னா")                       # 33 percent is the figure furthest above its rule
    weak = fund()
    weak["bs"] = {**weak["bs"], "borrow_nc": 9000 * CR}                          # a heavy debt: the worst figure draws a reaction too
    rows, deck, said = analysis(weak)
    out = market.react(said, weak, turn=0)
    assert {ln.get("reaction") for ln in out} == {None, "good", "bad"} and deck[-1]["items"][0]["tone"] == "bad"
    assert asyncio.run(market.reword(Model(None), said, weak)) == (said, 0)


def test_net_profit_is_the_owners_share_when_the_filing_gives_it():
    """TCS Q2 FY27: 13,934 crore for the period, 13,884 crore to the owners. The press and the EPS use the second, so do we."""
    f = nse.parse(filing("2026-07-01", "2026-09-30", {**company(11000e7, 2400e7, 1800e7, 9.0), "ProfitOrLossAttributableToOwnersOfParent": 1750e7}))
    assert {x["key"]: x["now"] for x in nse.rows(f, None, None)}["profit"] == 1750e7
    assert {x["key"]: x["now"] for x in nse.rows(nse.parse(NOW), None, None)}["profit"] == 1800e7


def test_the_disclaimers_are_said_word_for_word_whatever_the_model_returns():
    r = result()
    said = market.lines(r, market.deck(r))
    assert said[0].get("fixed") and said[-1].get("fixed")
    out, _ = asyncio.run(market.reword(Model({"lines": {str(i + 1): ln["say"] + " சரியா?" for i, ln in enumerate(said)}}), said, r))
    assert out[0]["say"] == market.NOTICE_SAY and out[-1]["say"] == said[-1]["say"] and out[2]["say"].endswith("சரியா?")


def test_the_presenter_is_cut_from_a_doodle_sheet_aligned_and_transparent(tmp_path):
    """A 3 x 2 sheet (mouth closed/half/open, eyes open then shut) on white: six frames of the presenter's square, background clear, faces kept."""
    from PIL import Image, ImageDraw
    sheet = Image.new("RGB", (600, 400), "white")
    d = ImageDraw.Draw(sheet)
    for r in range(2):
        for c in range(3):
            x, y = c * 200 + 40 + c * 3, r * 200 + 30 - r * 2          # the generator does not centre tiles exactly
            d.rectangle((x, y, x + 120, y + 150), fill=(30, 60, 40), outline="black")
            d.ellipse((x + 40, y + 20, x + 80, y + 50), fill="white", outline="black")   # a white eye inside the drawing must stay
    path = tmp_path / "sheet.png"
    sheet.save(path)
    faces = slides.own_faces(tmp_path, path)
    assert sorted(faces) == [(m, e) for m in range(3) for e in range(2)]
    a, b = Image.open(faces[(0, 0)]), Image.open(faces[(2, 1)])
    assert a.size == (slides.FACE, slides.FACE) and a.getbbox() == b.getbbox()          # same place in every frame
    assert a.getpixel((0, 0))[3] == 0 and a.getpixel((slides.FACE // 2, slides.FACE - 5))[3] == 255
    eye = [p for p in a.getdata() if p[3] == 255 and p[:3] == (255, 255, 255)]
    assert eye                                                                           # the eye's white is not cut out
    assert slides.own_faces(tmp_path, tmp_path / "missing.png") is None
