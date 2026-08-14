"""MCP client: connect a server, list what it offers, call it.

MCP is the reason neither you nor I have to write a per-integration adapter for
every service. A server declares its own tools; Orchestra reads that list and
offers them to whichever agents you grant.

Two transports, and the difference is the whole privacy story:

  stdio  — a process spawned on this machine. Interior. Nothing crosses.
  http   — someone else's server. Exterior, inspected on the way out, and it
           lands on the declaration exactly like a hosted model call.

One thing to be clear-eyed about: a stdio server is arbitrary code running as
you. `npx -y some-package` downloads and executes whatever is behind that name.
So a server is never spawned until it has been approved once, by exact command,
and the command is shown verbatim before approval. Orchestra never installs
anything on its own.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from typing import Any

import httpx

from .base import ToolError, ToolResult, ToolSpec, wrap_untrusted

HANDSHAKE_TIMEOUT = 20.0
CALL_TIMEOUT = 120.0
PROTOCOL_VERSION = "2024-11-05"

# Commands that would run an interpreter over arbitrary text rather than a
# named package. Approval is per-command, so this only blocks the shapes where
# "approve once" would amount to approving anything at all later.
FORBIDDEN_HEADS = {"sh", "bash", "zsh", "eval", "source", "curl", "wget"}


@dataclass
class MCPServer:
    name: str
    transport: str = "stdio"        # "stdio" | "http"
    command: str | None = None      # stdio
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None          # http
    auth_header: str | None = None
    approved: bool = False

    @property
    def reach(self) -> str:
        return "local" if self.transport == "stdio" else "remote"

    def command_line(self) -> str:
        return " ".join([self.command or ""] + list(self.args or [])).strip()

    def as_dict(self, *, redact: bool = True) -> dict[str, Any]:
        out = {
            "name": self.name, "transport": self.transport, "command": self.command,
            "args": self.args or [], "url": self.url, "approved": self.approved,
            "reach": self.reach, "command_line": self.command_line(),
        }
        out["auth_header"] = "set" if (self.auth_header and redact) else self.auth_header
        out["env_keys"] = sorted((self.env or {}).keys())
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MCPServer":
        return cls(
            name=(raw.get("name") or "").strip(),
            transport=raw.get("transport") or "stdio",
            command=(raw.get("command") or None),
            args=list(raw.get("args") or []),
            env=dict(raw.get("env") or {}),
            url=(raw.get("url") or None),
            auth_header=(raw.get("auth_header") or None),
            approved=bool(raw.get("approved")),
        )

    def validate(self) -> None:
        if not self.name or not self.name.replace("-", "").replace("_", "").isalnum():
            raise ToolError("Give the server a short name: letters, numbers, dashes.")
        if self.transport == "stdio":
            if not self.command:
                raise ToolError("A stdio server needs a command to run.")
            head = os.path.basename(self.command)
            if head in FORBIDDEN_HEADS:
                raise ToolError(
                    f"Refused: {head} runs arbitrary text, so approving it once would "
                    "approve anything it is later handed. Point at the package or "
                    "binary directly."
                )
            if not shutil.which(self.command):
                raise ToolError(f"Not on your PATH: {self.command}")
        elif self.transport == "http":
            if not (self.url or "").startswith(("http://", "https://")):
                raise ToolError("An HTTP server needs a http(s) URL.")
        else:
            raise ToolError(f"Unknown transport: {self.transport}")


class MCPSession:
    """One connection. Short-lived: opened per operation, closed after.

    Long-lived subprocesses would mean supervising them across reloads and
    crashes for no benefit — an agent's tool call is not hot enough to justify
    a process pool.
    """

    def __init__(self, server: MCPServer) -> None:
        self.server = server
        self._proc: asyncio.subprocess.Process | None = None
        self._id = 0

    async def __aenter__(self) -> "MCPSession":
        if self.server.transport == "stdio":
            if not self.server.approved:
                raise ToolError(
                    f"'{self.server.name}' has not been approved yet. It would run "
                    f"`{self.server.command_line()}` on this machine."
                )
            env = {**os.environ, **(self.server.env or {})}
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    self.server.command, *(self.server.args or []),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
            except OSError as exc:
                raise ToolError(f"Could not start {self.server.command}: {exc}") from exc
            await self._handshake()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def _rpc(self, method: str, params: dict[str, Any] | None = None, timeout: float = CALL_TIMEOUT) -> Any:
        if self.server.transport == "http":
            return await self._rpc_http(method, params, timeout)
        return await self._rpc_stdio(method, params, timeout)

    async def _rpc_stdio(self, method: str, params: dict[str, Any] | None, timeout: float) -> Any:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise ToolError("The MCP server is not running.")
        request = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params or {}}
        self._proc.stdin.write((json.dumps(request) + "\n").encode())
        await self._proc.stdin.drain()

        while True:
            try:
                line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=timeout)
            except asyncio.TimeoutError:
                raise ToolError(f"{self.server.name} did not answer {method} within {timeout:.0f}s.") from None
            if not line:
                err = ""
                if self._proc.stderr:
                    err = (await self._proc.stderr.read(600)).decode(errors="replace").strip()
                raise ToolError(f"{self.server.name} exited without answering. {err}".strip())
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # servers log to stdout; skip anything that is not a frame
            # Notifications carry no id; keep reading until our reply arrives.
            if message.get("id") != request["id"]:
                continue
            if "error" in message:
                raise ToolError(f"{self.server.name}: {message['error'].get('message', message['error'])}")
            return message.get("result")

    async def _rpc_http(self, method: str, params: dict[str, Any] | None, timeout: float) -> Any:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.server.auth_header:
            headers["Authorization"] = self.server.auth_header
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params or {}}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(self.server.url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    raise ToolError(f"{self.server.name} returned {resp.status_code}: {resp.text[:300]}")
                body = resp.text.strip()
                # Streamable-HTTP servers answer with SSE framing.
                if body.startswith("event:") or body.startswith("data:"):
                    for line in body.splitlines():
                        if line.startswith("data:"):
                            body = line[5:].strip()
                            break
                message = json.loads(body)
        except httpx.HTTPError as exc:
            raise ToolError(f"Could not reach {self.server.name}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ToolError(f"{self.server.name} sent something that is not JSON-RPC.") from exc

        if "error" in message:
            raise ToolError(f"{self.server.name}: {message['error'].get('message', message['error'])}")
        return message.get("result")

    async def _handshake(self) -> None:
        await self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "Orchestra", "version": "0.1.0"},
        }, timeout=HANDSHAKE_TIMEOUT)
        if self._proc and self._proc.stdin:
            note = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            self._proc.stdin.write((json.dumps(note) + "\n").encode())
            await self._proc.stdin.drain()

    async def list_tools(self) -> list[dict[str, Any]]:
        if self.server.transport == "http":
            await self._rpc("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "Orchestra", "version": "0.1.0"},
            }, timeout=HANDSHAKE_TIMEOUT)
        result = await self._rpc("tools/list", timeout=HANDSHAKE_TIMEOUT)
        return (result or {}).get("tools") or []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        blocks = (result or {}).get("content") or []
        parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        text = "\n".join(p for p in parts if p) or json.dumps(result)[:4000]
        if (result or {}).get("isError"):
            raise ToolError(f"{self.server.name}/{name}: {text[:400]}")
        return text


async def probe(server: MCPServer) -> list[dict[str, Any]]:
    """What does this server actually offer? Shown before anything is granted."""
    server.validate()
    async with MCPSession(server) as session:
        return await session.list_tools()


class MCPTool:
    """One tool exposed by one server, in Orchestra's shape."""

    def __init__(self, server: MCPServer, descriptor: dict[str, Any]) -> None:
        self.server = server
        self.tool_name = descriptor.get("name", "")
        self.spec = ToolSpec(
            name=f"{server.name}.{self.tool_name}",
            description=descriptor.get("description") or f"{self.tool_name} via {server.name}",
            input_schema=descriptor.get("inputSchema") or {"type": "object", "properties": {}},
            reach=server.reach,
            source=f"mcp:{server.name}",
        )

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        async with MCPSession(self.server) as session:
            text = await session.call_tool(self.tool_name, arguments)
        return ToolResult(
            True,
            wrap_untrusted(f"mcp:{self.server.name}/{self.tool_name}", text),
            {"server": self.server.name, "tool": self.tool_name, "reach": self.server.reach},
        )
