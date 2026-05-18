# MiniHarness v0.2.3 Mode-Aware Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade MiniHarness permissions from a boolean shell toggle into a mode-aware pipeline with explicit deny rules, `default/plan/auto` behavior, and approval-ready `ask_user` outcomes for `run_shell`.

**Architecture:** Extend `RuntimePolicy` and `Config` with a permission mode, replace boolean permission decisions with explicit actions in `miniharness/permissions.py`, and keep enforcement centralized at `Agent._execute_tool_call()`. v0.2.3 intentionally limits the new pipeline to `run_shell`, while preserving existing behavior for other tools and reusing `miniharness.tools.base.is_sensitive_path()` for sensitive-target denial.

**Tech Stack:** Python 3, `dataclasses`, `enum.StrEnum`, `pytest`, existing MiniHarness runtime/CLI/tool abstractions

---

### Task 1: Introduce Permission Modes And Decision Types

**Files:**
- Modify: `miniharness/policy.py`
- Modify: `miniharness/permissions.py`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Replace the current runtime permission tests with mode-aware failing tests**

Update `tests/test_runtime.py` imports and tests:

```python
from miniharness.permissions import (
    PermissionAction,
    PermissionDecision,
    check_tool_permission,
)
from miniharness.policy import PermissionMode, RuntimePolicy
```

```python
def test_runtime_policy_defaults():
    policy = RuntimePolicy()

    assert policy.allow_outside_cwd is False
    assert policy.shell_timeout == 30
    assert policy.shell_enabled is True
    assert policy.permission_mode is PermissionMode.DEFAULT
```

```python
def test_check_tool_permission_denies_shell_when_disabled_before_mode_logic():
    decision = check_tool_permission(
        RuntimePolicy(shell_enabled=False, permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": "echo hi"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.DENY,
        reason="shell_disabled",
        source="deny_rule",
        message="tool run_shell is disabled by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "risk_tags": ["shell_exec"],
            "permission_mode": "auto",
            "rule": "shell_disabled",
        },
    )
```

```python
def test_check_tool_permission_unknown_tool_falls_through_as_allow():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        "unknown_tool",
        {},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.ALLOW,
        reason="non_shell_tool",
        source="mode",
        message="tool unknown_tool is not governed by v0.2.3 mode-aware permission checks",
        metadata={
            "tool_name": "unknown_tool",
            "risk_tags": [],
            "permission_mode": "default",
            "rule": "non_shell_passthrough",
        },
    )
```

- [ ] **Step 2: Run the focused runtime suite to verify it fails**

Run:

```bash
python -m pytest tests/test_runtime.py -v
```

Expected:

```text
FAILED tests/test_runtime.py::test_runtime_policy_defaults
FAILED tests/test_runtime.py::test_check_tool_permission_denies_shell_when_disabled_before_mode_logic
FAILED tests/test_runtime.py::test_check_tool_permission_unknown_tool_falls_through_as_allow
```

- [ ] **Step 3: Add `PermissionMode` and extend `RuntimePolicy`**

Update `miniharness/policy.py` to:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PermissionMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"
    AUTO = "auto"


@dataclass(frozen=True)
class RuntimePolicy:
    allow_outside_cwd: bool = False
    shell_timeout: int = 30
    shell_enabled: bool = True
    permission_mode: PermissionMode = PermissionMode.DEFAULT
