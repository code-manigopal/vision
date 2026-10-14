"""LM Studio's loaded models, freed for a while and put back (the `lms` command-line tool that comes with LM Studio).

The cloned voice needs the memory the local model holds (16 GB Mac), so the night's voice work runs inside `freed()`:
whatever was loaded is unloaded first and is always loaded again afterwards, even when the work fails. No `lms`
program, or nothing loaded, makes every call a no-op. Every call takes `run` so tests can stand in for the program.
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("vision")

LMS = Path.home() / ".lmstudio" / "bin" / "lms"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([str(LMS), *args], capture_output=True, text=True, timeout=300)


def _call(args: list[str], run) -> str | None:
    """The program's output, or None when it is missing, fails or times out (never raises)."""
    try:
        r = run(args)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("lms %s: %s", " ".join(args), e)
        return None
    return r.stdout if r.returncode == 0 else None


def _models(run) -> list[dict]:
    out = _call(["ps", "--json"], run)
    try:
        return [m for m in json.loads(out or "[]") if isinstance(m, dict) and m.get("identifier")]
    except (ValueError, TypeError):
        return []


def loaded(run=_run) -> list[str]:
    """Identifiers of the models in memory (`lms ps --json`)."""
    return [m["identifier"] for m in _models(run)]


def unload_all(run=_run) -> bool:
    return _call(["unload", "--all"], run) is not None


def load(identifier: str, run=_run, key: str = "", context: int = 0, ttl_ms: int = 0) -> bool:
    """Load a model again under the same identifier, with the context length and idle timeout it had."""
    args = ["load", key or identifier, "--identifier", identifier, "-y"]
    if context:
        args += ["-c", str(context)]
    if ttl_ms:
        args += ["--ttl", str(ttl_ms // 1000)]
    return _call(args, run) is not None


@contextlib.asynccontextmanager
async def freed(run=_run):
    """Inside: nothing is loaded. After: what was loaded before is loaded again, whatever happened inside."""
    held = _models(run)
    if held:
        unload_all(run)
    try:
        yield [m["identifier"] for m in held]
    finally:
        for m in held:
            if not load(m["identifier"], run, m.get("modelKey") or "", int(m.get("contextLength") or 0), int(m.get("ttlMs") or 0)):
                log.warning("lms: could not load %s again", m["identifier"])
