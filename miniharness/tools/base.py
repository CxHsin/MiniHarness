from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

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

    @property
    def is_error(self) -> bool:
        return not self.ok

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

    def execute_validated(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        ...

    def to_openai_tool(self) -> dict[str, Any]:
        ...


class Tool:
    name: str
    description: str
    parameters: dict[str, Any]

    def execute_validated(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        validation = validate_tool_arguments(self, args)
        if validation.is_error:
            return ToolResult(False, "", f"invalid arguments: {validation.error}")
        return self.execute(args, context)

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": deepcopy(self.parameters),
            },
        }


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool] | None = None):
        self._tools: dict[str, BaseTool] = {}
        for tool in tools or []:
            result = self.register(tool)
            if result.is_error:
                raise ValueError(result.error)

    def register(self, tool: BaseTool) -> ToolResult:
        if tool.name in self._tools:
            return ToolResult(False, "", f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool
        return ToolResult(True, f"registered {tool.name}")

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list(self) -> list[BaseTool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def execute(
        self,
        name: str,
        args: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(False, "", f"unknown tool: {name}")
        return tool.execute_validated(args, context)


def validate_tool_arguments(tool: BaseTool, args: dict[str, Any]) -> ToolResult:
    schema = getattr(tool, "parameters", {}) or {}
    required = schema.get("required", [])
    for name in required:
        if name not in args:
            return ToolResult(False, "", f"{name} is required")

    properties = schema.get("properties", {})
    for name, value in args.items():
        property_schema = properties.get(name)
        if property_schema is None:
            continue
        error = _validate_schema_value(name, value, property_schema)
        if error:
            return ToolResult(False, "", error)
    return ToolResult(True, "")


def _validate_schema_value(name: str, value: Any, schema: dict[str, Any]) -> str | None:
    expected_type = schema.get("type")
    if expected_type and not _matches_json_type(value, expected_type):
        return f"{name} must be {expected_type}"

    if "enum" in schema and value not in schema["enum"]:
        return f"{name} must be one of {schema['enum']}"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            return f"{name} must be >= {minimum}"
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            return f"{name} must be <= {maximum}"
    return None


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    return True


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
