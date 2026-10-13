"""The check a reworded resume or a cover letter must pass before it goes into a package: everything it states has to be in
the resume Mani wrote. Plain comparison, no model. A reworded resume that fails goes in as written instead.
"""

from __future__ import annotations

import re

from .job_match import skills_in


def _headings(md: str) -> set[str]:
    return {re.sub(r"[^a-z0-9]+", "", h.lower()) for h in re.findall(r"^#{2,3}\s+(.+)$", md, re.M)} - {""}


def _numbers(text: str) -> set[str]:
    text = re.sub(r"^\s*\d+[.)]\s", "", text, flags=re.M)          # list numbering is not a claim
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*", text)}


def _names(text: str) -> set[str]:
    """Capitalised words that are not simply the first word of a line or sentence: names of tools, firms, places."""
    out = set()
    for line in text.splitlines():
        for sentence in re.split(r"[.!?:;]\s+", re.sub(r"^[\s#>*\-•\d.)]+", "", line.replace("**", ""))):
            for w in sentence.split()[1:]:
                w = re.sub(r"'s$|’s$", "", w.strip(".,;:()[]\"'’“”|/"))
                if re.match(r"[A-Z][A-Za-z0-9+#]{2,}$", w):
                    out.add(w)
    return out


def unsupported(source: str, out: str, structure: bool = True, numbers: bool = True, names: bool = True) -> list[str]:
    """What `out` states that `source` does not back, as short notes; empty = nothing found. `structure` also holds every
    section, role, degree and project heading in place (none dropped, none added)."""
    notes = []
    if structure:
        had, got = _headings(source), _headings(out)
        if had - got:
            notes.append(f"drops {len(had - got)} heading(s) of the original")
        if got - had:
            notes.append(f"adds {len(got - had)} heading(s)")
    extra = [s for s in skills_in(out) if s not in skills_in(source)]
    notes += [f"names {s}, which the resume doesn't" for s in extra[:4]]
    if numbers:
        notes += [f"gives the number {n}, which the resume doesn't" for n in sorted(_numbers(out) - _numbers(source))[:4]]
    if names:
        words = set(re.findall(r"[a-z0-9+#]+", source.lower()))
        new = sorted(w for w in _names(out) if not set(re.findall(r"[a-z0-9+#]+", w.lower())) <= words)
        notes += [f"names {w}, which the resume doesn't" for w in new[:4] if w.lower() not in (s.lower() for s in extra)]
    return notes
