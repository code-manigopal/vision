"""Text for the voice: English words in Tamil letters and numbers as Tamil words.

A Tamil voice guesses at "revenue" written in English letters, and reads digit strings badly. The slides keep the
English spelling and the digits; only what is sent to the voice goes through voiced(). SOUNDS is the table of how
Mani says each word: correct it by ear, add to it freely (longest match first, whole words only, case ignored).

The spelling Mani picked by ear (2026-10-13, cloned voice): every English word in Tamil letters (left in English
letters the voice skips or garbles them), abbreviations run together with no dots or spaces (a dot is heard as a
full stop), endings joined to their word with no hyphen (பேங்க்-ஓட -> பேங்கோட), and a financial year said the way he
says it (FY27 -> ட்வென்டி சிக்ஸ் ட்வென்டி செவன் ஃபைனான்ஷியல் இயர்).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("vision.tamil_say")
FIXES = Path(__file__).resolve().parent.parent.parent / "data" / "voice_fixes.json"        # Mani's own spellings {english word or phrase: Tamil letters}; they win over everything (see fixes())
GOLDEN = Path(__file__).resolve().parent.parent.parent / "tests" / "golden_voice.json"     # the approved reference lines a fix must not change without force
LEARNED = Path(__file__).resolve().parent.parent.parent / "data" / "voice_words.json"      # words a model has said how a Tamil speaker pronounces (see learn()); Mani checks them by ear

SOUNDS = {
    "net interest income": "நெட் இன்ட்ரெஸ்ட் இன்கம்", "operating margin": "ஆப்பரேட்டிங் மார்ஜின்", "operating profit": "ஆப்பரேட்டிங் ப்ராஃபிட்",
    "net profit": "நெட் ப்ராஃபிட்", "gross npa": "க்ராஸ் என்பிஏ", "net npa": "நெட் என்பிஏ", "loan quality": "லோன் குவாலிட்டி",
    "sebi registered advisor": "செபி ரெஜிஸ்டர்ட் அட்வைசர்", "revenue": "ரெவென்யூ", "educational purpose": "எஜுகேஷனல் பர்பஸ்", "investment recommendation": "இன்வெஸ்ட்மென்ட் ரெகமெண்டேஷன்", "provisions": "ப்ரொவிஷன்ஸ்", "eps": "ஈபிஎஸ்", "npa": "என்பிஏ",
    "quarter": "குவார்ட்டர்", "percent": "பர்சன்ட்", "result": "ரிசல்ட்", "results": "ரிசல்ட்ஸ்", "numbers": "நம்பர்ஸ்", "number": "நம்பர்",
    "company": "கம்பெனி", "share": "ஷேர்", "bank": "பேங்க்", "report": "ரிப்போர்ட்", "income": "இன்கம்", "profit": "ப்ராஃபிட்", "margin": "மார்ஜின்",
    "growth": "க்ரோத்", "pressure": "ப்ரெஷர்", "invest": "இன்வெஸ்ட்", "level": "லெவல்", "hero": "ஹீரோ", "compare": "கம்பேர்", "video": "வீடியோ",
    "financial year": "ஃபைனான்ஷியல் இயர்", "q1": "க்யூ ஒன்", "q2": "க்யூ டூ", "q3": "க்யூ த்ரீ", "q4": "க்யூ ஃபோர்",
    "hdfc": "ஹெச்டிஎஃப்சி", "tcs": "டிசிஎஸ்", "icici": "ஐசிஐசிஐ", "sbi": "எஸ்பிஐ", "infosys": "இன்ஃபோசிஸ்", "limited": "லிமிடெட்", "itc": "ஐடிசி",
    # the company analysis videos: abbreviations run together, phrases before their words (longest match wins)
    "roe": "ஆர்ஓஈ", "roce": "ஆர்ஓசிஈ", "roa": "ஆர்ஓஏ", "pe": "பிஈ", "ebitda": "எபிட்டா", "ev to ebitda": "ஈவி டு எபிட்டா", "sebi": "செபி",
    "market cap": "மார்க்கெட் கேப்", "book value": "புக் வேல்யூ", "dividend yield": "டிவிடெண்ட் யீல்ட்", "promoter holding": "ப்ரமோட்டர் ஹோல்டிங்",
    "debt to equity": "டெட் டு ஈக்விட்டி", "price to book": "ப்ரைஸ் டு புக்", "free cash flow": "ஃப்ரீ கேஷ் ஃப்ளோ", "operating cash flow": "ஆப்பரேட்டிங் கேஷ் ஃப்ளோ",
    "asset turnover": "அசெட் டர்ன்ஓவர்", "lease liabilities": "லீஸ் லயபிலிட்டீஸ்", "52 week": "ஐம்பத்து இரண்டு வீக்",
    "asset": "அசெட்", "assets": "அசெட்ஸ்", "book": "புக்", "cash": "கேஷ்", "debt": "டெட்", "dividend": "டிவிடெண்ட்", "free": "ஃப்ரீ", "lease": "லீஸ்",
    "market": "மார்க்கெட்", "operating": "ஆப்பரேட்டிங்", "price": "ப்ரைஸ்", "promoter": "ப்ரமோட்டர்", "reserves": "ரிசர்வ்ஸ்", "analysis": "அனாலிசிஸ்",
    "business": "பிசினஸ்", "cap": "கேப்", "channel": "ச்சேனல்", "close": "க்ளோஸ்", "educational": "எஜுகேஷனல்", "equity": "ஈக்விட்டி", "file": "ஃபைல்",
    "filing": "ஃபைலிங்", "financial": "ஃபைனான்ஷியல்", "flow": "ஃப்ளோ", "fundamental": "ஃபண்டமென்டல்", "group": "குரூப்", "high": "ஹை", "holders": "ஹோல்டர்ஸ்",
    "holding": "ஹோல்டிங்", "liabilities": "லயபிலிட்டீஸ்", "low": "லோ", "machine": "மெஷின்", "statements": "ஸ்டேட்மென்ட்ஸ்", "to": "டு",
    "turnover": "டர்ன்ஓவர்", "value": "வேல்யூ", "week": "வீக்", "yield": "யீல்ட்", "net": "நெட்",
    # the reasons, key ratios and news of a results video
    "guidance": "கைடன்ஸ்", "headline": "ஹெட்லைன்", "headlines": "ஹெட்லைன்ஸ்", "news": "நியூஸ்", "sources": "சோர்ஸஸ்", "screen": "ஸ்க்ரீன்", "ratios": "ரேஷியோஸ்",
    "ratio": "ரேஷியோ",
    # finance lessons
    "lesson": "லெசன்", "lessons": "லெசன்ஸ்",
    # financials: lenders (NBFCs) and insurers
    "combined ratio": "கம்பைன்ட் ரேஷியோ", "credit cost": "க்ரெடிட் காஸ்ட்", "net interest margin": "நெட் இன்ட்ரெஸ்ட் மார்ஜின்", "interest income": "இன்ட்ரெஸ்ட் இன்கம்",
    "finance costs": "ஃபைனான்ஸ் காஸ்ட்ஸ்", "first year": "ஃபர்ஸ்ட் இயர்", "stage 3": "ஸ்டேஜ் த்ரீ", "credit": "க்ரெடிட்", "cost": "காஸ்ட்", "costs": "காஸ்ட்ஸ்",
    "premium": "ப்ரீமியம்", "solvency": "சால்வென்சி", "renewal": "ரெனிவல்", "gross": "க்ராஸ்", "written": "ரிட்டன்", "earned": "ஏர்ண்ட்", "interest": "இன்ட்ரெஸ்ட்",
    "insurance": "இன்ஷூரன்ஸ்", "reinsurance": "ரீஇன்ஷூரன்ஸ்", "policy": "பாலிசி", "policies": "பாலிசீஸ்", "claim": "க்ளெய்ம்", "claims": "க்ளெய்ம்ஸ்",
    "underwriting": "அண்டர்ரைட்டிங்", "irdai": "ஐஆர்டிஏஐ", "lender": "லெண்டர்", "nbfc": "என்பிஎஃப்சி", "aum": "ஏயுஎம்", "year": "இயர்",
    # the pre-market and post-market Shorts: index names as a Tamil speaker says them, abbreviations run together; "S&P 500" is a phrase so its & and 500 are not read as a number
    "bank nifty": "பேங்க் நிஃப்டி", "gift nifty": "கிஃப்ட் நிஃப்டி", "sgx nifty": "எஸ்ஜிஎக்ஸ் நிஃப்டி", "nifty": "நிஃப்டி", "sensex": "ஸென்செக்ஸ்", "s&p 500": "எஸ் அண்ட் பி ஃபைவ் ஹண்ட்ரட்",
    "dow jones": "டவ் ஜோன்ஸ்", "nasdaq": "நாஸ்டாக்", "nikkei": "நிக்கே", "kospi": "காஸ்பி", "hang seng": "ஹாங் செங்", "ftse": "ஃபுட்ஸி", "dax": "டாக்ஸ்", "cac": "காக்",
    "points": "பாயிண்ட்ஸ்", "us": "யூஎஸ்", "europe": "யூரோப்", "asia": "ஏஷியா", "pre-market": "ப்ரீ மார்க்கெட்", "post-market": "போஸ்ட் மார்க்கெட்",
    "open": "ஓபன்", "subscribe": "சப்ஸ்க்ரைப்", "update": "அப்டேட்",
    # the sign-off lines: how a Tamil speaker says them
    "bell icon": "பெல் ஐகான்", "click": "க்ளிக்", "videos": "வீடியோஸ்", "notification": "நோட்டிஃபிகேஷன்", "time": "டைம்", "time-க்கு": "டைமுக்கு", "miss": "மிஸ்",
    "market and finance": "மார்க்கெட் அண்ட் ஃபைனான்ஸ்", "finance": "ஃபைனான்ஸ்", "related": "ரிலேட்டட்", "contents": "கன்டென்ட்ஸ்", "daily": "டெய்லி",
}

ONES = ["", "ஒன்று", "இரண்டு", "மூன்று", "நான்கு", "ஐந்து", "ஆறு", "ஏழு", "எட்டு", "ஒன்பது", "பத்து", "பதினொன்று", "பன்னிரண்டு", "பதிமூன்று",
        "பதினான்கு", "பதினைந்து", "பதினாறு", "பதினேழு", "பதினெட்டு", "பத்தொன்பது"]
TENS = ["", "", "இருபது", "முப்பது", "நாற்பது", "ஐம்பது", "அறுபது", "எழுபது", "எண்பது", "தொண்ணூறு"]
TENS_AND = ["", "", "இருபத்து", "முப்பத்து", "நாற்பத்து", "ஐம்பத்து", "அறுபத்து", "எழுபத்து", "எண்பத்து", "தொண்ணூற்று"]
HUNDREDS = ["", "நூறு", "இருநூறு", "முன்னூறு", "நானூறு", "ஐநூறு", "அறுநூறு", "எழுநூறு", "எண்ணூறு", "தொள்ளாயிரம்"]
HUNDREDS_AND = ["", "நூற்று", "இருநூற்று", "முன்னூற்று", "நானூற்று", "ஐநூற்று", "அறுநூற்று", "எழுநூற்று", "எண்ணூற்று", "தொள்ளாயிரத்து"]
THOUSANDS = ["", "ஆயிரம்", "இரண்டாயிரம்", "மூவாயிரம்", "நான்காயிரம்", "ஐந்தாயிரம்", "ஆறாயிரம்", "ஏழாயிரம்", "எட்டாயிரம்", "ஒன்பதாயிரம்"]
DIGITS = ["பூஜ்ஜியம்"] + ONES[1:10]


def _under_thousand(n: int) -> str:
    h, r = divmod(n, 100)
    two = ONES[r] if r < 20 else (TENS[r // 10] if r % 10 == 0 else f"{TENS_AND[r // 10]} {ONES[r % 10]}")
    return two if not h else HUNDREDS[h] if not r else f"{HUNDREDS_AND[h]} {two}"


def number_words(n: int) -> str:
    """A whole number in Tamil words, the Indian way (thousand, lakh, crore): 73188 -> எழுபத்து மூவாயிரத்து நூற்று எண்பத்து எட்டு."""
    if n == 0:
        return DIGITS[0]
    if n < 0:
        return "மைனஸ் " + number_words(-n)
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thou, rest = divmod(n, 1000)
    parts = []
    if crore:
        parts.append(("ஒரு" if crore == 1 else number_words(crore)) + " கோடி" + ("யே" if lakh or thou or rest else ""))
    if lakh:
        parts.append(("ஒரு" if lakh == 1 else _under_thousand(lakh)) + (" லட்சத்து" if thou or rest else " லட்சம்"))
    if thou:                                            # under a hundred here: the lakhs took the rest
        fused = thou > 19 and thou % 10 > 1             # எழுபத்து மூவாயிரம், not எழுபத்து மூன்று ஆயிரம்
        t = THOUSANDS[thou] if thou < 10 else f"{TENS_AND[thou // 10]} {THOUSANDS[thou % 10]}" if fused else _under_thousand(thou) + " ஆயிரம்"
        parts.append(t[:-2] + "த்து" if rest else t)    # ஆயிரம் -> ஆயிரத்து before what follows
    if rest:
        parts.append(_under_thousand(rest))
    return " ".join(parts)


def number_said(text: str) -> str:
    """A number as the voice should say it. A whole number in Tamil words, the Indian way: "73,188" -> எழுபத்து மூவாயிரத்து
    நூற்று எண்பத்து எட்டு. A number with a decimal point the way Tanglish speakers say it, in English: "0.07" -> ஜீரோ பாயிண்ட்
    ஜீரோ செவன், "25.7" -> ட்வென்டி ஃபைவ் பாயிண்ட் செவன் (Mani, 2026-10-14: "பூஜ்ஜியம் புள்ளி பூஜ்ஜியம் ஏழு" came out
    with odd gaps; percentages and ratios are said in English in speech anyway)."""
    whole, _, frac = text.replace(",", "").partition(".")
    if not frac:
        return number_words(int(whole or 0))
    return f"{english_words(int(whole or 0))} பாயிண்ட் " + " ".join(EN_DIGITS[int(d)] for d in frac)


_WORDS = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(k) for k in sorted(SOUNDS, key=len, reverse=True)) + r")(?![A-Za-z])", re.I)


EN_ONES = ["", "ஒன்", "டூ", "த்ரீ", "ஃபோர்", "ஃபைவ்", "சிக்ஸ்", "செவன்", "எய்ட்", "நைன்", "டென்", "இலெவன்", "ட்வெல்வ்", "தர்டீன்", "ஃபோர்டீன்",
           "ஃபிஃப்டீன்", "சிக்ஸ்டீன்", "செவன்டீன்", "எய்டீன்", "நைன்டீன்"]
EN_TENS = {2: "ட்வென்டி", 3: "தர்ட்டி", 4: "ஃபார்ட்டி", 5: "ஃபிஃப்டி", 6: "சிக்ஸ்டி", 7: "செவன்டி", 8: "எய்ட்டி", 9: "நைன்டி"}
EN_DIGITS = ["ஜீரோ"] + EN_ONES[1:10]


def english_words(n: int) -> str:
    """A whole number in English words, in Tamil letters: 25 -> ட்வென்டி ஃபைவ், 138 -> ஒன் ஹண்ட்ரட் தர்ட்டி எய்ட்."""
    if n < 0:
        return "மைனஸ் " + english_words(-n)
    if n < 20:
        return EN_ONES[n] or EN_DIGITS[0]
    if n < 100:
        return f"{EN_TENS[n // 10]} {EN_ONES[n % 10]}".strip()
    if n < 1000:
        return f"{EN_ONES[n // 100]} ஹண்ட்ரட்" + (f" {english_words(n % 100)}" if n % 100 else "")
    return f"{english_words(n // 1000)} தவுசன்ட்" + (f" {english_words(n % 1000)}" if n % 1000 else "")
FRONT = "ிீெேை"                                       # the vowel signs i, ii, e, ee, ai
SIGN = {"அ": "", "ஆ": "ா", "இ": "ி", "ஈ": "ீ", "உ": "ு", "ஊ": "ூ", "எ": "ெ", "ஏ": "ே", "ஐ": "ை", "ஒ": "ொ", "ஓ": "ோ"}


def _year(yy: int) -> str:
    """27 -> ட்வென்டி செவன் (a year is said in English)."""
    return f"{EN_TENS[yy // 10]} {EN_ONES[yy % 10]}".strip() if yy // 10 in EN_TENS else number_words(yy)


def _join(m: re.Match) -> str:
    """An ending joined to its word: பேங்க்-ஓட -> பேங்கோட, ஹீரோ-ஓட -> ஹீரோவோட, டெய்லி-உம் -> டெய்லியும், குவார்ட்டர்-ல -> குவார்ட்டர்ல."""
    before, after = m.group(1), m.group(2)
    if after not in SIGN:
        return before + after
    if before.endswith("்"):
        return before[:-1] + SIGN[after]
    return before + ("ய" if before[-1] in FRONT else "வ") + SIGN[after]       # after a front vowel Tamil glides with ய (டெய்லி-உம் -> டெய்லியும்), else வ


def numbers_as_words(text: str) -> str:
    """Only the numbers put into Tamil words, for a voice that reads English letters itself but spells digits out one by one (Edge's)."""
    return re.sub(r"\d[\d,]*(?:\.\d+)?", lambda m: number_said(m.group(0)), text)


_cache: dict = {"stamp": None, "words": {}}


def learned() -> dict[str, str]:
    """The learned words (lower case English -> Tamil letters) from data/voice_words.json. Only an entry whose value is Tamil letters (and spaces) counts, and never one that SOUNDS has:
    the table Mani corrected by ear always wins, so a learned word cannot change how a line he approved is voiced."""
    try:
        st = LEARNED.stat()
    except OSError:
        return {}
    if _cache["stamp"] == (str(LEARNED), st.st_mtime_ns):
        return _cache["words"]
    try:
        raw = json.loads(LEARNED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    words = {k.lower(): v.strip() for k, v in raw.items() if isinstance(raw, dict) and isinstance(k, str) and isinstance(v, str) and re.fullmatch(r"[A-Za-z]+", k)
             and k.lower() not in SOUNDS and valid_tamil(v)} if isinstance(raw, dict) else {}
    _cache.update(stamp=(str(LEARNED), st.st_mtime_ns), words=words)
    return words


def valid_tamil(text: object) -> bool:
    """Tamil letters and single spaces only, not empty, short: all a learned pronunciation may be."""
    return isinstance(text, str) and 0 < len(text.strip()) <= 40 and bool(re.fullmatch(r"[\u0B80-\u0BFF]+(?: [\u0B80-\u0BFF]+)*", text.strip()))


K_CH = ("chr", "chem", "chor", "chas", "chaos", "character", "chri", "chir", "chiro", "chlor", "chol", "chasm")      # "ch" said as k, not as the ch of channel


def ch_sound(word: str, tamil: str) -> str:
    """A word-initial ச is read as "s" (the voice said "senal" for சேனல்): an English word that starts with the "ch" sound is spelt ச்ச... (ச்சேனல், ச்சார்ஜ், ச்செக்)."""
    tamil = tamil.strip()
    if word.lower().startswith("ch") and not word.lower().startswith(K_CH) and tamil.startswith("ச") and not tamil.startswith("ச்"):
        return "ச்" + tamil
    return tamil


def learn(new: dict) -> dict[str, str]:
    """Adds {english word: Tamil letters} to data/voice_words.json and returns what was added. A word already learned is never overwritten, a word SOUNDS has is never shadowed, a value that is
    not Tamil letters (or a key that is not a plain word) is refused."""
    have = learned()
    add = {k.lower(): ch_sound(k, v) for k, v in new.items() if isinstance(k, str) and re.fullmatch(r"[A-Za-z]+", k) and k.lower() not in SOUNDS and k.lower() not in have and valid_tamil(v)}
    if add:
        try:
            raw = json.loads(LEARNED.read_text(encoding="utf-8")) if LEARNED.exists() else {}
        except (OSError, ValueError):
            raw = {}
        raw = {**add, **(raw if isinstance(raw, dict) else {})}                    # what is on disk wins, even an entry learned() would not use
        LEARNED.parent.mkdir(parents=True, exist_ok=True)
        tmp = LEARNED.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(sorted(raw.items())), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, LEARNED)
    return add


def learned_in(text: str) -> dict[str, str]:
    """The learned words a line uses, for Mani to check by ear."""
    have = learned()
    return {w.lower(): have[w.lower()] for w in re.findall(r"[A-Za-z]+", text) if w.lower() in have}


_fix_cache: dict = {"stamp": None, "words": {}, "rx": None}


def fix_key(word: object) -> str:
    """The word or phrase a fix is for, tidied and lower case; empty if it is not plain English letters (digits, & and ' allowed after the first letter)."""
    w = " ".join(word.lower().split()) if isinstance(word, str) else ""
    return w if len(w) <= 40 and re.fullmatch(r"[a-z][a-z0-9&']*(?: [a-z0-9&']+)*", w) else ""


def _phrase(w: str) -> str:
    return r"(?<![A-Za-z])" + re.escape(w).replace(r"\ ", r"\s+") + r"(?![A-Za-z])"


def fixes() -> dict[str, str]:
    """Mani's pronunciation fixes from data/voice_fixes.json (lower case English word or phrase -> Tamil letters). Only an entry whose value is Tamil letters (and spaces) counts."""
    try:
        st = FIXES.stat()
    except OSError:
        return {}
    if _fix_cache["stamp"] == (str(FIXES), st.st_mtime_ns):
        return _fix_cache["words"]
    try:
        raw = json.loads(FIXES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    words = {fix_key(k): v.strip() for k, v in raw.items() if fix_key(k) and valid_tamil(v)} if isinstance(raw, dict) else {}
    rx = re.compile("|".join(_phrase(k) for k in sorted(words, key=len, reverse=True)), re.I) if words else None
    _fix_cache.update(stamp=(str(FIXES), st.st_mtime_ns), words=words, rx=rx)
    return words


def golden_lines(word: str) -> list[str]:
    """The approved reference lines (tests/golden_voice.json) that use the word: a fix for it would change how they are voiced."""
    try:
        gold = json.loads(GOLDEN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rx = re.compile(_phrase(word), re.I)
    return [g["say"] for g in gold if isinstance(g, dict) and rx.search(g.get("say", ""))]


def source(word: str) -> tuple[str, str]:
    """(where the word's spelling comes from, the spelling): fix, table (SOUNDS), learned or none."""
    w = fix_key(word)
    for name, tab in (("fix", fixes()), ("table", SOUNDS), ("learned", learned())):
        if w in tab:
            return name, tab[w]
    return "none", ""


def set_fix(word: str, spelling: str, force: bool = False) -> dict:
    """Saves Mani's spelling for a word: {ok, message}. Refused when the value is not Tamil letters, and when the word is in the approved reference lines unless force
    (the golden file is never changed here: tests/test_voice.py then fails until the reference is re-recorded)."""
    w = fix_key(word)
    if not w:
        return {"ok": False, "message": "The word must be plain English letters (a phrase is fine)."}
    if not valid_tamil(spelling):
        return {"ok": False, "message": "The spelling must be Tamil letters and spaces only."}
    note = ""
    hit = golden_lines(w)
    if hit:
        if not force:
            return {"ok": False, "message": f"This word is in the approved HDFC reference; change it there first. Line: {hit[0][:80]}"}
        note = " tests/test_voice.py will now fail until the reference is re-recorded."
        log.warning("voice fix %r forced although it is in the approved reference line %r", w, hit[0][:60])
    try:
        raw = json.loads(FIXES.read_text(encoding="utf-8")) if FIXES.exists() else {}
    except (OSError, ValueError):
        raw = {}
    raw = {**(raw if isinstance(raw, dict) else {}), w: spelling.strip()}
    FIXES.parent.mkdir(parents=True, exist_ok=True)
    tmp = FIXES.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(raw.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FIXES)
    return {"ok": True, "message": f"{w} → {spelling.strip()} saved." + note}


def voiced(text: str) -> str:
    """The line as the voice should be given it. Mani's fixes first (his word wins, longest match first), then SOUNDS; what neither has, or the learned words, stays as written."""
    if fixes() and _fix_cache["rx"]:
        text = _fix_cache["rx"].sub(lambda m: fixes()[" ".join(m.group(0).lower().split())], text)
    text = re.sub(r"\bFY\s?(\d{2})\b", lambda m: f"{_year(int(m.group(1)) - 1)} {_year(int(m.group(1)))} financial year", text)
    text = _WORDS.sub(lambda m: SOUNDS[m.group(1).lower()], text)
    extra = learned()
    if extra:                                                                       # a second table, used only for the words SOUNDS left as they were
        text = re.sub(r"(?<![A-Za-z])[A-Za-z]+(?![A-Za-z])", lambda m: extra.get(m.group(0).lower(), m.group(0)), text)
    text = re.sub(r"\d[\d,]*(?:\.\d+)?", lambda m: number_said(m.group(0)), text)
    text = re.sub(r"([\u0B80-\u0BFF]+)-([\u0B80-\u0BFF])", _join, text)
    return re.sub(r"\s+", " ", text.replace("%", " பர்சன்ட்")).strip()
