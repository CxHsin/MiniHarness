# MiniHarness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1 MiniHarness one-shot CLI agent described in `docs/superpowers/specs/2026-05-16-miniharness-design.md`.

**Architecture:** Implement a small Python package with a provider-neutral model client, explicit static tool registry, in-memory session state, Python-native tools, and a one-shot agent loop. Tool output is serialized to OpenAI tool messages as JSON, progress/logs go to stderr, and final answers go to stdout.

**Tech Stack:** Python 3.11+, `openai>=1.0`, `python-dotenv>=1.0`, `pytest>=8.0`, standard library `argparse`, `logging`, `subprocess`, `pathlib`, `json`, and `typing`.

---

## Dependency Graph

Tasks can be executed with this dependency shape:

```text
Task 1 CLI/package skeleton
Task 2 config/session
Task 3 base + filesystem tools --> Task 4 search/shell/todo
Task 5 model client + prompts

Task 1 + Task 2 + Task 4 + Task 5 --> Task 6 agent loop
Task 1 + Task 2 + Task 5 + Task 6 --> Task 7 CLI wiring
Task 7 --> Task 8 verification
```

Parallel-safe tracks after Task 1:

- Task 2 can run independently.
- Task 3 can run independently.
- Task 5 can run independently.
- Task 4 depends on Task 3.
- Task 6 depends on Tasks 2, 3, 4, and 5.
- Task 7 depends on Tasks 1, 2, 5, and 6.

### Task 1: Project Packaging And CLI Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `README.md`
- Create: `miniharness/__init__.py`
- Create: `miniharness/__main__.py`
- Create: `miniharness/cli.py`
- Create: `tests/__init__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
# tests/test_cli.py
import pytest

from miniharness.cli import build_parser


def test_parser_accepts_one_shot_task():
    parser = build_parser()
    args = parser.parse_args(["summarize this project"])
    assert args.task == "summarize this project"
    assert args.max_steps == 8
    assert args.history_budget_chars == 120000


def test_parser_verbose_sets_log_level_info():
    parser = build_parser()
    args = parser.parse_args(["--verbose", "summarize"])
    assert args.verbose is True


def test_parser_rejects_negative_max_steps():
    parser = build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--max-steps", "-1", "summarize"])

    assert exc.value.code == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`

Expected: FAIL because `miniharness.cli` does not exist.

- [ ] **Step 3: Implement package and parser skeleton**

Create `pyproject.toml`, `.env.example`, `README.md`, `miniharness/__init__.py`, `miniharness/__main__.py`, and `miniharness/cli.py` with parser defaults from the spec.

`pyproject.toml` must include:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`cli.py` exposes testable entry points:

```python
def build_parser() -> argparse.ArgumentParser:
    ...

def main(argv: list[str] | None = None) -> int:
    ...
```

`main(argv=None)` reads `sys.argv` through `argparse` by default, but tests can pass an explicit argument list.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`

Expected: PASS.

### Task 2: Configuration And Session

**Files:**
- Create: `miniharness/config.py`
- Create: `miniharness/session.py`
- Create: `tests/conftest.py`
- Test: `tests/test_config.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write failing config and session tests**

Tests cover CLI/env/default precedence, `.env` parsing, and turn-based history trimming.

Create shared test helpers in `tests/conftest.py`:

- `FakeModelClient`: stores a sequence of duck-typed response objects or dictionaries and returns them one at a time from `complete()`.
- `fake_tool_context`: fixture that creates a `ToolContext` rooted at `tmp_path`.
- `make_tool_call`: helper for constructing decoded tool-call-shaped dictionaries.

`tests/conftest.py` must not import `miniharness.model_client`, because Task 2 and Task 5 are parallel-safe. Fake responses should expose `content`, `tool_calls`, and `finish_reason` by simple attributes or dictionary keys until Task 5's concrete types exist.

