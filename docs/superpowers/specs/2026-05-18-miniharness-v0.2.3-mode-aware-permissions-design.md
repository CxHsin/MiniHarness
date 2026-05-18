# MiniHarness v0.2.3 Mode-Aware Permissions Design

Date: 2026-05-18

## Goal

MiniHarness v0.2.3 should evolve the v0.2.2 permission bootstrap into a real mode-aware decision pipeline.

The goal of this increment is not to deliver the full OpenHarness-style approval system in one step. The goal is to establish a stable permission decision model with:

- explicit deny rules
- mode-aware default behavior
- an approval-ready fallback state when policy cannot decide automatically

This increment should prove that permission mode is not the whole policy. Some operations must be rejected regardless of mode, while other operations should vary by `default`, `plan`, or `auto`.

## Scope

v0.2.3 should:

- introduce explicit permission modes in `RuntimePolicy`
- replace the v0.2.2 boolean permission outcome with a richer permission decision model
- make permission checks run as a fixed pipeline:
  1. deny rules
  2. mode check
  3. approval-required fallback
- introduce a small shared risk model that both file operations and shell-derived operations can use
- add the first mode-aware behavior for `run_shell`
- make `plan` mode conservative without making it absolute read-only

In practical enforcement scope, v0.2.3 should apply the new mode-aware permission pipeline only to `run_shell`. Other tools should continue using their current behavior unless they are already covered by existing tool-level checks.

v0.2.3 should not:

- implement a full interactive approval dialog yet
- add a full path-rule DSL or config file format in this version
- solve every shell classification problem
- redesign every tool around risk tagging in one pass
- expand prompt text to simulate permission features that do not exist yet

## Why This Increment Now

v0.2.2 proved one real enforcement path, but it still has two major limitations:

1. the result model is only `allow` or `deny`
2. policy still behaves like a small feature flag rather than a structured harness permission system

The next useful step is to separate:

- absolute rejection
- mode-based behavior
- unresolved actions that need user approval

That creates the correct shape for future approval UX without forcing the full interaction model into v0.2.3.

## Recommended Approach

Keep permission evaluation centralized in `miniharness/permissions.py`.

The permission system should continue to evaluate one tool call at a time, but its internal model should become more expressive. In particular:

- `RuntimePolicy` should declare the active permission mode
- permission evaluation should return an explicit action, not just a boolean
- permission evaluation should classify a tool call into a small set of risk tags before making a decision

No package export change is required for this increment. `miniharness/__init__.py` does not need to expose new permission helper types in v0.2.3.

This is preferable to scattering mode checks across tools because:

- `Agent` remains the single execution boundary
- mode semantics stay consistent across tools
- future approval handling can hook into one decision interface
- deny rules remain mode-independent by construction

v0.2.3 should reuse the existing sensitive-path knowledge already present in `miniharness.tools.base`, specifically `is_sensitive_path()` and its related constants, rather than redefining a second source of truth inside `permissions.py`.

## Design Overview

### RuntimePolicy Extension

Extend `RuntimePolicy` with a permission mode field:

```python
from enum import StrEnum


class PermissionMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"
    AUTO = "auto"
```

Suggested `RuntimePolicy` shape:

```python
@dataclass(frozen=True)
class RuntimePolicy:
    allow_outside_cwd: bool = False
    shell_timeout: int = 30
    shell_enabled: bool = True
    permission_mode: PermissionMode = PermissionMode.DEFAULT
```

`ToolContext` should continue receiving only the fields that tools already consume directly. `permission_mode` should not be copied into `ToolContext` in v0.2.3 because policy evaluation still belongs at the agent boundary.

### Permission Action Model

Replace the v0.2.2 boolean result with a three-state decision:

```python
class PermissionAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"
```

Suggested result type:

