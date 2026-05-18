from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ApprovalAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True)
class ApprovalDecision:
    action: ApprovalAction
    reason: str
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ApprovalHandler(Protocol):
    def decide(self, request: ApprovalRequest) -> ApprovalDecision: ...


class DenyingApprovalHandler:
    def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(
            action=ApprovalAction.REJECT,
            reason="approval_not_available",
            message=request.message,
            metadata={"tool_name": request.tool_name},
        )