Later tests should use fixtures through pytest, not by importing private symbols from another test module.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_config.py tests/test_session.py -v`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement config and session**

Implement `Config`, `load_config`, `Session`, and turn-based message trimming that preserves tool-call groups.

Keep `tests/conftest.py` limited to test helpers. Production code must not import it.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_config.py tests/test_session.py -v`

Expected: PASS.

### Task 3: Tool Base And Filesystem Tools

**Files:**
- Create: `miniharness/tools/base.py`
- Create: `miniharness/tools/fs.py`
- Create: `miniharness/tools/__init__.py`
- Test: `tests/test_fs_tools.py`

- [ ] **Step 1: Write failing filesystem tests**

Tests cover `BaseTool` schema conversion, cwd path safety, list formatting, list entry limit, read line windows, write overwrite, and parent directory creation.

BaseTool interface behavior is tested in `tests/test_fs_tools.py` through a small concrete test tool and through filesystem tool subclasses. Do not create a separate `tests/test_base_tool.py` unless the interface grows beyond schema conversion and dispatch support.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_fs_tools.py -v`

Expected: FAIL because tools do not exist.

- [ ] **Step 3: Implement base and filesystem tools**

Implement `ToolResult`, `ToolContext`, `BaseTool`, `ListDirTool`, `ReadFileTool`, `WriteFileTool`, path resolution, and registry exports.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_fs_tools.py -v`

Expected: PASS.

### Task 4: Search, Shell, And Todo Tools

**Files:**
- Create: `miniharness/tools/search.py`
- Create: `miniharness/tools/shell.py`
- Create: `miniharness/tools/todo.py`
- Modify: `miniharness/tools/__init__.py`
- Test: `tests/test_search_tool.py`
- Test: `tests/test_shell_tool.py`
- Test: `tests/test_todo_tool.py`

- [ ] **Step 1: Write failing tool tests**

Tests cover Python-native regex search, max result validation, skipped directories, shell success/failure/timeout, and todo add/list/done/remove/clear by visible index.

Shell timeout tests must use a cross-platform long-running command:

```text
python -c "import time; time.sleep(10)"
```

Do not use `sleep 10`; it is not portable to Windows.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_search_tool.py tests/test_shell_tool.py tests/test_todo_tool.py -v`

Expected: FAIL because tools do not exist.

- [ ] **Step 3: Implement tools**

Implement search, shell, and todo tools using the shared `ToolContext` and `ToolResult`.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_search_tool.py tests/test_shell_tool.py tests/test_todo_tool.py -v`

Expected: PASS.

### Task 5: Model Client And Prompt

**Files:**
- Create: `miniharness/model_client.py`
- Create: `miniharness/prompts.py`
- Test: `tests/test_model_client.py`

- [ ] **Step 1: Write failing model client tests**

Tests cover OpenAI response parsing, decoded tool call arguments, invalid JSON tool arguments, `finish_reason`, and retry classification helpers.

Retry tests must not call the real OpenAI API. They should use fake API exceptions/responses and injectable sleep/backoff hooks, or pure retry classification helpers that map error types/status codes to retry decisions.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_model_client.py -v`

Expected: FAIL because model client does not exist.

- [ ] **Step 3: Implement model client protocol and OpenAI adapter**

Implement `ModelClient`, `ModelResponse`, `ToolCall`, `OpenAIModelClient`, response parsing, and retry policy.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_model_client.py -v`

Expected: PASS.

### Task 6: Agent Loop

**Files:**
- Create: `miniharness/agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write failing agent tests**

Tests cover final answer termination, `finish_reason="length"` non-zero outcome, tool dispatch serialization as JSON content, multiple tool calls with partial failure, no-progress termination, output truncation marker, complete tool-call group history, and interrupted tool execution returning an interrupted outcome.

Use `FakeModelClient` from `tests/conftest.py` rather than defining a second fake client in this file.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_agent.py -v`

Expected: FAIL because agent loop does not exist.

