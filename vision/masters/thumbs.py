"""Hooks and titles for Mani Market Tamil's long videos: a 2-5 word Tanglish line picked by code from the video's own figures (the thumbnail's big type and the title).

A hook states what the filed figures show (a result's profit up, down or the same; an analysis's ROE as a question; a lesson's subject as a question) and never promises
or advises: every hook and title goes through `clean` (market.ADVICE, market.FORECAST, youtube.promises, the length). The thumbnail itself is drawn by slides.thumbnail.
"""

from __future__ import annotations

import re

from . import market, youtube
from ..services import nse

STOP = {"what", "how", "why", "is", "are", "a", "an", "the", "your", "do", "does", "can", "should", "to", "of", "in", "for", "and", "vs"}
LABEL = {"roe": "ROE", "roce": "ROCE", "npm": "Net margin", "opm": "Operating margin", "de": "Debt-equity", "roa": "ROA", "bv": "Book value", "ttm_revenue": "Revenue"}
TOP = {"bank": "nii", "lender": "lnii", "life": "premium", "general": "gwp"}          # the headline figure when there is no profit row
NAME = {"profit": "Profit", "revenue": "Revenue", "nii": "NII", "lnii": "NII", "premium": "Premium", "gwp": "Premium"}
ORDER = ("roe", "roce", "npm", "roa", "de", "bv")                                    # which ratio an analysis hook is about, first found wins


def clean(text: str, limit: int = 100) -> str:
    """The text if it is safe to publish as a hook or title (no advice, no forecast, no promise of earning, short enough), else ""."""
    t = " ".join(text.split())
    bad = market.ADVICE.search(t) or market.FORECAST.search(t) or market.RUDE.search(t) or youtube.promises(t)
    return "" if bad or not t or len(t) > limit else t


def pct(size: float) -> str:
    """A change as the hook says it: 15 for 15.2, 4.7 for 4.7."""
    s = abs(size)
    return str(round(s)) if s >= 10 else f"{s:.1f}".rstrip("0").rstrip(".")


def result_hook(result: dict) -> tuple[str, str]:
    """(hook, tone) for a quarterly result, from the year-on-year change of its profit, else of its headline figure. ("", "flat") when the filing gave no comparison."""
    rows = {r["key"]: r for r in result.get("rows") or []}
    for key in ("profit", TOP.get(nse.shape(result), "revenue")):
        row = rows.get(key)
        c = market.change(row) if row else None
        if not c:
            continue
        name = NAME.get(key, "Revenue")
        if c["way"] > 0:
            return clean(f"{name} {pct(c['size'])}% ஏறிருக்கு!"), "good"
        if c["way"] < 0:
            return clean(f"{name} {pct(c['size'])}% இறங்கிருக்கு"), "bad"
        return clean(f"{name} அதே அளவு"), "flat"
    return "", "flat"


def margin_question(result: dict) -> str:
    """", Margin ஏன் இறங்குச்சு?" when profit rose while the operating margin fell: a question about a figure the filing shows, nothing more."""
    rows = {r["key"]: r for r in result.get("rows") or []}
    p, m = (market.change(rows[k]) if k in rows else None for k in ("profit", "opm"))
    return ", Margin ஏன் இறங்குச்சு?" if p and m and p["way"] > 0 and m["way"] < 0 else ""


def result_title(result: dict) -> str:
    """"TCS Q2 FY27 Results | Profit 15% ஏறிருக்கு, Margin ஏன் இறங்குச்சு? | தமிழில்"; "" when there is no hook or the line is not clean (the caller keeps its own title)."""
    hook = result_hook(result)[0].rstrip("!")
    for ask in dict.fromkeys((margin_question(result), "")):                          # too long with the question: without it
        if hook and (t := clean(f"{market.short(result['name'])} {result['quarter']} Results | {hook}{ask} | தமிழில்")):
            return t
    return ""


def analysis_hook(rows: list[dict]) -> tuple[str, str]:
    """"ROE 18.2% எப்படி?" from the first of the main ratios the analysis has: the figure as filed, asked as a question, never judged."""
    have = {r["key"]: r for r in rows or []}
    for key in ORDER:
        r = have.get(key)
        if r and r.get("value") is not None:
            v = f"{r['value']:.1f}".rstrip("0").rstrip(".")
            return clean(f"{LABEL.get(key, r.get('label', key))} {v}{'%' if r.get('unit') == 'pct' else 'x' if r.get('unit') == 'x' else ''} எப்படி?"), "flat"
    return "", "flat"


def analysis_title(f: dict, rows: list[dict]) -> str:
    hook, _ = analysis_hook(rows)
    return clean(f"{market.short(f['name'])} Fundamental Analysis | {hook} | தமிழில்") if hook else ""


def initials(part: str) -> str:
    """"Fixed deposit" -> "FD"; one word stays as it is."""
    w = part.split()
    return "".join(x[0].upper() for x in w) if 1 < len(w) <= 3 else part.strip()


def lesson_hook(title: str) -> tuple[str, str]:
    """"FD vs RD: எது?" for "Fixed deposit vs recurring deposit"; otherwise the subject's first three words and "தெரியுமா?"."""
    if " vs " in title.lower():
        a, b = re.split(r"\s+vs\.?\s+", title, maxsplit=1, flags=re.I)
        b = re.split(r"[?:,]", b)[0]
        hook = f"{initials(a)} vs {initials(b)}: எது?"
        return clean(hook if len(hook.split()) <= 5 else f"{a.split()[0].capitalize()} vs {b.split()[0].capitalize()}: எது?"), "flat"      # "Old vs New: எது?"
    subject = [w for w in re.sub(r"[?:,.].*$", "", title).split() if w.lower() not in STOP][:3]
    return clean(f"{' '.join(subject).capitalize()}: தெரியுமா?") if subject else "", "flat"


def hook_for(job: dict) -> tuple[str, str]:
    """(hook, tone) for a long video's job: a result, an analysis or a lesson."""
    kind = job.get("kind", "result")
    if kind == "analysis":
        return analysis_hook(job.get("ratios") or [])
    if kind == "lesson":
        return lesson_hook((job.get("tp") or {}).get("title") or job.get("title") or "")
    return result_hook(job.get("result") or {})
