"""Finance lessons for Mani Market Tamil: a topic from the bank, its official pages, and a Tanglish lesson whose every fact is checked against them.

    TOPICS                      about 45 financial-literacy topics, each with 1-4 official pages (RBI, SEBI, DICGC, India Post, AMFI, Income Tax, PFRDA, IRDAI, ...)
    rank(store, signals, ...)   the topics in the order to make them: those that top Indian finance channels' recent videos are getting views for first, else the
                                least recently made; never one made within REPEAT_DAYS, never one that had no source or too little to say within SKIP_DAYS
    fetch_sources(c, topic)     the pages (HTML or PDF), a few seconds apart; a page that is dead or holds nothing on the topic is left out
    scrub(text, bad)            a channel's transcript with every sentence that names a company or stock, or talks of price, targets or the market's direction, removed
    write(llm, topic, pages)    the lesson: one request for the angle (from transcripts), one for the plan (slides), one per slide for its spoken lines
    check_line(item, ...)       why a spoken line is thrown away, or "" (the rules below); the lesson keeps only lines that pass

Mani's rules (2026-10-14), kept in code:
- Every fact and number comes from an official page fetched that night. A spoken line is kept only if each quote it gives (30+ characters) is in one of the pages,
  every number in the line (Tamil and English) is in its quotes, and it passes the same checks as the rest of the channel: all Tamil letters (the voice's own check, clone.unspelt),
  no ADVICE, FORECAST or RUDE wording, no company in the channel's index, no market direction.
- Other channels' transcripts (a call he made, against YouTube's terms) are raw material for the topic, the angle, viewers' questions and common misunderstandings: never for wording
  (a line sharing 8 or more words in a row with any transcript is thrown away) and never for facts (the plan and the lines are written from the official pages only).
- A lesson never discusses an individual stock or where the market is going.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import urlparse

import httpx

from ..services import filings_text, yt_channels
from ..services.filings_text import norm
from ..voice import clone
from . import market, youtube

log = logging.getLogger("vision.market")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "en-IN,en;q=0.9"}
DONE = "mm_done"
REPEAT_DAYS = 180                 # a topic is not made again within this many days
SKIP_DAYS = 3                     # a topic with no usable source, or too little to say, is left alone this long
SHORT_REPEAT_DAYS, SHORT_PER_TOPIC = 30, 3        # a Short covers one concept: the same topic again only after this long, and at most this many concepts from it
GAP = 1.5                         # seconds between two page downloads (kept polite; ~150 GETs in all for the validation, never more than 4 a lesson)
MAX_TOPICS = 2                    # topics tried in one night
MIN_KEPT, MIN_KEPT_SHORT = 10, 4  # spoken lines that must survive the checks, or the topic is skipped (TOO THIN)
PAGE_MIN = 800                    # a page with less text than this answered nothing
PDF_MAX = 12 << 20
PASSAGES = 11000                  # characters of official text in a plan request (about 3,000 tokens)
SLIDE_PASSAGES = 4500             # and in a request for one slide's lines
TRANSCRIPT_TOKENS = 2500          # what Groq may see of the transcripts, all together
SHINGLE = 8                       # a line sharing this many words in a row with a transcript is a copy
ICONS = ["bank", "paper", "lens", "shield", "coin", "piggy", "calendar", "goldbar", "rupee", "umbrella", "chart", "company"]
LATIN = market.LATIN

# a lesson says nothing of a share or of where the market goes (beyond ADVICE / FORECAST)
MARKET_DIR = re.compile(r"\b(nifty|sensex|bank ?nifty|bull(?:ish)?|bear(?:ish)?|rall(?:y|ies)|crash\w*|correction|share prices?|stock prices?|price targets?|hold)\b"
                        r"|நிஃப்டி|சென்செக்ஸ்|ஷேர் விலை|ஸ்டாக் விலை|புல்லிஷ்|பேரிஷ்", re.I)
BOOKISH = re.compile(r"என்பது|என்றால்|நீங்கள்|உங்கள்|செய்கிற|செய்யப்பட|இருக்கிறது|ஆகிறது|உள்ளது|வழங்குகிற|கொள்கிற|மேலாண்மை")       # book Tamil: the host talks like a friend (X னா, உங்க, பண்ணுது)
BRANDS = ("HDFC", "ICICI", "SBI", "Axis Bank", "Kotak", "Reliance", "Tata", "Adani", "Infosys", "TCS", "Wipro", "Zerodha", "Groww", "Paytm", "Upstox")   # banks and brokers are names too
SUFFIX = re.compile(r"\s*\b(limited|ltd\.?|corporation|corp\.?|company|co\.?)\b\.?$", re.I)           # a legal tail only: "Bank of India" stays whole
GENERIC = {"bank", "india", "indian", "industries", "power", "energy", "finance", "insurance", "life", "global", "international", "united", "national", "general", "capital"}     # never a name on their own

# lines Mani approved by ear (tests/golden_voice.json, the HDFC video): all Tamil letters, the way he says each word; the writer is shown them for the manner only
STYLE = [
    "நம்பர்ஸ் என்ன சொல்லுது? நல்லா இருக்கா, கவனிக்க வேண்டியது ஏதாவது இருக்கா? வாங்க பாக்கலாம்.",
    "நெட் இன்ட்ரெஸ்ட் இன்கம்னா, பேங்க் வாங்குற வட்டிக்கும் குடுக்குற வட்டிக்கும் உள்ள வித்தியாசம். பேங்கோட முக்கிய வருமானம் இதுதான்.",
    "ஆப்பரேட்டிங் ப்ராஃபிட்னா, கடன் இழப்புக்கு பணம் ஒதுக்குறதுக்கு முன்னாடி பேங்க் சம்பாதிச்சது.",
    "க்ராஸ் என்பிஏனா, மொத்த கடன்ல திரும்பி வராம நிக்கிற கடனோட சதவீதம். இது குறைஞ்சா நல்லது.",
    "ஆனா ப்ராஃபிட், நெட் இன்ட்ரெஸ்ட் இன்கம் வளர்ந்த அளவுக்கு வளரல.",
    "வராக்கடன் சதவீதம் குறைஞ்சிருக்கு, அதாவது கடன் தரம் மேம்பட்டிருக்கு.",
]

# the fixed lines (never written by the model): the opening, the closing, and (from market) the notice and the subscribe sign-offs
OPEN_SAY = "வணக்கம் நண்பர்களே! இன்னைக்கு {ta} பத்தி பாக்கலாம். இதுல சொல்ற தகவல்கள் எல்லாம் ஆஃபீஷியல் சோர்ஸ்ல இருந்து எடுத்தது, ஸ்க்ரீன்ல சோர்ஸ் பேரும் இருக்கும்."
OPEN_EN = "Hello friends! Today we will look at {title}. Everything here comes from official sources, and the source is named on the screen."
CLOSE_SAY = ("இது ஒரு educational lesson மட்டும்தான். முதலீட்டு ஆலோசனை இல்ல. நான் SEBI registered advisor இல்ல. "
             "உங்களுக்கு எது சரின்னு முடிவு பண்ணுறதுக்கு முன்னாடி, ஆஃபீஷியல் சோர்ஸ்ல ஒரு தடவ செக் பண்ணிக்கோங்க. அடுத்த வீடியோல பாக்கலாம்!")
CLOSE_EN = ("This is only an educational lesson. It is not investment advice. I am not a SEBI-registered advisor. "
            "Before you decide what suits you, check the official source once yourself. See you in the next video!")

WORDS_BAD_TA = "இருக்கும், ஆகும், போகும், ஏறும், இறங்கும், வாய்ப்பு, எதிர்பார், நாளை, அடுத்த"
WORDS_BAD_EN = "will, would, may, might, could, should, likely, expect, outlook, support, tomorrow, watch, buy, sell, target, cheap, expensive"


def est_tokens(text: str) -> int:
    """About how many tokens a model counts: Latin text four characters to a token, Tamil and other scripts about one and a third."""
    latin = len(re.findall(r"[\x00-\x7f]", text))
    return latin // 4 + int((len(text) - latin) / 1.3)


def domain(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


# ---------- the topic bank ----------
def _src(label: str, url: str) -> dict:
    return {"label": label, "url": url}


def topic(id: str, title: str, ta: str, group: str, srcs: list[dict], words: list[str], icon: str = "paper") -> dict:
    """One topic: `ta` is the title as the voice says it (Tamil letters), `words` the search phrases that match a channel's video title to it (any one phrase, whole words in any order)."""
    return {"id": id, "title": title, "ta": ta, "group": group, "sources": srcs, "words": words, "icon": icon}


