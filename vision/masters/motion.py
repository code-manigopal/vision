"""Motion Shorts: every second animated (HyperFrames), for the channels with `style: motion` (Mani, 2026-10-19, after the Venus prototype).

A Short is a list of scenes on the voice's clock. Each scene is one of a fixed library, filled from a plan (the Scene Planner's JSON,
checked in `check`); the model never writes HTML. Over every scene: the channel's moving background (stars, lab grid or terrain),
big word-by-word captions in the lower third, the channel's watermark, a flash and a whoosh on every cut, an impact on reveals,
music under the voice. Scene types:

    hook     {title, hot?, image?}                 the question slams in over the subject, punch-in, glow
    photo    {image, tag?, tag2?, round?}          the real thing (NASA, Commons) easing in, with callout tags
    text     {lines: [1-2], hot?}                  kinetic words
    number   {value, label}                        a count-up to the figure the line says
    compare  {a, b, a_image?, b_image?, a_value?, b_value?}   two things side by side, then their values
    orbit    {center, body, center_image?, body_image?}       one body circling another
    flow     {steps: [2-4], icons?: [...]}         a chain that lights up step by step
    split    {left, right, left_icon?, right_icon?, image?}   two halves (day/night, before/after)
    icons    {icons: [2-4], labels: [...]}         icons popping in a row
    map      {highlight: [countries], label?}      the world map easing to the highlighted countries
    gauge    {value, label}                        a thermometer-style bar filling to the figure
    outro    {text}                                the channel's logo and its follow line

Rules kept in code: every word on screen comes from the scene's own spoken line (labels), every figure is one the line says, a new
visual at least every `MAX_SCENE` seconds (a longer stretch is cut into two scenes), assets must exist (else the scene falls back to
`text`). `render` raises hf.RenderFailed on any trouble; the Editor then makes the Short the stock-footage way.
"""

from __future__ import annotations

import html as H
import json
import math
import re
from pathlib import Path

from ..services import hyperframes as hf

W, HGT = 1080, 1920
STAGE_H = 1240                     # scenes live above the captions (y < 1240); captions 1290-1550; YouTube's own controls below
MAX_SCENE = 3.2                    # seconds before the picture must change
TYPES = ("hook", "photo", "text", "number", "compare", "orbit", "flow", "split", "icons", "map", "gauge", "outro")

THEMES = {
    "space": {"bg": "radial-gradient(1200px 900px at 50% 30%,#1b1446 0%,#0a0b24 45%,#03040c 100%)", "a": "#4cc9ff", "hot": "#ff8a1f", "dots": "#ffffff",
              "neb": ("#6d28d955", "#0ea5e944")},
    "body": {"bg": "radial-gradient(1200px 900px at 50% 30%,#0b2a4a 0%,#06182c 50%,#020a14 100%)", "a": "#3ee0c9", "hot": "#ff4d6d", "dots": "#7fdcff",
             "neb": ("#0ea5e955", "#14b8a644")},
    "geography": {"bg": "radial-gradient(1200px 900px at 50% 30%,#123524 0%,#0a1f1a 50%,#030a08 100%)", "a": "#ffd23f", "hot": "#ff8a1f", "dots": "#c8f7c5",
                  "neb": ("#16a34a44", "#0ea5e944")},
}

CSS = """
#root{font-family:Anton,Impact,sans-serif;color:#fff}
.layer{position:absolute;inset:0}
.neb{position:absolute;border-radius:50%;filter:blur(20px)}
.sc{position:absolute;left:0;top:0;width:1080px;height:1240px;overflow:hidden}
.ph{position:absolute;background-size:cover;background-position:center;border-radius:28px;box-shadow:0 20px 80px #000a}
.ph.round{border-radius:50%}
.kin{position:absolute;left:40px;right:40px;text-align:center;line-height:.95;letter-spacing:2px;text-shadow:0 8px 30px #000c}
.tag{position:absolute;font-family:"Bebas Neue",Anton,sans-serif;font-size:60px;letter-spacing:3px;padding:6px 24px;border-radius:14px;background:#0b1030d9;border:3px solid var(--a);white-space:nowrap}
.tag.h{border-color:var(--hot)}
.ic{stroke:#fff;fill:none;stroke-width:1.6}
.cw{position:absolute;left:0;right:0;text-align:center;font-size:104px;line-height:1.02;opacity:0}
.cw span{display:inline-block;margin:0 24px;color:#fff;-webkit-text-stroke:3px #000;text-shadow:0 6px 0 #000,0 0 18px #000c}
#cap{position:absolute;left:70px;right:150px;top:1290px;height:260px}
#flash{position:absolute;inset:0;background:#fff;opacity:0}
#wm{position:absolute;right:36px;top:60px;width:150px;height:150px;opacity:.85}
.box{position:absolute;display:flex;align-items:center;justify-content:center;text-align:center;border-radius:26px;background:#0b1030d9;border:4px solid var(--a);font-size:62px;line-height:1.02;padding:0 18px}
.arrow{position:absolute;height:8px;background:var(--a);border-radius:4px;transform-origin:left center}
"""


# ---------- checking a plan ----------
def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _figures(s: str) -> set[str]:
    return {x.replace(",", "") for x in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}


NUM_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
             "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
             "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}


def said_numbers(line: str) -> set[str]:
    """Figures the spoken line says, in digits or in words ("four hundred sixty" -> 460, "ninety" -> 90)."""
    out = _figures(line)
    toks = re.findall(r"[a-z]+", line.lower())
    i = 0
    while i < len(toks):
        if toks[i] in NUM_WORDS:
            total, cur = 0, 0
            while i < len(toks) and (toks[i] in NUM_WORDS or (toks[i] == "and" and cur)):
                v = NUM_WORDS.get(toks[i], 0)
                if v == 100:
                    cur = max(cur, 1) * 100
                elif v >= 1000:
                    total += max(cur, 1) * v
                    cur = 0
                else:
                    cur += v
                i += 1
            out.add(str(total + cur))
        else:
            i += 1
    return out


