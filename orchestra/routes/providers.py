"""Provider setup, health, and the unified model list."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body

from .. import config
from ..providers import PROVIDER_IDS, all_models, build, build_all

router = APIRouter(tags=["providers"])


@router.get("/config")
async def get_config() -> dict[str, Any]:
    return config.redacted(config.load())


@router.patch("/config")
async def patch_config(patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Apply a partial config update.

    A masked secret echoed back from the UI is dropped rather than saved — that
    is how an unchanged key survives a settings save instead of being
    overwritten with its own display form.
    """
    providers = patch.get("providers")
    if isinstance(providers, dict):
        for pid, fields in providers.items():
            if not isinstance(fields, dict):
                continue
            fields.pop("_env_managed", None)
            for secret in list(config.SECRET_FIELDS):
                fields.pop(f"{secret}_set", None)
                value = fields.get(secret)
                if isinstance(value, str) and "…" in value:
                    fields.pop(secret)
            # An explicit empty string means "clear this credential".
            for key, value in list(fields.items()):
                if value == "":
                    fields[key] = None

    return config.redacted(config.update(patch))


@router.get("/providers")
async def list_providers() -> dict[str, Any]:
    cfg = config.load()
    providers = build_all(cfg)

    async def probe(pid: str):
        provider = providers[pid]
        status = await provider.status()
        return pid, {
            "id": pid,
            "label": provider.label,
            "configured": provider.configured(),
            "capabilities": {
                "json_schema": provider.caps.json_schema,
                "downloadable": provider.caps.downloadable,
                "server_side_research": provider.caps.server_side_research,
            },
            "status": status.as_dict(),
        }

    results = await asyncio.gather(*(probe(pid) for pid in PROVIDER_IDS), return_exceptions=True)

    out: dict[str, Any] = {}
    for index, result in enumerate(results):
        pid = PROVIDER_IDS[index]
        if isinstance(result, BaseException):
            out[pid] = {
                "id": pid,
                "label": pid,
                "configured": False,
                "status": {"state": "error", "detail": str(result), "models": None},
            }
        else:
            out[result[0]] = result[1]
    return {"providers": out, "concurrency": cfg.get("concurrency", {})}


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str) -> dict[str, Any]:
    provider = build(provider_id)
    status = await provider.status()
    return status.as_dict()


@router.get("/models")
async def list_models() -> dict[str, Any]:
    models = await all_models()
    return {"models": [m.as_dict() for m in models]}
