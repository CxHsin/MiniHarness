# MiniHarness

MiniHarness 是一个小型、本地运行的 CLI Agent。它使用 OpenAI-compatible API 调用模型，并通过本地工具读取文件、搜索文本、写入文件、运行命令和维护任务列表。

这个项目不是 OpenHands / OpenHarness 的完整复刻，而是一个更小、更容易理解、更容易调试的 Agent Harness。它适合学习 agent loop、tool calling、本地工具执行和 OpenAI-compatible 模型接入。

## 最新状态

- 当前版本：`0.2.1`
- 当前入口：`mh`
- 当前运行模式：一次性任务模式和交互式 REPL
- 当前模型接口：OpenAI-compatible Chat Completions API
- 当前工具：`list_dir`、`read_file`、`write_file`、`search_text`、`run_shell`、`todo`
- 当前可观测性：支持 `--trace`，可在 stderr 输出结构化执行轨迹
- 当前系统骨架：已引入 `RuntimePolicy`、`AgentCapabilities`、`AgentRuntime`
- 当前测试覆盖：agent loop、tools、config、CLI、model client、hooks / trace、runtime scaffold

## 快速开始

Windows 推荐使用 Python Launcher：

```powershell
py -3.12 -m pip install -e .[dev]
copy .env.example .env
```

macOS / Linux / Git Bash：

```bash
python -m pip install -e ".[dev]"
cp .env.example .env
```

编辑 `.env`：

```text
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=
```

运行一次性任务：

```powershell
mh --cwd . "总结这个项目"
```

查看帮助：

```powershell
mh --help
```

查看版本：

```powershell
mh --version
```

## 配置模型 / Provider

MiniHarness 使用 OpenAI Python SDK，但可以连接任何 OpenAI-compatible API。很多第三方服务要求 `OPENAI_BASE_URL` 以 `/v1` 结尾；如果遇到 `404 not found`，优先检查 base URL 和模型 ID。

### OpenAI

```text
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=
```

### DeepSeek

```text
OPENAI_API_KEY=sk-...
OPENAI_MODEL=deepseek-chat
OPENAI_BASE_URL=https://api.deepseek.com
```

### Ollama

```text
OPENAI_API_KEY=ollama
OPENAI_MODEL=qwen2.5-coder:7b
OPENAI_BASE_URL=http://localhost:11434/v1
```

### One API / LiteLLM / vLLM / 其他兼容服务

```text
OPENAI_API_KEY=<provider-key>
OPENAI_MODEL=<provider-model-id>
OPENAI_BASE_URL=https://provider.example/v1
```

也可以用 CLI 参数临时覆盖：

```powershell
mh --base-url http://localhost:11434/v1 --model qwen2.5-coder:7b "总结这个项目"
```

## 运行模式

MiniHarness 支持两种运行模式。

### 一次性任务

传入任务文本时，MiniHarness 会执行一次 agent loop，输出最终答复，然后退出：

```powershell
mh "阅读 README 并总结项目目标"
```

一次性任务会创建一个新的 session。下一次执行 `mh "任务"` 不会继承上一次的消息历史。

### 交互式 REPL

不传入任务文本时，MiniHarness 会进入交互式 REPL：

```text
mh
MiniHarness REPL. Type /help for commands.
mh> 总结这个项目
...
mh> /reset
Session reset
mh> /exit
```

REPL 命令：

| 命令 | 说明 |
| --- | --- |
| `/help` | 查看 REPL 命令 |
| `/exit` | 退出 REPL |
| `/quit` | 退出 REPL |
| `/reset` | 清空当前 session 的消息历史 |
| `/cwd` | 打印当前工作目录 |

REPL 会在同一进程中复用 session，因此你可以继续追问“继续”“基于上一步修改”等上下文相关任务。使用 `/reset` 可以让下一轮从干净上下文开始。单轮任务失败时，REPL 会打印错误并继续等待下一条输入。

## Provider 兼容性概览

MiniHarness 依赖 OpenAI-compatible Chat Completions 的 tool calling 能力。不同 provider 的兼容程度可能不同：

| Provider | 推荐状态 | 说明 |
| --- | --- | --- |
| OpenAI | 支持 | 使用默认 SDK 配置即可 |
| DeepSeek | 支持 | 使用 `deepseek-chat` 和官方 base URL |
| Ollama | 视模型而定 | 需要本地模型支持工具调用格式 |
| One API | 视后端而定 | 确认转发模型支持 tool calling |
| LiteLLM | 视后端而定 | 确认后端模型和 LiteLLM 配置支持工具调用 |
| vLLM | 视模型而定 | 需要启用兼容 API 和工具调用能力 |

