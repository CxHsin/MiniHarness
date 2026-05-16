from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    parse_error: str | None = None


@dataclass(frozen=True)
class ModelResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = "auto",
    ) -> ModelResponse:
        ...


def parse_chat_completion(response: Any) -> ModelResponse:
    choice = response.choices[0]
    message = choice.message
    tool_calls = []
    for raw_call in getattr(message, "tool_calls", None) or []:
        raw_args = raw_call.function.arguments or "{}"
        parse_error = None
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            arguments = {}
            parse_error = str(exc)
        tool_calls.append(
            ToolCall(
                id=raw_call.id,
                name=raw_call.function.name,
                arguments=arguments,
                parse_error=parse_error,
            )
        )
    return ModelResponse(
        content=getattr(message, "content", None),
        tool_calls=tool_calls,
        finish_reason=getattr(choice, "finish_reason", None),
        metadata={},
    )


def retry_decision(status_code: int | None, error_code: str | None) -> str:
    if status_code in {401, 403}:
        return "fail"
    if error_code == "context_length_exceeded":
        return "fail"
    if status_code == 429:
        return "rate_limit"
    if status_code is not None and status_code >= 500:
        return "retry"
    if error_code == "timeout":
        return "retry"
    return "fail"


def extract_error_code(exc: Exception) -> str | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        value = body.get("code")
        return value if isinstance(value, str) else None
    return None


class OpenAIModelClient:
    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        self.model = model
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = "auto",
    ) -> ModelResponse:
        attempt = 0
        while True:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools or None,
                    tool_choice=tool_choice if tools else None,
                )
                return parse_chat_completion(response)
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                error_code = extract_error_code(exc)
                decision = retry_decision(status_code, error_code)
                if decision == "rate_limit" and attempt < 3:
                    time.sleep(5 * (2**attempt))
                    attempt += 1
                    continue
                if decision == "retry" and attempt < 2:
                    time.sleep(1 * (2**attempt))
                    attempt += 1
                    continue
                raise
