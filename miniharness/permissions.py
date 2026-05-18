from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import re
from typing import Any

from .policy import PermissionMode, RuntimePolicy
from .tools.base import is_sensitive_path


class PermissionAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"


@dataclass(frozen=True)
class PermissionDecision:
    action: PermissionAction
    reason: str
    source: str
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.action is PermissionAction.ALLOW

    @property
    def error(self) -> str | None:
        return self.message


def _decision(
    *,
    action: PermissionAction,
    reason: str,
    source: str,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PermissionDecision:
    return PermissionDecision(
        action=action,
        reason=reason,
        source=source,
        message=message,
        metadata=metadata or {},
    )


_SAFE_READ_COMMANDS = (
    "dir",
    "ls",
    "pwd",
    "git status",
    "git diff --stat",
)
_SAFE_READ_PREFIXES = (
    "type ",
    "cat ",
    "rg ",
)
_COMMAND_TOKEN_PATTERN = re.compile(r'''(?:[^\s"']+|"[^"]*"|'[^']*')+''')
_WRAPPER_COMMANDS = {
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "sh",
    "bash",
    "zsh",
    "dash",
}
_WRAPPER_SWITCHES = {
    "/c",
    "/k",
    "-c",
    "-lc",
    "-command",
}
_DESTRUCTIVE_FLAGS = {
    "-r",
    "-rf",
    "-fr",
    "--recursive",
    "--force",
    "-recurse",
    "-force",
    "/s",
    "/q",
    "/f",
}
_HOME_ENV_PREFIXES = (
    "$home",
    "${home}",
    "%home%",
    "%userprofile%",
)


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().lower().split())


def _command_tokens(command: str) -> list[str]:
    return [token.strip("\"'") for token in _COMMAND_TOKEN_PATTERN.findall(command)]


def _command_tokens_without_wrappers(command: str) -> list[str]:
    tokens = _command_tokens(command)
    if len(tokens) >= 2 and tokens[0].lower() in _WRAPPER_COMMANDS and _is_wrapper_switch(tokens[1]):
        return tokens[2:]
    if len(tokens) >= 3 and tokens[0].lower() == "cmd" and tokens[1].lower() in {"/c", "/k"}:
        return tokens[2:]
    if len(tokens) >= 2 and tokens[0].lower() in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        for index, token in enumerate(tokens[1:], start=1):
            if token.lower() in {"-c", "-command"}:
                return tokens[index + 1 :]
    return tokens


def _unwrap_shell_wrapper(command: str) -> str | None:
    tokens = _command_tokens(command)
    if len(tokens) >= 2 and tokens[0].lower() in _WRAPPER_COMMANDS and _is_wrapper_switch(tokens[1]):
        payload = " ".join(tokens[2:]).strip()
        return payload or None
    if len(tokens) >= 3 and tokens[0].lower() in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        for index, token in enumerate(tokens[1:], start=1):
            if token.lower() in {"-c", "-command"}:
                payload = " ".join(tokens[index + 1 :]).strip()
                return payload or None
    return None


def _is_wrapper_switch(token: str) -> bool:
    return token.lower() in _WRAPPER_SWITCHES


def _command_variants(command: str) -> list[str]:
    variants = [command]
    seen = {command}
    current = command
    while True:
        unwrapped = _unwrap_shell_wrapper(current)
        if not unwrapped or unwrapped in seen:
            break
        variants.append(unwrapped)
        seen.add(unwrapped)
        current = unwrapped
    return variants


def _has_write_redirection(command: str) -> bool:
    normalized = _normalize_command(command)
    if ">" in normalized or "|" in normalized:
        return True
    tokens = _command_tokens(command)
    return any(token in {">", ">>", "|", "1>", "2>", "2>>", "1>>"} for token in tokens)


def _looks_like_safe_read_command(command: str) -> bool:
    variants = _command_variants(command)
    if any(_has_write_redirection(variant) for variant in variants):
        return False
    for variant in variants:
        normalized = _normalize_command(variant)
        if normalized in _SAFE_READ_COMMANDS:
            return True
        if any(normalized.startswith(prefix) for prefix in _SAFE_READ_PREFIXES):
            return True
    return False


def _matches_destructive_delete(command: str) -> bool:
    for variant in _command_variants(command):
        tokens = _command_tokens_without_wrappers(variant)
        if not tokens:
            continue

        verb = tokens[0].lower()
        flags = [token.lower() for token in tokens[1:]]
        flag_set = set(flags)

        if verb in {"rm", "rmdir", "rd", "del", "erase"}:
            if verb == "rm":
                for flag in flags:
                    if flag == "-r":
                        return True
                    if flag.startswith("-r") and len(flag) > 2:
                        return True
            elif bool(flag_set & {"/s", "/q", "/f", "-recurse", "-force", "--recursive", "--force"}):
                return True

        if verb in {"remove-item", "ri", "rm", "rmdir", "rd"}:
            if bool(flag_set & {"-recurse", "-force", "--recursive", "--force"}):
                return True

    return False


