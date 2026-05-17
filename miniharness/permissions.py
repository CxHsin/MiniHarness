from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .policy import RuntimePolicy


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    error: str | None = None


def check_tool_permission(
    policy: RuntimePolicy,
    tool_name: str,
    args: dict[str, Any],
) -> PermissionDecision:
    del args

    if tool_name == "run_shell" and policy.shell_enabled is False:
        return PermissionDecision(
            allowed=False,
            error=f"tool {tool_name} is disabled by runtime policy",
        )

    return PermissionDecision(allowed=True)
