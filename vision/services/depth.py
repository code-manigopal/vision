"""Depth from one photo: Depth Anything V2 Small (Apache 2.0) as an ONNX file, run locally with onnxruntime.

    models/depth-anything-v2-small.onnx   99 MB, fetched once by `python -m vision tour model`

`estimate` gives a map the size of the model's input, 0 = far, 1 = near. It is relative depth: good for
parallax, not for measuring a room. The larger Depth Anything models are non-commercial; keep to Small.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from ..config import ROOT

PATH = ROOT / "models" / "depth-anything-v2-small.onnx"
URL = "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx"
SIDE = 518                      # the long side the model sees; both sides must be multiples of 14
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_session = None


class DepthUnavailable(Exception):
    pass


def fetch() -> Path:
    """Download the model if it isn't on disk. Returns its path."""
    if PATH.exists() and PATH.stat().st_size > 50_000_000:
        return PATH
    PATH.parent.mkdir(parents=True, exist_ok=True)
    part = PATH.with_suffix(".part")
    with httpx.stream("GET", URL, follow_redirects=True, timeout=httpx.Timeout(60.0)) as r:
        r.raise_for_status()
        with part.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    part.replace(PATH)
    return PATH


def size_for(w: int, h: int, side: int = SIDE) -> tuple[int, int]:
    """The model's input size for a photo: same shape, long side `side`, both sides multiples of 14."""
    k = side / max(w, h)
    return max(14, round(w * k / 14) * 14), max(14, round(h * k / 14) * 14)


def estimate(img: Image.Image) -> np.ndarray:
    global _session
    if _session is None:
        if not PATH.exists():
            raise DepthUnavailable("The depth model isn't on disk: run  python -m vision tour model")
        import onnxruntime as ort
        _session = ort.InferenceSession(str(PATH), providers=["CPUExecutionProvider"])
    w, h = size_for(*img.size)
    x = (np.asarray(img.convert("RGB").resize((w, h), Image.BICUBIC), dtype=np.float32) / 255.0 - _MEAN) / _STD
    out = _session.run(None, {_session.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0]
    d = np.squeeze(out).astype(np.float32)
    lo, hi = float(d.min()), float(d.max())
    return (d - lo) / (hi - lo) if hi > lo else np.zeros_like(d)
