"""Slide videos: slides that build while the voice explains them, with a drawn presenter in the corner.

A deck is a list of slides; each slide has a title and items (drawings with a label, table rows, or cards). Every
spoken line names its slide and how many of that slide's items are on screen while it is said, so the picture
follows the voice. The slides are a web page: headless Chrome takes one picture per line (a browser shapes Tamil
letters properly, Pillow here does not), and ffmpeg wipes each new picture in from the left, which reads as being
drawn. The presenter is six small pictures (mouth closed, half, open; eyes open or shut) chosen by how loud the
voice is at that moment.

    deck  = [{"kind": "notice" | "cover" | "table" | "facts" | "quotes" | "points" | "board", "title": str, "items": [...], "cols": [...], "note": str}]
    notice: "items" = the disclaimer paragraphs, shown whole (older: "title" and "note");  board (tall Shorts): items are blocks {region, when, rows, foot}
    lines: a line may carry "hold" = the least seconds its picture stays (the disclaimer card, whose spoken line is short)
    table rows: {label, was, now, change, tone, note};  facts rows (one value, no comparison): {label, value, tone, note}
    quotes rows (up to four sentences of text, each behind a coloured chip): {label, text, tone}
    lines = [{"slide": 0, "show": 2, "say": "...", "en": "..."}]            # show = how many of the slide's items are visible; en = the English caption (optional)

A Short is the same page drawn 1080x1920 (`tall=True`): a small disclaimer line at the top, the board, the presenter lower right.

English captions (optional): each line's `en` is cut into chunks (caption_chunks), timed across that line's own audio, drawn once each as a transparent strip by
the same Chrome session (pictures(..., captions=texts)) and laid over the video by assemble(..., captions=...), which also writes the same chunks as an .srt.
"""

from __future__ import annotations

import base64
import html
import re
import subprocess
import wave
from pathlib import Path

W, H, FPS = 1920, 1080, 30
TALL = (1080, 1920)             # a Short
WIPE = 0.4                      # seconds a new thing takes to appear
FACE = 300                      # the presenter's square, bottom right
MOUTH_FPS = 12                  # how often the mouth may change; faster looks like a flicker

_S = 'stroke="#1b1b1b" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"'
_G = 'fill="none" stroke="#1f9d55" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"'
DOODLE = {
    "bank": f'<svg viewBox="0 0 200 180"><path d="M20 70 L100 20 L180 70 Z" fill="#cfe3ff" {_S}/><path d="M30 70h140v16H30z" fill="#fff" {_S}/>'
            + "".join(f'<path d="M{x} 86v56h18V86" fill="#fff" {_S}/>' for x in (44, 91, 138))
            + f'<path d="M22 142h156v20H22z" fill="#cfe3ff" {_S}/><circle cx="100" cy="50" r="9" fill="#f4b63f" {_S}/></svg>',
    "company": f'<svg viewBox="0 0 200 180"><path d="M30 164V40h80v124M110 164V78h60v86" fill="#cfe3ff" {_S}/><path d="M16 164h168" fill="none" {_S}/>'
               + "".join(f'<path d="M{x} {y}h14v14h-14z" fill="#fff7d6" {_S}/>' for x in (46, 80) for y in (58, 92, 126))
               + f'<path d="M132 98h16M132 126h16" fill="none" {_S}/></svg>',
    "paper": f'<svg viewBox="0 0 200 180"><path d="M50 14h72l32 32v120H50z" fill="#fff" {_S}/><path d="M122 14v32h32M68 70h66M68 92h66M68 114h40" fill="none" {_S}/>'
             f'<path d="M112 140l14 12 26-34" {_G}/></svg>',
    "lens": f'<svg viewBox="0 0 200 180"><circle cx="86" cy="76" r="50" fill="#fff7d6" {_S}/><path d="M124 112l48 48" stroke="#1b1b1b" stroke-width="14" stroke-linecap="round"/>'
            f'<path d="M72 62c0-22 32-20 30 0c-2 14-16 12-16 28M86 104v2" fill="none" {_S}/></svg>',
    "up": f'<svg viewBox="0 0 200 180"><path d="M24 150h152" fill="none" {_S}/><path d="M40 150v-40h26v40M86 150V84h26v66M132 150V52h26v98" fill="#bfe8cf" {_S}/>'
          f'<path d="M34 86l44-34 28 16 56-46m-28 0h28v28" {_G}/></svg>',
    "down": f'<svg viewBox="0 0 200 180"><path d="M24 150h152" fill="none" {_S}/><path d="M40 150V52h26v98M86 150V84h26v66M132 150v-40h26v40" fill="#f8cdc8" {_S}/>'
            f'<path d="M34 30l44 34 28-16 56 46m-28 0h28V66" fill="none" stroke="#d92d20" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "shield": f'<svg viewBox="0 0 200 180"><path d="M100 14l64 22v48c0 40-28 66-64 82c-36-16-64-42-64-82V36z" fill="#cfe3ff" {_S}/><path d="M70 88l22 22 40-46" {_G}/></svg>',
    "eye": f'<svg viewBox="0 0 200 180"><path d="M14 90c40-60 132-60 172 0c-40 60-132 60-172 0z" fill="#fff7d6" {_S}/><circle cx="100" cy="90" r="30" fill="#f4b63f" {_S}/>'
           f'<circle cx="100" cy="90" r="11" fill="#1b1b1b"/></svg>',
    "coin": f'<svg viewBox="0 0 200 180"><circle cx="100" cy="90" r="66" fill="#f4b63f" {_S}/><circle cx="100" cy="90" r="50" fill="#ffe08a" {_S}/>'
            f'<path d="M80 62h42M80 80h42M82 62c30 0 30 34 0 34l34 34" fill="none" {_S}/></svg>',
}

