"""Mani Market Tamil: the five forms NSE files results in (ordinary company, bank, NBFC, life insurer, general insurer) and how each is read.
Filings are small inline XBRL shaped on the real ones (ICICIPRULI, ICICIGI, BAJFINANCE, HDFCAMC probed 2026-10-14). No network, no browser."""

import asyncio
import re

import httpx
from test_market import PRICE, by_key, filing

from vision.masters import fundamentals, market
from vision.masters.tamil_say import voiced
from vision.services import nse
from vision.voice import clone

CR = 1e7
QUARTERS = [("30-JUN-2026", "2026-04-01", "2026-06-30"), ("31-MAR-2026", "2026-01-01", "2026-03-31"), ("31-DEC-2025", "2025-10-01", "2025-12-31"),
            ("30-SEP-2025", "2025-07-01", "2025-09-30"), ("30-JUN-2025", "2025-04-01", "2025-06-30")]
NS = '<xbrli:xbrl xmlns:in-capmkt-ent="http://www.sebi.gov.in/xbrl/IntegratedFinance_{form}/2025-01-31/in-capmkt/in-capmkt-ent">'


def cr(**kv):
    return {k: v * CR for k, v in kv.items()}


def life(prem, fyp, renew, pat, solv, eps):
    """A life insurer's quarter: the policyholders' surplus is NetSurplusDeficit, the company's own profit is the shareholders' account's."""
    return {**cr(NetPremiumIncome=prem, IncomeFirstYearPremium=fyp, IncomeRenewalPremium=renew, ProfitLossAfterTaxAndExtraordinaryItems=pat, NetSurplusDeficit=pat / 3),
            "SolvencyRatio": solv, "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized": eps}


def general(gwp, earned, pat, combined, solv, eps):
    return {**cr(GrossPremiumsWritten=gwp, PremiumEarned=earned, ProfitLossAfterTax=pat), "CombinedRatio": combined, "SolvencyRatio": solv,
            "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized": eps}


