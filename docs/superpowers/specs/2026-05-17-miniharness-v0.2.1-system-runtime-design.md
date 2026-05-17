# MiniHarness v0.2.1 System Runtime Design

Date: 2026-05-17

## Goal

MiniHarness v0.2.1 introduces a minimal system-runtime scaffold that gives future memory, permission, and skills work a clear place to live without prematurely implementing those systems.

The goal of this increment is structural, not feature-heavy. v0.2.1 should reduce coupling between `Agent`, `Config`, `Session`, `ToolContext`, and prompt construction so the project can evolve toward richer system behavior without pushing more responsibility into `agent.py`.

## Scope

v0.2.1 should:

- Introduce a small runtime composition layer for system-level state and metadata.
- Separate runtime policy from loop execution parameters.
- Separate capability facts from prompt text.
- Keep the current CLI, tool, and hook behavior stable by default.
- Provide explicit future integration points for memory, permissions, and skills.

v0.2.1 should not:

- Implement long-term memory.
- Implement a real permission enforcement framework beyond existing behavior.
- Implement skill loading, skill execution, or plugin discovery.
- Rewrite the system prompt into a large policy document.
- Redesign the tool registry or the hook event model.

## Why This Increment Now

MiniHarness already has several system-level concepts, but they are distributed across different modules:

- `Config` owns parsed external inputs.
- `Agent` owns loop execution and also constructs core runtime objects.
- `Session` owns message history state.
- `ToolContext` owns tool execution context.
- `prompts.py` owns system instructions.
- hooks provide observability, but not a runtime composition boundary.

This layout is still workable at v0.2.0 size, but it will become awkward once future memory, permission, and skills systems appear. Without a small runtime scaffold, those features will likely be added as more constructor arguments, more ad hoc prompt logic, or more direct references inside `agent.py`.

The purpose of v0.2.1 is to establish boundaries before those systems exist.

## Recommended Approach

Use a minimal three-module scaffold:

- `policy.py` for runtime policy expression
- `capabilities.py` for agent capability facts
- `runtime.py` for composed runtime state

This approach is preferable to a prompt-first design because MiniHarness does not yet have memory, permissions, or skills. Hard-coding future system behavior into the prompt before the underlying systems exist would create misleading abstractions and likely cause later rework.

It is also preferable to a permission-first design because the immediate problem is broader than shell or filesystem restrictions. The project needs a stable place for all future system-layer concerns, not only security policy.

## Design Overview

### RuntimePolicy

`RuntimePolicy` expresses runtime constraints and operating rules. In v0.2.1 it is intentionally small and mostly mirrors settings that already exist in the system.

Initial fields should include:

- `allow_outside_cwd: bool`
- `shell_timeout: int`

Possible future fields include:

- `allow_network: bool`
- `require_approval_for_shell: bool`
- `writable_roots: list[Path]`
- `allowed_tool_names: list[str] | None`

Important constraint: in v0.2.1, `RuntimePolicy` is primarily a structured expression of policy, not a full enforcement engine. Existing enforcement behavior remains where it already lives, such as in `ToolContext` or individual tools.

v0.2.1 should still define a clear ownership rule for overlapping fields:

- `RuntimePolicy` is the canonical source for runtime policy values.
- `ToolContext` continues to carry the concrete values that existing tools already consume.
- During runtime composition, `ToolContext` should be derived from `RuntimePolicy`, not configured independently.

This means some values will intentionally exist in both objects in v0.2.1, but the duplication is one-way and derived rather than peer-owned.

This keeps the first version lightweight while still giving future permissions work a clear home.

The next possible cleanup after v0.2.1 is to let `ToolContext` hold a reference to `RuntimePolicy` directly instead of copying policy fields. That change is intentionally deferred until the runtime scaffold has proven stable.

Suggested shape:

```python
@dataclass(frozen=True)
class RuntimePolicy:
    allow_outside_cwd: bool = False
    shell_timeout: int = 30
```

### AgentCapabilities

`AgentCapabilities` describes which system capabilities MiniHarness currently has available. It is not user configuration and it is not prompt prose.

Its purpose is to provide a stable system-facing description of reality so future prompt builders, UI surfaces, or runtime logic can query capability facts without inferring them from unrelated modules.

Initial fields should include:

- `has_memory: bool = False`
- `has_skills: bool = False`
- `has_permission_system: bool = False`
- `has_trace_hooks: bool = True`
- `supports_tool_registry: bool = True`

Possible future fields include:

- `has_session_summary`
- `supports_patch_editing`
- `supports_approvals`
- `supports_subagents`

