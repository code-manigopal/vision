"""Mani Market Tamil: what backs a result video (the company's own words, key ratios, news) and the checks on each. No network, no model, no browser."""

import asyncio
import json
import re
import time
from email.utils import formatdate

from test_market import by_key, bank_fund, fund, result

from vision.masters import fundamentals, market, market_crew, slides
from vision.services import filings_text, nse
from vision.voice import clone

CR = 1e7


def pdf(lines):
    """A one-page PDF with a text layer, one line of text each (no parentheses in the text)."""
    stream = "BT /F1 11 Tf 40 760 Td 14 TL " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    return (out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n").encode("latin-1")


REV = "Revenue grew 10 percent year on year, driven by strong demand for cloud services and new deal wins in the quarter."
MARGIN = "Operating margin declined because of higher wage costs and visa expenses during the quarter."
PROFIT = "Net profit rose 6 percent on the back of a lower tax rate and steady operating performance."
OUTLOOK = "We expect demand to remain healthy in the coming quarters, with a strong pipeline of large deals."
PRICEY = "We expect our share price to benefit from the strong pipeline of large deals in the coming quarters."
STATEMENT = "Net profit stood at 1800 crore and net margin at 19 percent for the quarter ended September."
DOC = " ".join([REV, MARGIN, PROFIT, OUTLOOK, PRICEY, STATEMENT])
SAY_REV = "கிளவுட் சர்வீசஸுக்கு டிமாண்ட் நல்லா இருந்ததால ரெவென்யூ 10 பர்சன்ட் வளர்ந்துச்சு."
SAY_MARGIN = "சம்பள செலவு கூடினதால மார்ஜின் கொஞ்சம் குறைஞ்சிருக்கு."
SAY_PROFIT = "வரி கம்மியானதால ப்ராஃபிட் 6 பர்சன்ட் ஏறிருக்கு."
SAY_OUT = "வர்ற குவார்ட்டர்ஸ்ல டிமாண்ட் நல்லா இருக்கும்னு எதிர்பாக்குறாங்க."


class Model:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    async def json(self, prompt, **kw):
        self.asked.append(prompt)
        return self.answer


def item(metric, way, point, quote, say):
    return {"metric": metric, "direction": way, "point": point, "quote": quote, "say": say}


GOOD_REV = item("revenue", "up", "Revenue grew 10 percent on strong cloud demand and deal wins.", REV, SAY_REV)
GOOD_MARGIN = item("margin", "down", "Operating margin declined on higher wage costs and visa expenses.", MARGIN, SAY_MARGIN)
GOOD_PROFIT = item("profit", "up", "Net profit rose 6 percent on a lower tax rate and steady operating performance.", PROFIT, SAY_PROFIT)
GOOD_OUT = item("outlook", "none", "The company expects healthy demand and a strong pipeline of large deals.", OUTLOOK, SAY_OUT)


def run(items, r=None, text=DOC):
    dropped = []
    got = asyncio.run(market.reasons(Model({"reasons": items}), r or result(), text, dropped=dropped))
    return got, dropped


def test_a_pdf_gives_its_text_and_a_scan_gives_nothing():
    data = pdf([REV, MARGIN, PROFIT, OUTLOOK])
    text = filings_text.pdf_text(data)
    assert "Revenue grew 10 percent" in text and "strong pipeline" in text
    assert filings_text.pdf_text(pdf(["A scan"])) == "" and filings_text.pdf_text(b"not a pdf at all") == ""         # too few words: no text layer worth reading
    assert filings_text.pdf_text(data, max_pages=0) == ""


def test_relevant_keeps_the_sentences_about_the_figures_in_order_and_stops_at_the_limit():
    text = "Dear Sir,\nWe write to inform you of the meeting.\n\n" + REV + " The weather was pleasant in Mumbai that week.\n\n" + MARGIN + "\n" + OUTLOOK
    got = filings_text.relevant(text)
    assert got.split("\n") == [REV, MARGIN, OUTLOOK] and "Dear Sir" not in got and "weather" not in got
    cut = filings_text.relevant(text, limit=len(REV) + 10)
    assert cut == REV
    assert filings_text.norm("Industry ‑leading  “growth”") == "industry-leading \"growth\""


def test_the_documents_to_read_are_the_press_release_then_the_presentation_then_the_board_outcome_near_the_result():
    def a(subject, text, day, kb=300.0):
        return {"subject": subject, "text": text, "url": f"https://nsearchives.test/{subject.replace(' ', '')}{day}.pdf", "at": f"2026-10-{day:02d}T15:00:00", "kb": kb}
    found = [a("Copy of Newspaper Publication", "about Copy of Newspaper Publication", 8), a("Outcome of Board Meeting", "submitted the financial results", 8),
             a("Investor Presentation", "Investor Presentation", 8), a("Press Release", "regarding a press release dated", 8), a("Press Release", "regarding a press release", 1),
             a("Outcome of Board Meeting", "a dividend", 8)]
    got = filings_text.choose(found, "08-Oct-2026 22:07:33")
    assert [(d["kind"], d["subject"]) for d in got] == [("press", "Press Release"), ("presentation", "Investor Presentation")] and got[0]["at"].startswith("2026-10-08")
    assert [d["kind"] for d in filings_text.choose(found, "08-Oct-2026 22:07:33", most=3)] == ["press", "presentation", "outcome"]
    assert filings_text.choose([a("Press Release", "x", 8, kb=9000.0)], "08-Oct-2026 22:07:33") == []             # over 8 MB: passed over
    assert filings_text.choose(found, "20-Oct-2026 10:00:00") == [] and filings_text.choose(found, "garbled") == []   # nothing within three days


def test_nse_announcements_are_read_newest_first_with_their_attachment_and_size():
    rows = [{"an_dt": "08-Oct-2026 15:43:32", "desc": "Press Release", "attchmntText": "TCS  informed the Exchange", "attchmntFile": "https://nsearchives.test/pr.pdf", "attFileSize": "806.35 KB"},
            {"an_dt": "09-Oct-2026 08:00:00", "desc": "Updates", "attchmntText": "x", "attchmntFile": "https://nsearchives.test/up.pdf", "attFileSize": "1.5 MB"},
            {"an_dt": "10-Oct-2026 08:00:00", "desc": "No file", "attchmntText": "x", "attchmntFile": "-", "attFileSize": None}]

    async def go():
        import httpx
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=rows))) as c:
            return await nse.announcements(c, "tcs")
    got = asyncio.run(go())
    assert [g["subject"] for g in got] == ["Updates", "Press Release"] and got[1]["text"] == "TCS informed the Exchange" and got[1]["kb"] == 806.35 and got[0]["kb"] == 1.5 * 1024


