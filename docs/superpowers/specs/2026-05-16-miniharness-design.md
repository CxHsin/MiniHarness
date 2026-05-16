# MiniHarness Design

Date: 2026-05-16

## Goal

MiniHarness is a usable local CLI coding agent inspired by HKUDS/OpenHarness and shareAI-lab/learn-claude-code. The first version should be small enough to understand, but capable enough to inspect and modify a local project with OpenAI API-backed tool use.

The first version targets a practical command-line agent, not a full OpenHarness clone. It intentionally excludes plugins, skills, MCP, hooks, subagents, background task queues, and context compaction until the base agent loop is stable.

## Positioning

MiniHarness will be a small modular Python CLI application.

It should support:

- Running one-shot tasks from the terminal.
- Reading, writing, searching, and listing files inside a selected working directory.
- Running shell commands with timeout handling.
- Maintaining a simple session todo list.
- Calling OpenAI API for model reasoning and tool calls.

It should not yet support:

- Interactive chat mode.
- Plugin discovery.
- Subagents.
- Skill loading.
- MCP servers.
- Hook pipelines.
- Long-running background task orchestration.
- Automatic context compression.

## Reference Influence

OpenHarness informs the long-term architecture: agent loop, tools, configuration, permissions, memory/session state, and extensibility boundaries.

learn-claude-code informs the implementation style: start with the smallest working agent loop, then add tools and runtime structure incrementally.

MiniHarness should combine these influences by keeping the first version modular but not over-abstracted.

## Recommended Approach

Use a small modular CLI layout:

```text
pyproject.toml
.env.example
miniharness/
  __init__.py
  __main__.py
  cli.py
  agent.py
  model_client.py
  config.py
  prompts.py
  session.py
  tools/
    __init__.py
    base.py
    fs.py
    search.py
    shell.py
    todo.py
tests/
  test_agent.py
  test_fs_tools.py
  test_search_tool.py
  test_shell_tool.py
  test_todo_tool.py
```

This layout is larger than a single-file prototype but keeps each boundary clear. It also leaves room to add permissions, patch editing, skills, plugins, and subagents later without rewriting the first implementation.

## CLI Behavior

The CLI should support:

```bash
mh "summarize this project"
mh --cwd ./repo "fix the failing test"
```

Primary options:

- `--cwd`: working directory for all filesystem and shell tools. Defaults to the current directory.
- `--model`: OpenAI model name. Defaults from config.
- `--max-steps`: maximum model/tool loop iterations. Defaults to `8`.
- `--shell-timeout`: default shell timeout in seconds. Defaults to `30`.
- `--max-tool-output-chars`: maximum characters returned from one tool call. Defaults to `12000`.
- `--history-budget-chars`: approximate character budget for retained message history. Defaults to `120000`.
- `--max-no-progress-steps`: maximum consecutive tool rounds with only errors or empty outputs. Defaults to `2`.
- `--log-level`: diagnostic verbosity. One of `ERROR`, `WARNING`, `INFO`, or `DEBUG`. Defaults to `WARNING`.
- `--verbose`: shortcut for `--log-level INFO`.
- `--version`: print the installed package version and exit.
- `--allow-outside-cwd`: opt out of the default path safety boundary.

Interactive mode is deferred to a later version. V1 exits after one task completes.

Standard `--help` behavior is required. It prints usage, options, and a short description of the local shell risk model.

## Installation And Entry Points

The first version should be installable as an editable Python package:

```bash
pip install -e .
```

`pyproject.toml` declares runtime dependencies and exposes a console script:

```text
mh = "miniharness.cli:main"
```

The package also provides `miniharness/__main__.py` so developers can run:

```bash
python -m miniharness "summarize this project"
```

Use `pyproject.toml` rather than `requirements.txt` as the primary dependency declaration.

Runtime dependencies:

- `openai>=1.0`
- `python-dotenv>=1.0`

Development dependencies:

- `pytest>=8.0`

Rich terminal rendering is not required for v1. The CLI prints raw Markdown as plain text.

