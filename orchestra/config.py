"""User configuration: provider credentials, model slots, concurrency lanes.

Lives in ~/.orchestra/config.json at mode 0600. Never in the repo — it holds API
keys. Environment variables win over the file so people can run Orchestra from a
secrets manager or CI without writing keys to disk at all.
"""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

# Where per-user state lives. Overridable so tests (and the cold-clone check)
# can point at a scratch directory.
HOME = Path(os.environ.get("ORCHESTRA_HOME", Path.home() / ".orchestra"))
CONFIG_PATH = HOME / "config.json"
AGENTS_DIR = HOME / "agents"

DEFAULTS: dict[str, Any] = {
    "providers": {
        "ollama": {"host": "http://127.0.0.1:11434"},
        "anthropic": {"api_key": None},
        # `starred` keeps the pickers usable: OpenRouter serves 400+ models and
        # only the ones you chose belong in a dropdown.
        "openrouter": {"api_key": None, "starred": []},
        "openai_compat": {"base_url": None, "api_key": None, "label": "OpenAI-compatible"},
    },
    # The "big agent" that plans and synthesizes.
    "orchestrator": {"provider": None, "model": None},
    # Per-provider parallelism. Cloud lanes are network-bound so they run wide;
    # the local lane is RAM-bound and must not throttle the cloud ones.
    "concurrency": {"anthropic": 8, "openai_compat": 8, "ollama": 2},
    # Privacy-tiered routing. Defaults to "redact" rather than "off": the point
    # of the project is that sensitive values do not reach a hosted model, and
    # a protection nobody switches on protects nobody. Categories default to
    # all of them; see privacy.ALL_CATEGORIES.
    "privacy": {"mode": "redact", "categories": None, "local_fallback": None},
    "mode": "direct",
}

# Environment overrides: (provider, field) -> env var name.
ENV_OVERRIDES = {
    ("ollama", "host"): "OLLAMA_HOST",
    ("anthropic", "api_key"): "ANTHROPIC_API_KEY",
    ("openrouter", "api_key"): "OPENROUTER_API_KEY",
    ("openai_compat", "base_url"): "OPENAI_BASE_URL",
    ("openai_compat", "api_key"): "OPENAI_API_KEY",
}

SECRET_FIELDS = {"api_key"}

_lock = threading.Lock()


def _merge(base: dict, override: dict) -> dict:
    """Recursive merge so a config written by an older version still loads."""
    out = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def ensure_home() -> Path:
    """Create ~/.orchestra owner-only.

    Called from every path that writes here, not just config saves — agent
    definitions land in this directory too, and a world-readable home would
    otherwise exist for as long as it took the user to save a key.
    """
    HOME.mkdir(parents=True, exist_ok=True)
    try:
        HOME.chmod(0o700)
    except OSError:
        # Some filesystems (network shares, Windows) ignore POSIX modes. Not
        # worth failing startup over.
        pass
    return HOME


def load() -> dict[str, Any]:
    """Return the effective config: defaults <- file <- environment."""
    stored: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            # A corrupt config should not brick the app — fall back to defaults
            # and let the setup screen rewrite it.
            stored = {}

    cfg = _merge(DEFAULTS, stored)

    for (provider, field), env_var in ENV_OVERRIDES.items():
        value = os.environ.get(env_var)
        if value:
            cfg["providers"].setdefault(provider, {})[field] = value

    return cfg


def save(cfg: dict[str, Any]) -> dict[str, Any]:
    """Persist config with owner-only permissions."""
    with _lock:
        ensure_home()
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        tmp.chmod(0o600)
        tmp.replace(CONFIG_PATH)
    return cfg


def update(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a partial update into the stored config and save it.

    Only the file is written; environment overrides are re-applied on load, so a
    key supplied by the environment is never copied to disk.
    """
    stored: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            stored = {}
    save(_merge(stored, patch))
    return load()


def env_managed(provider: str, field: str) -> bool:
    """True when this value comes from the environment and the UI can't edit it."""
    env_var = ENV_OVERRIDES.get((provider, field))
    return bool(env_var and os.environ.get(env_var))


def mask(value: str | None) -> str | None:
    """Render a secret for display: keep the shape, drop the secret."""
    if not value:
        return None
    if len(value) <= 12:
        return "…" + value[-4:]
    return f"{value[:7]}…{value[-4:]}"


def redacted(cfg: dict[str, Any]) -> dict[str, Any]:
    """A copy safe to send to the browser: secrets masked, provenance flagged."""
    out = deepcopy(cfg)
    for provider, fields in out.get("providers", {}).items():
        if not isinstance(fields, dict):
            continue
        for field in list(fields):
            if field in SECRET_FIELDS:
                fields[f"{field}_set"] = bool(fields[field])
                fields[field] = mask(fields[field])
            if env_managed(provider, field):
                fields.setdefault("_env_managed", []).append(field)
    return out
