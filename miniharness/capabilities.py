from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentCapabilities:
    has_memory: bool = False
    has_skills: bool = False
    has_permission_system: bool = False
    has_trace_hooks: bool = True
    supports_tool_registry: bool = True