The repository includes `.env.example`:

```text
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
```

The first implementation should also include a README with the developer quickstart:

```bash
pip install -e .
copy .env.example .env
mh "summarize this project"
```

On non-Windows shells, the copy step is `cp .env.example .env`.

## Runtime Flow

1. CLI parses arguments and loads configuration.
2. CLI creates a session with working directory, message history, and todo state.
3. Agent builds a system prompt describing MiniHarness capabilities and tool-use rules.
4. Agent appends the user task to the message list.
5. Agent calls OpenAI API.
6. If the model requests tool calls, MiniHarness validates and executes each tool.
7. Tool results are appended to the message list.
8. Agent repeats until the model returns a response with no tool calls or `--max-steps` is reached.
9. The final assistant answer is printed and the process exits.

Before each tool call, MiniHarness writes a brief status line to stderr, such as:

```text
[tool] read_file miniharness/agent.py
```

This keeps long multi-step runs from feeling silent without mixing status text into stdout.

If the model repeatedly issues invalid, failing, or empty-result tool calls, the agent stops early instead of spending every remaining step on the same failure pattern.

When the task ends, MiniHarness prints the final assistant answer to stdout and exits with a process status code. It does not print a post-answer prompt in v1. Users run `mh` again for follow-up work.

Exit code policy:

- `0`: task completed and a final assistant answer was produced.
- `1`: runtime error, API failure after retries, tool execution failure that stops the agent, interruption, or max-step/no-progress stop.
- `2`: CLI argument or configuration error.

Invalid numeric arguments, such as negative `--max-steps`, fail fast with exit code `2` and a concise validation message.

## Observability

V1 logs diagnostics to stderr only. Stdout is reserved for the final assistant answer so `mh` can be used in scripts.

At the default `WARNING` level, MiniHarness prints warnings and errors only. Tool progress lines are still printed so the user can see that work is happening.

At `INFO` level, MiniHarness prints:

- Tool call start lines with a short argument summary.
- Tool completion lines with success/failure and elapsed time.
- OpenAI request start/completion lines with elapsed time.
- Retry notices for rate limits, timeouts, and 5xx responses.
- Message history trimming events.
- Tool output truncation events.

At `DEBUG` level, MiniHarness may print more detailed tool arguments and response metadata, but it must avoid printing full API keys. It may still expose user file paths, command text, stdout/stderr excerpts, and environment-derived content produced by tools, so DEBUG logs should be treated as sensitive.

V1 does not write log files. Users can redirect stderr if they want a run log.

## Streaming

V1 does not support streaming model output. Each model call waits for the full API response before continuing.

Streaming can be added later for better perceived latency, especially around long final answers. Tool-call progress in v1 is handled through short stderr status lines.

## Loop Termination

A model response is considered the final answer when it contains no `tool_calls`.

If `finish_reason` is `length`, MiniHarness must warn the user that the model response was truncated. A length-truncated response is not treated as a clean success; the CLI should exit with code `1` unless a later implementation can continue the response safely.

If a response contains both assistant text and `tool_calls`, MiniHarness treats it as an intermediate assistant message, executes the requested tools, and continues the loop. The intermediate text is kept in the message history but is not printed as the final answer.

The first version will not add a separate `finish`, `done`, or `final_answer` tool. This keeps termination aligned with OpenAI tool-calling semantics.

If `--max-steps` is reached before a no-tool-call response, the agent stops and prints a concise message explaining that the step limit was reached.

MiniHarness also tracks no-progress tool rounds. A no-progress round is a model response where every requested tool call fails or returns an empty output. If this happens for `max_no_progress_steps` consecutive tool rounds, the agent stops and reports the repeated failure pattern to the user.

The agent should additionally detect exact repeated failing tool calls by `(tool_name, arguments_json, error)`. If the same failed call repeats consecutively, it counts toward the same no-progress limit. This prevents loops where the model keeps retrying an invalid argument such as an empty search pattern.

## System Prompt Strategy

The system prompt should be generated from a stable template with these sections:

