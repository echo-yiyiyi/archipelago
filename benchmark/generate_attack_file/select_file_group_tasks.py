#!/usr/bin/env python3
"""Extract one randomly selected task for each inject goal."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = (
    SCRIPT_DIR.parent
    / "sample_inject_goal"
    / "output"
    / "selected_90_tasks_with_inject_goals.json"
)
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "test_json"
EXECUTABLE_VECTORS = {"py", "pyc", "elf"}
FILE_GOAL_IDS = (
    "1_email_send_file",
    "2_email_send_draft",
    "3_email_forward_otp",
    "4_email_broadcast_link",
    "5_chat_send_link",
    "6_chat_to_achieve_url",
    "7_calendar_create_event",
    "8_fetch_external_link",
)
EXECUTABLE_GOAL_IDS = (
    "9_url_query_params",
    "10_chat_send_ssh",
    "11_terminal_remote_script",
    "12_terminal_cron_setup",
)
ALL_GOAL_IDS = FILE_GOAL_IDS + EXECUTABLE_GOAL_IDS


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"input JSON does not exist: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("input JSON must contain an array of objects")
    return value


def choose_one_per_goal(
    rows: list[dict[str, Any]], *, seed: int
) -> dict[str, dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = {goal: [] for goal in ALL_GOAL_IDS}
    for row in rows:
        goal = row.get("inject_goal")
        if goal not in candidates:
            continue
        is_executable = row.get("inject_vector") in EXECUTABLE_VECTORS
        if (goal in EXECUTABLE_GOAL_IDS) != is_executable:
            continue
        if goal in candidates:
            candidates[goal].append(row)
    missing = [goal for goal, values in candidates.items() if not values]
    if missing:
        raise ValueError(f"file-group goals have no candidates: {', '.join(missing)}")

    rng = random.Random(seed)
    goals = list(ALL_GOAL_IDS)
    rng.shuffle(goals)
    goals.sort(key=lambda goal: len(candidates[goal]))
    for values in candidates.values():
        rng.shuffle(values)

    selected: dict[str, dict[str, Any]] = {}
    used_task_ids: set[str] = set()

    def search(position: int) -> bool:
        if position == len(goals):
            return True
        goal = goals[position]
        values = candidates[goal].copy()
        rng.shuffle(values)
        # Prefer a distinct original task_id, while retaining random ordering.
        values.sort(key=lambda row: row.get("task_id") in used_task_ids)
        for row in values:
            task_id = row.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            if task_id in used_task_ids:
                continue
            selected[goal] = row
            used_task_ids.add(task_id)
            if search(position + 1):
                return True
            used_task_ids.remove(task_id)
            selected.pop(goal, None)
        return False

    if not search(0):
        raise RuntimeError("could not select one distinct task_id for every file goal")
    return {goal: selected[goal] for goal in ALL_GOAL_IDS}


def write_outputs(selected: dict[str, dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for goal in ALL_GOAL_IDS:
        destination = output_dir / f"{goal}.json"
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        # Keep the same top-level array shape as the benchmark task JSON files.
        temporary.write_text(
            json.dumps([selected[goal]], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = choose_one_per_goal(load_rows(args.input), seed=args.seed)
    write_outputs(selected, args.output_dir)
    for goal in ALL_GOAL_IDS:
        row = selected[goal]
        print(f"{goal}: {row['task_id']} ({row['inject_vector']})")


if __name__ == "__main__":
    main()
