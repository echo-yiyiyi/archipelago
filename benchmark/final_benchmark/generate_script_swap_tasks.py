#!/usr/bin/env python3
"""Generate separate args/no_args script-swap bundles with user-prompt helpers."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import random
import subprocess
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark.final_benchmark.generate_static_prompt_injection_tasks import (
    BENCHMARK_DIR, DEFAULT_GOALS, atomic_write, leakage_type, load_json_array,
    resolve_goal_ids,
)

ARGS_GOALS = [13, 14, 15, 16, 17, 25, 26, 27, 28, 29, 30, 31, 32]
NO_ARGS_GOALS = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12]
VECTORS = ("py", "pyc", "elf")
DEFAULT_INPUT = BENCHMARK_DIR / "sample_inject_vector/output/selected_15_tasks_with_inject_vectors.json"
DEFAULT_OUTPUT = BENCHMARK_DIR / "final_benchmark/user_prompt_script_swap"


def sample_tasks(tasks, goals, count, *, seed=42, vector_offset=0):
    if not tasks or not goals or not 0 < count <= len(tasks) * len(goals):
        raise ValueError("count must be positive and cannot exceed input tasks × allowed goals")
    identifiers = [task.get("task_id") for task in tasks]
    if any(not isinstance(t, str) or not t.strip() or Path(t).name != t or t in {".", ".."}
           for t in identifiers) or len(set(identifiers)) != len(tasks):
        raise ValueError("input must contain unique, non-empty, safe task_id values")
    rng = random.Random(seed)
    ordered_tasks, cycle = list(tasks), list(goals)
    rng.shuffle(ordered_tasks)
    rng.shuffle(cycle)
    rows = []
    quotient, remainder = divmod(count, len(tasks))
    # Contiguous goal-cycle segments guarantee balanced global goal counts and
    # no repeated goal within an original task, including non-multiple counts.
    for index, task in enumerate(ordered_tasks):
        for _ in range(quotient + (index < remainder)):
            goal = cycle[len(rows) % len(cycle)]
            row = dict(task)
            for key in ("attack_config", "attack_file", "attack_files", "populate_files",
                        "watcher_file", "watcher_config", "inject_goal", "harmful_task_id"):
                row.pop(key, None)
            row.update(inject_goal=goal, add_user_prompt=True, no_key_words=False,
                       leakage_type=leakage_type(goal))
            rows.append(row)
    vectors = list(VECTORS)
    random.Random(seed).shuffle(vectors)
    offset = vector_offset
    # Fresh vector sampling, balanced globally and within each goal. Continuing
    # the cycle in the next bundle also balances their combined vector counts.
    for goal in cycle:
        group = [row for row in rows if row["inject_goal"] == goal]
        rng.shuffle(group)
        for row in group:
            row["inject_vector"] = vectors[offset % len(vectors)]
            row["harmful_task_id"] = f"{row['task_id']}_{row['inject_vector']}_{goal}"
            offset += 1
    return rows


def generate_bundle(records, directory, args):
    sampled = directory / f"selected_{len(records)}_tasks_with_inject_goals.json"
    final = directory / f"selected_{len(records)}_tasks_with_attack_config.json"
    atomic_write(sampled, records)
    print(f"{directory.name}: {len(records)} tasks; vectors={dict(Counter(r['inject_vector'] for r in records))}", flush=True)
    if args.sample_only:
        return
    command = [sys.executable, "-m", "benchmark.generate_attack_config.generate",
               str(sampled), "--output", str(final), "--inject-goals", str(args.inject_goals.resolve())]
    if all(r["add_user_prompt"] for r in records):
        command.append("--add-user-prompt")
    for flag, value in (("--dataset-dir", args.dataset_dir), ("--model", args.model),
                        ("--reasoning-effort", args.reasoning_effort)):
        if value is not None:
            command.extend([flag, str(value.resolve() if isinstance(value, Path) else value)])
    subprocess.run(command, cwd=BENCHMARK_DIR.parent, check=True)
    generated = load_json_array(final, "generated tasks")
    expected = {r["harmful_task_id"]: r for r in records}
    if Counter(r["harmful_task_id"] for r in generated) != Counter(expected.keys()):
        raise ValueError("generator output does not match sampled task IDs")
    for row in generated:
        original = expected[row["harmful_task_id"]]
        for field in ("inject_goal", "inject_vector", "add_user_prompt", "no_key_words"):
            if row.get(field) != original[field]:
                raise ValueError(f"generator changed {field}: {row['harmful_task_id']}")
        if not isinstance(row.get("attack_config"), dict) or not row.get("populate_files"):
            raise ValueError(f"incomplete generated task: {row['harmful_task_id']}")
        row["leakage_type"] = leakage_type(row["inject_goal"])
        row["attack_config"]["leakage_type"] = row["leakage_type"]
        if bool(row["attack_config"].get("add_user_prompt", False)) != original["add_user_prompt"]:
            raise ValueError("generated attack config changed add_user_prompt")
        for relative in [row["attack_file"], *row["populate_files"]]:
            path = (directory / relative).resolve()
            if not path.is_relative_to(directory) or not path.is_file():
                raise ValueError(f"missing or out-of-bundle artifact: {relative}")
    atomic_write(final, generated)
    print(f"Generated {final}", flush=True)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("args_count", nargs="?", type=int, default=15)
    parser.add_argument("no_args_count", nargs="?", type=int, default=15)
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
    # Validate both groups before starting generation or writing either output.
    groups = [
        ("args", sample_tasks(tasks, resolve_goal_ids(ARGS_GOALS, catalog), args.args_count, seed=args.seed)),
        ("no_args", sample_tasks(tasks, resolve_goal_ids(NO_ARGS_GOALS, catalog), args.no_args_count,
                                 seed=args.seed, vector_offset=args.args_count)),
    ]
    for name, records in groups:
        generate_bundle(records, args.output_dir.resolve() / name, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
