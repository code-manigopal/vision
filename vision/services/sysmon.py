"""System instruments for the dashboard: CPU, memory and GPU load.

CPU and memory come from psutil (macOS, Linux, Windows). The GPU source is probed once at start:
Apple GPUs via ioreg (no sudo), NVIDIA via nvidia-smi; with neither, the GPU gauge is left out.
The dashboard draws whatever list of gauges this returns.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import shutil
import subprocess

import psutil

log = logging.getLogger("vision.sysmon")
GB = 1024 ** 3


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _apple_gpu() -> dict | None:
    m = re.search(r'"Device Utilization %"\s*=\s*(\d+)', _run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"]))
    return {"pct": int(m.group(1))} if m else None


def _nvidia_gpu() -> dict | None:
    out = _run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"])
    try:
        util, used, total = (float(x) for x in out.splitlines()[0].split(","))   # first card; MiB
    except (IndexError, ValueError):
        return None
    return {"pct": util, "vram_used": used / 1024, "vram_total": total / 1024}


def _gauge(id: str, label: str, pct: float, hot: int, detail: str = "") -> dict:
    return {"id": id, "label": label, "pct": max(0, min(100, round(pct))), "hot": hot, "detail": detail}


class SysMon:
    def __init__(self) -> None:
        mac = platform.system() == "Darwin"
        self.unified = mac and platform.machine() == "arm64"   # Apple Silicon: CPU and GPU share one memory pool
        probes = ([_apple_gpu] if mac else []) + ([_nvidia_gpu] if shutil.which("nvidia-smi") else [])
        self._gpu = next((p for p in probes if p() is not None), None)
        psutil.cpu_percent(None)   # first call only sets the baseline

    def sample(self) -> list[dict]:
        vm = psutil.virtual_memory()
        gauges = [
            _gauge("cpu", "CPU", psutil.cpu_percent(None), 80),
            _gauge("mem", "UNIFIED MEMORY" if self.unified else "RAM", vm.percent, 85,
                   f"{(vm.total - vm.available) / GB:.1f} / {vm.total / GB:.1f} GB"),
        ]
        gpu = self._gpu() if self._gpu else None
        if gpu:
            gauges.append(_gauge("gpu", "GPU", gpu["pct"], 80))
            if gpu.get("vram_total"):
                gauges.append(_gauge("vram", "VRAM", 100 * gpu["vram_used"] / gpu["vram_total"], 85,
                                     f"{gpu['vram_used']:.1f} / {gpu['vram_total']:.1f} GB"))
        return gauges


async def run(bus, interval: float = 2.0) -> None:
    """Sample forever and publish `system` events. Sampling runs in a thread (it shells out)."""
    mon = await asyncio.to_thread(SysMon)
    while True:
        try:
            bus.publish({"type": "system", "gauges": await asyncio.to_thread(mon.sample)})
        except Exception:
            log.exception("system sample failed")
        await asyncio.sleep(interval)