def text_ok(text: str, line: str, words: int = 5) -> bool:
    """On-screen text: short, every figure said in the line, and at least half its words from the line (no new claims)."""
    t = " ".join(str(text or "").split())
    if not t or len(t.split()) > words or len(t) > 40:
        return False
    if not _figures(t) <= said_numbers(line):
        return False
    mine = [w for w in re.findall(r"[a-z]+", t.lower()) if len(w) > 2]
    return not mine or sum(w in _words(line) for w in mine) * 2 >= len(mine)


def check(scene: dict, line: str, images: set[str], icons: set[str]) -> dict | None:
    """The scene as it will be drawn, or None. `images`: subjects the Asset Finder found; `icons`: allowed icon names."""
    if not isinstance(scene, dict) or scene.get("type") not in TYPES:
        return None
    t, s = scene["type"], dict(scene)
    img = lambda k: s.get(k) if s.get(k) in images else None
    if t == "hook":
        return {"type": t, "title": s["title"], "hot": s.get("hot") if text_ok(s.get("hot", ""), line, 3) else "", "image": img("image")} if text_ok(s.get("title"), line, 6) else None
    if t == "photo":
        if not img("image"):
            return None
        return {"type": t, "image": s["image"], "tag": s.get("tag") if text_ok(s.get("tag", ""), line) else "", "tag2": s.get("tag2") if text_ok(s.get("tag2", ""), line) else "",
                "round": bool(s.get("round"))}
    if t == "text":
        lines = [x for x in (s.get("lines") or [])[:2] if text_ok(x, line, 4)]
        return {"type": t, "lines": lines, "hot": s.get("hot") or ""} if lines else None
    if t in ("number", "gauge"):
        v = str(s.get("value") or "")
        if not re.search(r"\d", v) or not _figures(v) <= said_numbers(line) or len(v) > 12:
            return None
        return {"type": t, "value": v, "label": s.get("label") if text_ok(s.get("label", ""), line, 6) else ""}
    if t == "compare":
        if not (text_ok(s.get("a"), line, 3) and text_ok(s.get("b"), line, 3)):
            return None
        va, vb = [str(s.get(k) or "") for k in ("a_value", "b_value")]
        if not (va and vb and _figures(va + " " + vb) <= said_numbers(line)):
            va = vb = ""
        both = bool(img("a_image") and img("b_image"))                # one side with a picture and one without looks broken
        return {"type": t, "a": s["a"], "b": s["b"], "a_image": img("a_image") if both else None, "b_image": img("b_image") if both else None,
                "a_value": va, "b_value": vb}
    if t == "orbit":
        if not (text_ok(s.get("center"), line, 2) and text_ok(s.get("body"), line, 2)):
            return None
        return {"type": t, "center": s["center"], "body": s["body"], "center_image": img("center_image"), "body_image": img("body_image")}
    if t == "flow":
        steps = (s.get("steps") or [])[:4]
        if len(steps) < 2 or not all(text_ok(x, line, 3) for x in steps):
            return None
        ic = [x if x in icons else "" for x in (s.get("icons") or [])][:len(steps)]
        return {"type": t, "steps": steps, "icons": ic + [""] * (len(steps) - len(ic))}
    if t == "split":
        if not (text_ok(s.get("left"), line, 3) and text_ok(s.get("right"), line, 3)):
            return None
        return {"type": t, "left": s["left"], "right": s["right"], "left_icon": s.get("left_icon") if s.get("left_icon") in icons else "",
                "right_icon": s.get("right_icon") if s.get("right_icon") in icons else "", "image": img("image")}
    if t == "icons":
        names = [x for x in (s.get("icons") or [])[:4] if x in icons]
        labels = [x if text_ok(x, line, 3) else "" for x in (s.get("labels") or [])][:len(names)]
        return {"type": t, "icons": names, "labels": labels + [""] * (len(names) - len(labels))} if len(names) >= 2 else None
    if t == "map":
        from . import maps
        try:
            names = [maps.known(x) for x in (s.get("highlight") or [])[:6]]
        except Exception:  # noqa: BLE001 - no map data: no map scene
            return None
        if not names or not all(names) or not all(any(re.search(rf"\b{re.escape(a)}\b", line.lower()) for a in maps.aliases_of(n)) for n in names):
            return None
        return {"type": t, "highlight": names, "label": s.get("label") if text_ok(s.get("label", ""), line, 6) else ""}
    if t == "outro":
        return {"type": t, "text": str(s.get("text") or "")[:60]}
    return None


