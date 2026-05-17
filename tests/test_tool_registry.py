from miniharness.tools.base import (
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    validate_tool_arguments,
)


class SampleTool(Tool):
    name = "sample"
    description = "sample tool"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "count": {"type": "integer", "minimum": 1, "maximum": 3},
        },
        "required": ["text"],
    }

    def execute(self, args, context: ToolContext) -> ToolResult:
        return ToolResult(True, args["text"] * args.get("count", 1), None)


def test_tool_registry_registers_and_exports_openai_tools():
    tool = SampleTool()
    registry = ToolRegistry([tool])

    assert registry.get("sample") is tool
    assert registry.names() == ["sample"]
    exported = registry.to_openai_tools()
    assert exported[0]["type"] == "function"
    assert exported[0]["function"]["name"] == "sample"


def test_tool_registry_rejects_duplicate_tool_names():
    registry = ToolRegistry([SampleTool()])

    result = registry.register(SampleTool())

    assert result.ok is False
    assert "duplicate tool" in result.error


def test_tool_result_exposes_openharness_style_is_error_property():
    assert ToolResult(True, "ok").is_error is False
    assert ToolResult(False, "", "failed").is_error is True


def test_validate_tool_arguments_rejects_missing_required():
    result = validate_tool_arguments(SampleTool(), {"count": 1})

    assert result.ok is False
    assert "text is required" in result.error


def test_validate_tool_arguments_rejects_wrong_type_and_range():
    wrong_type = validate_tool_arguments(SampleTool(), {"text": "x", "count": "2"})
    out_of_range = validate_tool_arguments(SampleTool(), {"text": "x", "count": 4})

    assert wrong_type.ok is False
    assert "count must be integer" in wrong_type.error
    assert out_of_range.ok is False
    assert "count must be <= 3" in out_of_range.error


def test_tool_execute_validated_runs_validation_before_tool_logic(fake_tool_context):
    result = SampleTool().execute_validated({"count": 1}, fake_tool_context)

    assert result.ok is False
    assert "invalid arguments" in result.error
