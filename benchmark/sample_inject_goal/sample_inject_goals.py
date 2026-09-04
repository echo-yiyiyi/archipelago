#!/usr/bin/env python3
"""Create three randomly balanced inject-goal variants for every harmful task."""

from __future__ import annotations

import argparse
import itertools
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = SCRIPT_DIR.parent
DEFAULT_INPUT = (
    BENCHMARK_DIR
    / "sample_inject_vector"
    / "output"
    / "selected_30_tasks_with_inject_vectors.json"
)
DEFAULT_GOALS_INPUT = BENCHMARK_DIR / "inject_goal" / "inject_goal.json"
DEFAULT_OUTPUT = SCRIPT_DIR / "output" / "selected_90_tasks_with_inject_goals.json"
EXECUTABLE_VECTORS = {"py", "pyc", "elf"}
FILE_TYPE_GOAL_IDS = (
    "1_email_send_file",
    "2_email_send_prompt",
    "3_email_forward_otp",
    "4_email_broadcast_link",
    "5_chat_send_link",
    "6_chat_to_achieve_url",
    "7_calendar_create_event",
    "8_fetch_external_link",
)
EXECUTABLE_GOAL_IDS = FILE_TYPE_GOAL_IDS + (
    "9_url_query_params",
    "10_chat_send_ssh",
    "11_terminal_remote_script",
    "12_terminal_cron_setup",
)
FILE_TYPE_TARGET_COUNTS = {
    "1_email_send_file": 6,
    "2_email_send_prompt": 5,
    "3_email_forward_otp": 6,
    "4_email_broadcast_link": 5,
    "5_chat_send_link": 6,
    "6_chat_to_achieve_url": 5,
    "7_calendar_create_event": 6,
    "8_fetch_external_link": 6,
}
EXECUTABLE_TARGET_COUNTS = {
    "1_email_send_file": 3,
    "2_email_send_prompt": 3,
    "3_email_forward_otp": 3,
    "4_email_broadcast_link": 3,
    "5_chat_send_link": 3,
    "6_chat_to_achieve_url": 3,
    "7_calendar_create_event": 3,
    "8_fetch_external_link": 3,
    "9_url_query_params": 5,
    "10_chat_send_ssh": 6,
    "11_terminal_remote_script": 5,
    "12_terminal_cron_setup": 5,
}


def load_json_array(path: Path, description: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"{description} JSON does not exist: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{description} JSON must contain a top-level array")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"every {description} row must be a JSON object")
    return rows


def validate_inputs(
    tasks: list[dict[str, Any]], goals: list[dict[str, Any]]
) -> None:
    harmful_task_ids = []
    for task in tasks:
        if not isinstance(task.get("task_id"), str) or not task["task_id"]:
            raise ValueError("every task must have a non-empty task_id")
        if not isinstance(task.get("inject_vector"), str) or not task["inject_vector"]:
            raise ValueError(f"task {task['task_id']} has no inject_vector")
        harmful_task_id = task.get("harmful_task_id")
        if not isinstance(harmful_task_id, str) or not harmful_task_id:
            raise ValueError(f"task {task['task_id']} has no harmful_task_id")
        harmful_task_ids.append(harmful_task_id)
    if len(set(harmful_task_ids)) != len(harmful_task_ids):
        raise ValueError("input harmful_task_id values must be unique")

    available_goal_ids = [goal.get("goal_id") for goal in goals]
    if not all(isinstance(goal_id, str) and goal_id for goal_id in available_goal_ids):
        raise ValueError("every inject goal must have a non-empty goal_id")
    if len(set(available_goal_ids)) != len(available_goal_ids):
        raise ValueError("inject goal_id values must be unique")
    missing = sorted(set(EXECUTABLE_GOAL_IDS) - set(available_goal_ids))
    if missing:
        raise ValueError(f"inject_goal.json is missing goal IDs: {', '.join(missing)}")


