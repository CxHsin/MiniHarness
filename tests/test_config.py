from types import SimpleNamespace

from miniharness.config import load_config


def test_load_config_prefers_cli_over_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    args = SimpleNamespace(
        cwd=str(tmp_path),
        model="cli-model",
        base_url="https://cli.example/v1",
        max_steps=3,
        shell_timeout=4,
        max_tool_output_chars=5000,
        history_budget_chars=6000,
        max_no_progress_steps=1,
        log_level="DEBUG",
        verbose=False,
        allow_outside_cwd=True,
    )

    config = load_config(args, env_path=tmp_path / ".env")

    assert config.api_key == "env-key"
    assert config.model == "cli-model"
    assert config.base_url == "https://cli.example/v1"
    assert config.max_steps == 3
    assert config.shell_timeout == 4
    assert config.max_tool_output_chars == 5000
    assert config.history_budget_chars == 6000
    assert config.max_no_progress_steps == 1
    assert config.log_level == "DEBUG"
    assert config.allow_outside_cwd is True


def test_load_config_uses_dotenv_before_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENAI_API_KEY=dotenv-key\n"
        "OPENAI_MODEL=dotenv-model\n"
        "OPENAI_BASE_URL=https://dotenv.example/v1\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        cwd=str(tmp_path),
        model=None,
        base_url=None,
        max_steps=8,
        shell_timeout=30,
        max_tool_output_chars=12000,
        history_budget_chars=120000,
        max_no_progress_steps=2,
        log_level="WARNING",
        verbose=True,
        allow_outside_cwd=False,
    )

    config = load_config(args, env_path=env_path)

    assert config.api_key == "dotenv-key"
    assert config.model == "dotenv-model"
    assert config.base_url == "https://dotenv.example/v1"
    assert config.log_level == "INFO"
