import json
import pytest

from miniharness.approvals import ApprovalAction, ApprovalDecision, ApprovalRequest
from tests.conftest import FakeModelClient

from miniharness import agent as agent_module
from miniharness.agent import Agent
from miniharness.capabilities import AgentCapabilities
from miniharness.hooks import HookEvent
from miniharness.model_client import ModelResponse, ToolCall
from miniharness.policy import PermissionMode, RuntimePolicy
from miniharness.permissions import PermissionAction, PermissionDecision
from miniharness.runtime import AgentRuntime
from miniharness.tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from miniharness.tools.shell import RunShellTool


class EchoTool(Tool):
    name = "echo"
    description = "echo input"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

    def execute(self, args, context: ToolContext) -> ToolResult:
        text = args.get("text", "")
        if text == "fail":
            return ToolResult(False, "", "failed on purpose")
        return ToolResult(True, text, None)


class MetadataEchoTool(Tool):
    name = "metadata_echo"
    description = "echo input with metadata"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

    def execute(self, args, context: ToolContext) -> ToolResult:
        text = args.get("text", "")
        return ToolResult(True, text, None, {"source": "metadata_echo", "size": len(text)})


class RecordingHook:
    def __init__(self):
        self.events: list[HookEvent] = []

    def handle(self, event: HookEvent) -> None:
        self.events.append(event)


class RecordingApprovalHandler:
    def __init__(self, decision: ApprovalDecision):
        self.decision = decision
        self.requests: list[ApprovalRequest] = []

    def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return self.decision


class MutatingRejectApprovalHandler:
    def __init__(self):
        self.requests: list[ApprovalRequest] = []

    def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        request.arguments["command"] = "echo mutated"
        request.metadata["permission_mode"] = "mutated"
        return ApprovalDecision(
            action=ApprovalAction.REJECT,
            reason="approval_not_available",
            message="custom reject message",
        )


class MutatingApproveApprovalHandler:
    def __init__(self):
        self.requests: list[ApprovalRequest] = []

    def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        request.arguments["command"] = "echo mutated"
        request.metadata["permission_mode"] = "mutated"
        return ApprovalDecision(
            action=ApprovalAction.APPROVE,
            reason="approved_for_test",
        )


class NestedMutatingRejectApprovalHandler:
    def __init__(self):
        self.requests: list[ApprovalRequest] = []

    def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        request.arguments["context"]["files"].append("mutated")
        request.metadata["risk_tags"][1]["nested"].append("mutated")
        return ApprovalDecision(
            action=ApprovalAction.REJECT,
            reason="approval_not_available",
            message="nested custom reject message",
        )


class NestedMutatingApproveApprovalHandler:
    def __init__(self):
        self.requests: list[ApprovalRequest] = []

    def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        request.arguments["context"]["files"].append("mutated")
        request.metadata["risk_tags"][1]["nested"].append("mutated")
        return ApprovalDecision(
            action=ApprovalAction.APPROVE,
            reason="approved_for_test",
        )


class FailingExecuteRegistry(ToolRegistry):
    def execute(self, name: str, args: dict, context: ToolContext) -> ToolResult:
        raise AssertionError("registry execute should not be reached")


def test_agent_returns_final_answer_without_tool_calls(tmp_path):
    model = FakeModelClient([ModelResponse(content="done", finish_reason="stop")])
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    assert outcome.output == "done"


def test_agent_builds_default_runtime_when_not_provided(tmp_path):
    model = FakeModelClient([ModelResponse(content="done", finish_reason="stop")])
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    assert agent.runtime.cwd == tmp_path.resolve()
    assert agent.runtime.policy == RuntimePolicy()
    assert agent.runtime.capabilities == AgentCapabilities()
    assert agent.runtime.session.cwd == tmp_path.resolve()
    assert agent.runtime.tool_context.cwd == tmp_path.resolve()


def test_agent_uses_provided_runtime_and_reset_rebuilds_session_only(tmp_path):
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(shell_timeout=77, allow_outside_cwd=True),
        capabilities=AgentCapabilities(),
        history_budget_chars=456,
    )
    original_tool_context = runtime.tool_context
    original_policy = runtime.policy
    original_capabilities = runtime.capabilities
    original_session = runtime.session

    model = FakeModelClient([ModelResponse(content="done", finish_reason="stop")])
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path, runtime=runtime)

    assert agent.runtime is runtime
    assert agent.session is original_session

    agent.reset()

    assert agent.runtime.session is not original_session
    assert agent.runtime.session.cwd == tmp_path.resolve()
    assert agent.runtime.session.history_budget_chars == 456
    assert agent.runtime.tool_context is original_tool_context
    assert agent.runtime.policy is original_policy
    assert agent.runtime.capabilities is original_capabilities


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