def random_balanced_samples(
    goal_ids: tuple[str, ...],
    *,
    item_count: int,
    variants_per_item: int,
    rng: random.Random,
    forbidden_by_item: list[set[str]] | None = None,
    target_counts: dict[str, int] | None = None,
    max_attempts: int = 10_000,
) -> list[list[str]]:
    """Randomly sample distinct goals per item with globally balanced counts."""
    if item_count < 1 or variants_per_item < 1:
        raise ValueError("item_count and variants_per_item must be positive")
    if variants_per_item > len(goal_ids):
        raise ValueError("variants_per_item cannot exceed the number of goals")
    if forbidden_by_item is None:
        forbidden_by_item = [set() for _ in range(item_count)]
    if len(forbidden_by_item) != item_count:
        raise ValueError("forbidden_by_item must match item_count")
    if any(
        len(set(goal_ids) - forbidden) < variants_per_item
        for forbidden in forbidden_by_item
    ):
        raise ValueError("an item does not have enough allowed distinct goals")

    total_variants = item_count * variants_per_item
    base_count, extra_count = divmod(total_variants, len(goal_ids))
    if target_counts is not None:
        if set(target_counts) != set(goal_ids):
            raise ValueError("target_counts must contain exactly the allowed goals")
        if any(count < 0 for count in target_counts.values()):
            raise ValueError("target counts must be non-negative")
        if sum(target_counts.values()) != total_variants:
            raise ValueError("target counts must sum to the total variant count")

    for _ in range(max_attempts):
        if target_counts is None:
            extra_goals = set(rng.sample(list(goal_ids), extra_count))
            remaining = {
                goal_id: base_count + int(goal_id in extra_goals)
                for goal_id in goal_ids
            }
        else:
            remaining = target_counts.copy()
        item_order = list(range(item_count))
        rng.shuffle(item_order)
        samples: list[list[str] | None] = [None] * item_count
        failed = False

        for item_index in item_order:
            sample: list[str] = []
            for _ in range(variants_per_item):
                candidates = [
                    goal_id
                    for goal_id in goal_ids
                    if remaining[goal_id] > 0
                    and goal_id not in forbidden_by_item[item_index]
                    and goal_id not in sample
                ]
                if not candidates:
                    failed = True
                    break
                selected = rng.choices(
                    candidates,
                    weights=[remaining[goal_id] for goal_id in candidates],
                    k=1,
                )[0]
                sample.append(selected)
                remaining[selected] -= 1
            if failed:
                break
            samples[item_index] = sample

        if not failed and all(count == 0 for count in remaining.values()):
            return [sample for sample in samples if sample is not None]
    raise RuntimeError("could not produce distinct balanced random samples")


def build_even_vector_quotas(
    tasks: list[dict[str, Any]],
    goal_ids: tuple[str, ...],
    global_target_counts: dict[str, int],
    *,
    rng: random.Random,
) -> dict[str, dict[str, int]]:
    """Randomly construct exact vector-level quotas differing by at most one."""
    tasks_by_vector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        tasks_by_vector[task["inject_vector"]].append(task)

    vector_specs: dict[str, tuple[int, int, int]] = {}
    for vector, vector_tasks in tasks_by_vector.items():
        total = len(vector_tasks) * 3
        lower, extra_slots = divmod(total, len(goal_ids))
        vector_specs[vector] = (lower, lower + int(extra_slots > 0), extra_slots)

    vectors = list(tasks_by_vector)
    rng.shuffle(vectors)
    result: dict[str, dict[str, int]] = {}

    def search(position: int, remaining: dict[str, int]) -> bool:
        if position == len(vectors):
            return all(count == 0 for count in remaining.values())

        vector = vectors[position]
        lower, _, extra_slots = vector_specs[vector]
        extra_choices = list(itertools.combinations(goal_ids, extra_slots))
        rng.shuffle(extra_choices)
        future_vectors = vectors[position + 1 :]

        for extra_goals_tuple in extra_choices:
            extra_goals = set(extra_goals_tuple)
            quota = {
                goal_id: lower + int(goal_id in extra_goals)
                for goal_id in goal_ids
            }
            if any(quota[goal_id] > remaining[goal_id] for goal_id in goal_ids):
                continue
            next_remaining = {
                goal_id: remaining[goal_id] - quota[goal_id]
                for goal_id in goal_ids
            }
            feasible = True
            for goal_id in goal_ids:
                minimum_future = sum(
                    vector_specs[future_vector][0]
                    for future_vector in future_vectors
                )
                maximum_future = sum(
                    vector_specs[future_vector][1]
                    for future_vector in future_vectors
                )
                if not minimum_future <= next_remaining[goal_id] <= maximum_future:
                    feasible = False
                    break
            if not feasible:
                continue
            result[vector] = quota
            if search(position + 1, next_remaining):
                return True
            result.pop(vector, None)
        return False

    if not search(0, global_target_counts.copy()):
        raise RuntimeError("could not construct balanced vector-level goal quotas")
    return result