```

- [ ] **Step 4: Replace the boolean permission model with explicit actions**

Update `miniharness/permissions.py` to:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .policy import PermissionMode, RuntimePolicy


class PermissionAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"


@dataclass(frozen=True)
class PermissionDecision:
    action: PermissionAction
    reason: str
    source: str
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _decision(
    *,
    action: PermissionAction,
    reason: str,
    source: str,
    tool_name: str,
    permission_mode: PermissionMode,
    risk_tags: list[str],
    rule: str,
    message: str,
) -> PermissionDecision:
    return PermissionDecision(
        action=action,
        reason=reason,
        source=source,
        message=message,
        metadata={
            "tool_name": tool_name,
            "risk_tags": risk_tags,
            "permission_mode": permission_mode.value,
            "rule": rule,
        },
    )


def check_tool_permission(
    policy: RuntimePolicy,
    tool_name: str,
    args: dict[str, Any],
) -> PermissionDecision:
    del args
    if tool_name != "run_shell":
        return _decision(
            action=PermissionAction.ALLOW,
            reason="non_shell_tool",
            source="mode",
            tool_name=tool_name,
            permission_mode=policy.permission_mode,
            risk_tags=[],
            rule="non_shell_passthrough",
            message=f"tool {tool_name} is not governed by v0.2.3 mode-aware permission checks",
        )

    risk_tags = ["shell_exec"]
    if policy.shell_enabled is False:
        return _decision(
            action=PermissionAction.DENY,
            reason="shell_disabled",
            source="deny_rule",
            tool_name=tool_name,
            permission_mode=policy.permission_mode,
            risk_tags=risk_tags,
            rule="shell_disabled",
            message=f"tool {tool_name} is disabled by runtime policy",
        )

    return _decision(
        action=PermissionAction.ALLOW,
        reason="mode_allows_shell",
        source="mode",
        tool_name=tool_name,
        permission_mode=policy.permission_mode,
        risk_tags=risk_tags,
        rule="shell_enabled_passthrough",
        message=f"tool {tool_name} is allowed by runtime policy",
    )
```

- [ ] **Step 5: Re-run the runtime suite and make sure it passes**

Run:

```bash
python -m pytest tests/test_runtime.py -v
```

Expected:

```text
PASSED tests/test_runtime.py::test_runtime_policy_defaults
PASSED tests/test_runtime.py::test_check_tool_permission_denies_shell_when_disabled_before_mode_logic
PASSED tests/test_runtime.py::test_check_tool_permission_unknown_tool_falls_through_as_allow
```

- [ ] **Step 6: Commit the permission type-model changes**

Run:

```bash
git add miniharness/policy.py miniharness/permissions.py tests/test_runtime.py
git commit -m "feat: add mode-aware permission decisions"
```

### Task 2: Add Deny Rules And Mode-Aware Shell Decisions

**Files:**
- Modify: `miniharness/permissions.py`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Add focused failing tests for deny rules, default, plan, and auto**

Append to `tests/test_runtime.py`:

```python
def test_check_tool_permission_denies_sensitive_shell_target_even_in_auto():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": "cat ~/.ssh/id_rsa"},
    )

    assert decision.action is PermissionAction.DENY
    assert decision.reason == "sensitive_target"
    assert decision.source == "deny_rule"
    assert decision.metadata["rule"] == "sensitive_target"
```

```python
def test_check_tool_permission_default_mode_routes_ambiguous_shell_to_ask_user():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        "run_shell",
        {"command": "echo hello > out.txt"},
    )

    assert decision.action is PermissionAction.ASK_USER
    assert decision.reason == "approval_required"
    assert decision.source == "fallback"
    assert decision.metadata["permission_mode"] == "default"
```

```python
def test_check_tool_permission_plan_mode_allows_safe_read_shell():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.PLAN),
        "run_shell",
        {"command": "git status"},
    )

    assert decision.action is PermissionAction.ALLOW
    assert decision.reason == "safe_read_command"
    assert decision.source == "mode"
    assert decision.metadata["permission_mode"] == "plan"
```

```python
def test_check_tool_permission_plan_mode_routes_modifying_shell_to_ask_user():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.PLAN),
        "run_shell",
        {"command": "rm temp.txt"},
    )

    assert decision.action is PermissionAction.ASK_USER
    assert decision.reason == "approval_required"
    assert decision.source == "fallback"
```

```python
def test_check_tool_permission_auto_mode_allows_command_that_plan_would_ask_about():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": "rm temp.txt"},
    )

    assert decision.action is PermissionAction.ALLOW
    assert decision.reason == "auto_mode_allows_shell"
    assert decision.source == "mode"
```

- [ ] **Step 2: Run the new runtime tests to verify they fail**

Run:

```bash
python -m pytest tests/test_runtime.py -k "sensitive_shell_target or default_mode_routes or plan_mode_allows or plan_mode_routes or auto_mode_allows" -v
```

Expected:

