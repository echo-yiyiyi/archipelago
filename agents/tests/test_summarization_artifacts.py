import json
from typing import cast

from runner.agents.models import (
    AgentStatus,
    AgentTrajectoryOutput,
    LitellmAnyMessage,
)
from runner.agents.react_toolbelt_agent.resum import ReSumManager
from runner.main import save_summarization_artifacts


async def test_resum_records_input_output_and_trajectory_position(monkeypatch):
    manager = ReSumManager("test-model")
    messages = cast(
        list[LitellmAnyMessage],
        [{"role": "system", "content": "system"}]
        + [
            {"role": "user", "content": f"message-{index}"}
            for index in range(12)
        ],
    )

    async def fake_call_llm(prompt: str) -> str:
        assert "message-0" in prompt
        return "compact state"

    monkeypatch.setattr(manager, "_call_llm", fake_call_llm)

    compacted = await manager.summarize(messages, trigger="proactive_threshold")

    assert len(manager.summarization_records) == 1
    record = manager.summarization_records[0]
    assert record["trigger"] == "proactive_threshold"
    assert record["trigger_after_trajectory_message_index"] == 12
    assert record["input"]["messages"][1]["role"] == "user"
    assert record["output"] == {"summary": "compact state"}
    assert manager.get_full_history(compacted) == messages


def test_summarization_records_are_separate_artifacts(tmp_path):
    record = {"summarization_index": 1, "input": {}, "output": {"summary": "s"}}
    output = AgentTrajectoryOutput(
        messages=[],
        status=AgentStatus.COMPLETED,
        time_elapsed=1,
        summarization_records=[record],
    )
    trajectory_path = tmp_path / "trajectory.json"
    trajectory_path.write_text(output.model_dump_json(indent=2))

    save_summarization_artifacts(str(trajectory_path), output.summarization_records)

    assert "summarization_records" not in json.loads(trajectory_path.read_text())
    assert json.loads((tmp_path / "sumerize_1.json").read_text()) == record