def lender(interest, rev, fin, impair, pat, eps):
    return {**cr(InterestEarned=interest, RevenueFromOperations=rev, FinanceCosts=fin, ImpairmentOnFinancialInstruments=impair, ProfitOrLossAttributableToOwnersOfParent=pat,
                 ProfitLossForPeriod=pat + 10, ProfitBeforeTax=pat * 1.5, PaidUpValueOfEquityShareCapital=100), "FaceValueOfEquityShareCapital": 1,
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": eps}


def tagged(form, xml):
    return xml.replace("<xbrli:xbrl>", NS.format(form=form), 1)


def listed(symbol, rows):
    """rows: (end 'DD-MON-YYYY', consolidated, file name) -> NSE's list."""
    return {"data": [{"symbol": symbol, "smName": "Sample Limited", "qe_Date": d, "consolidated": "Consolidated" if c else "Standalone", "audited": "Audited",
                      "broadcast_Date": "13-Oct-2026 04:04:30", "xbrl": f"https://nsearchives.test/{n}"} for d, c, n in rows]}


def web(symbol, rows, files):
    def handler(req):
        if "integrated-filing-results" in str(req.url):
            return httpx.Response(200, json=listed(symbol, rows))
        return httpx.Response(200, text=files[str(req.url).rsplit("/", 1)[-1]])
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def result_of(form, symbol, now, prev, year, rows=None, files=None, inst=None):
    """nse.latest for a company whose Q2 FY27 / Q1 FY27 / Q2 FY26 filings carry these facts (the form is in each file's name, as NSE's are)."""
    f = {f"INTEGRATED_FILING_{form}_{n}.xml": filing(a, b, facts, instant=inst) for n, (a, b, facts) in
         {"now": ("2026-07-01", "2026-09-30", now), "prev": ("2026-04-01", "2026-06-30", prev), "year": ("2025-07-01", "2025-09-30", year)}.items()}
    rows = rows or [("30-SEP-2026", True, f"INTEGRATED_FILING_{form}_now.xml"), ("30-JUN-2026", True, f"INTEGRATED_FILING_{form}_prev.xml"),
                    ("30-SEP-2025", True, f"INTEGRATED_FILING_{form}_year.xml")]

    async def go():
        async with web(symbol, rows, {**f, **(files or {})}) as c:
            return await nse.latest(c, symbol)
    return asyncio.run(go())


LI = life(1380, 214, 729, 374, 2.299, 2.57), life(975, 171, 538, 386, 2.254, 2.66), life(1184, 197, 685, 299, 2.132, 2.06)
GI = general(886, 595, 403, 1.072, 0.0271, 8.08), general(807, 579, 546, 1.012, 0.0271, 10.97), general(780, 560, 520, 1.03, 0.0271, 10.4)
NB = lender(2051, 2317, 794, 199, 599, 9.62), lender(1918, 2150, 740, 201, 546, 8.79), lender(1700, 1950, 690, 180, 480, 7.9)
AM = {**cr(RevenueFromOperations=110, InterestEarned=0, FinanceCosts=0.4, OtherIncome=26, ProfitBeforeExceptionalItemsAndTax=109, ProfitOrLossAttributableToOwnersOfParent=83.7),
      "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": 19.53}
AM_PREV, AM_YEAR = {**AM, "RevenueFromOperations": 105 * CR, "ProfitOrLossAttributableToOwnersOfParent": 62 * CR}, {**AM, "RevenueFromOperations": 100 * CR}


def life_result():
    return result_of("LI", "ICICIPRULI", *LI)


def general_result():
    return result_of("GI", "ICICIGI", *GI)


def lender_result():
    return result_of("NBFC_INDAS", "BAJFINANCE", *NB)


def plain_result():
    return result_of("NBFC_INDAS", "HDFCAMC", AM, AM_PREV, AM_YEAR)


def test_the_form_is_read_from_the_file_name_then_the_taxonomy_then_the_tags():
    f = filing("2026-07-01", "2026-09-30", {"NetPremiumIncome": 5})
    assert nse.parse(f, "https://x/INTEGRATED_FILING_NBFC_INDAS_1_WEB.xml")["kind"] == "nbfc"                  # the file name wins, whatever the tags say
    assert [nse.parse(f, f"https://x/INTEGRATED_FILING_{k}_1_WEB.xml")["kind"] for k in ("INDAS", "BANKING", "LI", "GI")] == ["indas", "bank", "life", "general"]
    assert nse.parse(tagged("GI", f))["kind"] == "general" and nse.parse(tagged("NBFC", f))["kind"] == "nbfc"           # the taxonomy named inside the file
    assert nse.parse(f)["kind"] == "life" and nse.parse(filing("2026-07-01", "2026-09-30", {"GrossPremiumsWritten": 5}))["kind"] == "general"   # the tags
    assert nse.parse(filing("2026-07-01", "2026-09-30", {"InterestEarned": 9, "InterestExpended": 4}))["kind"] == "bank"
    assert nse.parse(filing("2026-07-01", "2026-09-30", {"InterestEarned": 9, "FinanceCosts": 4}))["kind"] == "indas"      # an NBFC states no InterestExpended: not mistaken for a bank
    plain = nse.parse(filing("2026-07-01", "2026-09-30", {"RevenueFromOperations": 9}))
    assert (plain["kind"], plain["bank"], nse.shape(plain)) == ("indas", False, "company")
    assert nse.shape({"bank": True}) == "bank" and nse.shape({}) == "company" and nse.shape({"kind": "nbfc", "lender": True}) == "lender" and nse.shape({"kind": "nbfc"}) == "plain"


def test_a_life_insurer_is_read_for_its_premium_and_the_shareholders_profit_not_the_policyholders_surplus():
    r = life_result()
    assert (r["kind"], r["bank"], r["lender"], r["quarter"]) == ("life", False, False, "Q2 FY27")
    rows = {x["key"]: x for x in r["rows"]}
    assert list(rows) == ["premium", "fyp", "renewal", "profit", "solvency", "eps"] and "opm" not in rows
    assert (rows["premium"]["now"], rows["premium"]["prev"], rows["premium"]["year"]) == (1380 * CR, 975 * CR, 1184 * CR)
    assert rows["profit"]["now"] == 374 * CR and rows["profit"]["year"] == 299 * CR          # the shareholders' account (374), not NetSurplusDeficit (374 / 3)
    assert (rows["solvency"]["now"], rows["solvency"]["unit"], rows["eps"]["now"]) == (229.9, "pct", 2.57)


def test_a_general_insurer_has_a_combined_ratio_where_lower_is_better_and_a_solvency_figure_that_cannot_be_right_is_left_out():
    r = general_result()
    rows = {x["key"]: x for x in r["rows"]}
    assert r["kind"] == "general" and list(rows) == ["gwp", "earned", "profit", "combined", "eps"]       # SolvencyRatio 0.0271 as filed: outside any real ratio, left out, not rescaled
    assert (rows["gwp"]["now"], rows["earned"]["now"], rows["combined"]["now"], rows["combined"]["year"]) == (886 * CR, 595 * CR, 107.2, 103.0)
    assert rows["combined"]["lower_is_better"] and market.change(rows["combined"])["tone"] == "bad" and not rows["gwp"]["lower_is_better"]
    assert nse._value({"v": {"SolvencyRatio": 2.299}}, "solvency", ("SolvencyRatio",)) == 229.9 and nse._value({"v": {"SolvencyRatio": 0.0242}}, "solvency", ("SolvencyRatio",)) is None
    assert nse._value({"v": {"CombinedRatio": 1.0778}}, "combined", ("CombinedRatio",)) == 107.8 and nse._value({"v": {"CombinedRatio": 107.0}}, "combined", ("CombinedRatio",)) is None


def test_a_lender_gets_interest_income_finance_costs_net_interest_income_worked_out_and_credit_cost():
    r = lender_result()
    rows = {x["key"]: x for x in r["rows"]}
    assert (r["kind"], r["bank"], r["lender"]) == ("nbfc", False, True) and nse.shape(r) == "lender"
    assert list(rows) == ["interest", "fin", "lnii", "impair", "profit", "eps"] and "opm" not in rows
    assert rows["lnii"]["now"] == (2051 - 794) * CR and rows["lnii"]["prev"] == (1918 - 740) * CR and rows["lnii"]["year"] == (1700 - 690) * CR      # interest earned less finance costs
    assert rows["profit"]["now"] == 599 * CR                                                      # the owners' share, not the whole period's profit (609)
    assert {k for k, x in rows.items() if x["lower_is_better"]} == {"fin", "impair"}


def test_an_nbfc_form_company_that_does_not_lend_is_read_like_an_ordinary_one_without_the_operating_margin():
    r = plain_result()
    assert (r["kind"], r["lender"], nse.shape(r)) == ("nbfc", False, "plain")
    rows = {x["key"]: x for x in r["rows"]}
    assert list(rows) == ["revenue", "profit", "eps"] and rows["revenue"]["now"] == 110 * CR
    assert nse.lends({"InterestEarned": 50.0, "RevenueFromOperations": 100.0}) and not nse.lends({"InterestEarned": 49.0, "RevenueFromOperations": 100.0})
    assert not nse.lends({"RevenueFromOperations": 100.0}) and not nse.lends({"InterestEarned": 5.0})
    assert [x["key"] for x in nse.rows({"kind": "nbfc", "lender": False, "bank": False, "v": {"RevenueFromOperations": 1e9, "ProfitBeforeExceptionalItemsAndTax": 1e8,
                                                                                          "ProfitLossForPeriod": 5e7}}, None, None)] == ["revenue", "profit"]


def test_an_insurer_is_read_from_the_consolidated_filing_and_from_the_standalone_one_when_the_consolidated_states_nothing():
    names = lambda form: [("30-SEP-2026", True, f"INTEGRATED_FILING_{form}_c.xml"), ("30-SEP-2026", False, f"INTEGRATED_FILING_{form}_now.xml"),       # noqa: E731
                          ("30-JUN-2026", False, f"INTEGRATED_FILING_{form}_prev.xml"), ("30-SEP-2025", False, f"INTEGRATED_FILING_{form}_year.xml")]
    group = filing("2026-07-01", "2026-09-30", life(1400, 220, 740, 380, 2.3, 2.6))
    both = result_of("LI", "ICICIPRULI", *LI, rows=names("LI"), files={"INTEGRATED_FILING_LI_c.xml": group})
    assert both["consolidated"] and both["rows"][0]["now"] == 1400 * CR                              # the group's figures when it states them
    empty = result_of("LI", "ICICIPRULI", *LI, rows=names("LI"), files={"INTEGRATED_FILING_LI_c.xml": filing("2026-07-01", "2026-09-30", {"ScripCode": 1})})
    assert not empty["consolidated"] and empty["rows"][0]["now"] == 1380 * CR and empty["rows"][0]["prev"] == 975 * CR       # the standalone one, with its own earlier quarters
    only = result_of("LI", "ICICIPRULI", *LI, rows=names("LI")[1:])
    assert not only["consolidated"] and only["rows"][0]["now"] == 1380 * CR


def test_a_filing_with_no_rows_for_its_form_gives_no_rows_and_nothing_breaks():
    r = result_of("LI", "ICICIPRULI", {"ScripCode": 1}, {"ScripCode": 1}, {"ScripCode": 1})
    assert r["rows"] == [] and r["kind"] == "life" and r["parser"] == nse.PARSER


# ---- fundamentals and ratios by form -----------------------------------------------------------------------------------------------------------

def fund_for(form, quarter, balance, opening, symbol="BAJFINANCE"):
    """nse.fundamentals for a company whose five latest quarters are all alike; the newest and the one a year before carry a balance sheet."""
    files, rows = {}, []
    for i, (d, a, b) in enumerate(QUARTERS):
        files[f"INTEGRATED_FILING_{form}_{i}.xml"] = filing(a, b, quarter, instant=balance if i == 0 else opening if i == 4 else None)
        rows.append((d, True, f"INTEGRATED_FILING_{form}_{i}.xml"))

    async def go():
        async with web(symbol, rows, files) as c:
            return await nse.fundamentals(c, symbol)
    f = asyncio.run(go())
    f["shareholding"], f["dividend"] = {"promoter": 55.5, "public": 44.5, "date": "2026-09-30"}, {"per_share": 6.0, "count": 2}
    return f


def life_fund():
    return fund_for("LI", life(1000, 150, 600, 300, 2.3, 3.0), cr(ShareholdersFunds=6000, ReservesAndSurplus=5000, Assets=90000), cr(ShareholdersFunds=5600), "ICICIPRULI")


def general_fund():
    return fund_for("GI", general(800, 600, 200, 1.05, 0.0271, 2.0), cr(PaidUpEquityCapital=500, ReservesAndSurplusExcludingRevaluationReserve=4300,
                                                                          FairValueChangeAccountAndRevaluationReserve=200, Assets=20000),
                    cr(PaidUpEquityCapital=500, ReservesAndSurplusExcludingRevaluationReserve=4000, FairValueChangeAccountAndRevaluationReserve=100), "ICICIGI")


def lender_fund():
    return fund_for("NBFC_INDAS", lender(900, 1000, 400, 50, 200, 2.0), cr(Equity=4000, EquityAttributableToOwnersOfParent=3900, OtherEquity=3800, Assets=12000, Borrowings=7000),
                    cr(Equity=3800, EquityAttributableToOwnersOfParent=3700), "BAJFINANCE")


def plain_fund():
    return fund_for("NBFC_INDAS", {**cr(RevenueFromOperations=100, InterestEarned=2, FinanceCosts=1, ProfitBeforeExceptionalItemsAndTax=70, ProfitBeforeTax=70,
                                       ProfitOrLossAttributableToOwnersOfParent=50, PaidUpValueOfEquityShareCapital=100), "FaceValueOfEquityShareCapital": 10,
                                   "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": 5.0},
                    cr(Equity=900, EquityAttributableToOwnersOfParent=900, OtherEquity=800, Assets=1200, CashAndCashEquivalents=50, BorrowingsNoncurrent=10, BorrowingsCurrent=5),
                    cr(Equity=800, EquityAttributableToOwnersOfParent=800), "HDFCAMC")


def close(a, b):
    return abs(a - b) < 1e-6 * max(1, abs(b))


def test_a_life_insurers_ratios_are_premium_profit_roe_book_value_and_solvency_as_filed():
    f = life_fund()
    assert (f["kind"], f["bank"], nse.shape(f), f["bs"]["owners"], f["bs"]["shares"]) == ("life", False, "life", 6000 * CR, 1e9)           # shares: quarter profit / quarter EPS
    r = by_key(fundamentals.ratios(f, None))
    ok = {"ttm_premium": 4000 * CR, "ttm_profit": 1200 * CR, "eps": 12.0, "roe": 100 * 1200 / 5800, "solvency": 230.0, "reserves": 5000 * CR, "bv": 60.0, "promoter": 55.5}
    assert set(r) == set(ok) and all(close(r[k], v) for k, v in ok.items())
    priced = by_key(fundamentals.ratios(f, PRICE))
    assert close(priced["pe"], 240 / 12.0) and close(priced["pb"], 4.0) and close(priced["mcap"], 24000 * CR) and "ev" not in priced and "roce" not in priced
    assert len(r) >= fundamentals.minimum(f) == fundamentals.MIN_FINANCIAL < fundamentals.MIN_RATIOS


def test_a_general_insurer_gets_its_combined_ratio_and_no_solvency_when_the_filing_states_none_that_can_be_right():
    f = general_fund()
    assert f["bs"]["owners"] == 5000 * CR and f["latest"] == {"combined": 105.0, "solvency": None}
    r = by_key(fundamentals.ratios(f, None))
    ok = {"ttm_premium": 3200 * CR, "ttm_profit": 800 * CR, "eps": 8.0, "roe": 100 * 800 / 4800, "combined": 105.0, "reserves": 4300 * CR, "bv": 50.0, "promoter": 55.5}
    assert set(r) == set(ok) and all(close(r[k], v) for k, v in ok.items())
    assert {x["key"]: x for x in fundamentals.ratios(f, None)}["ttm_premium"]["label"] == "Gross premium written"
    assert {x["key"]: x for x in fundamentals.ratios(life_fund(), None)}["ttm_premium"]["label"] == "Net premium income"


def test_a_lender_is_read_like_a_bank_with_no_roce_debt_or_margin_and_a_non_lender_like_a_company_with_neither_margin_nor_debt():
    f = lender_fund()
    assert (nse.shape(f), f["bank"], f["bs"]["owners"]) == ("lender", False, 3900 * CR)
    r = by_key(fundamentals.ratios(f, PRICE))
    assert close(r["lnii"], 4 * 500 * CR) and close(r["roe"], 100 * 800 / 3800) and close(r["roa"], 100 * 800 / 12000) and close(r["bv"], 39.0)
    assert not {"roce", "de", "debt", "opm", "npm", "ev", "cash", "leases", "turnover", "rev_growth"} & set(r) and "nii" not in r
    p = plain_fund()
    assert nse.shape(p) == "plain" and p["bs"]["borrow_nc"] is None
    r = by_key(fundamentals.ratios(p, PRICE))
    assert {"ttm_revenue", "npm", "roe", "roa", "turnover", "bv"} <= set(r) and not {"opm", "roce", "de", "debt", "ev", "leases", "cash"} & set(r)
    assert nse.shape(p) != "company" and fundamentals.minimum(p) == fundamentals.MIN_FINANCIAL and fundamentals.minimum({"bank": False}) == fundamentals.MIN_RATIOS


def test_an_insurers_premium_growth_comes_from_the_years_and_the_key_ratios_follow_the_form():
    f = life_fund()
    f["years"] = [{"end": "2026-03-31", "premium": 4200 * CR, "profit": 1100 * CR}, {"end": "2025-03-31", "premium": 3500 * CR, "profit": 1000 * CR}]
    r = {x["key"]: x for x in fundamentals.ratios(f, None)}
    assert close(r["prem_growth"]["value"], 20.0) and r["prem_growth"]["note"] == "FY26 vs FY25" and "rev_growth" not in r
    keys = {k: [x["key"] for x in market.key_ratios(fundamentals.ratios(f, PRICE), k)] for k in ("life", "company", True)}
    assert keys == {"life": ["roe", "solvency", "bv"], "company": ["roe"], True: ["roe", "bv"]}                    # a bool is the older bank / not a bank
    assert [x["key"] for x in market.key_ratios(fundamentals.ratios(general_fund(), None), "general")] == ["roe", "combined", "bv"]            # no solvency figure: none shown
    assert [x["key"] for x in market.key_ratios(fundamentals.ratios(lender_fund(), None), "lender")] == ["roe", "roa", "bv"]
    assert [x["key"] for x in market.key_ratios(fundamentals.ratios(plain_fund(), None), "plain")] == ["roe", "npm", "bv"]


# ---- the slides and lines of each form ----------------------------------------------------------------------------------------------------------

def decks():
    """(result, deck, lines) for each new form; the lender and the insurers with their key ratios."""
    out = []
    for r, f in ((life_result(), life_fund()), (general_result(), general_fund()), (lender_result(), lender_fund()), (plain_result(), plain_fund())):
        key = market.key_ratios(fundamentals.ratios(f, None), nse.shape(f))
        deck = market.deck(r, ratios=key)
        out.append((r, deck, market.lines(r, deck, key)))
    return out


def analysis_decks():
    out = []
    for f in (life_fund(), general_fund(), lender_fund(), plain_fund()):
        rows = fundamentals.ratios(f, PRICE)
        deck = market.analysis_deck(f, rows)
        out.append((f, deck, market.analysis_lines(f, rows, deck)))
    return out


def test_every_new_form_has_rows_explanations_and_a_deck_with_the_right_figures():
    for r, deck, said in decks():
        assert [s["kind"] for s in deck][:2] == ["notice", "cover"] and deck[-1]["kind"] == "points" and deck[1]["items"][0]["text"] == r["symbol"]
        shown = [i["key"] for s in deck if s["kind"] == "table" for i in s["items"]]
        assert shown == [x["key"] for x in r["rows"]]
        for key in shown:                                                           # every row has a name, and a sentence in both languages when it is explained at all
            assert key in market.SAY and (key in market.MEANS) == (key in market.MEANS_EN)
    life_deck, gen_deck, lend_deck, plain_deck = (d for _, d, _ in decks())
    assert life_deck[1]["items"][0]["icon"] == "shield" and lend_deck[1]["items"][0]["icon"] == "bank" and plain_deck[1]["items"][0]["icon"] == "company"
    assert [i["now"] for i in lend_deck[2]["items"]] == ["2,051", "794", "1,257"] and lend_deck[2]["items"][1]["tone"] == "bad"       # finance costs rose: lower is better
    assert [i["now"] for i in life_deck[3]["items"]] == ["374", "229.9%", "2.57"] and plain_deck[2]["items"][0]["now"] == "110"


def test_every_line_of_every_new_form_is_voiceable_captioned_with_the_same_figures_and_never_advice_or_a_forecast():
    for deck, said in [(d, s) for _, d, s in decks()] + [(d, s) for _, d, s in analysis_decks()] + [(d, market.react(s, r, turn=1)) for r, d, s in decks()]:
        assert said
        for ln in said:
            assert clone.unspelt(ln["say"]) == [], ln["say"]
            assert ln.get("en") and market.numbers(ln["say"]) == market.numbers(ln["en"]), (ln["say"], ln.get("en"))
            for text in (ln["say"], ln["en"]):
                assert not market.ADVICE.search(text) and not market.RUDE.search(text), text
            assert not market.FORECAST.search(ln["en"]), ln["en"]
            if not ln.get("fixed"):                                                 # the closing line has "அடுத்த வீடியோ" (next video): a fixed sentence of the owner's
                assert not market.FORECAST.search(ln["say"]), ln["say"]


def test_the_new_terms_are_explained_in_plain_sentences_and_said_in_tamil_letters():
    for key in ("interest", "fin", "lnii", "impair", "premium", "fyp", "renewal", "solvency", "gwp", "earned", "combined", "ttm_premium", "prem_growth"):
        assert key in market.MEANS and key in market.MEANS_EN, key
        assert not market.FORECAST.search(market.MEANS[key] + market.MEANS_EN[key]) and not market.ADVICE.search(market.MEANS_EN[key])
    assert "150 percent" in market.MEANS["solvency"] and "150 percent" in market.MEANS_EN["solvency"] and "underwriting" in market.MEANS["combined"]
    said = voiced("Combined ratio, Credit cost, Solvency ratio, First year premium, Renewal premium, IRDAI, NBFC, lender, insurance, policy, underwriting, AUM, stage 3, Net interest margin")
    assert not re.search(r"[A-Za-z]{2,}", said) and "கம்பைன்ட் ரேஷியோ" in said and "க்ரெடிட் காஸ்ட்" in said and "சால்வென்சி" in said and "ஐஆர்டிஏஐ" in said and "ஸ்டேஜ் த்ரீ" in said


def test_the_takeaways_follow_the_form_by_plain_rules():
    r = general_result()
    t = market.takeaways(r)
    assert t[0]["text"].startswith("Gross premium written") and any("Combined ratio ஏறிருக்கு" in x["text"] for x in t)       # the combined ratio rose from 101.2 to 107.2
    t = market.takeaways(life_result())
    assert t[0]["text"].startswith("Net premium income") and any("Solvency ratio 150-க்கு மேல" in x["text"] for x in t)
    t = market.takeaways(lender_result())
    assert t[0]["text"].startswith("Net interest income") and any("Credit cost" in x["text"] for x in t)
    assert market.reading({"key": "solvency", "value": 120.0}, True)[0] == "bad" and market.reading({"key": "combined", "value": 99.0}, True)[0] == "good"
    assert market.reading({"key": "solvency", "value": 230.0}, True)[1] == 0 and market._weight({"key": "solvency", "unit": "pct", "now": 300.0, "year": 200.0}) == 0.0


def test_a_reasons_metric_finds_the_row_its_form_names_differently():
    assert market.row_key(lender_result(), "nii") == "lnii" and market.row_key(lender_result(), "provisions") == "impair"
    assert market.row_key(life_result(), "revenue") == "premium" and market.row_key(general_result(), "revenue") == "gwp" and market.row_key(general_result(), "profit") == "profit"
    assert market.row_key({"kind": "indas", "bank": False}, "revenue") == "revenue"
    assert market.moves(lender_result()).startswith("interest income up")


def test_eps_is_not_compared_across_a_bonus_issue_or_a_split():
    """HDFCAMC: EPS 34.95 -> 19.53 in the filings because the share count doubled, not because profit halved; a comparison would mislead."""
    base = {"PaidUpValueOfEquityShareCapital": 1000e7, "FaceValueOfEquityShareCapital": 10.0, "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": 20.0,
            "RevenueFromOperations": 5000e7, "ProfitLossForPeriod": 2000e7}
    now = {"v": {**base, "PaidUpValueOfEquityShareCapital": 2000e7, "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": 11.0}, "bank": False, "kind": "indas"}
    old = {"v": base, "bank": False, "kind": "indas"}
    eps = {r["key"]: r for r in nse.rows(now, old, old)}["eps"]
    assert eps["now"] == 11.0 and eps["year"] is None and eps["prev"] is None
    same = {r["key"]: r for r in nse.rows(old, old, old)}["eps"]
    assert same["year"] == 20.0
