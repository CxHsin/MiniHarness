from miniharness.prompts import build_system_prompt


def test_build_system_prompt_accepts_runtime_argument():
    assert "MiniHarness" in build_system_prompt(runtime=None)