# ---------- drawing ----------
class Comp:
    """Collects one Short's html and timeline."""

    def __init__(self, theme: dict, assets: dict[str, Path], icon_paths: dict[str, Path]) -> None:
        self.t, self.assets, self.icons = theme, assets, icon_paths
        self.body: list[str] = []
        self.js: list[str] = []
        self.n = 0

    def tw(self, sel, frm, to, at):
        self.js.append(f"tl.fromTo({json.dumps(sel)}, {json.dumps(frm)}, {json.dumps(to)}, {at:.3f});")

    def to(self, sel, props, at):
        self.js.append(f"tl.to({json.dumps(sel)}, {json.dumps(props)}, {at:.3f});")

    def img(self, key: str | None) -> str:
        return f"assets/img-{re.sub(r'[^a-z0-9]+', '-', key.lower())}.jpg" if key else ""

    def icon(self, name: str, size: int, color: str = "#fff") -> str:
        p = self.icons.get(name)
        if not p:
            return ""
        svg = Path(p).read_text()
        return svg.replace("<svg", f'<svg class="ic" style="width:{size}px;height:{size}px;stroke:{color}"', 1)

    def scene(self, sc: dict, start: float, dur: float, first: bool) -> None:
        n = self.n = self.n + 1
        sid = f"m{n}"
        inner = getattr(self, "_" + sc["type"])(sc, sid, start, dur)
        self.body.append(f'<div id="{sid}" class="sc clip" data-start="{start:.3f}" data-duration="{dur + 0.25:.3f}">{inner}</div>')
        self.tw(f"#{sid}", {"opacity": 0, "scale": 1.08}, {"opacity": 1, "scale": 1, "duration": 0.32, "ease": "power3.out"}, start)
        if not first:
            self.js.append(f'tl.fromTo("#flash", {{opacity: 0.45}}, {{opacity: 0, duration: 0.22, immediateRender: false}}, {start:.3f});')

    # each scene type: returns inner html, adds its tweens
    def _hook(self, sc, sid, s, d):
        img = self.img(sc.get("image"))
        title = H.escape(sc["title"].upper())
        hot = (sc.get("hot") or "").upper()
        if hot and hot in title:
            title = title.replace(H.escape(hot), f'<span style="color:var(--hot)">{H.escape(hot)}</span>', 1)
        out = (f'<div id="{sid}p" class="ph round" style="left:140px;top:120px;width:800px;height:800px;background-image:url({img});box-shadow:0 0 140px var(--hot)"></div>' if img else "")
        out += f'<div id="{sid}k" class="kin" style="top:{940 if img else 420}px;font-size:{140 if len(title) < 40 else 112}px">{title}</div>'
        if img:
            self.tw(f"#{sid}p", {"scale": 2.4, "rotation": -8}, {"scale": 1, "rotation": 0, "duration": 0.9, "ease": "power4.out"}, s)
            self.to(f"#{sid}p", {"scale": 1.08, "duration": max(0.5, d - 0.9), "ease": "none"}, s + 0.9)
        self.tw(f"#{sid}k", {"opacity": 0, "scale": 2.2, "y": -60}, {"opacity": 1, "scale": 1, "y": 0, "duration": 0.45, "ease": "back.out(2.2)"}, s + 0.3)
        return out

    def _photo(self, sc, sid, s, d):
        img = self.img(sc["image"])
        if sc.get("round"):
            out = f'<div id="{sid}p" class="ph round" style="left:190px;top:170px;width:700px;height:700px;background-image:url({img})"></div>'
        else:
            out = f'<div id="{sid}p" class="ph" style="left:70px;top:150px;width:940px;height:760px;background-image:url({img})"></div>'
        for k, (key, x) in enumerate((("tag", 90), ("tag2", 560))):
            if sc.get(key):
                out += f'<div id="{sid}t{k}" class="tag{" h" if k else ""}" style="left:{x}px;top:{960 + k * 110}px">{H.escape(sc[key].upper())}</div>'
                self.tw(f"#{sid}t{k}", {"opacity": 0, "y": 40}, {"opacity": 1, "y": 0, "duration": 0.32, "ease": "back.out(2)"}, s + 0.5 + k * 0.5)
        self.tw(f"#{sid}p", {"x": -420, "rotation": -12, "opacity": 0}, {"x": 0, "rotation": 0, "opacity": 1, "duration": 0.55, "ease": "power3.out"}, s)
        self.to(f"#{sid}p", {"scale": 1.12, "rotation": 3 if sc.get("round") else 0, "duration": max(0.5, d - 0.5), "ease": "none"}, s + 0.55)
        return out

    def _text(self, sc, sid, s, d):
        hot = (sc.get("hot") or "").upper()
        rows = []
        for k, line in enumerate(sc["lines"]):
            t = H.escape(line.upper())
            if hot and hot in line.upper():
                t = t.replace(H.escape(hot), f'<span style="color:var(--a)">{H.escape(hot)}</span>', 1)
            rows.append(f'<div id="{sid}l{k}" class="kin" style="top:{420 + k * 230 - (115 if len(sc["lines"]) == 1 else 0)}px;font-size:{180 if len(line) <= 10 else 140 if len(line) <= 16 else 110}px">{t}</div>')
            self.tw(f"#{sid}l{k}", {"opacity": 0, "y": 100, "scale": 0.8}, {"opacity": 1, "y": 0, "scale": 1, "duration": 0.4, "ease": "back.out(2)"}, s + 0.15 + k * 0.35)
        self.to(f"#{sid} .kin", {"scale": 1.06, "duration": max(0.4, d - 0.8), "ease": "none"}, s + 0.8)
        return "".join(rows)

    def _count(self, sel, value, s, over):
        m = re.match(r"^(.*?)(\d[\d,]*(?:\.\d+)?)(.*)$", value)
        if not m:
            self.js.append(f'tl.set({json.dumps(sel)}, {{textContent: {json.dumps(value)}}}, {s:.3f});')
            return
        pre, digits, post = m.groups()
        end, dec = float(digits.replace(",", "")), (len(digits.split(".")[1]) if "." in digits else 0)
        for k in range(1, 23):
            v = end * (1 - (1 - k / 22) ** 3)
            txt = f"{v:,.{dec}f}" if "," in digits else f"{v:.{dec}f}"
            self.js.append(f'tl.set({json.dumps(sel)}, {{textContent: {json.dumps(pre + txt + post if k < 22 else value)}}}, {s + over * k / 22:.3f});')

    def _number(self, sc, sid, s, d):
        out = (f'<div id="{sid}n" class="kin" style="top:330px;font-size:{300 if len(sc["value"]) <= 5 else 220}px;color:var(--hot)">0</div>'
               + (f'<div id="{sid}b" class="kin" style="top:760px;font-size:84px">{H.escape(sc["label"].upper())}</div>' if sc.get("label") else ""))
        self._count(f"#{sid}n", sc["value"], s + 0.15, min(1.3, d * 0.5))
        self.js.append(f'tl.fromTo("#{sid}n", {{scale: 1}}, {{scale: 1.16, duration: 0.18, yoyo: true, repeat: 1}}, {s + 0.15 + min(1.3, d * 0.5):.3f});')
        if sc.get("label"):
            self.tw(f"#{sid}b", {"opacity": 0, "y": 40}, {"opacity": 1, "y": 0, "duration": 0.35}, s + 0.6)
        return out

    def _gauge(self, sc, sid, s, d):
        out = (f'<div style="position:absolute;left:150px;top:180px;width:110px;height:820px;border-radius:55px;border:8px solid #fff;background:#0b1030">'
               f'<div id="{sid}f" style="position:absolute;left:10px;right:10px;bottom:10px;height:60px;border-radius:40px;background:linear-gradient(var(--hot),#ffd23f)"></div></div>'
               f'<div id="{sid}n" class="kin" style="left:300px;top:380px;font-size:230px;color:var(--hot);text-align:left">0</div>'
               + (f'<div id="{sid}b" class="kin" style="left:300px;top:640px;font-size:76px;text-align:left">{H.escape(sc["label"].upper())}</div>' if sc.get("label") else ""))
        over = min(1.6, d * 0.6)
        self.tw(f"#{sid}f", {"height": 60}, {"height": 780, "duration": over, "ease": "power1.in"}, s + 0.2)
        self._count(f"#{sid}n", sc["value"], s + 0.2, over)
        if sc.get("label"):
            self.tw(f"#{sid}b", {"opacity": 0, "x": 40}, {"opacity": 1, "x": 0, "duration": 0.35}, s + 0.6)
        return out

    def _compare(self, sc, sid, s, d):
        out = ""
        for k, side in enumerate(("a", "b")):
            x = 70 + k * 500
            img = self.img(sc.get(f"{side}_image"))
            out += (f'<div id="{sid}{side}" style="position:absolute;left:{x}px;top:180px;width:440px;height:900px">'
                    + (f'<div class="ph round" style="left:20px;top:0;width:400px;height:400px;background-image:url({img})"></div>' if img else
                       f'<div class="box" style="left:20px;top:100px;width:400px;height:200px">{H.escape(sc[side].upper())}</div>')
                    + f'<div class="kin" style="left:0;right:0;top:440px;font-size:76px">{H.escape(sc[side].upper())}</div>'
                    + (f'<div id="{sid}{side}v" class="kin" style="left:0;right:0;top:560px;font-size:110px;color:{"var(--a)" if k == 0 else "var(--hot)"}">{H.escape(sc[f"{side}_value"])}</div>' if sc.get(f"{side}_value") else "")
                    + "</div>")
            self.tw(f"#{sid}{side}", {"opacity": 0, "x": -300 if k == 0 else 300}, {"opacity": 1, "x": 0, "duration": 0.45, "ease": "power3.out"}, s + k * 0.35)
            if sc.get(f"{side}_value"):
                self.tw(f"#{sid}{side}v", {"opacity": 0, "scale": 2}, {"opacity": 1, "scale": 1, "duration": 0.35, "ease": "back.out(2)"}, s + 0.9 + k * 0.3)
        out += f'<div id="{sid}vs" class="kin" style="top:330px;font-size:120px;color:#ffd23f">VS</div>'
        self.tw(f"#{sid}vs", {"opacity": 0, "scale": 0}, {"opacity": 1, "scale": 1, "duration": 0.3, "ease": "back.out(2.5)"}, s + 0.6)
        return out

    def _orbit(self, sc, sid, s, d):
        ci, bi = self.img(sc.get("center_image")), self.img(sc.get("body_image"))
        center = (f'<div class="ph round" style="left:390px;top:340px;width:300px;height:300px;background-image:url({ci})"></div>' if ci else
                  '<div class="ph round" style="left:390px;top:340px;width:300px;height:300px;background:radial-gradient(circle,#fff6c8,#ffcf3a 45%,#ff7a00 70%,#ff4d0000 72%);box-shadow:0 0 180px #ffb300"></div>')
        body = (f'<div class="ph round" style="left:300px;top:-75px;width:150px;height:150px;background-image:url({bi})"></div>' if bi else
                '<div class="ph round" style="left:300px;top:-60px;width:120px;height:120px;background:radial-gradient(circle at 35% 35%,#cfe9ff,#3b82f6 60%,#1e3a8a)"></div>')
        out = (center + f'<div style="position:absolute;left:150px;top:100px;width:780px;height:780px;border-radius:50%;border:3px dashed #ffffff40"></div>'
               f'<div id="{sid}o" style="position:absolute;left:540px;top:490px;width:0;height:0">{body}</div>'
               f'<div class="tag" style="left:330px;top:950px">{H.escape(sc["body"].upper())} ↻ {H.escape(sc["center"].upper())}</div>')
        self.tw(f"#{sid}o", {"rotation": -30}, {"rotation": 330, "duration": max(1.0, d), "ease": "none"}, s)
        return out

    def _flow(self, sc, sid, s, d):
        k_ = len(sc["steps"])
        gap = 860 / k_
        out = ""
        for k, (step, ic) in enumerate(zip(sc["steps"], sc["icons"])):
            y = 140 + k * gap
            out += (f'<div id="{sid}s{k}" style="position:absolute;left:110px;top:{y:.0f}px;width:860px;height:{gap - 60:.0f}px;display:flex;align-items:center;gap:40px;'
                    f'border-radius:28px;background:#0b1030d9;border:4px solid var(--a);padding:0 40px;font-size:{78 if k_ <= 3 else 64}px">'
                    f'{self.icon(ic, int(min(140, gap - 100)), "#fff") if ic else ""}<span>{H.escape(step.upper())}</span></div>')
            each = min(1.0, (d - 0.3) / k_)
            self.tw(f"#{sid}s{k}", {"opacity": 0, "x": -200}, {"opacity": 1, "x": 0, "duration": 0.35, "ease": "back.out(1.6)"}, s + 0.1 + k * each)
            self.js.append(f'tl.fromTo("#{sid}s{k}", {{borderColor: "#ffffff"}}, {{borderColor: "{self.t["hot"]}", duration: 0.3, immediateRender: false}}, {s + 0.3 + k * each:.3f});')
        return out

    def _split(self, sc, sid, s, d):
        img = self.img(sc.get("image"))
        base = (f'<div class="ph round" style="left:190px;top:200px;width:700px;height:700px;background-image:url({img})"></div>' if img else
                '<div class="ph round" style="left:190px;top:200px;width:700px;height:700px;background:#1e293b"></div>')
        out = (base + f'<div id="{sid}l" style="position:absolute;left:190px;top:200px;width:350px;height:700px;border-radius:350px 0 0 350px;background:var(--hot);mix-blend-mode:color;opacity:0"></div>'
               f'<div id="{sid}r" style="position:absolute;left:540px;top:200px;width:350px;height:700px;border-radius:0 350px 350px 0;background:#2563eb;mix-blend-mode:color;opacity:0"></div>'
               f'<div id="{sid}li" style="position:absolute;left:70px;top:90px">{self.icon(sc.get("left_icon") or "", 170, "#ffd23f")}</div>'
               f'<div id="{sid}ri" style="position:absolute;right:200px;top:90px">{self.icon(sc.get("right_icon") or "", 160, "#9bdcff")}</div>'
               f'<div id="{sid}lt" class="tag h" style="left:110px;top:960px">{H.escape(sc["left"].upper())}</div>'
               f'<div id="{sid}rt" class="tag" style="left:600px;top:960px">{H.escape(sc["right"].upper())}</div>')
        half = max(0.6, d / 2.4)
        self.tw(f"#{sid}l", {"opacity": 0}, {"opacity": 0.75, "duration": 0.4}, s + 0.3)
        self.tw([f"#{sid}li", f"#{sid}lt"], {"opacity": 0, "scale": 0.4}, {"opacity": 1, "scale": 1, "duration": 0.35, "ease": "back.out(2)"}, s + 0.35)
        self.tw(f"#{sid}r", {"opacity": 0}, {"opacity": 0.75, "duration": 0.4}, s + 0.3 + half)
        self.tw([f"#{sid}ri", f"#{sid}rt"], {"opacity": 0, "scale": 0.4}, {"opacity": 1, "scale": 1, "duration": 0.35, "ease": "back.out(2)"}, s + 0.35 + half)
        return out

    def _icons(self, sc, sid, s, d):
        k_ = len(sc["icons"])
        col = 940 / k_
        out = ""
        for k, (ic, lab) in enumerate(zip(sc["icons"], sc["labels"])):
            x = 70 + k * col
            out += (f'<div id="{sid}i{k}" style="position:absolute;left:{x:.0f}px;top:330px;width:{col:.0f}px;text-align:center">'
                    f'<div style="display:inline-block">{self.icon(ic, int(min(260, col - 30)), self.t["a"] if k % 2 == 0 else self.t["hot"])}</div>'
                    f'<div style="font-size:64px;margin-top:20px">{H.escape(lab.upper())}</div></div>')
            self.tw(f"#{sid}i{k}", {"opacity": 0, "scale": 0, "rotation": -25}, {"opacity": 1, "scale": 1, "rotation": 0, "duration": 0.38, "ease": "back.out(2.4)"}, s + 0.15 + k * min(0.45, d / (k_ + 1)))
        self.js.append(f'tl.to("#{sid} [id^={sid}i]", {{y: -18, duration: 0.35, yoyo: true, repeat: {max(1, int(d / 0.7))}, ease: "sine.inOut", stagger: 0.1}}, {s + 1.0:.3f});')
        return out

    def _map(self, sc, sid, s, d):
        from . import maps
        svg = maps.svg(sc["highlight"], 940, 760, focus=True)
        out = (f'<div style="position:absolute;left:70px;top:130px;width:940px;height:760px;border-radius:28px;overflow:hidden;border:3px solid #2e4566;background:#06101f">'
               f'<div id="{sid}mp" style="width:940px;height:760px">{svg}</div></div>'
               + (f'<div id="{sid}lb" class="kin" style="top:930px;font-size:80px">{H.escape(sc["label"].upper())}</div>' if sc.get("label") else ""))
        self.js.append(f'document.querySelectorAll("#{sid} .land").forEach(function (p) {{ p.setAttribute("fill", "#1c2a3f"); p.setAttribute("stroke", "#2e4566"); }});')
        self.tw(f"#{sid}mp", {"scale": 0.55}, {"scale": 1, "duration": 0.9, "ease": "power3.out"}, s)
        self.js.append(f'tl.to("#{sid} .hl", {{fill: "#ffd23f", duration: 0.35, stagger: 0.3}}, {s + 0.6:.3f});')
        if sc.get("label"):
            self.tw(f"#{sid}lb", {"opacity": 0, "y": 30}, {"opacity": 1, "y": 0, "duration": 0.35}, s + 0.8)
        return out

    def _outro(self, sc, sid, s, d):
        out = (f'<img id="{sid}g" src="assets/logo.png" style="position:absolute;left:240px;top:200px;width:600px;height:600px">'
               f'<div id="{sid}k" class="kin" style="top:860px;font-size:92px">{H.escape(sc.get("text", "").upper())}</div>')
        self.tw(f"#{sid}g", {"scale": 0, "rotation": -90}, {"scale": 1, "rotation": 0, "duration": 0.7, "ease": "back.out(1.6)"}, s)
        self.tw(f"#{sid}k", {"opacity": 0, "y": 50}, {"opacity": 1, "y": 0, "duration": 0.4}, s + 0.5)
        return out