1. Role and goal: MiniHarness is a local CLI coding agent working inside the selected project directory.
2. Capabilities: summarize available filesystem, shell, and todo tools.
3. Tool-use rules: inspect before editing, prefer focused file reads, use search for discovery, run relevant verification after changes, and keep tool calls purposeful.
4. Safety rules: respect the working directory boundary, avoid unnecessary destructive commands, and keep outputs concise.
5. Response rules: final answers should summarize changes, verification, and any remaining limitations.

Tool definitions are passed to OpenAI as native tool-calling JSON schemas, not as free-form text inside the prompt. The prompt may mention tool behavior at a high level, but argument schemas live in each tool definition.

The first version will not include few-shot examples. They can be added later if behavior is inconsistent after real use.

The template lives in `miniharness/prompts.py` as a named constant or small rendering function. Keeping prompts out of `agent.py` makes prompt changes easier to review and compare.

The prompt should state known v1 limits plainly: file edits use whole-file `write_file`, tool outputs may be truncated, and shell commands run with broad local authority.

## Model Backend

The first version uses the OpenAI API directly.

Configuration sources:

- `OPENAI_API_KEY` for authentication.
- `OPENAI_MODEL` as an optional model default.
- `.env` file values loaded from the project root or current working directory.
- CLI `--model` override.
- CLI `--max-steps` override.
- CLI `--shell-timeout` override.
- CLI `--max-tool-output-chars` override.
- CLI `--history-budget-chars` override.
- CLI `--max-no-progress-steps` override.

Configuration precedence is:

1. CLI arguments.
2. Process environment variables.
3. `.env` values.
4. Built-in defaults.

Built-in defaults:

- `model`: `gpt-4o-mini`
- `max_steps`: `8`
- `shell_timeout`: `30`
- `max_tool_output_chars`: `12000`
- `history_budget_chars`: `120000`
- `max_no_progress_steps`: `2`

The first version loads `.env` for secrets and simple model selection, but will not load JSON, TOML, or YAML config files. `config.py` exists to centralize `.env` loading, environment parsing, defaults, and CLI override merging. Rich file-based configuration can be added after the runtime behavior is stable.

The OpenAI integration should be isolated in `model_client.py` behind a provider-neutral interface. The first implementation may contain only an OpenAI-backed client, but the module name should not force future provider logic into an OpenAI-specific filename.

The model client should be injectable into the agent loop through a small protocol-style interface. Tests can pass a fake client without importing or patching the real OpenAI client.

`model_client.py` exposes a complete-response interface:

```python
class ModelClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = "auto",
    ) -> ModelResponse:
        ...
```

`ModelResponse` contains:

- `content: str | None`
- `tool_calls: list[ToolCall]`
- `finish_reason: str | None`
- provider metadata useful for debug logs

`ToolCall` contains the OpenAI tool call id, tool name, and decoded JSON arguments. Invalid JSON arguments are surfaced to the agent as a tool-call parsing failure, returned to the model as a tool error when possible.

The client should use a small retry policy:

- Authentication and permission errors fail immediately.
- Context length errors, such as `context_length_exceeded`, fail immediately because retrying the same messages will produce the same error.
- Rate limit errors retry up to 3 times, using `Retry-After` when available or exponential backoff starting at 5 seconds.
- Network timeouts and 5xx server errors retry up to 2 times with exponential backoff starting at 1 second.
- After retries are exhausted, the error is reported to the CLI.

API retries are internal to one model request and do not count as agent loop steps for `--max-steps`.

The first version does not need a configurable retry framework; these fixed defaults are acceptable.

## Message History

The session stores all assistant, user, and tool messages generated during the current run.

Session lifecycle is one CLI invocation. One-shot runs do not inherit message history from previous `mh` commands, and v1 does not persist session state to disk. The `session.py` module represents in-memory runtime state, not a durable conversation store.

The first version uses a simple bounded history strategy:

