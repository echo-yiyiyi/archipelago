#!/usr/bin/env python3
"""Sample balanced static injection goals, then generate configs and artifacts."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import random
import subprocess
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark.sample_inject_goal.sample_inject_goals import (
    atomic_write, load_json_array, random_balanced_samples,
)

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = BENCHMARK_DIR / "sample_inject_vector/output/selected_15_tasks_with_balanced_inject_vectors.json"
DEFAULT_GOALS = BENCHMARK_DIR / "inject_goal/inject_goal.json"
DEFAULT_OUTPUT_DIR = BENCHMARK_DIR / "final_benchmark/static_prompt_injection"
DEFAULT_GOAL_IDS = [*range(1, 9), *range(18, 25)]
EXTERNAL_GOALS = {1, 2, 3, 4, 5, 6, *range(8, 18)}
PROMPT_ONLY_INTERNAL_GOALS = {7, *range(18, 25)}


def resolve_goal_ids(requested, goals):
    """Accept numeric prefixes or full IDs, separated by spaces or commas."""
    available = [goal["goal_id"] for goal in goals]
    if len(set(available)) != len(available):
        raise ValueError("goal catalog contains duplicate goal_id values")
    selected = []
    for value in requested:
        for token in str(value).split(","):
            token = token.strip()
            matches = [g for g in available if g == token or g.split("_", 1)[0] == token]
            if len(matches) != 1:
                raise ValueError(f"unknown or ambiguous goal ID: {token!r}")
            if matches[0] in selected:
                raise ValueError(f"duplicate goal ID: {token}")
            selected.append(matches[0])
    if not selected:
        raise ValueError("at least one goal ID is required")
    return tuple(selected)


def leakage_type(goal_id):
    return "external" if int(goal_id.split("_", 1)[0]) in EXTERNAL_GOALS else "internal"


def expand_tasks(tasks, goal_ids, output_task_number, *, seed=42, script_mode=False):
    if not tasks or output_task_number <= 0 or output_task_number % len(tasks):
        raise ValueError("output task number must be a positive multiple of the input task count")
    variants = output_task_number // len(tasks)
    if variants > len(goal_ids):
        raise ValueError("goals per task cannot exceed the number of allowed goals")
    seen = set()
    grouped = defaultdict(list)
    for task in tasks:
        for field in ("task_id", "harmful_task_id", "inject_vector"):
            if not isinstance(task.get(field), str) or not task[field].strip():
                raise ValueError(f"every task needs a non-empty {field}")
        identifier = task["harmful_task_id"]
        if identifier in seen or Path(identifier).name != identifier or identifier in {".", ".."}:
            raise ValueError(f"duplicate or unsafe harmful_task_id: {identifier}")
        seen.add(identifier)
        vector = task["inject_vector"].lower().lstrip(".")
        if script_mode:
            if vector not in {"py", "pyc", "elf"}:
                raise ValueError(f"non-script inject vector: {vector}")
        elif vector in {"py", "pyc", "elf", "dynamic_prompt_injection", "dynamic_script_execution"}:
            raise ValueError(f"non-static inject vector: {vector}")
        grouped[task["inject_vector"]].append(task)

    rng = random.Random(seed)
    cycle = list(goal_ids)
    rng.shuffle(cycle)
    vectors = list(grouped)
    rng.shuffle(vectors)
    offset = 0
    assignments = {}
    # Consecutive segments of a shuffled cycle give exact balanced quotas both
    # globally and per vector, without the old fixed three-variant quotas.
    for vector in vectors:
        group = grouped[vector]
        count = len(group) * variants
        quotas = dict.fromkeys(goal_ids, 0)
        for index in range(offset, offset + count):
            quotas[cycle[index % len(cycle)]] += 1
        offset += count
        samples = random_balanced_samples(
            goal_ids, item_count=len(group), variants_per_item=variants,
            rng=rng, target_counts=quotas,
        )
        for task, sample in zip(group, samples):
            assignments[task["harmful_task_id"]] = sample
    output = []
    for task in tasks:
        for goal in assignments[task["harmful_task_id"]]:
            record = {**task, "inject_goal": goal,
                      "harmful_task_id": f"{task['harmful_task_id']}_{goal}",
                      "leakage_type": leakage_type(goal)}
            # Configs and fixtures from an earlier goal must not be reused.
            for field in ("attack_config", "attack_file", "attack_files", "populate_files"):
                record.pop(field, None)
            output.append(record)
    return output


def parse_args(argv=None, *, script_mode=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=(BENCHMARK_DIR / "sample_inject_vector/output/selected_15_tasks_with_inject_vectors.json") if script_mode else DEFAULT_INPUT)
    parser.add_argument("--output-task-number", "--output-task-count", type=int, default=30)
    parser.add_argument("--goal-ids", nargs="+", default=None if script_mode else DEFAULT_GOAL_IDS,
                        help="Numeric or full goal IDs, space/comma separated; script defaults to all catalog goals except prompt-only internal goals")
    parser.add_argument("--inject-goals", "--goals-input", type=Path, default=DEFAULT_GOALS)
    parser.add_argument("--output-dir", type=Path, default=(BENCHMARK_DIR / "final_benchmark/static_script_injection") if script_mode else DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sample-only", action="store_true", help="Write sampled JSON without API/artifact generation")
    parser.add_argument("--dataset-dir", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--add-user-prompt", action="store_true")
    return parser.parse_args(argv)


def main(argv=None, *, script_mode=False):
    args = parse_args(argv, script_mode=script_mode)
    tasks = load_json_array(args.input.resolve(), "tasks")
    goals = load_json_array(args.inject_goals.resolve(), "goals")
    requested = args.goal_ids
    if requested is None:
        requested = [g["goal_id"] for g in goals
                     if int(g["goal_id"].split("_", 1)[0]) not in PROMPT_ONLY_INTERNAL_GOALS]
    goal_ids = resolve_goal_ids(requested, goals)
    if script_mode and any(int(g.split("_", 1)[0]) in PROMPT_ONLY_INTERNAL_GOALS for g in goal_ids):
        raise ValueError("internal script goals must use args IDs 25–32, not prompt IDs 7 or 18–24")
    records = expand_tasks(tasks, goal_ids, args.output_task_number, seed=args.seed, script_mode=script_mode)
    output_dir = args.output_dir.resolve()
    sampled_path = output_dir / f"selected_{len(records)}_tasks_with_inject_goals.json"
    final_path = output_dir / f"selected_{len(records)}_tasks_with_attack_config.json"
    atomic_write(sampled_path, records)
    print(f"Sampled {len(records)} tasks: {sampled_path}", flush=True)
    print(f"Goal counts: {dict(Counter(r['inject_goal'] for r in records))}", flush=True)
    if args.sample_only:
        return 0
    command = [sys.executable, "-m", "benchmark.generate_attack_config.generate",
               str(sampled_path), "--output", str(final_path),
               "--inject-goals", str(args.inject_goals.resolve())]
    for flag, value in (("--dataset-dir", args.dataset_dir), ("--model", args.model),
                        ("--reasoning-effort", args.reasoning_effort)):
        if value is not None:
            command.extend([flag, str(value.resolve() if isinstance(value, Path) else value)])
    if args.add_user_prompt:
        command.append("--add-user-prompt")
    subprocess.run(command, cwd=BENCHMARK_DIR.parent, check=True)
    final_records = load_json_array(final_path, "generated tasks")
    if Counter(r["harmful_task_id"] for r in final_records) != Counter(r["harmful_task_id"] for r in records):
        raise ValueError("generator output does not match sampled tasks")
    for record in final_records:
        record["leakage_type"] = leakage_type(record["inject_goal"])
        if not isinstance(record.get("attack_config"), dict) or not record.get("populate_files"):
            raise ValueError(f"incomplete generated task: {record['harmful_task_id']}")
        record["attack_config"]["leakage_type"] = record["leakage_type"]
        for relative_path in [record["attack_file"], *record["populate_files"]]:
            artifact = (output_dir / relative_path).resolve()
            if not artifact.is_relative_to(output_dir) or not artifact.is_file():
                raise ValueError(f"missing or out-of-bundle artifact: {relative_path}")
    atomic_write(final_path, final_records)
    print(f"Generated {len(final_records)} complete tasks: {final_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
