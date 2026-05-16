from miniharness.session import Session


def test_session_keeps_tool_call_group_together_when_trimming(tmp_path):
    session = Session(cwd=tmp_path, history_budget_chars=260)
    session.add_message({"role": "system", "content": "system"})
    session.add_message({"role": "user", "content": "latest question"})
    session.add_turn(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "old_call"}],
            },
            {
                "role": "tool",
                "tool_call_id": "old_call",
                "content": "x" * 200,
            },
        ]
    )
    session.add_turn(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "new_call"}],
            },
            {
                "role": "tool",
                "tool_call_id": "new_call",
                "content": "new result",
            },
        ]
    )

    messages = session.get_messages()

    assert messages[0]["role"] == "system"
    assert {"role": "user", "content": "latest question"} in messages
    assert not any(message.get("tool_call_id") == "old_call" for message in messages)
    assert any(message.get("tool_call_id") == "new_call" for message in messages)
    assert any(
        message.get("tool_calls") == [{"id": "new_call"}] for message in messages
    )


def test_session_does_not_persist_between_instances(tmp_path):
    first = Session(cwd=tmp_path)
    second = Session(cwd=tmp_path)

    first.add_message({"role": "user", "content": "hello"})

    assert second.get_messages() == []