- Keep the system prompt.
- Keep the latest user message.
- Keep recent assistant and tool messages up to `history_budget_chars`.
- Truncate oversized tool outputs before they enter history.
- When history exceeds the budget, drop the oldest non-system turns first while preserving valid OpenAI tool-call ordering.

History trimming is turn-based, not message-by-message. A turn is either:

- A plain user or assistant message with no tool calls.
- An assistant message with tool calls plus all corresponding tool result messages.

An assistant tool-call message and its tool results must be kept or dropped as a unit. MiniHarness must never leave a tool result without the assistant `tool_call_id` request that created it, and must never leave an assistant tool-call request without all of its corresponding tool results.

The first version will not implement token counting, semantic summarization, or reliable long-term memory. If the API returns a context length error, MiniHarness should report it clearly and suggest starting a smaller task. Context compaction is a future extension.

The history budget is character-based as a coarse approximation of token usage. OpenAI context limits are token-based, so this should be treated as a pragmatic v1 heuristic rather than an exact guarantee.

Future interactive mode will need explicit reset behavior and clearer memory expectations. In v1, users run a fresh `mh` command for each task.

## Tools

All tools return a common result shape:

```python
{
    "ok": True,
    "output": "...",
    "error": None,
}
```

Failures use:

```python
{
    "ok": False,
    "output": "...",
    "error": "...",
}
```

`output` should preserve useful stdout or partial results even when `ok` is `False`. `error` describes why the tool failed. For shell commands, a non-zero exit code sets `ok` to `False` but still preserves stdout and stderr in the returned content.

When returning results to OpenAI, MiniHarness serializes the tool result into the tool message `content` field as JSON:

```json
{
  "ok": false,
  "output": "...",
  "error": "..."
}
```

The OpenAI message shape is:

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "{\"ok\":false,\"output\":\"...\",\"error\":\"...\"}"
}
```

The model receives the JSON string, not a Python dict literal. This keeps success, output, and error semantics visible to the model.

Tool outputs are truncated to `max_tool_output_chars` before being returned to the model. Truncation keeps the beginning and end of the output with a clear marker in the middle:

```text
... [output truncated at 12000 chars, N characters omitted] ...
```

Keeping both ends preserves command headers, early errors, summaries, and trailing stack traces more reliably than keeping only the first or last segment.

The truncation marker is part of the tool output sent back to the model. The model must be able to tell that it is seeing incomplete data and can request a narrower `read_file`, `search_text`, or shell command if it needs more context.

Truncation is owned by `agent.py` after a tool returns its structured result and before the result is appended to message history. Individual tools should return their natural output up to their own semantic limits, such as search match limits. Centralizing final truncation keeps tool behavior consistent.

## Tool Registration

The first version uses an explicit static registry.

`tools/__init__.py` exports:

```python
TOOLS: list[BaseTool]
```

`agent.py` imports `TOOLS`, builds the OpenAI tool-calling JSON schema array from each tool, and dispatches model-requested calls by tool name.

V1 should not use dynamic module scanning, decorators, plugin discovery, or automatic filesystem discovery. Static registration keeps startup behavior predictable and makes tool ordering obvious in code review.

`BaseTool` is a minimal protocol-style interface:

```python
class BaseTool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        ...

    def to_openai_tool(self) -> dict[str, Any]:
        ...
