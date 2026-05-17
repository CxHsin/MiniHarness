# MiniHarness v0.2.1 System Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal runtime scaffold that separates policy, capabilities, and runtime-composed state while preserving current MiniHarness behavior.

**Architecture:** Introduce `RuntimePolicy`, `AgentCapabilities`, and `AgentRuntime` as small dataclasses, then migrate CLI composition onto that runtime object while keeping `Agent` backward-compatible through a transitional dual-constructor path. Keep prompt behavior effectively unchanged, and let `ToolContext` remain the concrete tool-facing object derived from runtime policy.

**Tech Stack:** Python 3.11+, pytest, dataclasses, existing MiniHarness agent/CLI/session/tool modules

---

## File Structure

- Create: `miniharness/policy.py`
  Responsibility: define immutable runtime policy defaults and future policy seam.
- Create: `miniharness/capabilities.py`
  Responsibility: define immutable capability facts for the current agent runtime.
- Create: `miniharness/runtime.py`
  Responsibility: define `AgentRuntime`, eager cwd resolution, default session/tool-context construction, and hook list storage.
- Modify: `miniharness/agent.py`
  Responsibility: accept optional runtime injection, build default runtime when absent, preserve behavior, and reset session via runtime cwd.
- Modify: `miniharness/cli.py`
  Responsibility: compose runtime from config, construct hooks through runtime, and pass runtime into `Agent`.
- Modify: `miniharness/prompts.py`
  Responsibility: optionally accept runtime input without materially changing prompt text.
- Create: `tests/test_prompts.py`
  Responsibility: verify prompt builder compatibility independent from model client tests.
- Create: `tests/test_runtime.py`
  Responsibility: verify policy/capabilities/runtime defaults, immutability, cwd resolution, and runtime object wiring.
- Modify: `tests/test_agent.py`
  Responsibility: verify default runtime construction, runtime injection, reset semantics, and hook behavior through runtime.
- Modify: `tests/test_cli.py`
  Responsibility: verify CLI runtime composition, trace hook path, and constructor kwargs shape.
- Optional Modify: `README.md`
  Responsibility: add a short note that v0.2.1 introduces runtime scaffolding without changing user-facing commands.
- Optional Modify: `CHANGELOG.md`
  Responsibility: record v0.2.1 system runtime scaffold release notes.

## Task Decomposition

Task 1 creates the new runtime modules and their tests.
Task 2 integrates runtime into `Agent` while preserving all existing behavior.
Task 3 moves CLI composition to runtime and adds mapping guard tests.
Task 4 updates lightweight release docs if implementation scope includes version notes.

### Task 1: Runtime Core Types

**Files:**
- Create: `miniharness/policy.py`
- Create: `miniharness/capabilities.py`
- Create: `miniharness/runtime.py`
- Create: `tests/test_runtime.py`

- [ ] **Step 1: Write the failing runtime tests**

Add `tests/test_runtime.py` with:

```python
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from miniharness.capabilities import AgentCapabilities
from miniharness.hooks import ConsoleHook
from miniharness.policy import RuntimePolicy
from miniharness.runtime import AgentRuntime


def test_runtime_policy_defaults():
    policy = RuntimePolicy()

    assert policy.allow_outside_cwd is False
    assert policy.shell_timeout == 30


def test_runtime_policy_is_frozen():
    policy = RuntimePolicy()

    with pytest.raises(FrozenInstanceError):
        policy.shell_timeout = 99


def test_agent_capabilities_defaults():
    capabilities = AgentCapabilities()

    assert capabilities.has_memory is False
    assert capabilities.has_skills is False
    assert capabilities.has_permission_system is False
    assert capabilities.has_trace_hooks is True
    assert capabilities.supports_tool_registry is True


def test_agent_runtime_resolves_cwd_and_builds_session_and_tool_context(tmp_path):
    runtime = AgentRuntime.create(
        cwd=tmp_path / ".",
        policy=RuntimePolicy(shell_timeout=45, allow_outside_cwd=True),
        capabilities=AgentCapabilities(),
        history_budget_chars=321,
        hooks=[ConsoleHook()],
    )

    assert runtime.cwd == tmp_path.resolve()
    assert isinstance(runtime.cwd, Path)
    assert runtime.session.cwd == tmp_path.resolve()
    assert runtime.session.history_budget_chars == 321
    assert runtime.tool_context.cwd == tmp_path.resolve()
    assert runtime.tool_context.shell_timeout == 45
    assert runtime.tool_context.allow_outside_cwd is True
    assert len(runtime.hooks) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_runtime.py -v`

