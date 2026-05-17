from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model_client import ModelClient, ToolCall
from .prompts import build_system_prompt
from .session import Session
from .tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentOutcome:
    output: str
    error: str | None
    exit_code: int


class Agent:
    def __init__(
        self,
        model_client: ModelClient,
        tools: list[BaseTool],
        cwd: str | Path,
        max_steps: int = 8,
        max_tool_output_chars: int = 12000,
        history_budget_chars: int = 120000,
        max_no_progress_steps: int = 2,
        shell_timeout: int = 30,
        allow_outside_cwd: bool = False,
    ):
        self.model_client = model_client
        self.tools = {tool.name: tool for tool in tools}
        self.max_steps = max_steps
        self.max_tool_output_chars = max_tool_output_chars
        self.max_no_progress_steps = max_no_progress_steps
        self.session = Session(cwd=cwd, history_budget_chars=history_budget_chars)
        self._history_budget_chars = history_budget_chars
        self.context = ToolContext(
            cwd=Path(cwd),
            allow_outside_cwd=allow_outside_cwd,
            shell_timeout=shell_timeout,
        )

    def run(self, task: str) -> AgentOutcome:
        self._ensure_system_prompt()
        self.session.add_message({"role": "user", "content": task})
        no_progress_rounds = 0
        for _step in range(self.max_steps):
            response = self.model_client.complete(
                self.session.get_messages(),
                [tool.to_openai_tool() for tool in self.tools.values()],
                tool_choice="auto",
            )
            if response.finish_reason == "length":
                return self._continue_truncated_final_answer(response.content or "")
            if not response.tool_calls:
                return AgentOutcome(response.content or "", None, 0)

            assistant_message = self._assistant_tool_message(response)
            tool_messages = []
            round_had_progress = False
            for tool_call in response.tool_calls:
                logger.info("tool call: %s", tool_call.name)
                result = self._execute_tool_call(tool_call)
                if result.ok and result.output:
                    round_had_progress = True
                result = self._truncate_result(result)
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result.to_dict(), ensure_ascii=False),
                    }
                )
            self.session.add_turn([assistant_message, *tool_messages])
            if round_had_progress:
                no_progress_rounds = 0
            else:
                no_progress_rounds += 1
            if no_progress_rounds >= self.max_no_progress_steps:
                return AgentOutcome("", "no progress after repeated tool failures", 1)
        return AgentOutcome("", "maximum agent steps reached", 1)

    def _continue_truncated_final_answer(self, partial: str) -> AgentOutcome:
        self.session.add_turn(
            [
                {"role": "assistant", "content": partial},
                {
                    "role": "user",
                    "content": (
                        "Continue the previous answer from exactly where it stopped. "
                        "Do not repeat text that was already written."
                    ),
                },
            ]
        )
        response = self.model_client.complete(
            self.session.get_messages(),
            [tool.to_openai_tool() for tool in self.tools.values()],
            tool_choice="none",
        )
        output = partial + (response.content or "")
        if response.finish_reason == "length":
            return AgentOutcome(output, "model response was truncated after continuation", 1)
        if response.tool_calls:
            return AgentOutcome(output, "model requested tools during continuation", 1)
        return AgentOutcome(output, None, 0)

    def reset(self) -> None:
        self.session = Session(
            cwd=self.session.cwd,
            history_budget_chars=self._history_budget_chars,
        )

    def _ensure_system_prompt(self) -> None:
        messages = self.session.get_messages()
        if messages and messages[0].get("role") == "system":
            return
        self.session.add_message({"role": "system", "content": build_system_prompt()})

    def _assistant_tool_message(self, response) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": response.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in response.tool_calls
            ],
        }

    def _execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        if tool_call.parse_error:
            return ToolResult(False, "", f"invalid tool arguments: {tool_call.parse_error}")
        tool = self.tools.get(tool_call.name)
        if tool is None:
            return ToolResult(False, "", f"unknown tool: {tool_call.name}")
        try:
            return tool.execute(tool_call.arguments, self.context)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            return ToolResult(False, "", str(exc))

    def _truncate_result(self, result: ToolResult) -> ToolResult:
        output = result.output
        limit = self.max_tool_output_chars
        if len(output) <= limit:
            return result
        omitted = len(output) - limit
        marker = f"\n... [output truncated at {limit} chars, {omitted} characters omitted] ...\n"
        head_len = max((limit - len(marker)) // 2, 0)
        tail_len = max(limit - len(marker) - head_len, 0)
        truncated = output[:head_len] + marker + output[-tail_len if tail_len else len(output) :]
        return ToolResult(result.ok, truncated, result.error)