```python
@dataclass(frozen=True)
class PermissionDecision:
    action: PermissionAction
    reason: str
    source: str
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Field intent:

- `action`: the final decision
- `reason`: stable machine-readable explanation key
- `source`: which decision layer produced the result
- `message`: human-facing explanation text
- `metadata`: extra structured details for future tracing and approvals

Suggested `metadata` contents in v0.2.3:

- `tool_name`: the tool being checked
- `risk_tags`: the matched internal risk tags for this decision
- `permission_mode`: the active mode at decision time
- `rule`: the matched deny rule or mode rule identifier when applicable

Suggested `source` values in v0.2.3:

- `deny_rule`
- `mode`
- `fallback`

`source` should identify the pipeline stage that produced the result, not the action itself. In particular, `ASK_USER` does not imply `source="fallback"` by definition. A future version may return `ASK_USER` from a mode-stage decision while still using `source="mode"`.

### Minimal Shared Risk Model

v0.2.3 should introduce a small internal risk vocabulary. It does not need to be a fully generic framework yet, but shell-derived and future file-derived decisions should speak the same language.

Suggested first-pass risk tags:

- `read_only`
- `write_file`
- `delete_file`
- `delete_dir`
- `shell_exec`
- `sensitive_target`

This model should stay internal to `permissions.py` in v0.2.3.

The point is not to perfectly classify everything. The point is to stop making permission decisions purely from tool name alone.

Of these tags, only the subset needed for `run_shell` enforcement must be exercised in v0.2.3. The broader tag vocabulary is reserved for future use so the internal language does not need to be reinvented in later increments.

This increment does not pay down the existing `RuntimePolicy` -> `ToolContext` duplication debt beyond what already exists for `allow_outside_cwd` and `shell_timeout`. Each new policy field should continue to require an explicit decision about whether it belongs only at the agent boundary or must also flow into tools.

### Permission Pipeline

The permission pipeline should be fixed in this order:

1. explicit deny rules
2. mode check
3. unresolved fallback to approval-required

This ordering is the core design decision of v0.2.3.

It means:

- deny rules cannot be overridden by `auto`
- `plan` mode is conservative, but not the only source of rejection
- `ask_user` is a first-class outcome, not an exceptional error path

### Deny Rules

The first deny rules should be intentionally small and absolute.

v0.2.3 should include at least:

- `run_shell` remains denied when `shell_enabled=False`
- shell commands that clearly target sensitive paths should be denied regardless of mode
- shell commands that clearly match obviously destructive root-style deletion patterns should be denied regardless of mode
- the existing interactive-command guard in `miniharness.tools.shell` may remain as a second line of defense in v0.2.3; this increment does not require migrating all such checks into the permission pipeline

Within deny rules, `shell_enabled=False` is a global tool-level rule and should be checked before any command-content rule. It does not inspect arguments; it disables shell execution categorically.

This increment does not need a full shell parser. Conservative string-pattern detection is acceptable for the first deny rules as long as the rules are explicit and well tested.

v0.2.3 command classification should be intentionally limited:

- command-name and command-prefix matching are acceptable
- limited path-token inspection is acceptable for obviously sensitive targets
- full argument parsing is out of scope

This means edge cases such as `cat /etc/shadow` may not be classified perfectly in v0.2.3 unless they are caught by the small sensitive-target checks. That limitation should be documented in implementation notes and future work, not hidden.

Examples of the intended class of deny rule:

- deleting `/`, `~/.ssh`, or similar sensitive targets
- shell operations clearly aimed at secrets/config roots

The exact first patterns should be kept minimal and explicit in the spec implementation, not expanded into a broad heuristic security engine yet.

### Mode Semantics

The first version of mode behavior should focus on `run_shell`.

#### `default`

`default` should behave like a balanced mode:

- safe read-oriented shell commands may be allowed
- ambiguous write or delete shell operations should fall through to `ask_user`
- absolute deny rules still win first

In v0.2.3, `default` does not need a broad unique allow-set beyond the safe read-oriented commands. Its practical distinction from `plan` may remain narrow in this increment, with `plan` reserved as the stricter semantic mode for future expansion. The acceptance criteria should not require a large behavioral gap between `default` and `plan` yet.

#### `plan`

`plan` should be conservative, but not absolute read-only.

That means:

- clearly safe read-oriented shell commands may be allowed
- clearly dangerous operations are denied by deny rules
- many modifying commands should become `ask_user`
- small, explainable cleanup behavior can be allowed later, but v0.2.3 does not need to solve every safe-delete case yet

The important design constraint is that `plan` should not collapse into a trivial "all writes deny" model, because some controlled deletion or cleanup flows are valid planning-time operations.

#### `auto`

`auto` should be the least conservative mode:

- safe and normal shell commands may be allowed directly
- deny rules still apply first
- anything not denied and not obviously unsafe can be allowed without user confirmation in this version

`auto` is not equivalent to "ignore permission policy." It is still bounded by explicit deny rules.

### Safe Shell Commands In v0.2.3

v0.2.3 should define a narrow first-pass notion of shell commands that are safe enough to auto-allow in `default` and `plan`.

Examples of the intended class:

- directory listing
- file viewing
- text search
- read-only git inspection commands

Examples:

- `dir`
- `ls`
- `pwd`
- `type README.md`
- `cat README.md`
- `rg pattern`
- `git status`
- `git diff --stat`

This should be implemented conservatively. It is better in v0.2.3 to classify too few commands as safe than too many.

These examples are examples of command-family classification, not a guarantee of deep argument-aware safety analysis. For example, `cat` may be considered a read-oriented command family, while argument-level sensitive-target checks remain intentionally narrow in this increment.

### Approval-Required Fallback

When deny rules do not trigger and mode cannot confidently allow the action, permission evaluation should return:

```python
PermissionDecision(
    action=PermissionAction.ASK_USER,
    reason="approval_required",
    source="fallback",
    message="tool run_shell requires user approval in the current permission mode",
)
```

v0.2.3 does not need to implement the interactive approval dialog itself.

For this increment, `ask_user` should be surfaced through the existing failure path as a structured non-executed tool result. That keeps the integration small while preserving the correct future shape.

This means `ASK_USER` is approval-ready rather than approval-complete in v0.2.3. At the agent integration layer it is still represented as a non-executed failure result, even though it is semantically distinct from a hard deny. Future approval UX should intercept `ASK_USER` before it collapses into the generic failure experience.

## Agent Integration

Permission checks should still happen in `Agent._execute_tool_call()` after tool JSON parsing and before tool execution.

The updated order should be:

1. handle tool JSON parse errors
2. run permission evaluation
3. if `ALLOW`, continue into `self.tools.execute(...)`
4. if `DENY`, return a failed `ToolResult`
5. if `ASK_USER`, return a failed `ToolResult` that clearly indicates approval is required and execution did not happen

Suggested shape:

```python
from .permissions import check_tool_permission, PermissionAction


