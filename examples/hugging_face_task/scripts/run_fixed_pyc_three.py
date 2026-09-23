#!/usr/bin/env python3
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK = "task_01ca29fd17b04f43b09cc07d7b1a2ad0"
OVERLAY = ROOT / "input" / TASK / "pyc_mcp_experiment" / "world_overlay"
RUNS = [
    ("run_pyc_fixed2_20260817_01", 18140, 1),
    ("run_pyc_fixed2_20260817_02", 18150, 2),
    ("run_pyc_fixed2_20260817_03", 18160, 3),
]


def run_one(item: tuple[str, int, int]) -> tuple[str, int]:
    run_id, port, network_octet = item
    env = os.environ.copy()
    env["HF_MAX_STEPS"] = "30"
    env["HF_EXPERIMENT_NAME"] = "email_send_file"
    env["RUNTIME_NETWORK_CIDR"] = f"10.241.{network_octet}.0/28"
    env["RUNTIME_EGRESS_SUBNET"] = f"10.242.{network_octet}.0/28"
    command = [
        sys.executable,
        str(ROOT / "main_concurrency.py"),
        TASK,
        "--concurrency", "1",
        "--base-port", str(port),
        "--run-id", run_id,
        "--world-overlay", str(OVERLAY),
        "--skip-build",
    ]
    log_path = ROOT / "output" / "concurrent" / f"{run_id}.launcher.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        completed = subprocess.run(command, cwd=ROOT.parent.parent / "agents", env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
    return run_id, completed.returncode


def main() -> int:
    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run_one, item) for item in RUNS]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"finished {result[0]} returncode={result[1]}", flush=True)
    return 1 if any(code != 0 for _, code in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
