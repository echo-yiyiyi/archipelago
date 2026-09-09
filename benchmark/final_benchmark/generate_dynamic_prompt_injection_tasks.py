#!/usr/bin/env python3
"""Generate balanced dynamic prompt-injection configs and watcher bundles."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark.final_benchmark.generate_script_swap_tasks import (
    ARGS_GOALS, BENCHMARK_DIR, DEFAULT_GOALS, generate_bundle, load_json_array,
    resolve_goal_ids, sample_tasks,
)
from benchmark.final_benchmark.generate_static_prompt_injection_tasks import DEFAULT_INPUT, DEFAULT_GOAL_IDS

DEFAULT_OUTPUT = BENCHMARK_DIR / 'final_benchmark/dynamic_prompt_injection'


def parse_args(argv=None, *, script_mode=False):
    parser = argparse.ArgumentParser(description="Generate dynamic script-execution watcher bundles with args goals." if script_mode else __doc__)
    parser.add_argument('--output-task-number', '--output-task-count', type=int, default=30)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--inject-goals', type=Path, default=DEFAULT_GOALS)
    parser.add_argument('--output-dir', type=Path, default=(BENCHMARK_DIR / 'final_benchmark/dynamic_script_injection') if script_mode else DEFAULT_OUTPUT)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--sample-only', action='store_true')
    parser.add_argument('--dataset-dir', type=Path)
    parser.add_argument('--model')
    parser.add_argument('--reasoning-effort')
    return parser.parse_args(argv)


def main(argv=None, *, script_mode=False):
    args = parse_args(argv, script_mode=script_mode)
    tasks = load_json_array(args.input.resolve(), 'tasks')
    catalog = load_json_array(args.inject_goals.resolve(), 'goals')
    goals = resolve_goal_ids(ARGS_GOALS if script_mode else DEFAULT_GOAL_IDS, catalog)
    count = args.output_task_number
    if script_mode:
        if count <= 0 or count % 2:
            raise ValueError('output task number must be a positive even number for paired groups')
        count //= 2
    records = sample_tasks(tasks, goals, count, seed=args.seed)
    vector = 'dynamic_script_execution' if script_mode else 'dynamic_prompt_injection'
    for row in records:
        row.update(inject_vector=vector, add_user_prompt=False,
                   no_key_words=True,
                   harmful_task_id=f"{row['task_id']}_{vector}_{row['inject_goal']}")
    if script_mode:
        for enabled in (True, False):
            group = deepcopy(records)
            for row in group:
                row['add_user_prompt'] = enabled
            generate_bundle(group, args.output_dir.resolve() / f'add_user_prompt_{str(enabled).lower()}', args)
    else:
        generate_bundle(records, args.output_dir.resolve(), args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
