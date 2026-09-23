#!/usr/bin/env python3
"""Run prepared position-variant trajectories with isolated worlds in one batch."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import main_concurrency
from run_isolated_batch import choose_free_network_second_octet


EXAMPLE_DIR = Path(__file__).resolve().parent
AGENTS_DIR = Path(
    os.environ.get("AGENTS_DIR", EXAMPLE_DIR.parent.parent / "agents")
).resolve()


@dataclass(frozen=True)
class PreparedRun:
    position: str
    experiment: str
    trajectory: Path
    world_overlay: Path | None
    additional_turns: int
    repeat: int


def load_runs(manifest_path: Path, repeats: int, excluded: set[str]) -> tuple[str, list[PreparedRun]]:
    manifest = json.loads(manifest_path.read_text())
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("manifest must contain a cases list")
    task_dir = manifest_path.parent.parent
    if not task_dir.name.startswith("task_"):
        raise ValueError("manifest must be inside a task_* directory")
    runs: list[PreparedRun] = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("name"), str):
            raise ValueError("each case must have a name")
        name = case["name"]
        if name in excluded:
            continue
        case_dir = manifest_path.parent / name
        trajectory_value = case.get("trajectory")
        trajectory = (
            manifest_path.parent / trajectory_value
            if isinstance(trajectory_value, str)
            else case_dir / "trajectory.json"
        )
        if not trajectory.is_file():
            raise ValueError(f"missing prepared trajectory: {trajectory}")
        overlay_value = case.get("world_overlay")
        overlay = case_dir / overlay_value if isinstance(overlay_value, str) else None
        if overlay is not None and not overlay.is_dir():
            raise ValueError(f"missing world overlay: {overlay}")
        turns = case.get("additional_turns")
        if not isinstance(turns, int) or turns < 1:
            raise ValueError(f"invalid additional_turns for {name}")
        experiment = case.get("security_variant")
        if not isinstance(experiment, str) or not experiment:
            raise ValueError(f"missing security_variant for {name}")
        for repeat in range(1, repeats + 1):
            runs.append(PreparedRun(name, experiment, trajectory, overlay, turns, repeat))
    if not runs:
        raise ValueError("no prepared runs selected")
    return task_dir.name, runs


def child_result(run: PreparedRun, returncode: int, run_id: str) -> dict[str, object]:
    result: dict[str, object] = {
        "position": run.position,
        "experiment": run.experiment,
        "repeat": run.repeat,
        "run_id": run_id,
        "trajectory": f"output/concurrent/{run_id}/tasks",
        "returncode": returncode,
    }
    score_path = EXAMPLE_DIR / "output" / "concurrent" / run_id / "score_summary.json"
    try:
        score = json.loads(score_path.read_text())
        task = next(iter(score.get("tasks", [])), None)
        if isinstance(task, dict):
            for key in (
                "attack_success", "security_score", "security_judging_status",
                "final_score", "passed_at_1",
            ):
                if key in task:
                    result[key] = task[key]
    except (OSError, json.JSONDecodeError, TypeError):
        result["security_judging_status"] = "missing"
    return result


def write_summary(batch_dir: Path, results: list[dict[str, object]]) -> dict[str, object]:
    positions: dict[str, dict[str, object]] = {}
    for position in sorted({str(item["position"]) for item in results}):
        items = [item for item in results if item["position"] == position]
        judged = [item for item in items if item.get("security_judging_status") == "completed"]
        successes = sum(item.get("attack_success") is True for item in judged)
        positions[position] = {
            "run_count": len(items),
            "security_judged_count": len(judged),
            "security_unjudged_count": len(items) - len(judged),
            "attack_success_count": successes,
            "attack_success_rate": successes / len(judged) if judged else None,
        }
    judged_all = [item for item in results if item.get("security_judging_status") == "completed"]
    successes_all = sum(item.get("attack_success") is True for item in judged_all)
    summary: dict[str, object] = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_count": len(results),
        "security_judged_count": len(judged_all),
        "security_unjudged_count": len(results) - len(judged_all),
        "attack_success_count": successes_all,
        "attack_success_rate": successes_all / len(judged_all) if judged_all else None,
        "positions": positions,
        "runs": sorted(results, key=lambda item: str(item["run_id"])),
    }
    target = batch_dir / "score_summary.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(target)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--parallel", type=int, default=64)
    parser.add_argument("--base-port", type=int, default=30000)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1 or args.parallel < 1:
        parser.error("--repeats and --parallel must be positive")
    try:
        task_id, runs = load_runs(args.manifest.resolve(), args.repeats, set(args.exclude))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    if args.base_port < 1 or args.base_port + len(runs) > 65535:
        parser.error("--base-port leaves insufficient ports")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    batch_id = f"position_batch_{timestamp}_{task_id.removeprefix('task_')}"
    batch_dir = EXAMPLE_DIR / "input" / ".isolated_batches" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=False)
    (batch_dir / "batch_manifest.json").write_text(json.dumps({
        "batch_id": batch_id,
        "source_manifest": str(args.manifest.resolve()),
        "task_id": task_id,
        "repeats": args.repeats,
        "requested_parallel": args.parallel,
        "effective_parallel": min(args.parallel, len(runs)),
        "excluded": args.exclude,
        "runs": [
            {
                "position": run.position,
                "repeat": run.repeat,
                "trajectory": str(run.trajectory),
                "world_overlay": str(run.world_overlay) if run.world_overlay else None,
                "additional_turns": run.additional_turns,
                "experiment": run.experiment,
            }
            for run in runs
        ],
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"Prepared {len(runs)} runs in {batch_dir}", flush=True)
    if args.prepare_only:
        return 0

    main_concurrency.build_environment_image(main_concurrency.DEFAULT_IMAGE)
    main_concurrency.build_proxy_image(main_concurrency.DEFAULT_PROXY_IMAGE)
    network_second_octet = choose_free_network_second_octet()

    def launch(item: tuple[int, PreparedRun]) -> dict[str, object]:
        index, run = item
        run_id = (
            f"iso_pos_{timestamp}_{index:03d}_{run.position[:12]}_"
            f"{task_id.removeprefix('task_')[:8]}"
        )
        command = [
            sys.executable, str(EXAMPLE_DIR / "main_concurrency.py"), task_id,
            "--resume-trajectory", str(run.trajectory),
            "--additional-turns", str(run.additional_turns),
            "--concurrency", "1", "--base-port", str(args.base_port + index),
            "--run-id", run_id, "--skip-build",
        ]
        if run.world_overlay is not None:
            command.extend(["--world-overlay", str(run.world_overlay)])
        environment = os.environ.copy()
        environment["HF_EXPERIMENT_NAME"] = run.experiment
        environment["RUNTIME_NETWORK_CIDR"] = f"10.{network_second_octet}.{index}.0/28"
        environment["RUNTIME_EGRESS_SUBNET"] = f"10.{network_second_octet}.{index}.16/28"
        log_path = batch_dir / f"{index:03d}_{run.position}_{run.repeat}.launcher.log"
        with log_path.open("w") as output:
            completed = subprocess.run(
                command, cwd=AGENTS_DIR, env=environment,
                stdout=output, stderr=subprocess.STDOUT,
            )
        return child_result(run, completed.returncode, run_id)

    results: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(args.parallel, len(runs))
    ) as executor:
        futures = [executor.submit(launch, item) for item in enumerate(runs)]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            write_summary(batch_dir, results)
            print(
                f"Finished {result['position']} repeat {result['repeat']}: "
                f"{result['run_id']} security={result.get('security_judging_status')} "
                f"attack={result.get('attack_success')}",
                flush=True,
            )
    summary = write_summary(batch_dir, results)
    print(json.dumps({key: summary[key] for key in (
        "run_count", "security_judged_count", "security_unjudged_count",
        "attack_success_count", "attack_success_rate",
    )}, indent=2), flush=True)
    return 1 if any(item["returncode"] != 0 for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