如果 provider 返回 `404`、`tool_calls` 格式异常，或模型始终不调用工具，通常不是 MiniHarness 的 agent loop 问题，而是 base URL、模型 ID 或 provider tool calling 兼容性问题。

## MiniHarness 的核心能力

### Agent Loop

MiniHarness 的 agent loop 会：

- 构建 system prompt，说明工具能力和行为规则
- 把用户任务发送给模型
- 解析模型返回的 `tool_calls`
- 顺序执行工具，并把工具结果以 JSON tool message 返回给模型
- 当模型不再返回 `tool_calls` 时，将该回复视为最终答案
- 当最终文本回答因 `finish_reason="length"` 截断时，自动续写一次；如果仍然截断，则返回错误，避免把半截回答当作完成结果
- 使用 no-progress 计数器避免连续失败的工具调用无限消耗步骤数

默认上限：

| 参数 | 默认值 |
| --- | --- |
| `--max-steps` | `8` |
| `--max-no-progress-steps` | `2` |
| `--history-budget-chars` | `120000` |
| `--max-tool-output-chars` | `12000` |

### Tools

MiniHarness v0.1.2 引入了轻量工具注册表。Agent 通过 `ToolRegistry` 获取工具、导出 OpenAI tool schema，并在执行前做基础参数校验。

| 工具 | 说明 |
| --- | --- |
| `list_dir` | 列出目录，目录优先，最多返回 500 项 |
| `read_file` | 读取 UTF-8 文本文件，支持行号窗口，并拒绝明显的二进制文件 |
| `write_file` | 整文件写入，存在文件会覆盖，必要时创建父目录 |
| `search_text` | 使用 Python 正则搜索文本文件，最多返回 500 条匹配 |
| `run_shell` | 运行本地 shell 命令，默认 30 秒超时 |
| `todo` | 维护本次运行中的任务列表 |

工具结果统一包含：

```json
{
  "ok": true,
  "output": "tool output",
  "error": null,
  "metadata": {}
}
```

工具参数校验覆盖 `required`、基础 JSON 类型、`minimum`、`maximum` 和 `enum`。校验失败时，工具不会进入自身执行逻辑，而是统一返回 `invalid arguments: ...`。

### Hooks / Trace

MiniHarness v0.2.0 新增了轻量 hooks 观察层，用于让 CLI 用户看到 agent 正在做什么。

- `Agent` 支持注入可选 `hooks`
- `HookDispatcher` 负责安全分发事件；单个 hook 失败不会中断整个运行
- `ConsoleHook` 会把事件格式化成单行文本输出到 stderr
- `--trace` 会在 CLI 中启用 `ConsoleHook`
- 默认不开启 trace，因此不改变既有 stdout 最终答案输出

当前事件覆盖：

- `run.started`
- `step.started`
- `model.completed`
- `tool.started`
- `tool.completed`
- `run.completed`
- `run.failed`

示例：

```powershell
mh --trace --cwd . "总结这个项目"
```

输出效果类似：

```text
[run] started
[step 1] model completed with 2 tool calls
[step 1] tool read_file started {"path":"README.md"}
[step 1] tool read_file completed ok
[run] completed in 1 steps
```

### Runtime Scaffold

MiniHarness v0.2.1 引入了最小系统骨架，用于给未来 memory、权限系统和 skills 留清晰挂点。

- `RuntimePolicy`：表达运行期策略，如 `shell_timeout` 和 `allow_outside_cwd`
- `AgentCapabilities`：表达当前 agent 具备哪些系统能力
- `AgentRuntime`：组合 `cwd`、`session`、`tool_context`、`policy`、`capabilities` 和 `hooks`

这次增量是结构性改进，不改变现有命令使用方式，也不提前实现长期 memory、动态 skills 或审批流。

### Session / Context

每次 `mh "任务"` 都会创建一个新的 session。REPL 模式会在同一进程中复用 session，直到你输入 `/reset` 或退出。session 只在本次进程中存在，不写入磁盘，也不会跨命令持久化。

消息历史使用字符预算做近似裁剪，不做精确 token 计数。裁剪时会保留 system prompt、最新用户消息和完整的 assistant/tool 调用轮次，避免破坏 OpenAI tool message 的 `tool_call_id` 关联。

### Safety

文件工具默认只能访问 `--cwd` 内的路径。可以使用 `--allow-outside-cwd` 放开限制，但不建议在不可信任务中使用。

`run_shell` 不是沙箱。它可以：

