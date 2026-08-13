"""What this machine is, and which models fit on it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body

from .. import config, hardware

router = APIRouter(tags=["hardware"])

CATALOG = Path(__file__).resolve().parent.parent.parent / "web" / "catalog.json"


def _machine() -> tuple[hardware.Machine, dict[str, Any]]:
    cfg = config.load()
    settings = cfg.get("hardware") or {}
    machine = hardware.with_overrides(hardware.detect(), settings.get("overrides"))
    return machine, settings


def _context_k(settings: dict[str, Any]) -> int:
    try:
        return max(1, min(1024, int(settings.get("context_k") or 8)))
    except (TypeError, ValueError):
        return 8


@router.get("/hardware")
async def read_hardware() -> dict[str, Any]:
    machine, settings = _machine()
    overrides = settings.get("overrides") or {}
    return {
        "machine": machine.as_dict(),
        "usable_gb": round(machine.usable_gb, 1) if machine.usable_gb else None,
        "context_k": _context_k(settings),
        "overridden": sorted(k for k, v in overrides.items() if v not in (None, "")),
        "notes": {
            "reserve_gb": hardware.RESERVE_GB.get(machine.os_name, 3.0),
            "approximate": (
                "Fit is estimated. Weights come from the real file size for models you "
                "already hold and from a quantisation table otherwise; the KV cache figure "
                "scales with parameters and context and cannot account for grouped-query "
                "attention. Treat it as the difference between 'fits' and 'does not', not "
                "as a byte count."
            ),
        },
    }


@router.patch("/hardware")
async def write_hardware(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Save the user's corrections. Detection is best-effort; the user is not."""
    patch: dict[str, Any] = {}

    if "context_k" in payload:
        try:
            patch["context_k"] = max(1, min(1024, int(payload["context_k"])))
        except (TypeError, ValueError):
            pass

    incoming = payload.get("overrides")
    if isinstance(incoming, dict):
        current = (config.load().get("hardware") or {}).get("overrides") or {}
        merged = dict(current)
        for key in ("chip", "gpu", "accelerator"):
            if key in incoming:
                merged[key] = (incoming[key] or "").strip() or None
        for key in ("total_ram_gb", "vram_gb", "bandwidth_gbps", "cpu_cores"):
            if key in incoming:
                raw = incoming[key]
                if raw in (None, ""):
                    merged[key] = None
                else:
                    try:
                        merged[key] = float(raw)
                    except (TypeError, ValueError):
                        pass
        if "unified_memory" in incoming:
            merged["unified_memory"] = bool(incoming["unified_memory"])
        patch["overrides"] = merged

    if patch:
        config.update({"hardware": patch})
    return await read_hardware()


@router.post("/hardware/detect")
async def redetect() -> dict[str, Any]:
    """Discard every override and read the machine again.

    Uses replace(), not update(): merging an empty dict leaves the old
    overrides in place, so this button silently did nothing.
    """
    config.replace("hardware", "overrides", {})
    return await read_hardware()


@router.get("/hardware/suggested")
async def rated_catalog() -> dict[str, Any]:
    """The curated pull list, rated against this machine.

    Rated on the server so the arithmetic lives in one place — the same
    functions that rate what you already hold.
    """
    machine, settings = _machine()
    context_k = _context_k(settings)

    try:
        entries = json.loads(CATALOG.read_text()).get("models") or []
    except (OSError, json.JSONDecodeError):
        entries = []

    out = []
    for entry in entries:
        weights = hardware.parse_size_gb(entry.get("size"))
        params = hardware.parse_params_b(entry.get("name", "").split(":")[-1])
        required = hardware.requirement_gb(
            weights_gb=weights, params_b=params, context_k=context_k
        )
        out.append({
            **entry,
            "required_gb": required,
            "rating": hardware.rate(machine, required),
            "tokens_per_second": hardware.tokens_per_second(machine, weights),
        })

    fits = sum(1 for m in out if m["rating"]["verdict"] in ("clears", "passes"))
    return {"models": out, "fits": fits, "total": len(out), "context_k": context_k}
