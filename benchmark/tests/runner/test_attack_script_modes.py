import json
import subprocess
from pathlib import Path

from benchmark.generate_attack_config.generate import (
    needs_instruction_lure,
    uses_runtime_args,
)


ROOT = Path(__file__).resolve().parents[3]
SELECTED = ROOT / "benchmark" / "generate_attack_config" / "output" / "selected_6_with_attack_config.json"
ARGS = ROOT / "benchmark" / "generate_attack_config" / "output" / "args_user_prompt_v3" / "args_tasks.json"


def _has_runtime_argument_gate(path: Path) -> bool:
    if path.suffix in {".py", ".txt"}:
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        text = subprocess.run(["strings", str(path)], capture_output=True, text=True, check=True).stdout
    return "parse_runtime_args" in text or "missing required runtime argument" in text


def test_selected6_original_goals_are_no_argument_scripts():
    records = json.loads(SELECTED.read_text(encoding="utf-8"))
    assert len(records) == 6
    for record in records:
        path = ROOT / "benchmark" / "generate_attack_config" / "output" / record["attack_file"]
        assert path.is_file(), path
        assert not _has_runtime_argument_gate(path), (record["harmful_task_id"], path)


def test_five_arg_tasks_are_explicitly_arg_goals():
    records = json.loads(ARGS.read_text(encoding="utf-8"))
    assert len(records) == 5
    assert all(str(record["inject_goal"]).endswith("_arg") for record in records)


def test_goal_number_selects_args_independently_of_user_prompt():
    assert not uses_runtime_args({"inject_goal": "1_email_send_file", "add_user_prompt": True})
    assert uses_runtime_args({"inject_goal": "13_email_send_file_arg", "add_user_prompt": True})


def test_user_prompt_controls_instruction_lure_only():
    assert needs_instruction_lure({"inject_goal": "1_email_send_file"})
    assert needs_instruction_lure({"inject_goal": "1_email_send_file", "add_user_prompt": False})
    assert not needs_instruction_lure({"inject_goal": "1_email_send_file", "add_user_prompt": True})
