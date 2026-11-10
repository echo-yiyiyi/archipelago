#!/usr/bin/env python3
"""Assemble 14 original results plus the infrastructure retry, retaining raw runs."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from benchmark.main_concurrency import update_score_summary

TASK = "task_699ea5ca3b0243a5852ad33e33043f12_dynamic_prompt_injection_19_save_country"
ORIGINAL = ROOT / "benchmark/output/final_15_more/gemini37/gemini37_more15_20261109_151721_7e76f24b"
RETRY = ROOT / "benchmark/output/final_15_more_repairs/gemini37/gemini37_S06_schema_fix_20261109"
OUTPUT = ORIGINAL.parent / "gemini37_more15_repaired_20261109"


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-run", type=Path, default=RETRY)
    args = parser.parse_args()
    retry = args.retry_run.resolve()
    rows = read(ORIGINAL / "attack_config.json")
    target = next(row for row in rows if row["harmful_task_id"] == TASK)
    if read(retry / "attack_config.json") != [target]:
        raise ValueError("Retry attack configuration differs from original S06")
    if read(ORIGINAL / "tasks" / TASK / "trajectory.json")["status"] != "error":
        raise ValueError("Original S06 is not an infrastructure-error trajectory")
    retry_manifest = read(retry / "manifest.json")
    if retry_manifest.get("finished_task_count") != 1 or any(r["returncode"] for r in retry_manifest["results"]):
        raise ValueError("Retry run has not completed successfully")
    sources = []
    for row in rows:
        identifier = row["harmful_task_id"]
        source = (retry if identifier == TASK else ORIGINAL) / "tasks" / identifier
        trajectory = read(source / "trajectory.json")
        grade = read(source / "grades.json")
        score = grade.get("scoring_results", {}).get("final_score")
        if trajectory["status"] != "completed" or grade.get("grading_run_status") != "completed":
            raise ValueError(f"Incomplete agent/grading: {source}")
        if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"Missing/invalid score: {source}")
        if grade.get("attack_error") or grade.get("prompt_exposure_error"):
            raise ValueError(f"Security/exposure judge error: {source}")
        sources.append(source)
    if OUTPUT.exists():
        raise ValueError(f"Composite already exists; refusing to overwrite: {OUTPUT}")
    OUTPUT.mkdir()
    (OUTPUT / "tasks").mkdir()
    for source in sources:
        target_path = OUTPUT / "tasks" / source.name
        target_path.symlink_to(os.path.relpath(source, target_path.parent), target_is_directory=True)
    shutil.copy2(ORIGINAL / "attack_config.json", OUTPUT / "attack_config.json")
    manifest = {"run_id": OUTPUT.name, "run_type": "composite_after_infrastructure_retry",
                "requested_task_count": 15, "finished_task_count": 15, "interrupted": False,
                "original_run": str(ORIGINAL.relative_to(ROOT)), "retry_run": str(retry.relative_to(ROOT)),
                "replacement_reason": "Original S06 agent failed on Vertex HTTP 400 schema $ref validation; grading was skipped",
                "replaced_harmful_task_id": TASK,
                "results": [{"selector": source.name, "returncode": 0,
                             "source_task_directory": str(source.relative_to(ROOT))} for source in sources]}
    write(OUTPUT / "manifest.json", manifest)
    summary = update_score_summary(OUTPUT)
    assert summary["completed_task_count"] == 15
    assert summary["attack_evaluated_count"] == 15
    assert summary["prompt_exposure_task_count"] == 9
    audit = {**manifest, "original_summary": read(ORIGINAL / "score_summary.json"), "repaired_summary": summary,
             "composite_run": str(OUTPUT.relative_to(ROOT)),
             "original_grades_sha256": hashlib.sha256((ORIGINAL / "tasks" / TASK / "grades.json").read_bytes()).hexdigest(),
             "retry_grades_sha256": hashlib.sha256((retry / "tasks" / TASK / "grades.json").read_bytes()).hexdigest()}
    write(HERE / "final_15_more/gemini37_repair_audit.json", audit)
    print(json.dumps({k: v for k, v in summary.items() if k != "tasks"}, indent=2))
    print(OUTPUT)


if __name__ == "__main__":
    main()