def captions(comp: Comp, chunks: list) -> str:
    """Word-by-word captions from shorts_edit.timed_chunks: each chunk pops in, the spoken word lights up."""
    out = []
    for g, (a, z, _text, words) in enumerate(chunks):
        out.append(f'<div class="cw" id="g{g}">' + "".join(f'<span id="g{g}w{k}">{H.escape(w.upper().strip(",.;:"))}</span>' for k, (w, _, _) in enumerate(words)) + "</div>")
        comp.js.append(f'tl.set("#g{g}", {{opacity: 1}}, {a:.3f}); tl.set("#g{g}", {{opacity: 0}}, {z:.3f});')
        comp.js.append(f'tl.fromTo("#g{g}", {{scale: 0.7}}, {{scale: 1, duration: 0.18, ease: "back.out(3)"}}, {a:.3f});')
        for k, (w, ws, we) in enumerate(words):
            col = comp.t["hot"] if k % 3 == 1 else comp.t["a"]
            comp.js.append(f'tl.to("#g{g}w{k}", {{color: "{col}", scale: 1.06, duration: 0.08}}, {ws:.3f}); tl.to("#g{g}w{k}", {{color: "#ffffff", scale: 1, duration: 0.1}}, {we:.3f});')
    return '<div id="cap">' + "".join(out) + "</div>"