```text
FAILED tests/test_runtime.py::test_check_tool_permission_denies_sensitive_shell_target_even_in_auto
FAILED tests/test_runtime.py::test_check_tool_permission_default_mode_routes_ambiguous_shell_to_ask_user
FAILED tests/test_runtime.py::test_check_tool_permission_plan_mode_allows_safe_read_shell
FAILED tests/test_runtime.py::test_check_tool_permission_plan_mode_routes_modifying_shell_to_ask_user
FAILED tests/test_runtime.py::test_check_tool_permission_auto_mode_allows_command_that_plan_would_ask_about
```

- [ ] **Step 3: Implement risk tags, deny rules, and mode-aware command classification**

Extend `miniharness/permissions.py` with helpers that:

- classify `run_shell` into risk tags
- detect safe read-style shell commands by narrow prefix matching
- detect sensitive targets by extracting simple path-like tokens and checking them with `is_sensitive_path()`
- detect obviously destructive root-style deletion commands

Use this implementation shape:

```python
from pathlib import Path

from .policy import PermissionMode, RuntimePolicy
from .tools.base import is_sensitive_path

SAFE_READ_PREFIXES = (
    "dir",
    "ls",
    "pwd",
    "type ",
    "cat ",
    "rg ",
    "git status",
    "git diff --stat",
)

DESTRUCTIVE_DELETE_PATTERNS = (
    "rm -rf /",
    "rm -rf ~",
    "del /f /s /q c:\\",
    "rmdir /s /q c:\\",
)


def _command_lower(command: str) -> str:
    return " ".join(command.strip().lower().split())


def _extract_risk_tags(command: str) -> list[str]:
    lowered = _command_lower(command)
    tags = ["shell_exec"]
    if any(lowered.startswith(prefix) for prefix in ("dir", "ls", "pwd", "type ", "cat ", "rg ", "git status", "git diff --stat")):
        tags.append("read_only")
    if "rm " in lowered or lowered.startswith("del ") or lowered.startswith("erase "):
        tags.append("delete_file")
    if "rmdir " in lowered or "rm -r" in lowered or "rm -rf" in lowered:
        tags.append("delete_dir")
    return tags


def _looks_like_safe_read_command(command: str) -> bool:
    lowered = _command_lower(command)
    return any(lowered == prefix or lowered.startswith(prefix) for prefix in SAFE_READ_PREFIXES)


def _targets_sensitive_path(command: str) -> bool:
    for raw_token in command.replace('"', " ").replace("'", " ").split():
        token = raw_token.strip()
        if not token or token.startswith("-"):
            continue
        expanded = Path(token).expanduser()
        try:
            if is_sensitive_path(expanded):
                return True
        except Exception:
            continue
    return False


def _matches_destructive_delete(command: str) -> bool:
    lowered = _command_lower(command)
    return any(pattern in lowered for pattern in DESTRUCTIVE_DELETE_PATTERNS)
```

Then update `check_tool_permission(...)` to:

- keep non-shell passthrough unchanged
- deny on `shell_enabled=False`
- deny on sensitive target
- deny on destructive delete patterns
- allow safe read commands in `default` and `plan`
- return `ASK_USER` for other shell commands in `default` and `plan`
- allow remaining shell commands in `auto`

- [ ] **Step 4: Re-run the focused runtime tests and make sure they pass**

Run:

```bash
python -m pytest tests/test_runtime.py -k "sensitive_shell_target or default_mode_routes or plan_mode_allows or plan_mode_routes or auto_mode_allows" -v
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Run the full runtime suite**

Run:

```bash
python -m pytest tests/test_runtime.py -v
```

Expected:

```text
all tests in tests/test_runtime.py pass
```

- [ ] **Step 6: Commit the shell decision pipeline**

Run:

```bash
git add miniharness/permissions.py tests/test_runtime.py
git commit -m "feat: add mode-aware shell permission rules"
```

### Task 3: Wire Agent, Config, And CLI To The New Permission Model

**Files:**
- Modify: `miniharness/agent.py`
- Modify: `miniharness/config.py`
- Modify: `miniharness/cli.py`
- Test: `tests/test_agent.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add failing agent integration tests for `ask_user` and safe shell allow**

Append to `tests/test_agent.py`:

```python
from miniharness.policy import PermissionMode, RuntimePolicy
from miniharness.tools.shell import RunShellTool
```

