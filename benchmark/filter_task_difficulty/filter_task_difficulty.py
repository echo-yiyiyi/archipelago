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
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "score_1": {"law": 3, "banking": 3, "consulting": 3},
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


class ModelRunController:
    """Track model launchers so a completed mismatch can stop its peer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._cancel_reasons: dict[str, str] = {}

    def register(self, model_name: str, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._processes[model_name] = process
            reason = self._cancel_reasons.get(model_name)
        if reason is not None:
            self._interrupt(process)

    def unregister(self, model_name: str, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if self._processes.get(model_name) is process:
                self._processes.pop(model_name, None)

    def cancel(self, model_name: str, reason: str) -> None:
        with self._lock:
            self._cancel_reasons.setdefault(model_name, reason)
            process = self._processes.get(model_name)
        if process is not None:
            self._interrupt(process)

    def cancel_reason(self, model_name: str) -> str | None:
        with self._lock:
            return self._cancel_reasons.get(model_name)

    @staticmethod
    def _interrupt(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            # Signal only main_concurrency.py. It owns task termination and
            # Compose cleanup; signalling its whole process group would also
            # interrupt an in-flight `docker compose down` and strand networks.
            process.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass


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
    model_max_turns: int,
    controller: ModelRunController,
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
    # Allow exactly model_max_turns turns; the next step is the fuse point.
    environment["AGENT_MAX_STEPS"] = str(model_max_turns + 1)
    log_path = driver_logs / f"{run_id}.log"
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=BENCHMARK_DIR,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
        controller.register(model_name, process)
        try:
            returncode = process.wait()
        finally:
            controller.unregister(model_name, process)

    run_dir = run_output / run_id
    score: float | None = None
    error: str | None = None
    summary_path = run_dir / "score_summary.json"
    if returncode == 0 and summary_path.is_file():
        try:
            rows = read_json(summary_path).get("tasks", [])
            match = next(row for row in rows if row.get("task_id") == candidate.task_id)
            score = float(match["final_score"])
        except (OSError, json.JSONDecodeError, KeyError, StopIteration, TypeError, ValueError) as exc:
            error = f"could not read score: {exc}"
    else:
        error = f"runner exited {returncode}"

    cancel_reason = controller.cancel_reason(model_name)

    # A turn-limited agent may exit without a grading summary. Treat a
    # trajectory that crossed the limit as an intentional score of zero,
    # unless this run was deliberately interrupted after its peer mismatched.
    if score is None and cancel_reason is None:
        trajectory_path = run_dir / "tasks" / candidate.task_id / "trajectory.json"
        try:
            trajectory = read_json(trajectory_path)
            turns = assistant_turns(trajectory_path)
            if turns > model_max_turns:
                score = 0.0
                error = f"exceeded {model_max_turns} turns; treated as score 0"
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    cancelled_by_peer = cancel_reason is not None and score is None
    if cancelled_by_peer:
        error = cancel_reason

    return {
        "model": model_name,
        "score": score,
        "bucket": score_bucket(score) if score is not None else None,
        "matches_gemini_bucket": (
            score is not None and score_bucket(score) == candidate.score_bucket
        ),
        "returncode": returncode,
        "cancelled_by_peer": cancelled_by_peer,
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
    retained_task_ids: set[str] = set()
    for attempt in attempts:
        bucket = attempt.get("score_bucket")
        domain = attempt.get("domain")
        task_id = attempt.get("task_id")
        if (
            attempt.get("retained")
            and isinstance(task_id, str)
            and task_id not in retained_task_ids
            and bucket in counts
            and domain in counts[bucket]
        ):
            counts[bucket][domain] += 1
            retained_task_ids.add(task_id)
    return counts


def accept_score_one_tasks(
    attempts: list[dict[str, Any]],
    candidates: list[Candidate],
    task_ids: list[str],
) -> int:
    """Add explicit score=1 confirmations without discarding prior run history."""
    candidate_by_id = {candidate.task_id: candidate for candidate in candidates}
    already_retained = {
        attempt.get("task_id") for attempt in attempts if attempt.get("retained")
    }
    added = 0
    for task_id in dict.fromkeys(task_ids):
        candidate = candidate_by_id.get(task_id)
        if candidate is None:
            raise ValueError(f"--accept-score-one-task is not a candidate: {task_id}")
        if candidate.score_bucket != "score_1":
            raise ValueError(
                f"--accept-score-one-task requires Gemini score=1: {task_id}"
            )
        if task_id in already_retained:
            print(f"Already retained by task override: {task_id}", flush=True)
            continue
        attempts.append(
            {
                **asdict(candidate),
                "attempted_at": utc_now(),
                "models": {
                    model_name: {
                        "model": model_name,
                        "score": 1.0,
                        "bucket": "score_1",
                        "matches_gemini_bucket": True,
                        "manual_override": True,
                    }
                    for model_name in MODEL_CONFIGS
                },
                "status": "accepted_manually",
                "retained": True,
                "manual_override": "explicitly confirmed as matching score=1",
            }
        )
        already_retained.add(task_id)
        added += 1
        print(f"Accepted as matching score=1: {task_id}", flush=True)
    return added


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


def attempt_is_terminal(attempt: dict[str, Any]) -> bool:
    """Return true for a full comparison or any conclusive model mismatch."""
    if attempt_has_scores(attempt):
        return True
    models = attempt.get("models")
    if not isinstance(models, dict):
        return False
    results = [models.get(model_name) for model_name in MODEL_CONFIGS]
    return any(
        isinstance(result, dict)
        and
        isinstance(result.get("score"), (int, float))
        and not isinstance(result.get("score"), bool)
        and result.get("matches_gemini_bucket") is False
        for result in results
    )


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
            "Fuse GPT/Opus when their runtime trajectory exceeds this turn "
            "count and record that model score as 0 (default: 80)."
        ),
    )
    parser.add_argument("--gpt-base-port", type=int, default=19080)
    parser.add_argument("--opus-base-port", type=int, default=19180)
    parser.add_argument(
        "--gpt-runtime-cidr",
        default="172.30.0.0/16",
        help="Docker runtime network pool for GPT (default: 172.30.0.0/16).",
    )
    parser.add_argument(
        "--opus-runtime-cidr",
        default="172.31.0.0/16",
        help="Docker runtime network pool for Opus (default: 172.31.0.0/16).",
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
    parser.add_argument(
        "--accept-score-one-task",
        action="append",
        default=[],
        metavar="TASK_ID",
        help=(
            "Record a Gemini score=1 candidate as explicitly confirmed and retained. "
            "May be supplied more than once."
        ),
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
    report["quotas"] = QUOTAS
    if accept_score_one_tasks(attempts, candidates, args.accept_score_one_task):
        save_report(report_path, csv_path, report)
    # Infrastructure failures (including the old score=None records) must be
    # retried on resume. Only completed two-model comparisons count as tried.
    attempted_ids = {
        attempt.get("task_id") for attempt in attempts if attempt_is_terminal(attempt)
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
            controller = ModelRunController()
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    executor.submit(
                        run_model, name, config, candidate,
                        args.run_output.resolve(), driver_logs,
                        args.gpt_base_port if name == "gpt_5_6_sol" else args.opus_base_port,
                        str(gpt_network) if name == "gpt_5_6_sol" else str(opus_network),
                        args.environment_image, args.proxy_image, args.model_max_turns,
                        controller,
                    ): name
                    for name, config in MODEL_CONFIGS.items()
                }
                model_results = {}
                for future in as_completed(futures):
                    name = futures[future]
                    result = future.result()
                    model_results[name] = result
                    if (
                        result["score"] is not None
                        and not result["matches_gemini_bucket"]
                    ):
                        for peer_name in MODEL_CONFIGS:
                            if peer_name not in model_results:
                                reason = (
                                    f"cancelled because {name} scored {result['score']} "
                                    f"outside Gemini bucket {candidate.score_bucket}"
                                )
                                print(f"Interrupting {peer_name}: {reason}", flush=True)
                                controller.cancel(peer_name, reason)

            retained = all(
                result["matches_gemini_bucket"] for result in model_results.values()
            )
            all_scored = all(
                result["score"] is not None for result in model_results.values()
            )
            early_rejected = any(
                result.get("cancelled_by_peer") is True
                for result in model_results.values()
            )
            status = (
                "completed"
                if all_scored
                else "rejected_early" if early_rejected else "infrastructure_error"
            )
            attempt = {
                **asdict(candidate),
                "attempted_at": utc_now(),
                "models": model_results,
                "status": status,
                "retained": retained,
            }
            attempts.append(attempt)
            if attempt_is_terminal(attempt):
                attempted_ids.add(candidate.task_id)
            if retained:
                counts[bucket][candidate.domain] += 1
            save_report(report_path, csv_path, report)
            scores = ", ".join(
                f"{name}={result['score']} match={result['matches_gemini_bucket']}"
                for name, result in model_results.items()
            )
            print(f"Result retained={retained}: {scores}", flush=True)
            if not attempt_is_terminal(attempt):
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
