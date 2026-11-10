#!/usr/bin/env python3
"""Run the generated bundle with any existing orchestrator config and graders."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Existing config suffix, e.g. deepseekv4 or gemini37")
    parser.add_argument("--concurrency", type=int, default=15)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-root", type=Path, default=ROOT / "benchmark/output/final_15_more")
    args, extra = parser.parse_known_args()
    if not args.model or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in args.model):
        parser.error("model must be an existing config suffix")
    if args.concurrency < 1:
        parser.error("concurrency must be positive")
    configs = [p for p in (ROOT / f"benchmark/orchestrator_config_{args.model}.json",
                          ROOT / f"litellm_configs/{args.model}.json") if p.is_file()]
    if len(configs) != 1 or not json.loads(configs[0].read_text()).get("model"):
        parser.error("expected exactly one existing model config")
    subprocess.run([sys.executable, str(HERE / "generate_final_15_more.py"), "--validate-only"], cwd=ROOT, check=True)
    run_id = f"{args.model}_more15_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
    command = ["bash", str(ROOT / "benchmark/run_concurrency.sh"),
               "--task-json", str(HERE / "final_15_more/selected_15_tasks_with_attack_config.json"),
               "--concurrency", str(args.concurrency), "--run-id", run_id,
               "--output-root", str(args.output_root.resolve() / args.model)]
    if args.skip_build:
        command.append("--skip-build")
    # Allow ordinary runner flags such as --timer and --base-port, while keeping
    # the validated task source, model and results destination fixed above.
    if any(flag.split("=", 1)[0] in {"--task-json", "--attack-config-json", "--all", "--output-root", "--run-id"} for flag in extra):
        parser.error("extra arguments cannot replace the bundle or results destination")
    command.extend(extra)
    env = os.environ.copy()
    for key in ("ATTACK_CONFIG_FILE", "ATTACK_CONFIG_BASE_DIR", "ATTACK_TASK_SELECTOR"):
        env.pop(key, None)
    env["ORCHESTRATOR_CONFIG"] = str(configs[0])
    print(f"ORCHESTRATOR_CONFIG={shlex.quote(str(configs[0]))} {shlex.join(command)}", flush=True)
    if not args.dry_run:
        subprocess.run(command, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
