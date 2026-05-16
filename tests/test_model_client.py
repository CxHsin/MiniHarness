from types import SimpleNamespace

from miniharness.model_client import (
    ModelResponse,
    OpenAIModelClient,
    ToolCall,
    extract_error_code,
    parse_chat_completion,
    retry_decision,
)
from miniharness.prompts import build_system_prompt


def test_parse_chat_completion_extracts_tool_calls():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(
                                name="read_file",
                                arguments='{"path":"README.md"}',
                            ),
                        )
                    ],
                ),
            )
        ]
    )

    parsed = parse_chat_completion(response)

    assert parsed == ModelResponse(
        content=None,
        tool_calls=[ToolCall(id="call_1", name="read_file", arguments={"path": "README.md"})],
        finish_reason="tool_calls",
        metadata={},
    )


def test_parse_chat_completion_marks_invalid_tool_json():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_bad",
                            function=SimpleNamespace(name="read_file", arguments="{bad"),
                        )
                    ],
                ),
            )
        ]
    )

    parsed = parse_chat_completion(response)

    assert parsed.tool_calls[0].id == "call_bad"
    assert parsed.tool_calls[0].name == "read_file"
    assert parsed.tool_calls[0].arguments == {}
    assert parsed.tool_calls[0].parse_error is not None


def test_retry_decision_classifies_errors():
    assert retry_decision(status_code=401, error_code=None) == "fail"
    assert retry_decision(status_code=400, error_code="context_length_exceeded") == "fail"
    assert retry_decision(status_code=429, error_code=None) == "rate_limit"
    assert retry_decision(status_code=500, error_code=None) == "retry"
    assert retry_decision(status_code=None, error_code="timeout") == "retry"


def test_extract_error_code_handles_non_dict_body():
    error = SimpleNamespace(body="not a dict")

    assert extract_error_code(error) is None


def test_system_prompt_mentions_v1_limits():
    prompt = build_system_prompt()

    assert "whole-file" in prompt
    assert "truncated" in prompt
    assert "shell commands" in prompt


def test_openai_model_client_accepts_base_url(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("miniharness.model_client.OpenAI", FakeOpenAI)

    OpenAIModelClient(api_key="key", model="qwen", base_url="http://localhost:11434/v1")

    assert captured == {
        "api_key": "key",
        "base_url": "http://localhost:11434/v1",
    }