def assign_tasks_with_vector_quotas(
    tasks: list[dict[str, Any]],
    goal_ids: tuple[str, ...],
    vector_quotas: dict[str, dict[str, int]],
    *,
    rng: random.Random,
    forbidden_by_task_id: dict[str, set[str]] | None = None,
) -> dict[str, list[str]]:
    """Randomly assign three goals per task while exactly meeting vector quotas."""
    forbidden_by_task_id = forbidden_by_task_id or {}
    tasks_by_vector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        tasks_by_vector[task["inject_vector"]].append(task)

    assignments: dict[str, list[str]] = {}
    vector_order = list(tasks_by_vector)
    rng.shuffle(vector_order)
    for vector in vector_order:
        vector_tasks = tasks_by_vector[vector]
        task_order = vector_tasks.copy()
        rng.shuffle(task_order)
        remaining = vector_quotas[vector].copy()
        vector_assignments: dict[str, list[str]] = {}

        def search(position: int) -> bool:
            if position == len(task_order):
                return all(count == 0 for count in remaining.values())
            task = task_order[position]
            forbidden = forbidden_by_task_id.get(task["task_id"], set())
            candidates = [
                combination
                for combination in itertools.combinations(goal_ids, 3)
                if not (set(combination) & forbidden)
                and all(remaining[goal_id] > 0 for goal_id in combination)
            ]
            rng.shuffle(candidates)
            future_tasks = task_order[position + 1 :]

            for combination in candidates:
                for goal_id in combination:
                    remaining[goal_id] -= 1
                feasible = all(
                    remaining[goal_id]
                    <= sum(
                        goal_id
                        not in forbidden_by_task_id.get(
                            future_task["task_id"], set()
                        )
                        for future_task in future_tasks
                    )
                    for goal_id in goal_ids
                )
                if feasible:
                    selected = list(combination)
                    rng.shuffle(selected)
                    vector_assignments[task["harmful_task_id"]] = selected
                    if search(position + 1):
                        return True
                    vector_assignments.pop(task["harmful_task_id"], None)
                for goal_id in combination:
                    remaining[goal_id] += 1
            return False

        if not search(0):
            raise RuntimeError(f"could not assign goals within vector {vector}")
        assignments.update(vector_assignments)
    return assignments


def expand_tasks(
    tasks: list[dict[str, Any]], *, seed: int
) -> list[dict[str, Any]]:
    file_tasks = [
        task for task in tasks if task["inject_vector"] not in EXECUTABLE_VECTORS
    ]
    executable_tasks = [
        task for task in tasks if task["inject_vector"] in EXECUTABLE_VECTORS
    ]
    file_by_task_id = {task["task_id"]: task for task in file_tasks}
    executable_by_task_id = {task["task_id"]: task for task in executable_tasks}
    if len(file_by_task_id) != len(file_tasks):
        raise ValueError("each task_id must have exactly one file-type vector")
    if len(executable_by_task_id) != len(executable_tasks):
        raise ValueError("each task_id must have exactly one executable vector")
    if set(file_by_task_id) != set(executable_by_task_id):
        raise ValueError(
            "file-type and executable vectors must contain the same task_id values"
        )

    rng = random.Random(seed)
    file_vector_quotas = build_even_vector_quotas(
        file_tasks,
        FILE_TYPE_GOAL_IDS,
        FILE_TYPE_TARGET_COUNTS,
        rng=rng,
    )
    executable_vector_quotas = build_even_vector_quotas(
        executable_tasks,
        EXECUTABLE_GOAL_IDS,
        EXECUTABLE_TARGET_COUNTS,
        rng=rng,
    )
    samples_by_harmful_task_id = assign_tasks_with_vector_quotas(
        file_tasks,
        FILE_TYPE_GOAL_IDS,
        file_vector_quotas,
        rng=rng,
    )
    file_goals_by_task_id = {
        task["task_id"]: set(samples_by_harmful_task_id[task["harmful_task_id"]])
        for task in file_tasks
    }
    samples_by_harmful_task_id.update(
        assign_tasks_with_vector_quotas(
            executable_tasks,
            EXECUTABLE_GOAL_IDS,
            executable_vector_quotas,
            rng=rng,
            forbidden_by_task_id=file_goals_by_task_id,
        )
    )

    output = []
    for task in tasks:
        for inject_goal in samples_by_harmful_task_id[task["harmful_task_id"]]:
            output.append(
                {
                    **task,
                    "inject_goal": inject_goal,
                    "harmful_task_id": f"{task['harmful_task_id']}_{inject_goal}",
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
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--goals-input", type=Path, default=DEFAULT_GOALS_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed for reproducible random sampling (default: %(default)s).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tasks = load_json_array(args.input.resolve(), "tasks")
    goals = load_json_array(args.goals_input.resolve(), "inject goals")
    validate_inputs(tasks, goals)
    output = expand_tasks(tasks, seed=args.seed)
    output_path = args.output.resolve()
    atomic_write(output_path, output)

    file_goal_counts = Counter(
        task["inject_goal"]
        for task in output
        if task["inject_vector"] not in EXECUTABLE_VECTORS
    )
    executable_goal_counts = Counter(
        task["inject_goal"]
        for task in output
        if task["inject_vector"] in EXECUTABLE_VECTORS
    )
    print(f"Wrote {len(output)} tasks to {output_path}")
    print(f"File-type goal counts: {dict(sorted(file_goal_counts.items()))}")
    print(f"Executable goal counts: {dict(sorted(executable_goal_counts.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
