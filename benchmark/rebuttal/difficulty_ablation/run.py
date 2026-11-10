#!/usr/bin/env python3
"""Run old-set difficulty groups through the existing benchmark runner/judges."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main(*, directory=HERE, axis="difficulty", levels=("easy", "medium", "hard"), output_name="difficulty_ablation"):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument(f"--{axis}", dest="group", choices=("all", *levels), default="all")
    parser.add_argument("--concurrency", type=int, default=15)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--include-reused", action="store_true", help="Rerun all 45 instances instead of just the 30 additions")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.model) or args.concurrency < 1:
        parser.error("model must be a config suffix and concurrency must be positive")
    configs = [p for p in (ROOT / f"benchmark/orchestrator_config_{args.model}.json",
                          ROOT / f"litellm_configs/{args.model}.json") if p.is_file()]
    if len(configs) != 1 or not json.loads(configs[0].read_text()).get("model"):
        parser.error("expected exactly one existing model configuration")
    subprocess.run([sys.executable, str(directory / "generate.py"), "--validate-only"], cwd=ROOT, check=True)
    env = os.environ.copy()
    for key in ("ATTACK_CONFIG_FILE", "ATTACK_CONFIG_BASE_DIR", "ATTACK_TASK_SELECTOR"):
        env.pop(key, None)
    env["ORCHESTRATOR_CONFIG"] = str(configs[0])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    selected = levels if args.group == "all" else (args.group,)
    for index, level in enumerate(selected):
        filename = "selected_15_tasks_with_attack_config.json" if args.include_reused else "new_tasks_with_attack_config.json"
        path = directory / level / filename
        count = len(json.loads(path.read_text()))
        run_id = f"{args.model}_old_{level}_{stamp}"
        command = ["bash", str(ROOT / "benchmark/run_concurrency.sh"), "--task-json", str(path),
                   "--concurrency", str(min(args.concurrency, count)), "--run-id", run_id,
                   "--output-root", str(ROOT / "benchmark/output" / output_name / args.model / level)]
        if args.skip_build or index:
            command.append("--skip-build")
        print(f"{level}: {count} old-set instances", flush=True)
        print(f"ORCHESTRATOR_CONFIG={shlex.quote(str(configs[0]))} {shlex.join(command)}", flush=True)
        if not args.dry_run:
            subprocess.run(command, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