CSS = """
*{box-sizing:border-box;margin:0}
body{width:1920px;height:1080px;overflow:hidden;font-family:"Baloo Thambi 2","Mukta Malar","Tamil Sangam MN",sans-serif;color:#1b1b1b;
 background:#fbf8f1 linear-gradient(#e9e3d4 1px,transparent 1px) 0 0/100% 54px}
.slide{position:absolute;inset:0;padding:60px 110px 0;display:none}
.pill{display:inline-block;background:#14532d;color:#fff;font-size:50px;font-weight:700;padding:12px 44px;border-radius:14px;box-shadow:8px 8px 0 #f4b63f}
.tag{position:absolute;top:66px;right:110px;font:600 26px "JetBrains Mono",Menlo,monospace;color:#b42318;border:3px dashed #b42318;border-radius:10px;padding:8px 18px;transform:rotate(3deg)}
.src{position:absolute;top:76px;right:110px;font-size:28px;color:#6b6455}
.mark{position:absolute;bottom:30px;left:110px;font-size:30px;font-weight:700;color:#14532d}
.row3{display:flex;justify-content:space-around;align-items:flex-end;margin-top:70px}
.row3 svg{width:360px;display:block;margin:0 auto 10px}.row3 div{text-align:center;font-size:44px;font-weight:600}
table{width:100%;margin-top:34px;border-collapse:separate;border-spacing:0 12px;font-size:42px}
th{font-size:32px;color:#6b6455;text-align:right;padding:0 26px}th:first-child,td:first-child{text-align:left}
td{background:#fff;padding:16px 26px;text-align:right;font-family:"JetBrains Mono",Menlo,monospace;border-top:3px solid #1b1b1b;border-bottom:3px solid #1b1b1b;white-space:nowrap}
td:first-child{font-family:inherit;font-weight:700;border-left:3px solid #1b1b1b;border-radius:14px 0 0 14px}
td:last-child{font-family:inherit;font-size:34px;text-align:left;border-right:3px solid #1b1b1b;border-radius:0 14px 14px 0;white-space:normal}
table.facts td:first-child{width:46%}table.facts td.now{font-size:46px}table.facts{width:1700px}
td i{font-style:normal;font-size:26px;font-weight:400;color:#6b6455;margin-left:10px}
td.now{font-weight:700}.good{color:#1f9d55}.bad{color:#d92d20}.flat{color:#6b6455}
.cards{display:flex;gap:44px;margin-top:60px}
.card{flex:1;color:#1b1b1b;background:#fff;border:4px solid #1b1b1b;border-radius:20px;padding:26px;text-align:center;font-size:42px;font-weight:700;box-shadow:10px 10px 0 #1f9d55}
.card.bad{box-shadow:10px 10px 0 #d92d20}.card.flat{box-shadow:10px 10px 0 #f4b63f}.card svg{width:230px;display:block;margin:0 auto 10px}
.notice{margin:210px auto 0;width:1300px;background:#fff;border:5px solid #1b1b1b;border-radius:24px;padding:60px 70px;text-align:center;font-size:44px;box-shadow:12px 12px 0 #f4b63f}
.notice b{display:block;font-size:64px;margin-bottom:26px;color:#14532d}
.quotes{display:flex;flex-direction:column;gap:14px;width:1420px;margin-top:30px}
.q{display:flex;align-items:center;gap:26px;background:#fff;border:3px solid #1b1b1b;border-radius:16px;padding:12px 22px;font-size:33px;line-height:1.2}
.q span{color:#1b1b1b}.q b{flex:none;width:260px;font-size:26px;line-height:1.2;color:#fff;background:#1f9d55;border-radius:10px;padding:12px 14px;text-align:center}
.q.bad b{background:#d92d20}.q.flat b{background:#6b6455}
.note{margin:44px 340px 0 0;font-size:34px;color:#6b6455}
.disc{margin:80px auto 0;width:1580px;padding:46px 64px;text-align:left;font-size:34px;line-height:1.5}
.disc p+p{margin-top:28px}.disc b{display:inline;font-size:inherit;margin:0;color:#14532d}
"""

