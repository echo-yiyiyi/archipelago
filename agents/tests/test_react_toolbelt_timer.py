import json
import time
from types import SimpleNamespace

import pytest

from runner.agents.react_toolbelt_agent.main import ReActAgent
from runner.agents.react_toolbelt_agent.tools import timer_status


def _timer_call(call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name="timer", arguments="{}"),
    )


def test_timer_status_never_reports_negative_remaining_time() -> None:
    result = json.loads(timer_status(total_seconds=300, elapsed_seconds=301.25))

    assert result == {
        "total_seconds": 300,
        "elapsed_seconds": 301.2,
        "remaining_seconds": 0.0,
        "expired": True,
        "prompt": (
            "The time limit has expired. Please submit your answer as soon as "
            "possible and do not delay much longer."
        ),
    }


def test_timer_is_initially_available_when_enabled() -> None:
    agent = ReActAgent.__new__(ReActAgent)
    agent.all_tools = {}
    agent.toolbelt = set()
    agent.timer_seconds = 300

    names = [tool["function"]["name"] for tool in agent._get_tools()]

    assert "timer" in names
    assert names[-1] == "final_answer"


@pytest.mark.asyncio
async def test_parallel_timer_calls_each_receive_a_result() -> None:
    agent = ReActAgent.__new__(ReActAgent)
    agent.timer_seconds = 300
    agent.timer_started_at = time.monotonic() - 15
    agent.messages = []

    await agent._handle_tool_calls(None, [_timer_call("timer-1"), _timer_call("timer-2")])

    assert [message.tool_call_id for message in agent.messages] == [
        "timer-1",
        "timer-2",
    ]
    for message in agent.messages:
        result = json.loads(message.content)
        assert 284 <= result["remaining_seconds"] <= 285
        assert result["expired"] is False


@pytest.mark.asyncio
async def test_automatic_timer_call_adds_a_fresh_update_for_a_turn() -> None:
    tracked_outputs = []
    agent = ReActAgent.__new__(ReActAgent)
    agent.timer_seconds = 300
    agent.timer_started_at = time.monotonic() - 20
    agent._automatic_timer_call_count = 0
    agent.messages = []
    agent._usage_tracker = SimpleNamespace(track_tool_output=tracked_outputs.append)

    await agent._append_automatic_timer_update(None)

    assert len(agent.messages) == 2
    assistant_message, tool_message = agent.messages
    assert assistant_message.tool_calls[0].function.name == "timer"
    assert tool_message.name == "timer"
    assert tool_message.tool_call_id == assistant_message.tool_calls[0].id
    assert tracked_outputs == [tool_message.content]
