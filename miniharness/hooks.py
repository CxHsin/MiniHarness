from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Any, Protocol, TextIO

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HookEvent:
    type: str
    run_id: str
    step: int | None
    payload: dict[str, Any]


class AgentHook(Protocol):
    def handle(self, event: HookEvent) -> None:
        ...


class HookDispatcher:
    def __init__(self, hooks: list[AgentHook] | None = None):
        self._hooks = list(hooks or [])

    def emit(self, event: HookEvent) -> None:
        for hook in self._hooks:
            try:
                hook.handle(event)
            except Exception:
                logger.exception("Hook dispatch failed")


class ConsoleHook:
    def __init__(self, stream: TextIO | None = None):
        self._stream = stream or sys.stderr

    def handle(self, event: HookEvent) -> None:
        self._stream.write(self._format(event) + "\n")
        self._stream.flush()

    def _format(self, event: HookEvent) -> str:
        prefix = "[run]" if event.step is None else f"[step {event.step + 1}]"
        if event.type == "run.started":
            return f"{prefix} started"
        if event.type == "run.completed":
            steps_used = event.payload.get("steps_used", "?")
            return f"{prefix} completed in {steps_used} steps"
        if event.type == "run.failed":
            return f"{prefix} failed: {event.payload.get('error', 'unknown error')}"
        if event.type == "model.completed":
            tool_call_count = event.payload.get("tool_call_count", 0)
            if event.payload.get("is_continuation"):
                return f"{prefix} model completed (continuation)"
            if tool_call_count:
                return f"{prefix} model completed with {tool_call_count} tool calls"
            return f"{prefix} model completed"
        if event.type == "tool.started":
            tool_name = event.payload.get("tool_name", "unknown")
            arguments_summary = event.payload.get("arguments_summary", "")
            suffix = f" {arguments_summary}" if arguments_summary else ""
            return f"{prefix} tool {tool_name} started{suffix}"
        if event.type == "tool.completed":
            tool_name = event.payload.get("tool_name", "unknown")
            if event.payload.get("ok"):
                return f"{prefix} tool {tool_name} completed ok"
            return f"{prefix} tool {tool_name} failed: {event.payload.get('error', 'unknown error')}"
        return f"{prefix} {event.type}"


__all__ = ["HookEvent", "AgentHook", "HookDispatcher", "ConsoleHook"]
