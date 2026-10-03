"""Quality gate for generated demo websites (static checks, stdlib + Pillow only).

check_site(html, site_dir=..., lead=..., copy=..., theme=...) -> {"ok", "score", "issues"}
Checks rely on HTML semantics and generic CSS properties, not on any template's class names.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

# ----------------------------------------------------------------------------- HTML tree

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
OPTIONAL_END = {"p", "li", "tr", "td", "th", "tbody", "thead", "tfoot", "option", "dt", "dd", "html", "body", "head"}
BLOCKS = {"div", "section", "main", "header", "footer", "nav", "article", "aside", "ul", "ol", "table", "form",
          "a", "button", "figure", "blockquote"}
CLOSES_P = {"div", "section", "ul", "ol", "table", "form", "header", "footer", "nav", "main", "article", "aside",
            "blockquote", "p", "h1", "h2", "h3", "h4", "h5", "h6", "figure"}
HIDDEN_TAGS = {"script", "style", "noscript", "template", "head", "title"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
MEDIA_TAGS = {"img", "picture", "video", "iframe", "canvas", "svg"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    def classes(self):
        return (self.attrs.get("class") or "").split()

    def text(self) -> str:
        if self.tag in HIDDEN_TAGS:
            return ""
        out = []
        for c in self.children:
            out.append(c if isinstance(c, str) else c.text())
        return " ".join(" ".join(out).split())

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

    def has_media(self) -> bool:
        return any(n.tag in MEDIA_TAGS for n in self.walk())

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.stack = [self.root]
        self.problems: list[str] = []

    def _top(self):
        return self.stack[-1]

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag in CLOSES_P and self._top().tag == "p":
            self.stack.pop()
        if tag == "li" and self._top().tag == "li":
            self.stack.pop()
        if tag == "tr":
            while self._top().tag in ("td", "th", "tr"):
                self.stack.pop()
        if tag in ("td", "th"):
            while self._top().tag in ("td", "th"):
                self.stack.pop()
        n = Node(tag, a, self._top())
        self._top().children.append(n)
        if tag not in VOID:
            self.stack.append(n)
            if tag in ("script", "style"):
                self.set_cdata_mode(tag)

    def handle_startendtag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        self._top().children.append(Node(tag, a, self._top()))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        idx = None
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                idx = i
                break
        if idx is None:
            if tag in BLOCKS:
                self.problems.append(f"stray </{tag}>")
            return
        for n in self.stack[idx + 1:]:
            if n.tag in BLOCKS:
                self.problems.append(f"<{n.tag}> not closed before </{tag}>")
        del self.stack[idx:]

    def handle_data(self, data):
        self._top().children.append(data)

    def close(self):
        super().close()
        for n in self.stack[1:]:
            if n.tag in BLOCKS:
                self.problems.append(f"<{n.tag}> never closed")


def _parse(html: str):
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root, b.problems


# ----------------------------------------------------------------------------- CSS helpers

def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def iter_rules(css: str):
    """Yield (context, selector, body). context = tuple of at-rule headers enclosing the rule."""
    css = _strip_comments(css)
    out = []

    def block_end(i):
        depth = 0
        while i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return len(css) - 1

    def scan(s, e, ctx):
        i = s
        while i < e:
            j = css.find("{", i, e)
            if j < 0:
                return
            header = css[i:j].strip()
            k = block_end(j)
            inner = css[j + 1:k]
            if header.startswith("@"):
                name = header.split()[0].lower() if header.split() else ""
                if name in ("@media", "@supports", "@layer", "@container", "@scope"):
                    scan(j + 1, k, ctx + (header,))
            else:
                out.append((ctx, header, inner))
            i = k + 1

    scan(0, len(css), ())
    return out


def decls(body: str) -> list[tuple[str, str]]:
    res = []
    for piece in body.split(";"):
        if ":" in piece:
            k, v = piece.split(":", 1)
            k = k.strip().lower()
            if k:
                res.append((k, v.strip()))
    return res


NAMED = {"white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "gray": (128, 128, 128),
         "grey": (128, 128, 128)}


def _split_args(s: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return parts


def parse_color(v: str | None, vars_: dict, depth: int = 0):
    if not v or depth > 8:
        return None
    v = v.strip().rstrip(";").replace("!important", "").strip()
    low = v.lower()
    m = re.fullmatch(r"#([0-9a-f]{3,8})", low)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        if len(h) in (6, 8):
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        return None
    if low in NAMED:
        return NAMED[low]
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)\s*(?:[,/]\s*[\d.%]+\s*)?\)", low)
    if m:
        return tuple(min(255, int(float(x))) for x in m.groups())
    m = re.fullmatch(r"var\((--[\w-]+)\s*(?:,(.*))?\)", v, flags=re.S)
    if m:
        if m.group(1) in vars_:
            return parse_color(vars_[m.group(1)], vars_, depth + 1)
        return parse_color(m.group(2), vars_, depth + 1) if m.group(2) else None
    m = re.fullmatch(r"color-mix\(\s*in\s+\w+\s*,(.*)\)", v, flags=re.S | re.I)
    if m:
        args = _split_args(m.group(1))
        if len(args) == 2:
            def one(a):
                pm = re.search(r"([\d.]+)%\s*$", a)
                pct = float(pm.group(1)) if pm else None
                col = parse_color(re.sub(r"\s*[\d.]+%\s*$", "", a), vars_, depth + 1)
                return col, pct
            (c1, p1), (c2, p2) = one(args[0]), one(args[1])
            if c1 and c2:
                if p1 is None and p2 is None:
                    p1 = p2 = 50.0
                elif p1 is None:
                    p1 = 100 - p2
                elif p2 is None:
                    p2 = 100 - p1
                tot = (p1 + p2) or 1
                return tuple(round((a * p1 + b * p2) / tot) for a, b in zip(c1, c2))
    return None


def _lum(c):
    def f(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = c
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ----------------------------------------------------------------------------- selector matching

GATE_RE = re.compile(r"(?:^|[\s>+~])(?:html|body)?\.(?:js|has-js|is-js|js-[\w-]+|reveal-on[\w-]*|jsenabled)(?![\w-])|\[data-js")
STATE_RE = re.compile(r"::|:(?:hover|focus|focus-within|focus-visible|active|checked|target|disabled|visited)")
SKIP_CLASSES = {"sr-only", "visually-hidden", "skip", "skip-link", "honeypot", "hp", "lightbox", "modal", "tooltip",
                "preloader", "screen-reader-text"}


def _compound(sel: str):
    sel = re.sub(r":not\([^)]*\)", "", sel)
    sel = re.sub(r":[\w-]+(\([^)]*\))?", "", sel)
    sel = re.sub(r"\[[^\]]*\]", "", sel)
    parts = re.split(r"\s*[>+~]\s*|\s+", sel.strip())
    last = parts[-1] if parts else ""
    tag = re.match(r"^[a-zA-Z][\w-]*", last)
    return (tag.group(0).lower() if tag else None,
            re.findall(r"\.([\w-]+)", last), re.findall(r"#([\w-]+)", last))


def _matches(node: Node, tag, classes, ids) -> bool:
    if tag is None and not classes and not ids:
        return False
    if tag and node.tag != tag:
        return False
    nc = set(node.classes())
    if any(c not in nc for c in classes):
        return False
    if ids and node.attrs.get("id") not in ids:
        return False
    return True


# ----------------------------------------------------------------------------- the checks

def _issue(issues, id_, severity, message, where=""):
    issues.append({"id": id_, "severity": severity, "message": message, "where": where})


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").lower()
    return " ".join(s.split())


def _lead_text(lead) -> str:
    try:
        return _norm(json.dumps(lead or {}, ensure_ascii=False, default=str))
    except Exception:
        return ""


RISKY = [
    (r"award[- ]winning", "award-winning"), (r"(?<![\w])#1(?![\w])", "#1"), (r"\bbest in\b", "best in"),
    (r"licen[sc]ed (?:and|&) insured", "licensed and insured"), (r"\byears of experience\b", "years of experience"),
    (r"\bsince (?:19|20)\d\d\b", "since YEAR"), (r"\bguarantee[ds]?\b", "guarantee"), (r"\bcertified\b", "certified"),
    (r"\$\s?\d[\d,]*(?:\.\d\d)?", "price figure"),
]


def check_site(html: str, *, site_dir: Path | None = None, lead: dict | None = None,
               copy: dict | None = None, theme: dict | None = None) -> dict:
    issues: list[dict] = []
    html = html or ""
    try:
        root, problems = _parse(html)
    except Exception as e:  # pragma: no cover
        _issue(issues, "parse-error", "fail", "The page could not be parsed as HTML.", str(e)[:80])
        return _result(issues)
    site_dir = Path(site_dir) if site_dir else None
    nodes = list(root.walk())
    by_tag: dict[str, list[Node]] = {}
    for n in nodes:
        by_tag.setdefault(n.tag, []).append(n)

    def tags(t):
        return by_tag.get(t, [])

    body = (tags("body") or [root])[0]
    vis_text = body.text()
    html_el = (tags("html") or [None])[0]

    # --- 1. structure
    if problems:
        _issue(issues, "unbalanced-tags", "fail", "Some block tags are unclosed or mismatched, so the layout may break.",
               "; ".join(problems[:3]))
    h1s = tags("h1")
    if len(h1s) != 1:
        _issue(issues, "one-h1", "fail", f"The page has {len(h1s)} main headings (h1) but needs exactly one.", f"{len(h1s)} h1")
    title = " ".join((tags("title")[0].text() if tags("title") else "").split())
    if not title and tags("title"):
        title = " ".join("".join(c for c in tags("title")[0].children if isinstance(c, str)).split())
    if not title:
        _issue(issues, "missing-title", "fail", "The page has no title.", "<title>")
    desc = next((m.attrs.get("content", "").strip() for m in tags("meta")
                 if (m.attrs.get("name") or "").lower() == "description"), "")
    if not desc:
        _issue(issues, "missing-description", "fail", "The meta description is missing or empty.", "meta description")
    if not (html_el and html_el.attrs.get("lang", "").strip()):
        _issue(issues, "missing-lang", "warn", "The html element has no lang attribute.", "<html>")
    if not any((m.attrs.get("name") or "").lower() == "viewport" for m in tags("meta")):
        _issue(issues, "missing-viewport", "fail", "The viewport meta tag is missing, so phones will show a zoomed-out page.", "<head>")
    prev = 0
    for h in (n for n in nodes if n.tag in HEADINGS):
        lvl = int(h.tag[1])
        if prev and lvl - prev > 1:
            _issue(issues, "heading-skip", "warn", f"Heading levels jump from h{prev} to h{lvl}.", h.text()[:40])
            break
        prev = lvl
    for s in tags("section"):
        if len(s.text()) < 15 and not s.has_media():
            _issue(issues, "empty-section", "fail", "A section has almost no text and no image, so it renders as an empty block.",
                   (s.attrs.get("id") or " ".join(s.classes()) or "section")[:40])

    # --- 2. content honesty
    no_code = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    attr_text = " ".join([title, desc] + [i.attrs.get("alt", "") for i in tags("img")])
    scan = vis_text + " " + attr_text
    hrefs = " ".join(a.attrs.get("href", "") for a in tags("a"))
    found = []

    def hit(pattern, label, text=scan, flags=0):
        m = re.search(pattern, text, flags)
        if m:
            found.append(label)

    hit(r"lorem ipsum", "lorem ipsum", flags=re.I)
    if "{{" in no_code or "}}" in no_code:
        found.append("{{ }}")
    hit(r"\bundefined\b", "undefined", flags=re.I)
    hit(r"(?<![\w'])None(?![\w'])(?!\s+(?:of|at|needed|required|found))", "None")
    hit(r"\bnull\b", "null")
    hit(r"\[object Object\]", "[object Object]")
    hit(r"\bTODO\b", "TODO")
    hit(r"\bplaceholder\b", "placeholder", text=vis_text, flags=re.I)
    hit(r"your business", "Your Business", flags=re.I)
    if "example.com" in (scan + " " + hrefs).lower():
        found.append("example.com")
    hit(r"\{\s*'[^']*'\s*:", "python dict repr")
    hit(r"\[\s*'[^']*'\s*[,\]]", "python list repr")
    if "\\n" in scan or "\\u00" in scan:
        found.append("literal \\n")
    hit(r"(?<!\.)\.\.(?!\.)|,,|;;|::|,\.|\.,|, ,", "doubled punctuation")   # "!!" and "??" are left alone: real customer reviews use them
    for ph in found:
        _issue(issues, "placeholder-text", "fail", f"The page contains leftover or placeholder text ({ph}).", ph)
    if "```" in scan or re.search(r"\*\*[^*\s][^*]*\*\*", vis_text) or re.search(r"(?m)^\s*#{1,4}\s+\w", vis_text) \
            or any(re.match(r"\s*json\s*[\{\[]", t) for n in nodes if n.tag not in HIDDEN_TAGS
                   for t in n.children if isinstance(t, str)):
        _issue(issues, "markdown-artifact", "fail", "The text contains unprocessed model output such as markdown or a json label.", "visible text")
    name = (lead or {}).get("name") if lead else None
    if name:
        n1 = _norm(str(name))
        pg = _norm(vis_text + " " + title)
        alnum = lambda s: re.sub(r"[^a-z0-9]", "", s)
        if n1 not in pg and alnum(n1) not in alnum(pg):
            _issue(issues, "business-name-missing", "fail", "The business name does not appear anywhere on the page.", str(name)[:60])
    seen: dict[str, str] = {}
    dup_reported = set()
    for h in (n for n in nodes if n.tag in HEADINGS):
        t = _norm(h.text())
        if not t:
            continue
        if t in seen and t not in dup_reported:
            dup_reported.add(t)
            _issue(issues, "duplicate-headings", "fail", "Two headings on the page have identical text.", t[:50])
        seen.setdefault(t, h.tag)
    hay = _lead_text(lead)
    vt = vis_text
    for pat, label in RISKY:
        for m in re.finditer(pat, vt, flags=re.I):
            phrase = m.group(0)
            if _norm(phrase) in hay:
                continue
            _issue(issues, "risky-claim", "warn", f'The page makes an unverified claim ("{phrase}") that is not in the business data.', phrase)
            break
    for p in tags("p"):
        if len(p.text().split()) > 90:
            _issue(issues, "long-paragraph", "warn", "A paragraph is longer than about 90 words.", p.text()[:40])
            break
    if h1s and len(h1s[0].text().split()) > 9:
        _issue(issues, "long-headline", "warn", "The main headline is longer than about 9 words.", h1s[0].text()[:50])

    # --- 3. contact and conversion
    phone = (lead or {}).get("phone") if lead else None
    if phone and _digits(phone):
        want = _digits(phone)[-10:]
        if not any(_digits(a.attrs.get("href", ""))[-10:] == want for a in tags("a")
                   if (a.attrs.get("href") or "").lower().startswith("tel:")):
            _issue(issues, "missing-tel", "fail", "There is no tel: link matching the business phone number.", str(phone))
    maps_ok = any(re.search(r"google\.[a-z.]+/maps|maps\.app\.goo\.gl|goo\.gl/maps|maps\.apple|openstreetmap|/dir/|directions",
                            (a.attrs.get("href") or ""), re.I) for a in tags("a")) or \
        any(re.search(r"maps|openstreetmap", i.attrs.get("src", ""), re.I) for i in tags("iframe"))
    if not maps_ok:
        _issue(issues, "missing-directions", "warn", "There is no directions link or map embed.", "map")
    if not re.search(r"demo site prepared for.{0,200}?not yet the business'?s official website", _norm(vis_text), re.S):
        _issue(issues, "missing-disclaimer", "fail", "The required demo disclaimer text is missing.", "footer")
    imgs = tags("img")
    if imgs and not re.search(r"\b(photos?|images?)\s*(?:by|:|credit)|photo credit|credits?:", vis_text, re.I):
        _issue(issues, "missing-credits", "warn", "Photos are used but no photo credit is shown.", "footer")

    # --- 4. images
    first_img = imgs[0] if imgs else None
    uses: dict[str, int] = {}
    local_bytes = 0
    for im in imgs:
        src = (im.attrs.get("src") or "").strip()
        if "alt" not in im.attrs:
            _issue(issues, "img-no-alt", "fail", "An image has no alt attribute.", src[:60])
        if not src:
            _issue(issues, "img-no-src", "fail", "An image has no src.", "<img>")
            continue
        uses[src] = uses.get(src, 0) + 1
        if re.match(r"^(https?:)?//|^data:", src, re.I) or site_dir is None:
            continue
        try:
            path = (site_dir / src.split("?")[0].split("#")[0].lstrip("/")).resolve()
            path.relative_to(site_dir.resolve())
        except Exception:
            _issue(issues, "img-missing", "fail", "An image points outside the site folder.", src[:60])
            continue
        if not path.is_file():
            _issue(issues, "img-missing", "fail", "An image file referenced by the page does not exist.", src[:60])
            continue
        local_bytes += path.stat().st_size
        try:
            from PIL import Image
            with Image.open(path) as pic:
                pic.verify()
            with Image.open(path) as pic:
                w, h = pic.size
        except Exception:
            _issue(issues, "img-corrupt", "fail", "An image file is corrupt and cannot be opened.", src[:60])
            continue
        hero = im is first_img or any("hero" in c.lower() for a in [im, *im.ancestors()] for c in a.classes())
        if w < (600 if hero else 300):
            _issue(issues, "img-tiny", "warn", f"An image is only {w}px wide, which will look blurry.", src[:60])
    for src, n in uses.items():
        if n > 2:
            _issue(issues, "img-duplicate", "warn", f"The same image is used {n} times.", src[:60])
    for n in nodes:
        hint = " ".join(n.classes() + [n.attrs.get("id", ""), n.attrs.get("aria-label", "")]).lower()
        if "gallery" in hint and n.tag in ("div", "section", "ul", "figure", "ol") \
                and not any(x.tag in ("img", "picture") for x in n.walk()) \
                and "background-image" not in (n.attrs.get("style", "") + "".join(c.attrs.get("style", "") for c in n.walk())):
            _issue(issues, "gallery-empty", "warn", "A gallery container holds no images, so it will show empty cells.", hint[:40])
            break
    if local_bytes > 3 * 1024 * 1024:
        _issue(issues, "images-heavy", "warn", f"Local images total {local_bytes // 1024 // 1024} MB, which loads slowly on mobile.", "images")

    # --- CSS gathering
    css = "\n".join("".join(c for c in s.children if isinstance(c, str)) for s in tags("style"))
    rules = iter_rules(css)
    vars_: dict[str, str] = {}
    for ctx, sel, bd in rules:
        if not ctx and any(s.strip() in (":root", "html", "body", "*") for s in sel.split(",")):
            for k, v in decls(bd):
                if k.startswith("--"):
                    vars_[k] = v

    # --- 5. contrast
    def var_color(names):
        for nm in names:
            for key in (f"--{nm}",):
                if key in vars_:
                    c = parse_color(vars_[key], vars_)
                    if c:
                        return c, key
        return None, None

    ROLE = {"text": ["text", "t", "fg", "ink", "foreground", "color-text", "text-color"],
            "bg": ["bg", "background", "bg-color", "page-bg", "color-bg"],
            "surface": ["surface", "card", "soft", "bg-alt"],
            "muted": ["muted", "text-muted", "subtle"],
            "primary": ["p", "primary", "brand", "color-primary"],
            "accent": ["a", "accent", "color-accent"],
            "on-primary": ["on-primary", "on-p", "primary-text", "primary-contrast"],
            "on-accent": ["on-accent", "on-a", "accent-text"]}
    col = {r: var_color(n) for r, n in ROLE.items()}
    reported = set()

    def pair(fg_role, bg_role, level, src=None):
        fg, fk = col[fg_role] if src is None else src[0]
        bg, bk = col[bg_role] if src is None else src[1]
        if not fg or not bg:
            return
        r = contrast(fg, bg)
        key = (fg_role, bg_role)
        if key in reported:
            return
        if level == "fail" and r < 4.5:
            reported.add(key)
            _issue(issues, "contrast-fail", "fail", f"Text colour {fg_role} on {bg_role} has contrast {r:.1f}:1, below the 4.5:1 minimum.", f"{fg_role}/{bg_role}")
        elif level == "warn" and r < 3:
            reported.add(key)
            _issue(issues, "contrast-warn", "warn", f"{fg_role} against {bg_role} has contrast {r:.1f}:1, below 3:1 for large text and controls.", f"{fg_role}/{bg_role}")

    for f, b in (("text", "bg"), ("text", "surface"), ("muted", "bg"), ("muted", "surface"),
                 ("on-primary", "primary"), ("on-accent", "accent")):
        pair(f, b, "fail")
    for f, b in (("primary", "bg"), ("accent", "bg")):
        pair(f, b, "warn")
    if theme:
        tc = {k: parse_color(str(theme.get(k, "")), {}) for k in ("primary", "accent", "bg", "text")}
        if tc["text"] and tc["bg"] and ("text", "bg") not in reported:
            r = contrast(tc["text"], tc["bg"])
            if r < 4.5:
                reported.add(("text", "bg"))
                _issue(issues, "contrast-fail", "fail", f"Theme text on background has contrast {r:.1f}:1, below the 4.5:1 minimum.", "theme text/bg")
        for k in ("primary", "accent"):
            if tc[k] and tc["bg"] and (k, "bg") not in reported and contrast(tc[k], tc["bg"]) < 3:
                reported.add((k, "bg"))
                _issue(issues, "contrast-warn", "warn", f"Theme {k} against the background has contrast {contrast(tc[k], tc['bg']):.1f}:1, below 3:1.", f"theme {k}/bg")
    nrule = 0
    for ctx, sel, bd in rules:
        if ctx or sel.startswith("@") or nrule > 400:
            continue
        d = dict(decls(bd))
        fg = parse_color(d.get("color"), vars_)
        bgc = parse_color(d.get("background-color") or d.get("background"), vars_)
        if fg and bgc and contrast(fg, bgc) < 4.5 and ("rule", sel) not in reported:
            reported.add(("rule", sel))
            _issue(issues, "contrast-rule", "warn", f"A CSS rule sets text and background colours with contrast {contrast(fg, bgc):.1f}:1.", sel[:50])
        nrule += 1

    # --- 6. mobile
    def in_min_width(ctx):
        return any("min-width" in c for c in ctx)

    def check_decls(sel, d, ctx, el_tag=None, el_classes=()):
        dd = dict(d)
        m = re.fullmatch(r"(\d+(?:\.\d+)?)px", dd.get("width", "").strip())
        if m and float(m.group(1)) > 400 and "max-width" not in dd and not in_min_width(ctx):
            _issue(issues, "fixed-width", "fail", f"An element has a fixed width of {m.group(1)}px which overflows phone screens.", sel[:50])
        if "nowrap" in dd.get("white-space", "") and not in_min_width(ctx):
            tag, classes, _ = _compound(sel) if sel else (el_tag, el_classes, [])
            textish = tag in HEADINGS or tag in ("p", "li") or any(
                re.search(r"title|headline|heading|lead|copy|body|desc|paragraph", c) for c in classes)
            if textish:
                _issue(issues, "nowrap-text", "fail", "Headings or body text are set to never wrap, which overflows on phones.", sel[:50])
        fs = dd.get("font-size", "")
        fm = re.fullmatch(r"(\d+(?:\.\d+)?)(px|rem|em)", fs.strip())
        if fm:
            px = float(fm.group(1)) * (1 if fm.group(2) == "px" else 16)
            tag, classes, _ = _compound(sel) if sel else (el_tag, el_classes, [])
            if px < 12 and (tag in ("html", "body", "p", "li", "td") or any(
                    re.search(r"body|copy|text|desc|paragraph|lead", c) for c in classes)):
                _issue(issues, "small-font", "warn", f"Body copy is set below 12px ({fs}).", sel[:50])

    for ctx, sel, bd in rules:
        check_decls(sel, decls(bd), ctx)
    for n in nodes:
        st = n.attrs.get("style")
        if st:
            check_decls("", decls(st), (), n.tag, n.classes())
    seen_long = False
    for tnode in body.walk():
        if tnode.tag in HIDDEN_TAGS:
            continue
        for t in tnode.children:
            if isinstance(t, str) and not seen_long:
                for w in t.split():
                    if len(w) > 28 and not re.search(r"://|@|www\.", w):
                        seen_long = True
                        _issue(issues, "long-word", "warn", "A very long unbroken word may overflow on small screens.", w[:40])
                        break
    for tb in tags("table"):
        cols = max((len([c for c in r.children if isinstance(c, Node) and c.tag in ("td", "th")])
                    for r in tb.walk() if r.tag == "tr"), default=0)
        par = tb.parent
        wrapped = par is not None and any(re.search(r"scroll|responsive|overflow|wrap", c) for c in par.classes()) \
            or (par is not None and "overflow" in par.attrs.get("style", ""))
        if cols > 4 and not wrapped:
            _issue(issues, "table-wide", "warn", f"A table has {cols} columns and no scroll wrapper for phones.", "table")

    # --- 7. weight and hygiene
    if len(html.encode("utf-8")) > 250 * 1024:
        _issue(issues, "html-heavy", "warn", "The HTML is larger than 250 KB.", f"{len(html) // 1024} KB")
    if len(css.encode("utf-8")) > 60 * 1024:
        _issue(issues, "css-heavy", "warn", "The inline CSS is larger than 60 KB.", f"{len(css) // 1024} KB")
    for s in tags("script"):
        if s.attrs.get("src"):
            _issue(issues, "external-script", "fail", "The page loads an external script; only inline scripts are allowed.", s.attrs["src"][:60])
    for n in nodes:
        if n.tag in ("img", "script", "source", "iframe", "video", "audio", "link"):
            for attr in ("src", "href", "srcset", "poster"):
                v = n.attrs.get(attr, "")
                if re.match(r"\s*http://", v, re.I):
                    _issue(issues, "insecure-resource", "fail", "A resource is loaded over insecure http://.", v[:60])
    if re.search(r"url\(\s*['\"]?http://", css, re.I):
        _issue(issues, "insecure-resource", "fail", "The CSS loads a resource over insecure http://.", "css url()")

    # hidden without JS
    flagged = set()
    # something hidden at one screen size and shown at another by a media query (a mobile call bar) is not hidden content
    shown_in_media = {one.strip() for ctx, sel, bd in rules if ctx for one in sel.split(",")
                      if dict(decls(bd)).get("display", "none").replace("!important", "").strip() != "none"}
    for ctx, sel, bd in rules:
        if ctx:
            continue
        d = dict(decls(bd))
        hide = None
        if re.fullmatch(r"0(\.0+)?", d.get("opacity", "").replace("!important", "").strip()):
            hide = "opacity:0"
        elif "hidden" in d.get("visibility", ""):
            hide = "visibility:hidden"
        elif d.get("display", "").replace("!important", "").strip() == "none":
            hide = "display:none"
        if not hide or (hide == "display:none" and all(one.strip() in shown_in_media for one in sel.split(","))):
            continue
        for one in sel.split(","):
            one = one.strip()
            if not one or GATE_RE.search(" " + one) or STATE_RE.search(one) or "[hidden" in one:
                continue
            tag, classes, ids = _compound(one)
            if any(c in SKIP_CLASSES for c in classes):
                continue
            need = 1 if hide == "opacity:0" else 15
            for el in nodes:
                if el.tag in HIDDEN_TAGS or el.tag in ("html", "body") and hide != "opacity:0":
                    continue
                if _matches(el, tag, classes, ids) and len(el.text()) >= need:
                    if one not in flagged:
                        flagged.add(one)
                        _issue(issues, "hidden-without-js", "fail",
                               f"Content is hidden by default ({hide}) and only appears if JavaScript runs.", one[:60])
                    break
    for el in nodes:
        st = dict(decls(el.attrs.get("style", ""))) if el.attrs.get("style") else {}
        if st and (st.get("opacity", "").strip() == "0" or "hidden" in st.get("visibility", "")) and len(el.text()) >= 1 \
                and el.tag not in HIDDEN_TAGS:
            _issue(issues, "hidden-without-js", "fail", "An element with text is hidden by an inline style.", el.tag)
            break

    return _result(issues)


def _result(issues: list[dict]) -> dict:
    fails = sum(1 for i in issues if i["severity"] == "fail")
    warns = len(issues) - fails
    return {"ok": fails == 0, "score": max(0, 100 - 20 * fails - 4 * warns), "issues": issues}


def summarize(result: dict) -> str:
    if result.get("ok"):
        return "QA passed"
    fails = [i for i in result.get("issues", []) if i["severity"] == "fail"]
    msgs = " ".join(i["message"].rstrip(".") + "." for i in fails[:2])
    return f"QA failed: {len(fails)} problems: {msgs}"


REBUILD_FIXABLE = {
    "parse-error", "unbalanced-tags", "one-h1", "missing-title", "missing-description", "missing-viewport",
    "empty-section", "contrast-fail", "fixed-width", "nowrap-text", "hidden-without-js", "external-script",
    "insecure-resource", "img-no-alt", "img-no-src", "missing-disclaimer",
}


def fixable_by_rebuild(result: dict) -> bool:
    """True when every failure is a layout/recipe problem another build could fix."""
    fails = [i["id"] for i in result.get("issues", []) if i["severity"] == "fail"]
    return bool(fails) and all(f in REBUILD_FIXABLE for f in fails)
