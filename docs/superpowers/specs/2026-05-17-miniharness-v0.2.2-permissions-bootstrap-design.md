# MiniHarness v0.2.2 Permissions Bootstrap Design

Date: 2026-05-17

## Goal

MiniHarness v0.2.2 introduces the first real permission-enforcement path built on top of the v0.2.1 runtime scaffold.

The goal of this increment is not to deliver a complete permissions framework. The goal is to make `RuntimePolicy` participate in real execution decisions, establish one unified permission-check entry point, and prove the pattern with one minimal but real restriction.

## Scope

v0.2.2 should:

- Introduce a small permission-check module for tool-call authorization.
- Add one real policy field to `RuntimePolicy`: `shell_enabled: bool = True`.
- Enforce that policy at the agent tool-execution boundary.
- Deny `run_shell` when `shell_enabled` is `False`.
- Preserve existing behavior by default when `shell_enabled` is left at `True`.

v0.2.2 should not:

- Add approval dialogs or interactive confirmations.
- Add command-level shell allowlists or denylists.
- Add filesystem write-root policy in this version.
- Add a general role-based or user-based permission model.
- Expand prompt text to simulate a full permissions system.

## Why This Increment Now

MiniHarness v0.2.1 introduced `RuntimePolicy`, `AgentCapabilities`, and `AgentRuntime`, but `RuntimePolicy` is still only descriptive. It does not yet affect actual tool execution.

The next useful step is to make policy real without overcommitting to a large security framework. That means:

- one policy field
- one enforcement point
- one real restriction

This is enough to validate the design direction and reduce the risk of future permission work turning into scattered tool-specific checks.

## Recommended Approach

Add a new module:

- `miniharness/permissions.py`

This module should interpret policy for a single tool call and return a small structured decision.

No package export change is required for this increment. `miniharness/__init__.py` does not need to expose the new permission helper types in v0.2.2.

The unified check should be called from `Agent._execute_tool_call()` after tool-argument parsing succeeds but before the tool executes.

This is preferable to placing policy logic directly inside `ToolRegistry` or inside individual tools because:

- `Agent` already owns the execution boundary for tool calls.
- the permission decision applies uniformly to all tools
- existing tool implementations remain unchanged
- hooks and error reporting automatically reuse the existing failure path

## Design Overview

### RuntimePolicy Extension

Extend `RuntimePolicy` with:

- `shell_enabled: bool = True`

Suggested shape:

```python
@dataclass(frozen=True)
class RuntimePolicy:
    allow_outside_cwd: bool = False
    shell_timeout: int = 30
    shell_enabled: bool = True
```

The default stays `True` so current CLI behavior remains unchanged.

Only the fields that existing tools already consume should continue flowing into `ToolContext` in v0.2.2. `shell_enabled` should not be copied into `ToolContext`, because permission enforcement for this rule happens at the agent boundary rather than inside tools.

## Permission Decision Model

`permissions.py` should define a small result type:

```python
@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    error: str | None = None
```

This keeps the module explicit and testable. It avoids overloading `ToolResult` for policy interpretation while staying simple enough for a bootstrap version.

### Permission Check Function

The core function should be:

```python
def check_tool_permission(
    policy: RuntimePolicy,
    tool_name: str,
    args: dict[str, Any],
) -> PermissionDecision:
    ...
```

In v0.2.2 it should implement exactly one real rule:

- If `tool_name == "run_shell"` and `policy.shell_enabled is False`
- Return:

```python
PermissionDecision(
    allowed=False,
    error=f"tool {tool_name} is disabled by runtime policy",
)
```

Otherwise:

```python
PermissionDecision(allowed=True)
```

The `args` parameter is included now even though the first rule does not need it. That gives future versions a stable function signature for argument-sensitive rules without immediately adding complexity.

## Agent Integration

Permission checks should happen in `Agent._execute_tool_call()`.

The order should be:

1. Handle tool JSON parse errors first
2. Run `check_tool_permission(...)`
3. If denied, return `ToolResult(False, "", decision.error)`
4. If allowed, continue into `self.tools.execute(...)`

This ordering is intentional. Permission checks happen before schema validation inside `ToolRegistry.execute()`, so a disabled tool is rejected as a policy decision even if its arguments would also fail validation.

Suggested shape:

```python
from .permissions import check_tool_permission


def _execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
    if tool_call.parse_error:
        return ToolResult(False, "", f"invalid tool arguments: {tool_call.parse_error}")

    decision = check_tool_permission(
        policy=self.runtime.policy,
        tool_name=tool_call.name,
        args=tool_call.arguments,
    )
    if not decision.allowed:
        return ToolResult(False, "", decision.error)

    try:
        return self.tools.execute(tool_call.name, tool_call.arguments, self.context)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        return ToolResult(False, "", str(exc))
```

