from .fs import ListDirTool, ReadFileTool, WriteFileTool
from .search import SearchTextTool
from .shell import RunShellTool
from .todo import TodoTool
from .base import ToolRegistry

TOOLS = [
    ListDirTool(),
    ReadFileTool(),
    WriteFileTool(),
    SearchTextTool(),
    RunShellTool(),
    TodoTool(),
]
TOOL_REGISTRY = ToolRegistry(TOOLS)

__all__ = [
    "TOOLS",
    "TOOL_REGISTRY",
    "ToolRegistry",
    "ListDirTool",
    "ReadFileTool",
    "WriteFileTool",
    "SearchTextTool",
    "RunShellTool",
    "TodoTool",
]
