# MiniHarness v0.2.4 Approval Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an approval runtime skeleton so `ASK_USER` decisions flow through a real approval subsystem instead of collapsing directly into a generic tool failure.

**Architecture:** Introduce a new `miniharness.approvals` module with request/decision types and a conservative default handler, compose that handler into `AgentRuntime`, and update `Agent._execute_tool_call()` to route `PermissionAction.ASK_USER` through the approval layer. Keep user-facing CLI behavior stable in v0.2.4 by preserving the original permission-layer message and not adding any interactive prompt yet.

**Tech Stack:** Python 3.12, `dataclasses`, `enum.StrEnum`, `typing.Protocol`, `pytest`, existing MiniHarness runtime/CLI/tool abstractions

---

## File Structure

- `miniharness/approvals.py`
  New module for approval request/decision abstractions and the default rejecting handler.
- `miniharness/runtime.py`
  Extend `AgentRuntime` to compose an approval handler and install a safe default in both the dataclass field and `create(...)`.
- `miniharness/agent.py`
  Route `PermissionAction.ASK_USER` through the approval subsystem and preserve approval metadata when rejecting.
- `tests/test_runtime.py`
  Add approval unit tests and runtime composition tests, since this file already covers runtime defaults and construction.
- `tests/test_agent.py`
  Add integration tests for approval rejection and custom approval success using the existing `FailingExecuteRegistry` / `FakeModelClient` patterns.
- `tests/test_cli.py`
  Add a CLI/runtime composition assertion that the default approval handler is present on the built runtime.
- `miniharness/__init__.py`
  Bump version to `0.2.4`.
- `CHANGELOG.md`
  Add the `0.2.4` entry.

### Task 1: Add Approval Types And Runtime Defaults

**Files:**
- Create: `miniharness/approvals.py`
- Modify: `miniharness/runtime.py`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Write failing approval unit and runtime tests**

Add to `tests/test_runtime.py` imports:

```python
from miniharness.approvals import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalRequest,
    DenyingApprovalHandler,
)
```

Append these tests:

```python
def test_approval_request_defaults_metadata():
    request = ApprovalRequest(
        tool_name="run_shell",
        arguments={"command": "echo hello > out.txt"},
        reason="approval_required",
        message="tool run_shell requires user approval in the current permission mode",
    )

    assert request.metadata == {}
```

```python
def test_approval_decision_defaults_metadata():
    decision = ApprovalDecision(
        action=ApprovalAction.REJECT,
        reason="approval_not_available",
    )

    assert decision.metadata == {}
```

```python
def test_denying_approval_handler_reuses_request_message():
    handler = DenyingApprovalHandler()
    request = ApprovalRequest(
        tool_name="run_shell",
        arguments={"command": "echo hello > out.txt"},
        reason="approval_required",
        message="tool run_shell requires user approval in the current permission mode",
    )

    decision = handler.decide(request)

    assert decision == ApprovalDecision(
        action=ApprovalAction.REJECT,
        reason="approval_not_available",
        message="tool run_shell requires user approval in the current permission mode",
        metadata={"tool_name": "run_shell"},
    )
```

```python
def test_agent_runtime_defaults_to_denying_approval_handler_when_built_directly(tmp_path):
    runtime = AgentRuntime(
        cwd=tmp_path.resolve(),
        session=Session(cwd=tmp_path, history_budget_chars=123),
        tool_context=ToolContext(cwd=tmp_path.resolve()),
        policy=RuntimePolicy(),
        capabilities=AgentCapabilities(),
    )

    assert isinstance(runtime.approval_handler, DenyingApprovalHandler)
```

```python
def test_agent_runtime_create_installs_default_approval_handler(tmp_path):
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(),
        capabilities=AgentCapabilities(),
    )

    assert isinstance(runtime.approval_handler, DenyingApprovalHandler)
```

```python
def test_agent_runtime_create_preserves_injected_approval_handler(tmp_path):
    handler = DenyingApprovalHandler()

    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(),
        capabilities=AgentCapabilities(),
        approval_handler=handler,
    )

    assert runtime.approval_handler is handler
```

- [ ] **Step 2: Run the focused runtime tests to verify they fail**

Run:

```bash
py -3.12 -m pytest tests/test_runtime.py -k "approval or installs_default_approval_handler or preserves_injected_approval_handler" -v
```

Expected:

```text
selected tests fail with ImportError or missing approval_handler construction support
```

- [ ] **Step 3: Create `miniharness/approvals.py` with the approval abstractions**

Create `miniharness/approvals.py`:

```python
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
```

- [ ] **Step 4: Extend `AgentRuntime` to compose the approval handler**

Update `miniharness/runtime.py` imports and dataclass:

