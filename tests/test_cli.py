import pytest

import miniharness.cli as cli
from miniharness.cli import build_parser


def test_parser_accepts_one_shot_task():
    parser = build_parser()

    args = parser.parse_args(["summarize this project"])

    assert args.task == "summarize this project"
    assert args.max_steps == 8
    assert args.history_budget_chars == 120000
    assert args.log_level == "WARNING"
    assert args.base_url is None


def test_parser_verbose_sets_log_level_info():
    parser = build_parser()

    args = parser.parse_args(["--verbose", "summarize"])

    assert args.verbose is True


def test_parser_accepts_trace_flag():
    parser = build_parser()

    args = parser.parse_args(["--trace", "summarize"])

    assert args.trace is True


def test_parser_rejects_negative_max_steps():
    parser = build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--max-steps", "-1", "summarize"])

    assert exc.value.code == 2


def test_parser_rejects_invalid_log_level():
    parser = build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--log-level", "TRACE", "summarize"])

    assert exc.value.code == 2


def test_main_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])

    assert exc.value.code == 0
    assert "mh 0.2.2" in capsys.readouterr().out


def test_main_requires_api_key_for_task(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    code = cli.main(["--cwd", str(tmp_path), "summarize"])

    assert code == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_main_prints_final_answer_to_stdout(monkeypatch, tmp_path, capsys):
    captured_client_args = {}
    captured_agent_kwargs = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured_agent_kwargs.update(kwargs)

        def run(self, task):
            return cli.AgentOutcome(output="final answer", error=None, exit_code=0)

    def fake_model_client(api_key, model, base_url=None):
        captured_client_args.update(
            {"api_key": api_key, "model": model, "base_url": base_url}
        )
        return object()

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(cli, "OpenAIModelClient", fake_model_client)
    monkeypatch.setattr(cli, "Agent", FakeAgent)

    code = cli.main(
        [
            "--cwd",
            str(tmp_path),
            "--model",
            "qwen",
            "--base-url",
            "http://localhost:11434/v1",
            "summarize",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == "final answer\n"
    assert captured_client_args == {
        "api_key": "key",
        "model": "qwen",
        "base_url": "http://localhost:11434/v1",
    }
    assert "hooks" not in captured_agent_kwargs
    assert captured_agent_kwargs["runtime"].hooks == []


def test_main_trace_wires_console_hook_and_keeps_stdout_clean(monkeypatch, tmp_path, capsys):
    class FakeAgent:
        def __init__(self, **kwargs):
            self._hook = kwargs["runtime"].hooks[0]

        def run(self, task):
            self._hook.handle(
                cli.HookEvent(
                    type="run.started",
                    run_id="abc",
                    step=None,
                    payload={"task": task, "max_steps": 8, "model": "fake-model"},
                )
            )
            self._hook.handle(
                cli.HookEvent(
                    type="run.completed",
                    run_id="abc",
                    step=None,
                    payload={"steps_used": 1, "used_continuation": False},
                )
            )
            return cli.AgentOutcome(output="final answer", error=None, exit_code=0)

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        cli, "OpenAIModelClient", lambda api_key, model, base_url=None: object()
    )
    monkeypatch.setattr(cli, "Agent", FakeAgent)

    code = cli.main(["--trace", "--cwd", str(tmp_path), "summarize"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == "final answer\n"
    assert "[run] started" in captured.err
    assert "[run] run.completed" not in captured.err


def test_main_builds_runtime_and_passes_it_to_agent(monkeypatch, tmp_path, capsys):
    captured_agent_kwargs = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured_agent_kwargs.update(kwargs)

        def run(self, task):
            return cli.AgentOutcome(output="final answer", error=None, exit_code=0)

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        cli, "OpenAIModelClient", lambda api_key, model, base_url=None: object()
    )
    monkeypatch.setattr(cli, "Agent", FakeAgent)

    code = cli.main(["--trace", "--cwd", str(tmp_path), "summarize"])

    assert code == 0
    runtime = captured_agent_kwargs["runtime"]
    assert runtime.cwd == tmp_path.resolve()
    assert runtime.policy.shell_timeout == 30
    assert runtime.policy.allow_outside_cwd is False
    assert runtime.session.history_budget_chars == 120000
    assert len(runtime.hooks) == 1
    assert "hooks" not in captured_agent_kwargs


def test_runtime_mapping_keeps_policy_session_and_loop_fields_separate(
    monkeypatch, tmp_path
):
    captured_agent_kwargs = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured_agent_kwargs.update(kwargs)

        def run(self, task):
            return cli.AgentOutcome(output="done", error=None, exit_code=0)

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        cli, "OpenAIModelClient", lambda api_key, model, base_url=None: object()
    )
    monkeypatch.setattr(cli, "Agent", FakeAgent)

    cli.main(
        [
            "--cwd",
            str(tmp_path),
            "--shell-timeout",
            "41",
            "--history-budget-chars",
            "765",
            "--max-steps",
            "9",
            "--max-tool-output-chars",
            "4321",
            "--max-no-progress-steps",
            "4",
            "--allow-outside-cwd",
            "summarize",
        ]
    )

    runtime = captured_agent_kwargs["runtime"]
    assert runtime.policy.shell_timeout == 41
    assert runtime.policy.allow_outside_cwd is True
    assert runtime.session.history_budget_chars == 765
    assert captured_agent_kwargs["max_steps"] == 9
    assert captured_agent_kwargs["max_tool_output_chars"] == 4321
    assert captured_agent_kwargs["max_no_progress_steps"] == 4


def test_main_without_task_enters_repl(monkeypatch, tmp_path, capsys):
    tasks = []

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, task):
            tasks.append(task)
            return cli.AgentOutcome(output=f"answer: {task}", error=None, exit_code=0)

        def reset(self):
            tasks.append("<reset>")

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        cli, "OpenAIModelClient", lambda api_key, model, base_url=None: object()
    )
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    inputs = iter(["first task", "", "/reset", "second task", "/exit"])

    code = cli.main(["--cwd", str(tmp_path)])
    captured = capsys.readouterr()

    assert code == 0
    assert tasks == ["first task", "<reset>", "second task"]
    assert "answer: first task" in captured.out
    assert "answer: second task" in captured.out
    assert "Session reset" in captured.err


