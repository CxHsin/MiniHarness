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

Required fields:

- `type`: stable event name, such as `tool.started`
- `run_id`: unique identifier for one `agent.run()` invocation
- `step`: current loop step number, or `None` for events outside a step
- `payload`: event-specific data as a dict

Optional future fields such as timestamp or elapsed milliseconds can be added later without changing the core dispatch shape.

`run_id` should be generated inside `Agent.run()` with a fresh UUID per invocation so every event from one run can be correlated reliably.

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
- Payload includes the user task and configured step limit

`step.started`

- Emitted once for each agent loop iteration before the model call
- Payload includes the current message count

`model.completed`

- Emitted after one model response is received
- Payload includes `finish_reason`, whether tool calls were present, and tool call count
- Continuation responses triggered by `finish_reason="length"` also emit `model.completed`

`tool.started`

- Emitted before a single tool call executes
- Payload includes tool name, tool call id, and arguments summary
- This event fires even when argument parsing later fails, so every tool attempt is bracketed by `tool.started` and `tool.completed`

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

The existing control flow in `Agent.run()` remains intact. The only new responsibility is emitting events at the key lifecycle points above.

Important integration rules:

- Hook emission must happen inside the existing success and failure branches so terminal events always reflect the real outcome.
- Tool parse errors should still surface through `tool.completed` with `ok=False`.
- Output truncation should be observable through `tool.completed` payload metadata rather than by introducing a separate truncation event.
- `reset()` does not need hook events in v0.2 because hooks are scoped to a run, not general agent state mutation.
- The continuation path in `_continue_truncated_final_answer()` should emit a second `model.completed` event and never emit `tool.started` or `tool.completed`, because that request uses `tool_choice="none"`.

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

`--trace` is a CLI concern first. `load_config()` should surface a boolean trace flag, and `_build_agent()` should wire a `ConsoleHook` into the agent when that flag is set.

### ConsoleHook

`ConsoleHook` is a built-in hook implementation for human-readable stderr output and should live in `miniharness/hooks.py` alongside the event and dispatcher types.

It should produce compact lines such as:

```text
[run] started
[step 1] model completed with 2 tool calls
[step 1] tool read_file started
[step 1] tool read_file completed ok
[run] completed in 2 steps
```

Design constraints:

- Output goes to stderr only.
- Lines should stay concise and avoid dumping full JSON arguments.
- Final assistant content must still go only to stdout.
- The trace should help a human follow execution, not mirror the full message history.

The CLI remains the owner of presentation. The agent only emits structured events.

## Compatibility

This increment should be backward-compatible by default:

- Existing `Agent` callers do not need to change anything.
- Existing tools and `ToolRegistry` APIs remain unchanged.
- Existing tests for runs without hooks should still pass.
- REPL behavior stays the same unless `--trace` is enabled for that process.

Hooks are additive. When no hooks are attached, the runtime behavior should be functionally identical to v0.1.2.

The `step` field uses the current loop iteration number for normal events. For the continuation call after a truncated final answer, the emitted `model.completed` event should reuse the same step number as the truncated response it continues, so the two responses stay grouped in trace output.

## Testing Strategy

Testing should cover the hook layer directly and through the CLI.

### Agent Tests

Add tests that verify:

- Successful runs emit the expected event sequence.
- Tool-using runs emit `tool.started` and `tool.completed` in order.
- Failing runs emit `run.failed`.
- Tool argument parse errors still emit a completed tool event with failure metadata.
- Runs with truncated tool output mark that truncation in the emitted tool payload.

Use a recording hook in tests to capture emitted events and assert only on stable fields, not presentation strings.

### Dispatcher Tests

Add tests that verify:

- Dispatch with no hooks is a no-op.
- Multiple hooks receive the same event in registration order.
- One hook raising an exception does not prevent later hooks from running.

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
