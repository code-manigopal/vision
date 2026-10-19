"""Animated slides (HyperFrames): the same deck and look as slides.py, moving with the voice.

Each slide is a clip from its first spoken line to its last (crossfading into the next). An item appears on the line that
first shows it (`show` > its index), animated by the slide's kind:
  table   the row slides in, the row being spoken about (show - 1) is lit and the rest dimmed, this year's figure counts up
          from last year's to the filed figure, the change chip pops, and below the table last year and this year grow as bars
          (only when the table has four rows or fewer: below that is the captions' band)
  facts   the row slides in and its value counts up
  board   (a Short) each region's card pops in, its rows one after another
  quotes  each sentence slides in behind its chip
  points / cards, cover   each card rises in and its drawing is drawn on
  notice  (the disclaimer) fades in and stays still, to be read
The presenter (Mani's own six face tiles, slides.own_faces, or the drawn stand-in) is part of the page: his mouth follows
the voice's loudness as before, he blinks, breathes, nods as each line starts, points his arm at the row or card being
spoken about, bounces a little at a good figure and tilts his head at a bad one.
A count-up shows only steps between the two figures and always ends on the deck's own text, exactly: nothing on screen is a
figure the deck does not have. The presenter, the captions and the audio are laid on top by slides.assemble, as before.
"""

from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path

from ..services import hyperframes as hf
from . import slides

FADE = 0.4                   # a slide crossfades into the next
STEPS = 18                   # a count-up passes through this many figures
NUM = re.compile(r"^(.*?)(\d[\d,]*(?:\.\d+)?)(.*)$")

EXTRA = """
.slide{display:block}
.bars{position:absolute;left:110px;width:1250px;top:760px;display:grid;grid-template-columns:170px 1fr;row-gap:10px;align-items:center;opacity:0}
.bars .bl{font-size:26px;font-weight:700;color:#6b6455}.bars .tr{position:relative;height:32px}
.bars .bar{height:32px;border-radius:9px;width:0}.bars .was{background:#b9b29f}.bars .now.good{background:#1f9d55}.bars .now.bad{background:#d92d20}.bars .now.flat{background:#6b6455}
.bars .bv{position:absolute;top:-3px;font:500 28px "JetBrains Mono",Menlo,monospace;color:#4a4536}.bars .bv.b{color:#1b1b1b;font-weight:700}
tr.lit td{border-color:#14532d}
"""


def times(secs: list[float]) -> list[float]:
    out, t = [], 0.0
    for s in secs:
        out.append(round(t, 3))
        t += s
    return out


def steps(was: str | None, now: str) -> list[str]:
    """The texts a count-up passes through on its way from `was` to `now` (both as the deck writes them), ending on `now`
    itself. [] when `now` has no figure to count (then it simply appears). Commas, decimals, prefix and suffix follow `now`."""
    m = NUM.match(now or "")
    if not m:
        return []
    pre, digits, post = m.groups()
    end = float(digits.replace(",", ""))
    w = NUM.match(was or "")
    start = float(w.group(2).replace(",", "")) if w else 0.0
    dec = len(digits.split(".")[1]) if "." in digits else 0
    indian = bool(re.search(r"\d,\d\d,\d{3}", digits))

    def fmt(v: float) -> str:
        s = f"{v:.{dec}f}"
        whole, _, frac = s.partition(".")
        neg = whole.startswith("-")
        whole = whole.lstrip("-")
        if "," in digits:
            if indian and len(whole) > 3:
                head, tail = whole[:-3], whole[-3:]
                head = ",".join(re.findall(r"\d{1,2}(?=(?:\d{2})*$)", head))
                whole = f"{head},{tail}"
            else:
                whole = f"{int(whole):,}"
        return pre + ("-" if neg else "") + whole + ("." + frac if frac else "") + post

    out = [fmt(start + (end - start) * (1 - (1 - k / STEPS) ** 3)) for k in range(1, STEPS)]
    out = [x for i, x in enumerate(out) if (i == 0 or x != out[i - 1]) and x != now]
    return out + [now]


def _tween(sel: str, frm: dict, to: dict, at: float) -> str:
    return f"tl.fromTo({json.dumps(sel)}, {json.dumps(frm)}, {json.dumps(to)}, {at:.3f});"