Suggested shape:

```python
@dataclass(frozen=True)
class AgentCapabilities:
    has_memory: bool = False
    has_skills: bool = False
    has_permission_system: bool = False
    has_trace_hooks: bool = True
    supports_tool_registry: bool = True
```

### AgentRuntime

`AgentRuntime` is the composition object for runtime-scoped state and system-layer metadata. It should own the objects that are created once for an `Agent` instance and then reused across runs unless reset explicitly.

Initial fields should include:

- `cwd: Path`
- `session: Session`
- `tool_context: ToolContext`
- `policy: RuntimePolicy`
- `capabilities: AgentCapabilities`
- `hooks: list[AgentHook]`

`AgentRuntime.cwd` should be resolved eagerly to an absolute `Path` at runtime construction time and should become the single source of truth for the working directory.

This implies the following v0.2.1 rules:

- `Session` should be constructed from `runtime.cwd`
- `ToolContext` should be constructed from `runtime.cwd`
- `Agent.reset()` should rebuild `Session` from `runtime.cwd`, not from a separately drifting session-owned cwd

This gives MiniHarness a place to attach future system modules:

- memory can live on runtime state
- permission coordination can live on runtime policy
- skills or instruction providers can be exposed through runtime capabilities or future runtime-managed providers

Suggested shape:

```python
@dataclass
class AgentRuntime:
    cwd: Path
    session: Session
    tool_context: ToolContext
    policy: RuntimePolicy
    capabilities: AgentCapabilities
    hooks: list[AgentHook]
```

`AgentRuntime` should remain small. It is a composition boundary, not a service locator for every future feature.

`hooks` are runtime-owned configuration inputs, but `Agent` still owns the active `HookDispatcher`. In v0.2.1, hooks are treated as fixed for the lifetime of an `Agent` instance. Mutating `runtime.hooks` after agent construction is out of scope and should not be expected to rewire the dispatcher dynamically.

## Agent Integration

`Agent` should gain an optional `runtime` argument:

```python
Agent(
    model_client=...,
    tools=...,
    cwd=...,
    runtime=None,
)
```

The constructor should support both modes during v0.2.1:

- If `runtime` is provided, the agent uses runtime-owned `session`, `tool_context`, and hooks.
- If `runtime` is not provided, the agent constructs a default runtime from the current constructor arguments.

When both `runtime` and overlapping legacy constructor arguments are provided, `runtime` should take precedence for runtime-owned concerns such as cwd, session, tool context, and hooks. Loop-specific execution parameters such as `max_steps` remain agent-owned in v0.2.1.

This soft migration keeps existing call sites working while allowing the CLI to move onto the new composition path first.

The dual constructor shape is transitional, not the long-term target. The intended end state after the runtime scaffold settles is for agent construction to center on `model_client`, `tools`, and `runtime`, with legacy runtime-related constructor parameters eventually removed in a later version.

Responsibilities after integration:

- `Agent` remains responsible for loop orchestration, model calls, tool dispatch, truncation handling, and hook emission.
- `Agent` no longer needs to be the primary place where system-level state is assembled.
- `Agent.reset()` should replace the runtime session with a fresh `Session` while keeping the rest of the runtime stable.
- `Agent.reset()` should preserve runtime policy, runtime capabilities, runtime cwd, and hook wiring.

Important constraint: v0.2.1 should not turn `Agent` into a thin shell over a large runtime framework. The runtime object is there to reduce coupling, not to move the entire application into a new abstraction layer.

## CLI Integration

The CLI should become the main runtime composition layer.

`_build_agent()` should:

1. Load `Config`
2. Build `RuntimePolicy` from config values
3. Build `AgentCapabilities` from current supported features
4. Construct `Session`
5. Construct `ToolContext`
6. Construct hooks when trace is enabled
7. Assemble `AgentRuntime`
8. Pass that runtime into `Agent`

The config-to-runtime mapping should be explicit:

| Config field | Destination | Rationale |
| --- | --- | --- |
| `cwd` | `AgentRuntime.cwd` | shared runtime root |
| `shell_timeout` | `RuntimePolicy.shell_timeout` | runtime constraint |
| `allow_outside_cwd` | `RuntimePolicy.allow_outside_cwd` | runtime constraint |
| `history_budget_chars` | `Session.history_budget_chars` | session state |
| `trace` | hook construction in CLI | composition concern |
| `max_steps` | `Agent` | loop execution limit |
| `max_tool_output_chars` | `Agent` | loop output control |
| `max_no_progress_steps` | `Agent` | loop termination control |

