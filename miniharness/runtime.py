from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .capabilities import AgentCapabilities
from .hooks import AgentHook
from .policy import RuntimePolicy
from .session import Session
from .tools.base import ToolContext


@dataclass
class AgentRuntime:
    cwd: Path
    session: Session
    tool_context: ToolContext
    policy: RuntimePolicy
    capabilities: AgentCapabilities
    hooks: list[AgentHook] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        cwd: str | Path,
        policy: RuntimePolicy,
        capabilities: AgentCapabilities,
        history_budget_chars: int = 120000,
        hooks: list[AgentHook] | None = None,
    ) -> "AgentRuntime":
        resolved_cwd = Path(cwd).resolve()
        return cls(
            cwd=resolved_cwd,
            session=Session(cwd=resolved_cwd, history_budget_chars=history_budget_chars),
            tool_context=ToolContext(
                cwd=resolved_cwd,
                # Fields duplicated from RuntimePolicy to ToolContext for backward compatibility.
                # Future: ToolContext should reference RuntimePolicy directly.
                allow_outside_cwd=policy.allow_outside_cwd,
                shell_timeout=policy.shell_timeout,
            ),
            policy=policy,
            capabilities=capabilities,
            hooks=list(hooks or []),
        )