def test_a_reason_is_kept_only_when_every_check_passes():
    r = result()
    assert market.change(next(x for x in r["rows"] if x["key"] == "opm"))["way"] < 0 and market.change(next(x for x in r["rows"] if x["key"] == "revenue"))["way"] > 0
    got, dropped = run([GOOD_REV, GOOD_MARGIN, GOOD_PROFIT, GOOD_OUT])
    assert [g["metric"] for g in got] == ["margin", "revenue", "profit", "outlook"] and not dropped         # strongest-moving figure first, the outlook last
    assert got[0]["tone"] == "bad" and got[1]["tone"] == "good" and got[3]["tone"] == "flat"
    bad = {
        "direction differs from our figure": item("margin", "up", "Operating margin improved on wage costs and visa expenses.", MARGIN, SAY_MARGIN),
        "quote is not in the document": item("revenue", "up", "Revenue grew 10 percent on strong cloud demand and deal wins.", REV.replace("grew", "soared"), SAY_REV),
        "unknown metric or direction": item("sales", "up", "Revenue grew 10 percent on strong cloud demand.", REV, SAY_REV),
        "a number is not in the quote": item("revenue", "up", "Revenue grew 10 percent on strong cloud demand and deal wins.", REV, SAY_REV.replace("10", "12")),
        "spoken line is not all Tamil script": item("revenue", "up", "Revenue grew 10 percent on strong cloud demand and deal wins.", REV, SAY_REV + " AI"),
        "advice or rude wording": item("revenue", "up", "Revenue grew 10 percent on strong cloud demand and deal wins.", REV, SAY_REV + " இத வாங்கலாம்."),
        "the point is not in the quote's words": item("revenue", "up", "Revenue grew because of record exports to Europe and Japan markets.", REV, SAY_REV),
        "the quote does not speak of that metric": item("nii", "up", "Revenue grew 10 percent on strong cloud demand and deal wins.", REV, SAY_REV),
        "price or target wording in an outlook": item("outlook", "none", "The company expects its share price to benefit from the strong pipeline of large deals.", PRICEY, SAY_OUT),
        "the quote gives no reason, it restates a figure": item("profit", "up", "Net profit stood at 1800 crore and net margin at 19 percent for the quarter.", STATEMENT,
                                                                 "ப்ராஃபிட் 1800 கோடி, மார்ஜின் 19 பர்சன்ட்."),
        "not a complete item": {"metric": "revenue"},
    }
    got, dropped = run([*bad.values(), GOOD_REV])
    assert [g["metric"] for g in got] == ["revenue"] and [why for _, why in dropped] == list(bad)
    short, _ = run([item("revenue", "up", "Revenue grew 10 percent.", "Revenue grew 10 percent.", SAY_REV)])
    assert short == []                                                                                    # a quote under 40 characters is no evidence