```python
from dataclasses import dataclass, field
from pathlib import Path

from .approvals import ApprovalHandler, DenyingApprovalHandler
from .capabilities import AgentCapabilities
from .hooks import AgentHook
from .policy import RuntimePolicy
from .session import Session
from .tools.base import ToolContext
```

```python
@dataclass
class AgentRuntime:
    cwd: Path
    session: Session
    tool_context: ToolContext
    policy: RuntimePolicy
    capabilities: AgentCapabilities
    hooks: list[AgentHook] = field(default_factory=list)
    approval_handler: ApprovalHandler = field(default_factory=DenyingApprovalHandler)
```

Update `create(...)` signature and return:

```python
@classmethod
def create(
    cls,
    cwd: str | Path,
    policy: RuntimePolicy,
    capabilities: AgentCapabilities,
    history_budget_chars: int = 120000,
    hooks: list[AgentHook] | None = None,
    approval_handler: ApprovalHandler | None = None,
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
        approval_handler=approval_handler or DenyingApprovalHandler(),
    )
```

- [ ] **Step 5: Run the focused runtime tests and then the full runtime suite**

Run:

```bash
py -3.12 -m pytest tests/test_runtime.py -k "approval or installs_default_approval_handler or preserves_injected_approval_handler" -v
py -3.12 -m pytest tests/test_runtime.py -v
```

Expected:

```text
all selected tests pass
all tests in tests/test_runtime.py pass
```

- [ ] **Step 6: Commit the approval-type and runtime-default changes**

Run:

```bash
git add miniharness/approvals.py miniharness/runtime.py tests/test_runtime.py
git commit -m "feat: add approval runtime primitives"
```

### Task 2: Route `ASK_USER` Through The Approval Layer

**Files:**
- Modify: `miniharness/agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Add failing approval integration tests to `tests/test_agent.py`**

Add imports:

```python
from miniharness.approvals import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalRequest,
)
```

Add helper handlers near the existing test doubles:

```python
class RecordingApprovalHandler:
    def __init__(self, decision: ApprovalDecision):
        self.decision = decision
        self.requests: list[ApprovalRequest] = []

    def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return self.decision
```

Append these tests:

```python
def test_agent_routes_ask_user_through_approval_handler(tmp_path):
    handler = RecordingApprovalHandler(
        ApprovalDecision(
            action=ApprovalAction.REJECT,
            reason="approval_not_available",
            message="tool run_shell requires user approval in the current permission mode",
        )
    )
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
        approval_handler=handler,
    )
    agent = Agent(
        model_client=model,
        tools=[RunShellTool()],
        cwd=tmp_path,
        runtime=runtime,
    )

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    assert len(handler.requests) == 1
    assert handler.requests[0] == ApprovalRequest(
        tool_name="run_shell",
        arguments={"command": "echo hello > out.txt"},
        reason="approval_required",
        message="tool run_shell requires user approval in the current permission mode",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "default",
            "risk_tags": ["shell_exec"],
            "rule": "mode_fallback",
        },
    )
```

```python
def test_agent_rejected_approval_does_not_fall_through_to_registry_execute(tmp_path):
    handler = RecordingApprovalHandler(
        ApprovalDecision(
            action=ApprovalAction.REJECT,
            reason="approval_not_available",
            message="tool run_shell requires user approval in the current permission mode",
        )
    )
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
        approval_handler=handler,
    )
    agent = Agent(
        model_client=model,
        tools=FailingExecuteRegistry([EchoTool()]),
        cwd=tmp_path,
        runtime=runtime,
    )

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is False
    assert "requires user approval" in content["error"]
    assert "approval" not in content["metadata"]
```

```python
def test_agent_executes_tool_when_approval_handler_approves(tmp_path):
    handler = RecordingApprovalHandler(
        ApprovalDecision(
            action=ApprovalAction.APPROVE,
            reason="approved_for_test",
        )
    )
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments={"command": "dir"},
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
        approval_handler=handler,
    )
    agent = Agent(
        model_client=model,
        tools=[RunShellTool()],
        cwd=tmp_path,
        runtime=runtime,
    )

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is True
    assert content["metadata"]["returncode"] == 0
    assert len(handler.requests) == 1
```

- [ ] **Step 2: Run the focused agent tests to verify they fail**

Run:

```bash
py -3.12 -m pytest tests/test_agent.py -k "approval_handler or rejected_approval or approval_handler_approves" -v
```

Expected:

```text
selected tests fail because Agent does not yet call runtime.approval_handler
```

- [ ] **Step 3: Update `miniharness/agent.py` to call the approval subsystem**

Update imports:

```python
from .approvals import ApprovalAction, ApprovalRequest
from .capabilities import AgentCapabilities
from .hooks import AgentHook, HookDispatcher, HookEvent
from .permissions import PermissionAction, check_tool_permission
from .model_client import ModelClient, ToolCall
from .policy import RuntimePolicy
from .prompts import build_system_prompt
from .runtime import AgentRuntime
from .session import Session
from .tools.base import BaseTool, ToolRegistry, ToolResult
```

Replace the `ASK_USER` branch in `_execute_tool_call()`:

```python
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

