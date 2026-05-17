# Changelog

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