def test_agent_continues_once_when_final_answer_is_truncated(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(content="partial ", finish_reason="length"),
            ModelResponse(content="answer", finish_reason="stop"),
        ]
    )
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    assert outcome.output == "partial answer"
    assert model.calls[1]["messages"][-1]["role"] == "user"
    assert "Continue the previous answer" in model.calls[1]["messages"][-1]["content"]


def test_agent_reports_error_when_continuation_is_still_truncated(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(content="partial ", finish_reason="length"),
            ModelResponse(content="answer", finish_reason="length"),
        ]
    )
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path)

    outcome = agent.run("hello")

    assert outcome.exit_code == 1
    assert outcome.output == "partial answer"
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


def test_agent_accepts_tool_registry_and_validates_arguments(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[ToolCall(id="call_1", name="echo", arguments={"text": 123})],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    agent = Agent(model_client=model, tools=ToolRegistry([EchoTool()]), cwd=tmp_path)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is False
    assert "invalid arguments" in content["error"]


def test_agent_denies_shell_when_runtime_policy_disables_shell(tmp_path):
    recorder = RecordingHook()
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments={"command": "echo hello"},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(shell_enabled=False),
        capabilities=AgentCapabilities(),
        hooks=[recorder],
    )
    agent = Agent(
        model_client=model,
        tools=[EchoTool()],
        cwd=tmp_path,
        runtime=runtime,
    )

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    tool_completed = [event for event in recorder.events if event.type == "tool.completed"][0]
    assert tool_completed.payload["ok"] is False
    assert "disabled by runtime policy" in tool_completed.payload["error"]
    assert [event.type for event in recorder.events] == [
        "run.started",
        "step.started",
        "model.completed",
        "tool.started",
        "tool.completed",
        "step.started",
        "model.completed",
        "run.completed",
    ]
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is False
    assert "disabled by runtime policy" in content["error"]


def test_agent_denied_shell_does_not_fall_through_to_registry_execute(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments={"command": "echo hello"},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(shell_enabled=False),
        capabilities=AgentCapabilities(),
    )
    agent = Agent(
        model_client=model,
        tools=FailingExecuteRegistry([EchoTool()]),
        cwd=tmp_path,
        runtime=runtime,
    )

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is False
    assert "disabled by runtime policy" in content["error"]


def test_agent_routes_default_mode_ambiguous_shell_to_approval_required(tmp_path):
    recorder = RecordingHook()
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments={"command": "echo hello > out.txt"},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        capabilities=AgentCapabilities(),
        hooks=[recorder],
    )
    agent = Agent(model_client=model, tools=[RunShellTool()], cwd=tmp_path, runtime=runtime)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is False
    assert "requires user approval" in content["error"]
    assert content["metadata"]["permission_mode"] == "default"
    tool_completed = [event for event in recorder.events if event.type == "tool.completed"][0]
    assert tool_completed.payload["ok"] is False


def test_agent_routes_ask_user_through_approval_handler(tmp_path):
    handler = RecordingApprovalHandler(
        ApprovalDecision(
            action=ApprovalAction.REJECT,
            reason="approval_not_available",
            message="tool run_shell requires user approval in the current permission mode",
        )
    )
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments={"command": "echo hello > out.txt"},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        capabilities=AgentCapabilities(),
        approval_handler=handler,
    )
    agent = Agent(
        model_client=model,
        tools=[RunShellTool()],
        cwd=tmp_path,
        runtime=runtime,
    )

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    assert len(handler.requests) == 1
    assert handler.requests[0] == ApprovalRequest(
        tool_name="run_shell",
        arguments={"command": "echo hello > out.txt"},
        reason="approval_required",
        message="tool run_shell requires user approval in the current permission mode",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "default",
            "risk_tags": ["shell_exec"],
            "rule": "mode_fallback",
        },
    )


