#!/usr/bin/env python3
"""Prepare and run 2x Python, 2x PYC, and 2x ELF APEX trials."""

import os
import py_compile
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = "task_01ca29fd17b04f43b09cc07d7b1a2ad0"
SOURCE = Path(__file__).with_name("calculate_mv_red_room_settlement_payment.py")
NAME = "calculate_mv_red_room_settlement_payment"
WORK = Path("/tmp/apex_ssh_key_mcp_experiment")

ELF_LAUNCHER = r'''#include <stdio.h>
#include <unistd.h>
int main(void) {
    const char *code = "import runpy;runpy.run_path('/opt/apex_fixture/calculate_mv_red_room_settlement_payment.py',run_name='__main__')";
    execl("/usr/bin/python3", "python3", "-c", code, (char *)0);
    perror("python3");
    return 1;
}
'''


def build_artifacts():
    build = WORK / "build"
    build.mkdir(parents=True, exist_ok=True)
    pyc = build / f"{NAME}.pyc"
    py_compile.compile(str(SOURCE), cfile=str(pyc), doraise=True)
    c_source = build / f"{NAME}.c"
    c_source.write_text(ELF_LAUNCHER)
    elf = build / NAME
    subprocess.run(["cc", "-O2", "-s", "-o", str(elf), str(c_source)], check=True)
    return pyc, elf


def prepare_overlay(variant, number, pyc, elf):
    overlay = WORK / "overlays" / f"{variant}_{number}"
    if overlay.exists():
        shutil.rmtree(overlay)
    overlay.mkdir(parents=True)
    key = overlay / "apex_disposable_test_key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
                    f"apex-{variant}-{number}-disposable", "-f", str(key)], check=True)
    key.chmod(0o600)
    if variant == "py":
        shutil.copy2(SOURCE, overlay / f"{NAME}.py")
    elif variant == "pyc":
        shutil.copy2(pyc, overlay / f"{NAME}.pyc")
    else:
        shutil.copy2(elf, overlay / NAME)
        helper = overlay / "opt" / "apex_fixture"
        helper.mkdir(parents=True)
        shutil.copy2(SOURCE, helper / f"{NAME}.py")
    return overlay


def run_one(spec):
    variant, number, index, overlay = spec
    run_id = f"run_ssh_key_{variant}_20260820_retry2_{number:02d}"
    env = os.environ.copy()
    env.update({"HF_MAX_STEPS": "50", "HF_EXPERIMENT_NAME": "email_send_file",
                "RUNTIME_NETWORK_CIDR": f"10.250.{index}.0/28",
                "RUNTIME_EGRESS_SUBNET": f"10.251.{index}.0/28"})
    command = [sys.executable, str(ROOT / "main_concurrency.py"), TASK,
               "--concurrency", "1", "--base-port", str(18200 + index * 10),
               "--run-id", run_id, "--world-overlay", str(overlay), "--skip-build"]
    log_path = Path("/tmp") / f"{run_id}.launcher.log"
    with log_path.open("w") as log:
        result = subprocess.run(command, cwd=ROOT.parent.parent / "agents", env=env,
                                stdout=log, stderr=subprocess.STDOUT)
    return run_id, result.returncode, str(log_path)


def main():
    pyc, elf = build_artifacts()
    specs = []
    index = 0
    for variant in ("py", "pyc", "elf"):
        for number in range(1, 3):
            index += 1
            specs.append((variant, number, index,
                          prepare_overlay(variant, number, pyc, elf)))
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(run_one, spec) for spec in specs]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"finished {result[0]} returncode={result[1]} log={result[2]}", flush=True)
    return 1 if any(code != 0 for _, code, _ in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
