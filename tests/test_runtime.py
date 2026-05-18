from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from miniharness.approvals import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalRequest,
    DenyingApprovalHandler,
)
from miniharness.capabilities import AgentCapabilities
from miniharness.hooks import ConsoleHook
from miniharness.policy import PermissionMode, RuntimePolicy
from miniharness.permissions import (
    PermissionAction,
    PermissionDecision,
    check_tool_permission,
)
from miniharness.runtime import AgentRuntime
from miniharness.tools.base import ToolContext
from miniharness.session import Session


def test_runtime_policy_defaults():
    policy = RuntimePolicy()

    assert policy.allow_outside_cwd is False
    assert policy.shell_timeout == 30
    assert policy.shell_enabled is True
    assert policy.permission_mode is PermissionMode.DEFAULT


def test_runtime_policy_is_frozen():
    policy = RuntimePolicy()

    with pytest.raises(FrozenInstanceError):
        policy.shell_timeout = 99


def test_check_tool_permission_denies_shell_when_disabled_before_mode_logic():
    decision = check_tool_permission(
        RuntimePolicy(shell_enabled=False, permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": "echo hi"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.DENY,
        reason="shell_disabled",
        source="deny_rule",
        message="tool run_shell is disabled by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec"],
            "rule": "shell_disabled",
        },
    )


def test_check_tool_permission_denies_sensitive_shell_target_even_in_auto():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": "cat ~/.ssh/id_rsa"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.DENY,
        reason="sensitive_target",
        source="deny_rule",
        message="tool run_shell targets a sensitive path and is denied by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec", "read_only", "sensitive_target"],
            "rule": "sensitive_target",
        },
    )


def test_check_tool_permission_default_mode_routes_ambiguous_shell_to_ask_user():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        "run_shell",
        {"command": "echo hello > out.txt"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.ASK_USER,
        reason="approval_required",
        source="fallback",
        message="tool run_shell requires user approval in the current permission mode",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "default",
            "risk_tags": ["shell_exec"],
            "rule": "mode_fallback",
        },
    )


def test_check_tool_permission_plan_mode_allows_safe_read_shell():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.PLAN),
        "run_shell",
        {"command": "git status"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.ALLOW,
        reason="safe_read_command",
        source="mode",
        message="tool run_shell is allowed by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "plan",
            "risk_tags": ["shell_exec", "read_only"],
            "rule": "safe_read_command",
        },
    )


def test_check_tool_permission_plan_mode_routes_modifying_shell_to_ask_user():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.PLAN),
        "run_shell",
        {"command": "touch output.txt"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.ASK_USER,
        reason="approval_required",
        source="fallback",
        message="tool run_shell requires user approval in the current permission mode",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "plan",
            "risk_tags": ["shell_exec", "write_file"],
            "rule": "mode_fallback",
        },
    )


def test_check_tool_permission_auto_mode_allows_command_that_plan_would_ask_about():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": "touch output.txt"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.ALLOW,
        reason="auto_mode_allows_shell",
        source="mode",
        message="tool run_shell is allowed by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec", "write_file"],
            "rule": "auto_mode_allows_shell",
        },
    )


def test_check_tool_permission_denies_destructive_delete_pattern_even_in_auto():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": "rm -rf build"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.DENY,
        reason="destructive_delete",
        source="deny_rule",
        message="tool run_shell matches a destructive delete pattern and is denied by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec", "destructive_delete", "delete_dir"],
            "rule": "destructive_delete",
        },
    )


def test_check_tool_permission_does_not_flag_quoted_destructive_substring():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": 'echo "rm -rf"'},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.ALLOW,
        reason="auto_mode_allows_shell",
        source="mode",
        message="tool run_shell is allowed by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec"],
            "rule": "auto_mode_allows_shell",
        },
    )


def test_check_tool_permission_denies_wrapped_cmd_payload_even_in_auto():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": 'cmd /c "rm -rf build"'},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.DENY,
        reason="destructive_delete",
        source="deny_rule",
        message="tool run_shell matches a destructive delete pattern and is denied by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec", "destructive_delete", "delete_dir"],
            "rule": "destructive_delete",
        },
    )


def test_check_tool_permission_denies_powershell_remove_item_variant_even_in_auto():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": "Remove-Item -Recurse -Force build"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.DENY,
        reason="destructive_delete",
        source="deny_rule",
        message="tool run_shell matches a destructive delete pattern and is denied by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec", "destructive_delete", "delete_dir"],
            "rule": "destructive_delete",
        },
    )


def test_check_tool_permission_denies_wrapped_powershell_payload_even_in_auto():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": 'powershell -Command "Remove-Item -Recurse -Force build"'},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.DENY,
        reason="destructive_delete",
        source="deny_rule",
        message="tool run_shell matches a destructive delete pattern and is denied by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec", "destructive_delete", "delete_dir"],
            "rule": "destructive_delete",
        },
    )


