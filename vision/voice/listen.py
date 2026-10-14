"""Listening back to a spoken line before it goes into a video: the check that stands in for Mani's ear.

    check(wav, say)   -> {"ok", "score", "gap", "lead", "tail", "why"}

Two things can go wrong with the cloned voice and both are audible: it garbles or skips words (seen when a word was
left in English letters), and it leaves a hole in the middle of a sentence. So each line is (1) written down by a
local Whisper model and compared with what was meant to be said, and (2) searched for silences. The bars come from
the video Mani approved by ear on 2026-10-13 (HDFC Bank Q1 FY27, 13 lines): its lines scored 0.65 or more and its
longest silence inside a line was 0.42 s. What this cannot hear: a word said clearly but wrongly stressed, or a
number off by a digit (Whisper mishears digits itself). Those are held by the spelling table in masters/tamil_say.py,
which only changes by hand, and by tests/test_voice.py, which pins the approved spellings.

Whisper "large-v3-turbo" is used: "small" loops on a line longer than about fifteen seconds.
"""

from __future__ import annotations

import difflib
import re
import subprocess
import unicodedata
from pathlib import Path

from ..masters.tamil_say import voiced

MODEL = "mlx-community/whisper-large-v3-turbo"
MIN_SCORE = 0.55                # the approved lines: 0.65 to 0.95; a garbled one: about 0.3
MAX_GAP, MAX_EDGE = 0.6, 0.45   # seconds of silence inside a line, and at either end (approved: 0.42 and 0.28)


def _letters(text: str) -> str:
    """Tamil letters only, with English words and digits first put the way the voice was given them."""
    return re.sub(r"[^஀-௿]", "", unicodedata.normalize("NFC", voiced(re.sub(r"(?<=\d),(?=\d)", "", text))))


def score(say: str, heard: str) -> float:
    """How much of what was meant is in what was heard, 0 to 1."""
    a, b = _letters(say), _letters(heard)
    return round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 3) if a and b else 0.0


def heard(wav: Path, model: str = MODEL, temperature: float = 0.0) -> str:
    import mlx_whisper
    return mlx_whisper.transcribe(str(wav), path_or_hf_repo=model, language="ta", condition_on_previous_text=False, temperature=temperature)["text"].strip()


def silences(wav: Path, run=subprocess.run) -> dict:
    """The silence before the first word, after the last, and the longest one in between."""
    out = run(["ffmpeg", "-v", "info", "-i", str(wav), "-af", "silencedetect=noise=-38dB:d=0.12", "-f", "null", "-"], capture_output=True, text=True).stderr
    total = re.findall(r"Duration: (\d+):(\d+):([\d.]+)", out)
    dur = int(total[0][0]) * 3600 + int(total[0][1]) * 60 + float(total[0][2]) if total else 0.0
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    spans = [(s, ends[i] if i < len(ends) else dur) for i, s in enumerate(starts)]
    lead = next((e - s for s, e in spans if s < 0.03), 0.0)
    tail = next((e - s for s, e in spans if abs(e - dur) < 0.05), 0.0)
    inner = [e - s for s, e in spans if s >= 0.03 and abs(e - dur) >= 0.05]
    return {"lead": round(max(lead, 0.0), 2), "tail": round(tail, 2), "gap": round(max(inner, default=0.0), 2)}


def check(wav: Path, say: str, hear=heard) -> dict:
    s = silences(wav)
    sc = score(say, hear(wav))
    if sc < MIN_SCORE:                                  # Whisper can loop on one syllable ("த்துத்துத்து...", seen 2026-10-14 on a good line that then scored 0.85):
        try:                                            # a low score gets one second listen, slightly less greedy, and the better of the two counts
            sc = max(sc, score(say, hear(wav, temperature=0.2)))
        except TypeError:                               # a listener that takes no temperature (tests' fakes)
            pass
    why = [f"heard only {sc:.2f} of the line (needs {MIN_SCORE})"] * (sc < MIN_SCORE) + [f"a {s['gap']} s hole inside the line"] * (s["gap"] > MAX_GAP) \
        + [f"{max(s['lead'], s['tail'])} s of silence at an end"] * (max(s["lead"], s["tail"]) > MAX_EDGE)
    return {"ok": not why, "score": sc, **s, "why": "; ".join(why)}