Expected: FAIL with import errors because `miniharness.policy`, `miniharness.capabilities`, and `miniharness.runtime` do not exist yet.

- [ ] **Step 3: Write minimal runtime implementation**

Create `miniharness/policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimePolicy:
    allow_outside_cwd: bool = False
    shell_timeout: int = 30
```

Create `miniharness/capabilities.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentCapabilities:
    has_memory: bool = False
    has_skills: bool = False
    has_permission_system: bool = False
    has_trace_hooks: bool = True
    supports_tool_registry: bool = True
```

Create `miniharness/runtime.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_runtime.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add miniharness/policy.py miniharness/capabilities.py miniharness/runtime.py tests/test_runtime.py
git commit -m "feat: add runtime scaffold core types"
```

### Task 2: Agent Runtime Integration

**Files:**
- Modify: `miniharness/agent.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write the failing agent runtime tests**

Add to `tests/test_agent.py`:

```python
from miniharness.capabilities import AgentCapabilities
from miniharness.policy import RuntimePolicy
from miniharness.runtime import AgentRuntime


def test_agent_builds_default_runtime_when_not_provided(tmp_path):
    model = FakeModelClient([ModelResponse(content="done", finish_reason="stop")])
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    assert agent.runtime.cwd == tmp_path.resolve()
    assert agent.runtime.policy == RuntimePolicy()
    assert agent.runtime.capabilities == AgentCapabilities()
    assert agent.runtime.session.cwd == tmp_path.resolve()
    assert agent.runtime.tool_context.cwd == tmp_path.resolve()


def test_agent_uses_provided_runtime_and_reset_rebuilds_session_only(tmp_path):
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(shell_timeout=77, allow_outside_cwd=True),
        capabilities=AgentCapabilities(),
        history_budget_chars=456,
    )
    original_tool_context = runtime.tool_context
    original_policy = runtime.policy
    original_capabilities = runtime.capabilities
    original_session = runtime.session

    model = FakeModelClient([ModelResponse(content="done", finish_reason="stop")])
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path, runtime=runtime)

    assert agent.runtime is runtime
    assert agent.session is original_session

    agent.reset()

    assert agent.runtime.session is not original_session
    assert agent.runtime.session.cwd == tmp_path.resolve()
    assert agent.runtime.session.history_budget_chars == 456
    assert agent.runtime.tool_context is original_tool_context
    assert agent.runtime.policy is original_policy
    assert agent.runtime.capabilities is original_capabilities
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py::test_agent_builds_default_runtime_when_not_provided tests/test_agent.py::test_agent_uses_provided_runtime_and_reset_rebuilds_session_only -v`

Expected: FAIL because `Agent` does not yet expose `runtime` or rebuild session through runtime-owned state.

- [ ] **Step 3: Implement minimal agent runtime support**

Update `miniharness/agent.py`:

```python
from .capabilities import AgentCapabilities
from .policy import RuntimePolicy
from .runtime import AgentRuntime
```

Change constructor shape and initialization:

```python
class Agent:
    def __init__(
        self,
        model_client: ModelClient,
        tools: list[BaseTool] | ToolRegistry,
        cwd: str | Path,
        max_steps: int = 8,
        max_tool_output_chars: int = 12000,
        history_budget_chars: int = 120000,
        max_no_progress_steps: int = 2,
        shell_timeout: int = 30,
        allow_outside_cwd: bool = False,
        hooks: list[AgentHook] | None = None,
        runtime: AgentRuntime | None = None,
    ):
        # During the v0.2.1 transition, cwd is ignored when runtime is provided.
        self.model_client = model_client
        self.tools = tools if isinstance(tools, ToolRegistry) else ToolRegistry(tools)
        self.max_steps = max_steps
        self.max_tool_output_chars = max_tool_output_chars
        self.max_no_progress_steps = max_no_progress_steps
        self.runtime = runtime or AgentRuntime.create(
            cwd=cwd,
            policy=RuntimePolicy(
                allow_outside_cwd=allow_outside_cwd,
                shell_timeout=shell_timeout,
            ),
            capabilities=AgentCapabilities(),
            history_budget_chars=history_budget_chars,
            hooks=hooks,
        )
        self.session = self.runtime.session
        self.context = self.runtime.tool_context
        self._dispatcher = HookDispatcher(self.runtime.hooks)
        self._run_id: str | None = None