Insert the approve continuation immediately after:

```python
    if approval.action is ApprovalAction.APPROVE:
        try:
            return self.tools.execute(tool_call.name, tool_call.arguments, self.context)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            return ToolResult(False, "", str(exc))
```

Then remove the now-duplicated unconditional `try/except` block beneath the old `ASK_USER` branch and keep a single normal execution `try/except` path for the `ALLOW` case:

```python
try:
    return self.tools.execute(tool_call.name, tool_call.arguments, self.context)
except KeyboardInterrupt:
    raise
except Exception as exc:
    return ToolResult(False, "", str(exc))
```

- [ ] **Step 4: Run the focused agent tests and then the full agent suite**

Run:

```bash
py -3.12 -m pytest tests/test_agent.py -k "approval_handler or rejected_approval or approval_handler_approves or approval_required" -v
py -3.12 -m pytest tests/test_agent.py -v
```

Expected:

```text
all selected tests pass
all tests in tests/test_agent.py pass
```

- [ ] **Step 5: Commit the agent approval-routing changes**

Run:

```bash
git add miniharness/agent.py tests/test_agent.py
git commit -m "feat: route approval-required tools through runtime handler"
```

### Task 3: Wire CLI Composition, Bump Version, And Run Regression

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `miniharness/__init__.py`
- Modify: `CHANGELOG.md`
- Optional verify only: `miniharness/cli.py`

- [ ] **Step 1: Add the CLI runtime assertion and version expectation first**

Append to `tests/test_cli.py`:

```python
def test_main_builds_runtime_with_default_approval_handler(monkeypatch, tmp_path):
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

    cli.main(["--cwd", str(tmp_path), "summarize"])

    assert captured_agent_kwargs["runtime"].approval_handler is not None
```

Update `test_main_prints_version` to expect:

```python
assert "mh 0.2.4" in capsys.readouterr().out
```

- [ ] **Step 2: Run the focused CLI tests to verify the version assertion fails first**

Run:

```bash
py -3.12 -m pytest tests/test_cli.py -k "default_approval_handler or prints_version" -v
```

Expected:

```text
version test fails with "mh 0.2.3"
```

- [ ] **Step 3: Bump version and add the changelog entry**

Update `miniharness/__init__.py`:

```python
__version__ = "0.2.4"
```

Add to the top of `CHANGELOG.md`:

```markdown
## 0.2.4

- Added `miniharness.approvals` with approval request and decision abstractions.
- Added runtime-composed approval handlers with a conservative default rejecting implementation.
- Routed `PermissionAction.ASK_USER` through the approval subsystem before final tool execution or rejection.
```

- [ ] **Step 4: Re-run the focused CLI tests and then the targeted regression suites**

Run:

```bash
py -3.12 -m pytest tests/test_cli.py -k "default_approval_handler or prints_version" -v
py -3.12 -m pytest tests/test_runtime.py tests/test_agent.py tests/test_cli.py -v
```

Expected:

```text
all selected tests pass
all tests in tests/test_runtime.py, tests/test_agent.py, and tests/test_cli.py pass
```

- [ ] **Step 5: Run the full test suite**

Run:

```bash
py -3.12 -m pytest -v
```

Expected:

```text
all tests pass
```

- [ ] **Step 6: Commit the release bump and regression updates**

Run:

```bash
git add tests/test_cli.py miniharness/__init__.py CHANGELOG.md
git commit -m "chore: release v0.2.4 approval runtime skeleton"
```

## Self-Review

- Spec coverage:
  - approval request/decision/handler abstractions are covered in Task 1.
  - runtime composition of the default approval handler is covered in Task 1 and verified again in Task 3.
  - `ASK_USER` execution routing through `Agent` is covered in Task 2.
  - preservation of the original permission-layer message is covered by Task 1 and Task 2 tests.
  - conservative default rejection and no-fallthrough execution behavior are covered in Task 1 and Task 2.
  - release metadata and regression verification are covered in Task 3.
- Placeholder scan:
  - no `TBD`, `TODO`, or “implement later” placeholders remain.
- Type consistency:
  - `ApprovalRequest`, `ApprovalAction`, `ApprovalDecision`, `ApprovalHandler`, and `DenyingApprovalHandler` names are used consistently across tasks.
