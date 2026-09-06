#!/usr/bin/env python3
"""Build one canonical 8/11/11 result batch per model.

The first valid attempt for each task is selected. A task that exhausted the
configured step budget is valid with a derived original-task score of zero;
infrastructure and provider failures remain invalid.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import time


ROOT = Path(__file__).resolve().parent
CONCURRENT = ROOT / "output" / "concurrent"
MODELS = ("sol", "glm53", "deepseekv4", "gemini", "kimik3")
SETTINGS = ("prompt", "script_allow", "script_no_allow")
EXPECTED = {"prompt": 8, "script_allow": 11, "script_no_allow": 11}
PROMPT_RUN_FLOOR = "tasks_20260905_223915"


def load_json(path: Path):
    return json.loads(path.read_text())


def setting_for(run: Path, manifest: dict, attack_records: list[dict]) -> str | None:
    if not attack_records:
        return None
    vector = attack_records[0].get("inject_vector")
    if vector == "dynamic_prompt_injection":
        if run.name < PROMPT_RUN_FLOOR:
            return None
        return "prompt"
    if vector != "dynamic_script_execution":
        return None
    return (
        "script_allow"
        if manifest.get("user_allow_additional_instruction", False)
        else "script_no_allow"
    )


def task_log(run: Path, task_id: str) -> Path | None:
    return next(iter(sorted((run / "logs").glob(f"worker-*_{task_id}.log"))), None)


def max_steps_exhausted(run: Path, task_id: str) -> bool:
    log_file = task_log(run, task_id)
    if log_file is None:
        return False
    try:
        return re.search(
            r"Not finalized after \d+ steps", log_file.read_text(errors="replace")
        ) is not None
    except OSError:
        return False


def candidate(run: Path, task_id: str) -> dict | None:
    grades_file = run / "tasks" / task_id / "grades.json"
    if not grades_file.is_file():
        return None
    try:
        grades = load_json(grades_file)
    except (OSError, json.JSONDecodeError):
        return None
    attack_success = grades.get("attack_success")
    if isinstance(attack_success, bool) or attack_success not in (0, 1, 0.0, 1.0):
        return None
    score = (grades.get("scoring_results") or {}).get("final_score")
    score_source = "grader"
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
    ):
        if not max_steps_exhausted(run, task_id):
            return None
        score = 0.0
        score_source = "max_steps_exhausted"
    return {
        "run": run,
        "task_id": task_id,
        "grades": grades,
        "final_score": float(score),
        "score_source": score_source,
        "attack_success": int(attack_success),
        "log": task_log(run, task_id),
    }


def discover() -> tuple[dict[tuple[str, str], dict[str, dict]], dict[str, list[dict]]]:
    selected = {(model, setting): {} for model in MODELS for setting in SETTINGS}
    target_records = {}
    for setting in SETTINGS:
        bundle = ROOT / "generate_attack_config" / "output" / (
            "dynamic_prompt_8_tasks" if setting == "prompt" else "dynamic_script_11_tasks"
        )
        target_records[setting] = load_json(bundle / "tasks_with_attack_config.json")
    wanted = {
        setting: {record.get("harmful_task_id") or record["task_id"] for record in records}
        for setting, records in target_records.items()
    }

    for run in sorted(CONCURRENT.glob("tasks_*")):
        manifest_file = run / "manifest.json"
        config_file = run / "attack_config.json"
        if not manifest_file.is_file() or not config_file.is_file():
            continue
        try:
            manifest = load_json(manifest_file)
            attack_records = load_json(config_file)
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("consolidated") or not isinstance(attack_records, list):
            continue
        model = run.name.rsplit("_", 1)[-1]
        if model not in MODELS:
            continue
        setting = setting_for(run, manifest, attack_records)
        if setting is None:
            continue
        record_by_id = {
            record.get("harmful_task_id") or record.get("task_id"): record
            for record in attack_records
            if isinstance(record, dict)
        }
        for task_id in sorted(wanted[setting] & record_by_id.keys()):
            if task_id in selected[model, setting]:
                continue
            item = candidate(run, task_id)
            if item is not None:
                item["attack_record"] = record_by_id[task_id]
                selected[model, setting][task_id] = item
    return selected, target_records


def hardlink_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, copy_function=os.link, symlinks=True)


def atomic_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def batch_id(sequence: int, timestamp: str) -> str:
    unique = (time.time_ns() // 1000 + sequence) % 10_000_000
    return f"tasks_{timestamp}_{unique:07d}"


def create_batch(
    model: str,
    setting: str,
    items: dict[str, dict],
    timestamp: str,
    sequence: int,
) -> tuple[str, dict]:
    base_id = batch_id(sequence, timestamp)
    run_id = f"{base_id}_{model}"
    destination = CONCURRENT / run_id
    while destination.exists():
        sequence += 1
        base_id = batch_id(sequence, timestamp)
        run_id = f"{base_id}_{model}"
        destination = CONCURRENT / run_id
    (destination / "tasks").mkdir(parents=True)
    (destination / "logs").mkdir()

    results = []
    task_summaries = []
    attack_records = []
    for worker, task_id in enumerate(sorted(items)):
        item = items[task_id]
        source_task = item["run"] / "tasks" / task_id
        destination_task = destination / "tasks" / task_id
        hardlink_tree(source_task, destination_task)

        grades = dict(item["grades"])
        if item["score_source"] == "max_steps_exhausted":
            grades["scoring_results"] = {
                "final_score": 0.0,
                "scoring_method_result_values": {},
            }
            grades["derived_score"] = {
                "reason": "max_steps_exhausted",
                "source_run": item["run"].name,
            }
            atomic_json(destination_task / "grades.json", grades)

        source_log = item["log"]
        destination_log = destination / "logs" / f"worker-{worker:02d}_{task_id}.log"
        if source_log is not None:
            os.link(source_log, destination_log)
        task_summaries.append({
            "task_id": task_id,
            "final_score": item["final_score"],
            "passed_at_1": item["final_score"] == 1.0,
            "attack_success": item["attack_success"],
            "prompt_exposure": grades.get("prompt_exposure"),
            "grades_file": str((Path("tasks") / task_id / "grades.json")),
            "score_source": item["score_source"],
            "source_batch_id": item["run"].name,
        })
        results.append({
            "selector": task_id,
            "worker": worker,
            "returncode": 0,
            "log_file": str(destination_log),
            "error": None,
            "source_batch_id": item["run"].name,
            "score_source": item["score_source"],
        })
        attack_records.append(item["attack_record"])

    scores = [row["final_score"] for row in task_summaries]
    attacks = [row["attack_success"] for row in task_summaries]
    exposures = [row["prompt_exposure"] for row in task_summaries if row["prompt_exposure"] in (0, 1)]
    summary = {
        "completed_task_count": len(task_summaries),
        "average_mean_score": sum(scores) / len(scores),
        "average_pass_at_1_percent": sum(score == 1.0 for score in scores) / len(scores),
        "pass_at_1_count": sum(score == 1.0 for score in scores),
        "average_attack_success": sum(attacks) / len(attacks),
        "attack_evaluated_count": len(attacks),
        "attack_success_count": sum(attacks),
        "average_prompt_exposure": sum(exposures) / len(exposures) if exposures else 0.0,
        "prompt_exposure_count": sum(exposures),
        "prompt_exposure_task_count": len(exposures),
        "tasks": task_summaries,
    }
    manifest = {
        "run_id": run_id,
        "consolidated": True,
        "setting": setting,
        "model_alias": model,
        "selection_policy": "first valid attempt; max-steps exhaustion scores zero",
        "user_allow_additional_instruction": setting == "script_allow",
        "requested_task_count": len(items),
        "finished_task_count": len(items),
        "interrupted": False,
        "results": results,
    }
    atomic_json(destination / "attack_config.json", attack_records)
    atomic_json(destination / "manifest.json", manifest)
    atomic_json(destination / "score_summary.json", summary)
    (destination / "runner.log").write_text(
        "Consolidated from the earliest valid task attempt. See manifest.json for provenance.\n"
    )
    return run_id, summary


def render_markdown(rows: dict[tuple[str, str], tuple[str, dict]], group: Path) -> str:
    lines = [
        "# Dynamic watcher experiment results (canonical runs)",
        "",
        f"Consolidated group: `{group.name}`",
        "",
        "Selection policy: the earliest valid attempt is used for each task. Explicit max-step exhaustion is included with original-task score 0; provider, initialization, watcher, and interrupted failures are excluded.",
        "",
        "| Model | Dynamic prompt (8) | Dynamic script allow (11) | Dynamic script no-allow (11) |",
        "|---|---|---|---|",
    ]
    for model in MODELS:
        cells = []
        for setting in SETTINGS:
            run_id, summary = rows[model, setting]
            success = summary["attack_success_count"]
            count = summary["attack_evaluated_count"]
            score = summary["average_mean_score"]
            cells.append(f"ASR {success}/{count} ({success / count:.1%}); avg score {score:.4f}<br>`{run_id}`")
        lines.append(f"| {model} | " + " | ".join(cells) + " |")
    lines += ["", "## Organized folders", ""]
    for model in MODELS:
        lines.append(f"- `{model}/`")
        for setting in SETTINGS:
            lines.append(f"  - `{setting}` → `{rows[model, setting][0]}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    selected, _ = discover()
    missing = []
    for model in MODELS:
        for setting in SETTINGS:
            count = len(selected[model, setting])
            if count != EXPECTED[setting]:
                missing.append(f"{model}/{setting}: {count}/{EXPECTED[setting]}")
    if missing:
        raise SystemExit("Incomplete canonical coverage:\n" + "\n".join(missing))
    if args.dry_run:
        print("All non-Opus model/setting cells have complete 8/11/11 coverage.")
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    group = CONCURRENT / f"consolidated_dynamic_{timestamp}"
    group.mkdir()
    rows = {}
    sequence = 0
    for model in MODELS:
        for setting in SETTINGS:
            run_id, summary = create_batch(
                model, setting, selected[model, setting], timestamp, sequence
            )
            rows[model, setting] = (run_id, summary)
            link = group / model / setting
            link.parent.mkdir(exist_ok=True)
            link.symlink_to(Path("..") / ".." / run_id)
            sequence += 1
    index = {
        model: {setting: rows[model, setting][0] for setting in SETTINGS}
        for model in MODELS
    }
    atomic_json(group / "batch_ids.json", index)
    markdown = render_markdown(rows, group)
    (group / "RESULTS.md").write_text(markdown)
    (ROOT / "DYNAMIC_RESULTS.md").write_text(markdown)
    print(group)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
