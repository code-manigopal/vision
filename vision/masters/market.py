"""Results videos for the Mani Market Tamil channel: a company's filed result -> slides and a Tanglish script.

    deck(result)                 the slides (cover, the numbers three or four to a table, the takeaway), built by code
    lines(result, slides)        one spoken line per thing that appears, from plain templates: every number is the filing's
    reword(llm, said, result)    the model makes those lines sound spoken; a line that gains or loses a number, gives
                                 anything like advice, or is rude or accusing is thrown away and the plain line is used
    react(said, result)          a comic reaction after the worst figure and after the best one, when they are big enough
    analysis_deck(f, ratios)     the other kind of video: one company's ratios (services/nse.fundamentals + masters/fundamentals.ratios) as fact tables
    analysis_lines(f, ratios, d) its spoken lines: what each ratio means, its value, and where a plain rule of thumb gives one, a reading of it
    reasons(llm, result, text)   why the numbers moved, in the company's own words: the model finds them in the company's press release or presentation and
                                 code keeps only those whose quote is in the document, whose numbers are in the quote and whose direction fits our figures
    key_ratios(rows, shape)      the three or four filing-based ratios the results video shows;  news_pick / news_gists  headlines about the result (never about the price)

Mani's rule for the humour: Tamil cinema comedy, the feeling said out loud, the way a friend reacts; tease, but never
disrespectful and never abusive. The reactions are a bank written here (REACT), not the model's: the model, asked for
them, pasted the same two onto every line. Each line carries the mood its own figure earned (good, bad, flat) and how
big the move was, so a joke cannot call a good result poor, and a small move gets none.

`result` is what services/nse.latest returns. Only what the company reported is said: no buy, sell, target or
forecast, and the closing line says so. Mani's rule for this channel: the voice explains, it does not read the slide.
Every long video opens on the disclaimer card (NOTICE, his wording, 2026-10-13, held on screen for NOTICE_HOLD seconds); a Short has no card and
no spoken disclaimer, only SHORT_NOTE as a small line at the top. report_deck / report_lines: the pre-market and post-market Shorts (templates only, no model).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from zoneinfo import ZoneInfo

from ..services import nse, world
from ..services.filings_text import norm
from .fundamentals import GROUPS

FINANCIAL = ("bank", "lender", "life", "general")

def nse_time(text: str) -> datetime:
    """NSE's "08-Oct-2026 22:07:33" as an Indian-time datetime (datetime.min, in that zone, when it cannot be read)."""
    try:
        return datetime.strptime(text[:20].strip().title(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    except ValueError:
        return datetime(1970, 1, 2, tzinfo=ZoneInfo("Asia/Kolkata"))


DISCLAIMER_EN = ("Disclaimer: The content on Mani Market Tamil is for educational and informational purposes only, not investment advice. "
                 "We are not SEBI-registered Investment Advisers or Research Analysts. Investments are subject to market risks. "
                 "Please do your own research or consult a registered professional before investing. All investment decisions and their outcomes are your responsibility.")
DISCLAIMER_TA = ("மறுப்பு அறிவிப்பு: Mani Market Tamil சேனலில் பகிரப்படும் தகவல்கள் கல்வி மற்றும் தகவல் நோக்கத்திற்காக மட்டுமே; முதலீட்டு ஆலோசனை அல்ல. "
                 "நாங்கள் SEBI-யில் பதிவு செய்யப்பட்ட முதலீட்டு ஆலோசகர்களோ அல்லது ஆராய்ச்சி ஆய்வாளர்களோ அல்ல. முதலீடுகள் சந்தை அபாயங்களுக்கு உட்பட்டவை. "
                 "முதலீடு செய்வதற்கு முன் சொந்தமாக ஆராய்ச்சி செய்யவும் அல்லது பதிவு செய்யப்பட்ட நிபுணரின் ஆலோசனையைப் பெறவும். உங்கள் முதலீட்டு முடிவுகளுக்கு நீங்களே பொறுப்பு.")
NOTICE = {"kind": "notice", "title": "", "items": [DISCLAIMER_EN, DISCLAIMER_TA]}     # the owner's wording, shown whole on the card of every long video (2026-10-13)
NOTICE_HOLD = 6.0                                   # the spoken line is short: the card stays on screen at least this long (seconds)
SHORT_NOTE = "Mani Market Tamil · For educational and informational purposes only, not investment advice. Not SEBI-registered."     # the small line at the top of every Short
NOTICE_SAY = "தொடங்குறதுக்கு முன்னாடி ஒரு விஷயம். இந்த வீடியோ educational purpose-க்கு மட்டும்தான். இது investment recommendation இல்ல."
NOTICE_SAY_EN = "One thing before we start. This video is for educational purposes only. It is not an investment recommendation."
CLOSING = "இது company report பண்ண numbers மட்டும்தான். முதலீட்டு ஆலோசனை இல்ல. நான் SEBI registered advisor இல்ல. அடுத்த வீடியோல பாக்கலாம்!"
CLOSING_EN = "These are only the numbers the company reported. This is not investment advice. I am not a SEBI-registered advisor. See you in the next video!"
# the owner's own sign-off lines, word for word; never reworded. A long video says SUBSCRIBE_LONG after its closing line, a Short says SUBSCRIBE_SHORT last.
SUBSCRIBE_LONG = ("நம்ம channel-அ subscribe பண்ணாம பாக்குறீங்கன்னா, subscribe பண்ணிட்டு bell icon-அ click பண்ணுங்க. "
                  "அப்போதான் நம்ம channel videos உங்களுக்கு notification-ல time-க்கு வரும், miss பண்ணாம பார்ப்பீங்க.")
SUBSCRIBE_LONG_EN = ("If you have not subscribed to our channel yet, please subscribe and click the bell icon. "
                     "That way our videos reach you on time as notifications, and you never miss one.")
SUBSCRIBE_SHORT = "இந்த மாதிரி Market and Finance related contents daily-உம் தெரிஞ்சிக்க, நம்ம channel-அ subscribe பண்ணுங்க."
SUBSCRIBE_SHORT_EN = "To catch Market and Finance content like this every day, subscribe to our channel."
ADVICE = re.compile(r"\b(buy|sell|target|multibagger|jackpot|must[- ]have|guaranteed?|sure ?shot|accumulate|book profits?"
                    r"|(?:under|over) ?valued|cheap(?:er)?|expensive|bargain|(?:over|under)priced|outperform|upside)\b"
                    r"|வாங்குங்க|வாங்கலாம்|விற்க|ஜாக்பாட்|இலக்கு|மலிவு|மலிவா|காஸ்ட்லி|விலை குறைவு|விலை அதிகம்|அண்டர் ?வேல்யூ|ஓவர் ?வேல்யூ", re.I)
# never said about a company or its people: abuse, and accusations a filing cannot support
RUDE = re.compile(r"\b(fraud|scam|cheat\w*|thief|loot\w*|crook\w*|idiot|stupid|fool|useless|waste fellow|shameless)\b"
                  r"|மோசடி|திருட|ஏமாத்த|ஏமாற்ற|முட்டாள்|லூசு|பைத்திய|நாய|கழுத|பொறுக்கி|மானங்கெட்ட|வெட்கங்கெட்ட|தண்டம்", re.I)
log = logging.getLogger("vision.market")
# said after a figure; {name} is the company. Add lines freely: same rule, tease like a friend, never insult or accuse.
REACT = {
    "bad": ["என்னடா இது, சத்திய சோதனை!",
            "{name}, உன்ன நம்பி எவ்ளோ பேரு invest பண்ணிருக்காங்க... இப்படி பண்ணலாமா பா?",
            "இவ்ளோ பெரிய ஆளு... இந்த number-அ பாத்தா மனசு கொஞ்சம் வலிக்குது பா.",
            "ஐயோ ஐயோ! இத எதிர்பார்க்கலையே.",
            "என்ன கொடுமை சார் இது!",
            "கொஞ்சம் பொறுப்பா இருக்கலாம்ல பா, {name}?",
            "அடுத்த quarter-ல ஆவது மனசு வை பா.",
            "இந்த number-க்கு ஒரு டீ குடிச்சிட்டு வந்துதான் பேசணும்."],
    "good": ["அடேங்கப்பா! இது வேற level.",
             "சூப்பர் பா! இப்படித்தான் இருக்கணும்.",
             "{name}, இன்னைக்கு நீ தான் பா hero.",
             "பாருங்க பாருங்க, கலக்கிட்டாங்க.",
             "செம்ம! இத பாத்தா மனசுக்கு ஒரு நிம்மதி.",
             "வேற மாதிரி, வேற மாதிரி!",
             "இதுக்கு ஒரு விசில் போடலாம்."],
}
# the English caption of each reaction, same order and length as REACT: how a friend would say it, good-humoured, never rude
REACT_EN = {
    "bad": ["What is this now? A real test of patience!",
            "{name}, so many people have invested trusting you... is this how you do it, my friend?",
            "Such a big name... seeing this number hurts the heart a little.",
            "Oh no, oh no! I did not see this coming.",
            "What an ordeal this is, sir!",
            "Be a little more responsible, {name}, my friend.",
            "At least next quarter, do try harder, my friend.",
            "This number needs a cup of tea before we can even talk about it."],
    "good": ["Wow! This is on another level.",
             "Super! This is exactly how it is done.",
             "{name}, you are the hero today!",
             "Look at that, look at that, they have nailed it!",
             "Awesome! Seeing this gives some peace of mind.",
             "Totally different class!",
             "This deserves a whistle!"],
}
REACT_FROM = {"bad": 5.0, "good": 10.0}             # how big a move earns a reaction (percent; a margin or ratio counts ten per point)
FLAT = {"cr": 0.5, "rs": 0.5, "pct": 0.05}          # a change smaller than this is "about the same" (percent for cr/rs, points for pct)

# what a term means, said once when its row appears
MEANS = {
    "opm": "Operating margin-னா, நூறு ரூபாய் revenue-ல செலவெல்லாம் போக எவ்வளவு மிஞ்சுதுன்னு சொல்றது.",
    "eps": "EPS-னா, ஒரு share-க்கு company சம்பாதிச்ச லாபம்.",
    "nii": "Net interest income-னா, bank வாங்குற வட்டிக்கும் குடுக்குற வட்டிக்கும் உள்ள வித்தியாசம். Bank-ஓட முக்கிய வருமானம் இதுதான்.",
    "op": "Operating profit-னா, கடன் இழப்புக்கு பணம் ஒதுக்குறதுக்கு முன்னாடி bank சம்பாதிச்சது.",
    "provisions": "Provisions-னா, திரும்பி வராம போகக்கூடிய கடனுக்காக bank ஒதுக்கி வைக்கிற பணம்.",
    "gnpa": "Gross NPA-னா, மொத்த கடன்ல திரும்பி வராம நிக்கிற கடனோட சதவீதம். இது குறைஞ்சா நல்லது.",
    "nnpa": "Net NPA-னா, ஒதுக்கின பணத்த கழிச்ச பிறகு மிஞ்சுற வராக்கடன் சதவீதம்.",
    # a lender (an NBFC): it lends out money it has borrowed
    "interest": "Interest income-னா, கடன் குடுத்து company வாங்குற வட்டி. lender-ஓட முக்கிய வருமானம் இதுதான்.",
    "fin": "Finance costs-னா, company தான் கடன் வாங்குனதுக்கு கட்டுற வட்டி. இது குறைஞ்சா நல்லது.",
    "lnii": "Net interest income-னா, கடன் குடுத்து வாங்குற வட்டிக்கும், கடன் வாங்கி கட்டுற வட்டிக்கும் உள்ள வித்தியாசம். இத filing-ல இருக்கிற ரெண்டு numbers-ல இருந்து கணக்கு போட்டிருக்கோம்.",
    "impair": "Credit cost-னா, குடுத்த கடன்ல திரும்பி வராம போற ஆபத்து இருக்கிறதுக்காக, company ஒதுக்கி வைக்கிற பணம். இது குறைஞ்சா நல்லது.",
    # insurers
    "premium": "Net premium income-னா, மக்கள் insurance policy-க்காக கட்டுற premium-ல, reinsurance கழிச்சு மிஞ்சுறது. இதுதான் insurance company-ஓட முக்கிய வருமானம்.",
    "fyp": "First year premium-னா, புதுசா எடுத்த policy-க்கு, முதல் வருஷம் கட்டுற premium. புது business எவ்ளோ வருதுன்னு இது காட்டுது.",
    "renewal": "Renewal premium-னா, ஏற்கனவே இருக்கிற policy-ய தொடர்ந்து வச்சுக்க, மக்கள் ஒவ்வொரு வருஷமும் கட்டுற premium.",
    "solvency": "Solvency ratio-னா, insurance company-கிட்ட claim குடுக்க எவ்வளவு பணம் இருக்குன்னு காட்டுறது. IRDAI, குறைஞ்சது 150 percent இருக்கணும்னு சொல்லுது.",
    "gwp": "Gross premium written-னா, அந்த quarter-ல எழுதின policy-களுக்காக வந்த மொத்த premium.",
    "earned": "Net premium earned-னா, reinsurance கழிச்சு, அந்த காலத்துக்கு உண்மையாவே company சம்பாதிச்ச premium.",
    "combined": "Combined ratio-னா, நூறு ரூபாய் premium-ல claim-க்கும் செலவுக்கும் எவ்வளவு போகுதுன்னு காட்டுறது. நூறுக்கு கீழ இருந்தா, underwriting-ல லாபம்.",
}
MEANS_EN = {
    "opm": "Operating margin shows how much is left out of every hundred rupees of revenue after all the costs.",
    "eps": "EPS is the profit the company earned for each share.",
    "nii": "Net interest income is the difference between the interest a bank earns and the interest it pays. It is the bank's main income.",
    "op": "Operating profit is what the bank earned before setting money aside for bad loans.",
    "provisions": "Provisions are the money a bank sets aside for loans that are at risk of not coming back.",
    "gnpa": "Gross NPA is the percentage of all loans that are stuck and not being repaid. Lower is better.",
    "nnpa": "Net NPA is the percentage of stuck loans that is left after the money set aside is taken off.",
    "interest": "Interest income is the interest the company earns on the loans it gives. It is a lender's main income.",
    "fin": "Finance costs are the interest the company pays on the money it has borrowed. Lower is better.",
    "lnii": "Net interest income is the difference between the interest earned on loans and the interest paid on borrowings. We worked it out from two numbers in the filing.",
    "impair": "Credit cost is the money the company sets aside for loans that are at risk of not coming back. Lower is better.",
    "premium": "Net premium income is what people pay for insurance policies, after reinsurance is taken off. It is an insurer's main income.",
    "fyp": "First year premium is what people pay in the first year for newly bought policies. It shows how much new business is coming in.",
    "renewal": "Renewal premium is what people pay every year to keep their existing policies going.",
    "solvency": "Solvency ratio shows how well an insurer can pay its claims. IRDAI asks for at least 150 percent.",
    "gwp": "Gross premium written is the total premium that came in for the policies written in the quarter.",
    "earned": "Net premium earned is the premium the company has really earned for the period, after reinsurance is taken off.",
    "combined": "Combined ratio shows how much of every hundred rupees of premium goes on claims and costs. Below a hundred means an underwriting profit.",
}
SAY = {"revenue": "Revenue", "opm": "Operating margin", "profit": "Net profit", "eps": "EPS", "nii": "Net interest income", "op": "Operating profit",
       "provisions": "Provisions", "gnpa": "Gross NPA", "nnpa": "Net NPA",
       "interest": "Interest income", "fin": "Finance costs", "lnii": "Net interest income", "impair": "Credit cost", "premium": "Net premium income", "fyp": "First year premium",
       "renewal": "Renewal premium", "solvency": "Solvency ratio", "gwp": "Gross premium written", "earned": "Net premium earned", "combined": "Combined ratio"}
UNIT = {"cr": "₹ கோடி", "rs": "₹", "pct": "%", "x": "x"}
NO_JOKE = {"solvency"}                              # no comic reaction to a regulator's capital figure


def financial(x: dict) -> bool:
    """A bank, lender or insurer: ROE is judged against 15 rather than 20, and there is no debt reading."""
    return nse.shape(x) in FINANCIAL


def icon(x: dict) -> str:
    return {"bank": "bank", "lender": "bank", "life": "shield", "general": "shield"}.get(nse.shape(x), "company")


def short(name: str) -> str:
    return re.sub(r"\s+(limited|ltd\.?)$", "", name.strip(), flags=re.I)


def names_ta() -> dict:
    """How the company's short name is said, in Tamil letters, by symbol (names_ta.json; a symbol missing from it is simply not there)."""
    try:
        return json.loads((Path(__file__).parent / "names_ta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def said_name(x: dict) -> str:
    """The company's name for the spoken lines: Tamil letters from names_ta.json, else the short name (which clone.unspelt then flags, as before).
    `x` is a result or a fundamentals dict."""
    return names_ta().get((x.get("symbol") or "").upper()) or short(x["name"])


def grouped(n: float) -> str:
    """Indian digit grouping: 123456 -> 1,23,456."""
    s = str(abs(round(n)))
    head, tail = s[:-3], s[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return ("-" if n < 0 else "") + (head + "," if head else "") + tail


def shown(v: float | None, unit: str) -> str:
    if v is None:
        return "–"
    return grouped(v / 1e7) if unit == "cr" else f"{v:.2f}".rstrip("0").rstrip(".") + {"pct": "%", "x": "x"}.get(unit, "")


def spoken(v: float, unit: str) -> str:
    return str(round(v / 1e7)) + " கோடி" if unit == "cr" else f"{v:.2f}".rstrip("0").rstrip(".") + {"pct": " percent", "x": " மடங்கு"}.get(unit, " ரூபாய்")


def fig_en(v: float, unit: str) -> str:
    """A figure as the English caption shows it: ₹73,188 crore, 11.2%, ₹38.37 (the same figure `spoken` says, grouped for reading)."""
    sign, v = ("-" if v < 0 else ""), abs(v)
    n = f"{v:.2f}".rstrip("0").rstrip(".")
    return sign + (f"₹{grouped(v / 1e7)} crore" if unit == "cr" else n + "%" if unit == "pct" else n + " times" if unit == "x" else "₹" + n)


def change(row: dict, against: str = "year") -> dict | None:
    """How a figure moved against the year-ago quarter (or the one before): size, direction, and whether that is good."""
    was, now = row.get(against), row["now"]
    if was is None or (row["unit"] != "pct" and not was):
        return None
    size = now - was if row["unit"] == "pct" else 100 * (now - was) / abs(was)
    way = 0 if abs(size) < FLAT[row["unit"]] else (1 if size > 0 else -1)
    tone = "flat" if not way else "good" if (way > 0) != bool(row.get("lower_is_better")) else "bad"
    amount = f"{abs(size):.2f}".rstrip("0").rstrip(".") if row["unit"] == "pct" else f"{abs(size):.1f}".rstrip("0").rstrip(".")
    return {"size": size, "way": way, "tone": tone, "amount": amount,
            "text": "≈ அதே அளவு" if not way else f"{'▲' if way > 0 else '▼'} {amount}{' pts' if row['unit'] == 'pct' else '%'}"}


def takeaways(result: dict) -> list[dict]:
    """Up to three things the numbers show, by plain rules. Each: icon, the card's words, tone, and what is said."""
    r = {x["key"]: x for x in result["rows"]}
    ch = {k: change(x) for k, x in r.items()}
    out: list[dict] = []

    def add(icon, text, tone, say, en):
        out.append({"icon": icon, "text": text, "tone": tone, "say": say, "en": en})
    sh = nse.shape(result)
    top = {"bank": "nii", "lender": "lnii", "life": "premium", "general": "gwp"}.get(sh, "revenue")
    name = SAY[top]
    if ch.get(top):
        c = ch[top]
        if c["way"] > 0:
            add("up", f"{name} {c['amount']}% வளர்ச்சி", "good", f"ஆக மொத்தம், {name} போன வருஷத்த விட {c['amount']} percent வளர்ந்திருக்கு.",
                f"All in all, {name.lower()} has grown {c['amount']}% compared with last year.")
        elif c["way"] < 0:
            add("down", f"{name} {c['amount']}% குறைவு", "bad", f"ஆக மொத்தம், {name} போன வருஷத்த விட {c['amount']} percent குறைஞ்சிருக்கு.",
                f"All in all, {name.lower()} has fallen {c['amount']}% compared with last year.")
        else:
            add("eye", f"{name} அதே அளவு", "flat", f"ஆக மொத்தம், {name} போன வருஷம் இருந்த அதே அளவுலதான் இருக்கு.",
                f"All in all, {name.lower()} is at about the same level as last year.")
    p, t = ch.get("profit"), ch.get(top)
    costs = (ch.get("opm") or {}).get("way", 0)     # a word about costs only when the margin moved the same way
    if p and p["way"] < 0:
        add("down", "Profit குறைஞ்சிருக்கு", "bad", f"Net profit {p['amount']} percent குறைஞ்சிருக்கு. இது கவனிக்க வேண்டிய விஷயம்.",
            f"Net profit has fallen {p['amount']}%. This is something to keep an eye on.")
    elif p and t and p["size"] > t["size"] + 1:
        add("coin", f"Profit, {name}-அ விட வேகம்", "good", f"Profit, {name}-அ விட வேகமா வளர்ந்திருக்கு." + (" அதாவது செலவு கட்டுக்குள்ள இருக்கு." if costs > 0 else ""),
            f"Profit has grown faster than {name.lower()}." + (" That means costs are under control." if costs > 0 else ""))
    elif p and t and p["size"] < t["size"] - 1:
        add("eye", f"Profit வளர்ச்சி {name}-அ விட கம்மி", "flat", f"ஆனா profit, {name} வளர்ந்த அளவுக்கு வளரல." + (" செலவு கொஞ்சம் கூடியிருக்கு." if costs < 0 else ""),
            f"But profit has not grown as much as {name.lower()}." + (" Costs have gone up a little." if costs < 0 else ""))
    elif p:
        add("coin", "Profit-ம் அதே வேகத்துல", "good", "Profit-ம் கிட்டத்தட்ட அதே வேகத்துல வளர்ந்திருக்கு.", "Profit has also grown at about the same pace.")
    if sh == "lender":                                  # credit cost is what a lender sets aside for loans at risk: down is good
        c = ch.get("impair")
        if c and c["way"]:
            good = c["way"] < 0
            add("shield" if good else "eye", "Credit cost குறைஞ்சிருக்கு" if good else "Credit cost ஏறிருக்கு", "good" if good else "bad",
                "Credit cost குறைஞ்சிருக்கு, அதாவது திரும்பி வராத கடனுக்காக ஒதுக்குற பணம் கம்மியாயிருக்கு." if good else "Credit cost ஏறிருக்கு, அதாவது கடனுக்காக ஒதுக்குற பணம் அதிகமாயிருக்கு. இத கவனிக்கணும்.",
                "Credit cost has come down, which means less money is being set aside for loans at risk." if good else
                "Credit cost has gone up, which means more money is being set aside for loans at risk. This is worth keeping an eye on.")
    elif sh == "general":                               # under a hundred percent: the premium covers the claims and costs
        c = ch.get("combined")
        if c and c["way"]:
            good = c["way"] < 0
            add("shield" if good else "eye", "Combined ratio குறைஞ்சிருக்கு" if good else "Combined ratio ஏறிருக்கு", "good" if good else "bad",
                "Combined ratio குறைஞ்சிருக்கு, அதாவது claim, செலவு கம்மியாயிருக்கு." if good else "Combined ratio ஏறிருக்கு, அதாவது claim, செலவு அதிகமாயிருக்கு. இத கவனிக்கணும்.",
                "Combined ratio has come down, which means claims and costs are lower." if good else
                "Combined ratio has gone up, which means claims and costs are higher. This is worth keeping an eye on.")
    elif sh == "life":
        x = r.get("solvency")
        if x:
            good = x["now"] >= 150
            add("shield" if good else "eye", "Solvency ratio 150-க்கு மேல" if good else "Solvency ratio 150-க்கு கீழ", "good" if good else "bad",
                f"Solvency ratio {spoken(x['now'], 'pct')}. IRDAI கேக்குற 150 percent-க்கு மேல இருக்கு." if good else f"Solvency ratio {spoken(x['now'], 'pct')}. IRDAI கேக்குற 150 percent-க்கு கீழ இருக்கு.",
                f"Solvency ratio is {fig_en(x['now'], 'pct')}, above the 150% IRDAI asks for." if good else f"Solvency ratio is {fig_en(x['now'], 'pct')}, below the 150% IRDAI asks for.")
    else:
        last = ch.get("gnpa") if sh == "bank" else ch.get("opm")
        if last and last["way"]:
            if sh == "bank":
                good = last["way"] < 0
                add("shield" if good else "eye", "கடன் தரம் மேம்பட்டிருக்கு" if good else "வராக்கடன் ஏறிருக்கு", "good" if good else "bad",
                    "வராக்கடன் சதவீதம் குறைஞ்சிருக்கு, அதாவது கடன் தரம் மேம்பட்டிருக்கு." if good else "வராக்கடன் சதவீதம் ஏறிருக்கு. அடுத்த quarter-ல இத கவனிக்கணும்.",
                    "The percentage of bad loans has come down, which means loan quality has improved." if good else
                    "The percentage of bad loans has gone up. This is worth keeping an eye on next quarter.")
            else:
                good = last["way"] > 0
                add("shield" if good else "eye", "Margin மேம்பட்டிருக்கு" if good else "Margin-ல pressure", "good" if good else "bad",
                    "Margin-ம் மேம்பட்டிருக்கு." if good else "Margin கொஞ்சம் இறங்கிருக்கு. அடுத்த quarter-லயும் இத கவனிக்கணும்.",
                    "Margin has improved too." if good else "Margin has slipped a little. This is worth keeping an eye on next quarter too.")
    return out[:3]


def filed_ts(result: dict) -> float:
    """When the result was filed as a timestamp (NSE's time is Indian time, whatever the Mac's clock says)."""
    return nse_time(result["filed"]).timestamp()


def filed_on(result: dict) -> str:
    try:
        return datetime.strptime(result["filed"][:11], "%d-%b-%Y").strftime("%d %b %Y")
    except (ValueError, TypeError, KeyError):
        return ""


def source(result: dict) -> str:
    return " · ".join(x for x in ("Source: NSE filing", filed_on(result), "Consolidated" if result["consolidated"] else "Standalone", result.get("audited")) if x)


def deck(result: dict, per_table: int = 4, reasons: list[dict] = (), ratios: list[dict] = (), news: list[dict] = ()) -> list[dict]:
    """Notice, cover, the numbers, then (when there are any) the company's reasons, the key ratios and the news, then the takeaways.
    `ratios` is key_ratios(...) and `news` the headlines kept (news_pick); each is left out when empty."""
    name, q = short(result["name"]), result["quarter"]
    rows = []
    for x in result["rows"]:
        c, b = change(x), change(x, "prev")
        rows.append({"key": x["key"], "label": f"{x['label']} [{UNIT[x['unit']]}]", "was": shown(x["year"], x["unit"]), "now": shown(x["now"], x["unit"]),
                     "change": c["text"] if c else "–", "tone": c["tone"] if c else "flat", "note": f"{result['before']}: {shown(x['prev'], x['unit'])}" if b else ""})
    size = per_table if len(rows) <= per_table or len(rows) > per_table + 2 else (len(rows) + 1) // 2      # five or six rows: two even tables
    tables = [{"kind": "table", "title": f"{q} · Numbers", "cols": [result["year_ago"], q, "YoY"], "items": rows[i:i + size]} for i in range(0, len(rows), size)]
    return [NOTICE,
            {"kind": "cover", "title": f"{name} · {q} Result", "items": [
                {"icon": icon(result), "text": result["symbol"]}, {"icon": "paper", "text": q}, {"icon": "lens", "text": "என்ன சொல்லுது?"}]},
            *tables, *extras(result, reasons, ratios, news),
            {"kind": "points", "title": "ஆக மொத்தம்", "items": takeaways(result), "note": "Company report பண்ண numbers மட்டும் · முதலீட்டு ஆலோசனை இல்ல"}]


def _row_line(x: dict, result: dict) -> str:
    name, c, b = SAY[x["key"]], change(x), change(x, "prev")
    out = [MEANS[x["key"]]] if x["key"] in MEANS else []
    if not c:
        out.append(f"{name} இந்த quarter-ல {spoken(x['now'], x['unit'])}.")
    elif x["unit"] == "pct":
        verb = "அதே அளவுல இருக்கு" if not c["way"] else f"{spoken(x['now'], 'pct')}-க்கு {'ஏறிருக்கு' if c['way'] > 0 else 'இறங்கிருக்கு'}"
        out.append(f"{name} போன வருஷம் இதே quarter-ல {spoken(x['year'], 'pct')}. இப்போ {verb}." if c["way"] else f"{name} போன வருஷம் மாதிரியே {spoken(x['now'], 'pct')}-ல இருக்கு.")
    else:
        out.append(f"{name} போன வருஷம் இதே quarter-ல {spoken(x['year'], x['unit'])}. இப்போ {spoken(x['now'], x['unit'])}.")
        out.append("கிட்டத்தட்ட அதே அளவுதான்." if not c["way"] else f"அதாவது {c['amount']} percent {'வளர்ச்சி' if c['way'] > 0 else 'குறைவு'}.")
    if b and b["way"] and x["unit"] != "pct":
        out.append(f"போன quarter-ஓட பாத்தா {b['amount']} percent {'ஏற்றம்' if b['way'] > 0 else 'இறக்கம்'}.")
    return " ".join(out)


def _row_en(x: dict) -> str:
    """The English caption of a row's line: the same figures as `_row_line`, in plain spoken English."""
    name, c, b, unit = SAY[x["key"]], change(x), change(x, "prev"), x["unit"]
    out = [MEANS_EN[x["key"]]] if x["key"] in MEANS_EN else []
    if not c:
        out.append(f"{name} this quarter is {fig_en(x['now'], unit)}.")
    elif unit == "pct":
        out.append(f"{name} was {fig_en(x['year'], unit)} in the same quarter last year. Now it has {'risen' if c['way'] > 0 else 'fallen'} to {fig_en(x['now'], unit)}."
                   if c["way"] else f"{name} is at {fig_en(x['now'], unit)}, the same as last year.")
    else:
        out.append(f"{name} was {fig_en(x['year'], unit)} in the same quarter last year. Now it is {fig_en(x['now'], unit)}.")
        out.append("It is about the same." if not c["way"] else f"That is {c['amount']}% {'growth' if c['way'] > 0 else 'lower'}.")
    if b and b["way"] and unit != "pct":
        out.append(f"Against the last quarter, it is {b['amount']}% {'higher' if b['way'] > 0 else 'lower'}.")
    return " ".join(out)


def _weight(x: dict) -> float:
    c = change(x)
    return 0.0 if not c or x["key"] in NO_JOKE else abs(c["size"]) * (10 if x["unit"] == "pct" else 1)


def lines(result: dict, slides: list[dict], ratios: list[dict] = ()) -> list[dict]:
    """One spoken line per thing that appears on the slides, in order. `ratios` are the rows behind the Key Ratios slide, if it is there."""
    name, q = said_name(result), result["quarter"]
    by_key = {x["key"]: x for x in result["rows"]}
    qn, fy = q.split()
    nth = {"Q1": "முதல்", "Q2": "ரெண்டாவது", "Q3": "மூணாவது", "Q4": "நாலாவது"}[qn]
    nth_en, name_en = {"Q1": "first", "Q2": "second", "Q3": "third", "Q4": "fourth"}[qn], short(result["name"])
    out = [{"slide": 0, "show": 1, "say": NOTICE_SAY, "en": NOTICE_SAY_EN, "fixed": True, "hold": NOTICE_HOLD},
           {"slide": 1, "show": 1, "say": f"வணக்கம் நண்பர்களே! {name}-ஓட {qn} result வந்துருக்கு. இது {fy}-ஓட {nth} quarter.",
            "en": f"Hello friends! {name_en}{"'" if name_en.endswith("s") else "'s"} {qn} result is out. This is the {nth_en} quarter of {fy}."},
           {"slide": 1, "show": 3, "say": "Numbers என்ன சொல்லுது? நல்லா இருக்கா, கவனிக்க வேண்டியது ஏதாவது இருக்கா? வாங்க பாக்கலாம்.",
            "en": "What do the numbers say? Are they good, or is there something to keep an eye on? Let's see."}]
    for s, slide in enumerate(slides):
        if slide["kind"] == "table":
            out += [{"slide": s, "show": i + 1, "say": _row_line(by_key[r["key"]], result), "en": _row_en(by_key[r["key"]]), "tone": r["tone"], "weight": _weight(by_key[r["key"]])}
                    for i, r in enumerate(slide["items"])]
        elif slide["kind"] == "facts":                              # the key ratios: the analysis video's own wording for each
            rows = {r["key"]: r for r in ratios}
            for i, it in enumerate(slide["items"]):
                say, tone, _ = _fact_line(rows[it["key"]], financial(result))
                out.append({"slide": s, "show": i + 1, "say": say, "en": _fact_en(rows[it["key"]], financial(result)), "tone": tone})
        elif slide["kind"] == "quotes":
            out += quote_lines(s, slide)
        elif slide["kind"] == "points":
            out += [{"slide": s, "show": i + 1, "say": it["say"], **en_of(it, "en"), "tone": it["tone"]} for i, it in enumerate(slide["items"])]
            out += closing(s, len(slide["items"]) + 1)
    return out


def closing(s: int, show: int) -> list[dict]:
    """The last two lines of a long video: the closing line (unchanged) and then the sign-off asking for a subscribe and the bell, both fixed. The slide stays the last one."""
    return [{"slide": s, "show": show, "say": CLOSING, "en": CLOSING_EN, "fixed": True}, {"slide": s, "show": show, "say": SUBSCRIBE_LONG, "en": SUBSCRIBE_LONG_EN, "fixed": True}]


def en_of(d: dict, key: str) -> dict:
    """`{"en": caption}` when the slide's data has one, else nothing: a line without a caption simply shows none."""
    return {"en": d[key]} if d.get(key) else {}


def quote_lines(s: int, slide: dict) -> list[dict]:
    """The spoken lines of a quotes slide: an optional intro, then each item that has a line of its own (item["say"]). A row with no line is shown
    with the next one's, or with the last line when it trails; the source note appears with the last line."""
    items, note = slide["items"], 1 if slide.get("note") else 0
    spoken = [i for i, it in enumerate(items) if it.get("say")]
    out = []
    if slide.get("intro"):
        out.append({"slide": s, "show": 1 if spoken else len(items) + note, "say": slide["intro"], "fixed": True, **en_of(slide, "intro_en")})
    out += [{"slide": s, "show": i + 1, "say": items[i]["say"], "tone": items[i].get("tone", "flat"), "fixed": True, **en_of(items[i], "en")} for i in spoken]
    if spoken and spoken[-1] < len(items) - 1 or note and out:        # whatever has not appeared yet appears with the last line
        out[-1] = {**out[-1], "show": len(items) + note}
    return out


# ---- the analysis video: one company's ratios, no quarter comparison -----------------------------------------------------------

MEANS.update({
    "ttm_revenue": "Revenue-னா, company தன்னோட பொருளையோ சேவையையோ வித்து வாங்கின மொத்த பணம்.",
    "ttm_profit": "Net profit-னா, எல்லா செலவும் வரியும் போக, கடைசியா company கையில மிஞ்சுற லாபம்.",
    "npm": "Net margin-னா, நூறு ரூபாய் revenue-ல கடைசியா எவ்வளவு லாபமா மிஞ்சுதுன்னு சொல்றது.",
    "rev_growth": "Revenue growth-னா, விற்பனை எவ்வளவு percent கூடியிருக்கு அல்லது குறைஞ்சிருக்குன்னு காட்டுறது.",
    "profit_growth": "Profit growth-னா, லாபம் எவ்வளவு percent கூடியிருக்கு அல்லது குறைஞ்சிருக்குன்னு காட்டுறது.",
    "roe": "ROE-னா, share holders போட்ட பணத்துக்கு company எவ்வளவு லாபம் சம்பாதிக்குதுன்னு காட்டுறது. நூறு ரூபாய் போட்டா எவ்வளவு திரும்ப வருதுன்னு நினைச்சுக்கோங்க.",
    "roce": "ROCE-னா, company எடுத்த மொத்த முதலுக்கு, அதாவது சொந்த பணமும் கடனும் சேர்த்து, எவ்வளவு லாபம் வருதுன்னு காட்டுறது.",
    "roa": "ROA-னா, company-ஓட மொத்த assets வச்சு எவ்வளவு லாபம் எடுக்குதுன்னு காட்டுறது.",
    "turnover": "Asset turnover-னா, company தன்னோட assets வச்சு எத்தன மடங்கு revenue எடுக்குதுன்னு காட்டுறது.",
    "reserves": "Reserves-னா, company இதுவரைக்கும் சம்பாதிச்சு, வெளிய எடுக்காம உள்ளயே சேர்த்து வச்ச லாபம்.",
    "debt": "Debt-னா, company வெளிய இருந்து வாங்கின கடன்.",
    "leases": "Lease liabilities-னா, வாடகைக்கு எடுத்த இடம், கட்டிடம் மாதிரி விஷயங்களுக்கு கட்ட வேண்டிய பணம்.",
    "de": "Debt to equity-னா, சொந்த பணத்துக்கு எவ்வளவு கடன் இருக்குன்னு காட்டுறது.",
    "cash": "Cash-னா, company கையில இருக்கிற ரொக்கம்.",
    "bv": "Book value-னா, company எல்லா கடனும் அடைச்சா, ஒரு share-க்கு மிஞ்சுற மதிப்பு.",
    "promoter": "Promoter holding-னா, company-ய ஆரம்பிச்சவங்க, அவங்க குடும்பம் கிட்ட இருக்கிற share சதவீதம்.",
    "cfo": "Operating cash flow-னா, தினசரி business நடத்தி, company கையில உண்மையா வந்த பணம்.",
    "fcf": "Free cash flow-னா, operating cash flow-ல இருந்து machine, கட்டிடம் மாதிரி செலவுகள கழிச்சா மிஞ்சுற பணம்.",
    "price": "Price-னா, market-ல ஒரு share எந்த விலைக்கு வித்துச்சுங்கிறது.",
    "mcap": "Market cap-னா, share price-ய மொத்த share எண்ணிக்கையால பெருக்குனா வர்ற, company-ஓட மொத்த மதிப்பு.",
    "pe": "PE-னா, ஒரு ரூபாய் லாபத்துக்கு market எவ்வளவு கொடுக்குதுன்னு காட்டுறது.",
    "pb": "Price to book-னா, share price, book value-வ விட எத்தன மடங்கு இருக்குன்னு காட்டுறது.",
    "dyield": "Dividend yield-னா, share price-க்கு எதிரா, ஒரு வருஷத்துல dividend-ஆ எவ்வளவு percent வந்துச்சுன்னு காட்டுறது.",
    "high": "52 week high-னா, ஒரு வருஷத்துல share தொட்ட அதிகபட்ச price.",
    "low": "52 week low-னா, ஒரு வருஷத்துல share தொட்ட குறைஞ்சபட்ச price.",
    "ev": "EV to EBITDA-னா, company-ஓட மொத்த மதிப்பையும் கடனையும் சேர்த்து, ஒரு வருஷ operating லாபத்தோட ஒப்பிடுறது.",
    "ttm_premium": "Premium-னா, மக்கள் insurance policy-க்காக company-க்கு கட்டுற பணம். இதுதான் insurance company-ஓட முக்கிய வருமானம்.",
    "prem_growth": "Premium growth-னா, வர்ற premium எவ்வளவு percent கூடியிருக்கு அல்லது குறைஞ்சிருக்குன்னு காட்டுறது.",
})
MEANS_EN.update({
    "ttm_revenue": "Revenue is the total money the company took in by selling its products or services.",
    "ttm_profit": "Net profit is what is finally left in the company's hands after all costs and taxes.",
    "npm": "Net margin shows how much is finally left as profit out of every hundred rupees of revenue.",
    "rev_growth": "Revenue growth shows by what percent sales have grown or fallen.",
    "profit_growth": "Profit growth shows by what percent profit has grown or fallen.",
    "roe": "ROE shows how much profit the company earns on the money its shareholders put in. Think of it as how much comes back for every hundred rupees put in.",
    "roce": "ROCE shows how much profit the company earns on all the capital it uses, its own money and borrowed money together.",
    "roa": "ROA shows how much profit the company earns from its total assets.",
    "turnover": "Asset turnover shows how many times over the company turns its assets into revenue.",
    "reserves": "Reserves are the profits the company has earned so far and kept inside instead of paying out.",
    "debt": "Debt is the money the company has borrowed from outside.",
    "leases": "Lease liabilities are the money owed for things like rented land and buildings.",
    "de": "Debt to equity shows how much debt the company has against its own money.",
    "cash": "Cash is the money the company has in hand.",
    "bv": "Book value is what is left per share if the company paid off all its debts.",
    "promoter": "Promoter holding is the percentage of shares held by the people who started the company, and their families.",
    "cfo": "Operating cash flow is the money that actually came into the company's hands from running the business day to day.",
    "fcf": "Free cash flow is what is left of operating cash flow after spending on things like machines and buildings.",
    "price": "Price is what one share sold for in the market.",
    "mcap": "Market cap is the company's total value: the share price multiplied by the total number of shares.",
    "pe": "PE shows how much the market pays for every rupee of profit.",
    "pb": "Price to book shows how many times the book value the share price is.",
    "dyield": "Dividend yield shows what percent of the share price came back as dividend over one year.",
    "high": "The 52 week high is the highest price the share touched in a year.",
    "low": "The 52 week low is the lowest price the share touched in a year.",
    "ev": "EV to EBITDA compares the company's total value plus its debt with one year of operating profit.",
    "ttm_premium": "Premium is the money people pay the company for insurance policies. It is an insurance company's main income.",
    "prem_growth": "Premium growth shows by what percent the premium coming in has grown or fallen.",
})
# the value sentence of each ratio; {v} is the figure as spoken
TELL = {
    "ttm_revenue": "கடைசி பன்னிரண்டு மாசத்துல company-ஓட revenue {v}.", "nii": "கடைசி பன்னிரண்டு மாசத்துல net interest income {v}.",
    "ttm_profit": "அதே காலத்துல net profit {v}.", "opm": "Operating margin {v}.", "npm": "Net margin {v}.", "eps": "கடைசி பன்னிரண்டு மாசத்துல EPS {v}.",
    "roe": "ROE {v}.", "roce": "ROCE {v}.", "roa": "ROA {v}.", "turnover": "Asset turnover {v}.", "reserves": "Reserves {v}.", "debt": "மொத்த debt {v}.",
    "leases": "Lease liabilities {v}. இத debt கூட சேர்க்கல.", "de": "Debt to equity {v}.", "cash": "Cash {v}.", "bv": "Book value {v}.",
    "promoter": "Promoter holding {v}.", "cfo": "கடைசி financial year-ல operating cash flow {v}.", "fcf": "Free cash flow {v}.",
    "mcap": "அந்த price வச்சு பாத்தா market cap {v}.", "pe": "PE {v}.", "pb": "Price to book {v}.", "dyield": "Dividend yield {v}.",
    "high": "52 week high {v}.", "low": "52 week low {v}.", "ev": "EV to EBITDA {v}.",
    "lnii": "கடைசி பன்னிரண்டு மாசத்துல net interest income {v}.", "ttm_premium": "கடைசி பன்னிரண்டு மாசத்துல premium {v}.", "solvency": "Solvency ratio {v}.", "combined": "Combined ratio {v}.",
}
TELL_EN = {
    "ttm_revenue": "In the last twelve months, the company's revenue is {v}.", "nii": "In the last twelve months, net interest income is {v}.",
    "ttm_profit": "In the same period, net profit is {v}.", "opm": "Operating margin is {v}.", "npm": "Net margin is {v}.", "eps": "In the last twelve months, EPS is {v}.",
    "roe": "ROE is {v}.", "roce": "ROCE is {v}.", "roa": "ROA is {v}.", "turnover": "Asset turnover is {v}.", "reserves": "Reserves are {v}.", "debt": "Total debt is {v}.",
    "leases": "Lease liabilities are {v}. We have not added this to debt.", "de": "Debt to equity is {v}.", "cash": "Cash is {v}.", "bv": "Book value is {v}.",
    "promoter": "Promoter holding is {v}.", "cfo": "In the last financial year, operating cash flow is {v}.", "fcf": "Free cash flow is {v}.",
    "mcap": "At that price, the market cap is {v}.", "pe": "PE is {v}.", "pb": "Price to book is {v}.", "dyield": "Dividend yield is {v}.",
    "high": "The 52 week high is {v}.", "low": "The 52 week low is {v}.", "ev": "EV to EBITDA is {v}.",
    "lnii": "In the last twelve months, net interest income is {v}.", "ttm_premium": "In the last twelve months, the premium is {v}.", "solvency": "Solvency ratio is {v}.",
    "combined": "Combined ratio is {v}.",
}
MONTH = ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"]
GOOD_ROE = {False: 20, True: 15}                        # a rule of thumb for a company and for a bank


def dmy(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b %Y")


def said_date(iso: str) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{d.day} {MONTH[d.month - 1]} {d.year}"


def reading(r: dict, bank: bool = False) -> tuple[str, float, str, str, str] | None:
    """What a plain rule of thumb says of a ratio, as an observation: (tone, weight, the card's words, the sentence, its English caption), or None.
    The weight is how far the figure is from the rule (a reaction needs 10 for good, 5 for bad). Never a verdict on the share."""
    k, v = r["key"], r["value"]
    if k in ("roe", "roce"):
        hi, name = (GOOD_ROE[bank], "ROE") if k == "roe" else (20, "ROCE")
        if v >= hi:
            return "good", v - hi + 10, "நல்ல level", f"{name} {hi} percent-க்கு மேல இருந்தா பொதுவா நல்லதுன்னு சொல்லுவாங்க. இது ஒரு தோராயமான விதி மட்டும்தான். இங்க அதுக்கு மேலயே இருக்கு.", \
                f"{name} above {hi}% is usually called good. This is only a rough rule of thumb. Here it is even above that."
        if v < 10:
            return "bad", 15 - v, "கொஞ்சம் கம்மி", f"{name} பத்து percent-க்கு கீழ இருந்தா குறைவுன்னு பாப்பாங்க. இது ஒரு தோராயமான விதி மட்டும்தான். இங்க அப்படித்தான் இருக்கு.", \
                f"{name} below ten percent is usually seen as low. This is only a rough rule of thumb. That is where it stands here."
        return "flat", 0, "நடுத்தரம்", "இது நடுத்தர level-ல இருக்கு.", "This is at a middling level."
    if k == "solvency":                                 # weight 0: no joke about a regulator's capital figure
        if v >= 150:
            return "good", 0, "150-க்கு மேல", "இது IRDAI கேக்குற 150 percent-க்கு மேல இருக்கு.", "This is above the 150% IRDAI asks for."
        return "bad", 0, "150-க்கு கீழ", "இது IRDAI கேக்குற 150 percent-க்கு கீழ இருக்கு.", "This is below the 150% IRDAI asks for."
    if k == "combined":
        if v < 100:
            return "good", 0, "underwriting லாபம்", "Combined ratio நூறு percent-க்கு கீழ இருந்தா, insurance தொழில்லயே லாபம்னு அர்த்தம். இங்க அப்படித்தான் இருக்கு.", \
                   "A combined ratio below a hundred percent means the insurance business itself makes a profit. That is where it stands here."
        return "bad", 0, "underwriting நஷ்டம்", "Combined ratio நூறு percent-க்கு மேல இருந்தா, insurance தொழில்ல நஷ்டம்; லாபம் முதலீட்டு வருமானத்துல இருந்துதான் வருது. இங்க அப்படித்தான் இருக்கு.", \
               "A combined ratio above a hundred percent means the insurance business itself makes a loss, and the profit comes from investment income. That is where it stands here."
    if k == "opm" and v >= 20:
        return "good", v - 10, "வலுவான margin", "Operating margin இருபது percent-க்கு மேல இருந்தா வலுவான margin-ன்னு சொல்லுவாங்க. இது ஒரு தோராயமான விதி.", \
               "Operating margin above twenty percent is called a strong margin. This is only a rough rule of thumb."
    if k == "opm" and v < 10:
        return "flat", 0, "மெல்லிய margin", "பத்து percent-க்கு கீழ இருந்தா மெல்லிய margin-ன்னு சொல்லுவாங்க. ஆனா இது துறைக்கு துறை மாறும்.", \
               "Below ten percent is called a thin margin. But this changes from one sector to another."
    if k == "de" and not bank:
        if v <= 0.5:
            return "good", 10 + 10 * (0.5 - v), "கடன் ரொம்ப கம்மி", "Debt to equity ஒண்ணுக்கு கீழ இருந்தா, கடன் சொந்த பணத்த விட கம்மின்னு அர்த்தம். இங்க அது அரைக்கும் கீழ இருக்கு.", \
                   "Debt to equity below one means the debt is less than the company's own money. Here it is even below half."
        if v > 1.5:
            return "bad", 5 + 5 * (v - 1.5), "கடன் அதிகம்", "Debt to equity 1.5-க்கு மேல இருந்தா கடன் அதிகம்னு பாப்பாங்க. இது ஒரு தோராயமான விதி.", \
                   "Debt to equity above 1.5 is seen as high debt. This is only a rough rule of thumb."
        return "flat", 0, "மிதமான கடன்", "கடன் மிதமான அளவுல இருக்கு.", "The debt is at a moderate level."
    if k in ("rev_growth", "profit_growth", "prem_growth"):     # no reaction (weight 0): a base year with a one-off makes a joke unfair
        if v >= 10:
            return "good", 0, "வேகமான வளர்ச்சி", "இது வேகமான வளர்ச்சி.", "This is fast growth."
        if v >= 0:
            return "flat", 0, "மெதுவான வளர்ச்சி", "வளர்ச்சி மெதுவாதான் இருக்கு.", "Growth is slow."
        return ("bad", 0, "குறைஞ்சிருக்கு", "இதுல ஒரு தடவை வந்த லாபம் மாதிரி விஷயங்களும் சேர்ந்திருக்கலாம், அதனால filing-ஐயும் பாக்கணும்.",
                "A one-off gain in the earlier period can be part of this, so read the filing too.") if k == "profit_growth" else ("bad", 0, "குறைஞ்சிருக்கு", "", "")
    if k == "promoter":
        if v < 0.005:
            return "flat", 0, "promoter holding இல்ல", "இந்த company-ல promoter group-ஓட holding இல்ல.", "The promoter group has no holding in this company."
        if v >= 50:
            return "flat", 0, "பெரும்பான்மை promoter கிட்ட", "பாதிக்கு மேல share promoter group கிட்டதான் இருக்கு.", "More than half of the shares are with the promoter group."
    if k == "fcf":
        return (("good", 0, "பணம் மிஞ்சுது", "செலவுகள் போக பணம் மிஞ்சுது.", "Money is left over after the spending.") if v > 0 else
                ("bad", 0, "செலவு கூடுதல்", "செலவுகள் operating cash flow-ஐ விட அதிகமா இருந்திருக்கு.", "The spending was higher than the operating cash flow."))
    return None


# a ratio's English note (fundamentals.ratios) as the slide shows it: Tanglish, dates as 11 Sep 2026; longer phrases first
NOTES = [("interest income less finance costs", "வட்டி வருமானம் - finance costs"), ("net premium income", "net premium income"), ("gross premium written", "gross premium written"),
         ("latest quarter", "கடைசி quarter"), ("operating profit / revenue net of excise duty", "Operating profit / excise duty கழிச்ச revenue"), ("operating profit / revenue as filed", "Operating profit / filing-ல உள்ள revenue"),
         ("profit / revenue net of excise duty", "Profit / excise duty கழிச்ச revenue"), ("profit / revenue as filed", "Profit / filing-ல உள்ள revenue"),
         ("before excise duty is taken off", "excise duty கழிக்கல"), ("net of excise duty", "excise duty கழிச்சு"), ("as filed", "filing-ல உள்ளபடி"),
         ("includes profit from discontinued operations", "நிறுத்தின business லாபமும் சேரும்"), ("includes one-offs", "ஒருமுறை வருமானமும் சேரும்"),
         ("last 12 months vs the 12 before", "கடைசி 12 மாசம் vs முந்தின 12"), ("last 12 months, owners' share", "கடைசி 12 மாசம், owners பங்கு"), ("last 12 months", "கடைசி 12 மாசம்"),
         ("profit / average equity", "லாபம் / சராசரி equity"), ("profit / closing equity", "லாபம் / முடிவு equity"), ("EBIT / (equity + borrowings)", "EBIT / (equity + கடன்)"),
         ("profit / total assets", "லாபம் / மொத்த assets"), ("revenue / total assets", "revenue / மொத்த assets"), ("borrowings; lease liabilities not added", "கடன் மட்டும், lease சேர்க்கல"),
         ("shown apart from debt", "debt-ல சேர்க்கல"), ("borrowings / equity", "கடன் / equity"), ("cash and equivalents", "ரொக்கம்"), ("equity / number of shares", "equity / share எண்ணிக்கை"),
         ("price / last 12 months EPS", "price / கடைசி 12 மாச EPS"), ("price / book value", "price / book value"), ("dividends declared in the last year / price", "கடந்த வருஷ dividend / price"),
         ("(market cap + debt - cash) / operating profit", "(market cap + கடன் - ரொக்கம்) / operating profit"), ("operating cash flow less capital spending", "operating cash flow - மூலதன செலவு"),
         ]
DATED = [(r"price on ([\d\w ]{11}) x shares", r"\1 price x share எண்ணிக்கை"), (r"as (?:on|of) ([\d\w ]{11})", r"\1 நிலவரம்"),
         (r"close on ([\d\w ]{11})", r"\1 close"), (r"year to ([\d\w ]{11})", r"\1 வரை")]
SPLIT = {"turnover"}       # said as two lines, the meaning then the figure: as one line the cloned voice garbled it (NH and PIIND, 2026-10-15)
DEFINED = {"ttm_revenue", "opm", "npm", "rev_growth", "profit_growth", "prem_growth"}          # a ratio whose basis the slide always states, beside the reading


def note_ta(note: str) -> str:
    note = re.sub(r"\d{4}-\d{2}-\d{2}", lambda m: dmy(m.group(0)), note)
    for rx, ta in DATED:
        note = re.sub(rx, ta, note)
    for en, ta in NOTES:
        note = note.replace(en, ta)
    return note


def _fact(r: dict, bank: bool) -> dict:
    rd = reading(r, bank)
    label = r["label"] + (f" [{UNIT[r['unit']]}]" if r["unit"] in ("cr", "rs") else "")
    note = note_ta(r["note"])
    return {"key": r["key"], "label": label, "value": shown(r["value"], r["unit"]), "tone": rd[0] if rd else "flat",
            "note": f"{rd[2]} · {note}" if rd and r["key"] in DEFINED else rd[2] if rd else note}


def analysis_takeaways(f: dict, rows: list[dict]) -> list[dict]:
    """Up to three things the ratios show, by plain rules, in the order returns and debt, growth, margin, promoter."""
    r, bank, out = {x["key"]: x["value"] for x in rows}, financial(f), []
    hi = GOOD_ROE[bank]

    def add(icon, text, tone, say, en):
        out.append({"icon": icon, "text": text, "tone": tone, "say": say, "en": en})
    roe, de = r.get("roe"), r.get("de")
    if roe is not None and roe >= hi and (bank or (de is not None and de <= 0.5)):
        add("shield", "அதிக ROE" + ("" if bank else ", குறைந்த கடன்"), "good",
            f"ஆக மொத்தம், ROE {roe:.1f} percent." + ("" if bank else " கடன் ரொம்ப கம்மி. அதாவது சொந்த பணத்தை வச்சே நல்லா லாபம் எடுக்குறாங்க."),
            f"All in all, ROE is {roe:.1f}%." + ("" if bank else " Debt is very low. That means they earn good profit using their own money."))
    elif de is not None and de > 1.5:
        add("eye", "கடன் அதிகம்", "bad", f"ஆக மொத்தம், debt to equity {de:.1f} மடங்கு. கடன் அளவ கவனிக்க வேண்டியிருக்கு.",
            f"All in all, debt to equity is {de:.1f} times. The amount of debt is worth keeping an eye on.")
    elif roe is not None and roe >= hi:
        add("shield", "நல்ல ROE", "good", f"ஆக மொத்தம், ROE {roe:.1f} percent, நல்ல level-ல இருக்கு.", f"All in all, ROE is {roe:.1f}%, at a good level.")
    elif roe is not None and roe < 10:
        add("eye", "ROE கம்மி", "bad", f"ஆக மொத்தம், ROE {roe:.1f} percent, கொஞ்சம் குறைவா இருக்கு.", f"All in all, ROE is {roe:.1f}%, a little low.")
    rg, pg = r.get("rev_growth", r.get("prem_growth")), r.get("profit_growth")
    top, topen = ("Premium", "premium") if "prem_growth" in r else ("Revenue", "revenue")
    if rg is not None and pg is not None:
        if rg > 0 and pg > 0:
            add("up", f"{top}, profit இரண்டும் வளர்ச்சி", "good", f"{top}-உம் profit-உம் ரெண்டுமே வளர்ந்திருக்கு.", f"{top} and profit have both grown.")
        elif rg > 0:
            add("eye", f"{top} வளர்ச்சி, profit குறைவு", "flat", f"{top} வளர்ந்திருக்கு. ஆனா profit குறைஞ்சிருக்கு.", f"{top} has grown. But profit has fallen.")
        else:
            add("down", f"{top} குறைவு", "bad", f"{top} குறைஞ்சிருக்கு.", f"{top} has fallen.")
    elif pg is not None:
        add("up" if pg > 0 else "down", "Profit வளர்ச்சி" if pg > 0 else "Profit குறைவு", "good" if pg > 0 else "bad", "Profit வளர்ந்திருக்கு." if pg > 0 else "Profit குறைஞ்சிருக்கு.",
            "Profit has grown." if pg > 0 else "Profit has fallen.")
    m = r.get("opm")
    if m is not None and m >= 20:
        add("coin", "வலுவான margin", "good", f"Operating margin {m:.1f} percent, வலுவான level.", f"Operating margin is {m:.1f}%, a strong level.")
    elif m is not None and m < 10:
        add("eye", "மெல்லிய margin", "flat", f"Operating margin {m:.1f} percent, மெல்லிய margin. இது துறைக்கு துறை மாறும்.",
            f"Operating margin is {m:.1f}%, a thin margin. This changes from one sector to another.")
    sv = r.get("solvency")
    if m is None and sv is not None:
        add("shield" if sv >= 150 else "eye", "Solvency ratio" + (" 150-க்கு மேல" if sv >= 150 else " 150-க்கு கீழ"), "good" if sv >= 150 else "bad",
            f"Solvency ratio {sv:.1f} percent. IRDAI கேக்குற 150 percent-க்கு {'மேல' if sv >= 150 else 'கீழ'} இருக்கு.",
            f"Solvency ratio is {sv:.1f}%, {'above' if sv >= 150 else 'below'} the 150% IRDAI asks for.")
    p = r.get("promoter")
    if p is not None:
        add("eye", f"Promoter holding {shown(p, 'pct')}", "flat", "இந்த company-ல promoter group-ஓட holding இல்ல." if p < 0.005 else f"Promoter holding {p:.1f} percent.",
        "The promoter group has no holding in this company." if p < 0.005 else f"Promoter holding is {p:.1f}%.")
    return out[:3]


def analysis_source(f: dict) -> str:
    return " · ".join(x for x in ("Source: NSE filings", "Consolidated" if f["consolidated"] else "Standalone", f"to {dmy(f['ttm_to'])}" if f.get("ttm_to") else "") if x)


def analysis_deck(f: dict, rows: list[dict], per_table: int = 4) -> list[dict]:
    """Notice, cover, a facts table for each group of ratios (a long group is split evenly, four rows at most), the takeaways."""
    name, bank, tables = short(f["name"]), financial(f), []
    day = next((r["note"].replace("close on ", "") for r in rows if r["key"] == "price"), "")
    for group, title in GROUPS.items():
        items = [_fact(r, bank) for r in rows if r["group"] == group]
        n = -(-len(items) // per_table)
        for i in range(n):
            size = -(-len(items) // n)
            tables.append({"kind": "facts", "title": title + (f" {i + 1}/{n}" if n > 1 else "") + (f" · {dmy(day)} price" if group == "valuation" and day else ""),
                           "cols": ["Value"], "items": items[i * size:(i + 1) * size],
                           **({"note": "SEBI rule: கடைசி 30 நாள் price சொல்லக்கூடாது"} if group == "valuation" and i == n - 1 else {})})
    return [NOTICE,
            {"kind": "cover", "title": f"{name} · Fundamental Analysis", "items": [
                {"icon": icon(f), "text": f["symbol"]}, {"icon": "paper", "text": "Last 12 months · " + dmy(f["ttm_to"])}, {"icon": "lens", "text": "என்ன சொல்லுது?"}]},
            *tables,
            {"kind": "points", "title": "ஆக மொத்தம்", "items": analysis_takeaways(f, rows), "note": "Company report பண்ண numbers மட்டும் · முதலீட்டு ஆலோசனை இல்ல"}]


def _fact_line(r: dict, bank: bool, meaning: bool = True) -> tuple[str, str, float]:
    k, v = r["key"], r["value"]
    out = [MEANS[k]] if k in MEANS and meaning else []
    if k in ("rev_growth", "profit_growth", "prem_growth"):
        what = {"rev_growth": "Revenue", "prem_growth": "Premium"}.get(k, "Profit")
        basis = "போன financial year-ஓட ஒப்பிட்டா" if r["note"].startswith("FY") else "முந்தின பன்னிரண்டு மாசத்தோட ஒப்பிட்டா"
        out.append(f"{basis}, {what} {abs(v):.1f} percent {'வளர்ந்திருக்கு' if v >= 0 else 'குறைஞ்சிருக்கு'}.")
    elif k == "price":
        out.append(f"இந்த price {said_date(r['note'].replace('close on ', ''))} தேதி நிலவரம். அன்னைக்கு close ஆன price {spoken(v, 'rs')}. "
                   "SEBI விதிப்படி, educational channel-ல ஒரு share-ஓட கடைசி முப்பது நாள் price-ஐ சொல்லக்கூடாது. அதனாலதான் இந்த பழைய price-ஐ எடுத்துருக்கோம்.")
    elif k == "promoter" and v < 0.005:
        out.append("Promoter holding பூஜ்ஜியம் percent.")
    else:
        out.append(TELL[k].format(v=spoken(v, r["unit"])))
    rd = reading(r, bank)
    if rd and rd[3]:
        out.append(rd[3])
    return " ".join(out), rd[0] if rd else "flat", rd[1] if rd else 0.0


def date_en(iso: str) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{d.day} {d:%B %Y}"


def _fact_en(r: dict, bank: bool, meaning: bool = True) -> str:
    """The English caption of a ratio's line, with the same figures `_fact_line` says."""
    k, v = r["key"], r["value"]
    out = [MEANS_EN[k]] if k in MEANS_EN and meaning else []
    if k in ("rev_growth", "profit_growth", "prem_growth"):
        basis = "Compared with the last financial year," if r["note"].startswith("FY") else "Compared with the previous twelve months,"
        out.append(f"{basis} {({'rev_growth': 'revenue', 'prem_growth': 'premium'}).get(k, 'profit')} has {'grown' if v >= 0 else 'fallen'} by {abs(v):.1f}%.")
    elif k == "price":
        out.append(f"This price is as of {date_en(r['note'].replace('close on ', ''))}. The closing price that day was {fig_en(v, 'rs')}. "
                   "Under SEBI's rule, an educational channel cannot mention a share's price from the last thirty days. That is why we have taken this older price.")
    elif k == "promoter" and v < 0.005:
        out.append("Promoter holding is zero percent.")
    else:
        out.append(TELL_EN[k].format(v=fig_en(v, r["unit"])))
    rd = reading(r, bank)
    if rd and rd[4]:
        out.append(rd[4])
    return " ".join(out)


def analysis_lines(f: dict, rows: list[dict], slides: list[dict]) -> list[dict]:
    """One spoken line per thing that appears, in order. Each ratio: what the term means, its value, and a reading where a rule of thumb gives one."""
    name, bank = said_name(f), financial(f)
    by_key = {r["key"]: r for r in rows}
    out = [{"slide": 0, "show": 1, "say": NOTICE_SAY, "en": NOTICE_SAY_EN, "fixed": True, "hold": NOTICE_HOLD},
           {"slide": 1, "show": 1, "say": f"வணக்கம் நண்பர்களே! இன்னைக்கு {name}-ஓட fundamental analysis பாக்கலாம்.",
            "en": f"Hello friends! Today let's look at the fundamental analysis of {short(f['name'])}."},
           {"slide": 1, "show": 3, "say": "Company file பண்ண financial statements-ல இருந்து, ROE, debt, margin மாதிரி numbers என்ன சொல்லுதுன்னு பாக்கலாம். "
                                         f"இங்க இருக்கிற numbers கடைசி பன்னிரண்டு மாசத்துக்கு, {said_date(f['ttm_to'])} வரைக்கும்.",
            "en": "Let's see what numbers like ROE, debt and margin say, from the financial statements the company filed. "
                  f"The numbers here are for the last twelve months, up to {date_en(f['ttm_to'])}."}]
    for s, slide in enumerate(slides):
        if slide["kind"] == "facts":
            n = len(slide["items"])
            for i, it in enumerate(slide["items"]):
                r, show = by_key[it["key"]], i + 1 + (1 if i == n - 1 and slide.get("note") else 0)
                whole = r["key"] not in SPLIT or r["key"] not in MEANS
                if not whole:
                    out.append({"slide": s, "show": show, "say": MEANS[r["key"]], "en": MEANS_EN[r["key"]]})
                say, tone, weight = _fact_line(r, bank, meaning=whole)
                out.append({"slide": s, "show": show, "say": say, "en": _fact_en(r, bank, meaning=whole), "tone": tone, "weight": weight})
        elif slide["kind"] == "points":
            out += [{"slide": s, "show": i + 1, "say": it["say"], **en_of(it, "en"), "tone": it["tone"]} for i, it in enumerate(slide["items"])]
            out += closing(s, len(slide["items"]) + 1)
    return out


def numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip("0").rstrip(".") if "." in n else n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def keeps(plain: str, new: str) -> bool:
    """A reworded line is kept only if it adds no number the plain line lacks, drops none, gives no advice and is not rude."""
    return bool(new.strip()) and numbers(new) == numbers(plain) and not ADVICE.search(new) and not RUDE.search(new)


ASK = """You are the script editor for a Tamil stock-market YouTube channel. The host speaks colloquial Chennai Tamil mixed with English
finance words (Tanglish), written in Tamil script with the English words in Latin letters, exactly like the lines below.
Rewrite each numbered line so it sounds like a person explaining to a friend, warm and brisk, not like reading. Rules:
- Keep every number exactly as written and add no other number, date or fact. Write "percent", never the % sign.
- Keep the same meaning. No advice, no opinion on the share, no prediction: only what the company reported.
- Do not merge or split lines. Short sentences, the way people talk.
Company: {name}, {quarter}.
Lines:
{body}
Answer as {{"lines": {{"1": "...", "2": "...", ...}}}} with one entry for each of the {n} numbered lines."""


def react(said: list[dict], result: dict, turn: int | None = None) -> list[dict]:
    """The lines, with a reaction after the worst figure and after the best one when the move is big enough.

    `turn` picks which reaction from the bank (the caller counts videos so the same one does not come round twice running);
    left out, it follows from the company and the quarter."""
    turn = sum(map(ord, result["symbol"] + (result.get("quarter") or result.get("ttm_to") or ""))) if turn is None else turn
    name, out = said_name(result), list(said)
    for k, tone in enumerate(("bad", "good")):
        rows = [i for i, ln in enumerate(said) if ln.get("tone") == tone and ln.get("weight", 0) >= REACT_FROM[tone]]
        if rows:
            i, n = max(rows, key=lambda j: said[j]["weight"]), (turn + k) % len(REACT[tone])
            out[i] = {**said[i], "say": said[i]["say"].rstrip() + " " + REACT[tone][n].format(name=name), "reaction": tone,
                      **({"en": said[i]["en"].rstrip() + " " + REACT_EN[tone][n].format(name=short(result["name"]))} if said[i].get("en") else {})}
    return out


async def reword(llm, said: list[dict], result: dict, tier: str = "writer") -> tuple[list[dict], int]:
    """The lines made to sound spoken by the model; returns them and how many of the model's lines were kept."""
    body = "\n".join(f"{i + 1}. {ln['say']}" for i, ln in enumerate(said))
    ask = ASK.format(name=short(result["name"]), quarter=result.get("quarter") or f"fundamental analysis, last 12 months to {result.get('ttm_to')}", body=body, n=len(said))
    try:
        got = await llm.json(ask, tier=tier, max_tokens=4000)
    except Exception as e:  # noqa: BLE001 - no model, no rewording: the plain lines stand
        log.warning("market: the writer did not answer (%s); plain lines used", e)
        got = None
    new = (got or {}).get("lines") if isinstance(got, dict) else None
    if isinstance(new, list):                           # a list is taken only when nothing was merged or dropped
        new = {str(i + 1): n for i, n in enumerate(new)} if len(new) == len(said) else None
    if not isinstance(new, dict):
        log.warning("market: the writer's answer could not be matched to the %s lines; plain lines used", len(said))
        return said, 0
    kept = [isinstance(new.get(str(i + 1)), str) and not ln.get("fixed") and keeps(ln["say"], new[str(i + 1)]) for i, ln in enumerate(said)]    # a verified line is never reworded
    return [{**ln, "say": new[str(i + 1)].strip()} if ok else ln for i, (ln, ok) in enumerate(zip(said, kept))], sum(kept)


# ---- the reasons behind the numbers (the company's own words), key ratios and news ----------------------------------------------

METRIC_ROW = {"revenue": "revenue", "margin": "opm", "profit": "profit", "nii": "nii", "provisions": "provisions", "npa": "gnpa"}   # a reason -> the row it must agree with
ROW_OF = {"lender": {"nii": "lnii", "provisions": "impair"}, "life": {"revenue": "premium"}, "general": {"revenue": "gwp"}}      # the row a reason's metric means, for a form that names it differently
CHIP = {"revenue": "Revenue", "margin": "Margin", "profit": "Profit", "nii": "NII", "provisions": "Provisions", "npa": "Gross NPA", "outlook": "Guidance"}
WORD = {"revenue": "revenue", "margin": "margin", "profit": "profit", "nii": "net interest income", "provisions": "provisions", "npa": "வராக்கடன்"}
VERB, ARROW = {"up": "ஏறிருக்கு", "down": "குறைஞ்சிருக்கு"}, {"up": "▲", "down": "▼", "none": "="}
TIME = re.compile(r"share price|stock price|price target|\bprices?\b|\btargets?\b|valuation|re-?rating|ஷேர் விலை|விலை|இலக்கு", re.I)    # an outlook says nothing of the share
LATIN = re.compile(r"[A-Za-z]")
# the quote must speak of what the reason says it explains
ABOUT = {"revenue": r"revenue|growth|sales|deal|demand|order|business|volume|client|customer", "margin": r"margin|cost|efficien|profitab|wage|utili[sz]ation|productiv|pricing|expense",
         "profit": r"profit|earning|income|margin|cash|cost", "nii": r"interest|\bnim\b|margin|advances|loan|deposit", "provisions": r"provision|credit cost|stress|asset quality|write|slippage",
         "npa": r"\bnpa|asset quality|slippage|stress|recover|non-performing|gnpa", "outlook": r"expect|outlook|guidance|going forward|ahead|\bwill\b|\bplan|aim|intend|anticipate|pipeline|visibility|confiden"}
# a reason says why or what drove it; a sentence that only restates a figure is not one
CAUSE = re.compile(r"due to|driven by|on account of|because|owing to|led by|supported by|aided by|helped by|result of|on the back of|thanks to|attributable|deal|win|demand|momentum|pipeline"
                   r"|partnership|invest|wage|cost|pricing|volume|expansion|improv|lower|higher|declin|increase|reduc|growth in|broad-based|expect", re.I)
STOP = {"this", "that", "with", "from", "have", "been", "were", "into", "their", "there", "which", "while", "also", "more", "than", "over", "such", "like", "year", "quarter",
        "company", "said", "says", "about", "after", "will", "would", "could", "other", "these", "those", "across", "despite", "driven", "supported", "following"}


def supported(point: str, quote: str) -> bool:
    """Is the point said in the quote's own words? At least 60 % of the point's longer words (compared by their first five letters) are in the quote."""
    stems = lambda t: {w[:5] for w in re.findall(r"[a-z]{4,}", norm(t)) if w not in STOP}      # noqa: E731
    want, have = stems(point), stems(quote)
    return len(want) >= 3 and len(want & have) >= 0.6 * len(want)
REASONS = """You help a Tamil stock-market YouTube channel explain WHY a company's numbers moved, using only the company's own documents.
Company: {name}, {quarter} result. The numbers (year on year): {moves}.
Documents (text copied from the company's filings):
{text}

Find up to 5 reasons the company itself gives for how these numbers moved, or what it says it expects next. Answer as
{{"reasons": [{{"metric": "revenue|margin|profit|nii|provisions|npa|outlook", "direction": "up|down|none", "point": "...", "quote": "...", "say": "..."}}]}}
- metric: what the reason explains. "outlook" is only for a sentence where the company says what it expects, plans or aims for in future (guidance), never for something that already happened.
- direction: how that NUMBER moved year on year (up, down or none), as the numbers above show it. For provisions and npa it is the number itself, not good or bad.
- point: at most 25 English words, what the company said, in the quote's own words. No opinion, no advice, nothing about the share price. Do not add a cause the quote does not give.
- quote: ONE sentence copied EXACTLY, character for character, from the documents above (at least 40 characters). Never paraphrase it.
- say: the same point in one or two spoken sentences of colloquial Chennai Tamil, spoken by a presenter ABOUT the company (third person: "Company", "அவங்க"; never "we"/"நாங்கள்"), written ENTIRELY in Tamil script, with no English letters at all. English words
  are written in Tamil letters the way a Tamil speaker says them (ரெவென்யூ, மார்ஜின், க்ரோத், டீல், குவார்ட்டர்); abbreviations too, letter by letter (AI = ஏஐ, IT = ஐடி, US = யூஎஸ்).
  Numbers stay in digits; leave out "$", "US$" and units that need Latin letters (say டாலர்).
- Every number in point and in say must appear in the quote. Do not add or work out any number.
If the documents give no such reason, answer {{"reasons": []}}."""


def row_key(result: dict, metric: str) -> str | None:
    return ROW_OF.get(nse.shape(result), {}).get(metric) or METRIC_ROW.get(metric)


def moves(result: dict) -> str:
    """The result's year-on-year moves in a sentence for the model: "revenue up 10%, operating margin down 0.5 pts"."""
    out = []
    for x in result["rows"]:
        c = change(x)
        if c:
            out.append(f"{SAY[x['key']].lower()} {'up' if c['way'] > 0 else 'down' if c['way'] < 0 else 'about the same'}{' ' + c['amount'] + ('pts' if x['unit'] == 'pct' else '%') if c['way'] else ''}")
    return ", ".join(out)


def check_reason(item: object, doc: str, result: dict) -> str:
    """Why a reason from the model is thrown away, or "" when it is kept. `doc` is the normalised text the model was given."""
    if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("metric", "direction", "point", "quote", "say")):
        return "not a complete item"
    metric, way, point, quote, say = (item[k].strip() for k in ("metric", "direction", "point", "quote", "say"))
    if metric not in CHIP or way not in ("up", "down", "none"):
        return "unknown metric or direction"
    if len(quote) < 40 or norm(quote).rstrip(" .,;:") not in doc:
        return "quote is not in the document"
    if not numbers(point) <= numbers(quote) or not numbers(say) <= numbers(quote):
        return "a number is not in the quote"
    if not supported(point, quote):
        return "the point is not in the quote's words"
    if not re.search(ABOUT[metric], quote, re.I):
        return "the quote does not speak of that metric"
    if metric != "outlook" and not CAUSE.search(quote):
        return "the quote gives no reason, it restates a figure"
    if LATIN.search(say) or re.search(r"[$\u20b9\u20ac\u00a3]", say) or not say:           # a currency sign is read badly by the voice: it must be a word
        return "spoken line is not all Tamil script"
    named = re.sub(r"\b[A-Z]\w+ (?:Buy|Sell|Target)\b", "", point)                  # a company called Best Buy is not advice
    if ADVICE.search(say) or RUDE.search(say) or ADVICE.search(named) or RUDE.search(point):
        return "advice or rude wording"
    if metric == "outlook":
        return "price or target wording in an outlook" if TIME.search(point + " " + say) else ""
    row = next((x for x in result["rows"] if x["key"] == row_key(result, metric)), None)
    c = row and change(row)
    if not c:
        return "no figure of ours to agree with"
    return "" if {"up": 1, "down": -1, "none": 0}[way] == c["way"] else "direction differs from our figure"


WORD_EN = {"revenue": "revenue", "margin": "margin", "profit": "profit", "nii": "net interest income", "provisions": "provisions", "npa": "bad loans"}
VERB_EN = {"up": "rise", "down": "fall"}


def lead_en(metric: str, way: str) -> str:
    """The English of `lead`."""
    if metric == "outlook":
        return "What happens next? As per the company's guidance:"
    word = WORD_EN[metric]
    return f"Why did {word} {VERB_EN[way]}? The company's reason:" if way in VERB_EN else f"{word.capitalize()} stayed about the same. The company's reason:"


def lead(metric: str, way: str) -> str:
    """The fixed Tanglish question that opens a reason's spoken line (the company's own wording follows it)."""
    if metric == "outlook":
        return "அடுத்து என்ன நடக்கும்? Company-ஓட guidance படி,"
    word = WORD[metric]
    return f"ஏன் {word} {VERB[way]}? Company சொல்ற காரணம் இது." if way in VERB else f"{word} அதே அளவுலதான் இருக்கு. Company சொல்ற காரணம் இது."


async def reasons(llm, result: dict, text: str, tier: str = "writer", dropped: list | None = None) -> list[dict]:
    """Up to three reasons (strongest-moving figure first) and one outlook, each checked by code; anything else the model said is dropped.

    A reason is kept only if its quote is in `text` (at least 40 characters), every number in its point and its spoken line is in the quote, the
    spoken line has no Latin letters and no advice, and its direction is the direction of our own year-on-year figure for that metric. An outlook has
    no figure to agree with but must say nothing of price or targets. No model, no text or nothing surviving gives [] (the video has no reasons slide).
    `dropped`, if given, receives (item, why) for each one thrown away."""
    if not llm or not text.strip():
        return []
    ask = REASONS.format(name=short(result["name"]), quarter=result["quarter"], moves=moves(result), text=text)
    try:
        got = await llm.json(ask, tier=tier, max_tokens=3000)
    except Exception as e:  # noqa: BLE001 - no model, no reasons
        log.warning("market: the writer did not give reasons (%s)", e)
        return []
    items = (got or {}).get("reasons") if isinstance(got, dict) else None
    doc, kept = norm(text), []
    for it in items if isinstance(items, list) else []:
        why = check_reason(it, doc, result)
        if why:
            log.info("market: reason dropped (%s)", why)
            if dropped is not None:
                dropped.append((it, why))
            continue
        row = next((x for x in result["rows"] if x["key"] == row_key(result, it["metric"])), None)
        c = row and change(row)
        kept.append({**{k: it[k].strip() for k in ("metric", "direction", "point", "quote", "say")}, "weight": _weight(row) if row else 0.0,
                     "tone": c["tone"] if c else "flat", "row": row["key"] if row else None})
    main, seen = [], set()
    for r in sorted((r for r in kept if r["metric"] != "outlook"), key=lambda r: -r["weight"]):
        if r["metric"] not in seen:
            seen.add(r["metric"])
            main.append(r)
    return main[:3] + [r for r in kept if r["metric"] == "outlook"][:1]


def source_note(docs: list[dict]) -> str:
    """"Source: Press Release, 08 Oct 2026, filed with NSE" for the documents the reasons came from."""
    return "Source: " + " · ".join(f"{d['subject']}, {dmy(d['at'][:10])}" for d in docs) + ", filed with NSE"


def reason_slide(items: list[dict], docs: list[dict]) -> dict:
    rows = [{"label": f"{CHIP[r['metric']]} {ARROW[r['direction']] if r['metric'] != 'outlook' else ''}".strip(), "tone": r["tone"] if r["metric"] != "outlook" else "flat",
             "text": r["point"], "say": lead(r["metric"], r["direction"]) + " " + r["say"],
             "en": lead_en(r["metric"], r["direction"]) + " " + r["point"]} for r in items]
    return {"kind": "quotes", "title": "ஏன் இப்படி? · Company சொன்னது", "items": rows, "note": source_note(docs)}


KEY = {"company": ("roe", "roce", "de", "npm"), "bank": ("roe", "roa", "bv"), "lender": ("roe", "roa", "bv"), "plain": ("roe", "npm", "bv"),
       "life": ("roe", "solvency", "bv"), "general": ("roe", "combined", "solvency", "bv")}


def key_ratios(rows: list[dict], kind: str | bool) -> list[dict]:
    """The filing-based ratios the results video shows (fundamentals.ratios rows), never a price-based one. `kind` is nse.shape(...); a bool is the older
    bank / not a bank."""
    by = {r["key"]: r for r in rows}
    return [by[k] for k in KEY["bank" if kind is True else "company" if kind is False else kind] if k in by]


def extras(result: dict, reasons_: list[dict], ratios: list[dict], news: list[dict]) -> list[dict]:
    """The slides between the numbers and the takeaways, in order, each only when there is something to show."""
    out = []
    docs = list({d["url"]: d for r in reasons_ for d in [r["doc"]]}.values()) if reasons_ else []
    if reasons_:
        out.append(reason_slide(reasons_, docs))
    if ratios:
        out.append({"kind": "facts", "title": "Key Ratios", "cols": ["Value"], "items": [_fact(r, financial(result)) for r in ratios]})
    if news:
        out.append(news_slide(news))
    return out


# news: headlines about the result, shown as published, never about the share price or anyone's advice
PRICEY = re.compile(r"share price|\b(?:shares?|stocks?)\b.*\b(?:jump|surge|rall|fall|slip|tank|soar|gain|drop|plunge|climb|slide|rise|rose|sink|sank|cut|hit)\w*"
                    r"|\b(?:jump|surge|rall|fall|slip|tank|soar|gain|drop|plunge|climb|slide|sink)\w*\b.*\b(?:shares?|stocks?)\b"
                    r"|target|\bbuy\b|\bsell\b|brokerage|upgrade|downgrade|multibagger|rating|\bnifty\b|\bsensex\b|price", re.I)


PREVIEW = re.compile(r"preview|expectations?|what to expect|date and time|live updates|schedule|set to announce|to announce|ahead of|could see|likely to|expected|key focus", re.I)           # written before the result: not about it
MOVE = "rises?|falls?|jumps?|surges?|slips?|tanks?|soars?|gains?|drops?|plunges?|climbs?|slides?|sinks?|slumps?|rallies|crash\\w*"    # "TCS rises": the share, not the company


SOCIAL = {"facebook", "youtube", "x", "twitter", "instagram", "reddit", "linkedin", "telegram"}          # not a publication
ABOUT_RESULT = re.compile(r"results?|earnings|\bQ[1-4]\b|quarter|profit|revenue|net income|\bnii\b|margin", re.I)


def news_pick(items: list[dict], name: str, symbol: str, limit: int = 3, near: float | None = None) -> list[dict]:
    """Up to `limit` headlines that name the company (whole word) from different publications, newest first; any about the share price or advice is dropped.
    Headlines about the result come first, then those closest in time to `near` (the filing, a timestamp; else the newest); with `near`, one published
    more than 12 hours before the filing (the filing's time can be hours after the company's announcement) is left out.
    Items are news.fetch_feed's {title, source, link, ts}. Result: {title, source, link, at (ISO date)}."""
    names = [re.compile(r"(?<![\w])" + re.escape(n) + r"(?![\w])", re.I) for n in (name, symbol) if n]
    moved = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(n) for n in (name, symbol) if n) + r")\s+(?:" + MOVE + r")\b", re.I)
    out, pubs = [], set()
    for it in sorted(items, key=lambda i: (not ABOUT_RESULT.search(i["title"]), abs(i["ts"] - near) if near else -i["ts"])):
        pub = (it.get("source") or "").strip().lower()
        if near and it["ts"] < near - 12 * 3600:
            continue
        letters = re.findall(r"[^\W\d_]", it.get("title") or "")
        if len([c for c in letters if c.isascii()]) < 0.9 * len(letters) or pub in SOCIAL:            # English headlines from publications only
            continue
        if not it.get("title") or not pub or pub in pubs or PRICEY.search(it["title"]) or ADVICE.search(it["title"]) or PREVIEW.search(it["title"]) or moved.search(it["title"]) or not any(n.search(it["title"]) for n in names):
            continue
        pubs.add(pub)
        out.append({"title": it["title"], "source": it["source"].strip(), "link": it.get("link", ""), "at": datetime.fromtimestamp(it["ts"]).date().isoformat()})
    return out[:limit]


NEWS_ASK = """You help a Tamil stock-market YouTube channel. Below are news headlines about a company's quarterly result. For each, write what the headline says
in ONE short spoken sentence of colloquial Chennai Tamil, written ENTIRELY in Tamil script: no English letters at all, so call the company "{name}", write
Q2 as "ரெண்டாவது குவார்ட்டர்", and write English words in Tamil letters the way a Tamil speaker says them (profit = ப்ராஃபிட், revenue = ரெவென்யூ).
Example: "TCS Q2 profit rises" -> "{name}-ஓட ரெண்டாவது குவார்ட்டர் ப்ராஃபிட் ஏறிருக்கு.". Say only what the headline says: add no fact, no opinion, nothing about the share price, and say no numbers (say "rose" or "fell", not by how much).
Headlines:
{body}
Answer as {{"gists": {{"1": "...", "2": "..."}}}}."""


async def news_gists(llm, news: list[dict], name: str = "", tier: str = "writer") -> list[str]:
    """One spoken sentence per headline from the model, or "" for a headline whose sentence fails (a number not in the headline, Latin letters, advice)."""
    if not llm or not news:
        return [""] * len(news)
    try:
        got = await llm.json(NEWS_ASK.format(name=name or "கம்பெனி", body="\n".join(f"{i + 1}. {n['title']}" for i, n in enumerate(news))), tier=tier, max_tokens=1500)
    except Exception as e:  # noqa: BLE001
        log.warning("market: the writer did not summarise the headlines (%s)", e)
        return [""] * len(news)
    said = (got or {}).get("gists") if isinstance(got, dict) else None
    out = []
    for i, n in enumerate(news):
        g = said.get(str(i + 1)) if isinstance(said, dict) else None
        ok = isinstance(g, str) and g.strip() and not LATIN.search(g) and numbers(g) <= numbers(n["title"]) and not ADVICE.search(g) and not RUDE.search(g) and not TIME.search(g)
        out.append(g.strip() if ok else "")
    return out


ORDINAL = ["முதல்", "ரெண்டாவது", "மூணாவது"]
NEWS_INTRO = ("இந்த result பத்தி வந்த சில headlines இங்க இருக்கு. இது screen-ல பேர் இருக்கிற news sources-ல இருந்து எடுத்தது. "
              "நான் headline சொல்றத மட்டும் சொல்றேன், முழு கட்டுரை இல்ல.")


NEWS_INTRO_EN = ("Here are a few headlines about this result. They come from the news sources named on the screen. "
                 "I am only saying what each headline says, not the full article.")
ORDINAL_EN = ["The first", "The second", "The third"]


def news_slide(news: list[dict]) -> dict:
    """The headlines as published; a headline with a verified "gist" (news_gists) also gets a spoken sentence."""
    rows = [{"label": f"{n['source']} · {datetime.strptime(n['at'], '%Y-%m-%d').strftime('%d %b')}", "tone": "flat", "text": n["title"],
             **({"say": f"{ORDINAL[i % 3]} headline சொல்றது இது: {n['gist']}", "en": f"{ORDINAL_EN[i % 3]} headline says: {n['title']}"} if n.get("gist") else {})}
            for i, n in enumerate(news)]
    return {"kind": "quotes", "title": "News-ல", "items": rows, "intro": NEWS_INTRO, "intro_en": NEWS_INTRO_EN, "note": "Headlines as published · முழு கட்டுரை இல்ல · price பத்தி இல்ல"}


# ---- the pre-market and post-market Shorts: figures only, from templates, no model ----------------------------------------------------------------

# SEBI's rule on recent price data: report what happened, never what may happen. No line of a report may say any of this (tests run every template through it).
FORECAST = re.compile(r"\b(will|would|expect\w*|forecast\w*|predict\w*|projected?|gap[- ]?(?:up|down)|opens?\s+(?:higher|lower)|targets?|support|resistance|breakouts?"
                      r"|bullish|bearish|likely|may|might|could|should|watch\w*|levels?\s+to\s+watch|outlook|upside|downside|tomorrow)\b"
                      r"|ஆகும்|போகும்|இருக்கும்|ஏறும்|இறங்கும்|விழும்|எதிர்பார்|இலக்கு|சப்போர்ட்|ரெசிஸ்டன்ஸ்|கேப் ?அப்|கேப் ?டவுன்|முன்னறிவி|கணிப்|வாய்ப்பு|நாளை|அடுத்த|பாருங்க.*லெவல்", re.I)
SIGN_OFF = SUBSCRIBE_SHORT                          # the last line of every Short (the owner's words)
REPORT_REACT_FROM = 1.5                             # the day's biggest mover earns one comic reaction when it moved this many percent
REPORT_FLAT = 0.05                                  # percent: a smaller move is "about the same"
REPORT_HEAD = {"premarket": {"gift"}, "postmarket": {"nifty", "sensex"}}      # the indices told in more detail, with their level
REPORT_ARROW = {1: "▲", -1: "▼", 0: "■"}


def _latin(text: str) -> list[str]:
    from .tamil_say import voiced
    return sorted(set(re.findall(r"[A-Za-z]{2,}", voiced(text))))


def _way(pct: float) -> int:
    return 0 if abs(pct) < REPORT_FLAT else (1 if pct > 0 else -1)


def _pct_text(pct: float) -> str:
    return f"{abs(pct):.2f}".rstrip("0").rstrip(".") or "0"


def _level(i: dict) -> str:
    """The level for the slide: Indian grouping for an Indian index, the usual commas elsewhere."""
    if i["key"] in ("gift", "nifty", "sensex", "banknifty"):
        return grouped(i["last"])
    return f"{i['last']:,.0f}" if i["last"] >= 1000 else f"{i['last']:,.2f}"


def report_deck(kind: str, data: dict) -> list[dict]:
    """One tall slide: the title pill and one block per region, each with a row per index (name, level, arrow and percent, coloured by direction)."""
    head, d = REPORT_HEAD[kind], data["date"]
    blocks = []
    for r in data["regions"]:
        rows = [{"label": i["name"], "value": _level(i), "arrow": REPORT_ARROW[_way(i["pct"])], "pct": f"{abs(i['pct']):.2f}%",
                 "tone": ("flat", "good", "bad")[_way(i["pct"])], "big": i["key"] in head} for i in r["items"]]
        nifty = next((i for i in r["items"] if i["key"] == "nifty" and i.get("advances") is not None and i.get("declines") is not None), None)
        blocks.append({"region": r["label"], "when": world.when(r), "rows": rows, **({"foot": f"Nifty 50 · {nifty['advances']} up · {nifty['declines']} down"} if nifty else {})})
    return [{"kind": "board", "title": f"{'Pre' if kind == 'premarket' else 'Post'}-Market · {d.day} {d:%b}", "items": blocks}]


def _said_move(i: dict, closed: bool) -> str:
    """One index as a sentence: its direction and percent. A closed session "closed", a live one "இப்போ"."""
    way, p = _way(i["pct"]), _pct_text(i["pct"])
    if closed:
        return f"{i['say']} கிட்டத்தட்ட அதே அளவுல close ஆச்சு." if not way else f"{i['say']} {p} percent {'ஏறி' if way > 0 else 'இறங்கி'} close ஆச்சு."
    return f"{i['say']} இப்போ கிட்டத்தட்ட அதே அளவுலதான் இருக்கு." if not way else f"{i['say']} இப்போ {p} percent {'ஏறிருக்கு' if way > 0 else 'இறங்கிருக்கு'}."


def _said_move_en(i: dict, closed: bool) -> str:
    way, p = _way(i["pct"]), _pct_text(i["pct"])
    if closed:
        return f"{i['say']} closed about the same." if not way else f"{i['say']} closed {p}% {'higher' if way > 0 else 'lower'}."
    return f"{i['say']} is about the same now." if not way else f"{i['say']} is {p}% {'higher' if way > 0 else 'lower'} now."


def _said_moves_en(items: list[dict], closed: bool) -> str:
    """The English of `_said_moves`: indices that moved the same way share the verb ("Dow Jones 0.35%, Nasdaq 0.15%, both closed lower.")."""
    groups: list[list[dict]] = []
    for i in items:
        if groups and _way(groups[-1][0]["pct"]) == _way(i["pct"]):
            groups[-1].append(i)
        else:
            groups.append([i])
    out = []
    for g in groups:
        way = _way(g[0]["pct"])
        if len(g) == 1:
            out.append(_said_move_en(g[0], closed))
        else:
            names = ", ".join(i["say"] if not way else f"{i['say']} {_pct_text(i['pct'])}%" for i in g)
            both = "both" if len(g) == 2 else "all"
            how = "about the same" if not way else "higher" if way > 0 else "lower"
            out.append(f"{names}, {both} closed {how}." if closed else f"{names}, {both} are {how} now.")
    return " ".join(out)


def _said_moves(items: list[dict], closed: bool) -> str:
    """Several indices in one sentence: those that moved the same way share the verb ("Dow Jones 0.35 percent, Nasdaq 0.15 percent இறங்கி close ஆச்சு")."""
    groups: list[list[dict]] = []
    for i in items:
        if groups and _way(groups[-1][0]["pct"]) == _way(i["pct"]):
            groups[-1].append(i)
        else:
            groups.append([i])
    out = []
    for g in groups:
        way = _way(g[0]["pct"])
        if len(g) == 1:
            out.append(_said_move(g[0], closed))
        else:
            names = ", ".join(i["say"] if not way else f"{i['say']} {_pct_text(i['pct'])} percent" for i in g)
            out.append(f"{names} " + (("கிட்டத்தட்ட அதே அளவுல close ஆச்சு." if closed else "இப்போ கிட்டத்தட்ட அதே அளவுலதான் இருக்கு.") if not way else
                                      (f"{'ஏறி' if way > 0 else 'இறங்கி'} close ஆச்சு." if closed else f"இப்போ {'ஏறிருக்கு' if way > 0 else 'இறங்கிருக்கு'}.")))
    return " ".join(out)


def _said_head(i: dict) -> str:
    """The headline index: its level to the whole number, the points and the percent (GIFT Nifty: the level and the percent)."""
    way, p, pts = _way(i["pct"]), _pct_text(i["pct"]), round(abs(i["change"]))
    level = round(i["last"])
    if i["key"] == "gift":
        return f"GIFT Nifty, அதாவது பழைய SGX Nifty, இப்போ {level}-ல இருக்கு. " + ("கிட்டத்தட்ட அதே அளவுதான்." if not way else f"{p} percent {'ஏற்றம்' if way > 0 else 'இறக்கம்'}.")
    done = "close ஆச்சு" if i["session"] == "closed" else "இப்போ இருக்கு"
    return f"{i['say']} {level}-ல {done}. " + ("கிட்டத்தட்ட அதே அளவுதான்." if not way or not pts else
                                          f"{pts} points {'ஏற்றம்' if way > 0 else 'இறக்கம்'}, அதாவது {p} percent.")


def _said_head_en(i: dict) -> str:
    way, p, pts = _way(i["pct"]), _pct_text(i["pct"]), round(abs(i["change"]))
    level = grouped(round(i["last"]))
    if i["key"] == "gift":
        return f"GIFT Nifty, the old SGX Nifty, is at {level} now. " + ("It is about the same." if not way else f"It is {p}% {'up' if way > 0 else 'down'}.")
    where = f"closed at {level}" if i["session"] == "closed" else f"is at {level} now"
    return f"{i['say']} {where}. " + ("It is about the same." if not way or not pts else f"It is {grouped(pts)} points {'up' if way > 0 else 'down'}, that is {p}%.")


def report_lines(kind: str, data: dict, deck: list[dict]) -> list[dict]:
    """The spoken lines, one or two per region, from plain templates: the direction and the percent of each index, nothing about what comes next.
    Each line says how many blocks of the slide are on screen; a line carries `mover` (its biggest move) for the comic reaction."""
    pre, out = kind == "premarket", []

    def add(show: int, say: str, en: str, items: list[dict] = ()):
        top = max(items, key=lambda i: abs(i["pct"]), default=None)
        out.append({"slide": 0, "show": show, "say": say, "en": en, **({"mover": {"say": top["say"], "pct": top["pct"]}} if top else {})})
    add(0, "வணக்கம் நண்பர்களே! இது pre-market update." if pre else "வணக்கம் நண்பர்களே! இது post-market update.",
        "Hello friends! This is the pre-market update." if pre else "Hello friends! This is the post-market update.")
    head, regions = REPORT_HEAD[kind], data["regions"]
    for n, r in enumerate(regions, 1):
        closed, items = r["session"] == "closed", r["items"]
        if r["id"] == "india" and pre:
            add(n, _said_head(items[0]), _said_head_en(items[0]), items)
        elif r["id"] == "india":
            for i in items:
                if i["key"] in head:
                    add(n, _said_head(i), _said_head_en(i), [i])
            rest = [i for i in items if i["key"] not in head]
            if rest:
                add(n, _said_moves(rest, True), _said_moves_en(rest, True), rest)
            nifty = next((i for i in items if i["key"] == "nifty" and i.get("advances") is not None and i.get("declines") is not None), None)
            if nifty:
                add(n, f"Nifty 50-ல {nifty['advances']} share ஏறிருக்கு, {nifty['declines']} share இறங்கிருக்கு.",
                    f"Out of Nifty 50, {nifty['advances']} shares are up and {nifty['declines']} are down.")
        else:
            lead = {"us": "US-ல.", "europe": "Europe-ல." if closed else "Europe இப்போ நடந்துட்டு இருக்கு.", "asia": "Asia-ல."}[r["id"]]
            lead_en = {"us": "In the US.", "europe": "In Europe." if closed else "Europe is trading now.", "asia": "In Asia."}[r["id"]]
            add(n, f"{lead} {_said_move(items[0], closed)}", f"{lead_en} {_said_move_en(items[0], closed)}", items[:1])
            if len(items) > 1:
                add(n, _said_moves(items[1:], closed), _said_moves_en(items[1:], closed), items[1:])
    add(len(regions), SIGN_OFF, SUBSCRIBE_SHORT_EN)
    return out


def report_react(said: list[dict], turn: int = 0) -> list[dict]:
    """After the line with the day's biggest move, when it was REPORT_REACT_FROM percent or more, one reaction from the REACT bank (good for a rise, bad for a fall).
    Only reactions that pass FORECAST / ADVICE and hold no English letters the voice would garble."""
    movers = [(abs(ln["mover"]["pct"]), n) for n, ln in enumerate(said) if ln.get("mover") and abs(ln["mover"]["pct"]) >= REPORT_REACT_FROM]
    if not movers:
        return said
    n = max(movers)[1]
    m, out = said[n]["mover"], list(said)
    tone = "good" if m["pct"] > 0 else "bad"
    bank = [(t, e) for t, e in zip(REACT[tone], REACT_EN[tone]) if not FORECAST.search(t) and not ADVICE.search(t) and not _latin(t.format(name=m["say"]))]
    if bank:
        t, e = bank[turn % len(bank)]
        out[n] = {**said[n], "say": said[n]["say"].rstrip() + " " + t.format(name=m["say"]), "reaction": tone,
                  **({"en": said[n]["en"].rstrip() + " " + e.format(name=m["say"])} if said[n].get("en") else {})}
    return out
