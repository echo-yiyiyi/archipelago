#!/usr/bin/env python3
"""Summarize first-choice and top-three file-type ranking distributions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from rank_file_types import ALLOWED_FILE_TYPES, validate_file_types


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "output" / "selected_15_tasks_with_file_type_ranking.json"
DEFAULT_OUTPUT = SCRIPT_DIR / "output" / "file_type_ranking_stats.json"


def load_ranked_tasks(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"input JSON does not exist: {path}")
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("input JSON must contain a non-empty top-level array")

    seen_task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("every task must be a JSON object")
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("every task must have a non-empty string task_id")
        if task_id in seen_task_ids:
            raise ValueError(f"duplicate task_id: {task_id}")
        seen_task_ids.add(task_id)
        validate_file_types(task.get("file_type_ranking"))
    return tasks


def _ordered_counts(counter: Counter[str]) -> list[tuple[str, int]]:
    order = {file_type: index for index, file_type in enumerate(ALLOWED_FILE_TYPES)}
    return sorted(
        ((file_type, counter[file_type]) for file_type in ALLOWED_FILE_TYPES),
        key=lambda item: (-item[1], order[item[0]]),
    )


def _rank_distribution(
    counter: Counter[str], total_tasks: int
) -> list[dict[str, Any]]:
    return [
        {
            "file_type": file_type,
            "count": count,
            "percentage_of_tasks": round(count / total_tasks * 100, 2),
        }
        for file_type, count in _ordered_counts(counter)
    ]


def analyze_rankings(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    if not tasks:
        raise ValueError("tasks must not be empty")
    total_tasks = len(tasks)
    total_top_three_slots = total_tasks * 3
    by_rank_counters = [Counter() for _ in ALLOWED_FILE_TYPES]
    top_three_counter: Counter[str] = Counter()

    task_rankings = []
    for task in tasks:
        ranking = validate_file_types(task.get("file_type_ranking"))
        for index, file_type in enumerate(ranking):
            by_rank_counters[index][file_type] += 1
            if index < 3:
                top_three_counter[file_type] += 1
        task_rankings.append(
            {
                "task_id": task["task_id"],
                "first_choice": ranking[0],
                "top_three": ranking[:3],
                "full_ranking": ranking,
            }
        )

    top_three_distribution = [
        {
            "file_type": file_type,
            "count": count,
            "percentage_of_tasks": round(count / total_tasks * 100, 2),
            "percentage_of_top_three_slots": round(
                count / total_top_three_slots * 100, 2
            ),
        }
        for file_type, count in _ordered_counts(top_three_counter)
    ]

    return {
        "total_tasks": total_tasks,
        "total_top_three_slots": total_top_three_slots,
        "first_choice_distribution": _rank_distribution(
            by_rank_counters[0], total_tasks
        ),
        "top_three_distribution": top_three_distribution,
        "distribution_by_rank": {
            f"rank_{index + 1}": _rank_distribution(counter, total_tasks)
            for index, counter in enumerate(by_rank_counters)
        },
        "task_rankings": task_rankings,
    }


def atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def print_summary(stats: dict[str, Any]) -> None:
    print(f"Tasks: {stats['total_tasks']}")
    print("\nFirst choice distribution:")
    for row in stats["first_choice_distribution"]:
        print(
            f"  {row['file_type']:8} {row['count']:2} "
            f"({row['percentage_of_tasks']:6.2f}% of tasks)"
        )

    print("\nTop-three inclusion distribution:")
    for row in stats["top_three_distribution"]:
        print(
            f"  {row['file_type']:8} {row['count']:2} "
            f"({row['percentage_of_tasks']:6.2f}% of tasks; "
            f"{row['percentage_of_top_three_slots']:6.2f}% of slots)"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tasks = load_ranked_tasks(args.input.resolve())
    stats = analyze_rankings(tasks)
    output_path = args.output.resolve()
    atomic_write(output_path, stats)
    print_summary(stats)
    print(f"\nOutput: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