def background(theme: dict, seconds: float) -> tuple[str, list[str]]:
    dots = "".join(f'<circle cx="{(i * 397) % 1080}" cy="{(i * 641) % 2200}" r="{0.8 + (i % 4) * 0.6}" opacity="{0.25 + (i % 5) * 0.12}"/>' for i in range(220))
    a, b = theme["neb"]
    html = (f'<svg class="layer" id="st1" width="1080" height="2200" fill="{theme["dots"]}">{dots}</svg>'
            f'<svg class="layer" id="st2" width="1080" height="2200" fill="{theme["dots"]}" style="opacity:.5;transform:scale(1.4)">{dots}</svg>'
            f'<div class="neb" id="nb1" style="left:-200px;top:200px;width:900px;height:900px;background:radial-gradient(circle,{a},transparent 65%)"></div>'
            f'<div class="neb" id="nb2" style="right:-300px;top:900px;width:1000px;height:1000px;background:radial-gradient(circle,{b},transparent 65%)"></div>')
    js = [f'tl.fromTo("#st1", {{y: 0}}, {{y: -260, duration: {seconds:.2f}, ease: "none"}}, 0);',
          f'tl.fromTo("#st2", {{y: 0}}, {{y: -520, duration: {seconds:.2f}, ease: "none"}}, 0);',
          f'tl.fromTo("#nb1", {{x: 0, y: 0}}, {{x: 200, y: -150, duration: {seconds:.2f}, ease: "sine.inOut"}}, 0);',
          f'tl.fromTo("#nb2", {{x: 0}}, {{x: -220, duration: {seconds:.2f}, ease: "sine.inOut"}}, 0);']
    return html, js


