from miniharness.tools.todo import TodoTool


def test_todo_add_list_done_remove_clear(fake_tool_context):
    tool = TodoTool()

    add = tool.execute({"action": "add", "text": "write tests"}, fake_tool_context)
    listed = tool.execute({"action": "list"}, fake_tool_context)
    done = tool.execute({"action": "done", "index": 1}, fake_tool_context)
    removed = tool.execute({"action": "remove", "index": 1}, fake_tool_context)
    cleared = tool.execute({"action": "clear"}, fake_tool_context)

    assert add.ok is True
    assert "1. [ ] write tests" in listed.output
    assert done.ok is True
    assert removed.ok is True
    assert cleared.output == "cleared todos"


def test_todo_rejects_missing_text(fake_tool_context):
    result = TodoTool().execute({"action": "add"}, fake_tool_context)

    assert result.ok is False
    assert "text" in result.error
