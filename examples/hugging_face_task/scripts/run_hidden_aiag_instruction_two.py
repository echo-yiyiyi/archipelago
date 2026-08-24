#!/usr/bin/env python3
"""Run the AIAG new-file overlay twice with its instruction file hidden."""

import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = "task_ccd303088b344ea8b81c13dc04309142"
SOURCE_OVERLAY = ROOT / "input" / TASK / "position_variants_review" / "02_new_aiag_additional_task_instructions_txt" / "world_overlay"
OVERLAY = Path("/tmp/hidden_aiag_instruction_overlay")
RUNS = [
    ("iso_hidden_aiag_20260820_01", 18310, 21),
    ("iso_hidden_aiag_20260820_02", 18311, 22),
]


def prepare_overlay() -> Path:
    if OVERLAY.exists():
        shutil.rmtree(OVERLAY)
    OVERLAY.mkdir(parents=True)
    source = SOURCE_OVERLAY / "AIAG_Additional_Task_Instructions.txt"
    hidden = OVERLAY / ".AIAG_Additional_Task_Instructions.txt"
    shutil.copy2(source, hidden)
    return OVERLAY


def run_one(item):
    run_id, port, network_octet = item
    env = os.environ.copy()
    env["HF_EXPERIMENT_NAME"] = "email_send_file"
    env["HF_MAX_STEPS"] = "30"
    env["RUNTIME_NETWORK_CIDR"] = f"10.252.{network_octet}.0/28"
    env["RUNTIME_EGRESS_SUBNET"] = f"10.253.{network_octet}.0/28"
    command = [
        sys.executable, str(ROOT / "main_concurrency.py"), TASK,
        "--concurrency", "1", "--base-port", str(port),
        "--run-id", run_id, "--world-overlay", str(OVERLAY), "--skip-build",
    ]
    log_path = ROOT / "output" / "concurrent" / f"{run_id}.launcher.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        result = subprocess.run(command, cwd=ROOT.parent.parent / "agents",
                                env=env, stdout=log, stderr=subprocess.STDOUT)
    return run_id, result.returncode, str(log_path)


def main() -> int:
    prepare_overlay()
    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run_one, item) for item in RUNS]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"finished {result[0]} returncode={result[1]} log={result[2]}", flush=True)
    return 1 if any(code != 0 for _, code, _ in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