def test_a_reason_for_a_figure_we_do_not_have_or_that_did_not_move_is_dropped_and_the_outlook_is_one_only():
    r = result()
    r["rows"] = [x for x in r["rows"] if x["key"] != "revenue"]
    got, dropped = run([GOOD_REV, GOOD_MARGIN], r)
    assert [g["metric"] for g in got] == ["margin"] and dropped[0][1] == "no figure of ours to agree with"
    second = item("outlook", "none", "The company expects healthy demand and a strong pipeline.", OUTLOOK, SAY_OUT)
    got, _ = run([GOOD_OUT, second, GOOD_MARGIN, item("margin", "down", "Operating margin declined on higher wage costs.", MARGIN, SAY_MARGIN)])
    assert [g["metric"] for g in got] == ["margin", "outlook"]                                          # one reason a metric, one outlook
    assert run([], r)[0] == [] and asyncio.run(market.reasons(Model({"reasons": [GOOD_REV]}), result(), "  ")) == [] and asyncio.run(market.reasons(None, result(), DOC)) == []
    assert asyncio.run(market.reasons(Model(None), result(), DOC)) == [] and asyncio.run(market.reasons(Model({"reasons": "x"}), result(), DOC)) == []


def test_the_outlook_is_introduced_as_the_companys_own_guidance_and_the_lines_follow_the_slide():
    r = result()
    got, _ = run([GOOD_REV, GOOD_MARGIN, GOOD_OUT])
    reasons = [{**g, "doc": {"subject": "Press Release", "at": "2026-10-08T15:43:32", "url": "https://nsearchives.test/pr.pdf"}} for g in got]
    deck = market.deck(r, reasons=reasons)
    assert [s["kind"] for s in deck] == ["notice", "cover", "table", "quotes", "points"] and deck[3]["title"] == "ஏன் இப்படி? · Company சொன்னது"
    assert deck[3]["note"] == "Source: Press Release, 08 Oct 2026, filed with NSE" and [i["label"] for i in deck[3]["items"]] == ["Margin ▼", "Revenue ▲", "Guidance"]
    said = [ln for ln in market.lines(r, deck) if ln["slide"] == 3]
    assert said[0]["say"] == "ஏன் margin குறைஞ்சிருக்கு? Company சொல்ற காரணம் இது. " + SAY_MARGIN and said[1]["say"].startswith("ஏன் revenue ஏறிருக்கு? Company சொல்ற காரணம் இது.")
    assert said[2]["say"].startswith("அடுத்து என்ன நடக்கும்? Company-ஓட guidance படி,") and [ln["show"] for ln in said] == [1, 2, 4] and all(ln["fixed"] for ln in said)
    assert all(1 <= ln["show"] <= len(deck[3]["items"]) + 1 for ln in said)
    page = slides.page(deck, channel="Mani Market Tamil")
    assert 'class="quotes"' in page and "Operating margin declined on higher wage costs" in page and "Source: Press Release, 08 Oct 2026, filed with NSE" in page
    assert not clone.unspelt(" ".join(ln["say"] for ln in said)), clone.unspelt(" ".join(ln["say"] for ln in said))        # the voice has Tamil letters for every word
    assert not market.ADVICE.search(" ".join(ln["say"] for ln in said))