def build(plan: list[dict], chunks: list, *, kind: str, seconds: float, images: dict[str, Path], icons: dict[str, Path],
          voice: Path, music: Path | None = None, sfx: dict[str, Path] | None = None, logo: Path | None = None) -> tuple[str, dict[str, Path]]:
    """The whole Short: (html, assets). `plan` = [{type, start, end, ...}] checked scenes covering the voice; `chunks` = timed captions."""
    theme = THEMES.get(kind, THEMES["space"])
    comp = Comp(theme, {}, icons)
    bg, bjs = background(theme, seconds)
    for k, sc in enumerate(plan):
        comp.scene(sc, sc["start"], max(0.4, sc["end"] - sc["start"]), first=(k == 0))
    caps = captions(comp, chunks)
    audio = [f'<audio id="vo" src="assets/voice.wav" data-start="0" data-duration="{seconds:.2f}"></audio>']
    if music:
        audio.append(f'<audio id="bgm" src="assets/music{Path(music).suffix}" data-start="0" data-duration="{seconds:.2f}" data-volume="0.12" data-fade-out="2"></audio>')
    fx = []
    for k, sc in enumerate(plan):
        if k and (sfx or {}).get("whoosh"):
            fx.append(("whoosh", sc["start"] - 0.08, 0.32))
        if sc["type"] in ("number", "gauge", "hook") and (sfx or {}).get("impact"):
            fx.append(("impact", sc["start"] + (0.3 if sc["type"] == "hook" else 1.3), 0.5))
    for n, (name, at, vol) in enumerate(fx):
        audio.append(f'<audio id="fx{n}" src="assets/{name}{Path(sfx[name]).suffix}" data-start="{max(0.0, at):.2f}" data-duration="2.5" data-volume="{vol}"></audio>')
    wm = '<img id="wm" src="assets/logo.png">' if logo else ""
    css = (f":root{{--a:{theme['a']};--hot:{theme['hot']}}}#root{{background:{theme['bg']}}}" + CSS
           + hf.font_face("Anton", "Anton-Regular.ttf", "400") + hf.font_face("Bebas Neue", "BebasNeue-Regular.ttf", "400"))
    page = hf.page(bg + "".join(comp.body) + caps + wm + '<div id="flash"></div>' + "".join(audio), "\n".join(bjs + comp.js),
                   width=W, height=HGT, seconds=seconds, css=css)
    assets = {"Anton-Regular.ttf": hf.FONTS / "Anton-Regular.ttf", "BebasNeue-Regular.ttf": hf.FONTS / "BebasNeue-Regular.ttf", "voice.wav": voice}
    assets.update({f"img-{re.sub(r'[^a-z0-9]+', '-', k.lower())}.jpg": Path(v) for k, v in images.items()})
    if music:
        assets[f"music{Path(music).suffix}"] = Path(music)
    for name in ("whoosh", "impact"):
        if (sfx or {}).get(name):
            assets[f"{name}{Path(sfx[name]).suffix}"] = Path(sfx[name])
    if logo:
        assets["logo.png"] = logo
    return page, assets


STOP = set("a an and are as at be but by for from had has have he her his i in is it its me my of on or our she so that the their them they this to was we "
           "were what when which who with you your had been not no one would could there then than into out up just all very even also does do did".split())