This placement is important:

- it enforces policy before tool execution
- it preserves the existing `ToolResult` failure path
- it lets hooks continue to report `tool.started` and `tool.completed(ok=False)` without schema changes

If `check_tool_permission()` itself raises because of a programming bug, that exception should propagate as an agent-level failure rather than being downgraded into a tool-level `ToolResult`. That is the desired fail-fast behavior for permission-system defects.

In the current agent loop, `tool.started` is emitted before `_execute_tool_call()` runs. That means denied tools still produce a started event even though the tool body never executes. This is intentional in v0.2.2 because the trace describes attempted tool execution, not only successful entry into tool internals.

## Hooks and Trace Behavior

No new hook event type is needed in v0.2.2.

When a tool is denied by policy:

- `tool.started` still emits
- `tool.completed` still emits
- `tool.completed.payload["ok"]` is `False`
- `tool.completed.payload["error"]` contains the permission denial message

This keeps trace behavior stable and avoids introducing permission-specific event vocabulary too early.

## CLI Integration

v0.2.2 should not add a new user-facing CLI flag yet.

That means:

- `Config` does not need a new field in this version
- `_build_agent()` can continue constructing `RuntimePolicy()` with the default `shell_enabled=True`
- tests and direct code construction can still exercise `shell_enabled=False` through explicit runtime injection

This keeps the feature bootstrap internal-first:

- policy field exists
- enforcement exists
- default UX remains unchanged

CLI configuration for disabling shell can be introduced in a later version once the enforcement path is proven stable.

Important limitation for v0.2.2:

- `shell_enabled=False` requires `Agent(runtime=AgentRuntime.create(...))`
- the individual-parameter `Agent.__init__()` path does not accept a direct `shell_enabled` argument in this version
- that legacy path therefore always uses the default `RuntimePolicy(shell_enabled=True)` unless a runtime is injected

## Compatibility

This increment should preserve the existing behavior of all current commands and tests under default configuration.

That means:

- `run_shell` remains available unless a runtime explicitly disables it
- REPL behavior stays unchanged
- CLI flags stay unchanged
- tool registry behavior stays unchanged

The new restriction is opt-in through runtime construction only in v0.2.2.

## Testing Strategy

Testing should cover both the pure decision logic and the integrated agent behavior.

### Permission Unit Tests

Add tests that verify:

- `test_runtime_policy_defaults()` also asserts `policy.shell_enabled is True`
- `check_tool_permission()` allows `run_shell` when `shell_enabled=True`
- `check_tool_permission()` denies `run_shell` when `shell_enabled=False`
- non-shell tools are allowed even when `shell_enabled=False`

### Agent Integration Tests

Add tests that verify:

- when runtime policy disables shell, a `run_shell` tool call returns a failed `ToolResult`
- the failure message reaches the model-facing tool message content
- no actual shell execution happens in the denied path
- hooks still emit `tool.started` and `tool.completed(ok=False)`

The existing `RecordingHook` pattern in `tests/test_agent.py` is sufficient for hook assertions in this version. No new hook fixture should be necessary.

### Regression Tests

Existing shell tool tests and CLI tests should continue to pass unchanged under default configuration.

A full test run should remain green after this change.

## Acceptance Criteria

v0.2.2 is complete when:

- package version metadata is updated from `0.2.1` to `0.2.2`
- `RuntimePolicy` includes `shell_enabled`
- `permissions.py` exists with a unified tool-permission check
- `Agent._execute_tool_call()` enforces permission decisions before tool execution
- `run_shell` is denied when `shell_enabled=False`
- hooks and trace continue to report denied tools through existing failure semantics
- default configuration preserves current behavior
- automated tests cover permission decisions, denied shell execution, and default-path regressions

## Non-Goals

The following are explicitly deferred:

- `--no-shell` or equivalent CLI flag
- interactive approvals
- per-command shell filtering
- filesystem permissions expansion
- prompt-based permission narration
- capability changes beyond what is needed for the shell rule

## Future Evolution

If the bootstrap works well, likely next steps are:

1. Add CLI-configurable policy toggles such as `--no-shell`.
2. Expand permission checks to filesystem policy.
3. Introduce richer policy outcomes such as "requires approval".
4. Use `ToolResult.metadata` to distinguish permission denials from other classes of tool failure when that distinction becomes valuable.
5. Let prompt or UI surfaces reflect enforced policy after real controls exist.

The critical constraint is that v0.2.2 should prove the permission-enforcement path with the smallest real rule, not jump directly into a full security framework.
