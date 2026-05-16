from __future__ import annotations

from .base import Tool, ToolContext, ToolResult


class TodoTool(Tool):
    name = "todo"
    description = "Maintain a session-local todo list."
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "done", "remove", "clear"],
            },
            "text": {"type": "string"},
            "index": {"type": "integer", "minimum": 1},
        },
        "required": ["action"],
    }

    def execute(self, args: dict, context: ToolContext) -> ToolResult:
        action = args.get("action")
        todos = context.todos
        if todos is None:
            return ToolResult(False, "", "todo state is unavailable")
        if action == "add":
            text = args.get("text")
            if not text:
                return ToolResult(False, "", "text is required")
            todos.append({"text": text, "done": False})
            return ToolResult(True, self._format(todos), None)
        if action == "list":
            return ToolResult(True, self._format(todos), None)
        if action == "done":
            todo = self._get_by_index(todos, args.get("index"))
            if isinstance(todo, ToolResult):
                return todo
            todo["done"] = True
            return ToolResult(True, self._format(todos), None)
        if action == "remove":
            index = args.get("index")
            todo = self._get_by_index(todos, index)
            if isinstance(todo, ToolResult):
                return todo
            del todos[int(index) - 1]
            return ToolResult(True, self._format(todos), None)
        if action == "clear":
            todos.clear()
            return ToolResult(True, "cleared todos", None)
        return ToolResult(False, "", f"unknown action: {action}")

    @staticmethod
    def _get_by_index(todos, index):
        if index is None:
            return ToolResult(False, "", "index is required")
        position = int(index) - 1
        if position < 0 or position >= len(todos):
            return ToolResult(False, "", "index out of range")
        return todos[position]

    @staticmethod
    def _format(todos) -> str:
        if not todos:
            return "no todos"
        lines = []
        for index, todo in enumerate(todos, start=1):
            marker = "x" if todo["done"] else " "
            lines.append(f"{index}. [{marker}] {todo['text']}")
        return "\n".join(lines)
