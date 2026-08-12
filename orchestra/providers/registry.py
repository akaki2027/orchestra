"""Builds live provider instances from the current config.

Providers are constructed per request rather than cached, so editing a key or
switching a model slot takes effect on the next call with no restart. That is
the "swap anything, any time" promise, and caching would quietly break it.
"""

from __future__ import annotations

from typing import Any

from .. import config, privacy
from .anthropic import AnthropicProvider
from .base import ModelInfo, Provider
from .guard import guarded
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

PROVIDER_IDS = ("ollama", "anthropic", "openai_compat")


def _raw(provider_id: str, settings: dict[str, Any]) -> Provider:
    if provider_id == "ollama":
        return OllamaProvider(host=settings.get("host"))
    if provider_id == "anthropic":
        return AnthropicProvider(api_key=settings.get("api_key"))
    if provider_id == "openai_compat":
        return OpenAICompatProvider(
            base_url=settings.get("base_url"),
            api_key=settings.get("api_key"),
            label=settings.get("label"),
        )
    raise KeyError(f"Unknown provider: {provider_id}")


def build(provider_id: str, cfg: dict[str, Any] | None = None) -> Provider:
    """The only way to get a provider — and therefore the only way to reach a model.

    Everything comes back wrapped in the privacy guard. That is deliberate: the
    guarantee has to hold for code that has not been written yet, so it is a
    property of this function rather than a rule contributors must remember.
    Do not add a path that returns `_raw(...)` directly.
    """
    cfg = cfg or config.load()
    settings = (cfg.get("providers") or {}).get(provider_id) or {}
    return guarded(_raw(provider_id, settings), privacy.Policy.from_config(cfg))


def build_all(cfg: dict[str, Any] | None = None) -> dict[str, Provider]:
    cfg = cfg or config.load()
    return {pid: build(pid, cfg) for pid in PROVIDER_IDS}


async def all_models(cfg: dict[str, Any] | None = None) -> list[ModelInfo]:
    """Every selectable model across every configured provider.

    A provider that is down contributes nothing rather than failing the list —
    an unreachable Ollama should never stop you picking a Claude model.
    """
    import asyncio

    providers = [p for p in build_all(cfg).values() if p.configured()]

    async def safe(provider: Provider) -> list[ModelInfo]:
        try:
            return await provider.list_models()
        except Exception:  # noqa: BLE001
            return []

    results = await asyncio.gather(*(safe(p) for p in providers))
    return [model for group in results for model in group]
