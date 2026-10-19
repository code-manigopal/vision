"""HyperFrames (heygen-com/hyperframes, Apache 2.0): an HTML page with a GSAP timeline rendered to an MP4 by its own headless
Chrome and FFmpeg, on this Mac. Used for animated slides (Mani Market Tamil) and animated scenes in Shorts.

Rules, keep them: the CLI version is pinned (`VERSION`), telemetry and update checks are off, and a page loads nothing from
the internet: GSAP and the fonts are local files (`python -m vision hyperframes` fetches them once into assets/hyperframes/
and assets/fonts/). Anything wrong (no Node 22+, no GSAP, a failed or overlong render) raises `RenderFailed`, and the caller
makes the video the way it did before; HyperFrames can never stop a video.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from ..config import ROOT

VERSION = "0.8.173"
GSAP = "3.14.2"
GSAP_URL = f"https://cdn.jsdelivr.net/npm/gsap@{GSAP}/dist/gsap.min.js"
HOME = ROOT / "assets" / "hyperframes"
FONTS = ROOT / "assets" / "fonts"
ENV = {"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1", "HYPERFRAMES_NO_UPDATE_CHECK": "1", "HYPERFRAMES_SKIP_SKILLS": "1"}
WORKERS = 2                 # each is a Chrome (~0.3-1.5 GB); 2 kept a 63 s slide at ~3.5 GB in all and about half real time


class RenderFailed(RuntimeError):
    pass


def node_ok(run=subprocess.run) -> bool:
    """Node 22 or newer and npx on the PATH (HyperFrames needs both)."""
    if not shutil.which("npx"):
        return False
    try:
        v = run(["node", "-v"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    m = re.match(r"v(\d+)", v)
    return bool(m and int(m.group(1)) >= 22)


def ready() -> bool:
    return (HOME / "gsap.min.js").is_file() and node_ok()


async def fetch(client: httpx.AsyncClient | None = None) -> list[str]:
    """GSAP into assets/hyperframes/ (once); returns what was fetched."""
    HOME.mkdir(parents=True, exist_ok=True)
    if (HOME / "gsap.min.js").is_file():
        return []
    async with (client or httpx.AsyncClient(timeout=60, follow_redirects=True)) as c:
        r = await c.get(GSAP_URL)
        r.raise_for_status()
    (HOME / "gsap.min.js").write_bytes(r.content)
    return [f"gsap {GSAP}"]


def font_face(name: str, file: str, weight: str = "100 900") -> str:
    """An @font-face for a font in assets/fonts/, copied into the project as assets/<file> by render()."""
    return f'@font-face{{font-family:"{name}";src:url("assets/{file}");font-weight:{weight}}}'


def page(body: str, script: str, *, width: int, height: int, seconds: float, css: str = "") -> str:
    """A whole composition: one root of `seconds`, local GSAP, `script` adds tweens to `tl` (a paused root timeline)."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width={width}, height={height}">
<script src="assets/gsap.min.js"></script>
<style>*{{margin:0;padding:0;box-sizing:border-box}}html,body{{width:{width}px;height:{height}px;overflow:hidden}}
#root{{position:relative;width:{width}px;height:{height}px;overflow:hidden}}{css}</style></head>
<body><div id="root" data-composition-id="main" data-start="0" data-duration="{seconds:.2f}" data-width="{width}" data-height="{height}">
{body}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{script}
window.__timelines["main"] = tl;
tl.seek(0);
</script></body></html>"""


def render(html: str, out: Path, *, assets: dict[str, Path] | None = None, timeout: float | None = None, workers: int = WORKERS,
           run=subprocess.run) -> Path:
    """Renders `html` to `out` (MP4). `assets` = {name in the page's assets/: file on disk}; GSAP is always added. The
    project folder (`out` with .hf) is kept beside the video for a look when something is off, and removed after a success."""
    if not ready():
        raise RenderFailed("HyperFrames is not set up (Node 22+ and `python -m vision hyperframes`)")
    proj = out.with_suffix(".hf")
    shutil.rmtree(proj, ignore_errors=True)
    (proj / "assets").mkdir(parents=True)
    for name, src in {"gsap.min.js": HOME / "gsap.min.js", **(assets or {})}.items():
        if not Path(src).is_file():
            raise RenderFailed(f"missing asset {src}")
        shutil.copyfile(src, proj / "assets" / name)
    (proj / "index.html").write_text(html, encoding="utf-8")
    (proj / "hyperframes.json").write_text(json.dumps({"paths": {"assets": "assets"}, "media": {"autoProxy": False}}))
    out.parent.mkdir(parents=True, exist_ok=True)
    seconds = float(re.search(r'data-duration="([\d.]+)"', html).group(1))
    try:
        r = run(["npx", "-y", f"hyperframes@{VERSION}", "render", str(proj), "-o", str(out), "--workers", str(workers), "--quiet"],
                capture_output=True, text=True, timeout=timeout or max(300.0, seconds * 6), env={**os.environ, **ENV})
    except (OSError, subprocess.SubprocessError) as e:
        raise RenderFailed(f"render did not finish: {e}") from e
    if r.returncode != 0 or not out.is_file() or out.stat().st_size < 1000:
        raise RenderFailed(f"render failed ({r.returncode}): {(r.stderr or r.stdout or '')[-400:]}")
    shutil.rmtree(proj, ignore_errors=True)
    return out
