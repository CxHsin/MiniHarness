# MiniHarness v0.2 Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add v0.2 observability hooks to MiniHarness so the agent emits structured lifecycle events and the CLI can render a `--trace` execution stream to stderr.

**Architecture:** Introduce a small `miniharness.hooks` module with immutable event records, a single-method hook protocol, a dispatcher, and a built-in `ConsoleHook`. Integrate event emission into `Agent.run()` and the truncated-answer continuation path, then wire `--trace` through CLI config into agent construction. Keep hooks read-only and preserve existing runtime behavior when no hooks are attached.

**Tech Stack:** Python 3.11+, standard library `dataclasses`, `typing`, `uuid`, `json`, `logging`, `argparse`, `pytest`.

---

## File Structure

- Create: `miniharness/hooks.py`
  Responsibility: hook event dataclass, protocol, dispatcher, console rendering, `__all__`.
- Modify: `miniharness/agent.py`
  Responsibility: accept hooks, generate `run_id`, emit lifecycle events, emit terminal failure on unexpected exceptions, cover continuation path.
- Modify: `miniharness/config.py`
  Responsibility: add `trace` boolean to config and load it from parsed args.
- Modify: `miniharness/cli.py`
  Responsibility: add `--trace`, construct `ConsoleHook`, pass hooks into `Agent`.
- Create: `tests/test_hooks.py`
  Responsibility: isolated dispatcher and console hook tests.
- Modify: `tests/test_agent.py`
  Responsibility: hook event sequence, payload, continuation, parse failure, truncation, and unexpected-exception tests.
- Modify: `tests/test_cli.py`
  Responsibility: `--trace` parser/config wiring and stdout/stderr separation.

## Dependency Graph

```text
Task 1 hook unit tests + hook module
Task 2 agent hook tests + agent integration depends on Task 1
Task 3 CLI/config trace tests + wiring depends on Task 1 and Task 2
Task 4 full verification depends on Tasks 1-3
```

### Task 1: Hook Core Module

**Files:**
- Create: `miniharness/hooks.py`
- Create: `tests/test_hooks.py`

- [ ] **Step 1: Write failing hook tests**

Add tests in `tests/test_hooks.py` for:

- `HookEvent` being an immutable dataclass
- `HookDispatcher` no-op behavior with no hooks
- `HookDispatcher` fan-out order
- `HookDispatcher` continuing after one hook raises
- `ConsoleHook` rendering `[run]` for `step=None`
- `ConsoleHook` converting 0-based step to 1-based display
- `ConsoleHook` keeping argument summaries on one line

Use test scaffolding like:

```python
from dataclasses import FrozenInstanceError

import pytest

from miniharness.hooks import ConsoleHook, HookDispatcher, HookEvent


class RecordingHook:
    def __init__(self):
        self.events = []

    def handle(self, event):
        self.events.append(event)


def test_hook_event_is_frozen():
    event = HookEvent(type="run.started", run_id="abc", step=None, payload={})

    with pytest.raises(FrozenInstanceError):
        event.type = "run.failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hooks.py -v`

Expected: FAIL because `miniharness.hooks` does not exist.

- [ ] **Step 3: Write minimal hook implementation**

Implement `miniharness/hooks.py` with:

- `HookEvent` as `@dataclass(frozen=True)`
- `AgentHook` protocol
- `HookDispatcher`
- `ConsoleHook`
- `__all__ = ["HookEvent", "AgentHook", "HookDispatcher", "ConsoleHook"]`

`ConsoleHook` should write to a configurable text stream defaulting to `sys.stderr`, which keeps it testable without patching global stderr.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hooks.py -v`

Expected: PASS.

### Task 2: Agent Hook Integration

**Files:**
- Modify: `miniharness/agent.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write failing agent hook tests**

Extend `tests/test_agent.py` with:

- a recording hook fixture/class implementing `handle(event)`
- successful final-answer event sequence
- tool-using event sequence
- `tool.completed(ok=False)` on invalid arguments
- `truncated=True` payload when tool output is shortened
- continuation path emitting a second `model.completed` with `is_continuation=True`
- unexpected model exception emitting `run.failed` before re-raising

Representative test skeleton:

```python
def test_agent_emits_events_for_tool_run(tmp_path):
    recorder = RecordingHook()
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[ToolCall(id="call_1", name="echo", arguments={"text": "hi"})],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path, hooks=[recorder])

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    assert [event.type for event in recorder.events] == [
        "run.started",
        "step.started",
        "model.completed",
        "tool.started",
        "tool.completed",
        "step.started",
        "model.completed",
        "run.completed",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent.py -v`

Expected: FAIL because `Agent` does not yet accept hooks or emit events.

- [ ] **Step 3: Implement agent hook emission**

Update `miniharness/agent.py` to:

- accept `hooks` in `__init__`
- build a dispatcher once per agent
- generate a fresh `run_id` inside `run()`
- emit all specified events with the approved payload keys
- emit `tool.started` before parse/validation failures can surface
- mark tool truncation in `tool.completed`
- emit continuation `model.completed`
- emit `run.failed` on unexpected exceptions before re-raising

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent.py -v`

Expected: PASS.

### Task 3: CLI And Config Trace Wiring

**Files:**
- Modify: `miniharness/config.py`
- Modify: `miniharness/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI/config tests**

Extend tests to cover:

- parser accepts `--trace`
- `load_config()` maps `args.trace` into `Config.trace`
- `main(argv=...)` with trace enabled still keeps final answer on stdout
- trace lines go to stderr

Keep this testable by monkeypatching `_build_agent` or `OpenAIModelClient` with a fake agent/model path rather than using real API calls.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`

Expected: FAIL because `--trace` and config wiring do not exist.

- [ ] **Step 3: Implement CLI/config changes**

Update:

- `Config` to include `trace: bool = False`
- `load_config()` to pass through `args.trace`
- `build_parser()` to add `--trace` with help text `print structured execution trace to stderr`
- `_build_agent()` to create `ConsoleHook()` when `config.trace` is true

Do not add environment-variable or `.env` fallback for trace mode.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`

Expected: PASS.

### Task 4: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused hook-related tests**

Run: `pytest tests/test_hooks.py tests/test_agent.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run: `pytest -v`

Expected: all tests pass.

- [ ] **Step 3: Spot-check trace CLI behavior**

Run: `python -m miniharness --help`

Expected: help includes `--trace`.

If API credentials are available, run:

`mh --trace --cwd . "summarize this project"`

Expected: trace lines on stderr and final answer only on stdout.

If credentials are unavailable, record the live trace smoke test as skipped.

---

## Self-Review

Spec coverage: The plan covers hook core types, payload semantics, continuation coverage, exception-to-`run.failed` behavior, CLI/config trace wiring, public exports, and verification.

Placeholder scan: No TBD/TODO placeholders remain. Each task contains explicit files, tests, commands, and expected outcomes.

Type consistency: The plan consistently uses `HookEvent`, `AgentHook`, `HookDispatcher`, `ConsoleHook`, `trace`, `run_id`, `is_continuation`, `truncated`, and `steps_used`.
