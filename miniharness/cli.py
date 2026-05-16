import argparse
import logging
import sys
from collections.abc import Sequence

from . import __version__
from .agent import Agent, AgentOutcome
from .config import load_config
from .model_client import OpenAIModelClient
from .tools import TOOLS


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
    return Agent(
        model_client=model_client,
        tools=TOOLS,
        cwd=config.cwd,
        max_steps=config.max_steps,
        max_tool_output_chars=config.max_tool_output_chars,
        history_budget_chars=config.history_budget_chars,
        max_no_progress_steps=config.max_no_progress_steps,
        shell_timeout=config.shell_timeout,
        allow_outside_cwd=config.allow_outside_cwd,
    )


def _run_repl(agent: Agent) -> int:
    print("MiniHarness REPL. Type /exit to quit, /reset to clear context.", file=sys.stderr)
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
        if outcome.exit_code != 0:
            return outcome.exit_code


def _print_outcome(outcome: AgentOutcome) -> None:
    if outcome.output:
        print(outcome.output)
    if outcome.error:
        print(outcome.error, file=sys.stderr)
