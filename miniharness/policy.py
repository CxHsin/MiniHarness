from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimePolicy:
    allow_outside_cwd: bool = False
    shell_timeout: int = 30
    shell_enabled: bool = True
