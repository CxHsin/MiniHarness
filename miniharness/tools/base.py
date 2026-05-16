from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

SENSITIVE_PATH_PARTS = {
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".kube",
}
SENSITIVE_FILENAMES = {
    "credentials",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "known_hosts",
    "config",
}


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class ToolContext:
    cwd: Path
    allow_outside_cwd: bool = False
    shell_timeout: int = 30
    todos: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        self.cwd = Path(self.cwd).resolve()
        if self.todos is None:
            self.todos = []


class BaseTool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        ...

    def to_openai_tool(self) -> dict[str, Any]:
        ...


class Tool:
    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def resolve_path(path: str, context: ToolContext) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = context.cwd / candidate
    resolved = candidate.resolve()
    if context.allow_outside_cwd:
        return resolved
    try:
        resolved.relative_to(context.cwd)
    except ValueError as exc:
        raise ValueError(f"path resolves outside cwd: {path}") from exc
    return resolved


def is_sensitive_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if parts & SENSITIVE_PATH_PARTS:
        return True
    return path.name.lower() in SENSITIVE_FILENAMES and bool(parts & SENSITIVE_PATH_PARTS)
