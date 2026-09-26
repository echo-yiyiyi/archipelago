#!/usr/bin/env python3
"""Assign balanced py, pyc, and elf injection vectors to selected tasks."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = (
    SCRIPT_DIR.parent
    / "extract_key_words"
    / "output"
    / "selected_15_keywords_extraction.json"
)
DEFAULT_OUTPUT = SCRIPT_DIR / "output" / "selected_15_tasks_with_inject_vectors.json"
INJECT_VECTORS = ("py", "pyc", "elf")


def load_tasks(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"input JSON does not exist: {path}")
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError("input JSON must contain a top-level array")
    if not all(isinstance(task, dict) for task in tasks):
        raise ValueError("every task must be a JSON object")

    task_ids = [task.get("task_id") for task in tasks]
    if not all(isinstance(task_id, str) and task_id for task_id in task_ids):
        raise ValueError("every task must have a non-empty string task_id")
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("task_id values must be unique")
    return tasks


def assign_inject_vectors(
    tasks: list[dict[str, Any]], *, per_vector: int = 5, seed: int = 42
) -> list[dict[str, Any]]:
    if per_vector < 1:
        raise ValueError("per_vector must be at least 1")
    expected_count = per_vector * len(INJECT_VECTORS)
    if len(tasks) != expected_count:
        raise ValueError(
            f"expected {expected_count} tasks ({per_vector} per vector), "
            f"got {len(tasks)}"
        )

    assignments = [
        vector
        for vector in INJECT_VECTORS
        for _ in range(per_vector)
    ]
    random.Random(seed).shuffle(assignments)

    output = []
    for task, vector in zip(tasks, assignments, strict=True):
        task_id = task["task_id"]
        output.append(
            {
                **task,
                "inject_vector": vector,
                "harmful_task_id": f"{task_id}_{vector}",
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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-vector", type=int, default=5)
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed used for reproducible assignment (default: %(default)s).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tasks = load_tasks(args.input.resolve())
    output = assign_inject_vectors(
        tasks,
        per_vector=args.per_vector,
        seed=args.seed,
    )
    output_path = args.output.resolve()
    atomic_write(output_path, output)

    counts = {
        vector: sum(item["inject_vector"] == vector for item in output)
        for vector in INJECT_VECTORS
    }
    print(f"Wrote {len(output)} tasks to {output_path}; vectors={counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