# a Short: 1080x1920. Text stays out of YouTube's own controls (bottom 280 px, right 120 px) and above the presenter, who takes the lower right corner.
TALL_CSS = """
body{width:1080px;height:1920px}
.top{position:absolute;top:14px;left:44px;right:44px;text-align:center;font:400 25px/1.25 "Nunito Sans","Helvetica Neue",Arial,sans-serif;color:#000}
.slide{padding:104px 0 0 60px}.mark{left:60px}
.board{display:flex;flex-direction:column;gap:20px;margin:30px 120px 0 0}
.blk{background:#fff;border:4px solid #1b1b1b;border-radius:20px;padding:12px 28px 8px;box-shadow:8px 8px 0 #f4b63f}
.blk h3{display:flex;justify-content:space-between;align-items:baseline;font-size:36px;color:#14532d;padding-bottom:4px}
.blk h3 i{font:500 24px "JetBrains Mono",Menlo,monospace;color:#6b6455}
.r{display:grid;grid-template-columns:1fr auto 210px;align-items:baseline;gap:16px;padding:7px 0;border-top:2px dashed #d8d1bf;font-size:38px;font-weight:700}
.r i{font:500 30px "JetBrains Mono",Menlo,monospace;color:#6b6455}.r span{font-family:"JetBrains Mono",Menlo,monospace;text-align:right}
.r.big{font-size:54px;padding:12px 0;grid-template-columns:1fr auto 320px}.r.big i{font-size:40px}.r span{white-space:nowrap}
.foot{border-top:2px dashed #d8d1bf;padding:8px 0 4px;font:500 28px "JetBrains Mono",Menlo,monospace;color:#6b6455}
"""

