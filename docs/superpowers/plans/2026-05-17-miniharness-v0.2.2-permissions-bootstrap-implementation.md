# MiniHarness v0.2.2 Permissions Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first real runtime-policy enforcement path by denying `run_shell` when `RuntimePolicy.shell_enabled` is `False`.

**Architecture:** Extend `RuntimePolicy` with one new boolean, add a small `miniharness/permissions.py` decision layer, and enforce it at `Agent._execute_tool_call()` before tool execution. Keep CLI behavior unchanged by default, and prove the path through unit tests, agent integration tests, and full regression runs.

**Tech Stack:** Python 3, `dataclasses`, `pytest`, existing MiniHarness runtime/agent/tool abstractions

---

### Task 1: Add Permission Policy Surface And Decision Module

**Files:**
- Create: `miniharness/permissions.py`
- Modify: `miniharness/policy.py`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Extend runtime-policy tests to describe the new default**

Add to `tests/test_runtime.py`:

```python
def test_runtime_policy_defaults():
    policy = RuntimePolicy()

    assert policy.allow_outside_cwd is False
    assert policy.shell_timeout == 30
    assert policy.shell_enabled is True
```

- [ ] **Step 2: Add permission-decision unit tests**

Append to `tests/test_runtime.py`:

```python
from miniharness.permissions import PermissionDecision, check_tool_permission


def test_check_tool_permission_allows_shell_when_enabled():
    decision = check_tool_permission(
        RuntimePolicy(shell_enabled=True),
        "run_shell",
        {"command": "echo hi"},
    )

    assert decision == PermissionDecision(allowed=True)


def test_check_tool_permission_denies_shell_when_disabled():
    decision = check_tool_permission(
        RuntimePolicy(shell_enabled=False),
        "run_shell",
        {"command": "echo hi"},
    )

    assert decision == PermissionDecision(
        allowed=False,
        error="tool run_shell is disabled by runtime policy",
    )


def test_check_tool_permission_allows_non_shell_tools_when_shell_disabled():
    decision = check_tool_permission(
        RuntimePolicy(shell_enabled=False),
        "read_file",
        {"path": "README.md"},
    )

    assert decision == PermissionDecision(allowed=True)
```

- [ ] **Step 3: Run the focused runtime tests to verify they fail**

Run:

```bash
python -m pytest tests/test_runtime.py -v
```

Expected:

```text
FAIL tests/test_runtime.py::test_runtime_policy_defaults
ERROR importing miniharness.permissions
```

- [ ] **Step 4: Add the new `shell_enabled` field to `RuntimePolicy`**

Update `miniharness/policy.py` to:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimePolicy:
    allow_outside_cwd: bool = False
    shell_timeout: int = 30
    shell_enabled: bool = True
```

- [ ] **Step 5: Create the permission-decision module**

Create `miniharness/permissions.py`:

```python
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
```

- [ ] **Step 6: Re-run runtime tests and make sure they pass**

Run:

```bash
python -m pytest tests/test_runtime.py -v
```

Expected:

```text
PASSED tests/test_runtime.py::test_runtime_policy_defaults
PASSED tests/test_runtime.py::test_check_tool_permission_allows_shell_when_enabled
PASSED tests/test_runtime.py::test_check_tool_permission_denies_shell_when_disabled
PASSED tests/test_runtime.py::test_check_tool_permission_allows_non_shell_tools_when_shell_disabled
```

- [ ] **Step 7: Commit the policy and permission bootstrap**

Run:

```bash
git add miniharness/policy.py miniharness/permissions.py tests/test_runtime.py
git commit -m "feat: add permission bootstrap policy checks"
```

### Task 2: Enforce Permission Decisions In The Agent Execution Boundary

**Files:**
- Modify: `miniharness/agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Add a denied-shell integration test at the agent boundary**

Append to `tests/test_agent.py`:

```python
def test_agent_denies_shell_tool_when_runtime_policy_disables_it(tmp_path):
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
                        arguments={"command": "echo blocked"},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(shell_enabled=False),
        capabilities=AgentCapabilities(),
        hooks=[recorder],
    )
    agent = Agent(model_client=model, tools=[], cwd=tmp_path, runtime=runtime)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    tool_payload = json.loads(model.calls[1]["messages"][-1]["content"])
    assert tool_payload["ok"] is False
    assert tool_payload["output"] == ""
    assert tool_payload["error"] == "tool run_shell is disabled by runtime policy"
    assert [event.type for event in recorder.events][3:5] == ["tool.started", "tool.completed"]
    assert recorder.events[4].payload["ok"] is False
    assert recorder.events[4].payload["error"] == "tool run_shell is disabled by runtime policy"
```

- [ ] **Step 2: Add a regression test that proves disabled shell does not touch the tool registry**

