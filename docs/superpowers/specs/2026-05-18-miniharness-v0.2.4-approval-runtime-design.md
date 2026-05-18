# MiniHarness v0.2.4 Approval Runtime Skeleton Design

Date: 2026-05-18

## Goal

MiniHarness v0.2.4 should turn approval from a permission outcome label into a real runtime subsystem.

The goal of this increment is not to deliver a full interactive approval dialog yet. The goal is to make `ASK_USER` participate in execution through a dedicated approval layer so future CLI, TUI, or UI approval flows have a stable place to attach.

After this increment:

- permission evaluation should still decide `ALLOW`, `DENY`, or `ASK_USER`
- `ASK_USER` should no longer collapse immediately into a generic tool failure
- `Agent` should route approval-required actions through an approval handler
- runtime composition should own the default approval behavior

## Scope

v0.2.4 should:

- introduce an approval runtime module
- define request and decision types for approvals
- define an approval handler interface and a default conservative implementation
- compose approval handling into `AgentRuntime`
- route `PermissionAction.ASK_USER` through the approval layer inside `Agent._execute_tool_call()`
- preserve existing behavior for `ALLOW` and `DENY`
- keep the new approval path limited to the existing `run_shell` permission pipeline in practice

v0.2.4 should not:

- implement an interactive CLI approval prompt yet
- add `--approval-policy` or other new CLI approval flags
- persist approval history or user choices
- expand the new approval pipeline to file tools in this increment
- redesign all permission metadata or risk classification in one pass

## Why This Increment Now

v0.2.3 established the correct permission decision shape:

1. deny rules
2. mode-aware allow behavior
3. approval-required fallback

But the execution path still treats `ASK_USER` as a failed tool result. That is useful as a placeholder, but it is not yet a real harness approval system.

The next useful step is to add a runtime-owned approval boundary without prematurely committing to one user interaction surface. This keeps the architecture moving toward OpenHarness-style harness engineering while keeping the implementation small and testable.

## Recommended Approach

Add a new module:

- `miniharness/approvals.py`

This module should contain the runtime-facing approval abstractions. Permission evaluation should stay in `miniharness/permissions.py`; approval execution should move into its own subsystem.

This is preferable to extending `permissions.py` further because:

- permissions remain responsible for classification and policy decisions
- approvals become responsible for handling unresolved actions
- `Agent` stays the single orchestration boundary
- future UI-specific approval implementations can be added without rewriting permission logic

No package export change is required in this increment. However, `miniharness.approvals` should be treated as a real module-level API surface for future custom approval handlers even if `miniharness/__init__.py` does not re-export those types in v0.2.4.

## Design Overview

### New Approval Types

v0.2.4 should introduce three core concepts:

```python
@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

```python
class ApprovalAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
```

```python
@dataclass(frozen=True)
class ApprovalDecision:
    action: ApprovalAction
    reason: str
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Field intent:

- `ApprovalRequest`: what is being asked for approval
- `ApprovalAction`: whether the request is approved or rejected
- `ApprovalDecision`: the approval subsystem's result

Within `ApprovalRequest`:

- `reason` should carry the stable machine-readable explanation key from permission evaluation, such as `approval_required`
- `message` should carry the user-facing text, such as `tool run_shell requires user approval in the current permission mode`

The request should carry the tool name, raw arguments, and permission-derived metadata forward intact so later approval UIs do not need to reconstruct missing context.

`ApprovalRequest.arguments` should contain the original parsed tool-call arguments from the model response. By the time approval handling runs, JSON parsing has already succeeded, but tool-schema validation has not necessarily happened yet. Approval handlers should treat these arguments as parsed-but-not-yet-validated input.

### Approval Handler Interface

The approval subsystem should be runtime-pluggable:

```python
class ApprovalHandler(Protocol):
    def decide(self, request: ApprovalRequest) -> ApprovalDecision: ...
```

The default implementation in v0.2.4 should be conservative:

```python
class DenyingApprovalHandler:
    def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(
            action=ApprovalAction.REJECT,
            reason="approval_not_available",
            message=request.message,
            metadata={"tool_name": request.tool_name},
        )
```

This implementation is intentionally simple. Its job is not to simulate approval; its job is to prove the execution shape while keeping behavior safe by default.

The default rejecting handler should preserve the original permission-layer user-facing message rather than replacing it with a new approval-specific string. This keeps current `ASK_USER`-path agent tests and user-visible error text stable while the execution shape changes underneath.

### AgentRuntime Composition

`AgentRuntime` should gain an approval handler field:

```python
@dataclass
class AgentRuntime:
    cwd: Path
    session: Session
    tool_context: ToolContext
    policy: RuntimePolicy
    capabilities: AgentCapabilities
    hooks: list[AgentHook]
    approval_handler: ApprovalHandler = field(default_factory=DenyingApprovalHandler)
```

`AgentRuntime.create(...)` should construct a default `DenyingApprovalHandler()` when one is not provided.

This keeps runtime as the composition layer, consistent with how hooks, policy, and capabilities were introduced in v0.2.1.

This default is important for direct `AgentRuntime(...)` construction as well as `AgentRuntime.create(...)`. v0.2.4 should not allow `approval_handler` to be absent, because an absent handler would turn `ASK_USER` into an execution-time crash rather than a conservative rejection.

### Execution Flow

The updated execution flow inside `Agent._execute_tool_call()` should be:

1. handle tool JSON parse errors
2. call `check_tool_permission(...)`
3. if `ALLOW`, execute the tool normally
4. if `DENY`, return a failed `ToolResult`
5. if `ASK_USER`, build an `ApprovalRequest`
6. call `self.runtime.approval_handler.decide(request)`
7. if approved, execute the tool
8. if rejected, return a failed `ToolResult`