# the presenter: one drawing, with three mouths and two pairs of eyes switched by class
FACE_CSS = """
*{margin:0}html,body{background:transparent;width:300px;height:300px;overflow:hidden}
.m,.e{display:none}.m0 .mouth0,.m1 .mouth1,.m2 .mouth2,.e0 .eyes0,.e1 .eyes1{display:inline}
"""
FACE_SVG = f"""<svg viewBox="0 0 300 300" width="300" height="300">
<path d="M62 300c0-66 40-92 88-92s88 26 88 92z" fill="#14532d" {_S}/><path d="M128 208l22 30 22-30" fill="#fff" {_S}/>
<path d="M134 178h32v36c-10 12-22 12-32 0z" fill="#e2a878" {_S}/>
<ellipse cx="150" cy="120" rx="62" ry="70" fill="#e9b587" {_S}/>
<path d="M88 112c-8-62 40-84 70-78c40-6 66 30 54 78c-8-34-28-44-60-44s-52 8-64 44z" fill="#1b1b1b" {_S}/>
<path d="M88 118c-12 0-12 28 2 28M212 118c12 0 12 28-2 28" fill="#e9b587" {_S}/>
<g class="e eyes0"><circle cx="126" cy="122" r="7" fill="#1b1b1b"/><circle cx="174" cy="122" r="7" fill="#1b1b1b"/></g>
<g class="e eyes1"><path d="M117 123h18M165 123h18" fill="none" {_S}/></g>
<path d="M112 104q14-9 28 0M160 104q14-9 28 0" fill="none" {_S}/><path d="M150 128v18l-8 4" fill="none" {_S}/>
<g class="m mouth0"><path d="M128 162q22 12 44 0" fill="none" {_S}/></g>
<g class="m mouth1"><path d="M130 160q20 16 40 0q-20 4-40 0z" fill="#7a1f1f" {_S}/></g>
<g class="m mouth2"><path d="M128 158q22 34 44 0q-22-6-44 0z" fill="#7a1f1f" {_S}/></g>
<path d="M6 262h288v38H6z" fill="#c69a6b" {_S}/><path d="M96 262l10-22h88l10 22" fill="#fff" {_S}/></svg>"""


# English captions: a rounded dark band with white Nunito Sans text, drawn in a transparent strip as wide as the frame (so every picture has one size and ffmpeg
# never reconfigures its graph). "top"/"height" place the strip, "x" is the band's room, "chars"/"words" the most one chunk holds. The wide video keeps them above the
# channel mark and below the slide; a Short keeps them out of YouTube's own controls (bottom 280 px, right 120 px) and above the presenter.
CAP = {False: {"x": (110, 1530), "top": 846, "height": 156, "font": 40, "chars": 60, "words": 10},
       True: {"x": (60, 960), "top": 1400, "height": 240, "font": 46, "chars": 32, "words": 6}}
GLUE = {"crore", "lakh", "points", "percent", "times"}             # a unit stays on the same chunk as the number before it
CAP_FONT = '"Nunito Sans","Helvetica Neue",Arial,sans-serif'


def run(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def probe(path: Path | str) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True, check=True).stdout.strip())


def _mix(text: str) -> str:
    """Escaped text; a part in [square brackets] becomes the small grey note beside a label."""
    out = html.escape(str(text))
    return out.replace("[", "<i>").replace("]", "</i>")


