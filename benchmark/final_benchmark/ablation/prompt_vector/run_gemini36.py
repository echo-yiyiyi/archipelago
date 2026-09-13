#!/usr/bin/env python3
"""Evaluate Gemini 3.6 Flash on nine prompt vectors; report exposure and ASR."""
import argparse
import csv
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
sys.path.insert(0, str(REPO))
from benchmark import run_models_parallel as parallel

VECTORS = ('email', 'txt', 'xlsx', 'word', 'md', 'chat', 'html', 'pdf', 'calendar')
MODEL_CONFIG = REPO / 'benchmark/orchestrator_config_gemini36.json'


def plan(root):
    config = json.loads(MODEL_CONFIG.read_text())
    if config.get('model') != 'vertex_ai/gemini-3.6-flash':
        raise ValueError('gemini36 config no longer selects Gemini 3.6 Flash')
    batches, paired = [], None
    for vector in VECTORS:
        directory = root / vector
        source = directory / 'selected_5_tasks_with_attack_config.json'
        rows = json.loads(source.read_text())
        if len(rows) != 5 or len({r['task_id'] for r in rows}) != 5 or len({r['inject_goal'] for r in rows}) != 5:
            raise ValueError(f'{source}: expected five distinct task IDs and goals')
        signature = {}
        for row in rows:
            config = row['attack_config']
            if row['inject_vector'] != vector or row.get('add_user_prompt', config.get('add_user_prompt', False)):
                raise ValueError(f'{source}: incorrect static prompt vector settings')
            signature[row['task_id']] = (row['inject_goal'], row['prompt'],
                json.dumps(config, sort_keys=True).replace(row['harmful_task_id'], '<ID>'))
            for name in [row['attack_file'], *row['populate_files']]:
                path = (directory / name).resolve()
                if not path.is_relative_to(directory.resolve()) or not path.is_file():
                    raise ValueError(f'Missing/out-of-bundle artifact: {path}')
        if paired is not None and signature != paired:
            raise ValueError(f'{vector}: task/goal/config pairing differs')
        paired = signature
        batches.append((vector, source, rows, parallel.runtime.link_hosts_from_attack_config(source)))
    jobs = []
    for i in range(5):
        for vector, source, rows, hosts in batches:
            row = rows[i]
            jobs.append(parallel.Job('gemini36', vector, row['harmful_task_id'], row['task_id'],
                source, MODEL_CONFIG, row['inject_goal'], hosts.get(row['harmful_task_id'])))
    if len({j.key for j in jobs}) != 45:
        raise ValueError('Expected 45 unique jobs')
    return jobs


def summarize(run):
    manifest = json.loads((run / 'manifest.json').read_text())
    groups = {}
    for key in manifest['jobs']:
        model, vector, task = key.split('/')
        row = groups.setdefault(vector, dict(model=model, vector=vector, requested=0, finished=0,
            failed=0, exposed=0, exposure_evaluated=0, successful=0, attack_evaluated=0))
        result = manifest.get('results', {}).get(key)
        row['requested'] += 1
        row['finished'] += int(result is not None)
        row['failed'] += int(result is not None and result['returncode'] != 0)
        grade_path = run / model / vector / 'tasks' / task / 'grades.json'
        grade = json.loads(grade_path.read_text()) if grade_path.exists() else {}
        for field, count, success in [('prompt_exposure', 'exposure_evaluated', 'exposed'),
                                      ('attack_success', 'attack_evaluated', 'successful')]:
            value = grade.get(field)
            if type(value) in (int, float) and value in (0, 1):
                row[count] += 1
                row[success] += int(value)
    rows = []
    for vector in VECTORS:
        if vector not in groups:
            continue
        row = groups[vector]
        row['exposure_missing'] = row['requested'] - row['exposure_evaluated']
        row['attack_missing'] = row['requested'] - row['attack_evaluated']
        row['exposure_rate'] = row['exposed'] / row['exposure_evaluated'] if row['exposure_evaluated'] else None
        row['asr'] = row['successful'] / row['attack_evaluated'] if row['attack_evaluated'] else None
        rows.append(row)
    if not rows:
        raise ValueError('No prompt vector jobs in manifest')
    notes = ('Exposure rate uses the benchmark prompt_exposure grade; ASR uses attack_success. '
             'Each rate has its own denominator of valid binary grades. Missing grades are excluded, not zero. '
             'Valid grades are included even for process failures, which are reported separately.')
    parallel.write_json(run / 'vector_summary.json', {'notes': notes, 'interrupted': manifest.get('interrupted', False), 'rows': rows})
    with (run / 'vector_summary.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ['# Gemini 3.6 Flash — prompt vector results', '', notes, '',
        '| Vector | Exposure rate (exposed/evaluated) | ASR (successful/evaluated) | Finished/requested | Process failed | Missing exposure/attack |',
        '|---|---:|---:|---:|---:|---:|']
    def metric(row, name, numerator, denominator):
        value = 'N/A' if row[name] is None else f"{row[name]:.2%}"
        return f"{value} ({row[numerator]}/{row[denominator]})"
    for r in rows:
        lines.append(f"| {r['vector']} | {metric(r, 'exposure_rate', 'exposed', 'exposure_evaluated')} | "
            f"{metric(r, 'asr', 'successful', 'attack_evaluated')} | {r['finished']}/{r['requested']} | "
            f"{r['failed']} | {r['exposure_missing']}/{r['attack_missing']} |")
    report = '\n'.join(lines) + '\n'
    (run / 'vector_summary.md').write_text(report)
    print(report, flush=True)
    print(f'Reports: {run}/vector_summary.{{md,csv,json}}', flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', type=Path, default=ROOT)
    parser.add_argument('--output-root', type=Path, default=REPO / 'benchmark/output/ablation/prompt_vector')
    parser.add_argument('--concurrency', type=int, default=9, help='Shared task slots, 1..64 (default: 9)')
    parser.add_argument('--max-steps', type=int, default=100)
    parser.add_argument('--base-port', type=int)
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--summarize', type=Path, metavar='RUN_DIR', help='Refresh reports from an existing manifest.json directory')
    args = parser.parse_args()
    if args.summarize:
        summarize(args.summarize.resolve())
        return 0
    if not 1 <= args.concurrency <= 64 or args.max_steps < 1:
        parser.error('Require concurrency 1..64 and positive max-steps')
    if args.base_port is not None and not 1 <= args.base_port <= 65536 - args.concurrency:
        parser.error('base-port leaves insufficient valid ports')
    args.input_root = args.input_root.resolve()
    args.output_root = args.output_root.resolve()
    args.models = ['gemini36']
    args.timer = False
    os.environ['HF_MAX_STEPS'] = str(args.max_steps)
    os.umask(0o077)
    try:
        jobs = plan(args.input_root)
    except (OSError, ValueError) as e:
        parser.error(str(e))
    if args.dry_run:
        print(json.dumps({'model': json.loads(MODEL_CONFIG.read_text())['model'], 'runs': len(jobs),
            'vectors': VECTORS, 'tasks_per_vector': 5, 'concurrency': args.concurrency,
            'max_steps': args.max_steps, 'timer': False}, indent=2))
        return 0
    args.output_root /= 'gemini36_' + time.strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:6]
    args.output_root.mkdir(parents=True)
    try:
        return parallel.execute(args, jobs)
    finally:
        for manifest in args.output_root.glob('parallel_*/manifest.json'):
            summarize(manifest.parent)


if __name__ == '__main__':
    raise SystemExit(main())