Suggested shape:

```python
decision = check_tool_permission(
    self.runtime.policy,
    tool_call.name,
    tool_call.arguments,
)

if decision.action is PermissionAction.DENY:
    return ToolResult(False, "", decision.message or decision.reason, decision.metadata)

if decision.action is PermissionAction.ASK_USER:
    request = ApprovalRequest(
        tool_name=tool_call.name,
        arguments=tool_call.arguments,
        reason=decision.reason,
        message=decision.message or decision.reason,
        metadata=decision.metadata,
    )
    approval = self.runtime.approval_handler.decide(request)
    if approval.action is ApprovalAction.REJECT:
        metadata = dict(decision.metadata)
        if approval.metadata:
            metadata["approval"] = approval.metadata
        return ToolResult(False, "", approval.message or approval.reason, metadata)
```

If approval is granted, execution should continue into `self.tools.execute(...)` exactly as it does for `ALLOW`.

### Default Behavior

The default approval behavior in v0.2.4 should be:

- `ALLOW`: execute immediately
- `DENY`: reject immediately
- `ASK_USER`: route to approval handler, which defaults to rejection

This means the user-visible behavior may still look like a refusal in many cases, but the refusal now comes from the approval subsystem rather than from permission transport collapse.

That distinction is the whole point of v0.2.4.

### Metadata Handling

v0.2.4 should preserve metadata across the transition:

- `PermissionDecision.metadata` should be copied into `ApprovalRequest.metadata`
- approval decisions may add their own metadata
- rejected approval results should include enough metadata in the final `ToolResult` for future tracing and testing

At minimum, the final failure metadata should preserve:

- `tool_name`
- `permission_mode`
- `risk_tags` when present
- approval-side reason or marker showing that approval handling was reached

### Hooks And Trace Behavior

No new hook events are required in v0.2.4.

Existing behavior should remain:

- `tool.started` still emits before permission and approval resolution
- `tool.completed` still emits
- rejected approval should surface as `tool.completed(ok=False)`

This increment should not add approval-specific console rendering yet.

This does preserve a temporary semantic mismatch: a tool can emit `tool.started` and later `tool.completed(ok=False)` even when the underlying tool implementation never actually ran because approval was rejected. That mismatch already exists in the current permission-denial path and is acceptable in v0.2.4. A future increment may add `approval.requested` / `approval.resolved` events to make the sequence more precise.

## CLI Integration

No new CLI flag is needed in v0.2.4.

`cli.py` should continue to construct runtime through `AgentRuntime.create(...)`, which will now also install the default approval handler.

This means approval support becomes available through runtime composition without exposing any new user-facing option yet.

## Compatibility

This increment intentionally changes internal execution shape more than user-facing behavior.

Compatibility expectations:

- `ALLOW` remains unchanged
- `DENY` remains unchanged
- `ASK_USER` still results in non-execution by default

The externally visible difference is that `ASK_USER` will now travel through a real approval subsystem before being rejected by the default handler.

That behavior is acceptable because v0.2.4 is explicitly a runtime skeleton increment.

## Testing Strategy

Testing should cover the new approval module, agent integration, and runtime composition.

### Approval Unit Tests

Add tests for:

- `ApprovalRequest` default metadata behavior
- `ApprovalDecision` default metadata behavior
- `DenyingApprovalHandler` always returning `REJECT`
- default rejection message and reason

### Agent Integration Tests

Add tests for:

- `ASK_USER` decisions call the approval handler
- rejected approval requests do not execute the tool
- approval rejection message is surfaced through the final `ToolResult`
- a custom approving handler allows the tool to execute
- existing `ASK_USER`-path tests should continue to match the permission-layer user-facing message, such as `"requires user approval"`, rather than needing a new approval-specific default rejection string
- rejected approval results should not add a noisy empty `approval` metadata object when the approval decision contributes no extra metadata

One important integration assertion is:

- `ToolRegistry.execute()` must not run when approval is rejected

The existing `FailingExecuteRegistry` pattern in `tests/test_agent.py` is the right mechanism to prove that rejected approval requests do not fall through to registry execution.

### Runtime And CLI Tests

Add tests for:

- `AgentRuntime.create()` installing a default approval handler
- direct `AgentRuntime(...)` construction receiving a conservative default handler through the dataclass field default
- explicitly injected approval handlers being preserved
- CLI-built runtimes receiving the default approval handler through composition

### Regression Tests

Existing permission, runtime, agent, and CLI tests should remain green after the new approval skeleton lands.

## Acceptance Criteria

v0.2.4 is complete when:

- `miniharness/approvals.py` exists with request, action, decision, and handler abstractions
- `AgentRuntime` composes an approval handler
- `Agent._execute_tool_call()` routes `ASK_USER` through the approval subsystem
- the default approval handler rejects conservatively
- approval rejection prevents tool execution
- a custom approving handler can allow execution in tests
- automated tests cover approval unit behavior, runtime composition, and agent integration

## Non-Goals

The following are explicitly deferred:

- interactive approval prompts
- CLI approval mode flags
- approval persistence
- approval tracing UI
- approval support for all tools
- permission taxonomy redesign beyond what is needed to pass approval context through

## Future Evolution

If v0.2.4 works well, likely next steps are:

1. Add a real CLI approval prompt handler.
2. Add configurable approval policies such as prompt, auto-approve, or auto-deny.
3. Expand approval-aware permission handling to file-write and delete operations.
4. Add approval-specific trace payloads or hook events.
5. Revisit whether approval requests should evolve into a richer shared request model with tool risk classification attached directly.

The critical constraint is that v0.2.4 should install the approval subsystem into runtime without prematurely locking MiniHarness into one user interaction model.
