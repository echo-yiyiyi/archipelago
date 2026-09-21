#!/usr/bin/env python3
"""Run final benchmark categories with an existing orchestrator configuration."""
from __future__ import annotations

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

ROOT = Path(__file__).resolve().parent
BENCHMARK = ROOT.parent
LAYOUT = {
    'static_prompt_injection': ('',),
    'static_script_injection': ('',),
    'user_prompt_script_swap': ('args', 'no_args'),
    'user_prompt_suffix_plant': ('',),
    'dynamic_prompt_injection': ('',),
    'dynamic_script_injection': (
        'allow_additional_instruction_true', 'allow_additional_instruction_false'),
}


def discover(category, root=ROOT):
    leaves = [f'{parent}/{child}'.rstrip('/') for parent, children in LAYOUT.items()
              for child in children]
    selected = [leaf for leaf in leaves if category == 'all' or leaf == category
                or leaf.startswith(category + '/')]
    if not selected:
        raise ValueError(f'unknown category: {category}; choose all or one of {list(LAYOUT)}')
    batches = []
    for leaf in selected:
        directory = root / leaf
        paths = sorted(directory.glob('selected_*_tasks_with_attack_config.json'))
        if len(paths) != 1:
            raise ValueError(f'{directory}: expected one complete task JSON, found {len(paths)}; remove obsolete versions or finish generation')
        path = paths[0]
        rows = json.loads(path.read_text())
        if not isinstance(rows, list) or not rows:
            raise ValueError(f'{path}: expected a nonempty task array')
        identifiers = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('attack_config'), dict):
                raise ValueError(f'{path}: missing task attack_config')
            identifier = row.get('harmful_task_id')
            if not identifier or identifier in identifiers or not row.get('task_id'):
                raise ValueError(f'{path}: missing or duplicate task identifier')
            identifiers.add(identifier)
            if not row.get('attack_file') or not row.get('populate_files'):
                raise ValueError(f'{path}: missing artifacts for {identifier}')
            for relative in [row['attack_file'], *row['populate_files']]:
                artifact = (directory / relative).resolve()
                if not artifact.is_relative_to(directory.resolve()) or not artifact.is_file():
                    raise ValueError(f'{path}: missing or out-of-bundle artifact {relative}')
            if leaf.startswith('dynamic_script_injection/'):
                enabled = leaf.endswith('_true')
                if row.get('add_user_prompt') is not False or row.get('user_allow_additional_instruction') is not enabled:
                    raise ValueError(f'{path}: outdated dynamic comparison flags; regenerate this bundle')
        batches.append((leaf, path.resolve(), len(rows)))
    return batches


def metrics(summary):
    def value(name, denominator):
        return summary.get(name) if summary.get(denominator, 0) else None
    return {
        'asr': value('average_attack_success', 'attack_evaluated_count'),
        'average_score': value('average_mean_score', 'completed_task_count'),
        'exposure_rate': value('average_prompt_exposure', 'prompt_exposure_task_count'),
        **{key: summary.get(key, 0) for key in (
            'attack_evaluated_count', 'completed_task_count', 'prompt_exposure_task_count')},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('category', help='Category, category/subcategory, or all')
    parser.add_argument('--model', required=True, help='Existing orchestrator config suffix, e.g. gemini35 or luna')
    parser.add_argument('--concurrency', type=int, default=3)
    parser.add_argument('--input-root', type=Path, default=ROOT,
                        help='Task category root, e.g. benchmark/all_category_test')
    parser.add_argument('--output-root', type=Path, default=BENCHMARK / 'output/final_benchmark')
    parser.add_argument('--temp-root', type=Path, help='Per-batch scratch parent on a separate data disk, automatically cleaned')
    parser.add_argument('--min-free-gb', type=float, default=30, help='Minimum free GiB on scratch/output filesystems')
    parser.add_argument('--min-system-free-gb', type=float, default=10, help='Minimum free GiB on system/Docker filesystem')
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--timer', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Validate inputs and print commands without Docker or model calls')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.model) or args.concurrency < 1:
        parser.error('model must be a config suffix and concurrency must be positive')
    if args.min_free_gb <= 0 or args.min_system_free_gb <= 0:
        parser.error('free-space thresholds must be positive')
    model_config = BENCHMARK / f'orchestrator_config_{args.model}.json'
    if not model_config.is_file():
        parser.error(f'model config does not exist: {model_config}')
    try:
        batches = discover(args.category, root=args.input_root.resolve())
        if not json.loads(model_config.read_text()).get('model'):
            raise ValueError(f'{model_config}: missing model field')
    except (ValueError, OSError) as error:
        parser.error(str(error))
    stamp = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
    output = args.output_root.resolve()
    report_path = output / 'summaries' / f'{args.model}_{args.category.replace("/", "_")}_{stamp}.json'
    report = {'model': args.model, 'model_config': str(model_config), 'category': args.category, 'batches': []}
    environment = os.environ.copy()
    environment['ORCHESTRATOR_CONFIG'] = str(model_config)
    # Each batch must resolve files and selectors from its own task JSON.
    for key in ('ATTACK_CONFIG_FILE', 'ATTACK_CONFIG_BASE_DIR', 'ATTACK_TASK_SELECTOR',
                'EXAMPLE_DIR', 'ARCHIPELAGO_DIR', 'TASK_OUTPUT_ROOT', 'SCORE_SUMMARY_FILENAME'):
        environment.pop(key, None)
    built = args.skip_build
    for category, task_json, count in batches:
        batch_id = f'{args.model}_{category.replace("/", "_")}_{stamp}'
        parent = output / category
        run_dir = parent / batch_id
        command = [sys.executable, str(BENCHMARK / 'main_concurrency.py'),
                   '--task-json', str(task_json), '--concurrency', str(args.concurrency),
                   '--run-id', batch_id, '--output-root', str(parent)]
        if built:
            command.append('--skip-build')
        if args.timer:
            command.append('--timer')
        print(f'{category}: {count} tasks\nORCHESTRATOR_CONFIG={shlex.quote(str(model_config))} {shlex.join(command)}', flush=True)
        if args.dry_run:
            continue
        try:
            if args.temp_root:
                if __package__:
                    from .runtime_storage import run_with_storage
                else:
                    from runtime_storage import run_with_storage
                result = run_with_storage(command, cwd=BENCHMARK.parent, env=environment,
                    temp_root=args.temp_root, output_root=output,
                    min_free_gb=args.min_free_gb, min_system_free_gb=args.min_system_free_gb)
            else:
                result = subprocess.run(command, cwd=BENCHMARK.parent, env=environment)
        except (OSError, ValueError) as error:
            print(f'Cannot start batch: {error}', file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print('Interrupted; stopping subsequent batches.', file=sys.stderr)
            return 130
        if result.returncode == 0:
            built = True
        score_file = run_dir / 'score_summary.json'
        summary = json.loads(score_file.read_text()) if score_file.is_file() else {}
        entry = {'category': category, 'batch_id': batch_id, 'task_count': count,
                 'returncode': result.returncode, 'output_dir': str(run_dir),
                 'score_summary': str(score_file), **metrics(summary)}
        report['batches'].append(entry)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(report_path)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        if result.returncode in (130, -2):
            return 130
    if not args.dry_run:
        print(f'Experiment summary: {report_path}')
    return int(any(batch['returncode'] != 0 for batch in report['batches']))


if __name__ == '__main__':
    raise SystemExit(main())
