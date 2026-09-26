#!/usr/bin/env python3
"""Generate user-prompt suffix-plant tasks with args goals and generic names."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark.final_benchmark.generate_script_swap_tasks import (
    ARGS_GOALS, BENCHMARK_DIR, DEFAULT_GOALS, DEFAULT_INPUT,
    generate_bundle, load_json_array, resolve_goal_ids, sample_tasks,
)

DEFAULT_OUTPUT = BENCHMARK_DIR / "final_benchmark/user_prompt_suffix_plant"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-task-number", "--output-task-count", type=int, default=30)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--inject-goals", type=Path, default=DEFAULT_GOALS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sample-only", action="store_true")
    parser.add_argument("--dataset-dir", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    tasks = load_json_array(args.input.resolve(), "tasks")
    catalog = load_json_array(args.inject_goals.resolve(), "goals")
    goals = resolve_goal_ids(ARGS_GOALS, catalog)
    records = sample_tasks(tasks, goals, args.output_task_number, seed=args.seed)
    for record in records:
        record["no_key_words"] = True
    generate_bundle(records, args.output_dir.resolve(), args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
