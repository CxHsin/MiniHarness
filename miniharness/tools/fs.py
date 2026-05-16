from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolContext, ToolResult, is_sensitive_path, resolve_path


class ListDirTool(Tool):
    name = "list_dir"
    description = "List directory entries under the working directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
        },
    }

    def execute(self, args: dict, context: ToolContext) -> ToolResult:
        try:
            path = resolve_path(args.get("path", "."), context)
            if not path.is_dir():
                return ToolResult(False, "", f"not a directory: {args.get('path', '.')}")
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = [self._format_entry(entry) for entry in entries[:500]]
            omitted = len(entries) - 500
            if omitted > 0:
                lines.append(f"... [{omitted} entries omitted]")
            return ToolResult(True, "\n".join(lines), None)
        except Exception as exc:
            return ToolResult(False, "", str(exc))

    @staticmethod
    def _format_entry(entry: Path) -> str:
        if entry.is_dir():
            return f"[dir]  {entry.name}/"
        return f"[file] {entry.name}  {entry.stat().st_size} bytes"


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a UTF-8 text file under the working directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "limit": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
    }

    def execute(self, args: dict, context: ToolContext) -> ToolResult:
        try:
            path = resolve_path(args["path"], context)
            raw = path.read_bytes()
            if b"\x00" in raw:
                return ToolResult(False, "", "Binary file cannot be read as text")
            text = raw.decode("utf-8")
            lines = text.splitlines()
            start_line = args.get("start_line")
            limit = args.get("limit")
            if start_line is not None:
                start_index = max(int(start_line) - 1, 0)
                end_index = None if limit is None else start_index + int(limit)
                selected = lines[start_index:end_index]
                numbered = [
                    f"{line_number}: {line}"
                    for line_number, line in enumerate(selected, start=start_index + 1)
                ]
                return ToolResult(True, "\n".join(numbered), None)
            if limit is not None:
                lines = lines[: int(limit)]
                return ToolResult(True, "\n".join(lines), None)
            return ToolResult(True, text, None)
        except Exception as exc:
            return ToolResult(False, "", str(exc))


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write UTF-8 text to a file under the working directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def execute(self, args: dict, context: ToolContext) -> ToolResult:
        try:
            path = resolve_path(args["path"], context)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            metadata = {"sensitive_path": is_sensitive_path(path)}
            return ToolResult(True, f"wrote {path}", None, metadata)
        except Exception as exc:
            return ToolResult(False, "", str(exc))
