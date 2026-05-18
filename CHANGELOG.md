# Changelog

## 0.2.3

- Added `PermissionMode` with `default`, `plan`, and `auto`.
- Replaced boolean shell permission checks with explicit `allow`, `deny`, and `ask_user` decisions.
- Added deny-rule-first shell enforcement and approval-required fallback for ambiguous shell commands.
- Added CLI and config support for `--permission-mode`.

## 0.2.2

- Added `RuntimePolicy.shell_enabled` and `miniharness.permissions` for runtime permission decisions.
- Deny `run_shell` at the agent execution boundary when shell access is disabled by runtime policy.
- Hardened tool-output truncation so capped output stays within the configured limit and preserves metadata.

## 0.2.1

- Added `RuntimePolicy`, `AgentCapabilities`, and `AgentRuntime` as the initial system runtime scaffold.
- Added runtime-aware `Agent` construction with backward-compatible fallback behavior.
- Moved CLI agent composition onto runtime assembly while preserving existing commands and output behavior.
- Added tests for runtime defaults, runtime injection, CLI runtime mapping, and prompt compatibility.

## 0.2.0

- Added lightweight hooks and trace-mode observability to the agent core and CLI.
- Added `HookEvent`, `HookDispatcher`, and `ConsoleHook`.
- Added `--trace` to print structured execution progress to stderr.

## 0.1.2

- Added a lightweight `ToolRegistry` for registration, lookup, dispatch, and OpenAI schema export.
- Added JSON Schema subset validation before tool execution.
- Added `ToolResult.is_error` as an OpenHarness-style compatibility property.
- Updated Agent and CLI wiring to use the registry-driven tool system.

## 0.1.1

- Added one-step continuation for truncated final model answers.
- Kept the REPL alive after a failed user turn.
- Added `/help` to the REPL command set.
- Updated README runtime documentation for v0.1.1.

## 0.1.0

- Initial MiniHarness implementation with OpenAI-compatible model calls.
- Added one-shot task mode and interactive REPL.
- Added local tools for file access, text search, shell commands, and todo tracking.