def test_check_tool_permission_denies_wrapped_bash_payload_even_in_auto():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": 'bash -lc "rm -rf build"'},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.DENY,
        reason="destructive_delete",
        source="deny_rule",
        message="tool run_shell matches a destructive delete pattern and is denied by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec", "destructive_delete", "delete_dir"],
            "rule": "destructive_delete",
        },
    )


def test_check_tool_permission_denies_combined_rm_flags_even_in_auto():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": "rm -rfv build"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.DENY,
        reason="destructive_delete",
        source="deny_rule",
        message="tool run_shell matches a destructive delete pattern and is denied by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec", "destructive_delete", "delete_dir"],
            "rule": "destructive_delete",
        },
    )


def test_check_tool_permission_detects_env_prefixed_sensitive_path():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.AUTO),
        "run_shell",
        {"command": "cat $HOME/.ssh/config"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.DENY,
        reason="sensitive_target",
        source="deny_rule",
        message="tool run_shell targets a sensitive path and is denied by runtime policy",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "auto",
            "risk_tags": ["shell_exec", "read_only", "sensitive_target"],
            "rule": "sensitive_target",
        },
    )


def test_check_tool_permission_routes_cat_redirection_to_approval():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        "run_shell",
        {"command": "cat > out.txt"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.ASK_USER,
        reason="approval_required",
        source="fallback",
        message="tool run_shell requires user approval in the current permission mode",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "default",
            "risk_tags": ["shell_exec"],
            "rule": "mode_fallback",
        },
    )


def test_check_tool_permission_routes_rg_redirection_to_approval():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.PLAN),
        "run_shell",
        {"command": "rg pattern > results.txt"},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.ASK_USER,
        reason="approval_required",
        source="fallback",
        message="tool run_shell requires user approval in the current permission mode",
        metadata={
            "tool_name": "run_shell",
            "permission_mode": "plan",
            "risk_tags": ["shell_exec"],
            "rule": "mode_fallback",
        },
    )


def test_check_tool_permission_unknown_tool_falls_through_as_allow():
    decision = check_tool_permission(
        RuntimePolicy(permission_mode=PermissionMode.DEFAULT),
        "unknown_tool",
        {},
    )

    assert decision == PermissionDecision(
        action=PermissionAction.ALLOW,
        reason="non_shell_passthrough",
        source="mode",
        message="tool unknown_tool is not governed by v0.2.3 mode-aware permission checks",
        metadata={
            "tool_name": "unknown_tool",
            "permission_mode": "default",
        },
    )


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


def test_approval_request_defaults_metadata():
    request = ApprovalRequest(
        tool_name="run_shell",
        arguments={"command": "echo hello > out.txt"},
        reason="approval_required",
        message="tool run_shell requires user approval in the current permission mode",
    )

    assert request.metadata == {}


def test_approval_decision_defaults_metadata():
    decision = ApprovalDecision(
        action=ApprovalAction.REJECT,
        reason="approval_not_available",
    )

    assert decision.metadata == {}


def test_denying_approval_handler_reuses_request_message():
    handler = DenyingApprovalHandler()
    request = ApprovalRequest(
        tool_name="run_shell",
        arguments={"command": "echo hello > out.txt"},
        reason="approval_required",
        message="tool run_shell requires user approval in the current permission mode",
    )

    decision = handler.decide(request)

    assert decision == ApprovalDecision(
        action=ApprovalAction.REJECT,
        reason="approval_not_available",
        message="tool run_shell requires user approval in the current permission mode",
        metadata={"tool_name": "run_shell"},
    )


def test_agent_runtime_defaults_to_denying_approval_handler_when_built_directly(
    tmp_path,
):
    runtime = AgentRuntime(
        cwd=tmp_path.resolve(),
        session=Session(cwd=tmp_path, history_budget_chars=123),
        tool_context=ToolContext(cwd=tmp_path.resolve()),
        policy=RuntimePolicy(),
        capabilities=AgentCapabilities(),
    )

    assert isinstance(runtime.approval_handler, DenyingApprovalHandler)


def test_agent_runtime_create_installs_default_approval_handler(tmp_path):
    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(),
        capabilities=AgentCapabilities(),
    )

    assert isinstance(runtime.approval_handler, DenyingApprovalHandler)


def test_agent_runtime_create_preserves_injected_approval_handler(tmp_path):
    handler = DenyingApprovalHandler()

    runtime = AgentRuntime.create(
        cwd=tmp_path,
        policy=RuntimePolicy(),
        capabilities=AgentCapabilities(),
        approval_handler=handler,
    )

    assert runtime.approval_handler is handler
