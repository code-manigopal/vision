"""Mani's own voice: lines spoken by IndicF5 (vision/voice/indic_f5.py) cloned from his reference clip.

The settings are the ones he picked by ear on 2026-10-13 and approved in a whole video (HDFC Bank Q1 FY27): the clip
with its pauses shortened (vault/voice/ref-tight.wav, its words in ref.txt), speed 1.3, 16 steps, 0.15 s between
lines. They are fixed here on purpose: **every video must sound like that one**, because the approval gate is meant
to go away. So nothing is taken on trust: each line is listened back to (voice/listen.py) and made again, up to
TRIES times with a different seed, if it is garbled or has a hole in it; a line that never passes stops the video
(VoiceFailed) rather than going out. The seed of a line follows from its words, so the same line comes out the same.

About 22 seconds of work per second of speech on the M1, so a whole video is an hour or more: every line is saved as
it is made and a line already on disk (same words, passed) is not made again. It needs the memory LM Studio's model
takes; unload that first (services/lmstudio.freed).
"""

from __future__ import annotations

import json
import re
import zlib
from pathlib import Path

from ..masters.tamil_say import voiced

ROOT = Path(__file__).resolve().parent.parent.parent
VOICE = ROOT / "vault" / "voice"
SPEED, STEPS, PAUSE, TRIES = 1.3, 16, 0.15, 3
SHORT_SPEED = 1.2               # Shorts are spoken a little slower (Mani, 2026-10-13: the long video's pace felt fast in a Short)


class VoiceFailed(RuntimeError):
    """A line that did not pass the listen-back after every try: the video is not made from it."""


def unspelt(text: str) -> list[str]:
    """English words the voice text still holds: the voice skips or garbles these, so they belong in tamil_say.SOUNDS."""
    return sorted(set(re.findall(r"[A-Za-z]{2,}", voiced(text))))


def speak(lines: list[dict], work: Path, speed: float = SPEED, steps: int = STEPS, ref: Path | None = None, log=print, make=None, check=None,
          tries: int = TRIES) -> list[Path]:
    """One wav per line, in Mani's voice, each one listened back to. Blocking and slow: run it in a thread or a script.

    `make(say, seed) -> (samples, rate)` and `check(wav, say) -> {"ok", "why", ...}` are the engine and the listener;
    tests pass their own. The checks of every line are left in work/qa.json."""
    import soundfile as sf
    from . import listen
    ref = ref or VOICE / "ref-tight.wav"
    check = check or listen.check
    if make is None:
        model = []                                      # loaded on the first line that needs making

        def make(say: str, seed: int):
            from .indic_f5 import generate, load_indicf5
            if not model:
                model.append(load_indicf5()[0])
            return generate(model[0], str(ref), (VOICE / "ref.txt").read_text(encoding="utf-8").strip(), say, steps=steps, speed=speed, seed=seed), 24000
    work.mkdir(parents=True, exist_ok=True)
    out, qa = [], []
    for n, ln in enumerate(lines):
        out.append(work / f"v{n:03d}.wav")
        say, mark = voiced(ln["say"]), out[-1].with_suffix(".json")
        left = unspelt(ln["say"])
        if left:
            raise VoiceFailed(f"line {n + 1} still has English letters the voice would garble: {', '.join(left)}")
        if out[-1].exists() and mark.exists() and (was := json.loads(mark.read_text(encoding="utf-8"))).get("say") == say and was.get("ok") and was.get("speed", SPEED) == speed:
            qa.append(was)
            continue
        seed = zlib.crc32(say.encode("utf-8")) % 1_000_000
        for attempt in range(tries):
            wave, rate = make(say, seed + attempt)
            sf.write(out[-1], wave, rate)
            got = {**check(out[-1], say), "say": say, "line": n + 1, "speed": speed, "seed": seed + attempt, "tries": attempt + 1, "seconds": round(len(wave) / rate, 1)}
            log(f"voice {n + 1}/{len(lines)}: {got['seconds']} s, heard {got.get('score')}" + (f", try {attempt + 1} failed: {got['why']}" if not got["ok"] else ""))
            if got["ok"]:
                break
        mark.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
        qa.append(got)
        if not got["ok"]:
            (work / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=1), encoding="utf-8")
            raise VoiceFailed(f"line {n + 1} did not pass after {tries} tries: {got['why']}")
    (work / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
