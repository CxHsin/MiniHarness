import json

from tests.conftest import FakeModelClient

from miniharness.agent import Agent
from miniharness.model_client import ModelResponse, ToolCall
from miniharness.tools.base import Tool, ToolContext, ToolResult


class EchoTool(Tool):
    name = "echo"
    description = "echo input"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

    def execute(self, args, context: ToolContext) -> ToolResult:
        text = args.get("text", "")
        if text == "fail":
            return ToolResult(False, "", "failed on purpose")
        return ToolResult(True, text, None)


def test_agent_returns_final_answer_without_tool_calls(tmp_path):
    model = FakeModelClient([ModelResponse(content="done", finish_reason="stop")])
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    assert outcome.output == "done"


def test_agent_reuses_session_across_runs_without_duplicate_system_prompt(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(content="first", finish_reason="stop"),
            ModelResponse(content="second", finish_reason="stop"),
        ]
    )
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    agent.run("hello")
    agent.run("continue")

    messages = model.calls[1]["messages"]
    assert [message["role"] for message in messages].count("system") == 1
    assert [message["content"] for message in messages if message["role"] == "user"] == [
        "hello",
        "continue",
    ]


def test_agent_reset_clears_previous_conversation(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(content="first", finish_reason="stop"),
            ModelResponse(content="second", finish_reason="stop"),
        ]
    )
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    agent.run("hello")
    agent.reset()
    agent.run("fresh")

    messages = model.calls[1]["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[-1]["content"] == "fresh"


def test_agent_length_finish_reason_exits_non_zero(tmp_path):
    model = FakeModelClient([ModelResponse(content="partial", finish_reason="length")])
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    outcome = agent.run("hello")

    assert outcome.exit_code == 1
    assert "truncated" in outcome.error


def test_agent_serializes_tool_result_as_json_content(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[ToolCall(id="call_1", name="echo", arguments={"text": "hi"})],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    tool_message = model.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_1"
    assert json.loads(tool_message["content"]) == {
        "ok": True,
        "output": "hi",
        "error": None,
        "metadata": {},
    }


def test_agent_executes_all_tool_calls_despite_partial_failure(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(id="call_1", name="echo", arguments={"text": "fail"}),
                    ToolCall(id="call_2", name="echo", arguments={"text": "ok"}),
                ],
            ),
            ModelResponse(content="recovered", finish_reason="stop"),
        ]
    )
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    outcome = agent.run("hello")

    assert outcome.output == "recovered"
    tool_messages = [m for m in model.calls[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["call_1", "call_2"]


def test_agent_stops_after_repeated_no_progress(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[ToolCall(id="call_1", name="echo", arguments={"text": "fail"})],
            ),
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[ToolCall(id="call_2", name="echo", arguments={"text": "fail"})],
            ),
        ]
    )
    agent = Agent(
        model_client=model,
        tools=[EchoTool()],
        cwd=tmp_path,
        max_no_progress_steps=2,
    )

    outcome = agent.run("hello")

    assert outcome.exit_code == 1
    assert "no progress" in outcome.error


def test_agent_truncates_tool_output_with_marker(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(id="call_1", name="echo", arguments={"text": "abcdefghij"})
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    agent = Agent(
        model_client=model,
        tools=[EchoTool()],
        cwd=tmp_path,
        max_tool_output_chars=8,
    )

    agent.run("hello")

    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert "output truncated at 8 chars" in content["output"]
