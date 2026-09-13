"""Run paired visibility conditions in one worker pool and summarize raw grades."""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from benchmark import run_models_parallel as parallel

CATEGORIES = ['static_prompt_injection', 'static_script_injection']


def plan(input_root, conditions):
    groups = []
    for condition in conditions:
        jobs = parallel.plan_jobs(input_root / condition, ['gpt', 'gemini36'], CATEGORIES)
        groups.append([replace(job, category=f'{condition}/{job.category}') for job in jobs])
    # Interleave conditions as well as models/categories within the shared pool.
    return [group[i] for i in range(max(map(len, groups))) for group in groups if i < len(group)]


def summarize(run_dir):
    manifest = json.loads((run_dir / 'manifest.json').read_text())
    groups = {}
    for key in manifest['jobs']:
        model, condition, category, task = key.split('/')
        path = run_dir / model / condition / category / 'tasks' / task / 'grades.json'
        try:
            grade = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            grade = {}
        result = manifest.get('results', {}).get(key)
        for scope in ['all', category]:
            group = groups.setdefault((model, condition, scope), {
                'requested': 0, 'finished': 0, 'failed': 0,
                'exposure_rate': [], 'asr': [], 'score': []})
            group['requested'] += 1
            group['finished'] += int(result is not None)
            group['failed'] += int(result is not None and result['returncode'] != 0)
            values = {'exposure_rate': grade.get('prompt_exposure'),
                      'asr': grade.get('attack_success'),
                      'score': (grade.get('scoring_results') or {}).get('final_score')}
            for metric, value in values.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                    group[metric].append(value)
    rows = []
    for (model, condition, category), group in sorted(groups.items()):
        row = dict(model=model, condition=condition, category=category,
                   requested=group['requested'], finished=group['finished'], failed=group['failed'])
        for metric in ['exposure_rate', 'asr', 'score']:
            values = group[metric]
            row[metric] = sum(values) / len(values) if values else None
            row[metric + '_n'] = len(values)
        rows.append(row)
    (run_dir / 'comparison.json').write_text(json.dumps(rows, indent=2) + '\n')
    with (run_dir / 'comparison.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ['# Hidden-file ablation', '',
             '`with` = visible attack files; `without` = hidden attack files.', '',
             'Rates use available evaluations; missing values are not counted as zero. '
             'Each metric shows its own evaluated count. Score is mean original-task utility (0–1). '
             'Exposure is the benchmark prompt_exposure metric.', '',
             '| Model | Condition | Category | Finished/requested | Failed | Exposure (n) | ASR (n) | Score (n) |',
             '|---|---|---|---:|---:|---:|---:|---:|']
    for row in rows:
        cells = [row['model'], row['condition'], row['category'],
                 f"{row['finished']}/{row['requested']}", str(row['failed'])]
        for metric in ['exposure_rate', 'asr', 'score']:
            value = row[metric]
            formatted = 'N/A' if value is None else (f'{value:.4f}' if metric == 'score' else f'{value:.1%}')
            cells.append(f"{formatted} ({row[metric + '_n']})")
        lines.append('| ' + ' | '.join(cells) + ' |')
    (run_dir / 'comparison.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print(f'\nReports: {run_dir}/comparison.{{md,csv,json}}', flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--condition', choices=['both', 'with', 'without'], default='both')
    parser.add_argument('--input-root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output-root', type=Path, required=False,
                        default=ROOT/'benchmark/output/ablation/hideen')
    parser.add_argument('--concurrency', type=int, default=20)
    parser.add_argument('--base-port', type=int)
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--summarize', type=Path, metavar='RUN_DIR', help='Refresh reports without running models')
    args = parser.parse_args()
    if args.summarize:
        summarize(args.summarize.resolve())
        return 0
    if not 1 <= args.concurrency <= 64:
        parser.error('concurrency must be between 1 and 64')
    if args.base_port is not None and not 1 <= args.base_port <= 65536 - args.concurrency:
        parser.error('base-port leaves insufficient valid ports')
    conditions = ['with', 'without'] if args.condition == 'both' else [args.condition]
    jobs = plan(args.input_root.resolve(), conditions)
    if args.dry_run:
        print(json.dumps({'task_count': len(jobs), 'global_concurrency': min(args.concurrency, len(jobs)),
                          'jobs': [job.key for job in jobs]}, indent=2))
        return 0
    args.models = ['gpt', 'gemini36']
    args.timer = False
    args.output_root = args.output_root.resolve() / ('hidden_' + time.strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8])
    try:
        return parallel.execute(args, jobs)
    finally:
        # Also report partial results after a failed or interrupted experiment.
        for manifest in args.output_root.glob('*/manifest.json'):
            summarize(manifest.parent)


if __name__ == '__main__':
    sys.exit(main())
