"""What this machine is, and whether a given model will actually run on it.

Browser-based calculators have to guess at hardware from a WebGPU adapter
string. Orchestra runs on your machine, so it can read the real figures — total
memory, chip name, core count, free disk — and for models you have already
pulled it can use the actual file size on disk instead of estimating weights
from a parameter count. That is the whole advantage of being local, so it is
worth taking.

Everything here is stdlib. Detection shells out to platform tools that ship
with the OS; anything missing degrades to None and the UI asks you to fill it
in rather than inventing a number.

The arithmetic is openly approximate and the UI says so. A fit estimate that
is honest about being an estimate is useful; one that implies precision it does
not have will get someone to pull a 40 GB model onto a 16 GB laptop.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

GB = 1024 ** 3

# Bytes per parameter by quantisation. These are the effective on-disk figures
# for llama.cpp-family quants, not the nominal bit-width — Q4_K_M is ~4.6 bits
# once you account for the higher-precision blocks it keeps.
BYTES_PER_PARAM: dict[str, float] = {
    "Q2_K": 0.33, "Q3_K_S": 0.39, "Q3_K_M": 0.43, "Q3_K_L": 0.47,
    "Q4_0": 0.56, "Q4_1": 0.62, "Q4_K_S": 0.55, "Q4_K_M": 0.58,
    "Q5_0": 0.68, "Q5_1": 0.74, "Q5_K_S": 0.66, "Q5_K_M": 0.68,
    "Q6_K": 0.82, "Q8_0": 1.06,
    "F16": 2.0, "FP16": 2.0, "BF16": 2.0, "F32": 4.0, "FP32": 4.0,
}
DEFAULT_QUANT = "Q4_K_M"

# Apple Silicon unified-memory bandwidth, GB/s. The GPU and CPU share one pool,
# so on these machines "VRAM" is simply RAM — which is why a 64 GB Mac runs
# models a 24 GB discrete card cannot.
APPLE_BANDWIDTH: dict[str, float] = {
    "m1": 68.25, "m1 pro": 200, "m1 max": 400, "m1 ultra": 800,
    "m2": 100, "m2 pro": 200, "m2 max": 400, "m2 ultra": 800,
    "m3": 100, "m3 pro": 150, "m3 max": 400, "m3 ultra": 800,
    "m4": 120, "m4 pro": 273, "m4 max": 546,
    "m5": 153, "m5 pro": 300, "m5 max": 600,
}

# Fraction of theoretical bandwidth actually reached in generation.
EFFICIENCY = {"apple": 0.65, "nvidia": 0.70, "amd": 0.60, "cpu": 0.35}

# Memory the OS and everything else needs. Held back before rating anything.
RESERVE_GB = {"Darwin": 4.0, "Windows": 4.0, "Linux": 2.0}

RUNTIME_OVERHEAD_GB = 0.5


@dataclass
class Machine:
    os_name: str = ""
    os_version: str = ""
    chip: str | None = None
    cpu_cores: int | None = None
    total_ram_gb: float | None = None
    unified_memory: bool = False
    gpu: str | None = None
    vram_gb: float | None = None
    bandwidth_gbps: float | None = None
    disk_free_gb: float | None = None
    accelerator: str = "cpu"
    detected: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "os_name": self.os_name, "os_version": self.os_version, "chip": self.chip,
            "cpu_cores": self.cpu_cores, "total_ram_gb": self.total_ram_gb,
            "unified_memory": self.unified_memory, "gpu": self.gpu, "vram_gb": self.vram_gb,
            "bandwidth_gbps": self.bandwidth_gbps, "disk_free_gb": self.disk_free_gb,
            "accelerator": self.accelerator, "detected": self.detected, "unknown": self.unknown,
        }

    @property
    def usable_gb(self) -> float | None:
        """Memory a model may actually occupy.

        On unified-memory machines the GPU draws from system RAM, so the pool is
        total RAM minus what the OS needs. On a discrete card, VRAM is the real
        ceiling — a 128 GB workstation still cannot fit a 30 GB model onto a
        12 GB card without spilling.
        """
        if not self.unified_memory and self.vram_gb:
            return max(0.5, self.vram_gb - 1.0)
        if self.total_ram_gb:
            return max(0.5, self.total_ram_gb - RESERVE_GB.get(self.os_name, 3.0))
        return None


def _run(cmd: list[str], timeout: float = 4.0) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _apple_bandwidth(chip: str | None) -> float | None:
    if not chip:
        return None
    low = chip.lower()
    # Longest key first so "M4 Max" never matches the "m4" entry.
    for key in sorted(APPLE_BANDWIDTH, key=len, reverse=True):
        if key in low:
            return APPLE_BANDWIDTH[key]
    return None


def _detect_macos(m: Machine) -> None:
    mem = _run(["sysctl", "-n", "hw.memsize"])
    if mem.isdigit():
        m.total_ram_gb = round(int(mem) / GB, 1)
        m.detected.append("total_ram_gb")

    cores = _run(["sysctl", "-n", "hw.ncpu"])
    if cores.isdigit():
        m.cpu_cores = int(cores)
        m.detected.append("cpu_cores")

    brand = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    if brand:
        m.chip = brand
        m.detected.append("chip")

    if platform.machine() == "arm64":
        m.unified_memory = True
        m.accelerator = "apple"
        m.gpu = f"{m.chip} (integrated)" if m.chip else "Apple Silicon (integrated)"
        m.vram_gb = m.total_ram_gb  # one pool, shared
        m.bandwidth_gbps = _apple_bandwidth(m.chip)
        if m.bandwidth_gbps:
            m.detected.append("bandwidth_gbps")
        else:
            m.unknown.append("bandwidth_gbps")
    else:
        m.unknown.append("gpu")


def _detect_linux(m: Machine) -> None:
    try:
        info = open("/proc/meminfo").read()
        match = re.search(r"MemTotal:\s+(\d+) kB", info)
        if match:
            m.total_ram_gb = round(int(match.group(1)) * 1024 / GB, 1)
            m.detected.append("total_ram_gb")
    except OSError:
        m.unknown.append("total_ram_gb")

    cores = os.cpu_count()
    if cores:
        m.cpu_cores = cores
        m.detected.append("cpu_cores")

    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                m.chip = line.split(":", 1)[1].strip()
                m.detected.append("chip")
                break
    except OSError:
        pass

    if shutil.which("nvidia-smi"):
        out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        first = out.splitlines()[0] if out else ""
        if "," in first:
            name, mib = first.split(",", 1)
            m.gpu = name.strip()
            try:
                m.vram_gb = round(float(mib.strip()) / 1024, 1)
                m.detected += ["gpu", "vram_gb"]
                m.accelerator = "nvidia"
            except ValueError:
                m.unknown.append("vram_gb")
    else:
        m.unknown.append("gpu")


def _detect_windows(m: Machine) -> None:
    mem = _run(["wmic", "computersystem", "get", "TotalPhysicalMemory"])
    digits = re.search(r"(\d{6,})", mem)
    if digits:
        m.total_ram_gb = round(int(digits.group(1)) / GB, 1)
        m.detected.append("total_ram_gb")

    cores = os.cpu_count()
    if cores:
        m.cpu_cores = cores
        m.detected.append("cpu_cores")

    cpu = _run(["wmic", "cpu", "get", "Name"])
    lines = [l.strip() for l in cpu.splitlines() if l.strip() and "Name" not in l]
    if lines:
        m.chip = lines[0]
        m.detected.append("chip")

    gpu = _run(["wmic", "path", "win32_VideoController", "get", "Name,AdapterRAM"])
    glines = [l.strip() for l in gpu.splitlines() if l.strip() and "Name" not in l]
    if glines:
        m.gpu = glines[0]
        m.detected.append("gpu")
        if "nvidia" in glines[0].lower():
            m.accelerator = "nvidia"
        elif "amd" in glines[0].lower() or "radeon" in glines[0].lower():
            m.accelerator = "amd"
        m.unknown.append("vram_gb")  # AdapterRAM caps at 4 GB and lies
    else:
        m.unknown.append("gpu")


def detect() -> Machine:
    """Read what this machine actually is. Never raises."""
    m = Machine(os_name=platform.system(), os_version=platform.release())
    try:
        if m.os_name == "Darwin":
            _detect_macos(m)
        elif m.os_name == "Linux":
            _detect_linux(m)
        elif m.os_name == "Windows":
            _detect_windows(m)
    except Exception:  # noqa: BLE001 - detection is best-effort by definition
        pass

    try:
        m.disk_free_gb = round(shutil.disk_usage(os.path.expanduser("~")).free / GB, 1)
        m.detected.append("disk_free_gb")
    except OSError:
        m.unknown.append("disk_free_gb")

    if m.bandwidth_gbps is None and "bandwidth_gbps" not in m.unknown:
        m.unknown.append("bandwidth_gbps")
    return m


def with_overrides(machine: Machine, overrides: dict[str, Any] | None) -> Machine:
    """Apply the user's corrections over what was detected.

    Detection is best-effort — Windows lies about VRAM, and a chip released
    after this file was written has no bandwidth entry. Anything the user
    types wins, and the UI marks which fields they set.
    """
    if not overrides:
        return machine
    for key in ("chip", "gpu", "accelerator"):
        if overrides.get(key):
            setattr(machine, key, overrides[key])
    for key in ("total_ram_gb", "vram_gb", "bandwidth_gbps", "disk_free_gb"):
        value = overrides.get(key)
        if value is not None:
            try:
                setattr(machine, key, float(value))
            except (TypeError, ValueError):
                pass
    if overrides.get("cpu_cores") is not None:
        try:
            machine.cpu_cores = int(overrides["cpu_cores"])
        except (TypeError, ValueError):
            pass
    if "unified_memory" in overrides:
        machine.unified_memory = bool(overrides["unified_memory"])
    return machine


# ------------------------------------------------------------------ sizing

def parse_params_b(text: str | None) -> float | None:
    """'7B' / '3.2B' / '70b' -> billions of parameters."""
    if not text:
        return None
    match = re.search(r"([\d.]+)\s*([BbMm])", text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value / 1000 if match.group(2).lower() == "m" else value


def parse_size_gb(text: str | None) -> float | None:
    """'4.7 GB' / '274 MB' -> gigabytes."""
    if not text:
        return None
    match = re.search(r"([\d.]+)\s*(GB|MB)", text, re.I)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value / 1024 if match.group(2).upper() == "MB" else value


def kv_cache_gb(params_b: float, context_k: int = 8) -> float:
    """Rough KV cache size. Scales with parameters and context length.

    Genuinely approximate: the real figure depends on layer count, head count,
    and whether the model uses grouped-query attention, none of which the model
    list tells us. Good enough to separate "fits" from "does not".
    """
    return params_b * context_k * 0.008


def requirement_gb(
    *,
    weights_gb: float | None = None,
    params_b: float | None = None,
    quant: str | None = None,
    context_k: int = 8,
) -> float | None:
    """Working set for one loaded model.

    Prefers a real file size when we have one — for models already pulled we
    know exactly what the weights weigh, which beats any estimate.
    """
    if weights_gb is None:
        if params_b is None:
            return None
        per_param = BYTES_PER_PARAM.get((quant or DEFAULT_QUANT).upper(), BYTES_PER_PARAM[DEFAULT_QUANT])
        weights_gb = params_b * per_param

    est_params = params_b if params_b is not None else weights_gb / BYTES_PER_PARAM[DEFAULT_QUANT]
    return round(weights_gb + kv_cache_gb(est_params, context_k) + RUNTIME_OVERHEAD_GB, 2)


def tokens_per_second(machine: Machine, weights_gb: float | None) -> float | None:
    """Back-of-envelope generation speed: bandwidth divided by bytes read per token."""
    if not weights_gb or not machine.bandwidth_gbps:
        return None
    eff = EFFICIENCY.get(machine.accelerator, EFFICIENCY["cpu"])
    return round((machine.bandwidth_gbps * eff) / weights_gb, 1)


# ------------------------------------------------------------------ rating

# Verdicts reuse the interface's stamp vocabulary rather than inventing a
# second grading language. "clears" is what a customs officer says.
VERDICTS = {
    "clears":  ("cleared", "Runs with room to spare."),
    "passes":  ("cleared", "Fits, with enough left for the rest of your machine."),
    "tight":   ("transit", "Fits, but little headroom. Expect pressure with a long context or a second model."),
    "over":    ("refused", "Larger than this machine can hold. It will swap, crawl, or fail to load."),
    "unknown": ("void", "Not enough is known about this machine to say."),
}


def rate(machine: Machine, required_gb: float | None) -> dict[str, Any]:
    usable = machine.usable_gb
    if required_gb is None or usable is None:
        verdict = "unknown"
        ratio = None
    else:
        ratio = required_gb / usable
        if ratio <= 0.5:
            verdict = "clears"
        elif ratio <= 0.75:
            verdict = "passes"
        elif ratio <= 1.0:
            verdict = "tight"
        else:
            verdict = "over"

    stamp, note = VERDICTS[verdict]
    return {
        "verdict": verdict,
        "stamp": stamp,
        "note": note,
        "required_gb": required_gb,
        "usable_gb": round(usable, 1) if usable else None,
        "ratio": round(ratio, 2) if ratio is not None else None,
    }