def _targets_sensitive_path(command: str) -> bool:
    for variant in _command_variants(command):
        for raw_token in _command_tokens_without_wrappers(variant):
            token = raw_token.strip("\"'`[](){}<>;,")
            if not token:
                continue
            candidates: list[Path] = []
            lower_token = token.lower()
            if lower_token.startswith(_HOME_ENV_PREFIXES):
                for separator in ("/", "\\"):
                    separator_index = token.find(separator)
                    if separator_index > 0:
                        suffix = token[separator_index + 1 :]
                        if suffix:
                            candidates.append(Path(suffix))
                        break
            if token.startswith(("~", "/", "./", "../")) or re.match(r"^[a-zA-Z]:[\\/]", token):
                candidates.append(Path(token).expanduser())
            for candidate in candidates:
                if is_sensitive_path(candidate):
                    return True
    return False


def _extract_risk_tags(command: str) -> list[str]:
    tags = ["shell_exec"]
    if _looks_like_safe_read_command(command):
        tags.append("read_only")
    if _matches_destructive_delete(command):
        tags.extend(["destructive_delete", "delete_dir"])
    elif _targets_sensitive_path(command):
        tags.append("sensitive_target")
    elif _normalize_command(command).startswith(("touch ", "mkdir ", "cp ", "mv ")):
        tags.append("write_file")
    return tags


def check_tool_permission(
    policy: RuntimePolicy,
    tool_name: str,
    args: dict[str, Any],
) -> PermissionDecision:
    if tool_name != "run_shell":
        return _decision(
            action=PermissionAction.ALLOW,
            reason="non_shell_passthrough",
            source="mode",
            message=f"tool {tool_name} is not governed by v0.2.3 mode-aware permission checks",
            metadata={
                "tool_name": tool_name,
                "permission_mode": policy.permission_mode.value,
            },
        )

    command = str(args.get("command") or "")
    risk_tags = _extract_risk_tags(command)

    if policy.shell_enabled is False:
        return _decision(
            action=PermissionAction.DENY,
            reason="shell_disabled",
            source="deny_rule",
            message=f"tool {tool_name} is disabled by runtime policy",
            metadata={
                "tool_name": tool_name,
                "permission_mode": policy.permission_mode.value,
                "risk_tags": risk_tags,
                "rule": "shell_disabled",
            },
        )

    if "sensitive_target" in risk_tags:
        return _decision(
            action=PermissionAction.DENY,
            reason="sensitive_target",
            source="deny_rule",
            message=f"tool {tool_name} targets a sensitive path and is denied by runtime policy",
            metadata={
                "tool_name": tool_name,
                "permission_mode": policy.permission_mode.value,
                "risk_tags": risk_tags,
                "rule": "sensitive_target",
            },
        )

    if "destructive_delete" in risk_tags:
        return _decision(
            action=PermissionAction.DENY,
            reason="destructive_delete",
            source="deny_rule",
            message=f"tool {tool_name} matches a destructive delete pattern and is denied by runtime policy",
            metadata={
                "tool_name": tool_name,
                "permission_mode": policy.permission_mode.value,
                "risk_tags": risk_tags,
                "rule": "destructive_delete",
            },
        )

    if _looks_like_safe_read_command(command):
        return _decision(
            action=PermissionAction.ALLOW,
            reason="safe_read_command",
            source="mode",
            message=f"tool {tool_name} is allowed by runtime policy",
            metadata={
                "tool_name": tool_name,
                "permission_mode": policy.permission_mode.value,
                "risk_tags": risk_tags,
                "rule": "safe_read_command",
            },
        )

    if policy.permission_mode in {PermissionMode.DEFAULT, PermissionMode.PLAN}:
        return _decision(
            action=PermissionAction.ASK_USER,
            reason="approval_required",
            source="fallback",
            message=f"tool {tool_name} requires user approval in the current permission mode",
            metadata={
                "tool_name": tool_name,
                "permission_mode": policy.permission_mode.value,
                "risk_tags": risk_tags,
                "rule": "mode_fallback",
            },
        )

    return _decision(
        action=PermissionAction.ALLOW,
        reason="auto_mode_allows_shell",
        source="mode",
        message=f"tool {tool_name} is allowed by runtime policy",
        metadata={
            "tool_name": tool_name,
            "permission_mode": policy.permission_mode.value,
            "risk_tags": risk_tags,
            "rule": "auto_mode_allows_shell",
        },
    )
