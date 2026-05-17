# MiniHarness v0.2 Hooks Design

Date: 2026-05-17

## Goal

MiniHarness v0.2 adds a lightweight hooks mechanism to the agent core so CLI users can see what the agent is doing while it runs.

The primary goal is observability, not behavior control. Hooks in v0.2 expose structured execution events that the CLI can render as human-readable trace output on stderr without changing the existing tool or model interfaces.

## Scope

This design is intentionally narrow. v0.2 should:

- Emit structured lifecycle events from the agent loop.
- Let the CLI attach a console-oriented hook implementation.
- Add a user-facing trace mode that prints execution progress to stderr.
- Keep stdout reserved for the final assistant answer.
- Preserve existing behavior when hooks are not enabled.

v0.2 should not:

- Let hooks mutate tool arguments or model messages.
- Let hooks cancel, retry, or reorder execution.
- Introduce plugin discovery or dynamic hook loading.
- Persist trace logs to disk.
- Redesign the current tool registry or session model.

## Why Hooks Now

MiniHarness v0.1.2 already has a compact but capable agent loop with tools, session reuse, output truncation, and no-progress detection. The next useful increment is not another tool, but visibility into how the loop progresses.

CLI users currently get a final answer and optional logger output, but they do not get a structured, stable description of run progress. A small hooks layer gives MiniHarness a cleaner observability seam and reduces the need to bake more ad hoc printing directly into `agent.py`.

## Recommended Approach

Use a small event-based hook system centered on one event type, one hook protocol, and one dispatcher.

This keeps the agent loop readable and preserves the current execution model:

- `Agent` remains responsible for orchestrating model calls and tool execution.
- The new hook layer observes those transitions.
- The CLI decides whether to attach a hook and how much of the event stream to render.

This is preferable to a middleware or interception design in v0.2 because the immediate problem is visibility, not policy injection.

## Design Overview

Add a new module such as `miniharness/hooks.py` with three core concepts:

### HookEvent

`HookEvent` is a small structured record representing one observed lifecycle event.

In v0.2, `HookEvent` should be an immutable dataclass. This keeps the event envelope itself stable and easy to inspect in tests while leaving `payload` flexible for future event additions.

Required fields:

- `type`: stable event name, such as `tool.started`
- `run_id`: unique identifier for one `agent.run()` invocation
- `step`: current loop step number, or `None` for events outside a step
- `payload`: event-specific data as a dict

Optional future fields such as timestamp or elapsed milliseconds can be added later without changing the core dispatch shape.

`run_id` should be generated inside `Agent.run()` with a fresh UUID per invocation so every event from one run can be correlated reliably.

Suggested shape:

```python
@dataclass(frozen=True)
class HookEvent:
    type: str
    run_id: str
    step: int | None
    payload: dict[str, Any]
```

### AgentHook

`AgentHook` is a minimal protocol or abstract base class:

```python
class AgentHook(Protocol):
    def handle(self, event: HookEvent) -> None:
        ...
```

One method is enough for v0.2. It keeps the interface stable and avoids a larger surface like `before_tool_call`, `after_tool_call`, and `before_model_call` methods that would make future expansion harder to manage.

### HookDispatcher

`HookDispatcher` owns fan-out and safety:

- If no hooks are registered, dispatch is a no-op.
- Hooks are invoked in registration order.
- If one hook raises an exception, the dispatcher catches it, records or logs it, and continues dispatching to the remaining hooks.
- Hook failures never abort the agent run.

This prevents observability code from becoming a new failure path in the core loop.

`HookDispatcher` is per-agent state created in `Agent.__init__()`. It does not need to be thread-safe in v0.2 because MiniHarness is currently a single-threaded CLI runtime. If MiniHarness is later embedded into a concurrent host, thread-safety can be revisited as a separate concern.

When a hook raises, the dispatcher should record that failure with `logger.exception(...)` and continue dispatching to later hooks. Hook failures are developer errors and should be visible in logs when logging is enabled.

## Payload Schemas

Payloads stay lightweight in v0.2, but they should still use stable keys and native Python values rather than pre-serialized JSON strings.

Event payloads should use these keys:

- `run.started`
  - `task: str`
  - `max_steps: int`
  - `model: str`
- `step.started`
  - `message_count: int`
- `model.completed`
  - `finish_reason: str | None`
  - `tool_call_count: int`
  - `has_tool_calls: bool`
  - `has_content: bool`
  - `is_continuation: bool`
- `tool.started`
  - `tool_name: str`
  - `tool_call_id: str`
  - `arguments_summary: str`
- `tool.completed`
  - `tool_name: str`
  - `tool_call_id: str`
  - `ok: bool`
  - `truncated: bool`
  - `error: str | None`
- `run.completed`
  - `steps_used: int`
  - `used_continuation: bool`
