#!/usr/bin/env python3
"""Generate one harmful-task JSON record from a selected APEX task ID."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .prompt import generate_harmful_task
except ImportError:  # Support direct execution from the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from archipelago.benchmark.generate_attack_config.prompt import (
        generate_harmful_task,
    )


OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id", help="task_id from selected_15_tasks_with_keywords.json")
    parser.add_argument(
        "--inject-goal-id",
        default="1_email_send_file",
        help="goal_id from inject_goal/inject_goal.json (default: %(default)s)",
    )
    parser.add_argument("--dataset-dir", type=Path)
    parser.add_argument("--selected-tasks", type=Path)
    parser.add_argument("--inject-goals", type=Path)
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    record = generate_harmful_task(
        args.task_id,
        args.inject_goal_id,
        args.dataset_dir,
        selected_tasks_path=args.selected_tasks,
        inject_goals_path=args.inject_goals,
        reasoning_effort=args.reasoning_effort,
    )
    output = args.output or (
        OUTPUT_DIR / f"{record['harmful_task_id']}.json"
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    # Keep the same top-level array shape as selected_15_tasks_with_keywords.json.
    temporary.write_text(
        json.dumps([record], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