def keywords(text: str, n: int = 3, avoid: str = "") -> str:
    """The line's telling words, in order (no little words), at most `n`, unlike `avoid` (what is already on screen)."""
    seen = set(re.findall(r"[a-z]+", avoid.lower()))
    words = [w.strip(",.;:!?\"'") for w in text.split()]
    keep = [w for w in words if w.lower() not in STOP and len(w) > 2]
    fresh = [w for w in keep if w.lower() not in seen] or keep
    fresh = [w for k, w in enumerate(fresh) if w.lower() not in (x.lower() for x in fresh[:k])]      # "climbs and climbs" once
    return " ".join((fresh[-n:] if len(fresh) > n else fresh))


def _filler(beat_text: str, shown: str, last_image: str | None) -> dict:
    """A second scene for a long line: the Short's latest photo again with the line's key words as a callout, but only when the line speaks of
    that photo's subject (the Alps do not belong on a line about trade); else those words as text."""
    words = keywords(beat_text, 3, shown)
    said = set(re.findall(r"[a-z]+", beat_text.lower()))
    if last_image and any(w in said for w in re.findall(r"[a-z]+", last_image.lower()) if w not in STOP and len(w) > 2):
        return {"type": "photo", "image": last_image, "tag": words, "round": True}
    return {"type": "text", "lines": [words]}


def timeline(plan: list[dict], beats: list[dict], seconds: float) -> list[dict]:
    """Places planned scenes on the clock: each scene names its beat ("beat": i, optional "part": 0/1 of a split beat); a beat longer than
    MAX_SCENE with one scene is split in two (the second half a `text` scene from the beat's own words) so the picture keeps changing."""
    t, spans = 0.0, []
    for b in beats:
        spans.append((t, t + b["dur"]))
        t += b["dur"]
    by_beat: dict[int, list[dict]] = {}
    for sc in plan:
        by_beat.setdefault(int(sc.get("beat", 0)), []).append(sc)
    out, last_image = [], None
    for i, (a, z) in enumerate(spans):
        mine = by_beat.get(i) or [_filler(beats[i]["text"], "", last_image)]
        if len(mine) == 1 and z - a > MAX_SCENE and mine[0]["type"] not in ("outro", "orbit", "number", "gauge"):
            shown = json.dumps(mine[0])
            mine = mine + [_filler(beats[i]["text"], shown, mine[0].get("image") or last_image)]
        for sc in mine:
            last_image = sc.get("image") or sc.get("b_image") or sc.get("body_image") or last_image
        step = (z - a) / max(1, len(mine))
        for k, sc in enumerate(mine):
            out.append({**sc, "start": round(a + k * step, 3), "end": round(a + (k + 1) * step, 3)})
    if out:
        out[-1]["end"] = round(seconds, 3)
    return out


def render(page: str, assets: dict[str, Path], out: Path) -> Path:
    return hf.render(page, out, assets=assets, timeout=1200)


# ---------- the Scene Planner ----------
SHAPES = {
    "hook": '{"type": "hook", "title": "2-5 words from the line, a question if it is one", "hot": "one word of the title", "image": "the thing it is about"}',
    "photo": '{"type": "photo", "image": "the real thing to show, e.g. Saturn / human heart / Nile River / flag of Nepal", "tag": "2-4 words from the line", "round": true for a planet or moon}',
    "text": '{"type": "text", "lines": ["1-3 words", "1-3 words"], "hot": "the key word"}',
    "number": '{"type": "number", "value": "a figure the line says, digits and unit, e.g. 460°C", "label": "2-5 words from the line"}',
    "gauge": '{"type": "gauge", "value": "a figure the line says", "label": "2-4 words"}',
    "compare": '{"type": "compare", "a": "thing", "b": "thing", "a_image": "thing to show", "b_image": "thing to show", "a_value": "only if the line says it", "b_value": "..."}',
    "orbit": '{"type": "orbit", "center": "Sun", "body": "Earth", "center_image": "...", "body_image": "..."}',
    "flow": '{"type": "flow", "steps": ["2-4 steps of 1-3 words"], "icons": ["an icon per step from the list"]}',
    "split": '{"type": "split", "left": "1-2 words", "right": "1-2 words", "left_icon": "...", "right_icon": "...", "image": "..."}',
    "icons": '{"type": "icons", "icons": ["2-4 icons from the list"], "labels": ["1-2 words each"]}',
    "map": '{"type": "map", "highlight": ["countries the line names"], "label": "2-5 words"}',
}


def _country(subject: str) -> str | None:
    """The country a subject such as "flag of Nepal" names, as the map data spells it; None for a bare "flag"."""
    from . import maps
    toks = re.findall(r"[A-Za-z]+", re.sub(r"\bflags?\b|\bof\b|\bthe\b", " ", subject, flags=re.I))
    for n in range(len(toks), 0, -1):                                   # "South Africa" before "Africa"
        for i in range(len(toks) - n + 1):
            try:
                hit = maps.known(" ".join(toks[i:i + n]))
            except Exception:  # noqa: BLE001 - no map data: no flag
                return None
            if hit:
                return hit
    return None


def ask(beats: list[dict], kind: str, icon_names: list[str]) -> str:
    kinds = [k for k in SHAPES if k != "map" or kind == "geography"]
    listing = "\n".join(f"{i}. ({b['dur']:.1f} s) {b['text']}" for i, b in enumerate(beats) if b.get("kind") != "outro")
    return ("You plan the visuals of a vertical YouTube Short that is animated every second (no stock video). For each numbered line give one scene, "
            f"or two scenes for a line longer than {MAX_SCENE:.0f} seconds. Scene types (JSON):\n" + "\n".join(f"- {SHAPES[k]}" for k in kinds) + "\n"
            "Rules: line 0 opens with a hook. Every word shown must come from that same line; a figure only if that line says it. An image names one real, "
            "photographable thing the line is about (a planet, an organ, a river, a country), never an idea. Vary the types: never the same type three times "
            "in a row; use the real thing (photo) often. Icons only from: " + ", ".join(icon_names) + ".\n"
            'Answer with one entry per line, in order, copying the line number: {"lines": [{"line": 0, "scenes": [{"type": "hook", ...}]}, '
            '{"line": 1, "scenes": [...]}, ...]}.\n\nLines:\n' + listing)