```

Update reset:

```python
    def reset(self) -> None:
        self.runtime.session = Session(
            cwd=self.runtime.cwd,
            history_budget_chars=self.runtime.session.history_budget_chars,
        )
        self.session = self.runtime.session
```

Keep existing `self.session` and `self.context` references so the rest of the file can remain mostly unchanged in v0.2.1.

Remove the now-dead line:

```python
self._history_budget_chars = history_budget_chars
```

Reason: `reset()` now reads `history_budget_chars` from `self.runtime.session`, so `_history_budget_chars` becomes dead state and should be removed explicitly rather than only disappearing by omission.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent.py::test_agent_builds_default_runtime_when_not_provided tests/test_agent.py::test_agent_uses_provided_runtime_and_reset_rebuilds_session_only -v`

Expected: PASS

- [ ] **Step 5: Run related regression tests**

Run: `python -m pytest tests/test_agent.py -v`

Expected: PASS

- [ ] **Step 6: Run full regression**

Run: `python -m pytest -v`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add miniharness/agent.py tests/test_agent.py
git commit -m "feat: integrate agent with runtime scaffold"
```

### Task 3: CLI Runtime Composition

**Files:**
- Modify: `miniharness/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI runtime tests**

Add to `tests/test_cli.py`:

```python
def test_main_builds_runtime_and_passes_it_to_agent(monkeypatch, tmp_path, capsys):
    captured_agent_kwargs = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured_agent_kwargs.update(kwargs)

        def run(self, task):
            return cli.AgentOutcome(output="final answer", error=None, exit_code=0)

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        cli, "OpenAIModelClient", lambda api_key, model, base_url=None: object()
    )
    monkeypatch.setattr(cli, "Agent", FakeAgent)

    code = cli.main(["--trace", "--cwd", str(tmp_path), "summarize"])

    assert code == 0
    runtime = captured_agent_kwargs["runtime"]
    assert runtime.cwd == tmp_path.resolve()
    assert runtime.policy.shell_timeout == 30
    assert runtime.policy.allow_outside_cwd is False
    assert runtime.session.history_budget_chars == 120000
    assert len(runtime.hooks) == 1
    assert "hooks" not in captured_agent_kwargs or captured_agent_kwargs["hooks"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py::test_main_builds_runtime_and_passes_it_to_agent -v`

Expected: FAIL because `_build_agent()` still passes legacy constructor kwargs directly and does not supply `runtime`.

- [ ] **Step 3: Implement CLI runtime composition**

Update `miniharness/cli.py` imports:

```python
from .capabilities import AgentCapabilities
from .policy import RuntimePolicy
from .runtime import AgentRuntime
```

Update `_build_agent()`:

```python
def _build_agent(config) -> Agent:
    model_client = OpenAIModelClient(config.api_key, config.model, config.base_url)
    hooks = [ConsoleHook()] if config.trace else []
    runtime = AgentRuntime.create(
        cwd=config.cwd,
        policy=RuntimePolicy(
            allow_outside_cwd=config.allow_outside_cwd,
            shell_timeout=config.shell_timeout,
        ),
        capabilities=AgentCapabilities(),
        history_budget_chars=config.history_budget_chars,
        hooks=hooks,
    )
    return Agent(
        model_client=model_client,
        tools=TOOL_REGISTRY,
        cwd=config.cwd,
        max_steps=config.max_steps,
        max_tool_output_chars=config.max_tool_output_chars,
        max_no_progress_steps=config.max_no_progress_steps,
        runtime=runtime,
    )
```

Adjust existing tests that currently expect `hooks` constructor kwargs so they now assert against `runtime.hooks`.

Update `test_main_prints_final_answer_to_stdout`:

```python
    assert "hooks" not in captured_agent_kwargs
    assert captured_agent_kwargs["runtime"].hooks == []
```

Replace the old assertion:

```python
    assert captured_agent_kwargs["hooks"] is None
```

Update `test_main_trace_wires_console_hook_and_keeps_stdout_clean`:

```python
    class FakeAgent:
        def __init__(self, **kwargs):
            self._hook = kwargs["runtime"].hooks[0]
```

Replace the old constructor body:

```python
        def __init__(self, **kwargs):
            self._hook = kwargs["hooks"][0]
```