def _slide(s: dict, frame: str) -> str:
    items, kind = s.get("items") or [], s.get("kind", "points")
    if kind == "notice" and items:             # the disclaimer card: the paragraphs whole, the channel's name in bold
        paras = "".join(f"<p>{html.escape(p).replace('Mani Market Tamil', '<b>Mani Market Tamil</b>')}</p>" for p in items)
        return f'<section class="slide">{frame}<div class="notice disc" data-i="0">{paras}</div></section>'
    if kind == "notice":                                # one statement, nothing else on the slide
        return f'<section class="slide">{frame}<div class="notice" data-i="0"><b>{_mix(s["title"])}</b>{_mix(s.get("note", ""))}</div></section>'
    if kind == "board":                                 # a Short's figures: a card per region, a row per index (name, level, arrow and percent)
        rows = lambda b: "".join(f'<div class="r{" big" if r.get("big") else ""}"><b>{html.escape(r["label"])}</b><i>{html.escape(r["value"])}</i>'
                                 f'<span class="{r["tone"]}">{r["arrow"]} {html.escape(r["pct"])}</span></div>' for r in b["rows"])
        body = '<div class="board">' + "".join(f'<div class="blk" data-i="{i}"><h3>{html.escape(b["region"])}<i>{html.escape(b["when"])}</i></h3>{rows(b)}'
                                               + (f'<div class="foot">{html.escape(b["foot"])}</div>' if b.get("foot") else "") + "</div>" for i, b in enumerate(items)) + "</div>"
        return f'<section class="slide">{frame}<span class="pill">{_mix(s["title"])}</span>{body}</section>'
    if kind == "cover":
        body = '<div class="row3">' + "".join(f'<div data-i="{i}">{DOODLE.get(it.get("icon"), "")}{_mix(it["text"])}</div>' for i, it in enumerate(items)) + "</div>"
    elif kind == "table":
        head = "<tr><th></th>" + "".join(f"<th>{html.escape(c)}</th>" for c in s.get("cols") or []) + "<th></th></tr>"
        body = "<table>" + head + "".join(
            f'<tr data-i="{i}"><td>{_mix(r["label"])}</td><td>{html.escape(r["was"])}</td><td class="now">{html.escape(r["now"])}</td>'
            f'<td class="{r.get("tone", "flat")}">{html.escape(r["change"])}</td><td>{_mix(r.get("note", ""))}</td></tr>' for i, r in enumerate(items)) + "</table>"
    elif kind == "facts":                               # a ratio table: the label, one value coloured by its tone, a short note
        body = '<table class="facts"><tr><th></th>' + "".join(f"<th>{html.escape(c)}</th>" for c in s.get("cols") or []) + "<th></th></tr>" + "".join(
            f'<tr data-i="{i}"><td>{_mix(r["label"])}</td><td class="now {r.get("tone", "flat")}">{html.escape(r["value"])}</td><td>{_mix(r.get("note", ""))}</td></tr>'
            for i, r in enumerate(items)) + "</table>"
    elif kind == "quotes":                              # sentences of text behind a chip (a reason and the metric it explains, a headline and its publication)
        body = '<div class="quotes">' + "".join(f'<div class="q {r.get("tone", "flat")}" data-i="{i}"><b>{_mix(r["label"])}</b><span>{html.escape(r["text"])}</span></div>'
                                                for i, r in enumerate(items)) + "</div>"
    else:
        body = '<div class="cards">' + "".join(f'<div class="card {it.get("tone", "good")}" data-i="{i}">{DOODLE.get(it.get("icon"), "")}{_mix(it["text"])}</div>'
                                               for i, it in enumerate(items)) + "</div>"
    note = f'<div class="note" data-i="{len(items)}">{_mix(s["note"])}</div>' if s.get("note") else ""
    return f'<section class="slide">{frame}<span class="pill">{_mix(s["title"])}</span>{body}{note}</section>'


def page(deck: list[dict], channel: str = "", tag: str = "", source: str = "", tall: bool = False, top: str = "") -> str:
    """The slides as one page. `tall` draws a Short (1080x1920) with `top` as the small line across the very top, set in Nunito Sans (the font file
    from services/fonts, else a system sans)."""
    frame = ("" if tall else f'<div class="tag">{html.escape(tag)}</div>' if tag else f'<div class="src">{html.escape(source)}</div>' if source else "") \
        + f'<div class="mark">{html.escape(channel)}</div>' + (f'<div class="top">{html.escape(top)}</div>' if tall and top else "")
    face = ""
    if tall:
        from ..services import fonts
        f = fonts.path("Nunito Sans")
        face = (f'@font-face{{font-family:"Nunito Sans";src:url("{Path(f).as_uri()}");font-weight:200 1000}}' if f else "") + TALL_CSS
    return (f'<!doctype html><html lang="ta"><meta charset="utf-8"><style>{CSS}{face}</style><body>' + "".join(_slide(s, frame) for s in deck)
            + "<script>function show(slide,n){document.querySelectorAll('.slide').forEach((s,i)=>{s.style.display=i==slide?'block':'none';"
              "s.querySelectorAll('[data-i]').forEach(e=>e.style.visibility=+e.dataset.i<n?'visible':'hidden')})}</script></body></html>")


