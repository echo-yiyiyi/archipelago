#!/usr/bin/env python3
"""Retry ungraded tasks and aggregate one completed result per original job."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import time
import uuid

from run_gemini35 import runner

parallel = runner.parallel
DEFAULT_RUN = runner.OUTPUT_ROOT / 'all_20260913_230913_2e72f3/parallel_20260913_230913_835cc6a8'


def read(path):
    return json.loads(path.read_text())


def task_dir(run, key):
    model, *parts, task = key.split('/')
    setting = '/'.join(parts)
    return run / model / setting / 'tasks' / task


def complete(path):
    # Zero ASR/score is a valid completed evaluation, not a reason to retry.
    try:
        grade = read(path / 'grades.json')
        score = grade['scoring_results']['final_score']
        return (type(score) in (int, float) and math.isfinite(score)
                and all(type(grade.get(k)) in (int, float) and grade[k] in (0, 1)
                        for k in ('attack_success', 'prompt_exposure')))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def collect(run, manifest):
    selected = {}
    # Always prefer the original completed result, then the first completed retry.
    candidates = [run] + sorted((run / 'resume_attempts').glob('attempt_*/parallel_*'))
    for candidate in candidates:
        for key in manifest['jobs']:
            if key not in selected and complete(task_dir(candidate, key)):
                selected[key] = candidate
    return selected


def merge(run, manifest, selected):
    output = run / 'resumed_results'
    output.mkdir(exist_ok=True)
    results, provenance, batches = {}, {}, []
    for key in manifest['jobs']:
        target = task_dir(output, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            raise ValueError(f'Refusing to replace non-symlink: {target}')
        if key not in selected:
            continue
        source = selected[key]
        target.symlink_to(task_dir(source, key).resolve(), target_is_directory=True)
        source_manifest = read(source / 'manifest.json') if (source / 'manifest.json').exists() else {}
        results[key] = source_manifest.get('results', {}).get(key, {
            'returncode': 0, 'recovered_from_complete_grades': True})
        provenance[key] = str(source)
    for model, setting in sorted({(k.split('/')[0], '/'.join(k.split('/')[1:-1])) for k in manifest['jobs']}):
        directory = output / model / setting
        for name in ('attack_config.json', 'orchestrator_config.json'):
            shutil.copy2(run / model / setting / name, directory / name)
        summary = parallel.runtime.update_score_summary(directory)
        batches.append({'model': model, 'category': setting, **parallel.metrics(summary)})
    report = dict(manifest, run_id=output.name, results=results, batches=batches,
                  finished_task_count=len(selected), interrupted=len(selected) < len(manifest['jobs']),
                  source_batch=str(run), result_sources=provenance)
    parallel.write_json(output / 'manifest.json', report)
    runner.summarize(output)
    return output


def prepare_jobs(run, manifest, pending, attempt):
    jobs = []
    for model, setting in sorted({(k.split('/')[0], '/'.join(k.split('/')[1:-1])) for k in pending}):
        directory = attempt / 'inputs' / model / setting
        directory.mkdir(parents=True)
        original = run / model / setting
        rows = read(original / 'attack_config.json')
        source_base = Path(manifest['input_root']) / setting.split('/')[0]
        # Freeze metadata from the interrupted batch and snapshot the local payloads.
        for row in rows:
            names = set(row.get('populate_files', []))
            names.update(row[k] for k in ('attack_file', 'watcher_file', 'watcher_config') if row.get(k))
            for name in names:
                source = (source_base / name).resolve()
                target = directory / name
                if Path(name).is_absolute() or '..' in Path(name).parts:
                    raise ValueError(f'Expected bundle-relative artifact: {name}')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        config = directory / 'attack_config.json'
        shutil.copy2(original / 'attack_config.json', config)
        model_config = directory / 'orchestrator_config.json'
        shutil.copy2(original / 'orchestrator_config.json', model_config)
        hosts = parallel.runtime.link_hosts_from_attack_config(config)
        records = {r['harmful_task_id']: r for r in rows}
        for key in pending:
            m, *parts, task = key.split('/')
            s = '/'.join(parts)
            if (m, s) != (model, setting):
                continue
            row = records[task]
            jobs.append(parallel.Job(model, setting, task, row['task_id'], config,
                                     model_config, row['inject_goal'], hosts.get(task)))
    order = {key: i for i, key in enumerate(manifest['jobs'])}
    return sorted(jobs, key=lambda j: order[j.key])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--concurrency', type=int, default=40)
    parser.add_argument('--max-steps', type=int, default=150)
    parser.add_argument('--base-port', type=int)
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--summarize-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 64 or args.max_steps < 1:
        parser.error('Require concurrency 1..64 and positive max-steps')
    run = args.run_dir.resolve()
    manifest = read(run / 'manifest.json')
    if manifest['models'] != ['gemini35'] or len(set(manifest['jobs'])) != len(manifest['jobs']):
        parser.error('Expected a Gemini 3.5 batch with distinct jobs')
    os.umask(0o077)
    # A dry-run does not create files, start Docker, or call any model API.
    def status():
        selected = collect(run, manifest)
        pending = [k for k in manifest['jobs'] if k not in selected]
        print(json.dumps({'total': len(manifest['jobs']), 'skip_completed': len(selected),
                          'restart_or_start': len(pending), 'max_steps': args.max_steps,
                          'concurrency': min(args.concurrency, len(pending)),
                          'pending_jobs': pending}, indent=2), flush=True)
        return selected, pending
    if args.dry_run:
        status()
        return 0
    with (run / '.resume.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another resume launcher is active for this batch')
        selected, pending = status()
        merge(run, manifest, selected)
        if args.summarize_only or not pending:
            return 0
        attempt = run / 'resume_attempts' / ('attempt_' + time.strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:6])
        jobs = prepare_jobs(run, manifest, pending, attempt)
        args.output_root = attempt
        args.input_root = Path(manifest['input_root'])
        args.models = manifest['models']
        args.timer = manifest.get('timer', False)
        os.environ['HF_MAX_STEPS'] = str(args.max_steps)
        try:
            return parallel.execute(args, jobs)
        finally:
            merge(run, manifest, collect(run, manifest))


if __name__ == '__main__':
    raise SystemExit(main())
