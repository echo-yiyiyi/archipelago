#!/usr/bin/env python3
"""Cross the 15 subset attack conditions with difficulty, keeping domain/set fixed."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from benchmark.rebuttal.more_tasks.generate_final_15_more import (
    ENDPOINT, FLAGS, MODEL, digest, read, validate_row, write,
)

SUBSET = HERE.parent / "subset"
LEVELS = ("easy", "medium", "hard")
TASK_FIELDS = ("task_id", "domain", "turns", "difficulty", "prompt", "keywords")


def design(source, taxonomy):
    if len(source) != 15 or len({r["task_id"] for r in source}) != 15:
        raise ValueError("Expected the original 15 unique subset tasks")
    metadata = {r["harmful_task_id"]: r for r in taxonomy["tasks"]}
    buckets = defaultdict(list)
    for row in source:
        buckets[row["domain"], row["difficulty"]].append(row)
    expected_counts = {(domain, level): 3 if level == "easy" else 1
                       for domain in ("banking", "law", "consulting") for level in LEVELS}
    if {k: len(v) for k, v in buckets.items()} != expected_counts:
        raise ValueError("Original subset domain/difficulty quotas changed")
    groups, assignments = {}, []
    for level in LEVELS:
        # Reserve native assignments before balancing the remaining ones.
        counts = Counter(r["task_id"] for r in source if r["difficulty"] == level)
        rows = []
        for template in source:
            reused = template["difficulty"] == level
            candidates = buckets[template["domain"], level]
            target = template if reused else min(candidates, key=lambda r: (counts[r["task_id"]], r["task_id"]))
            if not reused:
                counts[target["task_id"]] += 1
            row = {k: target[k] for k in TASK_FIELDS}
            row.update({k: template[k] for k in FLAGS if k in template})
            row["harmful_task_id"] = f"{row['task_id']}_{row['inject_vector']}_{row['inject_goal']}"
            info = metadata[template["harmful_task_id"]]
            assignments.append({"subset_id": info["subset_id"], "category": info["category"],
                                "set": "old", "difficulty": level, "domain": row["domain"],
                                "task_id": row["task_id"], "harmful_task_id": row["harmful_task_id"],
                                "source_harmful_task_id": template["harmful_task_id"],
                                "source_difficulty": template["difficulty"], "reused": reused,
                                **{k: template[k] for k in FLAGS if k in template}})
            rows.append(row)
        groups[level] = rows
    return groups, assignments


def validate(directory, groups, assignments, source, *, axis="difficulty", levels=LEVELS):
    from benchmark.main_concurrency import inject_goals_from_attack_config, selectors_from_attack_config
    from benchmark.runner.security_check import GOAL_ALIASES, SECURITY_CHECKERS, load_attack_config
    original = {r["harmful_task_id"]: r for r in source}
    for level in levels:
        base = directory / level
        path = base / "selected_15_tasks_with_attack_config.json"
        rows = read(path)
        if len(rows) != 15 or len(selectors_from_attack_config(path)) != 15:
            raise ValueError(f"{level}: incomplete/duplicate task selectors")
        if len(inject_goals_from_attack_config(path)) != 15:
            raise ValueError(f"{level}: incomplete goal mapping")
        fixed = "domain" if axis == "difficulty" else "difficulty"
        expected_counts = {"law": 5, "banking": 5, "consulting": 5} if axis == "difficulty" else {"easy": 9, "medium": 3, "hard": 3}
        if Counter(r[fixed] for r in rows) != Counter(expected_counts) or any(r[axis] != level for r in rows):
            raise ValueError(f"{level}: {axis}/{fixed} balance changed")
        meta = [a for a in assignments if a[axis] == level]
        for row, expected, slot in zip(rows, groups[level], meta):
            validate_row(row, expected, base)
            if load_attack_config(path, row["harmful_task_id"]) != row:
                raise ValueError("Judge config could not be loaded")
            if GOAL_ALIASES.get(row["inject_goal"], row["inject_goal"]) not in SECURITY_CHECKERS:
                raise ValueError("No security checker for goal")
            if slot["reused"]:
                old = original[slot["source_harmful_task_id"]]
                if row != old:
                    raise ValueError("Native subset config was changed")
                for relative in old["populate_files"]:
                    if (base / relative).read_bytes() != (SUBSET / relative).read_bytes():
                        raise ValueError("Native subset artifact was changed")
        for name, reused in (("new_tasks_with_attack_config.json", False), ("reused_tasks_with_attack_config.json", True)):
            expected_rows = [r for r, a in zip(rows, meta) if a["reused"] == reused]
            if read(base / name) != expected_rows:
                raise ValueError(f"{level}: inconsistent split: {name}")
    print(f"Validated 45 old-set instances: 15 reused + 30 generated; identical attack conditions/{fixed} across {axis}", flush=True)


def reusable_results(assignments, source):
    result = []
    # Only record evidence paths. Do not choose runs by their model performance.
    for model in ("deepseekv4", "gemini37"):
        for run in sorted((ROOT / "benchmark/output/subset" / model).glob("*")):
            path = run / "manifest.json"
            if not path.is_file():
                continue
            state = read(path)
            processes = state.get("results", [])
            if (state.get("finished_task_count") != 15 or state.get("interrupted")
                    or len(processes) != 15 or any(r.get("returncode") != 0 for r in processes)):
                continue
            frozen = run / "attack_config.json"
            if not frozen.is_file() or read(frozen) != source or state.get("timer"):
                raise ValueError(f"Reusable run does not match original subset conditions: {run}")
            grades = []
            for slot in assignments:
                if not slot["reused"]:
                    continue
                grade_path = run / "tasks" / slot["harmful_task_id"] / "grades.json"
                if not grade_path.is_file():
                    raise ValueError(f"Missing reusable grades: {grade_path}")
                grade = read(grade_path)
                if grade.get("attack_success") not in (0, 1) or grade.get("attack_error") or grade.get("prompt_exposure_error"):
                    raise ValueError(f"Invalid reusable attack grading: {grade_path}")
                grades.append({"subset_id": slot["subset_id"], "difficulty": slot["difficulty"], "domain": slot["domain"],
                               "harmful_task_id": slot["harmful_task_id"],
                               "grades_file": str(grade_path.relative_to(ROOT))})
            result.append({"model_config_suffix": model, "run_id": run.name,
                           "source_subset_sha256": digest(source), "tasks": grades})
    return result


def main(*, directory=HERE, axis="difficulty", levels=LEVELS, design_fn=design):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    with (directory / ".generation.lock").open("a") as lock:
        lock_mode = fcntl.LOCK_SH if args.validate_only else fcntl.LOCK_EX
        fcntl.flock(lock, lock_mode | fcntl.LOCK_NB)
        source = read(SUBSET / "selected_15_tasks_with_attack_config.json")
        groups, assignments = design_fn(source, read(SUBSET / "selection_manifest.json"))
        manifest = {"set": "old", "source_subset_sha256": digest(source), "provider": "azure", "model": MODEL,
                    "endpoint": ENDPOINT, "reasoning_effort": None,
                    "keywords": "Reuse target old-task keywords exactly; no new keyword sampling",
                    "assignment_rule": ("Keep native slots; fill within same domain/difficulty by least load, then task_id" if axis == "difficulty"
                                        else "Keep native slots; fill within target domain and fixed source difficulty by least load, then task_id"),
                    "counts": {level: {"total": 15, "reused": sum(a["reused"] for a in assignments if a[axis] == level),
                                      "new": sum(not a["reused"] for a in assignments if a[axis] == level)} for level in levels},
                    "tasks": assignments}
        manifest_path = directory / "design_manifest.json"
        if manifest_path.exists() and read(manifest_path) != manifest:
            raise ValueError("Design changed; preserve current artifacts before changing inputs")
        if args.validate_only:
            if not manifest_path.exists():
                raise ValueError("Prepare/generate the experiment first")
            validate(directory, groups, assignments, source, axis=axis, levels=levels)
            return
        write(manifest_path, manifest)
        write(directory / "reusable_results.json", reusable_results(assignments, source))
        for level, rows in groups.items():
            write(directory / level / "selected_15_tasks_with_inject_goals.json", rows)
        if args.prepare_only:
            print(manifest["counts"])
            return
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        env = {**os.environ, "BENCHMARK_GENERATION_PROVIDER": "azure", "AZURE_OPENAI_MODEL": MODEL,
               "AZURE_OPENAI_BASE_URL": ENDPOINT}
        original = {r["harmful_task_id"]: r for r in source}
        for level, rows in groups.items():
            base = directory / level
            meta = [a for a in assignments if a[axis] == level]
            generated = []
            for expected, slot in zip(rows, meta):
                checkpoint = base / f"generated_{slot['subset_id']}.json"
                if checkpoint.exists():
                    result = read(checkpoint)
                    if len(result) != 1:
                        raise ValueError(f"Invalid checkpoint: {checkpoint}")
                    validate_row(result[0], expected, base)
                    print(f"Reuse checkpoint {level}/{slot['subset_id']}", flush=True)
                elif slot["reused"]:
                    row = original[slot["source_harmful_task_id"]]
                    shutil.copytree(SUBSET / row["harmful_task_id"], base / row["harmful_task_id"], dirs_exist_ok=True)
                    result = [row]
                    validate_row(row, expected, base)
                    write(checkpoint, result)
                    print(f"Copy original {level}/{slot['subset_id']}", flush=True)
                else:
                    source_path = base / ".generation_input.json"
                    write(source_path, [expected])
                    print(f"Generate {level}/{slot['subset_id']}", flush=True)
                    subprocess.run([sys.executable, "-m", "benchmark.generate_attack_config.generate", str(source_path),
                                    "--output", str(checkpoint), "--model", MODEL, "--provider", "azure"],
                                   cwd=ROOT, env=env, check=True)
                    result = read(checkpoint)
                    validate_row(result[0], expected, base)
                generated.extend(result)
            write(base / "selected_15_tasks_with_attack_config.json", generated)
            for name, reused in (("new_tasks_with_attack_config.json", False), ("reused_tasks_with_attack_config.json", True)):
                write(base / name, [r for r, a in zip(generated, meta) if a["reused"] == reused])
            (base / ".generation_input.json").unlink(missing_ok=True)
        validate(directory, groups, assignments, source, axis=axis, levels=levels)
        write(directory / "generation_complete.json", {"design_sha256": digest(manifest),
              "group_sha256": {level: digest(read(directory / level / "selected_15_tasks_with_attack_config.json")) for level in levels}})


if __name__ == "__main__":
    main()