def pictures(deck: list[dict], lines: list[dict], work: Path, tall: bool = False, captions: list[str] | None = None, **frame) -> tuple:
    """One picture of the slides per spoken line, and the presenter's six faces (transparent). Needs Chrome. `tall` = a Short (1080x1920).
    With `captions` (the texts to draw, caption_texts) a third result comes back: {text: transparent strip}, and "" is the empty strip."""
    w, h = TALL if tall else (W, H)
    from selenium import webdriver
    work.mkdir(parents=True, exist_ok=True)
    (work / "slides.html").write_text(page(deck, tall=tall, **frame), encoding="utf-8")
    (work / "face.html").write_text(f'<!doctype html><meta charset="utf-8"><style>{FACE_CSS}</style><body>{FACE_SVG}</body>', encoding="utf-8")
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--hide-scrollbars")
    drv = webdriver.Chrome(options=opts)

    def shot(path: Path) -> Path:
        path.write_bytes(base64.b64decode(drv.execute_cdp_cmd("Page.captureScreenshot", {"format": "png"})["data"]))
        return path
    try:
        drv.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
        drv.get((work / "slides.html").as_uri())
        pngs = []
        for n, ln in enumerate(lines):
            drv.execute_script("show(arguments[0], arguments[1])", ln["slide"], ln["show"])
            pngs.append(shot(work / f"s{n:03d}.png"))
        drv.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {"width": FACE, "height": FACE, "deviceScaleFactor": 1, "mobile": False})
        drv.execute_cdp_cmd("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
        drv.get((work / "face.html").as_uri())
        faces = {}
        for m in range(3):
            for e in range(2):
                drv.execute_script("document.body.className = arguments[0]", f"m{m} e{e}")
                faces[(m, e)] = shot(work / f"face-{m}{e}.png")
        if captions is None:
            return pngs, faces
        box = CAP[tall]
        (work / "captions.html").write_text(caption_page(captions, tall), encoding="utf-8")
        drv.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {"width": w, "height": box["height"], "deviceScaleFactor": 1, "mobile": False})
        drv.get((work / "captions.html").as_uri())
        drv.execute_async_script("var done=arguments[arguments.length-1];document.fonts.load('600 40px \"Nunito Sans\"').then(()=>done(1),()=>done(0))")
        strips = {}
        for n, text in enumerate(["", *captions]):
            drv.execute_script("cap(arguments[0])", n - 1)
            strips[text] = shot(work / f"c{n:03d}.png")
        return pngs, faces, strips
    finally:
        drv.quit()


def _tokens(piece: str) -> list[str]:
    """The words of a piece, a unit kept with the number before it ("₹73,188 crore" is one token)."""
    out: list[str] = []
    for w in piece.split():
        if out and w.strip(".,;:!?").lower() in GLUE:
            out[-1] += " " + w
        else:
            out.append(w)
    return out


