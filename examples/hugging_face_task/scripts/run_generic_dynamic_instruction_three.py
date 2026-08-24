#!/usr/bin/env python3
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = "task_ccd303088b344ea8b81c13dc04309142"
RUNS = [
    ("iso_generic_20260817_000", 18200, 11),
    ("iso_generic_20260817_001", 18201, 12),
    ("iso_generic_20260817_002", 18202, 13),
]


def run_one(item: tuple[str, int, int]) -> tuple[str, int]:
    run_id, port, network_octet = item
    env = os.environ.copy()
    env["HF_EXPERIMENT_NAME"] = "prestarted_aiag_text_watcher"
    env["HF_MAX_STEPS"] = "50"
    env["RUNTIME_NETWORK_CIDR"] = f"10.245.{network_octet}.0/28"
    env["RUNTIME_EGRESS_SUBNET"] = f"10.246.{network_octet}.0/28"
    command = [
        sys.executable, str(ROOT / "main_concurrency.py"), TASK,
        "--concurrency", "1", "--base-port", str(port),
        "--run-id", run_id, "--skip-build",
    ]
    log_path = ROOT / "output" / "concurrent" / f"{run_id}.launcher.log"
    with log_path.open("w") as log:
        result = subprocess.run(command, cwd=ROOT.parent.parent / "agents",
                                env=env, stdout=log, stderr=subprocess.STDOUT)
    return run_id, result.returncode


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
