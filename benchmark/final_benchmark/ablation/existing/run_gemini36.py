#!/usr/bin/env python3
"""Run existing-file head and keyword-position tasks with Gemini 3.6 Flash."""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
sys.path.insert(0, str(REPO))
from benchmark import run_models_parallel as parallel

MODEL = "gemini36"
MODEL_NAME = "vertex_ai/gemini-3.6-flash"
MODEL_CONFIG = REPO / "benchmark/orchestrator_config_gemini36.json"
SETTINGS = ("head", "key-word")
CATEGORIES = ("static_prompt_injection", "static_script_injection")


def plan(input_root: Path, settings: list[str]):
    if json.loads(MODEL_CONFIG.read_text()).get("model") != MODEL_NAME:
        raise ValueError("orchestrator_config_gemini36.json does not select Gemini 3.6 Flash")
    groups = []
    signatures = {}
    for setting in settings:
        jobs = []
        for category in CATEGORIES:
            directory = input_root / setting / category
            source = directory / "selected_10_tasks_with_attack_config.json"
            rows = json.loads(source.read_text())
            if len(rows) != 10:
                raise ValueError(f"{source}: expected 10 tasks")
            hosts = parallel.runtime.link_hosts_from_attack_config(source)
            for row in rows:
                if row.get("attack_file"):
                    raise ValueError(f"{source}: standalone attack_file must be absent")
                if not row.get("populate_files") or not row.get("populate_file_destinations"):
                    raise ValueError(f"{source}: missing existing-file overlay metadata")
                for name in row["populate_files"]:
                    artifact = (directory / name).resolve()
                    if not artifact.is_relative_to(directory.resolve()) or not artifact.is_file():
                        raise ValueError(f"{source}: missing or out-of-bundle artifact {name}")
                jobs.append(parallel.Job(
                    MODEL, category, row["harmful_task_id"], row["task_id"], source,
                    MODEL_CONFIG, row["inject_goal"], hosts.get(row["harmful_task_id"]),
                ))
        if len(jobs) != 20:
            raise ValueError(f"{setting}: expected 20 tasks, found {len(jobs)}")
        for category in CATEGORIES:
            subset = [job for job in jobs if job.category == category]
            if len(subset) != 10:
                raise ValueError(f"{setting}/{category}: expected 10 tasks")
            signature = {(job.selector, job.dataset_selector, job.goal) for job in subset}
            if category in signatures and signatures[category] != signature:
                raise ValueError(f"{category}: head and key-word task/goal pairs differ")
            signatures[category] = signature
        groups.append([replace(job, category=f"{setting}/{job.category}") for job in jobs])
    return [group[index] for index in range(max(map(len, groups))) for group in groups if index < len(group)]


def summarize(run_dir: Path):
    manifest = json.loads((run_dir / "manifest.json").read_text())
    groups = {}
    for key in manifest["jobs"]:
        model, setting, category, task = key.split("/")
        result = manifest.get("results", {}).get(key)
        grade_path = run_dir / model / setting / category / "tasks" / task / "grades.json"
        try:
            grade = json.loads(grade_path.read_text())
        except (OSError, json.JSONDecodeError):
            grade = {}
        row = groups.setdefault((setting, category), {
            "setting": setting, "category": category, "requested": 0,
            "finished": 0, "failed": 0, "exposure": [], "asr": [], "score": [],
        })
        row["requested"] += 1
        row["finished"] += int(result is not None)
        row["failed"] += int(result is not None and result.get("returncode") != 0)
        values = {
            "exposure": grade.get("prompt_exposure"),
            "asr": grade.get("attack_success"),
            "score": (grade.get("scoring_results") or {}).get("final_score"),
        }
        for metric, value in values.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                row[metric].append(value)
    rows = []
    for _, group in sorted(groups.items()):
        row = {k: group[k] for k in ("setting", "category", "requested", "finished", "failed")}
        for metric in ("exposure", "asr", "score"):
            values = group[metric]
            row[metric] = sum(values) / len(values) if values else None
            row[metric + "_n"] = len(values)
        rows.append(row)
    parallel.write_json(run_dir / "existing_summary.json", rows)
    if rows:
        with (run_dir / "existing_summary.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    lines = [f"# {MODEL_NAME} existing-file results", "",
             "| Setting | Category | Finished | Failed | Exposure | ASR | Score |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        def shown(name, percent=False):
            value = row[name]
            text = "N/A" if value is None else f"{value:.2%}" if percent else f"{value:.4f}"
            return f"{text} ({row[name + '_n']})"
        lines.append(f"| {row['setting']} | {row['category']} | {row['finished']}/{row['requested']} | "
                     f"{row['failed']} | {shown('exposure', True)} | {shown('asr', True)} | {shown('score')} |")
    report = "\n".join(lines) + "\n"
    (run_dir / "existing_summary.md").write_text(report)
    print(report, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", nargs="+", choices=SETTINGS, default=list(SETTINGS))
    parser.add_argument("--input-root", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path, default=REPO / "benchmark/output/ablation/existing")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--max-steps", type=int, default=150)
    parser.add_argument("--base-port", type=int)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summarize", type=Path, metavar="RUN_DIR")
    args = parser.parse_args()
    if args.summarize:
        summarize(args.summarize.resolve())
        return 0
    if not 1 <= args.concurrency <= 64 or args.max_steps < 1:
        parser.error("concurrency must be 1..64 and max-steps must be positive")
    if len(set(args.settings)) != len(args.settings):
        parser.error("settings must be distinct")
    args.input_root = args.input_root.resolve()
    args.output_root = args.output_root.resolve()
    args.models = [MODEL]
    args.timer = False
    os.environ["HF_MAX_STEPS"] = str(args.max_steps)
    os.umask(0o077)
    try:
        jobs = plan(args.input_root, args.settings)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps({
            "model": MODEL_NAME,
            "settings": args.settings,
            "tasks": len(jobs),
            "concurrency": min(args.concurrency, len(jobs)),
            "max_steps": args.max_steps,
            "jobs": [job.key for job in jobs],
        }, indent=2))
        return 0
    selected_model = json.loads(MODEL_CONFIG.read_text())["model"]
    if selected_model.startswith("openai/") and not os.environ.get("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is required for this model config")
    stamp = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    args.output_root = args.output_root / (MODEL + "_" + stamp)
    args.output_root.mkdir(parents=True)
    try:
        return parallel.execute(args, jobs)
    finally:
        for manifest in args.output_root.glob("parallel_*/manifest.json"):
            summarize(manifest.parent)


if __name__ == "__main__":
    raise SystemExit(main())