def test_repl_help_prints_commands_and_continues(monkeypatch, tmp_path, capsys):
    tasks = []

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, task):
            tasks.append(task)
            return cli.AgentOutcome(output=f"answer: {task}", error=None, exit_code=0)

        def reset(self):
            raise AssertionError("reset should not be called")

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        cli, "OpenAIModelClient", lambda api_key, model, base_url=None: object()
    )
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    inputs = iter(["/help", "next task", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    code = cli.main(["--cwd", str(tmp_path)])
    captured = capsys.readouterr()

    assert code == 0
    assert tasks == ["next task"]
    assert "/reset" in captured.err
    assert "/cwd" in captured.err
    assert "answer: next task" in captured.out


def test_repl_keeps_running_after_agent_error(monkeypatch, tmp_path, capsys):
    tasks = []

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, task):
            tasks.append(task)
            if task == "bad task":
                return cli.AgentOutcome(output="", error="failed once", exit_code=1)
            return cli.AgentOutcome(output="recovered", error=None, exit_code=0)

        def reset(self):
            pass

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        cli, "OpenAIModelClient", lambda api_key, model, base_url=None: object()
    )
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    inputs = iter(["bad task", "good task", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    code = cli.main(["--cwd", str(tmp_path)])
    captured = capsys.readouterr()

    assert code == 0
    assert tasks == ["bad task", "good task"]
    assert "failed once" in captured.err
    assert "recovered" in captured.out


def test_main_handles_keyboard_interrupt(monkeypatch, tmp_path, capsys):
    class InterruptingAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, task):
            raise KeyboardInterrupt

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        cli, "OpenAIModelClient", lambda api_key, model, base_url=None: object()
    )
    monkeypatch.setattr(cli, "Agent", InterruptingAgent)

    code = cli.main(["--cwd", str(tmp_path), "summarize"])

    assert code == 1
    assert "Interrupted" in capsys.readouterr().err


def test_main_reports_model_runtime_errors_without_traceback(monkeypatch, tmp_path, capsys):
    class FailingAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, task):
            raise RuntimeError("provider returned 404 not found")

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        cli, "OpenAIModelClient", lambda api_key, model, base_url=None: object()
    )
    monkeypatch.setattr(cli, "Agent", FailingAgent)

    code = cli.main(["--cwd", str(tmp_path), "summarize"])

    captured = capsys.readouterr()
    assert code == 1
    assert "provider returned 404 not found" in captured.err
    assert "Traceback" not in captured.err
