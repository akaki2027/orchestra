"""Which tools exist, who may use them, and whether their model can.

Grants are per agent and default to none. An agent that was never given a tool
cannot reach one, so adding a server to the config does not quietly widen what
every existing agent can do.

The reliability estimate below is the honest half of this feature. Tool calling
is a structured-output problem, and small local models are bad at it — I hit
this building Research, which is why the local research path is a fixed
retrieve-then-answer pipeline rather than letting the model decide. Granting
tools to a 3B model produces silent failures: it writes a plausible-looking
call into prose, no tool runs, and the run continues as if it had.
"""

from __future__ import annotations

import re
from typing import Any

from .. import config, privacy
from .base import Tool, ToolError
from .guard import guarded
from .filesystem import FilesystemTool
from .mcp import MCPServer, MCPTool, MCPSession

# Rough parameter counts where a model id does not carry one.
_HOSTED_HINT = re.compile(r"(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z])")


def estimate_params_b(provider: str, model: str) -> float | None:
    """Best guess at model size, for the reliability warning only."""
    match = _HOSTED_HINT.search(model or "")
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    # Hosted frontier models carry no size in the id and are all comfortably
    # capable of tool calling.
    if provider in ("anthropic", "openrouter", "openai_compat"):
        return None
    return None


def _article(params: float) -> str:
    """"An 8B model", not "a 8B model" — 8, 11 and 18 are the spoken vowels."""
    return "An" if str(int(params)).startswith(("8", "11", "18")) else "A"


def tool_reliability(provider: str, model: str) -> dict[str, Any]:
    """Can this model be trusted to emit a structured tool call?

    Thresholds are from observed behaviour, not a benchmark: below roughly 7B,
    tool calling fails often enough that an agent will appear to work while
    doing nothing. Stated as a warning, never a block — it is the user's
    machine and their call.
    """
    params = estimate_params_b(provider, model)
    hosted = provider != "ollama"

    if hosted and params is None:
        return {"level": "good", "params_b": None,
                "note": "Hosted models of this class handle tool calling reliably."}
    if params is None:
        return {"level": "unknown", "params_b": None,
                "note": "Model size unknown, so tool-calling reliability cannot be judged."}
    if params < 4:
        return {"level": "poor", "params_b": params, "note": (
            f"{_article(params)} {params:g}B model calls tools unreliably. It will often describe a call "
            "in prose instead of making one, and the step will look like it succeeded "
            "while nothing ran. Give this agent no tools, or move it to a larger model.")}
    if params < 8:
        return {"level": "fair", "params_b": params, "note": (
            f"{_article(params)} {params:g}B model manages simple, single-argument tools and struggles "
            "with anything more structured. Keep its tool set small and its schemas flat.")}
    if params < 30:
        return {"level": "good", "params_b": params,
                "note": f"{_article(params)} {params:g}B model handles tool calling dependably."}
    return {"level": "good", "params_b": params,
            "note": f"{_article(params)} {params:g}B model handles tool calling dependably."}


# ---------------------------------------------------------------- registry

def servers(cfg: dict[str, Any] | None = None) -> list[MCPServer]:
    cfg = cfg or config.load()
    raw = (cfg.get("tools") or {}).get("mcp_servers") or []
    return [MCPServer.from_dict(entry) for entry in raw if entry.get("name")]


def find_server(name: str, cfg: dict[str, Any] | None = None) -> MCPServer | None:
    for server in servers(cfg):
        if server.name == name:
            return server
    return None


def save_servers(entries: list[MCPServer]) -> None:
    config.replace("tools", "mcp_servers", [
        {
            "name": s.name, "transport": s.transport, "command": s.command,
            "args": s.args or [], "env": s.env or {}, "url": s.url,
            "auth_header": s.auth_header, "approved": s.approved,
        }
        for s in entries
    ])


def filesystem_settings(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or config.load()
    fs = (cfg.get("tools") or {}).get("filesystem") or {}
    return {"root": fs.get("root"), "writable": bool(fs.get("writable"))}


async def available(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Everything grantable, for the agent editor. Never spawns a server."""
    cfg = cfg or config.load()
    out: list[dict[str, Any]] = []

    fs = filesystem_settings(cfg)
    out.append({
        "id": "filesystem",
        "label": "Filesystem",
        "reach": "local",
        "ready": bool(fs["root"]),
        "detail": (f"{fs['root']}{' · writable' if fs['writable'] else ' · read-only'}"
                   if fs["root"] else "No workspace folder set yet."),
    })

    for server in servers(cfg):
        out.append({
            "id": f"mcp:{server.name}",
            "label": server.name,
            "reach": server.reach,
            "ready": server.approved if server.transport == "stdio" else True,
            "detail": (server.command_line() if server.transport == "stdio" else server.url) or "",
            "needs_approval": server.transport == "stdio" and not server.approved,
        })
    return out


async def build_for(agent: dict[str, Any], cfg: dict[str, Any] | None = None) -> list[Tool]:
    """The tools this agent is allowed to use, instantiated and guarded.

    The only door. Every tool leaves here wrapped in `GuardedTool`, so a remote
    tool call is inspected under the same policy as a model call and lands on
    the same declaration. Do not add a path that returns a bare tool.

    A grant naming a server that has been removed or not yet approved is
    skipped rather than raised: an agent should degrade to fewer tools, not
    fail the whole run.
    """
    cfg = cfg or config.load()
    granted = list((agent.get("tools") or []))
    if not granted:
        return []

    built: list[Tool] = []

    if "filesystem" in granted:
        fs = filesystem_settings(cfg)
        if fs["root"]:
            try:
                built.append(FilesystemTool(fs["root"], writable=fs["writable"]))
            except ToolError:
                pass

    for grant in granted:
        if not grant.startswith("mcp:"):
            continue
        server = find_server(grant[4:], cfg)
        if not server:
            continue
        if server.transport == "stdio" and not server.approved:
            continue
        try:
            async with MCPSession(server) as session:
                descriptors = await session.list_tools()
        except ToolError:
            continue
        for descriptor in descriptors:
            built.append(MCPTool(server, descriptor))

    policy = privacy.Policy.from_config(cfg)
    return [guarded(tool, policy) for tool in built]