SRC = {          # every official page used, once: where it is and what the chip on the slide calls it
    "rbi-deposits": _src("RBI FAQs on banking: deposits", "https://www.rbi.org.in/commonman/english/scripts/FAQs.aspx?Id=325"),
    "rbi-deposit-rates": _src("RBI FAQs: interest rate on deposits", "https://www.rbi.org.in/commonman/Upload/English/FAQs/PDFs/FAQIRD01042025.pdf"),
    "rbi-dicgc": _src("RBI FAQ: deposit insurance (DICGC)", "https://www.rbi.org.in/commonperson/English/Scripts/FAQs.aspx?Id=272"),
    "rbi-kyc": _src("RBI FAQs on KYC", "https://www.rbi.org.in/commonman/english/Scripts/FAQs.aspx?Id=3782"),
    "rbi-sgb-page": _src("RBI: Sovereign Gold Bonds", "https://www.rbi.org.in/Scripts/BS_SwarnaBharat.aspx"),
    "rbi-sgb-faq": _src("RBI FAQ: Sovereign Gold Bond", "https://www.rbi.org.in/commonman/english/scripts/FAQs.aspx?Id=1658"),
    "rbi-lrs": _src("RBI FAQ: Liberalised Remittance Scheme", "https://www.rbi.org.in/commonperson/english/scripts/FAQs.aspx?Id=1834"),
    "rbi-retail-direct": _src("RBI FAQ: Retail Direct scheme", "https://www.rbi.org.in/commonman/english/scripts/FAQs.aspx?Id=3337"),
    "rbi-gsec": _src("RBI FAQ: government securities market", "https://www.rbi.org.in/commonman/english/scripts/FAQs.aspx?Id=711"),
    "rbi-credit-report": _src("RBI: free annual credit report", "https://www.rbi.org.in/commonman/english/scripts/Notification.aspx?Id=1884"),
    "rbi-fame": _src("RBI Financial Awareness Messages", "https://www.rbi.org.in/commonman/images/FAME202426022024.pdf"),
    "sebi-mf-faq": _src("SEBI FAQs for mutual fund investors", "https://www.sebi.gov.in/sebi_data/faqfiles/sep-2024/1727242783639.pdf"),
    "sebi-direct": _src("SEBI Investor: regular and direct plans", "https://investor.sebi.gov.in/regular_and_direct_mutual_funds.html"),
    "sebi-elss": _src("SEBI Investor: a guide to ELSS", "https://investor.sebi.gov.in/elss.html"),
    "sebi-derivatives": _src("SEBI Investor: understanding derivatives", "https://investor.sebi.gov.in/understanding_derivatives.html"),
    "sebi-fo-study": _src("SEBI study: individual traders in equity derivatives", "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787233506209.pdf"),
    "sebi-primary": _src("SEBI: beginner's guide to the primary market", "https://investor.sebi.gov.in/pdf/reference-material/primarymarkets.pdf"),
    "sebi-ipo": _src("SEBI Investor: how to invest in an IPO", "https://investor.sebi.gov.in/pdf/reference-material/ppt/PPT-3%20How%20to%20invest%20in%20Intial%20Public%20Offer%20Updated%2030%20Sep%202022.pdf"),
    "sebi-bonds": _src("SEBI: investor guide for corporate bonds", "https://investor.sebi.gov.in/pdf/reference-material/corporatebonds.pdf"),
    "sebi-assets": _src("SEBI Investor: investment asset classes", "https://investor.sebi.gov.in/investment-assetclasses.html"),
    "sebi-fe": _src("SEBI Financial Education Booklet", "https://investor.sebi.gov.in/pdf/downloadable-documents/Financial%20Education%20Booklet%20-%20English.pdf"),
    "sebi-beginners": _src("SEBI: beginner's guide to the capital markets", "https://investor.sebi.gov.in/pdf/reference-material/beginners.pdf"),
    "sebi-howto": _src("SEBI Investor: how to invest", "https://investor.sebi.gov.in/securities-howtoinvest.html"),
    "sebi-gold": _src("SEBI FAQs: gold exchange in India", "https://www.sebi.gov.in/sebi_data/faqfiles/nov-2022/1667996603757.pdf"),
    "ncfe": _src("NCFE financial education handbook", "https://ncfe.org.in/wp-content/uploads/2023/11/FE_Handbook_Eng.pdf"),
    "amfi-booklet": _src("AMFI: mutual funds made simple", "https://www.amfiindia.com/uploads/AMFI_Understanding_Mutual_Funds_IAP_Booklet_Final_Website_version_860a5b77aa.pdf"),
    "amfi-myths": _src("AMFI: myths and facts about mutual funds", "https://www.amfiindia.com/investor/knowledge-center-info?zoneName=MythsAndFactsAboutMutualFunds"),
    "amfi-categories": _src("AMFI: categorisation of mutual fund schemes", "https://www.amfiindia.com/investor/knowledge-center-info?zoneName=CategorizationOfMutualFundSchemes"),
    "amfi-nav": _src("AMFI: cut-off timings and applicable NAV", "https://www.amfiindia.com/investor/knowledge-center-info?zoneName=CutOffTimingsAndNewRuleOnApplicableNAV"),
    "it-regimes": _src("Income Tax Department: FAQs on new vs old regime", "https://www.incometax.gov.in/iec/foportal/help/new-tax-vs-old-tax-regime-faqs"),
    "it-regimes-pdf": _src("Income Tax Department: new vs old regime FAQs (PDF)", "https://www.incometax.gov.in/iec/foportal/sites/default/files/2024-07/New%20vs.%20Old%20Regime%20FAQs%20approved%20final.pdf"),
    "it-itr2": _src("Income Tax Department: ITR-2 FAQs", "https://www.incometax.gov.in/iec/foportal/help/e-filing-itr2-form-faq"),
    "it-salaried": _src("Income Tax Department: which ITR for salaried individuals", "https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-1"),
    "nps-faq": _src("PFRDA: NPS All Citizen Model FAQs", "https://pfrda.org.in/w/faqs/nps-all-citizen-model"),
    "nps-faq-pdf": _src("PFRDA: NPS All Citizen Model FAQs (PDF)", "https://www.pfrda.org.in/documents/33652/109556/NPS-All+citizen+Model.pdf"),
    "nps-exit": _src("NPS Trust: exit from NPS, All Citizen Model", "https://npstrust.org.in/sites/default/files/inline-images/22-Exit-FAQs-All-Citizen-Model.pdf"),
    "irdai-ulip": _src("IRDAI Policyholder: unit linked insurance policies", "https://policyholder.gov.in/unit-linked-insurance-policies"),
    "irdai-ulip-products": _src("IRDAI Policyholder: unit linked products", "https://policyholder.gov.in/unit-linked-products"),
    "irdai-what-to-buy": _src("IRDAI Policyholder: what life insurance to buy", "https://policyholder.gov.in/what-life-insurance-to-buy"),
    "irdai-handbook": _src("IRDAI: life insurance handbook", "https://irdai.gov.in/documents/37343/369581/Life+Insurance+Handbook+(English).pdf/2a13350c-0fb2-fc1d-bfaf-6ced7a31eeee?version=1.0&t=1631528774917"),
    "irdai-ulip-faq": _src("IRDAI: FAQs on unit linked products", "https://irdai.gov.in/documents/37343/365630/FAQs+on+Unit+Linked+Products.pdf/2eac3fc4-4f04-f974-eadb-a826b18a4e65?version=1.0&t=1631529718234&download=true"),
    "irdai-rights": _src("IRDAI Policyholder: know your rights and duties", "https://policyholder.gov.in/know-your-rights-and-duties"),
    "pib-epf-2025": _src("PIB (Ministry of Labour): EPF withdrawal rules, October 2025", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2179689&reg=48&lang=2"),
    "pib-epf-scheme": _src("PIB (Ministry of Labour): the Employees' Provident Fund Scheme", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=1942083"),
    "pib-epfo-claims": _src("PIB (Ministry of Labour): EPFO claim settlement", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2118168&reg=3&lang=2"),
    "ifsca-funds": _src("IFSCA: FAQs on fund management regulations", "https://ifsca.gov.in/Document/Legal/faqs-on-ifsca-fund-management-regulations-202209122022040455.pdf"),
    "ppf": _src("India Post: Public Provident Fund Scheme, 2019", "https://www.indiapost.gov.in/documents/offerings/schemesandservices/posb/PublicProvidentFundScheme2019English.pdf"),
    "ssa": _src("India Post: Sukanya Samriddhi Account Scheme, 2019", "https://www.indiapost.gov.in/documents/offerings/schemesandservices/posb/SukanyaSamriddhiAccountScheme2019English.pdf"),
    "ifsca-resident": _src("IFSCA: resident individuals and foreign securities through IFSC banking units", "https://ifsca.gov.in/Document/Legal/resident-individuals-permitted-to-invest-in-foreign-securities-through-banking-units-in-ifsc23022021095615.pdf"),
}
TOPICS = [
    # deposits
    topic("fd-basics", "How a bank fixed deposit works", "பேங்க் எஃப்டி எப்படி வேலை செய்யுது", "deposits", [SRC["rbi-fame"], SRC["sebi-fe"], SRC["rbi-deposits"], SRC["rbi-dicgc"]],
          ["fixed deposit", "fd interest", "fd rates", "bank fd"], "bank"),
    topic("fd-vs-rd", "Fixed deposit vs recurring deposit", "எஃப்டி வெர்சஸ் ஆர்டி", "deposits", [SRC["sebi-fe"], SRC["ncfe"], SRC["rbi-fame"], SRC["rbi-deposit-rates"]],
          ["fd vs rd", "rd vs fd", "fd or rd", "recurring deposit", "fixed deposit vs recurring deposit"], "calendar"),
    topic("fd-premature", "Breaking a fixed deposit early", "எஃப்டிய சீக்கிரம் எடுத்தா என்ன ஆகும்", "deposits", [SRC["rbi-deposit-rates"], SRC["rbi-deposits"]],
          ["premature withdrawal", "break fd", "close fd early", "fd penalty"], "piggy"),
    topic("deposit-insurance", "Is your bank deposit insured? DICGC", "பேங்க் டெபாசிட் இன்ஷூரன்ஸ் டிஐசிஜிசி", "deposits", [SRC["rbi-dicgc"]],
          ["dicgc", "deposit insurance", "bank deposit safe", "5 lakh insurance", "bank fail"], "umbrella"),
    topic("senior-citizen-fd", "Fixed deposits for senior citizens", "சீனியர் சிட்டிசன் எஃப்டி", "deposits", [SRC["rbi-deposit-rates"], SRC["rbi-deposits"]],
          ["senior citizen fd", "senior citizen fixed deposit", "senior citizen"], "bank"),
    topic("kyc-basics", "KYC: why banks ask and what it needs", "கேஒய்சி ஏன் கேக்குறாங்க", "deposits", [SRC["rbi-kyc"]], ["kyc", "what is kyc", "video kyc"], "paper"),
    # mutual funds
    topic("mf-basics", "What is a mutual fund?", "மியூச்சுவல் ஃபண்ட்னா என்ன", "mutual funds", [SRC["amfi-booklet"], SRC["sebi-mf-faq"]],
          ["mutual fund", "mutual funds for beginners", "mutual fund basics", "what is mutual fund"], "chart"),
    topic("mf-types", "Types of mutual funds", "மியூச்சுவல் ஃபண்ட் வகைகள்", "mutual funds", [SRC["amfi-categories"], SRC["amfi-booklet"], SRC["sebi-mf-faq"]],
          ["types of mutual funds", "mutual fund categories", "equity debt hybrid", "mutual fund types"], "chart"),
    topic("sip-vs-lumpsum", "SIP vs lump sum", "எஸ்ஐபி வெர்சஸ் லம்ப்சம்", "mutual funds", [SRC["amfi-booklet"], SRC["amfi-myths"], SRC["sebi-mf-faq"]],
          ["sip vs lumpsum", "sip or lump sum", "lumpsum", "sip", "systematic investment plan"], "calendar"),
    topic("expense-ratio", "Expense ratio: what a mutual fund costs", "எக்ஸ்பென்ஸ் ரேஷியோ", "mutual funds", [SRC["sebi-mf-faq"], SRC["sebi-direct"]],
          ["expense ratio", "ter", "mutual fund charges"], "rupee"),
    topic("direct-vs-regular", "Direct plan vs regular plan", "டைரக்ட் ப்ளான் வெர்சஸ் ரெகுலர் ப்ளான்", "mutual funds", [SRC["sebi-direct"], SRC["sebi-mf-faq"]],
          ["direct vs regular", "direct plan", "regular plan", "direct mutual fund"], "paper"),
    topic("nav-explained", "NAV: what it is and what it is not", "என்ஏவி னா என்ன", "mutual funds", [SRC["amfi-booklet"], SRC["amfi-myths"], SRC["amfi-nav"]],
          ["nav", "net asset value", "low nav", "nav myth"], "lens"),
    topic("index-funds", "Index funds", "இன்டெக்ஸ் ஃபண்ட்ஸ்", "mutual funds", [SRC["amfi-categories"], SRC["amfi-booklet"]],
          ["index fund", "index funds", "passive funds", "passive investing"], "chart"),
    topic("elss", "ELSS: tax-saving mutual funds", "இஎல்எஸ்எஸ் டாக்ஸ் சேவிங் ஃபண்ட்", "mutual funds", [SRC["sebi-elss"], SRC["amfi-categories"]],
          ["elss", "tax saving mutual fund", "tax saver", "80c mutual fund"], "paper"),
    # bonds
    topic("g-secs", "Government securities and T-bills", "கவர்ன்மென்ட் செக்யூரிட்டீஸ்", "bonds", [SRC["rbi-gsec"], SRC["rbi-retail-direct"]],
          ["government securities", "g sec", "gilt", "t bills", "treasury bills", "government bonds"], "bank"),
    topic("rbi-retail-direct", "RBI Retail Direct: government bonds for everyone", "ஆர்பிஐ ரீடெய்ல் டைரக்ட்", "bonds", [SRC["rbi-retail-direct"]],
          ["rbi retail direct", "retail direct", "buy government bonds"], "bank"),
    topic("corporate-bonds", "Corporate bonds and debentures", "கார்ப்பரேட் பாண்ட்ஸ்", "bonds", [SRC["sebi-bonds"], SRC["sebi-assets"]],
          ["corporate bonds", "bonds", "bond investing", "debentures", "bond"], "paper"),
    topic("bond-risks", "Bond risks: interest rate and credit risk", "பாண்ட் ரிஸ்க்", "bonds", [SRC["sebi-bonds"], SRC["sebi-assets"]],
          ["bond risk", "credit risk", "interest rate risk", "bond rating"], "shield"),
    # gold
    topic("sgb", "Sovereign Gold Bonds", "சவரின் கோல்ட் பாண்ட்ஸ்", "gold", [SRC["rbi-sgb-page"], SRC["rbi-sgb-faq"]],
          ["sovereign gold bond", "sgb", "gold bond"], "goldbar"),
    topic("gold-etf-egr", "Gold ETFs and Electronic Gold Receipts", "கோல்ட் இடிஎஃப் அண்ட் இஜிஆர்", "gold", [SRC["sebi-gold"], SRC["sebi-assets"]],
          ["gold etf", "electronic gold receipt", "digital gold", "egr", "gold etfs"], "goldbar"),
    topic("gold-ways", "Ways to invest in gold", "கோல்ட்ல இன்வெஸ்ட் பண்ற வழிகள்", "gold", [SRC["sebi-assets"], SRC["sebi-gold"], SRC["rbi-sgb-page"]],
          ["invest in gold", "gold investment", "gold vs", "buy gold", "gold"], "goldbar"),
    # small savings and retirement
    topic("ppf", "Public Provident Fund (PPF)", "பிபிஎஃப்", "savings", [SRC["ppf"]], ["ppf", "public provident fund"], "piggy"),
    topic("ssa", "Sukanya Samriddhi Account", "சுகன்யா சம்ருத்தி", "savings", [SRC["ssa"]], ["sukanya", "sukanya samriddhi", "ssy"], "piggy"),
    topic("nps", "National Pension System (NPS)", "நேஷனல் பென்ஷன் சிஸ்டம்", "retirement", [SRC["nps-faq"], SRC["nps-faq-pdf"], SRC["nps-exit"]],
          ["nps", "national pension system", "nps tier 1", "nps tier 2", "pension"], "umbrella"),
    topic("nps-exit", "NPS: withdrawals and exit", "என்பிஎஸ் எக்ஸிட் ரூல்ஸ்", "retirement", [SRC["nps-exit"], SRC["nps-faq-pdf"]],
          ["nps withdrawal", "nps exit", "nps annuity", "nps partial withdrawal"], "umbrella"),
    # insurance
    topic("term-vs-ulip", "Term insurance vs ULIP", "டெர்ம் இன்ஷூரன்ஸ் வெர்சஸ் யூலிப்", "insurance", [SRC["irdai-ulip"], SRC["irdai-handbook"], SRC["irdai-ulip-faq"], SRC["irdai-what-to-buy"]],
          ["term insurance", "term vs ulip", "ulip", "term plan", "life insurance"], "umbrella"),
    topic("ulip-charges", "ULIP charges and lock-in", "யூலிப் சார்ஜஸ்", "insurance", [SRC["irdai-ulip"], SRC["irdai-ulip-faq"], SRC["irdai-ulip-products"]],
          ["ulip charges", "ulip lock in", "ulip", "unit linked"], "umbrella"),
    topic("insurance-rights", "Your rights as a policyholder: free look and claims", "பாலிசி ஹோல்டர் ரைட்ஸ்", "insurance", [SRC["irdai-rights"], SRC["irdai-handbook"]],
          ["free look", "insurance claim", "policyholder", "insurance rights", "claim settlement"], "umbrella"),
    # provident fund
    topic("epf", "EPF: how the provident fund works", "இபிஎஃப் எப்படி வேலை செய்யுது", "retirement", [SRC["pib-epf-scheme"], SRC["pib-epf-2025"]],
          ["epf", "provident fund", "pf", "uan", "epfo"], "piggy"),
    topic("epf-withdrawal", "EPF withdrawal rules", "இபிஎஃப் வித்ட்ராயல் ரூல்ஸ்", "retirement", [SRC["pib-epf-2025"], SRC["pib-epfo-claims"]],
          ["epf withdrawal", "pf withdrawal", "withdraw pf", "pf claim"], "piggy"),
    # tax
    topic("tax-regimes", "Old vs new income tax regime", "ஓல்ட் வெர்சஸ் நியூ டாக்ஸ் ரெஜிம்", "tax", [SRC["it-regimes"], SRC["it-regimes-pdf"]],
          ["old vs new tax regime", "new tax regime", "old tax regime", "income tax slab", "tax regime"], "paper"),
    topic("section-80c", "Section 80C: what counts", "செக்ஷன் எய்ட்டி சி", "tax", [SRC["it-regimes"], SRC["it-regimes-pdf"], SRC["sebi-elss"]],
          ["80c", "section 80c", "tax saving", "save tax", "tax saving investments"], "rupee"),
    topic("itr-basics", "Filing an income tax return: which ITR?", "ஐடிஆர் ஃபைலிங்", "tax", [SRC["it-salaried"], SRC["it-itr2"]],
          ["itr", "income tax return", "itr filing", "file itr"], "paper"),
    topic("capital-gains", "Capital gains tax on shares and funds", "கேபிடல் கெயின்ஸ் டாக்ஸ்", "tax", [SRC["it-itr2"], SRC["it-salaried"]],
          ["capital gains", "ltcg", "stcg", "capital gains tax"], "rupee"),
    # money habits
    topic("credit-score", "Credit score and your free credit report", "கிரெடிட் ஸ்கோர்", "money habits", [SRC["rbi-credit-report"], SRC["rbi-fame"]],
          ["credit score", "cibil score", "cibil", "credit report"], "chart"),
    topic("emergency-fund", "The emergency fund", "எமர்ஜென்சி ஃபண்ட்", "money habits", [SRC["rbi-fame"], SRC["sebi-fe"], SRC["ncfe"]],
          ["emergency fund", "rainy day fund", "emergency savings"], "piggy"),
    topic("budgeting", "Budgeting: income, spending and saving", "பட்ஜெட் போடுறது எப்படி", "money habits", [SRC["rbi-fame"], SRC["ncfe"], SRC["sebi-fe"]],
          ["budget", "budgeting", "50 30 20", "save money", "monthly budget"], "rupee"),
    topic("compounding", "The power of compounding", "காம்பவுண்டிங்", "money habits", [SRC["rbi-fame"], SRC["ncfe"]],
          ["compounding", "power of compounding", "compound interest", "compound"], "chart"),
    topic("rule-of-72", "The rule of 72", "ரூல் ஆஃப் செவன்டி டூ", "money habits", [SRC["ncfe"], SRC["rbi-fame"]], ["rule of 72", "double your money"], "calendar"),
    topic("inflation", "Inflation and your savings", "இன்ஃப்ளேஷன்", "money habits", [SRC["rbi-fame"], SRC["sebi-fe"], SRC["ncfe"]],
          ["inflation", "inflation explained", "real return"], "rupee"),
    topic("saving-vs-investing", "Saving vs investing", "சேவிங் வெர்சஸ் இன்வெஸ்டிங்", "money habits", [SRC["rbi-fame"], SRC["sebi-fe"]],
          ["saving vs investing", "save or invest", "savings and investment"], "piggy"),
    topic("asset-allocation", "Asset classes and diversification", "அசெட் அலோகேஷன்", "money habits", [SRC["sebi-assets"], SRC["sebi-fe"]],
          ["asset allocation", "asset classes", "diversification", "diversify"], "chart"),
    # markets
    topic("fo-risk", "Futures and options: what SEBI's study found", "எஃப் அண்ட் ஓ ரிஸ்க்", "markets", [SRC["sebi-fo-study"], SRC["sebi-derivatives"]],
          ["f&o", "fno", "options trading", "futures and options", "derivatives", "option buying"], "shield"),
    topic("ipo-basics", "IPO basics: how a public issue works", "ஐபிஓ பேசிக்ஸ்", "markets", [SRC["sebi-primary"], SRC["sebi-ipo"], SRC["sebi-fe"]],
          ["ipo", "how to apply ipo", "ipo for beginners", "ipo allotment"], "company"),
    topic("demat-basics", "Demat and trading accounts", "டிமேட் அக்கவுன்ட்", "markets", [SRC["sebi-howto"], SRC["sebi-beginners"], SRC["sebi-fe"]],
          ["demat account", "trading account", "how to start investing", "open demat"], "paper"),
    topic("market-basics", "How the stock market works", "ஸ்டாக் மார்க்கெட் பேசிக்ஸ்", "markets", [SRC["sebi-beginners"], SRC["sebi-fe"]],
          ["stock market for beginners", "share market basics", "stock market basics", "how stock market works"], "chart"),
    topic("reading-pl", "How to read a company's profit and loss", "ப்ராஃபிட் அண்ட் லாஸ் படிக்கிறது எப்படி", "markets", [SRC["sebi-fe"], SRC["ncfe"]],
          ["profit and loss", "read balance sheet", "financial statements", "balance sheet", "how to read"], "paper"),
    # abroad
    topic("lrs", "Investing abroad from India: the LRS limit", "எல்ஆர்எஸ் வெளிநாட்டு இன்வெஸ்ட்மென்ட்", "abroad", [SRC["rbi-lrs"], SRC["ifsca-resident"]],
          ["lrs", "invest in us stocks", "us stocks from india", "international investing", "foreign stocks"], "company"),
    topic("gift-city", "GIFT City (IFSC): what it means for residents", "கிஃப்ட் சிட்டி", "abroad", [SRC["ifsca-resident"], SRC["ifsca-funds"], SRC["rbi-lrs"]],
          ["gift city", "ifsc", "gift ifsc"], "company"),
]


# ---------- choosing ----------
def made_at(store, key: str) -> float | None:
    got = store.kv_get(DONE, key)
    return None if not got or got.get("skipped") else got.get("at") or 1


def blocked(store, tid: str, now: float, short: bool = False) -> bool:
    """Is the topic off limits tonight: made within REPEAT_DAYS (a Short: the concept limit), or skipped within SKIP_DAYS."""
    sk = store.kv_get(DONE, f"lessonskip:{tid}")
    if sk and now - sk["at"] < SKIP_DAYS * 86400:
        return True
    if short:
        got = store.kv_get(DONE, f"lessonshort:{tid}")
        return bool(got) and (len(got.get("concepts") or []) >= SHORT_PER_TOPIC or now - got["at"] < SHORT_REPEAT_DAYS * 86400)
    at = made_at(store, f"lesson:{tid}")
    return bool(at) and now - at < REPEAT_DAYS * 86400


def skip(store, tid: str, why: str) -> None:
    store.kv_put(DONE, f"lessonskip:{tid}", {"skipped": why, "at": time.time()})


def rank(store, topics: list[dict], videos: list[dict] | None = None, now: float | None = None, short: bool = False) -> list[tuple[dict, float, list[dict]]]:
    """[(topic, score, matching videos)] in the order to make them. Topics with a signal come first (most recent views a day first); the rest follow, never made
    first, then the one made longest ago; TOPICS' own order breaks a tie. Blocked topics are left out."""
    now = now or time.time()
    out = []
    for n, t in enumerate(topics):
        if blocked(store, t["id"], now, short):
            continue
        s, hit = yt_channels.score(t, videos or [], now)
        last = (store.kv_get(DONE, f"lessonshort:{t['id']}") or {}).get("at") if short else made_at(store, f"lesson:{t['id']}")
        out.append((t, s, hit, (last or 0), n))
    out.sort(key=lambda x: (-x[1], x[3], x[4]))
    return [(t, s, hit) for t, s, hit, _, _ in out]


# ---------- the official pages ----------
def join_wrapped(text: str) -> str:
    """A PDF's text breaks a line wherever the page did: lines are joined into paragraphs (a line ending a sentence ends the paragraph)."""
    out: list[str] = []
    for ln in (x.strip() for x in text.splitlines()):
        if not ln:
            continue
        if out and not re.search(r"[.!?:]$", out[-1]) and len(out[-1]) < 700:
            out[-1] += " " + ln
        else:
            out.append(ln)
    return "\n".join(out)


async def fetch_page(c: httpx.AsyncClient, src: dict) -> dict | None:
    """{label, url, text} for one official page, or None (dead, blocked, a scan, or hardly any text). A cut-off download is tried once more."""
    for attempt in range(2):
        try:
            r = await c.get(src["url"], headers=UA, timeout=60.0)
            break
        except httpx.HTTPError as e:
            log.info("lessons: %s: %s", src["url"], e)
            r = None
    if r is None or r.status_code != 200:
        return None
    pdf = "pdf" in r.headers.get("content-type", "") or src["url"].lower().split("?")[0].endswith(".pdf")
    if pdf:
        text = join_wrapped(filings_text.pdf_text(r.content, 60)) if len(r.content) < PDF_MAX else ""
    else:
        text = filings_text.html_text(r.text)
    return {**src, "text": text} if len(text) >= PAGE_MIN else None


def keywords(*texts: str) -> set[str]:
    return {w for t in texts for w in yt_channels.words(t) if len(w) >= 4 and w not in market.STOP}


def hits(text: str, kws: set[str]) -> int:
    return len(set(yt_channels.words(text)) & kws)


def mentions(text: str, kws: set[str]) -> int:
    """How many times the page uses the topic's words."""
    return sum(w in kws for w in yt_channels.words(text))


async def fetch_sources(c: httpx.AsyncClient, tp: dict, gap: float = GAP, sleep=asyncio.sleep) -> list[dict]:
    """The topic's official pages that downloaded and really speak of it (its words come up at least 3 times), in the bank's order, a few seconds apart."""
    kws = keywords(tp["title"], *tp["words"])
    out = []
    for n, src in enumerate(tp["sources"]):
        if n:
            await sleep(gap)
        page = await fetch_page(c, src)
        if page and mentions(page["text"], kws) >= 3:
            out.append(page)
    return out


def units(text: str, size: int = 600) -> list[str]:
    """A page's paragraphs, a long one cut at sentence ends."""
    out = []
    for para in text.splitlines():
        if len(para) <= size:
            out.append(para)
        else:
            out += [s for s in re.split(r"(?<=[.!?])\s+", para) if s]
    return out


def passages(pages: list[dict], kws: set[str], limit: int = PASSAGES) -> str:
    """The sentences of the pages that speak most of the topic (words in kws), each page getting an equal share, in page order, each prefixed with its page's tag
    [S1], [S2]... A question is kept with the answer after it."""
    out, share = [], limit // max(len(pages), 1)
    for n, p in enumerate(pages, 1):
        us = units(p["text"])
        score = [hits(u, kws) + 0.5 * (hits(us[i - 1], kws) if i and us[i - 1].endswith("?") else 0) for i, u in enumerate(us)]
        pick, size = set(), 0
        for i in sorted(range(len(us)), key=lambda i: -score[i]):
            if score[i] <= 0 or size + len(us[i]) > share:
                continue
            pick.add(i)
            size += len(us[i]) + 1
            if i and us[i - 1].endswith("?") and size + len(us[i - 1]) <= share:
                pick.add(i - 1)
                size += len(us[i - 1]) + 1
        out.append(f"[S{n}] {p['label']} ({domain(p['url'])})\n" + "\n".join(us[i] for i in sorted(pick)))
    return "\n\n".join(out)


# ---------- transcripts: raw material only ----------
def trim(name: str) -> str:
    """A company's name without its legal tail ("Tata Consultancy Services Limited" -> "Tata Consultancy Services")."""
    while (short := SUFFIX.sub("", name).strip()) != name.strip():
        name = short
    return name.strip()


def index_pattern(names: list[str], symbols: list[str]) -> re.Pattern:
    """One pattern for any company in the channel's index (its short name; its symbol in capitals) or a well-known bank or broker."""
    longs = {trim(n) for n in names if len(trim(n)) >= 4 and trim(n).lower() not in GENERIC}
    parts = [r"(?i:\b(?:" + "|".join(re.escape(x) for x in sorted(longs | set(BRANDS), key=len, reverse=True)) + r")\b)"] if longs | set(BRANDS) else []
    syms = [s for s in symbols if len(s) >= 3]
    if syms:
        parts.append(r"\b(?:" + "|".join(re.escape(s) for s in sorted(syms, key=len, reverse=True)) + r")\b")
    return re.compile("|".join(parts)) if parts else re.compile(r"(?!x)x")


class Bad:
    """Something that .search()es true for a company name or symbol, a market-direction word, or ADVICE / FORECAST wording."""

    def __init__(self, names: list[str], symbols: list[str]) -> None:
        self.idx = index_pattern(names, symbols)

    def search(self, text: str):
        return self.idx.search(text) or MARKET_DIR.search(text) or market.ADVICE.search(text) or market.FORECAST.search(text)


def bad_pattern(names: list[str], symbols: list[str]) -> Bad:
    return Bad(names, symbols)


def sentences(text: str) -> list[str]:
    """Sentences of a transcript, which is often one unpunctuated run: a piece of more than 40 words is cut every 20."""
    out = []
    for piece in re.split(r"(?<=[.!?\u0964])\s+|\n+", text):
        w = piece.split()
        out += [" ".join(w[i:i + 20]) for i in range(0, len(w), 20)] if len(w) > 40 else [piece] if piece.strip() else []
    return out


def scrub(text: str, bad) -> str:
    """The transcript without any sentence that names a company or stock, speaks of price, target, buying, selling or the market's direction, or forecasts (`bad` from bad_pattern)."""
    return " ".join(s for s in sentences(text) if not bad.search(s))


def shingles(text: str, n: int = SHINGLE) -> set[tuple]:
    w = yt_channels.words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def transcript_text(transcripts: list[dict], bad, budget: int = TRANSCRIPT_TOKENS) -> str:
    """What Groq may see: each transcript scrubbed, most viewed first, up to `budget` tokens in all (each video gets an equal share)."""
    out, share = [], budget // max(len(transcripts), 1)
    for t in transcripts:
        clean, cut = scrub(t["text"], bad), []
        for s in sentences(clean):
            if est_tokens(" ".join(cut + [s])) > share:
                break
            cut.append(s)
        if cut:
            out.append(" ".join(cut))
    return "\n\n".join(out)


ANGLE = """Below are sentences from public videos by Indian personal-finance channels on the subject "{title}". Do NOT copy any wording. Tell me what viewers
want to understand and what they commonly get wrong. Answer as
{{"angle": "one sentence: the clearest way to frame this lesson for a beginner", "questions": ["3 to 5 questions viewers ask"], "misconceptions": ["up to 4 common misunderstandings"]}}
No numbers or amounts, no names of companies, products, people or channels, no advice.

{text}"""


async def angle(llm, tp: dict, text: str, model: str | None = None) -> dict:
    """{"angle", "questions", "misconceptions"} from the scrubbed transcripts, without any number, name or advice. Nothing (or a failed request) gives {}: the lesson is then planned from the pages alone."""
    if not llm or not text.strip():
        return {}
    try:
        got = await llm.json(ANGLE.format(title=tp["title"], text=text), tier="writer", max_tokens=1500, **({"model": model} if model else {}))
    except Exception as e:  # noqa: BLE001 - no model, no angle
        log.warning("lessons: no angle (%s)", e)
        return {}
    if not isinstance(got, dict):
        return {}
    ok = lambda s: isinstance(s, str) and 8 <= len(s) <= 200 and not re.search(r"\d", s) and not market.ADVICE.search(s)      # noqa: E731
    out = {"angle": got["angle"].strip() if ok(got.get("angle")) else ""}
    for k in ("questions", "misconceptions"):
        out[k] = [s.strip() for s in got.get(k) or [] if ok(s)][:5] if isinstance(got.get(k), list) else []
    return out if out["angle"] or out["questions"] or out["misconceptions"] else {}


def hints(a: dict) -> str:
    if not a:
        return ""
    return ("What viewers of other channels want to know (use it only to decide what to explain, never as a source of facts):\n"
            + (f"- framing: {a['angle']}\n" if a.get("angle") else "") + "".join(f"- question: {q}\n" for q in a.get("questions", []))
            + "".join(f"- common misunderstanding: {m}\n" for m in a.get("misconceptions", [])))


# ---------- the plan ----------
PLAN = """You plan a short lesson for a Tamil YouTube channel that teaches personal finance to beginners in India. Subject: {title}.
Official passages (the ONLY source of facts; each is tagged [S1], [S2]...):
{passages}

{hints}Plan {count}. Answer as
{{"title": "...", "slides": [{{"kind": "points", "heading": "...", "icon": "...", "items": ["...", "..."]}}]}}
- title: a Tanglish hook in this channel's style, English finance terms with a few Tamil words, under 80 characters, a question or a plain statement about the subject, for example
  "FD vs RD தமிழில் | என்ன வித்தியாசம்?" or "SIP னா என்ன? எளிமையா புரிஞ்சிக்கலாம்". Never a promise of returns, speed or income, and no "best" or "must".
- {shape}
- heading: at most 4 words. Each item: a short phrase of at most 6 words stating a fact the passages give. Digits only if the passages have them.
- icon: one of {icons}.
- {facts}
- Order: what it is, how it works, what to check (costs, limits, risks). Describe; never recommend.
- No company, fund or product names, nothing about where any market or price is going, no advice words (buy, sell, should)."""
PLAN_LONG = ("slides: 4 or 5 slides, each with 2 to 4 items.", "4 or 5 slides, each with 2 to 4 items",
             "If the passages give figures (rates, limits, years, amounts), make one slide {\"kind\": \"facts\", \"heading\": \"...\", \"rows\": [{\"label\": \"...\", \"value\": \"...\", \"note\": \"...\"}]} "
             "with up to 4 rows; every value is copied from the passages.")
PLAN_SHORT = ("slides: 1 or 2 slides, each with 2 or 3 items, about ONE concept of the subject.", "1 or 2 slides for ONE concept of the subject, each with 2 or 3 items; also \"concept\": \"3 to 6 words naming it\"",
              "Do not use a facts slide. The concept must not be one of: {covered}.")
LINES = """You write the spoken lines for ONE slide of a finance lesson on a Tamil YouTube channel. The host talks like a friend explaining, in colloquial Chennai Tamil
mixed with English finance words (Tanglish). Subject: {title}.
Official passages (the ONLY source of facts; each tagged [S1]...):
{passages}

The slide: "{heading}". Its items, shown one by one: {items}
Write {count} spoken lines for this slide, each a different point. Answer as
{{"lines": [{{"show": 1, "say": "...", "en": "...", "quotes": ["..."]}}]}}
- show: how many of the slide's items are on screen while the line is said (1 to {n}, never going down).
- say: one or two full sentences (at least 8 words), as a friend would say them, written ENTIRELY in Tamil letters: English words are written in Tamil letters the way a Tamil speaker says them (பேங்க், டெபாசிட், இன்ட்ரெஸ்ட், ரேட்),
  abbreviations letter by letter (FD = எஃப்டி, RD = ஆர்டி, RBI = ஆர்பிஐ, SEBI = செபி), numbers in digits, no ₹ or % sign (say ரூபாய் and பர்சன்ட்). Not one Latin letter may remain in say.
  Talk the way the examples below do: casual Chennai speech, short sentences, a term defined as "X னா, ..." and a point made plainly. Never bookish Tamil (என்பது, செய்யப்படுகிறது, கிறது, ப்படும்).
  Do not translate English finance words into formal Tamil (say டெபாசிட், இன்ட்ரெஸ்ட், பேங்க்); do not invent words. Never use these Tamil words: {bad_ta}.
- en: the same line in plain English for captions, one full sentence of at least 8 words, without these words: {bad_en}.
- Work from one quote at a time: your English sentence is that quote's own sentence made plain, keeping its key words, naming the thing it is about (FD, RD, NPS) and saying only what
  the quote says about it. Never join facts from different quotes into one claim, never compare two products in one line, never add a fact (no "no withdrawals", no "higher than").
- quotes: 1 or 2 sentences copied EXACTLY, character for character, from the passages above (each at least 30 characters), that support everything the line says.
- Every number in say and en must be in a quote, written as the quote writes it (5,00,000 or 5 lakh, 75 percent). Add no fact, number or name the quotes lack. No advice, no opinion, no prediction, no company or product names.
Examples of the host's manner (do not reuse their content):
{style}"""


REPAIR = """

Earlier you wrote lines for this slide and the checks threw some out, for the reasons below. Write NEW lines to replace them (same JSON, same rules, a different wording that fixes the
problem; if you cannot support a point with an exact quote, make a different point from the passages):
{rejected}"""


def explain(item: object, why: str) -> str:
    """What to tell the writer about a line the checks threw out: the words that did it."""
    say, en = (" ".join(str(item.get(k, "")).split()) if isinstance(item, dict) else "" for k in ("say", "en"))
    if why == "the caption says more than its quotes do":
        return "the English caption has words (or an acronym such as FD or RD) that its quote does not hold; say only what the quote says, in its own words, about the thing it names"
    if why == "book Tamil, not the way the host speaks":
        m = BOOKISH.search(say)
        return f"\"{m.group(0)}\" is book Tamil; say it the way a friend does: X னா, உங்க, பண்ணுது, இருக்கு, ஆகுது"
    if why in ("a garbled line (a word repeated)", "a line of the wrong length"):
        return "write a full, natural sentence or two of at least 8 words, never a list of fragments or a repeated word"
    if why in ("spoken line is not all Tamil script", "the voice would garble an English word"):
        words = re.findall(r"[A-Za-z][A-Za-z.\-]*", say) or clone.unspelt(say) or re.findall(r"[$\u20b9\u20ac\u00a3]", say)
        return f"these are not in Tamil letters: {', '.join(words)}; write every English word as it sounds in Tamil letters (லம்ப்சம், பிரின்சிபல், இன்ஸ்டால்மென்ட், டெர்ம்), and FD as எஃப்டி"
    if why in ("forecast wording", "advice or rude wording"):
        m = market.FORECAST.search(say) or market.FORECAST.search(en) or market.ADVICE.search(say) or market.ADVICE.search(en)
        return f"the word \"{m.group(0)}\" is not allowed; say it in the plain present tense (இருக்கு, ஆகுது, உண்டு), as a fact the passage states"
    if why == "quote is not in the source":
        return "a quote is not an exact copy of a sentence in the passages (30+ characters); copy a whole sentence exactly, character for character"
    if why in ("a number is not in the quotes", "the Tamil and the English caption give different numbers"):
        return "every number in say and en must be in a quote, the same numbers in both"
    if why == "names a company or the market":
        return "no company, bank or product names and nothing about markets or prices"
    return why


def sentence_sets(pages: list[dict]) -> list[tuple[str, set[str]]]:
    """Every paragraph or sentence of the pages with the stems it holds: what a slide's item is held against (see item_backed)."""
    return [(u, claims(u)[0]) for p in pages for u in units(p["text"])]


def item_backed(text: str, sets: list[tuple[str, set[str]]]) -> bool:
    """Does one sentence of the pages hold what an item on the slide says? Its longer words (60 %, by stem) and any acronym in it must be found in a single sentence, so a slide never
    shows a claim the pages do not make (an item of fewer than two such words is too thin to check and is not shown)."""
    words, acro = claims(text)
    return len(words) + len(acro) >= 2 and any(all(holds(u, a) for a in acro) and len(words & have) >= 0.6 * len(words) for u, have in sets)


def plan_slides(plan: object, source_text: str, short: bool, sets: list[tuple[str, set[str]]] | None = None) -> tuple[str, list[dict]]:
    """(title, slides) from the model's plan, keeping only what is safe to show: headings and items without advice, forecasts, names or invented numbers, each item (and facts row)
    backed by a sentence of the pages when `sets` (sentence_sets) is given; an icon from the list; a slide with fewer than two items or rows is dropped. The title is left "" when it
    fails (promises, advice)."""
    if not isinstance(plan, dict):
        return "", []
    have = market.numbers(source_text)
    ok = lambda s: isinstance(s, str) and 1 <= len(s.strip()) <= 70 and not market.ADVICE.search(s) and not market.FORECAST.search(s) and not market.RUDE.search(s) \
        and not MARKET_DIR.search(s) and market.numbers(s) <= have       # noqa: E731
    title = plan.get("title") if isinstance(plan.get("title"), str) else ""
    title = " ".join(title.split())[:95]
    if not title or youtube.promises(title) or market.ADVICE.search(title) or market.FORECAST.search(title) or MARKET_DIR.search(title):
        title = ""
    out = []
    for s in plan.get("slides") if isinstance(plan.get("slides"), list) else []:
        if not isinstance(s, dict) or not ok(s.get("heading")):
            continue
        icon = s.get("icon") if s.get("icon") in ICONS else "paper"
        if s.get("kind") == "facts" and not short:
            rows = [{"label": r["label"].strip(), "value": r["value"].strip(), "note": (r.get("note") or "").strip(), "tone": "flat"} for r in s.get("rows") or []
                    if isinstance(r, dict) and all(isinstance(r.get(k), str) for k in ("label", "value")) and ok(r["label"]) and ok(r["value"]) and ok(r.get("note") or "x")
                    and (sets is None or item_backed(f"{r['label']} {r['value']} {r.get('note') or ''}", sets))]
            if len(rows) >= 2:
                out.append({"kind": "facts", "title": s["heading"].strip(), "cols": ["Value"], "items": rows[:4]})
        else:
            items = [{"icon": icon, "text": i.strip(), "tone": "good"} for i in s.get("items") or [] if ok(i) and (sets is None or item_backed(i, sets))]
            if len(items) >= 2:
                out.append({"kind": "points", "title": s["heading"].strip(), "items": items[:3 if short else 4]})
    return title, out[:2 if short else 5]


# ---------- the spoken lines ----------
COMMON = market.STOP | {"does", "when", "your", "they", "them", "then", "only", "each", "every", "many", "most", "much", "some", "other", "about", "after", "before", "because", "either",
                        "being", "would", "could", "should", "using", "make", "makes", "made", "take", "takes", "give", "gives", "allow", "allowed", "means", "mean", "said", "just", "same",
                        "whether", "where", "what", "whom", "whose", "these", "those", "still", "even", "also", "very", "than", "rupee", "rupees", "lakh", "lakhs", "crore", "crores", "percent", "covering", "covers"}


def stem(word: str) -> str:
    """A word as compared between a line and its quote: lower case, a plural or -ed/-ing ending dropped, the first five letters."""
    return (re.sub(r"(ing|ed|es|s)$", "", word) if len(word) > 4 else word)[:5]


def claims(text: str) -> tuple[set[str], set[str]]:
    """(the stems of the longer words a line leans on, the acronyms in it): what a quote must hold for the line to be said to be backed by it."""
    return {stem(w) for w in re.findall(r"[a-z]{4,}", norm(re.sub(r"\b[A-Z]{2,5}\b", " ", text))) if w not in COMMON}, set(re.findall(r"\b[A-Z]{2,5}\b", text))


EXPAND = {"FD": "fixed deposit", "RD": "recurring deposit", "NPS": "national pension", "PPF": "public provident", "EPF": "provident fund", "SIP": "systematic investment",
          "ELSS": "equity linked saving", "SGB": "sovereign gold bond", "NAV": "net asset value", "IPO": "initial public offer", "ETF": "exchange traded fund",
          "LRS": "liberalised remittance", "ULIP": "unit linked", "KYC": "know your customer", "RBI": "reserve bank", "SEBI": "securities and exchange board", "DICGC": "deposit insurance",
          "AMC": "asset management", "NSC": "national savings certificate", "KVP": "kisan vikas", "SSA": "sukanya", "EGR": "electronic gold receipt", "UAN": "universal account"}
CLAUSE = re.compile(r"[,;:]|\b(?:and|while|but|whereas|so|which|that|also)\b")


def holds(quote: str, word: str) -> bool:
    """Does the quote have this acronym, as a word or by its usual expansion (FD: "fixed deposit")?"""
    return bool(re.search(rf"\b{word}\b", quote)) or EXPAND.get(word, "\0") in norm(quote)


def backed_by(en: str, quotes: list[str]) -> bool:
    """Is the English line really what the quotes say? A line with no acronym is backed when 60 % of its longer words (by stem) are in one quote, or 80 % in the quotes together. A line that
    names a thing by its acronym is held to more: each clause of it (cut at commas, "and", "while", "but"...) must be backed by ONE quote: that quote holds every acronym of the
    clause (FD, RD, NPS: as written or by its usual expansion) and at least 60 % of the clause's longer words (by stem); a clause with a single such word is backed if any quote has it.
    A line with fewer than two such words in all is too thin to check and is refused. So two quotes cannot be stitched into a claim neither makes ("RD has a 5 year lock-in"
    from a quote on term deposits and a quote on RDs), while "FD is this, RD is that" is fine when each half has its own quote."""
    words, acro = claims(en)
    if len(words) + len(acro) < 2:
        return False
    sets = [claims(q)[0] for q in quotes]
    if not acro:                                                  # no thing named by its acronym to bind a claim to: the line as a whole against the best quote, or all the quotes together
        return any(len(words & have) >= 0.6 * len(words) for have in sets) or len(words & set().union(*sets)) >= 0.8 * len(words)
    for clause in CLAUSE.split(en):
        w, a = claims(clause)
        if not w and not a:
            continue
        if len(w) + len(a) == 1:
            if not any(w <= have and all(holds(q, x) for x in a) for q, have in zip(quotes, sets)):
                return False
        elif not any(all(holds(q, x) for x in a) and len(w & have) >= 0.6 * len(w) for q, have in zip(quotes, sets)):
            return False
    return True


def stems_of(text: str) -> set[str]:
    w, a = claims(text)
    return w | {x.lower() for x in a}


LETTERS = {"A": "ஏ", "B": "பி", "C": "சி", "D": "டி", "E": "ஈ", "F": "எஃப்", "G": "ஜி", "H": "ஹெச்", "I": "ஐ", "J": "ஜே", "K": "கே", "L": "எல்", "M": "எம்", "N": "என்", "O": "ஓ",
           "P": "பி", "Q": "க்யூ", "R": "ஆர்", "S": "எஸ்", "T": "டி", "U": "யூ", "V": "வி", "W": "டபிள்யூ", "X": "எக்ஸ்", "Y": "வை", "Z": "இசெட்"}       # an acronym read letter by letter, run together
WORDS_TA = {"unit": "யூனிட்", "units": "யூனிட்ஸ்", "fund": "ஃபண்ட்", "funds": "ஃபண்ட்ஸ்", "mutual": "மியூச்சுவல்", "scheme": "ஸ்கீம்", "loan": "லோன்", "interest": "இன்ட்ரெஸ்ட்",
            "deposit": "டெபாசிட்", "deposits": "டெபாசிட்ஸ்", "principal": "பிரின்சிபல்", "investor": "இன்வெஸ்டர்", "investors": "இன்வெஸ்டர்ஸ்", "load": "லோட்", "exit": "எக்ஸிட்",
            "lock": "லாக்", "in": "இன்", "term": "டெர்ம்", "plan": "ப்ளான்", "tax": "டாக்ஸ்", "gold": "கோல்ட்", "bond": "பாண்ட்", "bonds": "பாண்ட்ஸ்", "risk": "ரிஸ்க்",
            "return": "ரிட்டர்ன்", "returns": "ரிட்டர்ன்ஸ்", "inflation": "இன்ஃப்ளேஷன்", "budget": "பட்ஜெட்", "saving": "சேவிங்", "savings": "சேவிங்ஸ்", "account": "அக்கவுன்ட்",
            "penalty": "பெனால்டி", "maturity": "மெச்சூரிட்டி", "customer": "கஸ்டமர்", "amount": "அமவுண்ட்", "rate": "ரேட்", "monthly": "மன்த்லி", "lakh": "லட்சம்", "crore": "கோடி",
            "demat": "டிமேட்", "broker": "ப்ரோக்கர்", "mutual fund": "மியூச்சுவல் ஃபண்ட்", "sip": "எஸ்ஐபி", "nav": "என்ஏவி", "fd": "எஃப்டி", "rd": "ஆர்டி"}         # a fallback for a word the writer left in Latin letters


def tamilise(say: str) -> str:
    """The line with English words the writer left in Latin letters written as a Tamil speaker says them: acronyms letter by letter (NAV -> என்ஏவி), common finance words from tamil_say.SOUNDS
    or WORDS_TA. A word it does not know stays, and check_line then throws the line out."""
    from .tamil_say import SOUNDS

    def one(m: re.Match) -> str:
        w = m.group(0)
        if w.lower() in SOUNDS or w.lower() in WORDS_TA:
            return SOUNDS.get(w.lower()) or WORDS_TA[w.lower()]
        return "".join(LETTERS[c] for c in w) if w.isupper() and 2 <= len(w) <= 6 else w
    return re.sub(r"[A-Za-z]+", one, say)


def squash(text: str) -> str:
    """Text as a quote is compared with a page: filings_text.norm, a parenthetical aside and the quotation marks left out, and the rupee written one way (a model often leaves out
    "(Rupees Five Lakhs)" or changes ` / Rs. / ₹ when it copies a sentence; a sentence is still found if only those differ)."""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[\u20b9`]|\brs\.?|\brupees?\b", " rs ", norm(text).replace("\u20b9", "`"), flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"[\"'\u2018\u2019\u201c\u201d()]", "", text)).strip()


WORD_N = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "fifty": 50}
UNITS = {"lakh": 1e5, "lakhs": 1e5, "லட்சம்": 1e5, "crore": 1e7, "crores": 1e7, "கோடி": 1e7, "thousand": 1e3}


def figs(text: str) -> set[str]:
    """The numbers of a text as figures to compare: "5 lakh", "5 லட்சம்" and "5,00,000" are all 500000 (market.numbers sees only the 5 in the first two)."""
    def one(m: re.Match) -> str:
        v = float(m.group(1).replace(",", "")) * UNITS[m.group(2).lower()]
        return str(int(v)) if v == int(v) else str(v)
    text = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|fifty)\s+(?=lakhs?|crores?|thousand)", lambda m: f"{WORD_N[m.group(1).lower()]} ", text, flags=re.I)
    return market.numbers(re.sub(r"(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|crores?|thousand|லட்சம்|கோடி)", one, text, flags=re.I))


def check_line(item: object, docs: list[str], bad, tx: set) -> str:
    """Why a line from the model is thrown away, or "" when it is kept. `docs` are the pages' texts as squash() gives them, `bad` from bad_pattern, `tx` the transcripts' shingles."""
    if not isinstance(item, dict) or not isinstance(item.get("say"), str) or not isinstance(item.get("en"), str) or not isinstance(item.get("quotes"), list):
        return "not a complete line"
    say, en = " ".join(item["say"].split()), " ".join(item["en"].split())
    quotes = [q.strip() for q in item["quotes"] if isinstance(q, str) and q.strip()]
    if not say or not en or not quotes:
        return "no line, caption or quote"
    if not 6 <= len(say.split()) <= 60 or len(en.split()) < 5:
        return "a line of the wrong length"
    if any(say.split().count(w) >= 3 for w in set(say.split())):
        return "a garbled line (a word repeated)"
    if BOOKISH.search(say):
        return "book Tamil, not the way the host speaks"
    for q in quotes:
        if len(q) < 30 or not any(squash(q).rstrip(" .,;:") in d for d in docs):
            return "quote is not in the source"
    have = set().union(*(figs(q) for q in quotes))
    if not figs(say) <= have or not figs(en) <= have:
        return "a number is not in the quotes"
    if figs(say) != figs(en):
        return "the Tamil and the English caption give different numbers"
    if LATIN.search(say) or re.search(r"[$\u20b9\u20ac\u00a3]", say):
        return "spoken line is not all Tamil script"
    if clone.unspelt(say):
        return "the voice would garble an English word"
    for t in (say, en):
        if market.ADVICE.search(t) or market.RUDE.search(t):
            return "advice or rude wording"
        if market.FORECAST.search(t):
            return "forecast wording"
    if bad.search(say) or bad.search(en):
        return "names a company or the market"
    if not backed_by(en, quotes):
        return "the caption says more than its quotes do"
    if tx and (shingles(en) & tx or shingles(say) & tx):
        return "a near copy of a transcript"
    return ""


class Busy(Exception):
    """The writer's allowance is used up (Groq answers 429 once its 200,000 tokens a day, shared with every other writer in VISION, are spent): a wait, not a fault of the topic."""


async def ask(llm, prompt: str, tokens: int, model: str | None = None):
    """One writer request, asked again once if it fails. A 429 (llm.py has already waited and tried three times) raises Busy."""
    err = None
    for _ in range(2):
        try:
            return await llm.json(prompt, tier="writer", max_tokens=tokens, **({"model": model} if model else {}))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise Busy(str(e)) from e
            err = e
        except Exception as e:  # noqa: BLE001
            err = e
    log.warning("lessons: the writer failed (%s)", err)
    return None


def chip(pages: list[dict], used: list[int]) -> str:
    """"Source: RBI FAQ on term deposits · rbi.org.in" for the pages (1-based tags) a slide's lines came from, at most two."""
    seen = []
    for n in used:
        p = pages[n - 1]
        if p not in seen:
            seen.append(p)
    return "Source: " + " + ".join(f"{p['label']} · {domain(p['url'])}" for p in seen[:2]) if seen else ""


def source_tag(quote: str, docs: list[str]) -> int:
    q = squash(quote).rstrip(" .,;:")
    return next((i for i, d in enumerate(docs, 1) if q in d), 1)


async def write(llm, tp: dict, pages: list[dict], transcripts: list[dict], bad, short: bool = False, covered: list[str] = (), model: str | None = None) -> dict:
    """The lesson: {title, deck, lines, concept, proposed, kept, dropped: [{say, en, why}], angle, tokens (the writer's, for Groq's daily allowance), too_thin}.
    `model` names another writer model (channel option `lesson_model`: Groq keeps a separate daily allowance per model, and the usual one is shared with every other writer in VISION).
    deck/lines are the long video's (notice, cover, point/facts slides, then the fixed closing and sign-off) or the Short's (point slides, sign-off), and exist only when it is not too_thin."""
    docs, tokens0 = [squash(p["text"]) for p in pages], getattr(llm, "used", 0)
    all_text = "\n".join(p["text"] for p in pages)
    tx = set().union(*(shingles(t["text"]) for t in transcripts)) if transcripts else set()
    a = await angle(llm, tp, transcript_text(transcripts, bad), model)
    shape = PLAN_SHORT if short else PLAN_LONG
    kws = keywords(tp["title"], *tp["words"])
    ask_plan = PLAN.format(title=tp["title"], passages=passages(pages, kws), hints=hints(a) + ("\n" if a else ""), count=shape[1], shape=shape[0], icons=", ".join(ICONS),
                           facts=shape[2].format(covered=", ".join(covered) or "none yet") if short else shape[2])
    raw = await ask(llm, ask_plan, 1800, model)
    title, plan = plan_slides(raw, all_text, short, sentence_sets(pages))
    concept = " ".join(str(raw.get("concept") or "").split())[:60] if isinstance(raw, dict) and short else ""
    out = {"title": title or f"{tp['title']} தமிழில் | Finance Basics"[:100], "concept": concept, "angle": a, "proposed": 0, "kept": 0, "dropped": [], "too_thin": True, "tokens": 0}
    if not plan:
        return out
    lines, kept_slides = [], []
    for s in plan:
        n = len(s["items"])
        shown = " | ".join(i["text"] if "text" in i else f"{i['label']}: {i['value']}" for i in s["items"])
        ask_lines = LINES.format(title=tp["title"], passages=passages(pages, keywords(s["title"], shown, tp["title"]), SLIDE_PASSAGES), heading=s["title"], items=shown,
                                 count="4 or 5" if not short else "3 or 4", n=n, bad_ta=WORDS_BAD_TA, bad_en=WORDS_BAD_EN, style="\n".join(f"- {x}" for x in STYLE))
        mine, rejected = [], []
        told = {m["say"] for ls in lines for m in ls}

        def take(got) -> None:
            show = max([m["show"] for m in mine] or [1])
            for it in (got.get("lines") if isinstance(got, dict) and isinstance(got.get("lines"), list) else [])[:7]:
                out["proposed"] += 1
                if isinstance(it, dict) and isinstance(it.get("say"), str):
                    it = {**it, "say": tamilise(it["say"])}
                why = check_line(it, docs, bad, tx)
                if not why and (" ".join(it["say"].split()) in told | {m["say"] for m in mine}
                                or any(len(stems_of(it["en"]) & stems_of(m["en"])) >= 0.7 * max(len(stems_of(it["en"])), 1) for m in mine) ):
                    why = "repeats a line"
                if why:
                    d = {"say": str(it.get("say", ""))[:200] if isinstance(it, dict) else "", "en": str(it.get("en", ""))[:200] if isinstance(it, dict) else "", "why": why}
                    out["dropped"].append(d)
                    rejected.append({**d, "fix": explain(it, why)})
                    continue
                try:
                    show = max(show, min(max(int(it.get("show", 1)), 1), n))
                except (TypeError, ValueError):
                    pass
                mine.append({"say": " ".join(it["say"].split()), "en": " ".join(it["en"].split()), "show": show, "src": source_tag(it["quotes"][0], docs),
                             "quotes": [q.strip() for q in it["quotes"] if isinstance(q, str)]})
        take(await ask(llm, ask_lines, 2000, model))
        if rejected and len(mine) < (4 if not short else 3):           # one more go at the lines the checks threw out, told what was wrong with each
            again = "\n".join(f'- "{r["say"]}" / "{r["en"]}": {r["fix"]}' for r in rejected[:6])
            rejected.clear()
            take(await ask(llm, ask_lines + REPAIR.format(rejected=again), 2000, model))
        if mine:
            mine[-1]["show"] = n + 1                                          # the last line shows everything and the source chip
            lines.append(mine)
            kept_slides.append({**s, "note": chip(pages, [m["src"] for m in mine]), "note_always": True})
    out["kept"], out["tokens"] = sum(map(len, lines)), getattr(llm, "used", 0) - tokens0
    if out["kept"] < (MIN_KEPT_SHORT if short else MIN_KEPT):
        return out
    deck, said = assemble(tp, kept_slides, lines, short)
    return {**out, "deck": deck, "lines": said, "too_thin": False}


def fit(text: str, size: int) -> str:
    """The text cut at a word before `size` characters (never in the middle of a word)."""
    head = text[:size + 1]
    return text if len(text) <= size else head[:-1] if head.endswith(" ") else head.rsplit(" ", 1)[0]


def assemble(tp: dict, slides_: list[dict], lines: list[list[dict]], short: bool) -> tuple[list[dict], list[dict]]:
    """The deck and the spoken lines in order. A long video: the notice card (its short spoken line, held 6 s), the cover (opening line), the slides with their lines, the closing
    line and the subscribe sign-off on the last slide. A Short: the slides and the subscribe sign-off (no card, no spoken disclaimer)."""
    if short:
        deck = list(slides_)
        said = [{"slide": s, "show": m["show"], "say": m["say"], "en": m["en"], "quotes": m["quotes"]} for s, ms in enumerate(lines) for m in ms]
        last = deck[-1]
        said.append({"slide": len(deck) - 1, "show": len(last["items"]) + 1, "say": market.SUBSCRIBE_SHORT, "en": market.SUBSCRIBE_SHORT_EN, "fixed": True})
        return deck, said
    cover = {"kind": "cover", "title": tp["title"], "items": [{"icon": tp["icon"], "text": fit(tp["title"], 26)}, {"icon": "paper", "text": "Official sources"}, {"icon": "lens", "text": "புரிஞ்சிக்கலாம்"}]}
    deck = [market.NOTICE, cover, *slides_]
    said = [{"slide": 0, "show": 1, "say": market.NOTICE_SAY, "en": market.NOTICE_SAY_EN, "fixed": True, "hold": market.NOTICE_HOLD},
            {"slide": 1, "show": 3, "say": OPEN_SAY.format(ta=tp["ta"]), "en": OPEN_EN.format(title=tp["title"]), "fixed": True}]
    said += [{"slide": 2 + s, "show": m["show"], "say": m["say"], "en": m["en"], "quotes": m["quotes"]} for s, ms in enumerate(lines) for m in ms]
    end, n = len(deck) - 1, len(deck[-1]["items"]) + 1
    said += [{"slide": end, "show": n, "say": CLOSE_SAY, "en": CLOSE_EN, "fixed": True}, {"slide": end, "show": n, "say": market.SUBSCRIBE_LONG, "en": market.SUBSCRIBE_LONG_EN, "fixed": True}]
    return deck, said


# ---------- what the upload carries ----------
def tags(tp: dict, short: bool) -> list[str]:
    return ["#PersonalFinanceTamil", "#TamilFinance", "#MoneyBasics", "#" + re.sub(r"[^A-Za-z0-9]", "", tp["group"].title())]


def summary(tp: dict, pages: list[dict], title: str, short: bool, disclaimer: str) -> str:
    """The description: what the lesson covers, the hashtags, "Sources:" with each official page (its name and address), the two disclaimer paragraphs last."""
    what = (f"A plain-language {'quick lesson' if short else 'lesson'} on {tp['title']}: how it works and what to check, from official sources. "
            "Information only, nothing here is investment advice.")
    return f"{what}\n\n" + " ".join(tags(tp, short)) + "\n\nSources:\n" + "\n".join(f"{p['label']}: {p['url']}" for p in pages) + f"\n\n{disclaimer}"