- [ ] **Step 3: Implement agent loop**

Implement one-shot `Agent.run(task)`, tool schema assembly, sequential tool dispatch, JSON tool messages, truncation, no-progress detection, interruption propagation, and final outcome object.

`agent.py` may call `logging.getLogger(__name__)`, but it must not call `logging.basicConfig()` or configure the root logger. Logging configuration is owned by `cli.py:main()`.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_agent.py -v`

Expected: PASS.

### Task 7: CLI Wiring And Documentation

**Files:**
- Modify: `miniharness/cli.py`
- Modify: `README.md`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Extend CLI tests**

Tests cover exit codes, missing API key configuration failure, `--version`, `--help`, stdout/stderr separation using a fake model client hook where practical, and `KeyboardInterrupt`/SIGINT handling returning exit code `1`.

Signal handling tests should spawn the CLI as a subprocess and use a fake long-running tool or fake model path that blocks long enough for the test to send SIGINT. The test should then assert exit code `1` and an interruption message on stderr.

For non-subprocess CLI tests, call `main(argv=[...])` directly and use shared fakes/fixtures from `tests/conftest.py` where injection is needed.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_cli.py -v`

Expected: FAIL until CLI is wired to config, agent, and model client.

- [ ] **Step 3: Implement CLI main**

Wire parser, config loading, logging, OpenAI model client, agent run, stdout/stderr behavior, and exit codes.

Logging configuration is owned here. `cli.py:main()` configures the root logger exactly once for the current process based on `--log-level`/`--verbose`; lower-level modules only obtain module loggers with `logging.getLogger(__name__)`.

Add graceful shutdown handling:

- Catch `KeyboardInterrupt` around the one-shot run.
- Ask the current tool execution to stop when practical.
- Ensure shell child processes started by `run_shell` are terminated on interruption.
- Print a concise interruption message to stderr.
- Exit with code `1`.
- Do not attempt to roll back file writes that already completed.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_cli.py -v`

Expected: PASS.

### Task 8: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run full test suite**

Run: `pytest -v`

Expected: all tests pass.

- [ ] **Step 2: Run CLI smoke commands**

Run: `python -m miniharness --help`

Expected: usage text with options and shell risk summary.

Run: `python -m miniharness --version`

Expected: package version.

Run: `pip install -e .`

Expected: editable install succeeds and exposes `mh`.

- [ ] **Step 3: Run real API smoke test when credentials are available**

Run: `mh --cwd . "summarize this project"`

Expected: with a real `OPENAI_API_KEY`, MiniHarness inspects the repository and prints a final answer to stdout.

If no real API key is available in the environment, record this verification as skipped with the reason `OPENAI_API_KEY not set`.

- [ ] **Step 4: Run verbose diagnostics smoke test**

Run: `mh --verbose --cwd . "summarize this project" 1>stdout.txt 2>stderr.txt`

Expected: stdout contains only the final assistant answer; stderr contains tool/API diagnostics.

If no real API key is available in the environment, run the closest fake-model CLI test instead and record the real API verification as skipped.

---

## Self-Review

Spec coverage: The plan covers packaging, CLI UX, config, session, all tools, model client, agent loop, observability, message serialization, retry classification, truncation, graceful shutdown, real API smoke verification, logging ownership, cross-platform shell tests, subprocess SIGINT tests, shared pytest fixtures, and tests.

Placeholder scan: No TBD/TODO/FIXME placeholders are present. Test snippets avoid ambiguous parser failure handling and use `pytest.raises(SystemExit)`.

Type consistency: Tool interfaces use `ToolContext`, `ToolResult`, `BaseTool`, `ModelClient`, `ModelResponse`, and `ToolCall` consistently across production tasks. Shared fakes live in `tests/conftest.py`, stay duck-typed until Task 5 concrete model types exist, and task-specific tests do not import helper classes from sibling test modules. Logging configuration belongs only to `cli.py`, while runtime modules use module loggers.
