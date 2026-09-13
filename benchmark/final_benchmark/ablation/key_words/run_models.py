#!/usr/bin/env python3
"""Run paired keyword ablations across three models and summarize each model."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import csv
import itertools
import json
import math
import os
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from benchmark import run_models_parallel as parallel

ROOT = Path(__file__).resolve().parent
MODELS = ['gemini36', 'gpt_terra_high', 'deepseekv4']
CATEGORIES = ['static_prompt_injection', 'static_script_injection']


def plan(input_root, settings, models):
    groups = []
    paired = {}
    for setting in settings:
        jobs = parallel.plan_jobs(input_root / setting, models, CATEGORIES)
        for category in CATEGORIES:
            subset = [j for j in jobs if j.category == category and j.model == models[0]]
            if len(subset) != 10:
                raise ValueError(f'{setting}/{category}: expected exactly 10 tasks')
            keys = {(j.selector, j.dataset_selector, j.goal) for j in subset}
            if category in paired and paired[category] != keys:
                raise ValueError(f'{category}: with/without task pairing differs')
            paired[category] = keys
        groups.append([replace(j, category=f'{setting}/{j.category}') for j in jobs])
    return [job for wave in itertools.zip_longest(*groups) for job in wave if job is not None]


def weighted(rows, value, count):
    valid = [(r[value], r[count]) for r in rows if r[count] > 0 and r[value] is not None]
    denominator = sum(n for _, n in valid)
    return sum(v * n for v, n in valid) / denominator if denominator else None


def summarize(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    rows = []
    for batch in manifest['batches']:
        setting, category = batch['category'].split('/', 1)
        # Resolve relative to the manifest, so copied result folders still work.
        score_file = manifest_path.parent / batch['model'] / batch['category'] / 'score_summary.json'
        summary = json.loads(score_file.read_text()) if score_file.exists() else {}
        row = {k: batch[k] for k in ('model', 'requested_task_count', 'finished_task_count', 'failed_task_count')}
        row.update(setting=setting, category=category)
        for value, average, count in (
            ('asr', 'average_attack_success', 'attack_evaluated_count'),
            ('exposure_rate', 'average_prompt_exposure', 'prompt_exposure_task_count'),
            ('score', 'average_mean_score', 'completed_task_count'),
        ):
            n = summary.get(count, 0)
            v = summary.get(average)
            if not isinstance(n, int) or n < 0 or n > row['requested_task_count']:
                raise ValueError(f'{score_file}: invalid {count}')
            if n and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)):
                raise ValueError(f'{score_file}: invalid {average}')
            row[count] = n
            row[value] = v if n else None
        row['missing_attack_count'] = row['requested_task_count'] - row['attack_evaluated_count']
        row['missing_exposure_count'] = row['requested_task_count'] - row['prompt_exposure_task_count']
        row['missing_score_count'] = row['requested_task_count'] - row['completed_task_count']
        rows.append(row)
    count_fields = ['requested_task_count', 'finished_task_count', 'failed_task_count',
                    'attack_evaluated_count', 'prompt_exposure_task_count', 'completed_task_count',
                    'missing_attack_count', 'missing_exposure_count', 'missing_score_count']
    for model, setting in sorted({(r['model'], r['setting']) for r in rows}):
        group = [r for r in rows if r['model'] == model and r['setting'] == setting and r['category'] in CATEGORIES]
        total = {'model': model, 'setting': setting, 'category': 'combined'}
        total.update({k: sum(r[k] for r in group) for k in count_fields})
        total.update(asr=weighted(group, 'asr', 'attack_evaluated_count'),
                     exposure_rate=weighted(group, 'exposure_rate', 'prompt_exposure_task_count'),
                     score=weighted(group, 'score', 'completed_task_count'))
        rows.append(total)
    rows.sort(key=lambda r: (r['model'], r['setting'], r['category']))
    notes = ('ASR = successful attacks / security-evaluated tasks. Exposure rate = exposed tasks / '
             'exposure-evaluated tasks (the benchmark prompt_exposure field). Score = mean original-task '
             'final_score over tasks with valid grades. Combined rows weight by each metric\'s own denominator. '
             'Missing evaluations remain missing, not zero; failures and denominators are reported separately. '
             'With and without are never pooled together.')
    output = manifest_path.parent
    parallel.write_json(output / 'model_summary.json', {'notes': notes, 'interrupted': manifest.get('interrupted', False), 'rows': rows})
    if rows:
        with (output / 'model_summary.csv').open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    lines = ['# Keyword ablation results', '', notes, '',
             '| Model | Setting | Category | Finished/requested | Failed | ASR (n) | Exposure (n) | Score (n) |',
             '|---|---|---|---:|---:|---:|---:|---:|']
    def metric(row, name, count, percent=False):
        value = row[name]
        shown = 'N/A' if value is None else f'{value:.2%}' if percent else f'{value:.4f}'
        return f'{shown} ({row[count]})'
    for r in rows:
        lines.append(f"| {r['model']} | {r['setting']} | {r['category']} | "
                     f"{r['finished_task_count']}/{r['requested_task_count']} | {r['failed_task_count']} | "
                     f"{metric(r, 'asr', 'attack_evaluated_count', True)} | "
                     f"{metric(r, 'exposure_rate', 'prompt_exposure_task_count', True)} | "
                     f"{metric(r, 'score', 'completed_task_count')} |")
    (output / 'model_summary.md').write_text('\n'.join(lines) + '\n')
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', nargs='+', choices=['with', 'without'], default=['with', 'without'])
    parser.add_argument('--models', nargs='+', default=MODELS, help='Benchmark orchestrator config suffixes')
    parser.add_argument('--input-root', type=Path, default=ROOT)
    parser.add_argument('--output-root', type=Path, default=REPO / 'benchmark/output/key_words')
    parser.add_argument('--concurrency', type=int, default=64, help='Shared task slots across all settings and models')
    parser.add_argument('--base-port', type=int)
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--timer', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--summarize-only', type=Path, metavar='RUN_DIR')
    args = parser.parse_args(argv)
    if args.summarize_only:
        directory = args.summarize_only.resolve()
        manifests = [directory / 'manifest.json'] if (directory / 'manifest.json').exists() else list(directory.glob('parallel_*/manifest.json'))
        if len(manifests) != 1:
            parser.error('RUN_DIR must contain exactly one run manifest')
        summarize(manifests[0])
        print(manifests[0].parent / 'model_summary.md')
        return 0
    if not 1 <= args.concurrency <= 64 or len(set(args.settings)) != len(args.settings):
        parser.error('concurrency must be 1..64 and settings must be distinct')
    if args.base_port is not None and not 1 <= args.base_port <= 65536 - args.concurrency:
        parser.error('base port leaves insufficient valid ports')
    try:
        jobs = plan(args.input_root.resolve(), args.settings, args.models)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps({'task_count': len(jobs), 'global_concurrency': min(args.concurrency, len(jobs)),
                          'models': {m: json.loads(next(j.model_config for j in jobs if j.model == m).read_text())['model'] for m in args.models},
                          'jobs': [j.key for j in jobs]}, indent=2))
        return 0
    if 'deepseekv4' in args.models and not os.environ.get('DEEPSEEK_API_KEY'):
        parser.error('DEEPSEEK_API_KEY is required; export it in the launching environment. Do not put secrets in JSON.')
    if any(json.loads(j.model_config.read_text())['model'].startswith('openai/') for j in jobs) and not os.environ.get('OPENAI_API_KEY'):
        parser.error('OPENAI_API_KEY is required for OpenAI models; export it in the launching environment.')
    args.output_root = args.output_root.resolve() / ('keyword_' + datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:6])
    args.output_root.mkdir(parents=True)
    try:
        return parallel.execute(args, jobs)
    finally:
        for manifest in args.output_root.glob('parallel_*/manifest.json'):
            summarize(manifest)
            print(f'Summary: {manifest.parent / "model_summary.md"}', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