- `run.failed`
  - `steps_used: int`
  - `error: str`

These payloads are intentionally minimal. Additional keys can be added later, but v0.2 implementations and tests should treat the keys above as the stable baseline.

## Event Model

v0.2 should expose a minimal stable event set:

- `run.started`
- `step.started`
- `model.completed`
- `tool.started`
- `tool.completed`
- `run.completed`
- `run.failed`

This is enough for useful trace output while keeping the event vocabulary small.

### Event Meanings

`run.started`

- Emitted once at the beginning of `Agent.run()`
- Payload includes the user task, configured step limit, and active model name

`step.started`

- Emitted once for each agent loop iteration before the model call
- Payload includes the current message count

`model.completed`

- Emitted after one model response is received
- Payload includes `finish_reason`, whether tool calls were present, tool call count, whether content was present, and whether the response came from the continuation path
- Continuation responses triggered by `finish_reason="length"` also emit `model.completed`
- This event represents one consumed `model_client.complete()` result after any internal client retries, not one raw HTTP attempt
- v0.2 intentionally omits `model.started`, so long model waits may appear silent between `step.started` and `model.completed`
- This event fires for every consumed model response, even when `content` is empty and `tool_calls` is empty

`tool.started`

- Emitted before a single tool call executes
- Payload includes tool name, tool call id, and arguments summary
- This event fires even when argument parsing later fails, so every tool attempt is bracketed by `tool.started` and `tool.completed`
- The arguments summary should be `json.dumps(arguments, ensure_ascii=False)` truncated to 200 characters so hooks and tests have a stable representation

`tool.completed`

- Emitted after a single tool call finishes, even on tool failure
- Payload includes tool name, tool call id, `ok`, whether output was truncated, and any short error string
- Payload reflects the post-truncation result that is appended to message history

`run.completed`

- Emitted once when the agent returns a final successful answer
- Payload includes total steps used and whether a continuation was needed for a truncated final answer

`run.failed`

- Emitted once when the agent exits with an error outcome
- Payload includes total steps used and the final error message
- This includes no-progress termination, maximum-step termination, and continuation failures after a truncated final answer

### Deliberate Omissions

v0.2 does not need `model.started` or per-message session trimming events. Those may become useful later, but they are not required to make trace mode valuable for CLI users.

## Agent Integration

`Agent` should accept an optional `hooks` argument at construction time. The default is no hooks.

Suggested shape:

```python
Agent(
    model_client=...,
    tools=...,
    cwd=...,
    hooks=None,
)
```

Internally, the constructor normalizes this to a dispatcher so the rest of the class can call one method, such as `_emit(event_type, step, payload)`.

The lifecycle split should be explicit:

- `_dispatcher` is created once in `Agent.__init__()`
- `_run_id` is created fresh at the start of each `run()`

The existing control flow in `Agent.run()` remains intact. The only new responsibility is emitting events at the key lifecycle points above.

Important integration rules:

- Hook emission must happen inside the existing success and failure branches so terminal events always reflect the real outcome.
- Tool parse errors should still surface through `tool.completed` with `ok=False`.
- Output truncation should be observable through `tool.completed` payload metadata rather than by introducing a separate truncation event.
- `reset()` does not need hook events in v0.2 because hooks are scoped to a run, not general agent state mutation.
- The continuation path in `_continue_truncated_final_answer()` should emit a second `model.completed` event and never emit `tool.started` or `tool.completed`, because that request uses `tool_choice="none"`.
- Every `model_client.complete()` invocation should emit exactly one `model.completed`, including the continuation call after a truncated answer.
- `KeyboardInterrupt` is not modeled as a hook event in v0.2. It is treated as an external process interruption handled by the CLI rather than a normal agent outcome.

## Continuation Path Coverage

The continuation path in `_continue_truncated_final_answer()` is part of the hook surface and should not be treated as invisible internal logic.

Rules for continuation coverage:

- The initial truncated response emits `model.completed` with `finish_reason="length"` and `is_continuation=False`
- The follow-up continuation request emits its own `model.completed` with `is_continuation=True`
- The continuation response reuses the triggering loop step number so it stays grouped with the step that caused the continuation
- The continuation path never emits `step.started` because it runs after the loop step has already completed
- If the continuation succeeds, the run ends with `run.completed`
- If the continuation is still truncated or unexpectedly contains tool calls, the run ends with `run.failed`

## CLI Integration

The CLI should add a new explicit trace flag:

```text
--trace
```

Behavior by mode:

- Default mode: unchanged, only print final answer and errors.
- `--verbose`: unchanged logger-oriented behavior for developers.
- `--trace`: attach a `ConsoleHook` and print structured progress lines to stderr.

`--trace` should be independent from `--verbose`. Users may want a clean execution trace without full logger noise.

`--trace` is a CLI concern first. The plumbing should be explicit:

