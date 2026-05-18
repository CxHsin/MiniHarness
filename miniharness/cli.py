import argparse
import logging
import sys
from collections.abc import Sequence

from . import __version__
from .agent import Agent, AgentOutcome
from .capabilities import AgentCapabilities
from .config import load_config
from .hooks import ConsoleHook, HookEvent
from .model_client import OpenAIModelClient
from .policy import RuntimePolicy
from .runtime import AgentRuntime
from .tools import TOOL_REGISTRY


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mh",
        description=(
            "MiniHarness runs local OpenAI-compatible agent tasks. "
            "Warning: shell commands are not sandboxed."
        ),
    )
    parser.add_argument("task", nargs="?", help="task to run; omit to enter REPL")
    parser.add_argument("--cwd", default=".", help="working directory")
    parser.add_argument("--model", default=None, help="OpenAI model override")
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible API base URL override",
    )
    parser.add_argument("--max-steps", type=positive_int, default=8)
    parser.add_argument("--shell-timeout", type=positive_int, default=30)
    parser.add_argument("--max-tool-output-chars", type=positive_int, default=12000)
    parser.add_argument("--history-budget-chars", type=positive_int, default=120000)
    parser.add_argument("--max-no-progress-steps", type=positive_int, default=2)
    parser.add_argument(
        "--log-level",
        choices=["ERROR", "WARNING", "INFO", "DEBUG"],
        default="WARNING",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="print structured execution trace to stderr",
    )
    parser.add_argument(
        "--permission-mode",
        choices=["default", "plan", "auto"],
        default="default",
        help="permission behavior for run_shell: balanced default, conservative plan, or permissive auto",
    )
    parser.add_argument("--allow-outside-cwd", action="store_true")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args)
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(levelname)s:%(name)s:%(message)s",
    )
    if not config.api_key:
        print("OPENAI_API_KEY is required", file=sys.stderr)
        return 2
    try:
        agent = _build_agent(config)
        if args.task:
            outcome = agent.run(args.task)
            _print_outcome(outcome)
            return outcome.exit_code
        return _run_repl(agent)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _build_agent(config) -> Agent:
    model_client = OpenAIModelClient(config.api_key, config.model, config.base_url)
    hooks = [ConsoleHook()] if config.trace else []
    runtime = AgentRuntime.create(
        cwd=config.cwd,
        policy=RuntimePolicy(
            allow_outside_cwd=config.allow_outside_cwd,
            shell_timeout=config.shell_timeout,
            permission_mode=config.permission_mode,
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


def _run_repl(agent: Agent) -> int:
    print("MiniHarness REPL. Type /help for commands.", file=sys.stderr)
    while True:
        try:
            task = input("mh> ").strip()
        except EOFError:
            print("", file=sys.stderr)
            return 0
        if not task:
            continue
        if task in {"/exit", "/quit"}:
            return 0
        if task == "/help":
            _print_repl_help()
            continue
        if task == "/reset":
            agent.reset()
            print("Session reset", file=sys.stderr)
            continue
        if task == "/cwd":
            print(agent.session.cwd, file=sys.stderr)
            continue
        if task.startswith("/"):
            print(f"Unknown command: {task}", file=sys.stderr)
            continue
        outcome = agent.run(task)
        _print_outcome(outcome)


def _print_repl_help() -> None:
    print(
        "\n".join(
            [
                "Commands:",
                "  /help   Show this help",
                "  /cwd    Show current working directory",
                "  /reset  Clear the current session",
                "  /exit   Exit the REPL",
                "  /quit   Exit the REPL",
            ]
        ),
        file=sys.stderr,
    )


def _print_outcome(outcome: AgentOutcome) -> None:
    if outcome.output:
        print(outcome.output)
    if outcome.error:
        print(outcome.error, file=sys.stderr)