- [ ] **Step 4: Run CLI tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`

Expected: PASS

- [ ] **Step 5: Run full regression**

Run: `python -m pytest -v`

Expected: PASS

- [ ] **Step 6: Add mapping guard test**

Add to `tests/test_cli.py`:

```python
def test_runtime_mapping_keeps_policy_session_and_loop_fields_separate(monkeypatch, tmp_path):
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

    cli.main(
        [
            "--cwd",
            str(tmp_path),
            "--shell-timeout",
            "41",
            "--history-budget-chars",
            "765",
            "--max-steps",
            "9",
            "--max-tool-output-chars",
            "4321",
            "--max-no-progress-steps",
            "4",
            "--allow-outside-cwd",
            "summarize",
        ]
    )

    runtime = captured_agent_kwargs["runtime"]
    assert runtime.policy.shell_timeout == 41
    assert runtime.policy.allow_outside_cwd is True
    assert runtime.session.history_budget_chars == 765
    assert captured_agent_kwargs["max_steps"] == 9
    assert captured_agent_kwargs["max_tool_output_chars"] == 4321
    assert captured_agent_kwargs["max_no_progress_steps"] == 4
```

- [ ] **Step 7: Run targeted tests**

Run: `python -m pytest tests/test_cli.py::test_runtime_mapping_keeps_policy_session_and_loop_fields_separate -v`

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add miniharness/cli.py tests/test_cli.py
git commit -m "feat: compose runtime in cli"
```

### Task 4: Prompt Signature and Release Notes

**Files:**
- Modify: `miniharness/prompts.py`
- Create: `tests/test_prompts.py`
- Optional Modify: `README.md`
- Optional Modify: `CHANGELOG.md`

- [ ] **Step 1: Write the failing prompt compatibility test**

Create `tests/test_prompts.py`:

```python
from miniharness.prompts import build_system_prompt


def test_build_system_prompt_accepts_runtime_argument():
    assert "MiniHarness" in build_system_prompt(runtime=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_prompts.py::test_build_system_prompt_accepts_runtime_argument -v`

Expected: FAIL with `TypeError` because `build_system_prompt()` does not accept `runtime`.

- [ ] **Step 3: Implement minimal prompt signature update**

Update `miniharness/prompts.py`:

```python
SYSTEM_PROMPT = """You are MiniHarness, a local CLI coding agent.

Work inside the selected project directory. Use tools deliberately: inspect before
editing, prefer focused file reads, use search for discovery, and run relevant
verification after changes.

Known v1 limits: file edits use whole-file write_file, tool outputs may be
truncated, and shell commands run with broad local authority. Final answers
should summarize changes, verification, and remaining limitations.
"""


def build_system_prompt(runtime=None) -> str:
    return SYSTEM_PROMPT
```

If release notes are in scope, append to `CHANGELOG.md`:

```markdown
## 0.2.1

- Added `RuntimePolicy`, `AgentCapabilities`, and `AgentRuntime` as the initial system runtime scaffold.
- Moved CLI agent construction onto runtime composition while preserving current behavior.
- Kept prompt behavior effectively unchanged while adding a future-ready runtime-aware signature.
```

If README release notes are in scope, add one short sentence in the runtime overview explaining that v0.2.1 adds internal runtime composition without changing commands.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_prompts.py::test_build_system_prompt_accepts_runtime_argument -v`

Expected: PASS

- [ ] **Step 5: Run full verification**

Run: `python -m pytest -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add miniharness/prompts.py tests/test_prompts.py README.md CHANGELOG.md
git commit -m "chore: finalize v0.2.1 runtime scaffold release notes"
```

## Self-Review

Spec coverage:
- Runtime core modules are covered in Task 1.
- Agent runtime injection, reset semantics, and cwd single-source behavior are covered in Task 2.
- CLI composition, config mapping, and trace/hook wiring are covered in Task 3.
- Prompt signature restraint and optional release notes are covered in Task 4.

Placeholder scan:
- No `TODO`, `TBD`, or “similar to Task N” placeholders remain.
- Every test and implementation step includes exact file paths and example code.

Type consistency:
- The plan consistently uses `RuntimePolicy`, `AgentCapabilities`, `AgentRuntime`, `runtime`, `policy`, `capabilities`, and `history_budget_chars`.
- `RuntimePolicy` and `AgentCapabilities` are consistently frozen dataclasses.