- `build_parser()` adds `--trace`
- `Config` adds `trace: bool = False`
- `load_config()` copies `args.trace` into `Config.trace`
- `_build_agent()` constructs a `ConsoleHook` when `config.trace` is true and passes it into `Agent`

`--trace` and `--verbose` are fully orthogonal:

- `--trace` controls whether `ConsoleHook` is attached
- `--verbose` and `--log-level` control logger output
- When both are enabled, both trace lines and logger lines may appear

### ConsoleHook

`ConsoleHook` is a built-in hook implementation for human-readable stderr output and should live in `miniharness/hooks.py` alongside the event and dispatcher types.

It should produce compact lines such as:

```text
[run] started
[step 1] model completed with 2 tool calls
[step 1] tool read_file started
[step 1] tool read_file completed ok
[run] completed in 2 steps
[run] failed: maximum agent steps reached
```

Design constraints:

- Output goes to stderr only.
- Lines should stay concise and avoid dumping full JSON arguments.
- Long `arguments_summary` values should be truncated again for display if needed; the console format should favor readability over exact payload reproduction.
- Final assistant content must still go only to stdout.
- The trace should help a human follow execution, not mirror the full message history.
- Trace lines and ordinary CLI error lines may both appear on stderr. This mixing is acceptable in v0.2 as long as stdout remains reserved for the final answer.
- User-facing step numbers in trace output should be 1-based even though the internal loop counter is 0-based.
- The continuation `model.completed` event should render with the triggering step number so it does not appear orphaned in trace output, for example `[step 3] model completed (continuation)`.
- `run.completed` and `run.failed` should render differently so success and failure are visually distinguishable at a glance.
- Console output should use a simple `f"[step {step}]"` prefix with no alignment padding.

The CLI remains the owner of presentation. The agent only emits structured events.

The existing `logger.info("tool call: %s", tool_call.name)` behavior may remain in v0.2 for backward compatibility. Hooks become the preferred user-facing observability path, while logger-based tool lines can be simplified or removed in a later version once trace output is established.

## Compatibility

This increment should be backward-compatible by default:

- Existing `Agent` callers do not need to change anything.
- Existing tools and `ToolRegistry` APIs remain unchanged.
- Existing tests for runs without hooks should still pass.
- REPL behavior stays the same unless `--trace` is enabled for that process.

Hooks are additive. When no hooks are attached, the runtime behavior should be functionally identical to v0.1.2.

The `step` field uses the current loop iteration number for normal events. For the continuation call after a truncated final answer, the emitted `model.completed` event should reuse the same step number as the truncated response it continues, so the two responses stay grouped in trace output.

In REPL mode, hooks are attached when the `Agent` is constructed for the session and reused across turns. Each `agent.run()` invocation emits its own fresh event stream with a new `run_id`.

## Testing Strategy

Testing should cover the hook layer directly and through the CLI.

### Agent Tests

Add tests that verify:

- Successful runs emit the expected event sequence.
- Tool-using runs emit `tool.started` and `tool.completed` in order.
- Failing runs emit `run.failed`.
- Tool argument parse errors still emit a completed tool event with failure metadata.
- Runs with truncated tool output mark that truncation in the emitted tool payload.
- Continuation responses emit a second `model.completed` with `is_continuation=True`.

Use a recording hook in tests to capture emitted events and assert on stable event fields and key payload values, not presentation strings.

### Dispatcher Tests

Add tests that verify:

- Dispatch with no hooks is a no-op.
- Multiple hooks receive the same event in registration order.
- One hook raising an exception does not prevent later hooks from running.
- Hook exceptions are logged.

### CLI Tests

Add tests that verify:

- `--trace` produces stderr progress output.
- `--trace` does not contaminate stdout final answers.
- Default mode still avoids trace lines.

## Acceptance Criteria

v0.2 is complete when:

- `Agent` can emit hook events without changing existing run semantics.
- A built-in console hook can render trace lines to stderr.
- The CLI exposes `--trace`.
- Existing behavior remains unchanged when hooks are absent.
- Automated tests cover event emission order, dispatcher safety, and CLI trace output.

## Non-Goals For v0.2

The following are intentionally deferred:

- Hook-based approvals for dangerous tools
- Hook-based retries or fallback policies
- User-defined hook module loading from config or filesystem
- Trace file export
- Rich event schema versioning
- Public plugin API guarantees for third-party extensions

These can build on the same event-based foundation later if they prove necessary.

## Future Evolution

If v0.2 proves useful, likely next steps are:

1. Add more events such as `model.started` or history-trim notifications.
2. Add a machine-readable trace sink, such as JSON lines.
3. Introduce opt-in policy hooks for approvals or blocking.
4. Add hook loading from configuration after the public interface stabilizes.

The important constraint is that v0.2 should start with observability only and avoid prematurely turning hooks into a full extension framework.