```python
def test_agent_routes_default_mode_ambiguous_shell_to_approval_required(tmp_path):
    recorder = RecordingHook()
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments={"command": "echo hello > out.txt"},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        capabilities=AgentCapabilities(),
        hooks=[recorder],
    )
    agent = Agent(model_client=model, tools=[RunShellTool()], cwd=tmp_path, runtime=runtime)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is False
    assert "requires user approval" in content["error"]
    assert content["metadata"]["permission_mode"] == "default"
    tool_completed = [event for event in recorder.events if event.type == "tool.completed"][0]
    assert tool_completed.payload["ok"] is False
```

```python
def test_agent_executes_safe_shell_command_in_plan_mode(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments={"command": "git status"},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(permission_mode=PermissionMode.PLAN),
        capabilities=AgentCapabilities(),
    )
    agent = Agent(model_client=model, tools=[RunShellTool()], cwd=tmp_path, runtime=runtime)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["metadata"]["returncode"] == 0 or content["ok"] is True
```

- [ ] **Step 2: Add failing CLI/config tests for `--permission-mode`**

Append to `tests/test_cli.py`:

```python
def test_parser_accepts_permission_mode():
    parser = build_parser()

    args = parser.parse_args(["--permission-mode", "plan", "summarize"])

    assert args.permission_mode == "plan"
```

```python
def test_runtime_mapping_includes_permission_mode(monkeypatch, tmp_path):
    captured_agent_kwargs = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured_agent_kwargs.update(kwargs)

        def run(self, task):
            return cli.AgentOutcome(output="done", error=None, exit_code=0)

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        cli, "OpenAIModelClient", lambda api_key, model, base_url=None: object()
    )
    monkeypatch.setattr(cli, "Agent", FakeAgent)

    cli.main(["--cwd", str(tmp_path), "--permission-mode", "plan", "summarize"])

    assert captured_agent_kwargs["runtime"].policy.permission_mode.value == "plan"
```

- [ ] **Step 3: Run targeted agent/CLI tests to verify they fail**

Run:

```bash
python -m pytest tests/test_agent.py -k "approval_required or safe_shell_command_in_plan_mode" tests/test_cli.py -k "permission_mode" -v
```

Expected:

```text
selected tests fail because permission modes are not yet wired through agent/config/cli
```

- [ ] **Step 4: Update `Agent` to transport `DENY` and `ASK_USER` through the new decision model**

Update imports in `miniharness/agent.py`:

```python
from .permissions import PermissionAction, check_tool_permission
```

Update `_execute_tool_call()` to:

```python
def _execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
    if tool_call.parse_error:
        return ToolResult(False, "", f"invalid tool arguments: {tool_call.parse_error}")

    decision = check_tool_permission(
        self.runtime.policy,
        tool_call.name,
        tool_call.arguments,
    )
    if decision.action is PermissionAction.DENY:
        return ToolResult(False, "", decision.message or decision.reason, decision.metadata)
    if decision.action is PermissionAction.ASK_USER:
        return ToolResult(False, "", decision.message or decision.reason, decision.metadata)

    try:
        return self.tools.execute(tool_call.name, tool_call.arguments, self.context)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        return ToolResult(False, "", str(exc))
```

- [ ] **Step 5: Thread permission mode through config and CLI**

Update `miniharness/config.py`:

```python
from .policy import PermissionMode
```

```python
@dataclass(frozen=True)
class Config:
    cwd: Path
    api_key: str | None
    model: str
    base_url: str | None = None
    max_steps: int = 8
    shell_timeout: int = 30
    max_tool_output_chars: int = 12000
    history_budget_chars: int = 120000
    max_no_progress_steps: int = 2
    log_level: str = "WARNING"
    allow_outside_cwd: bool = False
    trace: bool = False
    permission_mode: PermissionMode = PermissionMode.DEFAULT
```

```python
return Config(
    cwd=cwd,
    api_key=api_key,
    model=model,
    base_url=base_url,
    max_steps=args.max_steps,
    shell_timeout=args.shell_timeout,
    max_tool_output_chars=args.max_tool_output_chars,
    history_budget_chars=args.history_budget_chars,
    max_no_progress_steps=args.max_no_progress_steps,
    log_level=log_level,
    allow_outside_cwd=args.allow_outside_cwd,
    trace=getattr(args, "trace", False),
    permission_mode=PermissionMode(getattr(args, "permission_mode", "default")),
)
```