def test_a_reason_the_numbers_contradict_never_reaches_the_video_and_no_takeaway_says_what_the_ratios_deny():
    r = result()                                        # margin fell 24.0 -> 22.7 while profit and revenue rose
    claim = item("margin", "up", "Operating margin improved on wage costs and visa expenses.", MARGIN, SAY_MARGIN)
    got, dropped = run([claim, GOOD_REV])
    assert [g["metric"] for g in got] == ["revenue"] and dropped[0][1] == "direction differs from our figure"
    r["rows"][2] = {**r["rows"][2], "now": 2100e7}      # profit now outgrows revenue while the margin still fell: costs are not "under control"
    said = " ".join(t["say"] for t in market.takeaways(r))
    assert "செலவு கட்டுக்குள்ள" not in said and "Margin-ம் மேம்பட்டிருக்கு" not in said
    deck = market.deck(r, reasons=[{**g, "doc": {"subject": "Press Release", "at": "2026-10-08T00:00:00", "url": "u"}} for g in got])
    assert "Margin ▲" not in json.dumps(deck, ensure_ascii=False)


def feed(*items):
    body = "".join(f"<item><title>{t} - {src}</title><link>https://news.test/{i}</link><pubDate>{formatdate(ts)}</pubDate><source url=\"https://x.test\">{src}</source></item>"
                   for i, (t, src, ts) in enumerate(items))
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>g</title>{body}</channel></rss>"


def test_news_keeps_only_headlines_about_the_company_from_distinct_publications_and_none_about_its_price():
    now = time.time()
    items = [("Sample Q2 results: net profit rises 6% to Rs 1,800 crore", "The Mint", now - 3600), ("Sample shares jump 5% after Q2 results", "Moneycontrol", now - 7200),
             ("Sample Q2 results: revenue up 10% as cloud demand holds", "The Mint", now - 8000), ("Sample Q2: brokerages raise target price", "ET", now - 9000),
             ("Sample rises as margins steady", "Reuters", now - 9500), ("Sample Q2 preview: what to expect", "Livemint", now - 9900),
             ("Banks report mixed results this quarter", "BS", now - 10000), ("SAMPLE earnings: wage costs weigh on margin", "Business Standard", now - 11000),
             ("Sample Q2 profit beats, analysts say buy", "CNBC", now - 12000), ("Sampler results are in", "Other", now - 13000),
             ("Sample wins a large cloud deal alongside results", "Hindu", now - 14000), ("Sample results: dividend declared", "NDTV", now - 15000),
             ("Sample के नतीजे: मुनाफा बढ़ा", "Dainik", now - 16000), ("Sample results #Q2 #profit", "Facebook", now - 17000)]
    import feedparser
    parsed = feedparser.parse(feed(*items))
    rows = [{"title": e.title.rsplit(" - ", 1)[0], "source": e.source.title, "link": e.link, "ts": time.mktime(e.published_parsed) - time.timezone} for e in parsed.entries]
    got = market.news_pick(rows, "Sample", "SAMPLE")
    assert [n["source"] for n in got] == ["The Mint", "Business Standard", "Hindu"] and len({n["source"] for n in got}) == 3
    assert got[0]["title"] == "Sample Q2 results: net profit rises 6% to Rs 1,800 crore" and got[0]["link"].startswith("https://news.test/") and re.match(r"\d{4}-\d\d-\d\d$", got[0]["at"])
    titles = [n["title"] for n in market.news_pick(rows, "Sample", "SAMPLE", limit=9)]
    for gone in ("shares jump", "target price", "Sample rises", "preview", "Banks report", "analysts say buy", "Sampler", "नतीजे", "#Q2"):
        assert not any(gone in t for t in titles), gone
    assert market.news_pick([], "Sample", "SAMPLE") == []