```

`parameters` is the JSON schema object used inside OpenAI tool definitions. `ToolContext` carries runtime settings such as `cwd`, `allow_outside_cwd`, and shell timeout. `ToolResult` is the common result shape described above.

## Tool Execution Model

OpenAI responses may contain multiple `tool_calls`.

The first version supports multiple tool calls in one response, executed sequentially in the order returned by the model. It will not execute tools in parallel because filesystem writes and shell commands can have ordering dependencies.

All tool calls in one response are executed regardless of intermediate failures. Results, both successes and errors, are returned to the model as a complete set so the model can decide how to recover.

Each tool result must be returned with the matching OpenAI `tool_call_id`. This is required for the next model request to associate tool output with the correct requested call.

### Filesystem Tools

`list_dir(path=".")`

Lists directory entries under the active working directory.

Output format is a stable line-oriented listing:

```text
[dir]  src/
[file] pyproject.toml  1234 bytes
```

Directory names end with `/`. Files include size in bytes. Hidden files are included. Entries are sorted with directories first, then files, each group alphabetically.

`list_dir` returns at most 500 entries. If more entries exist, it returns the first 500 after sorting and appends a note telling the model how many entries were omitted. For very large directories, callers should use `search_text` or a narrower path.

`read_file(path, start_line=None, limit=None)`

Reads a UTF-8 text file. Optional line windowing prevents oversized responses.

`write_file(path, content)`

Writes UTF-8 text to a file under the active working directory. Parent directories may be created when needed.

If the target file already exists, `write_file` overwrites it completely. It does not append. Later versions can add patch and append tools for safer partial edits.

V1 writes entire files only. This means the model must keep the full target file content in context before overwriting it. Patch or diff-based editing is planned as the first post-v1 extension because whole-file writes are risky for large files and stale reads.

V1 assumes single-user, serial operation on the target working directory. It does not lock files, compare modification times, or detect that another process changed a file between `read_file` and `write_file`. If another editor or MiniHarness process modifies the same file concurrently, the last writer wins.

### Search Tool

`search_text(pattern, path=".", max_results=100)`

Searches text under a directory or file using a Python-native implementation. V1 does not call `rg`; using one implementation keeps behavior consistent across Windows, CI, and developer machines.

Search lives in `tools/search.py` because it is conceptually a project discovery tool rather than a filesystem read or shell command.

Output format is a stable `path:line:content` listing:

```text
miniharness/agent.py:42:def run(self, user_input: str) -> str:
```

The pattern is treated as a Python regular expression. Matching is case-sensitive by default. The first version does not implement glob filters, context lines, or `.gitignore` parsing.

The tool traverses files with `pathlib`, skips common large/generated directories such as `.git`, `__pycache__`, `.venv`, `node_modules`, and `dist`, and scans UTF-8 text files line by line. Binary files and unreadable files are skipped with a short note in the tool output when relevant.

The tool returns at most `max_results` matches, defaulting to 100. The allowed range is 1 to 500. If more matches exist, the output ends with a truncation note. The first version does not include context lines; callers can use `read_file` with a line window after locating a match.

### Shell Tool

`run_shell(command, timeout=None)`

Runs a command from the active working directory. Captures stdout, stderr, and exit code. Enforces a timeout. If `timeout` is not provided, the session default from `--shell-timeout` is used.

Commands are executed through the system shell, equivalent to Python `subprocess` with `shell=True`. This is intentional so users and the model can use pipelines, redirects, environment variable expansion, and shell built-ins.

### Todo Tool

`todo(action, text=None, index=None)`

Maintains session-local todos. Supported actions:

- `add`
- `list`
- `done`
- `remove`
- `clear`

`done` and `remove` use the visible list index returned by `list`.

## Safety And Permissions

The first version uses a lightweight safety model:

- Relative paths are resolved against `--cwd`.
- By default, tools cannot read or write outside `--cwd`.
- Absolute paths and `..` traversal are rejected unless `--allow-outside-cwd` is enabled.
- File tools are text-only and assume UTF-8.
- `write_file` may create parent directories, but only after the resolved target path passes the same safety check as file reads.
- Shell commands run from `--cwd`.
- Shell commands have a default timeout of 30 seconds.
- Large tool outputs are truncated to `max_tool_output_chars` before being returned to the model.

Interactive confirmation for dangerous shell commands is deferred to a later version.

V1 intentionally accepts a broad local shell risk model. `run_shell` can read files outside `--cwd`, print environment variables, access credentials available to the current process, communicate over the network, and run destructive commands. The `--cwd` path boundary protects MiniHarness file tools; it is not a sandbox for shell commands. This risk must be documented in the README before users run the CLI.

## Graceful Shutdown

MiniHarness should handle `Ctrl+C` predictably.

In one-shot mode:

- If a shell command is running, MiniHarness attempts to terminate the child process.
- The agent loop exits after printing a concise interruption message to stderr.
- In-flight OpenAI requests are abandoned from the CLI perspective when interruption is received.
- File writes that completed before interruption are kept. V1 does not roll back filesystem changes.

In the future interactive mode:

- `Ctrl+C` during user input should exit the session.
- `Ctrl+C` during tool execution should attempt to stop the running tool and return to the interactive prompt when practical.
- A second `Ctrl+C` should exit immediately.

The first version does not manage long-lived background processes beyond terminating the direct child process it started.

## Error Handling

Expected failures should be returned as structured tool results rather than crashing the agent loop.

Covered cases:

- Missing `OPENAI_API_KEY`.
- OpenAI API request errors.
- Invalid tool arguments.
- Path escaping attempts.
- Missing files.
- Encoding errors.
- Shell non-zero exit codes.
- Shell timeout.
- Maximum agent loop steps reached.

The CLI should print concise user-facing messages while preserving enough detail to debug failures.

## CLI Output

The final assistant answer is printed to stdout as raw Markdown text with no extra wrapper and no terminal rendering. For example, `**bold**` is printed literally as `**bold**`.

Tool execution status and diagnostics go to stderr. Intermediate assistant text attached to tool-call responses is not printed separately.

Because intermediate assistant text is not printed, the visible progress channel is stderr tool/API status. This is a deliberate v1 choice: stdout remains clean for the final answer, while stderr shows enough activity to avoid a silent run.

## Testing

Initial tests should cover:

- Path safety: tools cannot access files outside `--cwd` by default.
- Filesystem tools: list, read, and write.
- Search tool: regex matching, max result limits, skipped directories, and unreadable/binary file handling.
- Shell tool: successful command, failed command, and timeout.
- Todo tool: add, list, done, remove, and clear.
- Agent loop: fake model client that requests one tool call and then returns a final answer.
- Agent loop: response with multiple tool calls preserves result order and `tool_call_id` mapping.
- Agent loop: response with no tool calls terminates as the final answer.
- Agent loop: `finish_reason="length"` is reported as truncated output and exits non-zero.
- Tool message conversion: `ToolResult` is serialized as JSON in OpenAI tool message `content`.
- Agent loop: repeated no-progress tool rounds stop at `max_no_progress_steps`.
- Message history: trimming preserves assistant tool-call messages and corresponding tool results as complete groups.
- Tool output truncation: returned output includes a clear truncation marker visible to the model.
- Tool registry: all registered tools expose valid schemas and dispatch by name.
- CLI UX: `--help`, `--version`, invalid arguments, and exit codes behave as specified.
- Observability: verbose mode emits tool/API/trimming/truncation events to stderr without contaminating stdout.

Tests should avoid real OpenAI API calls. The model client must be mockable.

Shell timeout tests should use a very short timeout, such as one second or less, to avoid slow test runs.

Filesystem and path safety tests should use pytest `tmp_path` so each test has an isolated temporary working directory and automatic cleanup.

## Acceptance Criteria

V1 is considered complete when:

- `pip install -e .` installs the package and exposes `mh`.
- `.env.example` and README quickstart are present.
- `mh --help` and `mh --version` work.
- Unit tests pass without real OpenAI API calls.
- A fake model test completes a multi-step run with at least three tool rounds.
- Local tool tests cover read, write, list, search, shell, todo, truncation, path safety, and no-progress termination.
- With a real `OPENAI_API_KEY`, `mh "summarize this project"` can inspect the repository and return a final answer.
- Runtime diagnostics are visible on stderr when `--verbose` is used.

## Future Extensions

After the first version works, likely next increments are:

1. Patch editing tool.
2. Git status and diff tools.
3. Command permission policy and interactive approval.
4. Persistent session logs.
5. Skill loading.
6. Plugin discovery.
7. Context compaction.
8. Subagents and task delegation.

These are explicitly out of scope for the first implementation plan.