def _count(sel: str, texts: list[str], at: float, over: float) -> list[str]:
    if not texts:
        return []
    first = [f"tl.set({json.dumps(sel)}, {{textContent: {json.dumps(texts[0])}}}, {at:.3f});"]
    return first + [f"tl.set({json.dumps(sel)}, {{textContent: {json.dumps(t)}}}, {at + over * (k + 1) / len(texts):.3f});" for k, t in enumerate(texts[1:])]


def _num(s: str) -> float | None:
    m = NUM.match(s or "")
    return float(m.group(2).replace(",", "")) if m else None


# the pointing arm: a sleeve in the shirt's green and a hand, drawn pointing right from the shoulder (its left end), rotated to aim
ARM = """<svg viewBox="0 0 190 64" width="190" height="64"><path d="M4 18 L120 22 L122 46 L6 50 Q-4 34 4 18 Z" fill="#1c3a2b" stroke="#111" stroke-width="4" stroke-linejoin="round"/>
<path d="M118 20 Q140 14 150 24 L184 26 Q190 30 184 34 L152 36 Q150 46 136 48 Q120 50 118 44 Z" fill="#c98a5a" stroke="#111" stroke-width="4" stroke-linejoin="round"/>
<path d="M134 36 Q142 38 150 36" fill="none" stroke="#111" stroke-width="3" stroke-linecap="round"/></svg>"""
PRES_CSS = """
#pres{position:absolute;width:300px;height:300px}#presin{position:absolute;inset:0;transform-origin:50% 90%}
#presin img{position:absolute;inset:0;width:300px;height:300px;opacity:0}
#arm{position:absolute;width:190px;height:64px;transform-origin:4px 34px;opacity:0}
"""


def presenter(faces: dict, states: list[int], cues: list[tuple], total: float, size: tuple[int, int]) -> tuple[str, list[str], dict]:
    """The presenter's layer: (html, timeline lines, assets). `faces` = {(mouth, eyes shut): png}; `states` = slides.mouths of the
    voice; `cues` = [(time, kind, selector or tone)]: "point" at an element, "good"/"bad" a reaction, "nod" a small nod."""
    w, h = size
    x0, y0 = w - slides.FACE - 40, h - slides.FACE
    imgs = "".join(f'<img id="fc{m}{e}" src="assets/face-{m}{e}.png">' for (m, e) in sorted(faces))
    html_ = f'<div id="pres" style="left:{x0}px;top:{y0}px"><div id="presin">{imgs}</div></div><div id="arm" style="left:{x0 + 62}px;top:{y0 + 196}px">{ARM}</div>'
    js, fps = [], slides.MOUTH_FPS
    seq = [(m, 1 if int(i / fps / 3.7) != int((i + 2) / fps / 3.7) else 0) for i, m in enumerate(states)] or [(0, 0)]
    last = None
    for i, st in enumerate(seq):                       # only the changes: the face shown is swapped
        if st != last and st in faces:
            if last is not None:
                js.append(f'tl.set("#fc{last[0]}{last[1]}", {{opacity: 0}}, {i / fps:.3f});')
            js.append(f'tl.set("#fc{st[0]}{st[1]}", {{opacity: 1}}, {i / fps:.3f});')
            last = st
    js.append(f'tl.fromTo("#presin", {{y: 0}}, {{y: -4, duration: 1.9, ease: "sine.inOut", yoyo: true, repeat: {max(1, int(total / 1.9))}}}, 0);')
    busy = -1.0
    for t, kind, arg in sorted(cues):
        if kind == "nod":
            js.append(f'tl.to("#presin", {{rotation: 2.5, duration: 0.18, yoyo: true, repeat: 1, ease: "sine.inOut"}}, {t:.3f});')
        elif kind == "good":
            js.append(f'tl.to("#presin", {{y: -14, duration: 0.16, yoyo: true, repeat: 3, ease: "power1.out"}}, {t:.3f});')
        elif kind == "bad":
            js.append(f'tl.to("#presin", {{rotation: -6, duration: 0.35, ease: "sine.out"}}, {t:.3f});')
            js.append(f'tl.to("#presin", {{rotation: 0, duration: 0.5, ease: "sine.inOut"}}, {t + 1.6:.3f});')
        elif kind == "point" and t > busy:
            tx, ty = arg                                # where the item sits on the slide (roughly: a gesture, not a laser)
            sx, sy = x0 + 66, y0 + 230
            js.append(f"point({math.degrees(math.atan2(ty - sy, tx - sx)):.1f}, {t:.3f});")
            busy = t + 2.6
    return html_, js, {f"face-{m}{e}.png": p for (m, e), p in faces.items()}