def test_a_headline_is_summed_up_only_when_the_sentence_passes_and_the_slide_still_shows_it():
    news = [{"title": "Sample Q2 results: net profit rises 6% to Rs 1,800 crore", "source": "The Mint", "link": "l", "at": "2026-10-08"},
            {"title": "Sample Q2 results: revenue up 10%", "source": "Hindu", "link": "l", "at": "2026-10-08"},
            {"title": "Sample wins a cloud deal", "source": "ET", "link": "l", "at": "2026-10-09"},
            {"title": "Sample results: dividend declared", "source": "NDTV", "link": "l", "at": "2026-10-09"}]
    said = {"1": "ஸாம்பிள் கம்பெனியோட ப்ராஃபிட் 6 பர்சன்ட் ஏறிருக்குன்னு சொல்லுது.", "2": "ரெவென்யூ 12 பர்சன்ட் ஏறிருக்கு.", "3": "Sample ஒரு டீல் ஜெயிச்சிருக்கு.",
            "4": "இப்போ வாங்கலாம், டிவிடெண்ட் அறிவிச்சிருக்காங்க."}
    gists = asyncio.run(market.news_gists(Model({"gists": said}), news, "ஸாம்பிள்"))
    assert gists[0] == said["1"] and gists[1:] == ["", "", ""]                                           # a wrong number, Latin letters and advice are each refused
    assert asyncio.run(market.news_gists(None, news)) == [""] * 4 and asyncio.run(market.news_gists(Model(None), news)) == [""] * 4
    for n, g in zip(news, gists):
        n["gist"] = g
    r = result()
    deck = market.deck(r, news=news)
    slide = deck[3]
    assert slide["kind"] == "quotes" and slide["title"] == "News-ல" and [i["text"] for i in slide["items"]] == [n["title"] for n in news]
    assert slide["items"][0]["label"] == "The Mint · 08 Oct" and slide["items"][0]["say"].startswith("முதல் headline சொல்றது இது:") and not any("say" in i for i in slide["items"][1:])
    said_lines = [ln for ln in market.lines(r, deck) if ln["slide"] == 3]
    assert [ln["say"] for ln in said_lines][0] == market.NEWS_INTRO and len(said_lines) == 2 and said_lines[0]["show"] == 1
    assert said_lines[1]["show"] == 5 and all(ln["fixed"] for ln in said_lines)                          # the headlines with no sentence appear with the last line, and the note
    plain = market.deck(r, news=[{**n, "gist": ""} for n in news])[3]
    assert [ln["show"] for ln in market.lines(r, [*deck[:3], plain, deck[4]]) if ln["slide"] == 3] == [5]  # no sentence at all: the intro shows every headline
    assert "Headlines as published" in slides.page(deck, channel="x") and not clone.unspelt(market.NEWS_INTRO)