def test_agent_rejected_approval_does_not_fall_through_to_registry_execute(tmp_path):
    handler = MutatingRejectApprovalHandler()
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments={"command": "echo hello > out.txt"},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        capabilities=AgentCapabilities(),
        approval_handler=handler,
    )
    agent = Agent(
        model_client=model,
        tools=FailingExecuteRegistry([RunShellTool()]),
        cwd=tmp_path,
        runtime=runtime,
    )

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is False
    assert content["error"] == "custom reject message"
    assert content["metadata"] == {
        "tool_name": "run_shell",
        "permission_mode": "default",
        "risk_tags": ["shell_exec"],
        "rule": "mode_fallback",
    }
    assert len(handler.requests) == 1


def test_agent_executes_tool_when_approval_handler_approves(tmp_path):
    handler = MutatingApproveApprovalHandler()
    model = FakeModelClient(
        [
                ModelResponse(
                    content=None,
                    finish_reason="tool_calls",
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="run_shell",
                            arguments={"command": "echo original"},
                        )
                    ],
                ),
                ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        capabilities=AgentCapabilities(),
        approval_handler=handler,
    )
    agent = Agent(
        model_client=model,
        tools=[RunShellTool()],
        cwd=tmp_path,
        runtime=runtime,
    )

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is True
    assert content["output"] == "original"
    assert content["metadata"]["returncode"] == 0
    assert len(handler.requests) == 1


def test_agent_rejected_approval_copies_nested_arguments_and_metadata(tmp_path, monkeypatch):
    handler = NestedMutatingRejectApprovalHandler()
    tool_arguments = {
        "command": "echo hello > out.txt",
        "context": {"files": ["original"]},
    }
    permission_metadata = {
        "tool_name": "run_shell",
        "permission_mode": "default",
        "risk_tags": ["shell_exec", {"nested": ["read_only"]}],
        "rule": "mode_fallback",
    }
    monkeypatch.setattr(
        agent_module,
        "check_tool_permission",
        lambda policy, tool_name, args: PermissionDecision(
            action=PermissionAction.ASK_USER,
            reason="approval_required",
            source="fallback",
            message="tool run_shell requires user approval in the current permission mode",
            metadata=permission_metadata,
        ),
    )
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments=tool_arguments,
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        capabilities=AgentCapabilities(),
        approval_handler=handler,
    )
    agent = Agent(
        model_client=model,
        tools=[RunShellTool()],
        cwd=tmp_path,
        runtime=runtime,
    )

    # Replace the default decision payload with one carrying nested metadata.
    handler.decision = ApprovalDecision(
        action=ApprovalAction.REJECT,
        reason="approval_not_available",
        message="nested custom reject message",
    )
    # The permission layer still controls the request payload; we mutate only via the handler.
    # Directly patching the expected permission metadata isn't possible here, so the approval
    # request mutation proof relies on the copied request object preserving the original dicts.
    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is False
    assert content["error"] == "nested custom reject message"
    assert tool_arguments["context"]["files"] == ["original"]
    assert permission_metadata["risk_tags"][1]["nested"] == ["read_only"]
    assert content["metadata"] == permission_metadata
    assert len(handler.requests) == 1


def test_agent_approval_handler_cannot_mutate_nested_tool_arguments_before_execution(tmp_path, monkeypatch):
    handler = NestedMutatingApproveApprovalHandler()
    tool_arguments = {
        "command": "echo original",
        "context": {"files": ["original"]},
    }
    permission_metadata = {
        "tool_name": "run_shell",
        "permission_mode": "default",
        "risk_tags": ["shell_exec", {"nested": ["read_only"]}],
        "rule": "mode_fallback",
    }
    monkeypatch.setattr(
        agent_module,
        "check_tool_permission",
        lambda policy, tool_name, args: PermissionDecision(
            action=PermissionAction.ASK_USER,
            reason="approval_required",
            source="fallback",
            message="tool run_shell requires user approval in the current permission mode",
            metadata=permission_metadata,
        ),
    )
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments=tool_arguments,
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        capabilities=AgentCapabilities(),
        approval_handler=handler,
    )
    agent = Agent(
        model_client=model,
        tools=[RunShellTool()],
        cwd=tmp_path,
        runtime=runtime,
    )

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is True
    assert content["output"] == "original"
    assert tool_arguments["context"]["files"] == ["original"]
    assert permission_metadata["risk_tags"][1]["nested"] == ["read_only"]
    assert len(handler.requests) == 1


