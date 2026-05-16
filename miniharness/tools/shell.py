from __future__ import annotations

import subprocess

from .base import Tool, ToolContext, ToolResult

INTERACTIVE_COMMAND_MARKERS = (
    "npm create",
    "pnpm create",
    "yarn create",
    "npx create-",
    "create-next-app",
    "create vite",
)


class RunShellTool(Tool):
    name = "run_shell"
    description = "Run a shell command from the working directory."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "minimum": 1},
        },
        "required": ["command"],
    }

    def execute(self, args: dict, context: ToolContext) -> ToolResult:
        command = args.get("command")
        if not command:
            return ToolResult(False, "", "command is required")
        interactive_reason = self._interactive_command_reason(command)
        if interactive_reason:
            return ToolResult(False, "", interactive_reason, {"interactive": True})
        timeout = int(args.get("timeout") or context.shell_timeout)
        process = None
        try:
            process = subprocess.Popen(
                command,
                cwd=context.cwd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate(timeout=timeout)
            output = self._combine_output(stdout, stderr)
            if process.returncode != 0:
                return ToolResult(
                    False,
                    output,
                    f"command exited with exit code {process.returncode}",
                    {"returncode": process.returncode},
                )
            return ToolResult(True, output, None, {"returncode": process.returncode})
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            output = self._combine_output(exc.stdout, exc.stderr)
            return ToolResult(
                False,
                output,
                f"command timed out after {timeout}s",
                {"timed_out": True},
            )
        except KeyboardInterrupt:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            raise

    @staticmethod
    def _combine_output(stdout, stderr) -> str:
        parts = []
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(stderr)
        return "".join(parts).rstrip()

    @staticmethod
    def _interactive_command_reason(command: str) -> str | None:
        lowered = command.lower()
        if any(marker in lowered for marker in INTERACTIVE_COMMAND_MARKERS):
            return (
                "Command appears to start an interactive project generator. "
                "Run a non-interactive command or provide flags that disable prompts."
            )
        return None