def test_the_key_ratios_slide_for_a_company_and_for_a_bank_uses_the_analysis_wording_and_no_price():
    for f, want in ((fund(), ["roe", "roce", "de", "npm"]), (bank_fund(), ["roe", "roa", "bv"])):
        rows = fundamentals.ratios(f, None)
        key = market.key_ratios(rows, bool(f["bank"]))
        assert [r["key"] for r in key] == want
        r = result()
        r["bank"] = bool(f["bank"])
        deck = market.deck(r, ratios=key)
        slide = deck[3]
        assert slide["kind"] == "facts" and slide["title"] == "Key Ratios" and [i["key"] for i in slide["items"]] == want
        said = [ln for ln in market.lines(r, deck, key) if ln["slide"] == 3]
        assert len(said) == len(want) and [ln["show"] for ln in said] == list(range(1, len(want) + 1))
        analysis = {x["key"]: market._fact_line(x, bool(f["bank"]))[0] for x in rows}
        assert [ln["say"] for ln in said] == [analysis[k] for k in want]                                  # the same wording as the analysis video
        assert not {"price", "pe", "pb", "mcap", "dyield"} & {i["key"] for i in slide["items"]}
    assert market.deck(result())[3]["kind"] == "points"                                                  # no ratios, no slide


def test_the_description_lists_every_source_used_and_ends_with_the_disclaimer():
    r = {**result(), "source": "https://nsearchives.test/now.xml"}
    docs = [{"subject": "Press Release", "at": "2026-10-08T15:43:32", "url": "https://nsearchives.test/pr.pdf"}]
    news = [{"title": "t", "source": "The Mint", "link": "https://news.test/0", "at": "2026-10-08"}]
    text = market_crew.SlideEditor.result_summary(r, ["#SAMPLE"], docs, news)
    assert "Source: NSE filing (https://nsearchives.test/now.xml)" in text and "Company document: Press Release, 08 Oct 2026, filed with NSE (https://nsearchives.test/pr.pdf)" in text
    assert "News: The Mint, 08 Oct 2026 (https://news.test/0)" in text and text.endswith(market_crew.DISCLAIMER) and text.index("Source:") < text.index("News:") < text.index("Disclaimer:")
    bare = market_crew.SlideEditor.result_summary(r, ["#SAMPLE"], [], [])
    assert bare.endswith(f"Source: NSE filing (https://nsearchives.test/now.xml)\n{market_crew.DISCLAIMER}")


def test_the_desk_card_shows_what_backs_each_statement():
    from vision import desk
    v = {"reasons": [{"metric": "revenue", "point": "p", "quote": "q", "doc": {"subject": "Press Release", "url": "https://nsearchives.test/pr.pdf"}}],
         "news": [{"title": "t", "source": "The Mint", "at": "2026-10-08", "link": "https://news.test/0"}]}
    rows = desk._rows(*desk.backed(v))
    assert rows[0][0] == "Backed by · revenue" and "“q” (Press Release, https://nsearchives.test/pr.pdf)" in rows[0][1] and rows[1][0] == "Backed by · news" and desk.backed({}) == []