LOOK_Q = ("A short {kind} video will show this picture while the narrator talks about \"{subject}\". Is {subject} itself the main thing in it: a real "
          "photo{or_drawing} of the right kind of thing? You cannot always recognise the exact place or object, so judge the kind, not the name. Answer NO if "
          "it mainly shows people, soldiers or a historical event, a logo, text or a poster, a map or a chart, machinery or buildings that are not {subject}, or a different kind of thing "
          "(for example stars or a galaxy for a place on Earth, a rocket for a body part). Answer YES or NO first, then at most ten words.")
LOOKS_PER_SUBJECT = 3                     # Cloudflare's free day is shared with the E-books Manager: at most three looks for one subject


def judge_with(store, kind: str):
    """The vision check for visuals.picture: True = it shows the subject, False = it does not (or three candidates were already refused),
    None = it could not be looked at (no Cloudflare key, the free day used up): the title-checked picture stands."""
    from ..services import cfai
    looks: dict[str, int] = {}

    async def judge(rec: dict, subject: str) -> bool | None:
        looks[subject] = looks.get(subject, 0) + 1
        if looks[subject] > LOOKS_PER_SUBJECT:
            return False
        try:
            data = Path(rec["path"]).read_bytes()
            answer = await cfai.look(store, data, LOOK_Q.format(kind=kind, subject=subject, or_drawing=" or a clear drawing" if kind == "body" else ""))
        except Exception:  # noqa: BLE001 - could not look: the title check alone
            return None
        return verdict(answer)
    return judge


def verdict(answer: str) -> bool | None:
    """YES / NO from the vision model's answer ("**Yes**, it shows...", "No, it is Neptune"); None when it says neither."""
    m = re.search(r"\b(yes|no)\b", answer[:60], re.I)
    return None if not m else m.group(1).lower() == "yes"
    return judge


async def plan_short(llm, beats: list[dict], kind: str, outro: str, client, store=None) -> dict:
    """{plan: the checked scenes, images, icons, credits (one line per picture), refused: proposed scenes the checks threw out}. No answer = an empty plan
    (timeline() then fills every line from its own words)."""
    from ..services import visuals
    try:
        got = await llm.json(ask(beats, kind, list(visuals.ICONS)), tier="writer", max_tokens=3000)
    except Exception:  # noqa: BLE001 - no planner: the timeline's fallback scenes
        got = None
    raw = []
    for entry in ((got or {}).get("lines") or []) if isinstance(got, dict) else []:
        if isinstance(entry, dict) and isinstance(entry.get("line"), int):
            raw += [{**x, "beat": entry["line"]} for x in (entry.get("scenes") or []) if isinstance(x, dict)]
    if isinstance(got, dict) and isinstance(got.get("scenes"), list):                     # the flat shape, if the model answers that way
        raw += [x for x in got["scenes"] if isinstance(x, dict) and isinstance(x.get("beat"), int)]
    raw = [x for x in raw if 0 <= x["beat"] < len(beats)]
    subjects = []
    for sc in raw:
        for k in ("image", "a_image", "b_image", "center_image", "body_image"):
            v = " ".join(str(sc.get(k) or "").split())[:40]
            sc[k] = v
            if v and v not in subjects:
                subjects.append(v)
    images: dict[str, Path] = {}
    credits: list[str] = []
    for subj in subjects[:6]:                                           # at most six pictures to find for one Short
        if re.search(r"\bflags?\b", subj, re.I):                        # a flag is the country's own flag from Commons, never a search hit
            country = _country(subj)
            rec = await visuals.flag(client, country) if country else None
        elif kind == "geography" and not (_country(subj) or re.search(r"\b[A-Z][a-z]+", subj)):
            rec = None                                                  # "home" or "town" searched in NASA's library gives a star cluster: places by name only
        else:
            rec = await visuals.picture(client, kind, subj, judge=judge_with(store, kind) if store is not None else None)
        if rec:
            images[subj] = Path(rec["path"])
            line = f"{rec.get('title') or subj}: {rec.get('credit') or rec.get('source')} ({rec.get('license') or 'see page'}), {rec.get('page')}"
            if line not in credits:
                credits.append(line)
    names = {n for sc in raw for n in (sc.get("icons") or []) + [sc.get("left_icon"), sc.get("right_icon")] if n in visuals.ICONS}
    icons = {}
    for n in names:
        p = await visuals.icon(client, n)
        if p:
            icons[n] = Path(p)
    found = set(images)
    plan, refused = [], []
    for sc in raw:
        if beats[sc["beat"]].get("kind") == "outro":
            continue
        placed = None
        for i in sorted(range(max(0, sc["beat"] - 2), min(len(beats), sc["beat"] + 3)), key=lambda i: abs(i - sc["beat"])):
            ok = beats[i].get("kind") != "outro" and (sc["type"] != "hook" or i == 0) and check(sc, beats[i]["text"], found, set(icons))
            if ok:                                                      # the model's line numbers drift: the scene goes on the nearby line it is made of
                placed = {**ok, "beat": i}
                break
        if placed:
            plan.append(placed)
        else:
            refused.append(sc)
    for i, b in enumerate(beats):                                       # the sign-off is always the logo and the follow line
        if b.get("kind") == "outro":
            plan.append({"type": "outro", "text": outro, "beat": i})
    return {"plan": plan, "images": images, "icons": icons, "credits": credits, "refused": refused}