def caption_chunks(text: str, tall: bool = False) -> list[str]:
    """A caption cut into chunks that fit one or two lines: whole sentences and clauses first (at . ! ? , ; :), then at word breaks, evenly. A number
    never parts from its unit (₹73,188 crore, 11.2%, 1.6 points)."""
    box, text = CAP[tall], " ".join((text or "").split())
    fits = lambda t: len(t) <= box["chars"] and len(t.split()) <= box["words"]                      # noqa: E731
    pieces: list[list[str]] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text) if text else []:
        if fits(sentence):
            pieces.append(_tokens(sentence))
            continue
        clauses: list[str] = []
        for c in re.split(r"(?<=[,;:])\s+", sentence):       # a very short lead ("All in all,") or tail ("it said.") goes with its neighbour
            if clauses and (len(clauses[-1]) < 14 or len(c) < 14):
                clauses[-1] += " " + c
            else:
                clauses.append(c)
        for clause in clauses:
            rest = _tokens(clause)
            for k in ([1] if fits(clause) else range(max(-(-len(clause) // box["chars"]), -(-len(clause.split()) // box["words"])), 0, -1)):      # k runs of about equal length
                goal, cur = len(" ".join(rest)) / k, []
                while rest and (not cur or k == 1 or (len(" ".join(cur + rest[:1])) <= goal and len(cur) < box["words"])):
                    cur.append(rest.pop(0))
                pieces.append(cur)
    chunks: list[list[str]] = []
    for p in pieces:
        if chunks and fits(" ".join(chunks[-1] + p)):
            chunks[-1] += p
        else:
            chunks.append(list(p))
    return [" ".join(c) for c in chunks]


def caption_plan(lines: list[dict], tall: bool = False) -> list[list[str]]:
    """The chunks of each line's English caption ([] for a line with none: it shows no caption, never a wrong one)."""
    return [caption_chunks(ln.get("en") or "", tall) for ln in lines]


def caption_texts(plan: list[list[str]]) -> list[str]:
    """Each distinct chunk once, in the order shown: the pictures to draw."""
    return list(dict.fromkeys(c for chunks in plan for c in chunks))


def caption_times(chunks: list[str], speech: float, total: float) -> list[float]:
    """Seconds for each chunk of a line: the spoken part shared by character count, the line's pause (and any hold) added to the last chunk."""
    size = sum(map(len, chunks)) or 1
    speech = min(speech, total)
    secs = [speech * len(c) / size for c in chunks]
    secs[-1] += total - sum(secs)
    return secs


def srt_time(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _srt(timed: list[list[tuple[str, float]]], lengths: list[float], out: Path) -> Path:
    """The same chunks and times as a subtitle file (for a subtitle-track upload later). `lengths` are the lines' seconds: a line with no caption still takes its time."""
    rows, at, n = [], 0.0, 0
    for line, length in zip(timed, lengths):
        start = at
        for text, secs in line:
            n += 1
            rows.append(f"{n}\n{srt_time(start)} --> {srt_time(start + secs)}\n{text}\n")
            start += secs
        at += length
    out.write_text("\n".join(rows), encoding="utf-8")
    return out


def caption_page(texts: list[str], tall: bool = False) -> str:
    """The captions as one page the size of the strip: one band per text, shown one at a time (cap(n); cap(-1) shows none)."""
    box, (x0, x1) = CAP[tall], CAP[tall]["x"]
    from ..services import fonts
    f = fonts.path("Nunito Sans")
    face = f'@font-face{{font-family:"Nunito Sans";src:url("{Path(f).as_uri()}");font-weight:200 1000}}' if f else ""
    css = (f'{face}*{{margin:0;box-sizing:border-box}}html,body{{background:transparent;width:{TALL[0] if tall else W}px;height:{box["height"]}px;overflow:hidden}}'
           f'.c{{position:absolute;left:{x0}px;width:{x1 - x0}px;bottom:6px;display:none;justify-content:center}}'
           f'.c b{{display:inline-block;max-width:100%;background:rgba(27,27,27,.85);color:#fff;border-radius:{box["font"] // 2 + 2}px;padding:{box["font"] // 4}px {box["font"] * 3 // 5}px;'
           f'font:600 {box["font"]}px/1.25 {CAP_FONT};text-align:center;text-wrap:balance}}')
    return (f'<!doctype html><html lang="en"><meta charset="utf-8"><style>{css}</style><body>' + "".join(f'<div class="c"><b>{html.escape(t)}</b></div>' for t in texts)
            + "<script>function cap(n){document.querySelectorAll('.c').forEach((e,i)=>e.style.display=i==n?'flex':'none')}</script></body></html>")


def mouths(wav: Path, fps: int = MOUTH_FPS) -> list[int]:
    """The mouth for each 1/fps of the voice track: 0 closed, 1 half, 2 open, by loudness against the track's own loud parts."""
    import numpy as np
    with wave.open(str(wav), "rb") as w:
        rate, ch = w.getframerate(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    pcm = pcm[::ch]
    hop = rate // fps
    if len(pcm) < hop:
        return [0]
    rms = np.sqrt((pcm[:len(pcm) // hop * hop].reshape(-1, hop) ** 2).mean(axis=1))
    top = float(np.percentile(rms, 90)) or 1.0
    return [0 if r < 0.10 * top else 1 if r < 0.45 * top else 2 for r in rms]


def _face_list(states: list[int], faces: dict, out: Path, fps: int = MOUTH_FPS, blink_every: float = 3.7) -> Path:
    """An ffmpeg list of face pictures with how long each stays: runs of the same face are one entry."""
    seq = [(m, 1 if int(i / fps / blink_every) != int((i + 2) / fps / blink_every) else 0) for i, m in enumerate(states)]
    rows, i = [], 0
    while i < len(seq):
        j = i
        while j < len(seq) and seq[j] == seq[i]:
            j += 1
        rows.append(f"file '{faces[seq[i]].as_posix()}'\nduration {(j - i) / fps:.4f}")
        i = j
    out.write_text("\n".join(rows + [f"file '{faces[seq[-1]].as_posix()}'"]) + "\n", encoding="utf-8")
    return out


def _png_list(entries: list[tuple[Path, float]], out: Path) -> Path:
    """An ffmpeg list of pictures with how long each stays (the caption strips)."""
    out.write_text("".join(f"file '{p.as_posix()}'\nduration {d:.4f}\n" for p, d in entries) + f"file '{entries[-1][0].as_posix()}'\n", encoding="utf-8")
    return out


def assemble(work: Path, pngs: list[Path], lines: list[dict], spoken: list[Path], out: Path, faces: dict | None = None, pause: float = 0.15,
             size: tuple[int, int] = (W, H), captions: dict | None = None) -> Path:
    """Join the pictures and the spoken lines into the video. `spoken` holds one audio file per line; a line with `hold` stays at least that many seconds.
    `captions` = {"plan": caption_plan(lines), "pngs": the strips pictures() gave back}: each line's chunks are timed across that line's own audio, laid over the
    video, and written beside it as an .srt (captions.srt next to final.mp4). Left out, the video is made exactly as before."""
    wavs, secs = [], []
    for i, a in enumerate(spoken):                      # every line as a wav with its pause, so its length is exact
        wavs.append(work / f"l{i:03d}.wav")
        run(["-i", str(a), "-af", f"aresample=44100,apad=pad_dur={pause}" + (f",apad=whole_dur={lines[i]['hold']}" if lines[i].get("hold") else ""), "-ac", "1", str(wavs[-1])])
        secs.append(probe(wavs[-1]))
    (work / "voice.txt").write_text("".join(f"file '{w.as_posix()}'\n" for w in wavs), encoding="utf-8")
    voice = work / "voice.wav"
    run(["-f", "concat", "-safe", "0", "-i", str(work / "voice.txt"), "-c", "copy", str(voice)])
    n, args, graph, at, last = len(lines), [], [], 0.0, "0:v"
    for i, png in enumerate(pngs):                      # each picture stays for its line, plus the wipe into the next
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{secs[i] + (WIPE if i < n - 1 else 0):.3f}", "-i", str(png)]
    for i in range(1, n):                               # a new slide fades in; a new thing on the same slide is wiped in
        at += secs[i - 1]
        kind = "wiperight" if lines[i]["slide"] == lines[i - 1]["slide"] else "fade"
        graph.append(f"[{last}][{i}:v]xfade=transition={kind}:duration={WIPE}:offset={at:.3f}[x{i}]")
        last = f"x{i}"
    args += ["-i", str(voice)]
    if faces:
        args += ["-f", "concat", "-safe", "0", "-i", str(_face_list(mouths(voice), faces, work / "face.txt"))]
        graph.append(f"[{n + 1}:v]fps={FPS}[face];[{last}][face]overlay={size[0] - FACE - 40}:{size[1] - FACE}:eof_action=repeat[p]")
        last = "p"
    if captions:
        timed = [list(zip(chunks, caption_times(chunks, probe(a), secs[i]))) if chunks else [] for i, (chunks, a) in enumerate(zip(captions["plan"], spoken))]
        strips = captions["pngs"]
        entries = [(strips[c], d) if line else (strips[""], secs[i]) for i, line in enumerate(timed) for c, d in (line or [("", 0)])]
        args += ["-f", "concat", "-safe", "0", "-i", str(_png_list(entries, work / "captions.txt"))]
        graph.append(f"[{n + 1 + (1 if faces else 0)}:v]fps={FPS},format=rgba[cap];[{last}][cap]overlay=0:{CAP[size == TALL]['top']}:eof_action=repeat[c]")
        last = "c"
        _srt(timed, secs, out.with_name("captions.srt" if out.name == "final.mp4" else out.stem + ".srt"))
    graph.append(f"[{last}]format=yuv420p[v]")
    run([*args, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", f"{n}:a", "-t", f"{sum(secs):.3f}", "-r", str(FPS),
         "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)])
    return out
