#!/usr/bin/env python3
"""Look sample for the Mani Market Tamil channel: slides that build while the voice explains them.

    .venv/bin/python scripts/market_look_sample.py        ->  data/shorts/_sample/market-look.mp4

Three slides (a doodle opening, a results table, the takeaway) for a made-up bank; every number is invented and
the slides say so. Each spoken line reveals one thing on the slide, and the voice explains it instead of reading it.
The drawing and joining are vision/masters/slides.py. The voice here is Edge's Tamil voice, a stand-in until
Mani's own voice is cloned; the presenter in the corner is a stand-in drawing too.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision.masters import slides  # noqa: E402
from vision.masters.tamil_say import numbers_as_words  # noqa: E402

OUT = ROOT / "data" / "shorts" / "_sample"
VOICE, RATE, PAUSE = "ta-IN-ValluvarNeural", "+14%", 0.15

DECK = [
    {"kind": "cover", "title": "Sample Bank · Q2 Result", "items": [
        {"icon": "bank", "text": "Sample Bank"}, {"icon": "paper", "text": "Q2 FY27"}, {"icon": "lens", "text": "நல்லா இருக்கா?"}]},
    {"kind": "table", "title": "Financial Info", "cols": ["Q2 FY26", "Q2 FY27", "மாற்றம்"], "items": [
        {"label": "Total Income [₹ கோடி]", "was": "2,240", "now": "2,816", "change": "▲ 26%", "tone": "good", "note": "வளர்ச்சி வேகம் நல்லா இருக்கு"},
        {"label": "Net Profit [₹ கோடி]", "was": "194", "now": "221", "change": "▲ 14%", "tone": "good", "note": "Income அளவுக்கு profit ஏறல"},
        {"label": "NIM [margin]", "was": "3.6%", "now": "3.4%", "change": "▼ 0.2", "tone": "bad", "note": "Margin-ல pressure"},
        {"label": "Gross NPA", "was": "2.1%", "now": "1.8%", "change": "▼ 0.3", "tone": "good", "note": "கடன் தரம் மேம்பட்டிருக்கு"}]},
    {"kind": "points", "title": "ஆக மொத்தம்", "note": "மாதிரி வீடியோ · எண்கள் கற்பனை · முதலீட்டு ஆலோசனை இல்ல", "items": [
        {"icon": "up", "text": "Growth இருக்கு"}, {"icon": "shield", "text": "Loan quality நல்லா இருக்கு"},
        {"icon": "eye", "text": "Margin-அ கவனிக்கணும்", "tone": "bad"}]},
]

LINES = [
    {"slide": 0, "show": 1, "say": "வணக்கம் நண்பர்களே! Sample Bank-ஓட Q2 result வந்துருக்கு."},
    {"slide": 0, "show": 3, "say": "Numbers எல்லாம் நல்லா இருக்கா, இல்ல ஏதாவது கவனிக்க வேண்டிய விஷயம் இருக்கா? வாங்க பாக்கலாம்."},
    {"slide": 1, "show": 1, "say": "முதல்ல total income. போன வருஷம் இதே quarter-ல 2240 கோடி. இப்போ 2816 கோடி. அதாவது சுமார் 26 percent growth."},
    {"slide": 1, "show": 2, "say": "Net profit 194 கோடில இருந்து 221 கோடிக்கு ஏறிருக்கு. Growth இருக்கு, ஆனா income ஏறின அளவுக்கு profit ஏறல."},
    {"slide": 1, "show": 3, "say": "ஏன்னா, margin கொஞ்சம் குறைஞ்சிருக்கு. NIM 3.6-ல இருந்து 3.4 percent-க்கு இறங்கிருக்கு."},
    {"slide": 1, "show": 4, "say": "நல்ல விஷயம் என்னன்னா, gross NPA 2.1-ல இருந்து 1.8 percent-க்கு குறைஞ்சிருக்கு. அதாவது கடன் தரம் மேம்பட்டிருக்கு."},
    {"slide": 2, "show": 1, "say": "ஆக மொத்தம், வளர்ச்சி இருக்கு."},
    {"slide": 2, "show": 2, "say": "Loan quality-யும் நல்லா இருக்கு."},
    {"slide": 2, "show": 3, "say": "ஆனா margin-அ அடுத்த quarter-லயும் கவனிக்கணும்."},
    {"slide": 2, "show": 4, "say": "இது ஒரு மாதிரி வீடியோ. Numbers எல்லாம் கற்பனை, முதலீட்டு ஆலோசனை இல்ல."},
]


async def speak(lines: list[dict], work: Path, voice: str = VOICE, rate: str = RATE) -> list[Path]:
    import edge_tts
    out = []
    for n, ln in enumerate(lines):
        out.append(work / f"v{n:03d}.mp3")
        await edge_tts.Communicate(numbers_as_words(ln["say"]), voice, rate=rate).save(str(out[-1]))
    return out


def draw(deck: list[dict], said: list[dict], work: Path, tall: bool = False, captions: bool = True, **frame):
    """The slide pictures, the presenter and (unless switched off) the English caption strips: what slides.assemble needs, as (pngs, faces, captions)."""
    plan = slides.caption_plan(said, tall) if captions else None
    got = slides.pictures(deck, said, work, tall=tall, **({"captions": slides.caption_texts(plan)} if plan else {}), **frame)
    return got[0], got[1], ({"plan": plan, "pngs": got[2]} if plan else None)


async def voice(said: list[dict], work: Path, mani: bool = False, speed: float | None = None) -> list[Path]:
    """Edge's Tamil voice, or with `mani` Mani's cloned voice (an hour of work: run it only when LM Studio's model is unloaded)."""
    if not mani:
        return await speak(said, work)
    from vision.voice import clone
    missing = sorted({w for ln in said for w in clone.unspelt(ln["say"])})
    if missing:
        print("still in English letters (the voice may garble these; add them to tamil_say.SOUNDS):", ", ".join(missing))
    return await asyncio.to_thread(clone.speak, said, work / "mani", speed or clone.SPEED)


def main() -> None:
    work = OUT / "market-look"
    pngs, faces = slides.pictures(DECK, LINES, work, channel="Mani Market Tamil", tag="SAMPLE DATA · கற்பனை எண்கள்")
    final = slides.assemble(work, pngs, LINES, asyncio.run(speak(LINES, work)), OUT / "market-look.mp4", faces=faces, pause=PAUSE)
    print(f"{final}  ({slides.probe(final):.1f} s)")


if __name__ == "__main__":
    sys.exit(main())
