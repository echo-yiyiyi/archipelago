#!/usr/bin/env python3
"""Match the new tasks to subset slots and reuse the original Azure pipeline."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SUBSET = HERE.parent / "subset"
OUTPUT = HERE / "final_15_more"
MODEL = "gpt-5.6-sol"
ENDPOINT = "https://echoziyiyang-0462-resource.services.ai.azure.com/api/projects/echoziyiyang-0462/openai/v1/"
FLAGS = ("inject_goal", "inject_vector", "add_user_prompt", "no_key_words",
         "user_allow_additional_instruction", "leakage_type")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def match_tasks(new, old, taxonomy):
    if len(new) != 15 or len(old) != 15:
        raise ValueError("Both task lists must contain exactly 15 tasks")
    ids = [r["task_id"] for r in new]
    if len(set(ids)) != 15 or set(ids) & {r["task_id"] for r in old}:
        raise ValueError("New tasks must be unique and disjoint from the old subset")
    if Counter((r["domain"], r["difficulty"]) for r in new) != Counter(
            (r["domain"], r["difficulty"]) for r in old):
        raise ValueError("Domain/difficulty quotas differ from subset")
    buckets = defaultdict(deque)
    for task in new:
        if not task.get("prompt") or Path(task["task_id"]).name != task["task_id"] or task["task_id"] in {".", ".."}:
            raise ValueError("Each task needs a prompt and a safe task_id")
        buckets[task["domain"], task["difficulty"]].append(task)
    metadata = {r["harmful_task_id"]: r for r in taxonomy["tasks"]}
    rows, mapping = [], []
    for template in old:
        task = buckets[template["domain"], template["difficulty"]].popleft()
        # Whitelist experiment settings; never copy the old config or fixtures.
        row = {k: task[k] for k in ("task_id", "domain", "turns", "difficulty", "prompt")}
        row.update({k: template[k] for k in FLAGS if k in template})
        row["harmful_task_id"] = f"{row['task_id']}_{row['inject_vector']}_{row['inject_goal']}"
        rows.append(row)
        info = metadata[template["harmful_task_id"]]
        mapping.append({**{k: info[k] for k in (
            "subset_id", "category", "semantic_goal", "goal_group", "harm_type",
            "script_args", "requires_runtime_information")},
            "source_task_id": template["task_id"],
            "source_harmful_task_id": template["harmful_task_id"],
            **{k: row[k] for k in ("task_id", "harmful_task_id", "domain", "difficulty", *FLAGS) if k in row}})
    return rows, mapping


def validate_row(row, expected, directory):
    for key, value in expected.items():
        if row.get(key) != value:
            raise ValueError(f"{expected['harmful_task_id']}: changed {key}")
    config = row.get("attack_config")
    if not isinstance(config, dict) or not config.get("judge"):
        raise ValueError("Missing attack_config or judge rules")
    if bool(config.get("add_user_prompt")) != bool(expected.get("add_user_prompt")):
        raise ValueError("Changed add_user_prompt in attack_config")
    if config.get("leakage_type") != expected["leakage_type"]:
        raise ValueError("Changed leakage type in attack_config")
    if config.get("original_task_prompt", expected["prompt"]) != expected["prompt"]:
        raise ValueError("attack_config contains a stale task prompt")
    if not row.get("attack_file") or not row.get("populate_files"):
        raise ValueError("Missing artifact paths")
    for relative in [row["attack_file"], *row["populate_files"],
                     *[row[k] for k in ("watcher_file", "watcher_config") if k in row]]:
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError(f"Missing or out-of-bundle artifact: {relative}")
    if row["inject_vector"].startswith("dynamic_"):
        watcher = read(directory / row["watcher_config"])
        if watcher.get("attack_config") != config or watcher.get("inject_goal") != row["inject_goal"]:
            raise ValueError("Watcher config differs from the finalized attack_config")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--reasoning-effort", help="Omit to retain the original pipeline default")
    parser.add_argument("--workers", type=int, default=2, help="Keyword extraction workers")
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    new_path = HERE / "results/selected_15_tasks.json"
    old_path = SUBSET / "selected_15_tasks_with_attack_config.json"
    rows, mapping = match_tasks(read(new_path), read(old_path), read(SUBSET / "selection_manifest.json"))
    manifest = {"task_count": 15, "matching_rule": "subset order; first unused new task in the same domain/difficulty bucket",
                "source_tasks_sha256": digest(read(new_path)), "subset_sha256": digest(read(old_path)),
                "provider": "azure", "endpoint": ENDPOINT, "model": MODEL, "reasoning_effort": args.reasoning_effort,
                "keyword_module": "benchmark.extract_key_words.extract_key_words",
                "generation_module": "benchmark.generate_attack_config.generate",
                "coverage": read(SUBSET / "selection_manifest.json")["coverage"], "tasks": mapping}
    manifest_path = directory / "generation_manifest.json"
    if manifest_path.exists() and read(manifest_path) != manifest:
        raise ValueError("Inputs/settings changed; use a new output directory")
    final = directory / "selected_15_tasks_with_attack_config.json"
    if args.validate_only:
        generated = read(final)
        keywords = read(directory / "selected_15_tasks_with_keywords.json")
        from benchmark.extract_key_words.extract_key_words import validate_keywords
        if [r["task_id"] for r in keywords] != [r["task_id"] for r in rows]:
            raise ValueError("Keyword records do not match the task mapping")
        expected_rows = [{**r, "keywords": validate_keywords(k["keywords"])} for r, k in zip(rows, keywords)]
        if len(generated) != 15:
            raise ValueError("Final bundle must contain exactly 15 tasks")
        for row, expected in zip(generated, expected_rows):
            validate_row(row, expected, directory)
        from benchmark.main_concurrency import selectors_from_attack_config, inject_goals_from_attack_config
        from benchmark.runner.security_check import GOAL_ALIASES, SECURITY_CHECKERS, load_attack_config
        if len(selectors_from_attack_config(final)) != 15 or len(inject_goals_from_attack_config(final)) != 15:
            raise ValueError("Runner did not load all 15 tasks")
        for row in generated:
            if GOAL_ALIASES.get(row["inject_goal"], row["inject_goal"]) not in SECURITY_CHECKERS:
                raise ValueError(f"No security checker for {row['inject_goal']}")
            if load_attack_config(final, row["harmful_task_id"]) != row:
                raise ValueError("Judge config could not be loaded")
        print("Validated 15 matched tasks, keywords, artifacts, runner selectors and judge configs")
        return
    write(manifest_path, manifest)
    prepared = directory / "selected_15_tasks_with_inject_goals.json"
    write(prepared, rows)
    print(f"Prepared 15 matched tasks: {prepared}", flush=True)
    if args.prepare_only:
        return
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    env = {**os.environ, "BENCHMARK_GENERATION_PROVIDER": "azure", "AZURE_OPENAI_MODEL": MODEL,
           "AZURE_OPENAI_BASE_URL": ENDPOINT}
    optional = ["--reasoning-effort", args.reasoning_effort] if args.reasoning_effort else []
    keyword_path = directory / "selected_15_tasks_with_keywords.json"
    subprocess.run([sys.executable, "-m", manifest["keyword_module"], "--tasks-json", str(prepared),
                    "--output", str(keyword_path), "--model", MODEL, "--workers", str(args.workers), *optional],
                   cwd=ROOT, env=env, check=True)
    keywords = read(keyword_path)
    generated = []
    for row, slot in zip(keywords, mapping):
        checkpoint = directory / f"generated_{slot['subset_id']}.json"
        if checkpoint.exists():
            result = read(checkpoint)
            if len(result) != 1:
                raise ValueError(f"Invalid checkpoint: {checkpoint}")
            validate_row(result[0], row, directory)
            print(f"Reusing {slot['subset_id']}", flush=True)
        else:
            source = directory / ".generation_input.json"
            write(source, [row])
            subprocess.run([sys.executable, "-m", manifest["generation_module"], str(source),
                            "--output", str(checkpoint), "--model", MODEL, *optional], cwd=ROOT, env=env, check=True)
            result = read(checkpoint)
            validate_row(result[0], row, directory)
        generated.extend(result)
    write(final, generated)
    source = directory / ".generation_input.json"
    source.unlink(missing_ok=True)
    write(directory / "generation_complete.json", {"completed_at": datetime.now(timezone.utc).isoformat(),
          "task_count": len(generated), "final_sha256": digest(generated), "manifest_sha256": digest(manifest)})
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--validate-only", "--output-dir", str(directory),
                    *optional], cwd=ROOT, check=True)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