This is a good fit for the CLI because it already owns the translation from command-line arguments and environment variables into the running process configuration.

This keeps `Config` and `Agent` from growing into overlapping composition layers.

## Config Integration

`Config` should remain an external-input container. It should not become a runtime object and should not grow fields that represent derived system facts.

In v0.2.1:

- `Config` still owns parsed CLI and environment values.
- `Config` remains the input to runtime composition.
- `Config` should not directly carry `AgentCapabilities`.
- `Config` should not pretend to represent future memory or skills state.

This keeps the distinction clear:

- config answers "what did the user or environment request?"
- runtime answers "what objects and system state exist for this agent instance?"
- capabilities answer "what can this agent actually do?"

## Prompt Integration

`prompts.py` should not be substantially expanded in v0.2.1.

At most, `build_system_prompt()` may gain a more extensible signature such as:

```python
def build_system_prompt(runtime: AgentRuntime | None = None) -> str:
    ...
```

However, the initial implementation may still ignore that argument and return essentially the same prompt text as v0.2.0.

This is deliberate. MiniHarness does not yet have real memory, permissions, or skills, so v0.2.1 should avoid pretending those systems exist in prompt form alone.

The important design rule is:

- capabilities and policy become prompt inputs later
- they should not be hard-coded into prompt prose before the systems exist

## Compatibility

This increment should preserve existing behavior by default:

- existing CLI commands continue to work
- tool registry APIs remain unchanged
- hook behavior remains unchanged
- stdout and stderr behavior remains unchanged
- runs without explicit runtime injection still work

This means the runtime scaffold is additive and structural. It should not require users to learn new commands or operational concepts in v0.2.1.

## Testing Strategy

Testing should focus on structure, default behavior preservation, and runtime composition.

### Unit Tests

Add tests that verify:

- `RuntimePolicy` default values are correct
- `RuntimePolicy` is frozen and rejects mutation
- `AgentCapabilities` default values are correct
- `AgentRuntime` stores the expected objects
- `Agent` builds a default runtime when one is not provided
- `Agent` reuses a provided runtime session across runs
- `Agent.reset()` refreshes only session state, not the entire runtime policy/capabilities setup
- `AgentRuntime.cwd` is resolved to an absolute `Path`

### CLI Tests

Add tests that verify:

- `_build_agent()` passes a runtime object into `Agent`
- trace-enabled runs still attach `ConsoleHook` through runtime composition
- existing CLI behavior remains unchanged from the user perspective
- runtime-injected hooks and trace behavior can coexist in the same build path

Existing CLI tests currently replace `Agent` with a fake class. v0.2.1 tests may continue using that pattern, but they should assert on the received constructor kwargs or runtime object shape rather than depending on the real `Agent` implementation.

### Mapping Guard Tests

Add a small regression test around config-to-runtime composition that verifies the known field mapping stays aligned:

- `shell_timeout` and `allow_outside_cwd` flow into `RuntimePolicy`
- `history_budget_chars` flows into `Session`
- `trace` only affects hook construction
- loop parameters stay on `Agent`

This test is mainly a guardrail for future refactors so runtime composition does not silently drift.

### Regression Tests

Existing tests for:

- tool execution
- hooks
- REPL behavior
- session reuse
- final answer output

should continue to pass with minimal or no semantic changes.

## Acceptance Criteria

v0.2.1 is complete when:

- MiniHarness has explicit `RuntimePolicy`, `AgentCapabilities`, and `AgentRuntime` modules.
- The CLI composes a runtime and passes it into `Agent`.
- `Agent` supports both default construction and runtime injection.
- Existing user-facing behavior remains unchanged.
- The system prompt is not prematurely expanded to simulate missing systems.
- Automated tests cover runtime defaults, runtime injection, and compatibility with current CLI behavior.

## Non-Goals

The following are intentionally out of scope for v0.2.1:

- long-term memory persistence
- memory retrieval or summarization logic
- approval flows for dangerous tools
- skill discovery or loading
- prompt-driven fake memory or fake permissions
- dynamic runtime plugin registration

## Future Evolution

If the runtime scaffold proves stable, likely next steps are:

1. Introduce real permission-policy enforcement that consumes `RuntimePolicy`.
2. Add runtime-managed memory state and session summary layers.
3. Add skill or instruction-provider registration that surfaces through runtime capabilities.
4. Let prompt construction consume capability and policy facts after those systems are real.

The key constraint is that v0.2.1 should build the smallest structure that makes these next steps cleaner, without claiming those systems already exist.
