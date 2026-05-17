from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


@dataclass(frozen=True)
class Config:
    cwd: Path
    api_key: str | None
    model: str
    base_url: str | None = None
    max_steps: int = 8
    shell_timeout: int = 30
    max_tool_output_chars: int = 12000
    history_budget_chars: int = 120000
    max_no_progress_steps: int = 2
    log_level: str = "WARNING"
    allow_outside_cwd: bool = False
    trace: bool = False


def load_config(args: Any, env_path: str | Path | None = None) -> Config:
    cwd = Path(args.cwd).resolve()
    dotenv_path = Path(env_path) if env_path is not None else cwd / ".env"
    file_env = dotenv_values(dotenv_path) if dotenv_path.exists() else {}

    api_key = os.environ.get("OPENAI_API_KEY") or file_env.get("OPENAI_API_KEY")
    model = (
        getattr(args, "model", None)
        or os.environ.get("OPENAI_MODEL")
        or file_env.get("OPENAI_MODEL")
        or "gpt-4o-mini"
    )
    base_url = (
        getattr(args, "base_url", None)
        or os.environ.get("OPENAI_BASE_URL")
        or file_env.get("OPENAI_BASE_URL")
        or None
    )
    log_level = "INFO" if getattr(args, "verbose", False) else args.log_level

    return Config(
        cwd=cwd,
        api_key=api_key,
        model=model,
        base_url=base_url,
        max_steps=args.max_steps,
        shell_timeout=args.shell_timeout,
        max_tool_output_chars=args.max_tool_output_chars,
        history_budget_chars=args.history_budget_chars,
        max_no_progress_steps=args.max_no_progress_steps,
        log_level=log_level,
        allow_outside_cwd=args.allow_outside_cwd,
        trace=getattr(args, "trace", False),
    )
