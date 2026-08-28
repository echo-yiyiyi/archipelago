#!/usr/bin/env python3
"""Assign ranked file types evenly while minimizing preference loss."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rank_file_types import ALLOWED_FILE_TYPES, validate_file_types


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TASKS_INPUT = (
    SCRIPT_DIR.parent
    / "extract_key_words"
    / "output"
    / "selected_15_keywords_extraction.json"
)
DEFAULT_RANKINGS_INPUT = (
    SCRIPT_DIR / "output" / "selected_15_tasks_with_file_type_ranking.json"
)
DEFAULT_OUTPUT = (
    SCRIPT_DIR / "output" / "selected_15_tasks_with_balanced_inject_vectors.json"
)
RANK_COSTS = (0, 1, 3, 10, 30, 80, 200)


def load_json_array(path: Path, description: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"{description} JSON does not exist: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{description} JSON must contain a top-level array")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"every {description} row must be a JSON object")
    return rows


def load_inputs(
    tasks_path: Path, rankings_path: Path
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    tasks = load_json_array(tasks_path, "tasks")
    ranking_rows = load_json_array(rankings_path, "rankings")

    task_ids = [task.get("task_id") for task in tasks]
    if not all(isinstance(task_id, str) and task_id for task_id in task_ids):
        raise ValueError("every task must have a non-empty string task_id")
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("task task_id values must be unique")

    rankings: dict[str, list[str]] = {}
    for row in ranking_rows:
        task_id = row.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("every ranking must have a non-empty string task_id")
        if task_id in rankings:
            raise ValueError(f"duplicate ranking task_id: {task_id}")
        rankings[task_id] = validate_file_types(row.get("file_type_ranking"))

    missing = [task_id for task_id in task_ids if task_id not in rankings]
    extra = sorted(set(rankings) - set(task_ids))
    if missing:
        raise ValueError(f"missing rankings for task IDs: {', '.join(missing)}")
    if extra:
        raise ValueError(f"rankings contain unknown task IDs: {', '.join(extra)}")
    return tasks, rankings


def balanced_bounds(task_count: int, type_count: int) -> tuple[int, int]:
    minimum, remainder = divmod(task_count, type_count)
    maximum = minimum + (1 if remainder else 0)
    return minimum, maximum


def assign_balanced_file_types(
    tasks: list[dict[str, Any]], rankings: dict[str, list[str]]
) -> dict[str, str]:
    """Return the exact balanced assignment with the best lexicographic cost."""
    if not tasks:
        raise ValueError("tasks must not be empty")
    minimum, maximum = balanced_bounds(len(tasks), len(ALLOWED_FILE_TYPES))
    if minimum == 0:
        raise ValueError("there must be at least one task per file type")

    # state -> ((outside_top_three_count, total_rank_cost), assignment_indices)
    initial_counts = (0,) * len(ALLOWED_FILE_TYPES)
    states: dict[tuple[int, ...], tuple[tuple[int, int], tuple[int, ...]]] = {
        initial_counts: ((0, 0), ())
    }

    for task in tasks:
        task_id = task["task_id"]
        ranking = rankings[task_id]
        rank_by_type = {
            file_type: rank for rank, file_type in enumerate(ranking)
        }
        next_states: dict[
            tuple[int, ...], tuple[tuple[int, int], tuple[int, ...]]
        ] = {}

        for counts, (objective, assignment) in states.items():
            for type_index, file_type in enumerate(ALLOWED_FILE_TYPES):
                if counts[type_index] >= maximum:
                    continue
                rank = rank_by_type[file_type]
                new_counts_list = list(counts)
                new_counts_list[type_index] += 1
                new_counts = tuple(new_counts_list)
                new_objective = (
                    objective[0] + int(rank >= 3),
                    objective[1] + RANK_COSTS[rank],
                )
                candidate = (new_objective, assignment + (type_index,))
                incumbent = next_states.get(new_counts)
                if incumbent is None or candidate < incumbent:
                    next_states[new_counts] = candidate
        states = next_states

    feasible = [
        (objective, assignment)
        for counts, (objective, assignment) in states.items()
        if all(minimum <= count <= maximum for count in counts)
    ]
    if not feasible:
        raise RuntimeError("no balanced assignment satisfies the capacity bounds")

    _, best_assignment = min(feasible)
    return {
        task["task_id"]: ALLOWED_FILE_TYPES[type_index]
        for task, type_index in zip(tasks, best_assignment, strict=True)
    }


def build_output(
    tasks: list[dict[str, Any]], assignments: dict[str, str]
) -> list[dict[str, Any]]:
    output = []
    for task in tasks:
        task_id = task["task_id"]
        inject_vector = assignments[task_id]
        output.append(
            {
                **task,
                "inject_vector": inject_vector,
                "harmful_task_id": f"{task_id}_{inject_vector}",
            }
        )
    return output


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
    parser.add_argument("--tasks-input", type=Path, default=DEFAULT_TASKS_INPUT)
    parser.add_argument(
        "--rankings-input", type=Path, default=DEFAULT_RANKINGS_INPUT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tasks, rankings = load_inputs(
        args.tasks_input.resolve(), args.rankings_input.resolve()
    )
    assignments = assign_balanced_file_types(tasks, rankings)
    output_path = args.output.resolve()
    atomic_write(output_path, build_output(tasks, assignments))

    counts = {
        file_type: sum(value == file_type for value in assignments.values())
        for file_type in ALLOWED_FILE_TYPES
    }
    assigned_ranks = [
        rankings[task["task_id"]].index(assignments[task["task_id"]]) + 1
        for task in tasks
    ]
    print(f"Wrote {len(tasks)} tasks to {output_path}")
    print(f"Counts: {counts}")
    print(
        f"Top-three assignments: {sum(rank <= 3 for rank in assigned_ranks)}/"
        f"{len(assigned_ranks)}; assigned ranks={assigned_ranks}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
