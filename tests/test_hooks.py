from dataclasses import FrozenInstanceError
from io import StringIO

import pytest

from miniharness.hooks import ConsoleHook, HookDispatcher, HookEvent


class RecordingHook:
    def __init__(self):
        self.events = []

    def handle(self, event):
        self.events.append(event)


class RaisingHook:
    def handle(self, event):
        raise RuntimeError("hook blew up")


def test_hook_event_is_frozen():
    event = HookEvent(type="run.started", run_id="abc", step=None, payload={})

    with pytest.raises(FrozenInstanceError):
        event.type = "run.failed"


def test_dispatcher_is_noop_without_hooks():
    dispatcher = HookDispatcher()
    event = HookEvent(type="run.started", run_id="abc", step=None, payload={})

    dispatcher.emit(event)


def test_dispatcher_emits_to_hooks_in_order():
    first = RecordingHook()
    second = RecordingHook()
    dispatcher = HookDispatcher([first, second])
    event = HookEvent(type="run.started", run_id="abc", step=None, payload={})

    dispatcher.emit(event)

    assert first.events == [event]
    assert second.events == [event]


def test_dispatcher_continues_after_hook_failure(caplog):
    good = RecordingHook()
    dispatcher = HookDispatcher([RaisingHook(), good])
    event = HookEvent(type="run.started", run_id="abc", step=None, payload={})

    dispatcher.emit(event)

    assert good.events == [event]
    assert "Hook dispatch failed" in caplog.text


def test_console_hook_renders_run_prefix_for_step_none():
    stream = StringIO()
    hook = ConsoleHook(stream=stream)

    hook.handle(HookEvent(type="run.started", run_id="abc", step=None, payload={}))

    assert stream.getvalue() == "[run] started\n"


def test_console_hook_converts_zero_based_step_to_one_based():
    stream = StringIO()
    hook = ConsoleHook(stream=stream)

    hook.handle(
        HookEvent(
            type="tool.started",
            run_id="abc",
            step=0,
            payload={
                "tool_name": "read_file",
                "tool_call_id": "call_1",
                "arguments_summary": '{"path":"README.md"}',
            },
        )
    )

    assert stream.getvalue() == '[step 1] tool read_file started {"path":"README.md"}\n'


def test_console_hook_keeps_argument_summary_on_one_line():
    stream = StringIO()
    hook = ConsoleHook(stream=stream)

    hook.handle(
        HookEvent(
            type="tool.started",
            run_id="abc",
            step=1,
            payload={
                "tool_name": "write_file",
                "tool_call_id": "call_1",
                "arguments_summary": '{"content":"line1\\nline2"}',
            },
        )
    )

    assert stream.getvalue().count("\n") == 1
    assert "\\n" in stream.getvalue()
