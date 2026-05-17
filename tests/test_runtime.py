from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from miniharness.capabilities import AgentCapabilities
from miniharness.hooks import ConsoleHook
from miniharness.policy import RuntimePolicy
from miniharness.permissions import PermissionDecision, check_tool_permission
from miniharness.runtime import AgentRuntime


def test_runtime_policy_defaults():
    policy = RuntimePolicy()

    assert policy.allow_outside_cwd is False
    assert policy.shell_timeout == 30
    assert policy.shell_enabled is True


def test_runtime_policy_is_frozen():
    policy = RuntimePolicy()

    with pytest.raises(FrozenInstanceError):
        policy.shell_timeout = 99


def test_check_tool_permission_allows_shell_when_enabled():
    decision = check_tool_permission(
        RuntimePolicy(shell_enabled=True),
        "run_shell",
        {"command": "echo hi"},
    )

    assert decision == PermissionDecision(allowed=True)


def test_check_tool_permission_denies_shell_when_disabled():
    decision = check_tool_permission(
        RuntimePolicy(shell_enabled=False),
        "run_shell",
        {"command": "echo hi"},
    )

    assert decision == PermissionDecision(
        allowed=False,
        error="tool run_shell is disabled by runtime policy",
    )


def test_check_tool_permission_allows_non_shell_tools_when_shell_disabled():
    decision = check_tool_permission(
        RuntimePolicy(shell_enabled=False),
        "read_file",
        {"path": "README.md"},
    )

    assert decision == PermissionDecision(allowed=True)


def test_agent_capabilities_defaults():
    capabilities = AgentCapabilities()

    assert capabilities.has_memory is False
    assert capabilities.has_skills is False
    assert capabilities.has_permission_system is False
    assert capabilities.has_trace_hooks is True
    assert capabilities.supports_tool_registry is True


def test_agent_runtime_resolves_cwd_and_builds_session_and_tool_context(tmp_path):
    runtime = AgentRuntime.create(
        cwd=tmp_path / ".",
        policy=RuntimePolicy(shell_timeout=45, allow_outside_cwd=True),
        capabilities=AgentCapabilities(),
        history_budget_chars=321,
        hooks=[ConsoleHook()],
    )

    assert runtime.cwd == tmp_path.resolve()
    assert isinstance(runtime.cwd, Path)
    assert runtime.session.cwd == tmp_path.resolve()
    assert runtime.session.history_budget_chars == 321
    assert runtime.tool_context.cwd == tmp_path.resolve()
    assert runtime.tool_context.shell_timeout == 45
    assert runtime.tool_context.allow_outside_cwd is True
    assert len(runtime.hooks) == 1