- 读取工作目录外的文件
- 打印环境变量
- 访问当前进程可见的凭据
- 访问网络
- 执行破坏性命令

MiniHarness 会拒绝部分明显需要交互输入的项目生成命令，例如 `npm create`、`create-next-app`、`create vite`，避免命令挂起等待输入。但它不能替代 Docker、虚拟机或真正的权限沙箱。

建议先在测试目录中试用：

```powershell
mkdir scratch
mh --cwd .\scratch "创建一个 hello.txt 文件，内容是一行 hello"
```

## 常见命令

```powershell
mh "总结这个项目"
mh
mh --cwd . "搜索 README 中的安装说明"
mh --trace --cwd . "总结这个项目并显示执行轨迹"
mh --verbose --cwd . "阅读项目结构并说明核心模块"
mh --model deepseek-chat --base-url https://api.deepseek.com "总结这个项目"
mh --shell-timeout 120 "运行测试并总结失败原因"
```

## 当前限制

- `write_file` 是整文件覆盖，暂不支持 patch / diff 编辑
- 不做精确 token 计数，只用字符预算近似控制上下文
- 不做长期记忆、上下文压缩、插件系统、subagent 或 MCP
- hooks 当前只用于可观测性，不支持拦截、取消、重试或修改执行流程
- 不支持从配置或文件系统动态加载用户自定义 hook
- runtime scaffold 当前只提供系统层挂点，不提供真实 memory、权限审批或 skills 执行能力
- shell 权限模型较宽，适合本地可信开发环境，不适合直接处理不可信任务
- 不同 OpenAI-compatible provider 的 tool calling 兼容性差异较大，需要按服务商实际行为调试

## 排错

### 404 not found

通常是模型服务配置问题：

```text
OPENAI_BASE_URL=https://api.example.com/v1
OPENAI_MODEL=服务商支持的模型 ID
```

如果服务商文档要求 `/v1`，不要只填域名。

### 缺少 API Key

```text
OPENAI_API_KEY is required
```

检查 `.env` 是否存在，以及当前 shell 是否在项目根目录运行。

### 默认 Python 没有 pip 或 pytest

Windows 优先使用：

```powershell
py -3.12 -m pip install -e .[dev]
py -3.12 -m pytest -v
```

### 模型不调用工具

优先检查：

- 模型是否支持 tool calling
- provider 是否完整兼容 OpenAI Chat Completions tool call 格式
- `OPENAI_MODEL` 是否写成了 provider 真实支持的模型 ID
- `OPENAI_BASE_URL` 是否指向兼容 API，而不是网页端或非 OpenAI 格式接口

## 项目结构

```text
miniharness/
  cli.py            # CLI 入口、参数解析、REPL、--trace 接线
  config.py         # .env / 环境变量 / CLI 配置合并
  model_client.py   # OpenAI-compatible 模型客户端
  agent.py          # Agent loop、tool dispatch、hook 事件发出、runtime 接入
  prompts.py        # system prompt
  policy.py         # RuntimePolicy
  capabilities.py   # AgentCapabilities
  runtime.py        # AgentRuntime 组合层
  hooks.py          # HookEvent / HookDispatcher / ConsoleHook
  session.py        # 本次运行的消息历史
  tools/
    base.py         # ToolContext / ToolResult / Tool 基础协议
    fs.py           # 文件读写和目录列表
    search.py       # 文本搜索
    shell.py        # shell 命令执行
    todo.py         # 任务列表
tests/
```

## 测试

安装开发依赖：

```powershell
py -3.12 -m pip install -e .[dev]
```

运行测试：

```powershell
py -3.12 -m pytest -v
```

当前测试覆盖：

- agent loop 终止、工具调用、错误处理和截断行为
- runtime scaffold 默认值、注入路径和 cwd 一致性
- 文件、搜索、shell、todo 工具
- `.env`、环境变量和 CLI 参数合并
- OpenAI-compatible 响应解析和错误分类
- CLI 参数校验、stdout / stderr 输出边界和 REPL 行为
- hooks 事件发出、dispatcher 安全性和 `--trace` 输出

## 贡献

MiniHarness 的优先级是保持小、清晰、可测试。新增能力时建议遵守：

- 先写清楚 spec 或 plan，再实现
- 新工具必须有单元测试
- 新 provider 支持必须说明它的 tool calling 兼容边界
- 不把大型框架、插件系统或长期记忆直接塞进 v1 核心

## License

当前仓库尚未声明开源许可证。发布前请补充 `LICENSE` 文件，并在本节中写明许可证类型。
