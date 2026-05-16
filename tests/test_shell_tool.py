import sys
import subprocess

from miniharness.tools.shell import RunShellTool


def test_run_shell_success(fake_tool_context):
    result = RunShellTool().execute(
        {"command": f'{sys.executable} -c "print(123)"'},
        fake_tool_context,
    )

    assert result.ok is True
    assert "123" in result.output
    assert result.metadata["returncode"] == 0


def test_run_shell_non_zero_preserves_output(fake_tool_context):
    result = RunShellTool().execute(
        {"command": f'{sys.executable} -c "print(123); raise SystemExit(7)"'},
        fake_tool_context,
    )

    assert result.ok is False
    assert "123" in result.output
    assert "exit code 7" in result.error
    assert result.metadata["returncode"] == 7


def test_run_shell_timeout(fake_tool_context):
    result = RunShellTool().execute(
        {"command": f'{sys.executable} -c "import time; time.sleep(10)"', "timeout": 1},
        fake_tool_context,
    )

    assert result.ok is False
    assert "timed out" in result.error
    assert result.metadata["timed_out"] is True


def test_run_shell_terminates_child_on_keyboard_interrupt(monkeypatch, fake_tool_context):
    class InterruptingProcess:
        def __init__(self, *args, **kwargs):
            self.terminated = False
            created.append(self)

        def communicate(self, timeout=None):
            raise KeyboardInterrupt

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    created = []
    monkeypatch.setattr(subprocess, "Popen", InterruptingProcess)

    try:
        RunShellTool().execute({"command": "long-running"}, fake_tool_context)
    except KeyboardInterrupt:
        pass

    assert created[0].terminated is True


def test_run_shell_rejects_interactive_command(fake_tool_context):
    result = RunShellTool().execute(
        {"command": "npm create vite@latest"},
        fake_tool_context,
    )

    assert result.ok is False
    assert "interactive" in result.error.lower()