Update `miniharness/cli.py` parser and `_build_agent()`:

```python
parser.add_argument(
    "--permission-mode",
    choices=["default", "plan", "auto"],
    default="default",
    help="permission behavior for run_shell: balanced default, conservative plan, or permissive auto",
)
```

```python
policy=RuntimePolicy(
    allow_outside_cwd=config.allow_outside_cwd,
    shell_timeout=config.shell_timeout,
    permission_mode=config.permission_mode,
),
```

- [ ] **Step 6: Re-run targeted agent and CLI tests**

Run:

```bash
python -m pytest tests/test_agent.py -k "approval_required or safe_shell_command_in_plan_mode" tests/test_cli.py -k "permission_mode or runtime_mapping_includes_permission_mode" -v
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 7: Run the full agent and CLI suites**

Run:

```bash
python -m pytest tests/test_agent.py tests/test_cli.py -v
```

Expected:

```text
all tests in tests/test_agent.py and tests/test_cli.py pass
```

- [ ] **Step 8: Commit the agent/config/CLI integration**

Run:

```bash
git add miniharness/agent.py miniharness/config.py miniharness/cli.py tests/test_agent.py tests/test_cli.py
git commit -m "feat: wire permission modes through agent and cli"
```

### Task 4: Final Regression And Release Metadata

**Files:**
- Modify: `miniharness/__init__.py`
- Modify: `CHANGELOG.md`
- Optional verify only: `README.md`

- [ ] **Step 1: Add a changelog-ready release assertion**

Update `tests/test_cli.py::test_main_prints_version` to expect:

```python
assert "mh 0.2.3" in capsys.readouterr().out
```

- [ ] **Step 2: Run the version test to verify it fails**

Run:

```bash
python -m pytest tests/test_cli.py::test_main_prints_version -v
```

Expected:

```text
FAILED tests/test_cli.py::test_main_prints_version
```

- [ ] **Step 3: Bump version and add changelog notes**

Update `miniharness/__init__.py` to:

```python
__version__ = "0.2.3"
```

Add a `0.2.3` entry to `CHANGELOG.md` summarizing:

```markdown
## 0.2.3

- Added `PermissionMode` with `default`, `plan`, and `auto`.
- Replaced boolean shell permission checks with explicit `allow`, `deny`, and `ask_user` decisions.
- Added deny-rule-first shell enforcement and approval-required fallback for ambiguous shell commands.
- Added CLI and config support for `--permission-mode`.
```

- [ ] **Step 4: Run targeted release checks**

Run:

```bash
python -m pytest tests/test_runtime.py tests/test_agent.py tests/test_cli.py -v
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Run the full suite**

Run:

```bash
python -m pytest -v
```

Expected:

```text
all tests pass
```

- [ ] **Step 6: Commit the release bump**

Run:

```bash
git add miniharness/__init__.py CHANGELOG.md tests/test_cli.py
git commit -m "chore: release v0.2.3 mode-aware permissions"
```

## Self-Review

- Spec coverage check:
  - `PermissionMode` and `RuntimePolicy.permission_mode` are covered in Tasks 1 and 3.
  - `PermissionAction`, `PermissionDecision`, and approval-ready metadata are covered in Tasks 1 and 2.
  - deny-rule-first ordering and mode-aware `run_shell` behavior are covered in Task 2.
  - `ASK_USER` transport through `Agent._execute_tool_call()` is covered in Task 3.
  - `Config` / parser / `_build_agent()` mode flow is covered in Task 3.
  - version bump and changelog are covered in Task 4.
- Placeholder scan:
  - No `TBD`, `TODO`, or implicit “write tests later” steps remain.
- Type consistency:
  - `PermissionMode`, `PermissionAction`, `PermissionDecision`, and `permission_mode` names match the approved spec.

Plan complete and saved to `docs/superpowers/plans/2026-05-18-miniharness-v0.2.3-mode-aware-permissions-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
