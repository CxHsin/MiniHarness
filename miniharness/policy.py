from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PermissionMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"
    AUTO = "auto"


@dataclass(frozen=True)
class RuntimePolicy:
    allow_outside_cwd: bool = False
    shell_timeout: int = 30
    shell_enabled: bool = True
    permission_mode: PermissionMode = PermissionMode.DEFAULT
