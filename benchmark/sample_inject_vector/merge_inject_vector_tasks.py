#!/usr/bin/env python3
"""Merge file-type and executable-vector tasks, grouped by difficulty and task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_FILE_TYPE_INPUT = (
    SCRIPT_DIR / "output" / "selected_15_tasks_with_balanced_inject_vectors.json"
)
DEFAULT_EXECUTABLE_INPUT = (
    SCRIPT_DIR / "output" / "selected_15_tasks_with_inject_vectors.json"
)
DEFAULT_OUTPUT = (
    SCRIPT_DIR / "output" / "selected_30_tasks_with_inject_vectors.json"
)
DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2}


def load_tasks(path: Path, description: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"{description} JSON does not exist: {path}")
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError(f"{description} JSON must contain a top-level array")
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError(f"every {description} task must be a JSON object")
        if not isinstance(task.get("task_id"), str) or not task["task_id"]:
            raise ValueError(f"every {description} task must have a task_id")
        if task.get("difficulty") not in DIFFICULTY_ORDER:
            raise ValueError(
                f"task {task['task_id']} has unsupported difficulty: "
                f"{task.get('difficulty')!r}"
            )
        if not isinstance(task.get("inject_vector"), str) or not task["inject_vector"]:
            raise ValueError(
                f"task {task['task_id']} must have a non-empty inject_vector"
            )
        if not isinstance(task.get("harmful_task_id"), str) or not task["harmful_task_id"]:
            raise ValueError(
                f"task {task['task_id']} must have a non-empty harmful_task_id"
            )
    return tasks


def merge_tasks(
    file_type_tasks: list[dict[str, Any]],
    executable_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    file_by_id = {task["task_id"]: task for task in file_type_tasks}
    executable_by_id = {task["task_id"]: task for task in executable_tasks}
    if len(file_by_id) != len(file_type_tasks):
        raise ValueError("file-type input contains duplicate task_id values")
    if len(executable_by_id) != len(executable_tasks):
        raise ValueError("executable input contains duplicate task_id values")
    if set(file_by_id) != set(executable_by_id):
        missing_file = sorted(set(executable_by_id) - set(file_by_id))
        missing_executable = sorted(set(file_by_id) - set(executable_by_id))
        raise ValueError(
            "input task IDs do not match; "
            f"missing file-type={missing_file}, "
            f"missing executable={missing_executable}"
        )

    original_order = {
        task["task_id"]: index for index, task in enumerate(file_type_tasks)
    }
    ordered_task_ids = sorted(
        file_by_id,
        key=lambda task_id: (
            DIFFICULTY_ORDER[file_by_id[task_id]["difficulty"]],
            original_order[task_id],
        ),
    )

    merged = []
    for task_id in ordered_task_ids:
        file_task = file_by_id[task_id]
        executable_task = executable_by_id[task_id]
        if file_task["difficulty"] != executable_task["difficulty"]:
            raise ValueError(f"difficulty mismatch for task {task_id}")
        merged.extend((file_task, executable_task))

    harmful_task_ids = [task["harmful_task_id"] for task in merged]
    if len(set(harmful_task_ids)) != len(harmful_task_ids):
        raise ValueError("merged harmful_task_id values must be unique")
    return merged


def atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file-type-input", type=Path, default=DEFAULT_FILE_TYPE_INPUT
    )
    parser.add_argument(
        "--executable-input", type=Path, default=DEFAULT_EXECUTABLE_INPUT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    file_type_tasks = load_tasks(args.file_type_input.resolve(), "file-type")
    executable_tasks = load_tasks(args.executable_input.resolve(), "executable")
    merged = merge_tasks(file_type_tasks, executable_tasks)
    output_path = args.output.resolve()
    atomic_write(output_path, merged)
    difficulty_counts = {
        difficulty: sum(task["difficulty"] == difficulty for task in merged)
        for difficulty in DIFFICULTY_ORDER
    }
    print(f"Wrote {len(merged)} tasks to {output_path}")
    print(f"Difficulty counts: {difficulty_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