decision = check_tool_permission(
    policy=self.runtime.policy,
    tool_name=tool_call.name,
    args=tool_call.arguments,
)

if decision.action is PermissionAction.DENY:
    return ToolResult(False, "", decision.message or decision.reason, decision.metadata)

if decision.action is PermissionAction.ASK_USER:
    return ToolResult(False, "", decision.message or decision.reason, decision.metadata)
```

The key point is that both denied and approval-required outcomes must prevent tool execution.

In v0.2.3, `DENY` and `ASK_USER` intentionally share the same immediate `ToolResult` transport path even though their internal meanings differ. That is a temporary integration compromise until approval UX exists.

As in v0.2.2, permission evaluation happens before schema validation inside `ToolRegistry.execute()`. That is still intentional. A tool that is not permitted in the current policy should not proceed merely to discover that its arguments were invalid too.

If permission evaluation itself raises because of a programming error, that exception should continue to propagate as an agent-level failure.

## Hooks and Trace Behavior

No new hook event type is required in v0.2.3.

When a tool is denied or requires approval:

- `tool.started` still emits
- `tool.completed` still emits
- `tool.completed.payload["ok"]` is `False`
- `tool.completed.payload["error"]` contains the denial or approval-required message

This keeps the event model stable while the permission model becomes richer underneath.

Future versions may add permission-specific trace fields, but that is not required in v0.2.3.

## CLI Integration

v0.2.3 should make permission mode user-visible.

Suggested CLI flag:

- `--permission-mode {default,plan,auto}`

Behavior:

- default value is `default`
- `Config` should gain a `permission_mode` field so the path is explicit:
  `CLI arg -> parse args -> load_config() -> Config -> _build_agent() -> RuntimePolicy`
- `_build_agent()` should translate the CLI value into `RuntimePolicy.permission_mode`
- existing CLI behavior should remain effectively unchanged when the user does not specify the flag

This increment should not add a full approval prompt UX yet. If a decision becomes `ask_user`, the current system may return an explanatory tool failure while the approval workflow remains a future increment.

Required config flow in v0.2.3:

- `build_parser()` adds `--permission-mode`
- `Config` gains `permission_mode`
- `load_config()` maps parsed args into `Config.permission_mode`
- `_build_agent()` maps `Config.permission_mode` into `RuntimePolicy.permission_mode`

## Compatibility

This increment should preserve current behavior when:

- the mode remains `default`
- no deny rule is triggered
- the command is within the small set of safe read-style shell commands already classified as auto-allow

This statement is intentionally narrow. In v0.2.3, many shell commands that were previously auto-allowed in v0.2.2 will now become approval-required in `default` mode unless they fall inside the small safe read-style command set.

New behavior should be introduced only where the mode-aware pipeline intentionally changes decision-making.

## Testing Strategy

Testing should cover unit-level decision logic, mode semantics, deny-rule priority, and integrated agent behavior.

### Permission Unit Tests

Add tests that verify:

- `RuntimePolicy` defaults to `permission_mode=PermissionMode.DEFAULT`
- deny rules beat `PermissionMode.AUTO`
- `shell_enabled=False` still denies shell before mode logic
- unknown tool names are not special-cased by permission evaluation and still fall through to the existing registry failure behavior unless a deny rule explicitly matches first
- ambiguous modifying shell commands become `ask_user` in `default`
- safe read-only shell commands are allowed in `plan`
- ambiguous modifying shell commands become `ask_user` in `plan`
- shell commands denied by command-content rules are still denied when `shell_enabled=True`
- `auto` allows commands that `plan` would route to `ask_user`, as long as deny rules do not trigger

### Agent Integration Tests

Add tests that verify:

- denied shell commands do not execute and surface the deny message
- approval-required shell commands do not execute and surface the approval-required message
- `tool.started` and `tool.completed(ok=False)` still fire for both denied and approval-required decisions
- safe shell commands allowed by `plan` still execute successfully

### Tool Coverage Note

v0.2.3 should explicitly document which tools are covered by the new pipeline:

- `run_shell`: full deny -> mode -> ask pipeline
- file tools: unchanged in this increment except for their existing path-boundary and tool-local checks
- other tools: unchanged unless already governed by existing logic

### CLI Tests

Add tests that verify:

- `--permission-mode` is accepted by the parser
- `_build_agent()` maps CLI mode to `RuntimePolicy.permission_mode`
- the default mode remains `default`

### Regression Tests

Existing non-permission tests should remain green.

A full test run should remain green after this change.

## Acceptance Criteria

v0.2.3 is complete when:

- `RuntimePolicy` includes an explicit permission mode
- `PermissionDecision` supports `allow`, `deny`, and `ask_user`
- permission evaluation follows the fixed order: deny rules, mode check, fallback
- explicit deny rules cannot be overridden by `auto`
- `plan` mode allows a narrow set of safe read-oriented shell commands
- `default` mode routes ambiguous modifying shell commands to approval-required
- unresolved shell actions in `plan` surface as approval-required rather than auto-executing
- `--permission-mode` is exposed through the CLI
- automated tests cover deny priority, mode behavior, approval-required fallback, CLI mapping, and regressions

## Non-Goals

The following are explicitly deferred:

- a full interactive approval dialog
- persistent user approval state
- a complete shell parser
- a full path-rule configuration file
- a complete risk taxonomy for every current and future tool
- prompt narration of permission state beyond what the real system enforces

## Future Evolution

If v0.2.3 works well, likely next steps are:

1. Add an interactive approval UX for `ask_user`.
2. Expand deny rules into explicit path and command rule sets.
3. Introduce more shared risk classification for file-write and delete operations outside shell.
4. Expose richer permission-trace metadata to hooks or UI surfaces.
5. Move from a small hard-coded safe-command set to a more structured command classification model.
6. Revisit whether some future tools need access to permission mode through `ToolContext`, rather than keeping all mode semantics exclusively at the agent boundary.

The critical constraint is that v0.2.3 should establish the correct permission-system shape without attempting to finish the entire approval product in one release.
