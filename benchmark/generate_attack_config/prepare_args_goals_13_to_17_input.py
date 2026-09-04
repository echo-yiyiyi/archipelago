#!/usr/bin/env python3
"""Create the five executable, add-user-prompt input records for generate.py."""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "output" / "1_to_8_with_attack_config.json"
DEST = HERE / "input" / "args_goals_13_to_17.json"
VECTORS = {
    "1_email_send_file": "py", "2_email_send_prompt": "pyc",
    "3_email_forward_otp": "elf", "4_email_broadcast_link": "pyc",
    "6_chat_to_achieve_url": "elf",
}
ARG_GOALS = {
    "1_email_send_file": "13_email_send_file_arg",
    "2_email_send_prompt": "14_email_send_prompt_arg",
    "3_email_forward_otp": "15_email_forward_otp_arg",
    "4_email_broadcast_link": "16_email_broadcast_link_arg",
    "6_chat_to_achieve_url": "17_chat_to_achieve_url_arg",
}

def main() -> None:
    records = json.loads(SOURCE.read_text(encoding="utf-8"))
    selected = []
    for source in records:
        goal = source.get("inject_goal")
        if goal not in VECTORS: continue
        record = dict(source)
        vector = VECTORS[goal]
        arg_goal = ARG_GOALS[goal]
        record["inject_goal"] = arg_goal
        record["inject_vector"] = vector
        record["add_user_prompt"] = True
        config = dict(record.get("attack_config") or {})
        config.pop("cot", None)
        record["attack_config"] = config
        # Existing app fixtures are reusable; generate.py will make the new
        # executable attack_file under its output directory.
        original_attack = Path(str(record.get("attack_file", "task_helper")))
        suffix = ".py" if vector == "py" else ".pyc" if vector == "pyc" else ""
        task_id = str(record.get("task_id"))
        harmful_id = f"{task_id}_{vector}_{arg_goal}"
        record["harmful_task_id"] = harmful_id
        record["attack_file"] = f"{harmful_id}/{original_attack.stem}{suffix}"
        record.pop("populate_files", None)
        selected.append(record)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n")
    print(DEST)

if __name__ == "__main__": main()
