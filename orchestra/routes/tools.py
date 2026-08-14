"""Tool setup: the workspace folder, MCP servers, and approval.

Approval has its own endpoint on purpose. Adding a stdio server and agreeing to
run it are two decisions, and collapsing them into one save would mean a pasted
config block spawns a process the moment it lands.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from .. import agents as agent_store
from .. import config
from ..tools import mcp as mcp_client
from ..tools import registry
from ..tools.base import ToolError

router = APIRouter(tags=["tools"])


@router.get("/tools")
async def read_tools() -> dict[str, Any]:
    cfg = config.load()
    return {
        "filesystem": registry.filesystem_settings(cfg),
        "servers": [s.as_dict() for s in registry.servers(cfg)],
        "available": await registry.available(cfg),
        "guidance": GUIDANCE,
    }


@router.patch("/tools/filesystem")
async def set_workspace(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    current = registry.filesystem_settings()
    root = payload.get("root", current["root"])
    root = (root or "").strip() or None

    if root:
        from pathlib import Path

        resolved = Path(root).expanduser()
        if not resolved.is_dir():
            raise HTTPException(400, f"Not a folder: {root}")
        # Nominating your home directory means every agent with the grant can
        # read everything you own. Allowed, but not by accident.
        if resolved.resolve() == Path.home().resolve() and not payload.get("confirm_home"):
            raise HTTPException(400, (
                "That is your whole home folder. Every agent granted the filesystem "
                "tool would be able to read all of it. Pick a project folder, or "
                "confirm you meant this."
            ))
        root = str(resolved.resolve())

    writable = bool(payload.get("writable", current["writable"]))
    config.replace("tools", "filesystem", {"root": root, "writable": writable})
    return await read_tools()


@router.post("/tools/mcp/probe")
async def probe_server(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Ask a server what it offers, before anything is granted.

    A stdio server has to be approved first — probing runs the command, which
    is the act being approved.
    """
    server = mcp_client.MCPServer.from_dict(payload)
    try:
        server.validate()
        tools = await mcp_client.probe(server)
    except ToolError as exc:
        raise HTTPException(400, str(exc)) from exc

    return {
        "server": server.as_dict(),
        "tools": [
            {"name": t.get("name"), "description": (t.get("description") or "").strip()[:300]}
            for t in tools
        ],
    }


@router.post("/tools/mcp")
async def save_server(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    server = mcp_client.MCPServer.from_dict(payload)
    try:
        server.validate()
    except ToolError as exc:
        raise HTTPException(400, str(exc)) from exc

    existing = registry.servers()
    previous = next((s for s in existing if s.name == server.name), None)
    if previous:
        # Changing the command revokes approval. Approval is of a specific
        # command line, not of a name.
        server.approved = previous.approved and previous.command_line() == server.command_line()
        existing = [s for s in existing if s.name != server.name]
    registry.save_servers(existing + [server])
    return await read_tools()


@router.post("/tools/mcp/{name}/approve")
async def approve_server(name: str) -> dict[str, Any]:
    entries = registry.servers()
    target = next((s for s in entries if s.name == name), None)
    if not target:
        raise HTTPException(404, f"No server named {name}.")
    target.approved = True
    registry.save_servers(entries)
    return await read_tools()


@router.delete("/tools/mcp/{name}")
async def remove_server(name: str) -> dict[str, Any]:
    entries = [s for s in registry.servers() if s.name != name]
    registry.save_servers(entries)

    # Revoke the grant everywhere rather than leaving dangling ids behind.
    for agent in agent_store.list_agents():
        granted = agent.get("tools") or []
        if f"mcp:{name}" in granted:
            agent["tools"] = [g for g in granted if g != f"mcp:{name}"]
            try:
                agent_store.save(agent)
            except agent_store.AgentError:
                continue
    return await read_tools()


@router.get("/tools/reliability")
async def reliability(provider: str, model: str = "") -> dict[str, Any]:
    """Whether this model can be trusted to emit a tool call at all."""
    return registry.tool_reliability(provider, model)


GUIDANCE = {
    "small_model_tools": (
        "Tool calling asks a model to emit exact JSON on demand. Models under "
        "roughly 7B do that unreliably — they describe the call in prose instead "
        "of making it, and the step then looks like it worked while nothing ran. "
        "Orchestra warns rather than blocks, because it is your machine."
    ),
    "small_model_use": [
        {
            "title": "Bulk transformation over text you already have",
            "body": (
                "Summarising, reformatting, extracting fields, translating, "
                "rewriting tone. There is no decision to get wrong, the input is "
                "in the prompt, and running it locally means the text never "
                "leaves. This is where a 3B model earns its place in a run."
            ),
        },
        {
            "title": "The privacy lane",
            "body": (
                "Any step touching real names, addresses, keys, or client data. "
                "Route it to a local agent and the values stay on this machine — "
                "which is the point of the whole routing tier, and something no "
                "hosted model can offer at any size."
            ),
        },
        {
            "title": "Wide parallel fan-out",
            "body": (
                "Twelve documents, one question each. Small models are cheap "
                "enough to run several at once, and the orchestrator does the "
                "reasoning over their outputs."
            ),
        },
        {
            "title": "First-pass drafting and triage",
            "body": (
                "Rough drafts, classification, deciding what deserves a bigger "
                "model. Cheap where being approximately right is enough."
            ),
        },
    ],
    "small_model_avoid": [
        "Tool calling and MCP — that is what this warning is about.",
        "Multi-step reasoning where an early mistake propagates.",
        "Anything where a confident wrong answer costs more than no answer.",
        "Synthesis across many agent outputs — leave that to the orchestrator.",
    ],
}