Append to `tests/test_agent.py`:

```python
def test_agent_does_not_execute_shell_tool_when_permission_denies_it(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments={"command": "echo blocked"},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(shell_enabled=False),
        capabilities=AgentCapabilities(),
    )
    registry = ToolRegistry([])
    agent = Agent(model_client=model, tools=registry, cwd=tmp_path, runtime=runtime)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["error"] == "tool run_shell is disabled by runtime policy"
    assert "unknown tool" not in content["error"]
```

- [ ] **Step 3: Run the new agent tests and confirm they fail**

Run:

```bash
python -m pytest tests/test_agent.py -k "denies_shell or permission_denies" -v
```

Expected:

```text
FAILED tests/test_agent.py::test_agent_denies_shell_tool_when_runtime_policy_disables_it
FAILED tests/test_agent.py::test_agent_does_not_execute_shell_tool_when_permission_denies_it
```

- [ ] **Step 4: Wire permission checks into the agent**

Update the imports and `_execute_tool_call()` in `miniharness/agent.py`:

```python
from .permissions import check_tool_permission
```

```python
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

- [ ] **Step 5: Run targeted agent tests and make sure they pass**

Run:

```bash
python -m pytest tests/test_agent.py -k "denies_shell or permission_denies or invalid_arguments or emits_failed_tool_event" -v
```

Expected:

```text
PASSED tests/test_agent.py::test_agent_denies_shell_tool_when_runtime_policy_disables_it
PASSED tests/test_agent.py::test_agent_does_not_execute_shell_tool_when_permission_denies_it
PASSED tests/test_agent.py::test_agent_accepts_tool_registry_and_validates_arguments
PASSED tests/test_agent.py::test_agent_emits_failed_tool_event_for_invalid_arguments
```

- [ ] **Step 6: Run a full regression pass after the behavior change**

Run:

```bash
python -m pytest -v
```

Expected:

```text
all tests pass
```

- [ ] **Step 7: Commit the agent enforcement path**

Run:

```bash
git add miniharness/agent.py tests/test_agent.py
git commit -m "feat: enforce runtime tool permissions"
```

### Task 3: Update Version Metadata And Close The Loop

**Files:**
- Modify: `miniharness/__init__.py`
- Modify: `CHANGELOG.md`
- Optional verify only: `README.md`

- [ ] **Step 1: Add a version assertion that captures the release bump**

Add to `tests/test_cli.py`:

```python
def test_main_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])

    assert exc.value.code == 0
    assert "mh 0.2.2" in capsys.readouterr().out
```

- [ ] **Step 2: Run the version test and verify it fails before changing metadata**

Run:

```bash
python -m pytest tests/test_cli.py::test_main_prints_version -v
```

Expected:

```text
FAILED tests/test_cli.py::test_main_prints_version
```

- [ ] **Step 3: Bump package version and add changelog notes**

Update `miniharness/__init__.py` to:

```python
__version__ = "0.2.2"
```

Add a new `0.2.2` entry to `CHANGELOG.md` describing:

```markdown
## 0.2.2

- Added runtime permission bootstrap through `miniharness.permissions`.
- Added `RuntimePolicy.shell_enabled` with default-enabled backward compatibility.
- Denied `run_shell` at the agent boundary when shell access is disabled through injected runtime policy.
```

- [ ] **Step 4: Re-run targeted version and regression tests**

Run:

```bash
python -m pytest tests/test_cli.py::test_main_prints_version tests/test_runtime.py tests/test_agent.py tests/test_shell_tool.py -v
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Run the full suite one final time**

Run:

```bash
python -m pytest -v
```

Expected:

```text
all tests pass
```

- [ ] **Step 6: Commit the release polish**

Run:

```bash
git add miniharness/__init__.py CHANGELOG.md tests/test_cli.py
git commit -m "chore: release v0.2.2 permission bootstrap"
```

## Self-Review

- Spec coverage check:
  - `RuntimePolicy.shell_enabled` is implemented in Task 1.
  - `miniharness/permissions.py` and `PermissionDecision` are implemented in Task 1.
  - `Agent._execute_tool_call()` enforcement and denied-shell semantics are implemented in Task 2.
  - Existing hook semantics and no-execution denied path are verified in Task 2.
  - Version bump to `0.2.2` is implemented in Task 3.
  - Default-path regressions are covered by the targeted and full-suite test runs in Tasks 2 and 3.
- Placeholder scan:
  - No `TBD`, `TODO`, or implicit "write tests later" steps remain.
- Type consistency:
  - `RuntimePolicy.shell_enabled`, `PermissionDecision`, and `check_tool_permission(...)` names match the approved spec.

Plan complete and saved to `docs/superpowers/plans/2026-05-17-miniharness-v0.2.2-permissions-bootstrap-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