def test_excise_duty_is_taken_off_revenue_for_a_margin_and_growth_where_the_filing_lists_it_and_the_note_says_so():
    ctx = ('<xbrli:context id="Q"><xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period></xbrli:context>'
           '<xbrli:context id="X1"><xbrli:entity><xbrldi:explicitMember>m</xbrldi:explicitMember></xbrli:entity><xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate>'
           '<xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period></xbrli:context>'
           '<xbrli:context id="X2"><xbrli:entity><xbrldi:explicitMember>m</xbrldi:explicitMember></xbrli:entity><xbrli:period><xbrli:startDate>2025-04-01</xbrli:startDate>'
           '<xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period></xbrli:context>')
    facts = ('<in-capmkt:DescriptionOfOtherExpenses contextRef="X1">Excise Duty</in-capmkt:DescriptionOfOtherExpenses><in-capmkt:OtherExpenses contextRef="X1">600</in-capmkt:OtherExpenses>'
             '<in-capmkt:DescriptionOfOtherExpenses contextRef="X2">Excise Duty</in-capmkt:DescriptionOfOtherExpenses><in-capmkt:OtherExpenses contextRef="X2">1100</in-capmkt:OtherExpenses>')
    xml = f"<xbrli:xbrl>{ctx}{facts}</xbrli:xbrl>"
    assert nse.excise(xml, "2026-01-01", "2026-03-31") == 600.0 and nse.excise(xml, "2025-04-01", "2026-03-31") == 1100.0
    assert nse.excise(xml, "2025-01-01", "2025-03-31") is None and nse.excise("<x/>", "2026-01-01", "2026-03-31") is None
    f = fund()
    base = by_key(fundamentals.ratios(f))
    f["ttm"] = {**f["ttm"], "excise": 400 * CR}                                    # 4,000 revenue of which 400 is excise duty: 3,600 net
    f["years"] = [{**f["years"][0], "excise": 300 * CR}, {**f["years"][1], "excise": 100 * CR}]
    rows = {r["key"]: r for r in fundamentals.ratios(f)}
    assert abs(rows["opm"]["value"] - 100 * f["ttm"]["op"] / (3600 * CR)) < 1e-9 and rows["opm"]["value"] > base["opm"] and "net of excise duty" in rows["opm"]["note"]
    assert rows["npm"]["note"] == "profit / revenue net of excise duty, last 12 months" and "before excise duty" in rows["ttm_revenue"]["note"]
    assert abs(rows["rev_growth"]["value"] - 100 * ((3800 - 300) / (3040 - 100) - 1)) < 1e-9 and rows["rev_growth"]["note"] == "FY26 vs FY25, net of excise duty"
    assert "excise duty கழிச்ச revenue" in market._fact(rows["opm"], False)["note"] and "filing-ல உள்ளபடி" in market._fact(by_note(fund(), "rev_growth"), False)["note"]
    f["years"] = [{**f["years"][0], "disc": 0.0}, {**f["years"][1], "disc": 5000 * CR}]
    assert "discontinued operations" in {r["key"]: r for r in fundamentals.ratios(f)}["profit_growth"]["note"]


def by_note(f, key):
    return next(r for r in fundamentals.ratios(f) if r["key"] == key)


def test_slide_notes_are_tanglish_and_dates_read_11_sep_2026():
    assert market.note_ta("close on 2026-09-11") == "11 Sep 2026 close" and market.note_ta("as of 2026-09-30") == "30 Sep 2026 நிலவரம்"
    assert market.note_ta("year to 2026-03-31") == "31 Mar 2026 வரை" and market.note_ta("profit / average equity") == "லாபம் / சராசரி equity"
    assert market.note_ta("last 12 months vs the 12 before, as filed") == "கடைசி 12 மாசம் vs முந்தின 12, filing-ல உள்ளபடி" and market.note_ta("FY26 vs FY25") == "FY26 vs FY25"
    f = fund()
    rows = fundamentals.ratios(f, {"price": 240.0, "date": "2026-09-11", "high": 300.0, "low": 200.0})
    notes = " ".join(market._fact(r, False)["note"] for r in rows)
    assert not re.search(r"\d{4}-\d\d-\d\d", notes) and "last 12 months" not in notes and "borrowings" not in notes and "11 Sep 2026" in notes


def test_company_names_for_the_voice_come_from_names_ta_json_and_fall_back_to_the_short_name():
    names = json.loads((market.Path(market.__file__).parent / "names_ta.json").read_text(encoding="utf-8"))
    assert len(names) >= 240 and all(re.fullmatch(r"[஀-௿]+(?: [஀-௿]+)*", v) for v in names.values())
    assert market.said_name({"symbol": "tcs", "name": "Tata Consultancy Services Limited"}) == names["TCS"]
    assert market.said_name({"symbol": "NOSUCH", "name": "Nosuch Limited"}) == "Nosuch" and market.said_name({"name": "Plain Ltd."}) == "Plain"
    r = result()
    r["symbol"], r["name"] = "TCS", "Tata Consultancy Services Limited"
    said = market.lines(r, market.deck(r))
    assert names["TCS"] in said[1]["say"] and "Tata" not in said[1]["say"]
    assert "Tata Consultancy Services" in slides.page(market.deck(r), channel="x")                        # the slides keep the written name
