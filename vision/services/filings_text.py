"""The words in a company's own documents (press release, investor presentation, board outcome): pure functions, no I/O.

    choose(announcements, filed)   which of the company's announcements near a result to read (at most two, each small enough)
    pdf_text(data, max_pages)      the text of a PDF ("" for a scan with no text layer, or a file that is not a PDF)
    relevant(text, limit)          the sentences that talk about the numbers and the reasons behind them, in document order
    norm(text)                     text as compared when a quote is checked: one line, lower case, straight quotes
    html_text(html)                the readable paragraphs of a web page, one per line (an official FAQ page for a finance lesson); html_title(html) its title

The reasons on the results video come from here, so a quote the model gives is checked against this text, never trusted.
"""

from __future__ import annotations

import html as htmllib
import io
import re
from datetime import date, datetime

KINDS = [("press", re.compile(r"press[- ]release|media[- ]release|news[- ]release", re.I)),
         ("presentation", re.compile(r"investor presentation|earnings presentation|results presentation|\bpresentation\b", re.I)),
         ("outcome", re.compile(r"outcome of (?:the )?board", re.I))]
MAX_KB = 8 * 1024                # a bigger file is skipped
# a sentence is kept when it talks about the figures or why they moved
TOPIC = re.compile(r"revenue|growth|margin|profit|demand|deal|order book|\bwins?\b|\bcosts?\b|wage|provision|asset quality|\bnpa|outlook|guidance|expect|due to"
                   r"|driven by|on account of|attributable|\bnet interest|\bnim\b|advances|deposits|headcount|attrition|utili[sz]ation", re.I)


def norm(text: str) -> str:
    text = re.sub("[\u00a0\u2009\u202f]", " ", text).replace("\u00ad", "")
    for odd, plain in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'), ("\u2010", "-"), ("\u2011", "-"), ("\u2013", "-"), ("\u2014", "-")):
        text = text.replace(odd, plain)
    return re.sub(r"\s*-\s*", "-", re.sub(r"\s+", " ", text)).strip().lower()           # a PDF often leaves a space round a hyphen ("industry -leading")


def kind(a: dict) -> str | None:
    """"press", "presentation" or "outcome" (an outcome of a board meeting that deals with results), else None."""
    text = f"{a.get('subject', '')} {a.get('text', '')}"
    for name, rx in KINDS:
        if rx.search(text) and (name != "outcome" or re.search(r"result", text, re.I)):
            return name
    return None


def choose(found: list[dict], filed: str | date, days: int = 3, most: int = 2) -> list[dict]:
    """Press release, then investor presentation, then board outcome, filed within `days` of the result (one of each at most), `most` of them.
    `filed` is the result's filing time ("08-Oct-2026 22:07:33") or a date. A file bigger than MAX_KB is passed over."""
    if isinstance(filed, str):
        try:
            filed = datetime.strptime(filed[:11], "%d-%b-%Y").date()
        except ValueError:
            return []
    best: dict[str, dict] = {}
    for a in found:                                           # newest first: the first of a kind that fits is the one used
        k = kind(a)
        try:
            near = k and abs((datetime.fromisoformat(a["at"]).date() - filed).days) <= days
        except (KeyError, ValueError):
            near = False
        if near and (a.get("kb") is None or a["kb"] < MAX_KB) and k not in best:
            best[k] = a
    return [{**best[k], "kind": k} for k, _ in KINDS if k in best][:most]


def pdf_text(data: bytes, max_pages: int = 12) -> str:
    """The text of the first pages of a PDF. A file without text (a scan) or one that will not open gives ""."""
    try:
        from pypdf import PdfReader
        pages = PdfReader(io.BytesIO(data)).pages[:max_pages]
        text = "\n".join((p.extract_text() or "") for p in pages)
    except Exception:  # noqa: BLE001 - a broken or encrypted file is simply not read
        return ""
    return text if len(re.findall(r"[A-Za-z]{3,}", text)) >= 30 else ""


def relevant(text: str, limit: int = 9000) -> str:
    """The sentences that mention figures or reasons, in document order, up to `limit` characters (each kept whole)."""
    out, size = [], 0
    for para in re.split(r"\n\s*\n", text):
        flat = re.sub(r"\s+", " ", para.replace("-\n", "")).strip()
        for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“])", flat):
            if len(sent) > 25 and TOPIC.search(sent):
                if size + len(sent) + 1 > limit:
                    return "\n".join(out)
                out.append(sent)
                size += len(sent) + 1
    return "\n".join(out)


def source_of(quote: str, docs: list[dict]) -> dict | None:
    """The document (of those with a "text") that holds this quote, or None."""
    q = norm(quote)
    return next((d for d in docs if q in norm(d.get("text", ""))), None)


def html_title(page: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    return " ".join(htmllib.unescape(m.group(1)).split()) if m else ""


def html_text(page: str) -> str:
    """The readable text of a web page, one paragraph, heading or list item per line: no scripts, styles, menus or forms, a line seen twice kept once,
    a line of fewer than four words dropped (menus, buttons). Block tags end a line, so a sentence is never joined to the next paragraph."""
    page = re.sub(r"(?is)<(script|style|noscript|nav|svg|select|button)\b[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"\s+", " ", re.sub(r"(?is)<!--.*?-->", " ", page))             # the page's own line breaks are only wrapping
    page = re.sub(r"(?i)</?(p|div|li|ul|ol|tr|br|h[1-6]|table|section|article|dt|dd|blockquote)\b[^>]*>", "\n", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    out, seen = [], set()
    for line in htmllib.unescape(page).replace("\xa0", " ").splitlines():
        flat = " ".join(line.split())
        if len(flat.split()) >= 4 and flat not in seen:
            seen.add(flat)
            out.append(flat)
    return "\n".join(out)
