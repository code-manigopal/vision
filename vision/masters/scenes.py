"""Animated scenes for Shorts (HyperFrames): a few fixed templates the model may pick for a line instead of stock footage.

The model never writes HTML: per line it names a template and gives short labels (JSON); `check` keeps a scene only if the
template is known, every label is short, and every figure on it is one the spoken line itself says. The scenes of a Short are
rendered in one go (`render_shots`) and cut into one silent clip per beat, which the Editor uses like footage (no slow zoom).
No model answer, a refused scene or a failed render = the beat keeps its stock footage. Captions, voice, music and sound
effects are added by the Editor as always, so the scenes keep clear of the captions' band (about 940-1200 px).

Templates by kind (channel option `diagrams`: the kinds that may use them):
  science  orbit, compare, flow, cycle, number
  money    compare, number, growth (a curve's shape only, never figures, always "Illustration, not a promise"), breakdown,
           myth (a belief struck through, then what is true), checklist; no label may promise money (youtube.PROMISE, TOLD_PROMISE)
  story    chat (messages appearing; their words come from the line), quote (words taken whole from the line), timejump
           ("three years later", a figure only if the line says it), split (the two choices the person faced); sparingly
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

from ..services import hyperframes as hf

W, H = 1080, 1920
TEMPLATES = {
    "science": {
        "orbit": 'a body circling another, one side always shown: {"template": "orbit", "center": "Earth", "body": "Moon", "note": "same side faces Earth"}',
        "compare": 'two things side by side: {"template": "compare", "a": "Mount Everest", "b": "Mariana Trench", "a_value": "8,849 m", "b_value": "10,935 m"} '
                   '(values only if the line says them, else leave them out)',
        "flow": 'a process in 2-4 steps: {"template": "flow", "steps": ["Sunlight", "Leaves", "Sugar"]}',
        "cycle": 'a loop of 3-5 stages: {"template": "cycle", "steps": ["Evaporation", "Clouds", "Rain", "Rivers"]}',
        "number": 'one striking figure the line says: {"template": "number", "value": "59%", "label": "of the Moon seen from Earth"}',
    },
    "money": {
        "compare": 'two options side by side: {"template": "compare", "a": "Fixed deposit", "b": "Recurring deposit"} (add "a_value"/"b_value" only if the line says them)',
        "number": 'one figure the line says: {"template": "number", "value": "50%", "label": "of income for needs"}',
        "growth": 'the shape of a change over time, no figures: {"template": "growth", "shape": "compound" or "inflation", "label": "Interest earns interest"}',
        "breakdown": 'a whole split into 2-4 parts: {"template": "breakdown", "parts": [{"label": "Needs", "share": "50%"}, {"label": "Wants", "share": "30%"}]} '
                     '(shares only if the line says them)',
        "myth": 'a common belief, then what is true: {"template": "myth", "myth": "Credit cards are free money", "fact": "Unpaid balances charge interest"}',
        "checklist": 'things to check, 2-4: {"template": "checklist", "items": ["Lock-in period", "Interest rate", "Penalty"]}',
    },
    "story": {
        "chat": 'only when the line is about a text message or chat: {"template": "chat", "messages": [{"from": "them", "text": "We need to talk"}, {"from": "me", "text": "About what?"}]} '
                '(1-3 messages, words taken from the line)',
        "quote": 'the turning-point line, big and slow: {"template": "quote", "text": "words copied exactly from the line, at most 12"}',
        "timejump": 'when the story jumps in time: {"template": "timejump", "text": "Three years later"}',
        "split": 'when the person faced a choice: {"template": "split", "a": "Tell the truth", "b": "Stay silent"}',
    },
}
CSS = """
#root{background:#05070d;font-family:Anton,Impact,sans-serif;color:#fff}
.scene{position:absolute;inset:0}
.lbl{position:absolute;left:0;right:0;text-align:center;letter-spacing:1px}
.gold{color:#FBCA03}
.box{position:absolute;left:190px;width:700px;height:140px;border:5px solid #FBCA03;border-radius:28px;background:#0d1424;display:flex;align-items:center;
     justify-content:center;font-size:64px;text-align:center;line-height:1.05;padding:0 20px}
.arrow{position:absolute;left:520px;width:40px;height:90px}
.cnode{position:absolute;width:300px;margin-left:-150px;text-align:center;font-size:54px;line-height:1.05;opacity:.35}
.bar{position:absolute;bottom:0;width:240px;border-radius:24px 24px 0 0}
"""
STARS = "".join(f'<circle cx="{(i * 397) % W}" cy="{(i * 641) % H}" r="{1 + (i % 3) * 0.7}" opacity="{0.2 + (i % 5) * 0.1}"/>' for i in range(140))


def _short(s, words: int = 4, chars: int = 30) -> str | None:
    s = " ".join(str(s or "").split())
    return s if s and len(s) <= chars and len(s.split()) <= words else None


def _figures_ok(text: str, line: str) -> bool:
    """Every figure in `text` is one the spoken line says."""
    said = {x.replace(",", "") for x in re.findall(r"\d[\d,]*(?:\.\d+)?", line)}
    return all(x.replace(",", "") in said for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text))


def _promise(text: str) -> bool:
    from .youtube import PROMISE, TOLD_PROMISE
    return bool(PROMISE.search(text) or TOLD_PROMISE.search(text))


def check(scene: dict, line: str, kinds: set[str]) -> dict | None:
    """The scene as it will be drawn, or None when it breaks a rule (unknown template, long label, a figure the line does not say)."""
    if not isinstance(scene, dict):
        return None
    t = scene.get("template")
    if not any(t in TEMPLATES.get(k, {}) for k in kinds):
        return None
    def lab(key, words=4, chars=30):
        v = _short(scene.get(key), words, chars)
        return v if v and _figures_ok(v, line) and not _promise(v) else None
    if "money" in kinds and _promise(json.dumps(scene)):            # finance: nothing on screen may promise money
        return None
    if t == "orbit":
        out = {"center": lab("center", 2, 16), "body": lab("body", 2, 16), "note": lab("note", 5, 34) or ""}
        return {"template": t, **out} if out["center"] and out["body"] else None
    if t == "compare":
        out = {"a": lab("a", 3, 20), "b": lab("b", 3, 20), "a_value": lab("a_value", 2, 14) or "", "b_value": lab("b_value", 2, 14) or ""}
        if not (out["a"] and out["b"]):
            return None
        if bool(out["a_value"]) != bool(out["b_value"]):
            out["a_value"] = out["b_value"] = ""
        return {"template": t, **out}
    if t in ("flow", "cycle"):
        lo, hi = (2, 4) if t == "flow" else (3, 5)
        steps = [_short(x, 3, 18) for x in (scene.get("steps") or [])][:hi]
        if not all(x and _figures_ok(x, line) for x in steps):        # a step left out would change what the chain says: the whole scene goes
            return None
        return {"template": t, "steps": steps} if len(steps) >= lo else None
    if t == "number":
        v, l = _short(scene.get("value"), 2, 10), lab("label", 6, 36)
        return {"template": t, "value": v, "label": l} if v and l and re.search(r"\d", v) and _figures_ok(v, line) else None
    if t == "growth":
        shape, l = scene.get("shape"), lab("label", 6, 36)
        return {"template": t, "shape": shape, "label": l} if shape in ("compound", "inflation") and l and not re.search(r"\d", l) else None
    if t == "breakdown":
        parts = scene.get("parts") or []
        if not 2 <= len(parts) <= 4 or not all(isinstance(x, dict) for x in parts):
            return None
        labels = [_short(x.get("label"), 3, 16) for x in parts]
        shares = [_short(x.get("share"), 1, 5) or "" for x in parts]
        if not all(labels) or any(_promise(x) for x in labels):
            return None
        nums = [_num(x) for x in shares]
        if not (all(shares) and all(_figures_ok(x, line) for x in shares) and all(x is not None for x in nums) and abs(sum(nums) - 100) < 0.5):
            shares = [""] * len(parts)                  # shares only when the line says every one and they make a whole
        return {"template": t, "parts": [{"label": a, "share": b} for a, b in zip(labels, shares)]}
    if t == "myth":
        m, f = lab("myth", 7, 44), lab("fact", 7, 44)
        return {"template": t, "myth": m, "fact": f} if m and f else None
    if t == "chat":
        msgs = (scene.get("messages") or [])[:3]
        said = set(re.findall(r"[a-z']+", line.lower()))
        out = []
        for m_ in msgs:
            txt = _short((m_ or {}).get("text"), 8, 48) if isinstance(m_, dict) else None
            words_ = re.findall(r"[a-z']+", (txt or "").lower())
            if not txt or not words_ or sum(w in said for w in words_) / len(words_) < 0.7:     # the messages are the line's own words
                return None
            out.append({"from": "me" if m_.get("from") == "me" else "them", "text": txt})
        return {"template": t, "messages": out} if out else None
    if t == "quote":
        q = " ".join(str(scene.get("text") or "").split()).strip(' "\'')
        squash = lambda x: re.sub(r"[^a-z0-9 ]", "", x.lower())
        return {"template": t, "text": q} if q and len(q.split()) <= 12 and squash(q) in squash(line) else None
    if t == "timejump":
        v = lab("text", 4, 24)
        return {"template": t, "text": v} if v else None
    if t == "split":
        a, b = lab("a", 4, 24), lab("b", 4, 24)
        return {"template": t, "a": a, "b": b} if a and b else None
    if t == "checklist":
        items = [_short(x, 4, 24) for x in (scene.get("items") or [])][:4]
        if len(items) < 2 or not all(x and _figures_ok(x, line) and not _promise(x) for x in items):
            return None
        return {"template": t, "items": items}
    return None


def ask(lines: list[str], kinds: set[str], most: int) -> str:
    tmpl = "\n".join(f"- {name}: {desc}" for k in sorted(kinds) for name, desc in TEMPLATES.get(k, {}).items())
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(lines))
    return ("This is the script of a vertical YouTube Short, one numbered line per shot. Most shots show stock footage. Pick at most "
            f"{most} lines (never line 0) where a simple animated diagram would explain the line better than footage, using only these templates:\n"
            f"{tmpl}\n\nRules: labels are 1-4 plain words; use a figure only if that same line says it; skip a line rather than force a diagram.\n"
            'Answer as {"scenes": [{"line": 3, "template": "...", ...}]}.\n\nScript:\n' + numbered)


def _e(s) -> str:
    return html.escape(str(s))


def scene_html(n: int, sc: dict, start: float, dur: float) -> tuple[str, list[str]]:
    """One scene: (its clip's html, its timeline lines), placed at `start` for `dur` seconds."""
    sid, t = f"sc{n}", sc["template"]
    T = lambda x: round(start + x, 3)
    js = [f'tl.fromTo("#{sid}", {{opacity: 0}}, {{opacity: 1, duration: 0.3}}, {T(0)});']
    if t == "orbit":
        inner = (f'<div id="{sid}c" style="position:absolute;left:400px;top:520px;width:280px;height:280px;border-radius:50%;'
                 'background:radial-gradient(circle at 35% 35%,#8fd3ff,#1f6fb2 55%,#0b2c55);box-shadow:0 0 60px #2a8cff66"></div>'
                 '<div style="position:absolute;left:180px;top:300px;width:720px;height:720px;border-radius:50%;border:3px dashed #ffffff40"></div>'
                 f'<div id="{sid}a" style="position:absolute;left:540px;top:660px;width:0;height:0"><div style="position:absolute;left:245px;top:-100px;width:200px;height:200px;'
                 'border-radius:50%;background:radial-gradient(circle at 35% 35%,#f2f0e8,#8d8a82)"></div>'
                 '<svg style="position:absolute;left:245px;top:-100px" width="200" height="200" viewBox="-100 -100 200 200"><path d="M0,-94 A94,94 0 0,0 0,94" fill="none" stroke="#FBCA03" stroke-width="12"/></svg></div>'
                 f'<div class="lbl" style="top:1230px;font-size:70px">{_e(sc["body"])} <span class="gold">↻</span> {_e(sc["center"])}</div>'
                 + (f'<div id="{sid}n" class="lbl gold" style="top:110px;font-size:62px">{_e(sc["note"]).upper()}</div>' if sc["note"] else ""))
        js += [f'tl.fromTo("#{sid}c", {{scale: 0}}, {{scale: 1, duration: 0.5, ease: "back.out(1.7)"}}, {T(0.1)});',
               f'tl.fromTo("#{sid}a", {{rotation: -40}}, {{rotation: 320, duration: {dur:.2f}, ease: "none"}}, {T(0)});']
        if sc["note"]:
            js.append(f'tl.fromTo("#{sid}n", {{opacity: 0, y: 30}}, {{opacity: 1, y: 0, duration: 0.4}}, {T(0.5)});')
    elif t == "compare":
        valued = bool(sc["a_value"])
        a, b = (_num(sc["a_value"]), _num(sc["b_value"])) if valued else (None, None)
        if valued and a and b:
            top = max(a, b)
            ha, hb = 560 * a / top, 560 * b / top
            inner = (f'<div style="position:absolute;left:0;right:0;top:240px;height:600px">'
                     f'<div id="{sid}x" class="bar" style="left:230px;height:{ha:.0f}px;background:#67C7EB"></div>'
                     f'<div id="{sid}y" class="bar" style="left:610px;height:{hb:.0f}px;background:#FBCA03"></div></div>'
                     f'<div class="lbl" style="top:850px;font-size:50px"><span style="position:absolute;left:150px;width:400px">{_e(sc["a"])}<br><span style="color:#67C7EB">{_e(sc["a_value"])}</span></span>'
                     f'<span style="position:absolute;left:530px;width:400px">{_e(sc["b"])}<br><span class="gold">{_e(sc["b_value"])}</span></span></div>')
            js += [f'tl.fromTo("#{sid}x", {{scaleY: 0, transformOrigin: "bottom"}}, {{scaleY: 1, duration: 0.9, ease: "power2.out"}}, {T(0.2)});',
                   f'tl.fromTo("#{sid}y", {{scaleY: 0, transformOrigin: "bottom"}}, {{scaleY: 1, duration: 0.9, ease: "power2.out"}}, {T(0.2 + min(1.2, dur * 0.35))});']
        else:
            inner = (f'<div id="{sid}x" class="box" style="top:280px">{_e(sc["a"]).upper()}</div>'
                     f'<div id="{sid}v" class="lbl gold" style="top:470px;font-size:110px">VS</div>'
                     f'<div id="{sid}y" class="box" style="top:660px">{_e(sc["b"]).upper()}</div>')
            js += [f'tl.fromTo("#{sid}x", {{x: -700}}, {{x: 0, duration: 0.5, ease: "power3.out"}}, {T(0.1)});',
                   f'tl.fromTo("#{sid}v", {{scale: 0}}, {{scale: 1, duration: 0.4, ease: "back.out(2)"}}, {T(0.5)});',
                   f'tl.fromTo("#{sid}y", {{x: 700}}, {{x: 0, duration: 0.5, ease: "power3.out"}}, {T(0.8)});']
    elif t == "flow":
        k = len(sc["steps"])
        gap = 210 if k == 4 else 250
        y0 = 200 + (4 - k) * 60
        parts = []
        for i, s in enumerate(sc["steps"]):
            parts.append(f'<div id="{sid}s{i}" class="box" style="top:{y0 + i * gap}px">{_e(s).upper()}</div>')
            if i < k - 1:
                parts.append(f'<svg id="{sid}r{i}" class="arrow" style="top:{y0 + i * gap + 140}px;height:{gap - 140}px" viewBox="0 0 40 90" preserveAspectRatio="none">'
                             '<path d="M20 4 V70 M6 56 L20 84 L34 56" fill="none" stroke="#FBCA03" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>')
            each = min(1.2, (dur - 0.4) / k)
            js.append(f'tl.fromTo("#{sid}s{i}", {{opacity: 0, scale: 0.85}}, {{opacity: 1, scale: 1, duration: 0.35, ease: "back.out(1.8)"}}, {T(0.15 + i * each)});')
            if i < k - 1:
                js.append(f'tl.fromTo("#{sid}r{i}", {{opacity: 0, y: -20}}, {{opacity: 1, y: 0, duration: 0.3}}, {T(0.15 + i * each + each * 0.6)});')
        inner = "".join(parts)
    elif t == "cycle":
        import math
        k, cx, cy, r = len(sc["steps"]), 540, 530, 290
        parts = [f'<div style="position:absolute;left:{cx - r}px;top:{cy - r}px;width:{2 * r}px;height:{2 * r}px;border-radius:50%;border:5px dashed #ffffff40"></div>',
                 f'<div id="{sid}a" style="position:absolute;left:{cx}px;top:{cy}px;width:0;height:0"><div style="position:absolute;left:-22px;top:{-r - 22}px;width:44px;height:44px;'
                 'border-radius:50%;background:#FBCA03;box-shadow:0 0 30px #FBCA03"></div></div>']
        for i, s in enumerate(sc["steps"]):
            ang = -math.pi / 2 + 2 * math.pi * i / k
            x, y = cx + (r + 120) * math.cos(ang), cy + (r + 75) * math.sin(ang) - 30
            parts.append(f'<div id="{sid}s{i}" class="cnode" style="left:{x:.0f}px;top:{y:.0f}px">{_e(s).upper()}</div>')
            js.append(f'tl.to("#{sid}s{i}", {{opacity: 1, color: "#FBCA03", duration: 0.25}}, {T(dur * i / k)});')
            js.append(f'tl.to("#{sid}s{i}", {{color: "#ffffff", duration: 0.25}}, {T(dur * (i + 1) / k)});')
        js.append(f'tl.fromTo("#{sid}a", {{rotation: 0}}, {{rotation: 360, duration: {dur:.2f}, ease: "none"}}, {T(0)});')
        inner = "".join(parts)
    elif t == "growth":
        if sc["shape"] == "compound":                  # slow, then steeper: the shape of growth on growth
            d = "M140 820 C 420 810, 640 740, 940 300"
        else:                                          # what the same money buys, falling
            d = "M140 320 C 420 400, 640 600, 940 810"
        col = "#1f9d55" if sc["shape"] == "compound" else "#d92d20"
        inner = (f'<svg style="position:absolute;left:0;top:0" width="{W}" height="1150" viewBox="0 0 {W} 1150">'
                 '<path d="M140 270 V820 H960" fill="none" stroke="#ffffff66" stroke-width="5"/>'
                 f'<path id="{sid}p" d="{d}" fill="none" stroke="{col}" stroke-width="14" stroke-linecap="round"/></svg>'
                 f'<div class="lbl" style="top:840px;font-size:40px;color:#ffffff99">TIME →</div>'
                 f'<div id="{sid}l" class="lbl" style="top:120px;font-size:66px;padding:0 80px;line-height:1.05">{_e(sc["label"]).upper()}</div>'
                 f'<div class="lbl" style="top:205px;font-size:34px;color:#FBCA03">ILLUSTRATION, NOT A PROMISE</div>')
        js += [f'(function () {{ var p = document.getElementById("{sid}p"), L = Math.ceil(p.getTotalLength()) + 2;'
               f' tl.fromTo(p, {{strokeDasharray: L, strokeDashoffset: L}}, {{strokeDashoffset: 0, duration: {min(2.2, dur * 0.7):.2f}, ease: "power1.in"}}, {T(0.2)}); }})();',
               f'tl.fromTo("#{sid}l", {{opacity: 0, y: 30}}, {{opacity: 1, y: 0, duration: 0.4}}, {T(0.1)});']
    elif t == "breakdown":
        k, cols = len(sc["parts"]), ["#FBCA03", "#67C7EB", "#1f9d55", "#e8e3d4"]
        shares = [_num(p["share"]) for p in sc["parts"]]
        widths = [x / 100 * 900 for x in shares] if all(shares) else [900 / k] * k
        x, parts = 90, []
        for i, (p_, w_) in enumerate(zip(sc["parts"], widths)):
            parts.append(f'<div id="{sid}b{i}" style="position:absolute;left:{x:.0f}px;top:380px;width:{w_:.0f}px;height:200px;background:{cols[i]};'
                         f'border:4px solid #05070d;border-radius:18px"></div>'
                         f'<div id="{sid}t{i}" style="position:absolute;left:{x:.0f}px;width:{w_:.0f}px;top:{610 + (i % 2) * 120}px;text-align:center;font-size:50px;line-height:1">'
                         f'{_e(p_["label"]).upper()}<br><span style="color:{cols[i]}">{_e(p_["share"])}</span></div>')
            js += [f'tl.fromTo("#{sid}b{i}", {{scaleX: 0, transformOrigin: "left"}}, {{scaleX: 1, duration: 0.45, ease: "power2.out"}}, {T(0.2 + i * 0.45)});',
                   f'tl.fromTo("#{sid}t{i}", {{opacity: 0, y: 20}}, {{opacity: 1, y: 0, duration: 0.3}}, {T(0.45 + i * 0.45)});']
            x += w_
        inner = "".join(parts)
    elif t == "myth":
        inner = (f'<div class="lbl" style="top:180px;font-size:58px;color:#ff6b5e">MYTH</div>'
                 f'<div id="{sid}m" class="box" style="top:260px;height:210px;font-size:54px;border-color:#ff6b5e">{_e(sc["myth"]).upper()}</div>'
                 f'<div id="{sid}x" style="position:absolute;left:170px;top:360px;width:740px;height:12px;background:#ff6b5e;border-radius:6px"></div>'
                 f'<div id="{sid}h" class="lbl gold" style="top:530px;font-size:58px">WHAT IS TRUE</div>'
                 f'<div id="{sid}f" class="box" style="top:610px;height:210px;font-size:54px">{_e(sc["fact"]).upper()}</div>')
        js += [f'tl.fromTo("#{sid}m", {{opacity: 0, y: 30}}, {{opacity: 1, y: 0, duration: 0.4}}, {T(0.1)});',
               f'tl.fromTo("#{sid}x", {{scaleX: 0, transformOrigin: "left"}}, {{scaleX: 1, duration: 0.35}}, {T(min(1.2, dur * 0.35))});',
               f'tl.fromTo(["#{sid}h", "#{sid}f"], {{opacity: 0, y: 30}}, {{opacity: 1, y: 0, duration: 0.4, stagger: 0.15}}, {T(min(1.6, dur * 0.5))});']
    elif t == "checklist":
        k = len(sc["items"])
        parts = []
        for i, it in enumerate(sc["items"]):
            y = 230 + i * 175
            parts.append(f'<div id="{sid}c{i}" style="position:absolute;left:150px;top:{y}px;display:flex;align-items:center;gap:40px;font-size:66px">'
                         f'<svg width="110" height="110" viewBox="0 0 110 110"><rect x="6" y="6" width="98" height="98" rx="20" fill="#0d1424" stroke="#FBCA03" stroke-width="6"/>'
                         f'<path id="{sid}k{i}" d="M28 58 L48 78 L84 34" fill="none" stroke="#1f9d55" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/></svg>'
                         f'<span>{_e(it).upper()}</span></div>')
            each = min(1.0, (dur - 0.3) / k)
            js += [f'tl.fromTo("#{sid}c{i}", {{opacity: 0, x: -40}}, {{opacity: 1, x: 0, duration: 0.3}}, {T(0.1 + i * each)});',
                   f'tl.fromTo("#{sid}k{i}", {{strokeDasharray: 90, strokeDashoffset: 90}}, {{strokeDashoffset: 0, duration: 0.3}}, {T(0.35 + i * each)});']
        inner = "".join(parts)
    elif t == "chat":
        parts = []
        for i, m_ in enumerate(sc["messages"]):
            me = m_["from"] == "me"
            parts.append(f'<div id="{sid}m{i}" style="position:absolute;{"right" if me else "left"}:90px;top:{250 + i * 220}px;max-width:720px;padding:34px 44px;'
                         f'border-radius:44px;font-family:Arial,Helvetica,sans-serif;font-weight:700;font-size:54px;line-height:1.15;'
                         f'background:{"#2b7cff" if me else "#262a33"};color:#fff;{"border-bottom-right-radius:10px" if me else "border-bottom-left-radius:10px"}">{_e(m_["text"])}</div>')
            js.append(f'tl.fromTo("#{sid}m{i}", {{opacity: 0, y: 40, scale: 0.9}}, {{opacity: 1, y: 0, scale: 1, duration: 0.35, ease: "back.out(1.6)"}}, {T(0.2 + i * min(1.1, dur / 3))});')
        inner = "".join(parts)
    elif t == "quote":
        inner = (f'<div class="lbl gold" style="top:160px;font-size:240px;line-height:1">“</div>'
                 f'<div id="{sid}q" class="lbl" style="top:380px;font-size:84px;line-height:1.12;padding:0 90px">{_e(sc["text"]).upper()}</div>')
        js += [f'tl.fromTo("#{sid}q", {{opacity: 0, scale: 0.94}}, {{opacity: 1, scale: 1, duration: 0.6, ease: "power2.out"}}, {T(0.15)});',
               f'tl.to("#{sid}q", {{scale: 1.05, duration: {max(0.5, dur - 0.8):.2f}, ease: "none"}}, {T(0.8)});']
    elif t == "timejump":
        inner = (f'<div id="{sid}r" style="position:absolute;left:365px;top:300px;width:350px;height:350px;border-radius:50%;border:8px solid #FBCA03"></div>'
                 f'<div id="{sid}h" style="position:absolute;left:532px;top:340px;width:16px;height:140px;background:#FBCA03;border-radius:8px;transform-origin:50% 135px"></div>'
                 f'<div id="{sid}t" class="lbl" style="top:720px;font-size:100px">{_e(sc["text"]).upper()}</div>')
        js += [f'tl.fromTo("#{sid}h", {{rotation: 0}}, {{rotation: 1080, duration: {min(1.8, dur * 0.6):.2f}, ease: "power2.inOut"}}, {T(0.1)});',
               f'tl.fromTo("#{sid}t", {{opacity: 0, letterSpacing: "30px"}}, {{opacity: 1, letterSpacing: "2px", duration: 0.7, ease: "power2.out"}}, {T(0.5)});']
    elif t == "split":
        inner = (f'<svg style="position:absolute;left:0;top:0" width="{W}" height="1150"><path id="{sid}p" d="M540 1000 V700 M540 700 L250 420 M540 700 L830 420" '
                 'fill="none" stroke="#ffffff88" stroke-width="10" stroke-linecap="round"/></svg>'
                 f'<div id="{sid}a" style="position:absolute;left:60px;width:420px;top:240px;text-align:center;font-size:62px;line-height:1.05">{_e(sc["a"]).upper()}</div>'
                 f'<div id="{sid}b" class="gold" style="position:absolute;left:600px;width:420px;top:240px;text-align:center;font-size:62px;line-height:1.05">{_e(sc["b"]).upper()}</div>')
        js += [f'(function () {{ var p = document.getElementById("{sid}p"), L = Math.ceil(p.getTotalLength()) + 2;'
               f' tl.fromTo(p, {{strokeDasharray: L, strokeDashoffset: L}}, {{strokeDashoffset: 0, duration: 0.9, ease: "power1.inOut"}}, {T(0.1)}); }})();',
               f'tl.fromTo(["#{sid}a", "#{sid}b"], {{opacity: 0, y: 30}}, {{opacity: 1, y: 0, duration: 0.4, stagger: 0.3}}, {T(0.8)});']
    else:                                              # number
        steps_ = _count(sc["value"])
        inner = (f'<div id="{sid}v" class="lbl gold" style="top:330px;font-size:300px;line-height:1">{_e(steps_[0])}</div>'
                 f'<div id="{sid}l" class="lbl" style="top:690px;font-size:72px;padding:0 90px;line-height:1.1">{_e(sc["label"]).upper()}</div>')
        over = min(1.4, dur * 0.5)
        js += [f'tl.set("#{sid}v", {{textContent: {json.dumps(x)}}}, {T(0.1 + over * i / len(steps_))});' for i, x in enumerate(steps_)]
        js.append(f'tl.fromTo("#{sid}l", {{opacity: 0, y: 30}}, {{opacity: 1, y: 0, duration: 0.4}}, {T(0.3 + over)});')
    return (f'<div id="{sid}" class="scene clip" data-start="{start:.3f}" data-duration="{dur:.3f}"><svg width="{W}" height="{H}" style="position:absolute" fill="#fff">{STARS}</svg>'
            f"{inner}</div>"), js


def _num(s: str) -> float | None:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s or "")
    return float(m.group(0).replace(",", "")) if m else None


def _count(value: str) -> list[str]:
    from .slides_motion import steps
    return steps(None, value) or [value]


def render_shots(shots: list[tuple[dict, float]], work: Path, run=subprocess.run) -> list[Path]:
    """[(scene, seconds)] -> one silent clip per scene (scene-00.mp4...), rendered in one go and cut; or hf.RenderFailed."""
    body, js, at = [], [], 0.0
    for n, (sc, dur) in enumerate(shots):
        h, j = scene_html(n, sc, at, dur)
        body.append(h)
        js += j
        at += dur
    font = hf.FONTS / "Anton-Regular.ttf"
    if not font.is_file():
        raise hf.RenderFailed("the scene font is missing (python -m vision fonts)")
    page = hf.page("".join(body), "\n".join(js), width=W, height=H, seconds=at, css=hf.font_face("Anton", "Anton-Regular.ttf", "400") + CSS)
    whole = hf.render(page, work / "scenes.mp4", assets={"Anton-Regular.ttf": font})
    out, at = [], 0.0
    for n, (_, dur) in enumerate(shots):
        clip = work / f"scene-{n:02d}.mp4"
        r = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(whole), "-t", f"{dur:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "17", "-pix_fmt", "yuv420p", str(clip)], capture_output=True)
        if r.returncode != 0 or not clip.is_file():
            raise hf.RenderFailed(f"could not cut scene {n}")
        out.append(clip)
        at += dur
    return out
