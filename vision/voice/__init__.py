"""Local voice for the Mac mini. Every piece is optional and falls back to the browser's voice.

config.yaml -> voice:
  tts: kokoro | piper | macos | browser
  kokoro_voice: bf_emma            (natural British female)
  kokoro_model: models/kokoro-v1.0.onnx
  kokoro_voices: models/voices-v1.0.bin
  piper_model: models/en_GB-alba-medium.onnx
  macos_voice: Serena
  stt: whisper | browser
  whisper_model: mlx-community/whisper-small-mlx
  wake: true | false
  wake_model: hey_jarvis           (built-in; or a path to your own trained "hey viz" .onnx)

Install the extras on the Mac:  .venv/bin/pip install -r requirements-voice.txt  and  brew install ffmpeg
"""

from __future__ import annotations

import asyncio
import io
import logging
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

from ..config import ROOT

log = logging.getLogger("vision.voice")


class VoiceUnavailable(Exception):
    pass


# Kokoro voice id prefix -> (accent shown on the dashboard, phonemizer language)
KOKORO_ENGLISH = {"bf_": ("UK", "en-gb"), "bm_": ("UK", "en-gb"), "af_": ("US", "en-us"), "am_": ("US", "en-us")}


# ======================= speaking =======================
class TTS:
    def __init__(self, vcfg: dict) -> None:
        self.cfg = vcfg
        self.engine = (vcfg.get("tts") or "browser").lower()
        self._kokoro = None
        self._lock = asyncio.Lock()

    def available(self) -> bool:
        try:
            if self.engine == "kokoro":
                import kokoro_onnx  # noqa: F401
                return (ROOT / self.cfg.get("kokoro_model", "models/kokoro-v1.0.onnx")).exists()
            if self.engine == "piper":
                return bool(shutil.which("piper")) and (ROOT / self.cfg.get("piper_model", "")).exists()
            if self.engine == "macos":
                return bool(shutil.which("say"))
        except ImportError:
            return False
        return False

    async def synth(self, text: str, voice: str | None = None) -> bytes:
        if not self.available():
            raise VoiceUnavailable(f"TTS engine '{self.engine}' isn't installed")
        async with self._lock:  # one voice at a time
            return await asyncio.to_thread(self._synth, text[:1500], voice)

    def _load_kokoro(self):
        from kokoro_onnx import Kokoro
        if self._kokoro is None:
            self._kokoro = Kokoro(str(ROOT / self.cfg.get("kokoro_model", "models/kokoro-v1.0.onnx")),
                                  str(ROOT / self.cfg.get("kokoro_voices", "models/voices-v1.0.bin")))
        return self._kokoro

    def voices(self) -> dict:
        """The voices the dashboard may switch between: Kokoro's English ones (UK first), nothing for other engines."""
        default = self.cfg.get("kokoro_voice", "bf_emma")
        if self.engine != "kokoro" or not self.available():
            return {"engine": self.engine, "current": None, "voices": []}
        ids = sorted((v for v in self._load_kokoro().get_voices() if v[:3] in KOKORO_ENGLISH), key=lambda v: (list(KOKORO_ENGLISH).index(v[:3]), v))
        return {"engine": "kokoro", "current": default,
                "voices": [{"id": v, "name": v[3:].title(), "accent": KOKORO_ENGLISH[v[:3]][0], "gender": "F" if v[1] == "f" else "M"} for v in ids]}

    def _synth(self, text: str, voice: str | None = None) -> bytes:
        if self.engine == "kokoro":
            k = self._load_kokoro()
            if not voice or voice[:3] not in KOKORO_ENGLISH or voice not in k.get_voices():
                voice = self.cfg.get("kokoro_voice", "bf_emma")
            lang = KOKORO_ENGLISH.get(voice[:3], ("UK", "en-gb"))[1]
            samples, sr = k.create(text, voice=voice, speed=float(self.cfg.get("speed", 1.0)), lang=lang)
            return _wav(samples, sr)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.wav"
            if self.engine == "piper":
                subprocess.run(["piper", "--model", str(ROOT / self.cfg["piper_model"]), "--output_file", str(out)], input=text.encode(), check=True, capture_output=True)
            else:
                subprocess.run(["say", "-v", self.cfg.get("macos_voice", "Serena"), "-o", str(out), "--data-format=LEI16@22050", text], check=True, capture_output=True)
            return out.read_bytes()


def _wav(samples, sr: int) -> bytes:
    import numpy as np
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


# ======================= listening =======================
class STT:
    def __init__(self, vcfg: dict) -> None:
        self.cfg = vcfg
        self.engine = (vcfg.get("stt") or "browser").lower()

    def available(self) -> bool:
        if self.engine != "whisper":
            return False
        try:
            import mlx_whisper  # noqa: F401
        except ImportError:
            return False
        return bool(shutil.which("ffmpeg"))

    async def transcribe(self, audio: bytes, suffix: str = ".webm") -> str:
        if not self.available():
            raise VoiceUnavailable("Whisper isn't installed (pip install mlx-whisper, brew install ffmpeg)")
        return await asyncio.to_thread(self._run, audio, suffix)

    def _run(self, audio: bytes, suffix: str) -> str:
        import mlx_whisper
        with tempfile.NamedTemporaryFile(suffix=suffix) as f:
            f.write(audio)
            f.flush()
            res = mlx_whisper.transcribe(f.name, path_or_hf_repo=self.cfg.get("whisper_model", "mlx-community/whisper-small-mlx"), language="en")
        return (res.get("text") or "").strip()


# ======================= wake word =======================
class WakeWord:
    """Listens on the Mac's microphone; on "Hey …" it tells the dashboard to start listening."""

    def __init__(self, vcfg: dict, bus, loop: asyncio.AbstractEventLoop) -> None:
        self.cfg, self.bus, self.loop = vcfg, bus, loop
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def available(self) -> bool:
        try:
            import openwakeword  # noqa: F401
            import sounddevice  # noqa: F401
        except ImportError:
            return False
        return bool(self.cfg.get("wake"))

    def start(self) -> bool:
        if not self.available():
            return False
        self.thread = threading.Thread(target=self._run, name="wakeword", daemon=True)
        self.thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model
        name = self.cfg.get("wake_model", "hey_jarvis")
        model = Model(wakeword_models=[name]) if not name.endswith(".onnx") else Model(wakeword_models=[str(ROOT / name)])
        threshold = float(self.cfg.get("wake_threshold", 0.5))
        cooldown = 0
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280) as stream:
            while not self._stop.is_set():
                frame, _ = stream.read(1280)
                scores = model.predict(np.squeeze(frame))
                cooldown = max(0, cooldown - 1)
                if cooldown == 0 and max(scores.values()) >= threshold:
                    cooldown = 25  # ~2 s
                    self.loop.call_soon_threadsafe(self.bus.publish, {"type": "wake"})
