#!/usr/bin/env python3
"""Run the benign subset with any configured model and the existing scoring pipeline."""
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
    parser.add_argument('--model', required=True)
    parser.add_argument('--concurrency', type=int, default=15)
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args, extra = parser.parse_known_args()
    if not args.model or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.model):
        parser.error('Invalid model config suffix')
    if args.concurrency < 1: parser.error('Concurrency must be positive')
    config = ROOT / f'benchmark/orchestrator_config_{args.model}.json'
    if not config.is_file(): parser.error(f'Model config missing: {config}')
    if any(v.split('=', 1)[0] in {'--task-json','--attack-config-json','--output-root','--all','--run-id'} for v in extra):
        parser.error('Extra arguments cannot replace the benign task bundle or output destination')
    subprocess.run([sys.executable, str(HERE/'verify.py')], cwd=ROOT, check=True)
    command = ['bash', str(ROOT/'benchmark/run_concurrency.sh'),
               '--task-json', str(HERE/'selected_15_tasks_with_attack_config.json'),
               '--concurrency', str(args.concurrency), '--output-root', str(ROOT/'benchmark/output/benign_subset'/args.model),
               '--run-id', f'{args.model}_benign15_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}']
    if args.skip_build: command.append('--skip-build')
    command.extend(extra)
    env = os.environ.copy()
    for key in ['ATTACK_CONFIG_FILE', 'ATTACK_CONFIG_BASE_DIR', 'ATTACK_TASK_SELECTOR', 'INJECT_GOAL']:
        env.pop(key, None)
    env['ORCHESTRATOR_CONFIG'] = str(config)
    print('ORCHESTRATOR_CONFIG='+shlex.quote(str(config))+' '+shlex.join(command), flush=True)
    if not args.dry_run: subprocess.run(command, cwd=ROOT, env=env, check=True)


if __name__ == '__main__': main()
