from types import SimpleNamespace

import pytest


class FakeModelClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, tools, tool_choice="auto"):
        self.calls.append(
            {"messages": messages, "tools": tools, "tool_choice": tool_choice}
        )
        if not self.responses:
            raise AssertionError("FakeModelClient has no responses left")
        response = self.responses.pop(0)
        if isinstance(response, dict):
            return SimpleNamespace(**response)
        return response


@pytest.fixture
def fake_tool_context(tmp_path):
    from miniharness.tools.base import ToolContext

    return ToolContext(cwd=tmp_path)
