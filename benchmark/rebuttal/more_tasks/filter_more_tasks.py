#!/usr/bin/env python3
"""Select 15 new tasks: Gemini reference -> Azure GPT -> Claude Opus.

GPT must match the reference score bucket before Opus is started. The old
selection is always excluded. No model calls are made with --prepare-only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse
import uuid

HERE = Path(__file__).resolve().parent
BENCHMARK = HERE.parents[1]
PROJECT = BENCHMARK.parent
OLD_OUTPUT = BENCHMARK / "filter_task_difficulty/output"
OLD_SELECTION = OLD_OUTPUT / "selected_15_tasks.json"
BUNDLED_SELECTION = HERE / "previous_15_tasks.json"
REFERENCE_CANDIDATES = HERE / "reference_candidates.json"
MODELS = ("gpt_5_6_sol", "opus")

# Reuse the original bucket definitions, quotas, candidate ordering, and IO.
spec = importlib.util.spec_from_file_location(
    "more_tasks_original_filter", BENCHMARK / "filter_task_difficulty/filter_task_difficulty.py"
)
core = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = core
spec.loader.exec_module(core)


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gemini_default() -> Path:
    paths = [BENCHMARK / "output/concurrent/merged-gemini-3-5-flash",
             PROJECT / "examples/hugging_face_task/output/concurrent/merged-gemini-3-5-flash"]
    return next((path for path in paths if path.is_dir()), paths[0])


def excluded_tasks(paths: list[Path]) -> set[str]:
    excluded = set()
    for path in paths:
        rows = core.read_json(path)
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("task_id"), str) for row in rows
        ):
            raise ValueError(f"Expected a JSON task list with task_id: {path}")
        excluded.update(row["task_id"] for row in rows)
    return excluded


def task_dataset(explicit: Path | None, *, download: bool) -> Path | None:
    try:
        return core.find_tasks_json(explicit)
    except FileNotFoundError:
        if explicit is not None:
            raise
        if not download:
            return None
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download(
        repo_id="mercor/apex-agents", repo_type="dataset", filename="tasks_and_rubrics.json"
    )).resolve()


def candidates_for(args, excluded: set[str], dataset: Path | None):
    if args.gemini_run is None:
        if args.min_turns < 30 or args.max_turns > 100:
            raise ValueError("Bundled reference only covers 30 < turns < 100; provide --gemini-run for a wider range")
        inventory = core.read_json(args.reference_candidates)
        domains = core.load_domains(dataset) if dataset is not None else None
        candidates, skipped, seen = [], [], set()
        for bucket in core.BUCKETS:
            for row in inventory["buckets"][bucket]:
                candidate = core.Candidate(**row)
                if (candidate.task_id in seen or core.score_bucket(candidate.gemini_score) != bucket
                        or candidate.score_bucket != bucket or candidate.domain not in core.QUOTAS[bucket]):
                    raise ValueError(f"Invalid/duplicate reference candidate: {candidate.task_id}")
                seen.add(candidate.task_id)
                if candidate.task_id in excluded:
                    skipped.append({"task_id": candidate.task_id, "reason": "excluded previous selection"})
                    continue
                if domains is not None:
                    if candidate.task_id not in domains:
                        skipped.append({"task_id": candidate.task_id, "reason": "missing from supplied dataset"})
                        continue
                    if domains[candidate.task_id] != candidate.domain:
                        raise ValueError(f"Dataset/reference domain mismatch: {candidate.task_id}")
                if args.min_turns < candidate.turns < args.max_turns:
                    candidates.append(candidate)
        order = {bucket: index for index, bucket in enumerate(core.BUCKETS)}
        candidates.sort(key=lambda c: (order[c.score_bucket], c.turns, c.task_id))
        return candidates, skipped
    if dataset is not None:
        domains = core.load_domains(dataset)
    else:
        # Preview can use saved domain labels without downloading the dataset.
        # Scores and turns are still checked against the actual Gemini artifacts.
        inventory_path = OLD_OUTPUT / "candidates.json"
        inventory = core.read_json(inventory_path if inventory_path.exists() else args.reference_candidates)
        domains = {row["task_id"]: row["domain"]
                   for rows in inventory["buckets"].values() for row in rows}
    candidates, skipped = core.collect_candidates(
        args.gemini_run.resolve(), domains, args.min_turns, args.max_turns
    )
    skipped.extend({"task_id": candidate.task_id, "reason": "excluded previous selection"}
                   for candidate in candidates if candidate.task_id in excluded)
    return [candidate for candidate in candidates if candidate.task_id not in excluded], skipped


def azure_config(name: str, path: Path):
    config = core.read_json(path)
    model = config.get("model", "")
    if name == "gpt_5_6_sol" and not model.startswith(("azure/", "openai/responses/")):
        raise ValueError("GPT must use an Azure model or an OpenAI-compatible Responses adapter on Azure")
    if name == "opus" and not model.startswith(("azure_ai/claude-opus-", "anthropic/claude-opus-")):
        raise ValueError("Opus config must identify a Claude Opus model")
    extra = dict(config.get("extra_args", {}))
    if extra.get("api_key") or extra.get("azure_ad_token"):
        raise ValueError(f"{name}: use environment variables or Key Vault, not inline credentials")
    base_env = "AZURE_API_BASE" if name == "gpt_5_6_sol" else "AZURE_AI_API_BASE"
    endpoint = extra.get("api_base") or os.environ.get(base_env, "")
    parsed = urlparse(endpoint)
    if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(
            (".openai.azure.com", ".services.ai.azure.com", ".cognitiveservices.azure.com"))
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError(f"{name}: configure an Azure HTTPS endpoint via api_base or {base_env}")
    if name == "opus" and parsed.path.rstrip("/") != "/anthropic":
        raise ValueError("Opus api_base must end in /anthropic, without /v1/messages")
    if name == "gpt_5_6_sol" and model.startswith("openai/responses/"):
        if not parsed.path.rstrip("/").endswith("/openai/v1"):
            raise ValueError("Azure v1 api_base must end in /openai/v1/; omit /responses")
    extra["api_base"] = endpoint
    identity = {"model": model, "api_base": endpoint, "config_sha256": fingerprint(path)}
    config = {**config, "extra_args": extra}
    return config, identity


def credential(config: dict, variable: str) -> str:
    vault = config.get("azure_key_vault")
    if vault:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
        value = SecretClient(vault_url=vault["vault_url"], credential=DefaultAzureCredential()) \
            .get_secret(vault["secret_name"]).value
    else:
        value = os.environ.get(variable)
    if not value:
        raise ValueError(f"Set {variable} or azure_key_vault in the corresponding config")
    return value


def anthropic_config(path: Path):
    config = core.read_json(path)
    model = config.get("model", "")
    if not model.startswith("anthropic/claude-opus-"):
        raise ValueError("Official Claude API config must use anthropic/claude-opus-*")
    extra = dict(config.get("extra_args", {}))
    if extra.get("api_key"):
        raise ValueError("Use ANTHROPIC_API_KEY instead of inline credentials")
    endpoint = extra.get("api_base", "https://api.anthropic.com").rstrip("/")
    if endpoint != "https://api.anthropic.com":
        raise ValueError("Official Claude API must use https://api.anthropic.com; use --opus-provider azure for Foundry")
    extra["api_base"] = endpoint
    return {**config, "extra_args": extra}, {
        "model": model, "api_base": endpoint, "config_sha256": fingerprint(path),
    }


def prepare_runtime(output: Path, configs: dict) -> Path:
    runtime = output / "runtime"
    runtime.mkdir(exist_ok=True)
    for name in ("main.py", "runner", "utils", "proxy", "agent_config.json", "eval_configs.json",
                 "scoring_config.json", "mcp_config_all_oss_servers.json"):
        link = runtime / name
        target = BENCHMARK / name
        if not link.exists():
            link.symlink_to(target, target_is_directory=target.is_dir())
    for name, config in configs.items():
        effective = {key: value for key, value in config.items() if key != "azure_key_vault"}
        if name == "opus":
            # Preserve the existing runner's Anthropic image/prefill/cache handling.
            # An explicit api_base selects either Foundry or the official API.
            effective["model"] = effective["model"].replace("azure_ai/", "anthropic/", 1)
        core.write_json_atomic(runtime / f"{name}.json", effective)
    gpt = configs["gpt_5_6_sol"]
    judge_extra = dict(gpt["extra_args"])
    reasoning = judge_extra.pop("reasoning", None)
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        judge_extra["reasoning_effort"] = reasoning["effort"]
    core.write_json_atomic(runtime / "grading_settings.json", {
        "llm_judge_model": gpt["model"].replace("azure/responses/", "azure/", 1),
        "llm_judge_extra_args": judge_extra,
    })
    return runtime


def launch_model(name, candidate, args, runtime, credentials):
    run_id = f"more_{name}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}"
    output = args.output_dir.resolve()
    run_root = output / "runs"
    run_dir = run_root / run_id
    logs = output / "driver_logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / f"{run_id}.log"
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith(("ATTACK_", "LLM_GATEWAY_", "LITELLM_PROXY_")) or key in (
            "TASK_OUTPUT_ROOT", "AGENT_TIMER_SECONDS", "HF_MAX_STEPS", "AGENT_MAX_STEPS",
        ):
            environment.pop(key, None)
    environment.update({
        "EXAMPLE_DIR": str(runtime), "ARCHIPELAGO_DIR": str(PROJECT),
        "ENVIRONMENT_DIR": str(PROJECT / "environment"),
        "AGENTS_DIR": str(PROJECT / "agents"), "GRADING_DIR": str(PROJECT / "grading"),
        "ORCHESTRATOR_CONFIG": str(runtime / f"{name}.json"),
        "SCORE_SUMMARY_FILENAME": "score_summary.json",
        "RUNTIME_NETWORK_CIDR": args.runtime_cidr,
        "HF_MAX_STEPS": str(args.model_max_turns + 1),
        "AGENT_MAX_STEPS": str(args.model_max_turns + 1),
        "UV_PYTHON": sys.executable,
        # Sol grades both models, so its Azure key is present for every run.
        "AZURE_API_KEY": credentials["gpt_5_6_sol"],
        "OPENAI_API_KEY": credentials["gpt_5_6_sol"],
        "ANTHROPIC_API_KEY": credentials["opus"],
        "LLM_GATEWAY_API_BASE": "", "LLM_GATEWAY_API_KEY": "",
        "LITELLM_PROXY_API_BASE": "", "LITELLM_PROXY_API_KEY": "",
    })
    if args.opus_provider == "azure":
        environment["AZURE_AI_API_KEY"] = credentials["opus"]
    else:
        environment.pop("AZURE_AI_API_KEY", None)
    command = [sys.executable, str(BENCHMARK / "main_concurrency.py"), candidate.task_id,
               "--concurrency", "1", "--base-port", str(args.base_port), "--skip-build",
               "--environment-image", args.environment_image, "--proxy-image", args.proxy_image,
               "--run-id", run_id, "--output-root", str(run_root)]
    started = time.monotonic()
    with log_path.open("w") as log:
        process = subprocess.Popen(command, cwd=BENCHMARK, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            returncode = process.wait()
        except KeyboardInterrupt:
            process.send_signal(signal.SIGINT)
            process.wait()
            raise
    score = None
    error = None
    try:
        trajectory = core.read_json(run_dir / "tasks" / candidate.task_id / "trajectory.json")
        turns = sum(message.get("role") == "assistant" for message in trajectory["messages"])
        if turns > args.model_max_turns:
            score = 0.0
            error = f"exceeded {args.model_max_turns} turns; treated as score 0"
        elif returncode != 0:
            error = f"runner exited {returncode}"
        elif trajectory.get("status") != "completed":
            error = f"agent status: {trajectory.get('status')}"
        else:
            grades = core.read_json(run_dir / "tasks" / candidate.task_id / "grades.json")
            if grades.get("grading_run_status") != "completed":
                raise ValueError("grading did not complete")
            rows = core.read_json(run_dir / "score_summary.json")["tasks"]
            raw = next(row["final_score"] for row in rows if row["task_id"] == candidate.task_id)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
                raise ValueError("missing/non-finite score")
            score = float(raw)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exception:
        error = f"runner exited {returncode}; invalid/missing result ({type(exception).__name__})"
    return {"model": name, "score": score, "bucket": core.score_bucket(score) if score is not None else None,
            "matches_gemini_bucket": score is not None and core.score_bucket(score) == candidate.score_bucket,
            "run_id": run_id, "run_dir": str(run_dir), "driver_log": str(log_path),
            "returncode": returncode, "elapsed_seconds": round(time.monotonic() - started, 1), "error": error}


def save_report(output: Path, report: dict, tasks: dict):
    report["updated_at"] = core.utc_now()
    report["quota_counts"] = core.quota_counts(report["attempts"])
    core.write_json_atomic(output / "attempts.json", report)
    core.write_attempts_csv(output / "attempts.csv", report["attempts"])
    selected = {}
    difficulty = {"score_1": "easy", "score_075_1": "medium", "score_05_075": "hard"}
    for attempt in report["attempts"]:
        if attempt.get("retained"):
            task_id = attempt["task_id"]
            selected[task_id] = {"task_id": task_id, "domain": attempt["domain"],
                                 "turns": attempt["turns"], "difficulty": difficulty[attempt["score_bucket"]],
                                 "prompt": tasks[task_id]["prompt"]}
    core.write_json_atomic(output / "selected_15_tasks.json", sorted(selected.values(), key=lambda row: (
        row["domain"], row["turns"], row["task_id"])))


def select_tasks(candidates, report, args, runtime, credentials, tasks, launch=launch_model):
    """Persist after each model so a successful GPT run survives an Opus failure."""
    attempts = report["attempts"]
    latest = {attempt["task_id"]: attempt for attempt in attempts}
    counts = core.quota_counts(attempts)
    for candidate in candidates:
        if counts[candidate.score_bucket][candidate.domain] >= core.QUOTAS[candidate.score_bucket][candidate.domain]:
            continue
        previous = latest.get(candidate.task_id)
        if previous and previous.get("status") in ("retained", "gpt_rejected", "opus_rejected"):
            continue
        # Copy prior model results into a new attempt, preserving their provenance.
        results = dict(previous.get("models", {})) if previous else {}
        attempt = {**asdict(candidate), "attempted_at": core.utc_now(),
                   "models": results, "status": "running", "retained": False}
        attempts.append(attempt)
        latest[candidate.task_id] = attempt
        for name in MODELS:
            existing = results.get(name, {})
            if existing.get("score") is None:
                print(f"Running {name}: {candidate.task_id} ({candidate.score_bucket}/{candidate.domain})", flush=True)
                results[name] = launch(name, candidate, args, runtime, credentials)
            result = results[name]
            if result.get("score") is None:
                attempt["status"] = "infrastructure_error"
                save_report(args.output_dir, report, tasks)
                print(f"Stopped: {name}: {result.get('error')}; log: {result.get('driver_log')}", file=sys.stderr)
                return 3
            if not result["matches_gemini_bucket"]:
                attempt["status"] = "gpt_rejected" if name == MODELS[0] else "opus_rejected"
                save_report(args.output_dir, report, tasks)
                break
            attempt["status"] = "gpt_passed" if name == MODELS[0] else "retained"
            if name == MODELS[1]:
                attempt["retained"] = True
                counts[candidate.score_bucket][candidate.domain] += 1
            save_report(args.output_dir, report, tasks)
    save_report(args.output_dir, report, tasks)
    missing = {bucket: {domain: quota - counts[bucket][domain]
                       for domain, quota in domains.items() if counts[bucket][domain] < quota}
               for bucket, domains in core.QUOTAS.items()}
    missing = {bucket: domains for bucket, domains in missing.items() if domains}
    if missing:
        print(f"Candidates exhausted; unfilled quotas: {json.dumps(missing)}", file=sys.stderr)
        return 2
    print(f"Selected 15 new tasks: {args.output_dir / 'selected_15_tasks.json'}", flush=True)
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--gemini-run", type=Path,
                        help="Optional original Gemini run to recompute references; default uses bundled metadata")
    parser.add_argument("--reference-candidates", type=Path, default=REFERENCE_CANDIDATES)
    parser.add_argument("--tasks-json", type=Path)
    parser.add_argument("--exclude-tasks", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=HERE / "output")
    parser.add_argument("--gpt-config", type=Path, default=HERE / "orchestrator_config_gpt_azure.json")
    parser.add_argument("--opus-provider", choices=("anthropic", "azure"), default="anthropic",
                        help="Claude endpoint provider (default: official Anthropic API)")
    parser.add_argument("--opus-config", type=Path)
    parser.add_argument("--min-turns", type=int, default=30)
    parser.add_argument("--max-turns", type=int, default=100)
    parser.add_argument("--model-max-turns", type=int, default=80)
    parser.add_argument("--base-port", type=int, default=19280)
    parser.add_argument("--runtime-cidr", default="172.30.0.0/16")
    parser.add_argument("--environment-image", default="archipelago-hf-environment:concurrency")
    parser.add_argument("--proxy-image", default="archipelago-hf-runtime-proxy:concurrency")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-sync", action="store_true", help="Skip uv sync when agent/grading environments are already ready")
    args = parser.parse_args(argv)
    if args.opus_config is None:
        args.opus_config = HERE / ("orchestrator_config_opus.json" if args.opus_provider == "anthropic"
                                  else "orchestrator_config_opus_azure.json")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not 0 <= args.min_turns < args.max_turns or args.model_max_turns < 1:
        raise ValueError("Invalid turn limits")
    args.output_dir = args.output_dir.resolve()
    exclusions = [BUNDLED_SELECTION, *args.exclude_tasks]
    if OLD_SELECTION.exists():
        exclusions.append(OLD_SELECTION)
    if args.output_dir == OLD_OUTPUT.resolve() or any(path.resolve().parent == args.output_dir for path in exclusions):
        raise ValueError("Output must be separate from excluded selections")
    excluded = excluded_tasks(exclusions)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (args.output_dir / ".selection.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another selection is already running in this output directory")
        return prepare_or_run(args, excluded)


def prepare_or_run(args, excluded):
    dataset = task_dataset(args.tasks_json, download=False)
    candidates, skipped = candidates_for(args, excluded, dataset)
    core.write_candidates(args.output_dir / "candidates.json", candidates, skipped, args.min_turns, args.max_turns)
    print(f"{len(candidates)} candidates, excluding {len(excluded)} task IDs", flush=True)
    for bucket in core.BUCKETS:
        print(f"{bucket}: {dict(Counter(c.domain for c in candidates if c.score_bucket == bucket))}", flush=True)
    if args.prepare_only:
        return 0
    return run_selection(args, excluded, dataset)


def run_selection(args, excluded, dataset):
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("Activate the repaired Python 3.13 environment before running models")
    if not shutil.which("uv"):
        raise RuntimeError("uv is not on PATH; activate the repaired runtime")
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True)
    configs, identities = {}, {}
    for name, path in zip(MODELS, (args.gpt_config, args.opus_config)):
        configs[name], identities[name] = (anthropic_config(path)
            if name == "opus" and args.opus_provider == "anthropic" else azure_config(name, path))
    credentials = {
        "gpt_5_6_sol": credential(configs["gpt_5_6_sol"], "AZURE_API_KEY"),
        "opus": credential(configs["opus"], "ANTHROPIC_API_KEY" if args.opus_provider == "anthropic" else "AZURE_AI_API_KEY"),
    }
    dataset = dataset or task_dataset(args.tasks_json, download=True)
    tasks = {row["task_id"]: row for row in core.read_json(dataset)}
    candidates, skipped = candidates_for(args, excluded, dataset)
    for bucket, domains in core.QUOTAS.items():
        for domain, quota in domains.items():
            available = sum(c.score_bucket == bucket and c.domain == domain for c in candidates)
            if available < quota:
                raise ValueError(f"Insufficient candidates for {bucket}/{domain}: {available} < {quota}")
    core.write_candidates(args.output_dir / "candidates.json", candidates, skipped, args.min_turns, args.max_turns)
    context = {"models": identities, "opus_provider": args.opus_provider,
               "judge": "Azure GPT from --gpt-config",
               "filter_source_sha256": fingerprint(Path(core.__file__)),
               "gemini_run": str(args.gemini_run.resolve()) if args.gemini_run else None,
               "gemini_summary_sha256": fingerprint(args.gemini_run / "score_summary.json") if args.gemini_run else None,
               "reference_sha256": fingerprint(args.reference_candidates),
               "dataset_sha256": fingerprint(dataset), "excluded_ids": sorted(excluded),
               "min_turns": args.min_turns, "max_turns": args.max_turns,
               "model_max_turns": args.model_max_turns, "quotas": core.QUOTAS,
               "candidate_ids": [candidate.task_id for candidate in candidates]}
    report_path = args.output_dir / "attempts.json"
    report = core.read_json(report_path) if report_path.exists() else {
        "created_at": core.utc_now(), "context": context, "attempts": [],
    }
    if report.get("context") != context:
        raise ValueError("Run settings changed; use a different --output-dir")
    if any(attempt["task_id"] in excluded for attempt in report["attempts"]):
        raise ValueError("Saved report contains excluded task IDs")
    runtime = prepare_runtime(args.output_dir, configs)
    save_report(args.output_dir, report, tasks)
    if report["quota_counts"] == core.QUOTAS:
        print(f"Selection already complete: {args.output_dir / 'selected_15_tasks.json'}")
        return 0
    if not args.skip_sync:
        for directory in (PROJECT / "agents", PROJECT / "grading"):
            subprocess.run(["uv", "sync", "--locked", "--python", sys.executable], cwd=directory, check=True)
    if not args.skip_build:
        core.build_shared_images(args.environment_image, args.proxy_image)
    return select_tasks(candidates, report, args, runtime, credentials, tasks)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted. Rerun the same command to resume.", file=sys.stderr)
        raise SystemExit(130)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