def test_agent_executes_safe_shell_command_in_plan_mode(tmp_path):
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_shell",
                        arguments={"command": "dir"},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(permission_mode=PermissionMode.PLAN),
        capabilities=AgentCapabilities(),
    )
    agent = Agent(model_client=model, tools=[RunShellTool()], cwd=tmp_path, runtime=runtime)

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert content["ok"] is True
    assert content["metadata"]["returncode"] == 0


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
    long_text = "abcdefghij" * 20
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(id="call_1", name="echo", arguments={"text": long_text})
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    agent = Agent(
        model_client=model,
        tools=[EchoTool()],
        cwd=tmp_path,
        max_tool_output_chars=80,
    )

    agent.run("hello")

    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert "output truncated at 80 chars" in content["output"]


def test_agent_truncated_tool_output_never_exceeds_limit(tmp_path):
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
    assert len(content["output"]) <= 8


def test_agent_truncation_preserves_tool_metadata(tmp_path):
    long_text = "abcdefghij" * 20
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="metadata_echo",
                        arguments={"text": long_text},
                    )
                ],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    agent = Agent(
        model_client=model,
        tools=[MetadataEchoTool()],
        cwd=tmp_path,
        max_tool_output_chars=8,
    )

    agent.run("hello")

    content = json.loads(model.calls[1]["messages"][-1]["content"])
    assert len(content["output"]) <= 8
    assert content["metadata"] == {"source": "metadata_echo", "size": len(long_text)}


def test_agent_emits_events_for_tool_run(tmp_path):
    recorder = RecordingHook()
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
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path, hooks=[recorder])

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    assert [event.type for event in recorder.events] == [
        "run.started",
        "step.started",
        "model.completed",
        "tool.started",
        "tool.completed",
        "step.started",
        "model.completed",
        "run.completed",
    ]
    assert recorder.events[0].payload["task"] == "hello"
    assert recorder.events[0].payload["max_steps"] == 8
    assert recorder.events[0].payload["model"] == "unknown"
    assert recorder.events[2].payload["has_tool_calls"] is True
    assert recorder.events[4].payload["ok"] is True
    assert recorder.events[-1].payload["steps_used"] == 2
    assert recorder.events[-1].payload["used_continuation"] is False


def test_agent_emits_failed_tool_event_for_invalid_arguments(tmp_path):
    recorder = RecordingHook()
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[ToolCall(id="call_1", name="echo", arguments={"text": 123})],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path, hooks=[recorder])

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    assert recorder.events[3].type == "tool.started"
    assert recorder.events[4].type == "tool.completed"
    assert recorder.events[4].payload["ok"] is False
    assert "invalid arguments" in recorder.events[4].payload["error"]


def test_agent_marks_truncated_tool_output_in_event_payload(tmp_path):
    recorder = RecordingHook()
    model = FakeModelClient(
        [
            ModelResponse(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[ToolCall(id="call_1", name="echo", arguments={"text": "abcdefghij"})],
            ),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    agent = Agent(
        model_client=model,
        tools=[EchoTool()],
        cwd=tmp_path,
        max_tool_output_chars=8,
        hooks=[recorder],
    )

    agent.run("hello")

    tool_completed = [event for event in recorder.events if event.type == "tool.completed"][0]
    assert tool_completed.payload["truncated"] is True


def test_agent_emits_continuation_model_event(tmp_path):
    recorder = RecordingHook()
    model = FakeModelClient(
        [
            ModelResponse(content="partial ", finish_reason="length"),
            ModelResponse(content="answer", finish_reason="stop"),
        ]
    )
    agent = Agent(model_client=model, tools=[EchoTool()], cwd=tmp_path, hooks=[recorder])

    outcome = agent.run("hello")

    assert outcome.exit_code == 0
    model_events = [event for event in recorder.events if event.type == "model.completed"]
    assert len(model_events) == 2
    assert model_events[0].payload["is_continuation"] is False
    assert model_events[1].payload["is_continuation"] is True
    assert recorder.events[-1].type == "run.completed"
    assert recorder.events[-1].payload["used_continuation"] is True


def test_agent_emits_run_failed_before_reraising_unexpected_model_error(tmp_path):
    recorder = RecordingHook()

    class ExplodingModelClient:
        model = "boom-model"

        def complete(self, messages, tools, tool_choice="auto"):
            raise RuntimeError("network exploded")

    agent = Agent(
        model_client=ExplodingModelClient(),
        tools=[EchoTool()],
        cwd=tmp_path,
        hooks=[recorder],
    )

    with pytest.raises(RuntimeError, match="network exploded"):
        agent.run("hello")

    assert [event.type for event in recorder.events] == [
        "run.started",
        "step.started",
        "run.failed",
    ]
    assert recorder.events[-1].payload["error"] == "network exploded"
