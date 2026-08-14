"""Read and write files inside one folder you nominate.

This is the tool that makes the Coder agent useful: VS Code reloads from disk,
so an agent editing files in your project shows up as a diff in your editor
without anything having to drive the editor itself.

The entire risk surface is path escape. The model supplies the path, so every
operation resolves the path first and checks it is still inside the workspace
after symlinks are followed — `..`, an absolute path, and a symlink pointing at
`~/.ssh` all have to fail, and `resolve()` before comparison is what makes that
true. A check on the string before resolution catches none of them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .base import ToolError, ToolResult, ToolSpec, wrap_untrusted

MAX_READ_BYTES = 256_000
MAX_WRITE_BYTES = 1_000_000
MAX_LIST_ENTRIES = 400

# Never handed to a model, whatever the workspace is set to. A project folder
# routinely contains credentials, and "the agent read your .env" is not a
# failure mode worth discovering in production.
DENY_NAMES = {
    ".env", ".env.local", ".env.production", ".netrc", ".npmrc", ".pypirc",
    "id_rsa", "id_ed25519", "credentials", "credentials.json", ".git-credentials",
}
DENY_DIRS = {".git", ".ssh", "node_modules", "__pycache__", ".venv", "venv"}
DENY_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}


class FilesystemTool:
    """Workspace-confined file access. Local reach: nothing crosses the border."""

    def __init__(self, root: str, writable: bool = False) -> None:
        if not root:
            raise ToolError("No workspace folder is set for the filesystem tool.")
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ToolError(f"The workspace folder does not exist: {self.root}")
        self.writable = writable

        actions = "read_file, list_dir, search" + (", write_file" if writable else "")
        self.spec = ToolSpec(
            name="filesystem",
            description=(
                f"Read and inspect files inside {self.root}. "
                f"Actions: {actions}. Paths are relative to that folder and cannot "
                "escape it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read_file", "list_dir", "search"] + (["write_file"] if writable else []),
                    },
                    "path": {"type": "string", "description": "Path relative to the workspace root"},
                    "content": {"type": "string", "description": "For write_file"},
                    "query": {"type": "string", "description": "For search: text to find"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            reach="local",
            source="builtin",
        )

    # -- the guard --------------------------------------------------------

    def _resolve(self, raw: str | None) -> Path:
        """Resolve a model-supplied path and prove it stayed inside the workspace.

        Resolution happens first, so `..`, an absolute path, and a symlink
        pointing outside are all normalised before the containment check rather
        than after it.
        """
        candidate = (self.root / (raw or "")).expanduser()
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:  # RuntimeError: symlink loop
            raise ToolError(f"Could not resolve that path: {raw}") from exc

        if resolved != self.root and self.root not in resolved.parents:
            raise ToolError(
                f"Refused: {raw!r} resolves outside the workspace. "
                "The filesystem tool cannot reach beyond the folder you nominated."
            )

        rel = resolved.relative_to(self.root) if resolved != self.root else Path(".")
        parts = set(rel.parts)
        if parts & DENY_DIRS:
            raise ToolError(f"Refused: {rel} is inside a directory this tool never opens.")
        if resolved.name in DENY_NAMES or resolved.suffix.lower() in DENY_SUFFIXES:
            raise ToolError(f"Refused: {resolved.name} looks like a credential file.")
        return resolved

    # -- actions ----------------------------------------------------------

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        action = (arguments or {}).get("action")
        if action == "read_file":
            return self._read(arguments.get("path"))
        if action == "list_dir":
            return self._list(arguments.get("path"))
        if action == "search":
            return self._search(arguments.get("query"), arguments.get("path"))
        if action == "write_file":
            if not self.writable:
                raise ToolError("This filesystem tool is read-only. Enable writing on the agent to change files.")
            return self._write(arguments.get("path"), arguments.get("content"))
        raise ToolError(f"Unknown filesystem action: {action!r}")

    def _read(self, raw: str | None) -> ToolResult:
        target = self._resolve(raw)
        if not target.is_file():
            raise ToolError(f"Not a file: {raw}")
        data = target.read_bytes()[: MAX_READ_BYTES + 1]
        truncated = len(data) > MAX_READ_BYTES
        try:
            text = data[:MAX_READ_BYTES].decode("utf-8")
        except UnicodeDecodeError:
            raise ToolError(f"{raw} is not text this tool can read.") from None
        if truncated:
            text += f"\n\n[truncated at {MAX_READ_BYTES:,} bytes]"
        rel = target.relative_to(self.root)
        return ToolResult(True, wrap_untrusted(f"file:{rel}", text), {"path": str(rel), "bytes": len(data)})

    def _list(self, raw: str | None) -> ToolResult:
        target = self._resolve(raw)
        if not target.is_dir():
            raise ToolError(f"Not a directory: {raw}")
        rows = []
        for entry in sorted(target.iterdir())[:MAX_LIST_ENTRIES]:
            if entry.name in DENY_NAMES or entry.name in DENY_DIRS:
                continue
            kind = "dir " if entry.is_dir() else "file"
            size = "" if entry.is_dir() else f"  {entry.stat().st_size:,} B"
            rows.append(f"{kind}  {entry.relative_to(self.root)}{size}")
        body = "\n".join(rows) or "(empty)"
        return ToolResult(True, wrap_untrusted(f"dir:{target.relative_to(self.root) if target != self.root else '.'}", body), {"entries": len(rows)})

    def _search(self, query: str | None, raw: str | None) -> ToolResult:
        if not (query or "").strip():
            raise ToolError("search needs a query.")
        start = self._resolve(raw)
        needle = query.lower()
        hits: list[str] = []
        for path in start.rglob("*"):
            if len(hits) >= 60:
                break
            if not path.is_file():
                continue
            rel = path.relative_to(self.root)
            if set(rel.parts) & DENY_DIRS or path.name in DENY_NAMES:
                continue
            try:
                if path.stat().st_size > MAX_READ_BYTES:
                    continue
                for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                    if needle in line.lower():
                        hits.append(f"{rel}:{n}: {line.strip()[:180]}")
                        break
            except OSError:
                continue
        body = "\n".join(hits) or f"No file under {start.relative_to(self.root) if start != self.root else '.'} contains {query!r}."
        return ToolResult(True, wrap_untrusted(f"search:{query}", body), {"hits": len(hits)})

    def _write(self, raw: str | None, content: str | None) -> ToolResult:
        if content is None:
            raise ToolError("write_file needs content.")
        if len(content.encode()) > MAX_WRITE_BYTES:
            raise ToolError(f"Refused: over the {MAX_WRITE_BYTES:,} byte write limit.")
        target = self._resolve(raw)
        if target.is_dir():
            raise ToolError(f"{raw} is a directory.")
        target.parent.mkdir(parents=True, exist_ok=True)

        existed = target.is_file()
        # One backup of the previous contents. An agent overwriting work with no
        # way back is the failure people actually hit.
        if existed:
            backup = target.with_suffix(target.suffix + ".orchestra-bak")
            try:
                backup.write_bytes(target.read_bytes())
            except OSError:
                pass
        target.write_text(content)
        rel = target.relative_to(self.root)
        verb = "Replaced" if existed else "Created"
        return ToolResult(
            True,
            f"{verb} {rel} ({len(content):,} characters)."
            + (f" Previous contents kept at {rel}.orchestra-bak." if existed else ""),
            {"path": str(rel), "created": not existed},
        )


def default_workspace() -> str:
    return os.path.expanduser("~")
