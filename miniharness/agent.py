from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capabilities import AgentCapabilities
from .hooks import AgentHook, HookDispatcher, HookEvent
from .permissions import check_tool_permission
from .model_client import ModelClient, ToolCall
from .policy import RuntimePolicy
from .prompts import build_system_prompt
from .runtime import AgentRuntime
from .session import Session
from .tools.base import BaseTool, ToolRegistry, ToolResult

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
        tools: list[BaseTool] | ToolRegistry,
        cwd: str | Path,
        max_steps: int = 8,
        max_tool_output_chars: int = 12000,
        history_budget_chars: int = 120000,
        max_no_progress_steps: int = 2,
        shell_timeout: int = 30,
        allow_outside_cwd: bool = False,
        hooks: list[AgentHook] | None = None,
        runtime: AgentRuntime | None = None,
    ):
        # During the v0.2.1 transition, cwd is ignored when runtime is provided.
        self.model_client = model_client
        self.tools = tools if isinstance(tools, ToolRegistry) else ToolRegistry(tools)
        self.max_steps = max_steps
        self.max_tool_output_chars = max_tool_output_chars
        self.max_no_progress_steps = max_no_progress_steps
        self.runtime = runtime or AgentRuntime.create(
            cwd=cwd,
            policy=RuntimePolicy(
                allow_outside_cwd=allow_outside_cwd,
                shell_timeout=shell_timeout,
            ),
            capabilities=AgentCapabilities(),
            history_budget_chars=history_budget_chars,
            hooks=hooks,
        )
        self.session = self.runtime.session
        self.context = self.runtime.tool_context
        self._dispatcher = HookDispatcher(self.runtime.hooks)
        self._run_id: str | None = None

    def run(self, task: str) -> AgentOutcome:
        self._run_id = uuid.uuid4().hex
        self._ensure_system_prompt()
        self.session.add_message({"role": "user", "content": task})
        self._emit(
            "run.started",
            None,
            {
                "task": task,
                "max_steps": self.max_steps,
                "model": getattr(self.model_client, "model", "unknown"),
            },
        )
        no_progress_rounds = 0
        steps_used = 0
        try:
            for step in range(self.max_steps):
                steps_used = step + 1
                self._emit(
                    "step.started",
                    step,
                    {"message_count": len(self.session.get_messages())},
                )
                response = self.model_client.complete(
                    self.session.get_messages(),
                    self.tools.to_openai_tools(),
                    tool_choice="auto",
                )
                self._emit_model_completed(response, step, is_continuation=False)
                if response.finish_reason == "length":
                    return self._continue_truncated_final_answer(
                        response.content or "",
                        step,
                        steps_used,
                    )
                if not response.tool_calls:
                    outcome = AgentOutcome(response.content or "", None, 0)
                    self._emit_run_completed(steps_used, used_continuation=False)
                    return outcome

                assistant_message = self._assistant_tool_message(response)
                tool_messages = []
                round_had_progress = False
                for tool_call in response.tool_calls:
                    logger.info("tool call: %s", tool_call.name)
                    self._emit_tool_started(tool_call, step)
                    result = self._execute_tool_call(tool_call)
                    if result.ok and result.output:
                        round_had_progress = True
                    truncated = self._was_truncated(result)
                    result = self._truncate_result(result)
                    self._emit_tool_completed(tool_call, step, result, truncated)
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
                    error = "no progress after repeated tool failures"
                    self._emit_run_failed(steps_used, error)
                    return AgentOutcome("", error, 1)
            error = "maximum agent steps reached"
            self._emit_run_failed(steps_used, error)
            return AgentOutcome("", error, 1)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            self._emit_run_failed(steps_used, str(exc))
            raise

    def _continue_truncated_final_answer(self, partial: str, step: int, steps_used: int) -> AgentOutcome:
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
            self.tools.to_openai_tools(),
            tool_choice="none",
        )
        self._emit_model_completed(response, step, is_continuation=True)
        output = partial + (response.content or "")
        if response.finish_reason == "length":
            error = "model response was truncated after continuation"
            self._emit_run_failed(steps_used, error)
            return AgentOutcome(output, error, 1)
        if response.tool_calls:
            error = "model requested tools during continuation"
            self._emit_run_failed(steps_used, error)
            return AgentOutcome(output, error, 1)
        self._emit_run_completed(steps_used, used_continuation=True)
        return AgentOutcome(output, None, 0)

    def reset(self) -> None:
        self.runtime.session = Session(
            cwd=self.runtime.cwd,
            history_budget_chars=self.runtime.session.history_budget_chars,
        )
        self.session = self.runtime.session

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
        decision = check_tool_permission(
            self.runtime.policy,
            tool_call.name,
            tool_call.arguments,
        )
        if not decision.allowed:
            return ToolResult(False, "", decision.error)
        try:
            return self.tools.execute(tool_call.name, tool_call.arguments, self.context)
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
        if len(marker) >= limit:
            return ToolResult(result.ok, marker[:limit], result.error, result.metadata)
        head_len = max((limit - len(marker)) // 2, 0)
        tail_len = max(limit - len(marker) - head_len, 0)
        truncated = output[:head_len] + marker + output[-tail_len if tail_len else len(output) :]
        return ToolResult(result.ok, truncated, result.error, result.metadata)

    def _emit(self, event_type: str, step: int | None, payload: dict[str, Any]) -> None:
        self._dispatcher.emit(
            HookEvent(
                type=event_type,
                run_id=self._run_id or "",
                step=step,
                payload=payload,
            )
        )

    def _emit_model_completed(self, response, step: int, is_continuation: bool) -> None:
        self._emit(
            "model.completed",
            step,
            {
                "finish_reason": response.finish_reason,
                "tool_call_count": len(response.tool_calls),
                "has_tool_calls": bool(response.tool_calls),
                "has_content": bool(response.content),
                "is_continuation": is_continuation,
            },
        )

    def _emit_tool_started(self, tool_call: ToolCall, step: int) -> None:
        self._emit(
            "tool.started",
            step,
            {
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
                "arguments_summary": json.dumps(tool_call.arguments, ensure_ascii=False)[:200],
            },
        )

    def _emit_tool_completed(
        self,
        tool_call: ToolCall,
        step: int,
        result: ToolResult,
        truncated: bool,
    ) -> None:
        self._emit(
            "tool.completed",
            step,
            {
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
                "ok": result.ok,
                "truncated": truncated,
                "error": result.error,
            },
        )

    def _emit_run_completed(self, steps_used: int, used_continuation: bool) -> None:
        self._emit(
            "run.completed",
            None,
            {
                "steps_used": steps_used,
                "used_continuation": used_continuation,
            },
        )

    def _emit_run_failed(self, steps_used: int, error: str) -> None:
        self._emit(
            "run.failed",
            None,
            {
                "steps_used": steps_used,
                "error": error,
            },
        )

    def _was_truncated(self, result: ToolResult) -> bool:
        return len(result.output) > self.max_tool_output_chars
