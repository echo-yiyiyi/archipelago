#!/usr/bin/env python3
"""Select tasks whose difficulty bucket is stable across three models.

Candidates come from the merged Gemini run, are ordered by assistant turns,
and are rerun with GPT 5.6 Sol and Opus in parallel.  A task is retained only
when both rerun scores fall in the same bucket as its Gemini score.
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = SCRIPT_DIR.parent
ARCHIPELAGO_DIR = BENCHMARK_DIR.parent
DEFAULT_GEMINI_RUN = (
    ARCHIPELAGO_DIR
    / "examples/hugging_face_task/output/concurrent/merged-gemini-3-5-flash"
)
DEFAULT_RUN_OUTPUT = BENCHMARK_DIR / "output/concurrent"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"

BUCKETS = ("score_1", "score_075_1", "score_05_075")
BUCKET_LABELS = {
    "score_1": "score = 1",
    "score_075_1": "0.75 <= score < 1",
    "score_05_075": "0.5 <= score < 0.75",
}
DOMAIN_ALIASES = {
    "law": "law",
    "investment banking": "banking",
    "banking": "banking",
    "management consulting": "consulting",
    "consulting": "consulting",
}
QUOTAS = {
    "score_1": {"law": 2, "banking": 2, "consulting": 2},
    "score_075_1": {"law": 1, "banking": 1, "consulting": 1},
    "score_05_075": {"law": 1, "banking": 1, "consulting": 1},
}
MODEL_CONFIGS = {
    "gpt_5_6_sol": BENCHMARK_DIR / "orchestrator_config_gpt.json",
    "opus": BENCHMARK_DIR / "orchestrator_config_opus.json",
}


@dataclass(frozen=True)
class Candidate:
    task_id: str
    domain: str
    turns: int
    gemini_score: float
    score_bucket: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temporary.replace(path)


def score_bucket(score: float) -> str | None:
    if score == 1.0:
        return "score_1"
    if 0.75 <= score < 1.0:
        return "score_075_1"
    if 0.5 <= score < 0.75:
        return "score_05_075"
    return None


def normalize_domain(domain: str) -> str | None:
    return DOMAIN_ALIASES.get(domain.strip().lower())


def find_tasks_json(explicit_path: Path | None) -> Path:
    if explicit_path is not None:
        if not explicit_path.is_file():
            raise FileNotFoundError(f"tasks JSON does not exist: {explicit_path}")
        return explicit_path.resolve()

    cache_roots = []
    if os.environ.get("HF_HUB_CACHE"):
        cache_roots.append(Path(os.environ["HF_HUB_CACHE"]))
    if os.environ.get("HF_HOME"):
        cache_roots.append(Path(os.environ["HF_HOME"]) / "hub")
    cache_roots.append(Path.home() / ".cache/huggingface/hub")

    matches: list[Path] = []
    for root in cache_roots:
        matches.extend(
            root.glob(
                "datasets--mercor--apex-agents/snapshots/*/tasks_and_rubrics.json"
            )
        )
    if matches:
        return max(matches, key=lambda path: path.stat().st_mtime).resolve()

    raise FileNotFoundError(
        "Could not find the cached mercor/apex-agents tasks_and_rubrics.json. "
        "Pass it explicitly with --tasks-json. Running any benchmark task once "
        "will also populate the Hugging Face cache."
    )


def load_domains(tasks_json: Path) -> dict[str, str]:
    domains: dict[str, str] = {}
    for task in read_json(tasks_json):
        task_id = task.get("task_id")
        domain = normalize_domain(str(task.get("domain", "")))
        if isinstance(task_id, str) and domain is not None:
            domains[task_id] = domain
    return domains


def assistant_turns(trajectory_path: Path) -> int:
    trajectory = read_json(trajectory_path)
    messages = trajectory.get("messages")
    if not isinstance(messages, list):
        raise ValueError("trajectory.messages is not a list")
    return sum(
        1
        for message in messages
        if isinstance(message, dict) and message.get("role") == "assistant"
    )


def collect_candidates(
    gemini_run: Path, domains: dict[str, str], min_turns: int, max_turns: int
) -> tuple[list[Candidate], list[dict[str, str]]]:
    summary_path = gemini_run / "score_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"Gemini score summary does not exist: {summary_path}")

    candidates: list[Candidate] = []
    skipped: list[dict[str, str]] = []
    for row in read_json(summary_path).get("tasks", []):
        task_id = row.get("task_id")
        raw_score = row.get("final_score")
        if not isinstance(task_id, str) or isinstance(raw_score, bool) or not isinstance(
            raw_score, (int, float)
        ):
            continue
        score = float(raw_score)
        bucket = score_bucket(score)
        if bucket is None:
            continue
        domain = domains.get(task_id)
        if domain is None:
            skipped.append({"task_id": task_id, "reason": "missing/unsupported domain"})
            continue
        trajectory_path = gemini_run / "tasks" / task_id / "trajectory.json"
        try:
            turns = assistant_turns(trajectory_path)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            skipped.append({"task_id": task_id, "reason": f"invalid trajectory: {error}"})
            continue
        if min_turns < turns < max_turns:
            candidates.append(Candidate(task_id, domain, turns, score, bucket))

    bucket_order = {bucket: index for index, bucket in enumerate(BUCKETS)}
    candidates.sort(key=lambda item: (bucket_order[item.score_bucket], item.turns, item.task_id))
    return candidates, skipped


def write_candidates(
    path: Path,
    candidates: list[Candidate],
    skipped: list[dict[str, str]],
    min_turns: int,
    max_turns: int,
) -> None:
    grouped = {
        bucket: [asdict(item) for item in candidates if item.score_bucket == bucket]
        for bucket in BUCKETS
    }
    write_json_atomic(
        path,
        {
            "generated_at": utc_now(),
            "turn_definition": "number of trajectory messages whose role is assistant",
            "strict_turn_filter": f"{min_turns} < turns < {max_turns}",
            "buckets": grouped,
            "skipped": skipped,
        },
    )


def build_shared_images(environment_image: str, proxy_image: str) -> None:
    commands = [
        [
            "docker", "build", "--tag", environment_image, "--file",
            str(ARCHIPELAGO_DIR / "environment/Dockerfile"), str(ARCHIPELAGO_DIR),
        ],
        ["docker", "build", "--tag", proxy_image, str(BENCHMARK_DIR / "proxy")],
    ]
    for command in commands:
        subprocess.run(command, check=True)


def safe_fragment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)[:80]


def run_model(
    model_name: str,
    config_path: Path,
    candidate: Candidate,
    run_output: Path,
    driver_logs: Path,
    base_port: int,
    runtime_cidr: str,
    environment_image: str,
    proxy_image: str,
) -> dict[str, Any]:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    unique = str(time.time_ns())[-8:]
    run_id = safe_fragment(
        f"difficulty_{model_name}_{stamp}_{unique}_{candidate.task_id}"
    )
    command = [
        str(BENCHMARK_DIR / "run_concurrency.sh"),
        candidate.task_id,
        "--concurrency", "1",
        "--base-port", str(base_port),
        "--skip-build",
        "--environment-image", environment_image,
        "--proxy-image", proxy_image,
        "--run-id", run_id,
    ]
    environment = os.environ.copy()
    environment["ORCHESTRATOR_CONFIG"] = str(config_path.resolve())
    environment["SCORE_SUMMARY_FILENAME"] = "score_summary.json"
    environment["RUNTIME_NETWORK_CIDR"] = runtime_cidr
    log_path = driver_logs / f"{run_id}.log"
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command,
            cwd=BENCHMARK_DIR,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )

    run_dir = run_output / run_id
    score: float | None = None
    error: str | None = None
    summary_path = run_dir / "score_summary.json"
    if completed.returncode == 0 and summary_path.is_file():
        try:
            rows = read_json(summary_path).get("tasks", [])
            match = next(row for row in rows if row.get("task_id") == candidate.task_id)
            score = float(match["final_score"])
        except (OSError, json.JSONDecodeError, KeyError, StopIteration, TypeError, ValueError) as exc:
            error = f"could not read score: {exc}"
    else:
        error = f"runner exited {completed.returncode}"

    return {
        "model": model_name,
        "score": score,
        "bucket": score_bucket(score) if score is not None else None,
        "matches_gemini_bucket": (
            score is not None and score_bucket(score) == candidate.score_bucket
        ),
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "driver_log": str(log_path),
        "error": error,
    }


def write_attempts_csv(path: Path, attempts: list[dict[str, Any]]) -> None:
    fields = [
        "task_id", "domain", "turns", "gemini_score", "score_bucket",
        "gpt_5_6_sol_score", "gpt_5_6_sol_matches", "opus_score",
        "opus_matches", "status", "retained", "gpt_5_6_sol_error",
        "opus_error", "attempted_at",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for attempt in attempts:
            models = attempt.get("models", {})
            gpt = models.get("gpt_5_6_sol", {})
            opus = models.get("opus", {})
            writer.writerow(
                {
                    "task_id": attempt["task_id"],
                    "domain": attempt["domain"],
                    "turns": attempt["turns"],
                    "gemini_score": attempt["gemini_score"],
                    "score_bucket": attempt["score_bucket"],
                    "gpt_5_6_sol_score": gpt.get("score"),
                    "gpt_5_6_sol_matches": gpt.get("matches_gemini_bucket"),
                    "opus_score": opus.get("score"),
                    "opus_matches": opus.get("matches_gemini_bucket"),
                    "status": attempt.get("status"),
                    "retained": attempt.get("retained"),
                    "gpt_5_6_sol_error": gpt.get("error"),
                    "opus_error": opus.get("error"),
                    "attempted_at": attempt.get("attempted_at"),
                }
            )
    temporary.replace(path)


def quota_counts(attempts: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts = {bucket: {domain: 0 for domain in QUOTAS[bucket]} for bucket in BUCKETS}
    for attempt in attempts:
        bucket = attempt.get("score_bucket")
        domain = attempt.get("domain")
        if attempt.get("retained") and bucket in counts and domain in counts[bucket]:
            counts[bucket][domain] += 1
    return counts


def attempt_has_scores(attempt: dict[str, Any]) -> bool:
    """Return true only when both model runs produced numeric scores."""
    models = attempt.get("models")
    if not isinstance(models, dict):
        return False
    for model_name in MODEL_CONFIGS:
        result = models.get(model_name)
        if not isinstance(result, dict):
            return False
        score = result.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return False
    return True


def save_report(report_path: Path, csv_path: Path, report: dict[str, Any]) -> None:
    report["updated_at"] = utc_now()
    report["quota_counts"] = quota_counts(report["attempts"])
    write_json_atomic(report_path, report)
    write_attempts_csv(csv_path, report["attempts"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gemini-run", type=Path, default=DEFAULT_GEMINI_RUN)
    parser.add_argument("--tasks-json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-output", type=Path, default=DEFAULT_RUN_OUTPUT)
    parser.add_argument("--min-turns", type=int, default=30)
    parser.add_argument("--max-turns", type=int, default=100)
    parser.add_argument(
        "--model-max-turns",
        type=int,
        default=80,
        help=(
            "Do not run GPT/Opus for tasks above this turn count; record both "
            "model scores as 0 (default: 80)."
        ),
    )
    parser.add_argument("--gpt-base-port", type=int, default=19080)
    parser.add_argument("--opus-base-port", type=int, default=19180)
    parser.add_argument(
        "--gpt-runtime-cidr",
        default="10.254.0.0/16",
        help="Docker runtime network pool for GPT (default: 10.254.0.0/16).",
    )
    parser.add_argument(
        "--opus-runtime-cidr",
        default="10.255.0.0/16",
        help="Docker runtime network pool for Opus (default: 10.255.0.0/16).",
    )
    parser.add_argument("--environment-image", default="archipelago-hf-environment:concurrency")
    parser.add_argument("--proxy-image", default="archipelago-hf-runtime-proxy:concurrency")
    parser.add_argument(
        "--skip-build", action="store_true",
        help="Reuse the shared environment/proxy images instead of building them once.",
    )
    parser.add_argument(
        "--prepare-only", action="store_true",
        help="Only generate the sorted candidate inventory; do not run models.",
    )
    parser.add_argument(
        "--retry-attempted", action="store_true",
        help="Rerun tasks already present in attempts.json instead of resuming past them.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.min_turns >= args.max_turns:
        raise ValueError("--min-turns must be smaller than --max-turns")
    if args.model_max_turns < 0:
        raise ValueError("--model-max-turns must be non-negative")
    if args.gpt_base_port == args.opus_base_port:
        raise ValueError("GPT and Opus must use different base ports")
    try:
        gpt_network = ipaddress.ip_network(args.gpt_runtime_cidr)
        opus_network = ipaddress.ip_network(args.opus_runtime_cidr)
    except ValueError as error:
        raise ValueError(f"invalid runtime CIDR: {error}") from error
    if not isinstance(gpt_network, ipaddress.IPv4Network) or not isinstance(
        opus_network, ipaddress.IPv4Network
    ):
        raise ValueError("GPT and Opus runtime CIDRs must be IPv4 networks")
    if gpt_network.overlaps(opus_network):
        raise ValueError(
            f"GPT runtime CIDR {gpt_network} overlaps Opus runtime CIDR {opus_network}"
        )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    driver_logs = output_dir / "driver_logs"
    driver_logs.mkdir(exist_ok=True)
    tasks_json = find_tasks_json(args.tasks_json)
    candidates, skipped = collect_candidates(
        args.gemini_run.resolve(),
        load_domains(tasks_json),
        args.min_turns,
        args.max_turns,
    )
    candidates_path = output_dir / "candidates.json"
    write_candidates(
        candidates_path, candidates, skipped, args.min_turns, args.max_turns
    )
    print(f"Wrote {len(candidates)} sorted candidates to {candidates_path}", flush=True)
    if args.prepare_only:
        return 0

    for name, config in MODEL_CONFIGS.items():
        if not config.is_file():
            raise FileNotFoundError(f"missing {name} config: {config}")
    if not args.skip_build:
        print("Building shared environment and proxy images once...", flush=True)
        build_shared_images(args.environment_image, args.proxy_image)

    report_path = output_dir / "attempts.json"
    csv_path = output_dir / "attempts.csv"
    if report_path.is_file() and not args.retry_attempted:
        report = read_json(report_path)
        attempts = report.setdefault("attempts", [])
    else:
        report = {
            "created_at": utc_now(),
            "gemini_run": str(args.gemini_run.resolve()),
            "tasks_json": str(tasks_json),
            "quotas": QUOTAS,
            "runtime_cidrs": {
                "gpt_5_6_sol": str(gpt_network),
                "opus": str(opus_network),
            },
            "attempts": [],
        }
        attempts = report["attempts"]

    report["runtime_cidrs"] = {
        "gpt_5_6_sol": str(gpt_network),
        "opus": str(opus_network),
    }
    # Infrastructure failures (including the old score=None records) must be
    # retried on resume. Only completed two-model comparisons count as tried.
    attempted_ids = {
        attempt.get("task_id") for attempt in attempts if attempt_has_scores(attempt)
    }
    counts = quota_counts(attempts)
    by_bucket = {
        bucket: [candidate for candidate in candidates if candidate.score_bucket == bucket]
        for bucket in BUCKETS
    }

    for bucket in BUCKETS:
        print(f"Starting bucket: {BUCKET_LABELS[bucket]}", flush=True)
        for candidate in by_bucket[bucket]:
            if all(counts[bucket][domain] >= quota for domain, quota in QUOTAS[bucket].items()):
                break
            if counts[bucket][candidate.domain] >= QUOTAS[bucket][candidate.domain]:
                continue
            if candidate.task_id in attempted_ids and not args.retry_attempted:
                continue

            print(
                f"Trying {candidate.task_id} domain={candidate.domain} "
                f"turns={candidate.turns} gemini={candidate.gemini_score}",
                flush=True,
            )
            if candidate.turns > args.model_max_turns:
                # Long trajectories are deliberately excluded from model reruns.
                # Keep a complete numeric result so resume logic considers this
                # candidate handled and does not repeatedly revisit it.
                model_results = {
                    name: {
                        "model": name,
                        "score": 0.0,
                        "bucket": None,
                        "matches_gemini_bucket": False,
                        "returncode": None,
                        "elapsed_seconds": 0.0,
                        "run_id": None,
                        "run_dir": None,
                        "driver_log": None,
                        "error": f"skipped: turns={candidate.turns} > {args.model_max_turns}",
                    }
                    for name in MODEL_CONFIGS
                }
                retained = False
                status = "skipped_turn_limit"
                print(
                    f"Skipping model runs: turns={candidate.turns} "
                    f"> {args.model_max_turns}; both scores set to 0",
                    flush=True,
                )
            else:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = {
                        name: executor.submit(
                            run_model,
                            name,
                            config,
                            candidate,
                            args.run_output.resolve(),
                            driver_logs,
                            args.gpt_base_port if name == "gpt_5_6_sol" else args.opus_base_port,
                            (
                                str(gpt_network)
                                if name == "gpt_5_6_sol"
                                else str(opus_network)
                            ),
                            args.environment_image,
                            args.proxy_image,
                        )
                        for name, config in MODEL_CONFIGS.items()
                    }
                    model_results = {name: future.result() for name, future in futures.items()}

                retained = all(
                    result["matches_gemini_bucket"] for result in model_results.values()
                )
                status = (
                    "completed"
                    if all(result["score"] is not None for result in model_results.values())
                    else "infrastructure_error"
                )
            attempt = {
                **asdict(candidate),
                "attempted_at": utc_now(),
                "models": model_results,
                "status": status,
                "retained": retained,
            }
            attempts.append(attempt)
            if attempt_has_scores(attempt):
                attempted_ids.add(candidate.task_id)
            if retained:
                counts[bucket][candidate.domain] += 1
            save_report(report_path, csv_path, report)
            scores = ", ".join(
                f"{name}={result['score']} match={result['matches_gemini_bucket']}"
                for name, result in model_results.items()
            )
            print(f"Result retained={retained}: {scores}", flush=True)
            if not attempt_has_scores(attempt):
                failures = "; ".join(
                    f"{name}: {result.get('error') or 'score missing'} "
                    f"(log: {result['driver_log']})"
                    for name, result in model_results.items()
                    if result.get("score") is None
                )
                print(
                    "Stopping after infrastructure failure to avoid empty-running "
                    f"the remaining candidates. {failures}",
                    file=sys.stderr,
                    flush=True,
                )
                return 3

    save_report(report_path, csv_path, report)
    unmet = {
        bucket: {
            domain: QUOTAS[bucket][domain] - counts[bucket][domain]
            for domain in QUOTAS[bucket]
            if counts[bucket][domain] < QUOTAS[bucket][domain]
        }
        for bucket in BUCKETS
    }
    unmet = {bucket: domains for bucket, domains in unmet.items() if domains}
    if unmet:
        print(f"Finished with unmet quotas: {json.dumps(unmet, sort_keys=True)}", flush=True)
        return 2
    print(f"All quotas filled. Results: {report_path} and {csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; completed attempts remain saved.", file=sys.stderr)
        raise SystemExit(130)
