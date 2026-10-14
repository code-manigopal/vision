#!/usr/bin/env python3
"""Voice trial: a few lines of a results script spoken in Mani's own voice, cloned from his clip.

    .venv/bin/python scripts/voice_trial.py                 ->  data/shorts/_sample/voice-trial.wav
    .venv/bin/python scripts/voice_trial.py --steps 32      (slower, usually cleaner; default 16)
    .venv/bin/python scripts/voice_trial.py --say "one spelling" "another spelling"     ->  voice-say-1.wav, voice-say-2.wav

Needs, once: the terms accepted on https://huggingface.co/ai4bharat/IndicF5 and `.venv/bin/hf auth login`.
The voice comes from vault/voice/ref.wav (ten seconds of Mani, 24 kHz mono) and ref.txt (its exact words, in Tamil
letters). Each line is sent as the voice needs it (vision/masters/tamil_say.py); both forms are printed, with how
long each took, so pace and pronunciation can be judged line by line.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision.masters.tamil_say import voiced  # noqa: E402

VOICE, OUT = ROOT / "vault" / "voice", ROOT / "data" / "shorts" / "_sample"
LINES = [
    "வணக்கம் நண்பர்களே! HDFC Bank-ஓட Q1 FY27 result வந்துருக்கு.",
    "Numbers என்ன சொல்லுது? நல்லா இருக்கா, கவனிக்க வேண்டியது ஏதாவது இருக்கா? வாங்க பாக்கலாம்.",
    "Net profit போன வருஷம் இதே quarter-ல 18155 கோடி, இப்போ 19060 கோடி, அதாவது 5 percent வளர்ச்சி.",
    "Operating profit 21.2 percent குறைஞ்சிருக்கு. ஐயோ ஐயோ! இத எதிர்பார்க்கலையே.",
    "இது company report பண்ண numbers மட்டும்தான். முதலீட்டு ஆலோசனை இல்ல.",
]


def main() -> None:
    import numpy as np
    import soundfile as sf
    from vision.voice.indic_f5 import generate, load_indicf5
    steps = int(sys.argv[sys.argv.index("--steps") + 1]) if "--steps" in sys.argv and "--say" not in sys.argv else 16
    ref_text = (VOICE / "ref.txt").read_text(encoding="utf-8").strip()
    t0 = time.time()
    try:
        model, _ = load_indicf5()
    except Exception as e:  # noqa: BLE001 - the usual cause is the gate on the model's page
        sys.exit(f"The cloning model could not be loaded ({type(e).__name__}: {e}).\n"
                 "Accept the terms on https://huggingface.co/ai4bharat/IndicF5, then run: .venv/bin/hf auth login")
    print(f"model loaded in {time.time() - t0:.0f} s")
    pieces, gap = [], np.zeros(int(24000 * 0.2), np.float32)
    OUT.mkdir(parents=True, exist_ok=True)
    if "--say" in sys.argv:                             # spellings to compare by ear: each is sent exactly as typed, one file each
        for n, say in enumerate(sys.argv[sys.argv.index("--say") + 1:], 1):
            t = time.time()
            wave = generate(model, str(VOICE / "ref.wav"), ref_text, say, steps=steps)
            sf.write(OUT / f"voice-say-{n}.wav", wave, 24000)
            print(f"{n}: {len(wave) / 24000:5.1f} s of voice in {time.time() - t:5.1f} s | {say}")
        return
    for line in LINES:
        t, say = time.time(), voiced(line)
        wave = generate(model, str(VOICE / "ref.wav"), ref_text, say, steps=steps)
        print(f"{len(wave) / 24000:5.1f} s of voice in {time.time() - t:5.1f} s | {line}\n{'':29}| {say}")
        pieces += [wave, gap]
        sf.write(OUT / "voice-trial.wav", np.concatenate(pieces), 24000)       # after every line: a slow run still leaves something to hear
    print(OUT / "voice-trial.wav")


if __name__ == "__main__":
    main()
