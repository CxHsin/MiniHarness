from __future__ import annotations

import re

from .base import Tool, ToolContext, ToolResult, resolve_path

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "dist"}


class SearchTextTool(Tool):
    name = "search_text"
    description = "Search UTF-8 text files with a Python regular expression."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "default": "."},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        },
        "required": ["pattern"],
    }

    def execute(self, args: dict, context: ToolContext) -> ToolResult:
        try:
            pattern = args.get("pattern", "")
            if not pattern:
                return ToolResult(False, "", "pattern is required")
            max_results = int(args.get("max_results", 100))
            if max_results < 1 or max_results > 500:
                return ToolResult(False, "", "max_results must be between 1 and 500")
            regex = re.compile(pattern)
            root = resolve_path(args.get("path", "."), context)
            files = [root] if root.is_file() else self._iter_files(root)
            matches: list[str] = []
            omitted = 0
            for file_path in files:
                try:
                    with file_path.open("r", encoding="utf-8") as handle:
                        for line_number, line in enumerate(handle, start=1):
                            if regex.search(line):
                                if len(matches) < max_results:
                                    rel = file_path.relative_to(context.cwd)
                                    matches.append(f"{rel.as_posix()}:{line_number}:{line.rstrip()}")
                                else:
                                    omitted += 1
                except (UnicodeDecodeError, OSError, ValueError):
                    continue
            if omitted:
                matches.append(f"... [{omitted} matches omitted]")
            return ToolResult(True, "\n".join(matches), None)
        except Exception as exc:
            return ToolResult(False, "", str(exc))

    def _iter_files(self, root):
        for path in root.rglob("*"):
            # V1 intentionally skips common generated directories by directory name.
            if path.is_dir() and path.name in SKIP_DIRS:
                continue
            if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
                yield path