POINT_JS = """function point(ang, at) {
  var arm = document.getElementById("arm");
  tl.fromTo(arm, {opacity: 0, rotation: 100}, {opacity: 1, rotation: ang, duration: 0.45, ease: "back.out(1.4)"}, at);
  tl.to(arm, {rotation: ang + 4, duration: 0.3, yoyo: true, repeat: 3, ease: "sine.inOut"}, at + 0.5);
  tl.to(arm, {opacity: 0, rotation: 100, duration: 0.4, ease: "power1.in"}, at + 2.2);
}
"""


def build(deck: list[dict], lines: list[dict], secs: list[float], *, tall: bool = False, channel: str = "", tag: str = "", source: str = "", top: str = "",
          faces: dict | None = None, states: list[int] | None = None) -> str:
    """The whole slides track as one HyperFrames page, timed by each line's seconds (`secs`, the voice with its pauses)."""
    w, h = slides.TALL if tall else (slides.W, slides.H)
    starts, total = times(secs), round(sum(secs), 3)
    frame = ("" if tall else f'<div class="tag">{html.escape(tag)}</div>' if tag else f'<div class="src">{html.escape(source)}</div>' if source else "") \
        + f'<div class="mark">{html.escape(channel)}</div>' + (f'<div class="top">{html.escape(top)}</div>' if tall and top else "")
    body, js, cues = [], [], [(starts[i] + 0.05, "nod", "") for i in range(len(lines))]
    order = []                                         # slides in the order they are spoken
    for i, ln in enumerate(lines):
        if not order or order[-1][0] != ln["slide"]:
            order.append((ln["slide"], []))
        order[-1][1].append(i)
    for n, (k, idx) in enumerate(order):
        s = deck[k]
        t0 = starts[idx[0]]
        t1 = starts[idx[-1]] + secs[idx[-1]]
        dur = round(t1 - t0 + (FADE if n < len(order) - 1 else 0), 3)
        sec = slides._slide(s, frame).replace('<section class="slide">', f'<section class="slide clip" id="s{n}" data-start="{t0:.3f}" data-duration="{dur:.3f}">', 1)
        # every data-i element gets its own id; an item is the first element of its index, the note the one after the items
        items = s.get("items") or []
        kind = s.get("kind", "points")
        ids: dict[int, list[str]] = {}
        c = [0]

        def tag_item(m, n=n):
            c[0] += 1
            ids.setdefault(int(m.group(1)), []).append(f"s{n}e{c[0]}")
            return f'{m.group(0)} id="s{n}e{c[0]}"'
        sec = re.sub(r'data-i="(\d+)"', tag_item, sec)
        item_id = {it: f"#{ids[it][0]}" for it in range(len(items)) if it in ids}
        note_id = None
        if s.get("note"):
            k_note = 0 if s.get("note_always") else len(items)
            note_id = f"#{ids[k_note][-1]}" if ids.get(k_note) and (k_note == len(items) or len(ids[k_note]) > 1) else None
        widths = {}
        if kind == "table" and len(items) <= 4 and not tall:
            for r_i, r in enumerate(items):
                tone = r.get("tone", "flat")
                a, b = _num(r.get("was")), _num(r.get("now"))
                if a is None or b is None or max(a, b) <= 0:
                    continue
                top_ = max(a, b)
                widths[r_i] = (f"{a / top_ * 78:.1f}%", f"{b / top_ * 78:.1f}%")
                cols = s.get("cols") or ["", ""]
                sec = sec.replace("</section>", f'<div class="bars" id="s{n}b{r_i}"><div class="bl">{html.escape(cols[0])}</div><div class="tr" style="--w:{a / top_ * 78:.1f}%">'
                                  f'<div class="bar was" id="s{n}bw{r_i}"></div><span class="bv" style="left:calc({a / top_ * 78:.1f}% + 16px)">{html.escape(r["was"])}</span></div>'
                                  f'<div class="bl">{html.escape(cols[1] if len(cols) > 1 else "")}</div><div class="tr"><div class="bar now {tone}" id="s{n}bn{r_i}"></div>'
                                  f'<span class="bv b" id="s{n}bt{r_i}" style="left:calc({b / top_ * 78:.1f}% + 16px)">{html.escape(r["now"])}</span></div></div></section>', 1)
        body.append(sec)
        if n:
            js.append(_tween(f"#s{n}", {"opacity": 0}, {"opacity": 1, "duration": FADE}, t0))
        # when each item first shows
        first = {}
        for li in idx:
            for it in range(lines[li]["show"]):
                first.setdefault(it, starts[li])
        note_at = first.get(0 if s.get("note_always") else len(items))
        if note_id and note_at is not None:
            js.append(_tween(note_id, {"opacity": 0}, {"opacity": 1, "duration": 0.5}, note_at))
        for it, at in sorted(first.items()):
            if it not in item_id:
                continue
            sel = item_id[it]
            if kind == "notice":
                js.append(_tween(sel, {"opacity": 0}, {"opacity": 1, "duration": 0.5}, at))
                continue
            stagger = 0.12 * sum(1 for x, a2 in first.items() if a2 == at and x < it)
            at2 = at + stagger
            if kind in ("table", "facts"):
                # a table row itself is never moved (a transformed <tr> breaks the table in Chrome): its cells are
                js.append(_tween(f"{sel} td:not(:nth-child(4))" if kind == "table" else f"{sel} td", {"opacity": 0}, {"opacity": 1, "duration": 0.35, "stagger": 0.05}, at2))      # cells only fade: moving one breaks its borders
                r = items[it]
                cell = f"{sel} td.now"
                texts = steps(r.get("was") if kind == "table" else None, r["now"] if kind == "table" else r["value"])
                over = 1.1
                js += _count(cell, texts, at2 + 0.3, over)
                cues.append((at2 + 0.2, "point", (1150, (330 if kind == "table" else 320) + it * (114 if kind == "table" else 104))))
                if r.get("tone") in ("good", "bad") and texts:
                    cues.append((at2 + 0.3 + over, r["tone"], ""))
                if kind == "table":
                    js.append(_tween(f"{sel} td:nth-child(4)", {"opacity": 0}, {"opacity": 1, "duration": 0.3}, at2 + 0.3 + over))
            elif kind == "board":
                js.append(_tween(sel, {"opacity": 0, "scale": 0.92, "y": 30}, {"opacity": 1, "scale": 1, "y": 0, "duration": 0.4, "ease": "back.out(1.6)"}, at2))
                js.append(_tween(f"{sel} .r", {"opacity": 0, "x": 30}, {"opacity": 1, "x": 0, "duration": 0.3, "stagger": 0.15}, at2 + 0.25))
            elif kind == "quotes":
                cues.append((at2 + 0.1, "point", (1100, 300 + it * 110)))
                js.append(_tween(sel, {"opacity": 0, "x": -60}, {"opacity": 1, "x": 0, "duration": 0.45, "ease": "power2.out"}, at2))
                js.append(_tween(f"{sel} b", {"scale": 0.6}, {"scale": 1, "duration": 0.35, "ease": "back.out(2)"}, at2 + 0.2))
            else:                                       # cover icons, cards
                if kind != "cover":
                    n_c = len(items)
                    cues.append((at2 + 0.1, "point", ((110 + (it + 0.5) * 1700 / n_c) if not tall else 500, 520 if not tall else 360 + it * 230)))
                    if items[it].get("tone") in ("good", "bad"):
                        cues.append((at2 + 0.6, items[it]["tone"], ""))
                js.append(_tween(sel, {"opacity": 0, "y": 40, "scale": 0.9}, {"opacity": 1, "y": 0, "scale": 1, "duration": 0.45, "ease": "back.out(1.7)"}, at2))
                js.append(f"draw({json.dumps(sel)}, {at2 + 0.1:.3f});")
        # the items not shown yet are hidden from the slide's start
        for it, sel in item_id.items():
            if kind in ("table", "facts") and it in first:
                continue                                # its cells are hidden until they come in
            if it not in first or first[it] > t0:
                js.insert(0, f'tl.set("{sel}", {{opacity: 0}}, 0);')
        if note_id and (note_at is None or note_at > t0):
            js.insert(0, f'tl.set("{note_id}", {{opacity: 0}}, 0);')
        # table: light the row being spoken about, grow its bars
        if kind in ("table", "facts") and len(items) > 1:
            for li in idx:
                row = lines[li]["show"] - 1
                if 0 <= row < len(items) and len(items) > 1:
                    others = ", ".join(f"{item_id[j]} td" for j in range(lines[li]["show"]) if j != row and j in item_id)      # only rows already on screen
                    if others:
                        js.append(f'tl.to("{others}", {{opacity: 0.4, duration: 0.3}}, {starts[li]:.3f});')
                    if row in item_id:
                        js.append(f'tl.to("{item_id[row]} td", {{opacity: 1, duration: 0.3}}, {starts[li]:.3f});')
            shown = max(lines[li]["show"] for li in idx)
            if shown > 1:
                js.append(f'tl.to("{", ".join(f"{item_id[j]} td" for j in range(shown) if j in item_id)}", {{opacity: 1, duration: 0.3}}, {max(t0, t1 - 0.6):.3f});')
        if kind == "table" and not tall:
            for it, at in first.items():
                if it in widths:
                    nxt = min([a for x, a in first.items() if a > at] + [t1])
                    js.append(_tween(f"#s{n}b{it}", {"opacity": 0}, {"opacity": 1, "duration": 0.3}, at + 0.1))
                    js.append(f'tl.fromTo("#s{n}bw{it}", {{width: "0%"}}, {{width: "{widths[it][0]}", duration: 0.8, ease: "power2.out"}}, {at + 0.2:.3f});')
                    js.append(f'tl.fromTo("#s{n}bn{it}", {{width: "0%"}}, {{width: "{widths[it][1]}", duration: 1.1, ease: "power2.out"}}, {at + 0.3:.3f});')
                    js.append(_tween(f"#s{n}bt{it}", {"opacity": 0}, {"opacity": 1, "duration": 0.3}, at + 1.3))
                    js.append(f'tl.to("#s{n}b{it}", {{opacity: 0, duration: 0.25}}, {max(at + 1.6, nxt - 0.25):.3f});')
    from ..services import fonts
    css = slides.CSS + (slides.TALL_CSS if tall else "") + EXTRA + hf.font_face("Baloo Thambi 2", "BalooThambi2.ttf") + hf.font_face("JetBrains Mono", "JetBrainsMono.ttf") \
        + (hf.font_face("Nunito Sans", "NunitoSans.ttf", "200 1000") if fonts.path("Nunito Sans") else "")
    css = css.replace("body{width:1920px;height:1080px;overflow:hidden;", "body{overflow:hidden;")
    helpers = """function draw(sel, at) {
  document.querySelectorAll(sel + " svg path, " + sel + " svg circle, " + sel + " svg ellipse").forEach(function (p) {
    if (!p.getTotalLength) return; var L = Math.ceil(p.getTotalLength()) + 2;
    tl.fromTo(p, {strokeDasharray: L, strokeDashoffset: L}, {strokeDashoffset: 0, duration: 0.7, ease: "power1.inOut"}, at);
  });
}
"""
    if faces:
        p_html, p_js, _ = presenter(faces, states or [], cues, total, (w, h))
        body.append(p_html)
        js += p_js
        css += PRES_CSS
        helpers += POINT_JS
    return hf.page("".join(body), helpers + "\n".join(js), width=w, height=h, seconds=total, css=css)


def render(deck: list[dict], lines: list[dict], secs: list[float], out: Path, *, tall: bool = False, faces: dict | None = None,
           states: list[int] | None = None, **frame) -> Path:
    """The slides track as an MP4 (silent), with the presenter when `faces` are given, or hf.RenderFailed."""
    from ..services import fonts
    assets = {f: hf.FONTS / f for f in ("BalooThambi2.ttf", "JetBrainsMono.ttf") if (hf.FONTS / f).is_file()}
    if len(assets) < 2:
        raise hf.RenderFailed("the slide fonts are missing (python -m vision hyperframes)")
    if fonts.path("Nunito Sans"):
        assets["NunitoSans.ttf"] = Path(fonts.path("Nunito Sans"))
    if faces:
        assets.update({f"face-{m}{e}.png": Path(p) for (m, e), p in faces.items()})
    return hf.render(build(deck, lines, secs, tall=tall, faces=faces, states=states, **frame), out, assets=assets)
