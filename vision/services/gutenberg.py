"""Public-domain story collections from Project Gutenberg, split into single stories.

A book is fetched once as plain text (https://www.gutenberg.org/cache/epub/<id>/pg<id>.txt), its licence header and
footer are removed, and it is cut at its story headings. Each story is saved as a text file with the book's title and
author, so a retelling can cite it. Public domain in the United States; nothing newer is fetched.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from ..config import ROOT

DIR = ROOT / "data" / "classics"
UA = {"User-Agent": "vision-assistant/1.0 (personal)"}
SKIP = re.compile(r"^(contents|preface|introduction|foreword|notes?|index|appendix|glossary|illustrations|dedication|transcriber|the end|"
                  r"footnotes?|epilogue|prologue|.* impression$|.* edition$|part [ivxlc\d]+|book [ivxlc\d]+|chapter [ivxlc\d]+|[ivxlc]+\.?$|\d+\.?$)", re.I)


def page(book_id: int) -> str:
    return f"https://www.gutenberg.org/ebooks/{book_id}"


def body(text: str) -> tuple[dict, str]:
    """({title, author}, the book without Project Gutenberg's own header and footer)."""
    text = text.replace("\r\n", "\n").lstrip("﻿")
    meta = {k: (re.search(rf"^{k}:\s*(.+)$", text[:6000], re.M) or [None, ""])[1].strip() for k in ("Title", "Author")}
    a = re.search(r"\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", text, re.S)
    z = re.search(r"\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", text)
    return {"title": meta["Title"], "author": re.sub(r"^(graf|count|sir)\s+", "", meta["Author"], flags=re.I)}, text[a.end() if a else 0:z.start() if z else len(text)]


def heading(line: str) -> bool:
    """A story title set on its own line in capitals, as these collections print them."""
    t = line.strip()
    letters = re.sub(r"[^A-Za-z]", "", t)
    return 3 <= len(letters) and len(t) <= 70 and t == t.upper() and not t.endswith((",", ";")) and not SKIP.match(t)


def stories(text: str, min_words: int = 350, max_words: int = 7000) -> list[dict]:
    """[{title, text}] for every piece under a capitalised heading that is long enough to be a story and short enough to retell."""
    lines = text.split("\n")
    marks = [i for i, ln in enumerate(lines) if heading(ln) and (i == 0 or not lines[i - 1].strip()) and (i + 1 >= len(lines) or not lines[i + 1].strip())]
    out, seen = [], set()
    for n, i in enumerate(marks):
        chunk = "\n".join(lines[i + 1:marks[n + 1] if n + 1 < len(marks) else len(lines)]).strip()
        title = re.sub(r"[^\W\d_]+(?:['’][^\W\d_]+)?", lambda m: m.group(0).capitalize(), " ".join(lines[i].split()).strip(" ."))
        if min_words <= len(chunk.split()) <= max_words and title.lower() not in seen:
            seen.add(title.lower())
            out.append({"title": title, "text": re.sub(r"\n{3,}", "\n\n", chunk)})
    return out


async def shelve(book_id: int, client: httpx.AsyncClient | None = None) -> list[dict]:
    """Fetch a book once and save its stories under data/classics/<id>/. Returns [{n, title, book, author, words}]."""
    folder = DIR / str(book_id)
    index = folder / "index.json"
    if index.exists():
        return json.loads(index.read_text())
    async with (client or httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True)) as c:
        r = await c.get(f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt", headers=UA)
    if r.status_code != 200:
        raise RuntimeError(f"Project Gutenberg said {r.status_code} for book {book_id}")
    meta, text = body(r.content.decode("utf-8", errors="ignore"))
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, s in enumerate(stories(text)):
        (folder / f"{n:03d}.txt").write_text(s["text"], encoding="utf-8")
        rows.append({"n": n, "title": s["title"], "book": meta["title"], "author": meta["author"], "words": len(s["text"].split())})
    index.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    return rows


def read(book_id: int, n: int) -> str:
    return (DIR / str(book_id) / f"{n:03d}.txt").read_text(encoding="utf-8")
