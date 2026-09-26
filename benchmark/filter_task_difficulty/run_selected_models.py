#!/usr/bin/env python3
"""Run the selected 15 baseline tasks across models in one global worker pool."""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import csv
import fcntl
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import sys
import threading
import time
import uuid

HERE = Path(__file__).resolve().parent
BENCHMARK = HERE.parent
sys.path.insert(0, str(BENCHMARK))
DEFAULT_MODELS = ['gpt_astra_low', 'gemini36', 'gemini37', 'gemini38',
                  'luna', 'gpt_terra', 'glm53', 'deepseekv4', 'opus', 'sonnet5']


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def summarize(root, manifest):
    rows, details = [], []
    for model, info in manifest['models'].items():
        scores = []
        failed = 0
        for task in manifest['task_ids']:
            result = manifest['results'].get(f'{model}/{task}')
            score = None
            path = root / model / 'tasks' / task / 'grades.json'
            try:
                value = json.loads(path.read_text())['scoring_results']['final_score']
                if type(value) in (float, int) and math.isfinite(value):
                    score = float(value)
            except (OSError, ValueError, KeyError, TypeError):
                pass
            # A leftover/partial grade from a failed process is not a completed run.
            if result is None or result['returncode'] != 0:
                score = None
            if score is not None:
                scores.append(score)
            failed += int(result is not None and (result['returncode'] != 0 or score is None))
            details.append(dict(model=model, task_id=task, score=score,
                                returncode=result['returncode'] if result else None,
                                grades_file=str(path)))
        count = len(manifest['task_ids'])
        rows.append(dict(model=model, model_id=info['model_id'], total_tasks=count,
                         scored_tasks=len(scores), failed_tasks=failed,
                         mean_score=sum(scores) / count if len(scores) == count else None,
                         completed_mean_score=sum(scores) / len(scores) if scores else None))
    write_json(root / 'model_scores.json', rows)
    write_json(root / 'task_scores.json', details)
    temporary = root / 'model_scores.csv.tmp'
    with temporary.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(root / 'model_scores.csv')
    return rows


def completed(root, manifest, model, task):
    result = manifest['results'].get(f'{model}/{task}', {})
    if result.get('returncode') != 0:
        return False
    try:
        score = json.loads((root / model / 'tasks' / task / 'grades.json').read_text())['scoring_results']['final_score']
        return type(score) in (int, float) and math.isfinite(score)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks', type=Path, default=HERE / 'output/selected_15_tasks.json')
    parser.add_argument('--models', nargs='+', default=DEFAULT_MODELS,
                        help='Suffixes of benchmark/orchestrator_config_<name>.json')
    parser.add_argument('--concurrency', type=int, default=32)
    parser.add_argument('--output-root', type=Path, default=HERE / 'output/model_comparison')
    parser.add_argument('--retry-run', type=Path, help='Retry only incomplete tasks in this run; update its reports')
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--summarize', type=Path, help='Regenerate reports for an existing run directory')
    args = parser.parse_args(argv)
    if args.summarize:
        root = args.summarize.resolve()
        print(json.dumps(summarize(root, json.loads((root / 'manifest.json').read_text())), indent=2))
        return 0
    if not 1 <= args.concurrency <= 32:
        parser.error('--concurrency must be between 1 and 32')
    if args.retry_run:
        args.retry_run = args.retry_run.resolve()
        args.tasks = args.retry_run / 'selected_tasks.json'
    tasks = [row['task_id'] for row in json.loads(args.tasks.read_text())]
    if len(tasks) != 15 or len(set(tasks)) != 15 or any(not re.fullmatch(r'task_[A-Za-z0-9_-]+', t) for t in tasks):
        parser.error('--tasks must contain exactly 15 distinct task IDs')
    if len(set(args.models)) != len(args.models):
        parser.error('--models must be distinct')
    models = {}
    for name in args.models:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            parser.error(f'invalid model config name: {name}')
        path = BENCHMARK / f'orchestrator_config_{name}.json'
        config = json.loads(path.read_text())
        models[name] = dict(config=str(path), model_id=config['model'])
    jobs = [(model, task) for task in tasks for model in models]
    if args.retry_run:
        root = args.retry_run
        # Keep the lock open until process exit, including during cleanup/reporting.
        retry_lock = (root / '.retry.lock').open('a')
        try:
            fcntl.flock(retry_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another retry is updating this run; run retries sequentially or combine --models')
        manifest = json.loads((root / 'manifest.json').read_text())
        if any(model not in manifest['models'] for model in models):
            parser.error('Requested model is absent from the original run')
        for model, info in models.items():
            if info['model_id'] != manifest['models'][model]['model_id']:
                parser.error(f'{model}: model ID changed; use the original model for retries')
        jobs = [(model, task) for model, task in jobs if not completed(root, manifest, model, task)]
    if args.dry_run:
        print(json.dumps(dict(models=models, task_ids=tasks, total_runs=len(jobs),
                              concurrency=min(args.concurrency, len(jobs)), jobs=['/'.join(j) for j in jobs]), indent=2))
        return 0

    if not jobs:
        print('No incomplete tasks for the selected models.')
        if args.retry_run:
            summarize(root, manifest)
        return 0

    # Clear inherited experiment settings before loading the baseline runtime.
    for key in ('ATTACK_CONFIG_FILE', 'ATTACK_CONFIG_BASE_DIR', 'ATTACK_TASK_SELECTOR',
                'EXAMPLE_DIR', 'ARCHIPELAGO_DIR', 'AGENTS_DIR', 'ENVIRONMENT_DIR',
                'TASK_OUTPUT_ROOT', 'SCORE_SUMMARY_FILENAME', 'AGENT_MAX_STEPS',
                'ORCHESTRATOR_CONFIG', 'AGENT_TIMER_SECONDS'):
        os.environ.pop(key, None)
    import main_concurrency as runtime
    workers = min(args.concurrency, len(jobs))
    port = runtime.choose_available_base_port(workers)
    runtime.validate_ports(port, workers)
    subnets = runtime.allocate_runtime_subnets(workers)
    run_id = time.strftime('selected15_%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8]
    if args.retry_run:
        backup = root / 'retry_backups' / run_id
        backup.mkdir(parents=True)
        shutil.copy2(root / 'manifest.json', backup / 'manifest.json')
        for model, task in jobs:
            previous = root / model / 'tasks' / task
            if previous.exists():
                destination = backup / model / 'tasks' / task
                destination.parent.mkdir(parents=True, exist_ok=True)
                previous.rename(destination)
            result = manifest['results'].pop(f'{model}/{task}', None)
            if result and result.get('log_file'):
                log = Path(result['log_file'])
                if log.is_file():
                    destination = backup / model / 'logs' / log.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(log, destination)
        for model in {m for m, _ in jobs}:
            destination = backup / model / 'orchestrator_config.json'
            # Unstarted tasks may have neither task directories nor logs, so
            # the backup model directory has not necessarily been created.
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / model / 'orchestrator_config.json', destination)
            shutil.copy2(models[model]['config'], root / model / 'orchestrator_config.json')
        manifest['interrupted'] = False
        manifest.setdefault('retries', []).append(dict(id=run_id, jobs=['/'.join(j) for j in jobs]))
    else:
        root = args.output_root.resolve() / run_id
        root.mkdir(parents=True)
        shutil.copy2(args.tasks, root / 'selected_tasks.json')
        for model, info in models.items():
            directory = root / model
            (directory / 'logs').mkdir(parents=True)
            snapshot = directory / 'orchestrator_config.json'
            shutil.copy2(info['config'], snapshot)
            snapshot.chmod(0o600)
        manifest = dict(run_id=run_id, models=models, task_ids=tasks,
                        concurrency=workers, results={}, interrupted=False)

    def save():
        write_json(root / 'manifest.json', manifest)
        return summarize(root, manifest)

    save()
    print(f'Output: {root}\nRuns: {len(jobs)}; global concurrency: {workers}', flush=True)
    if not args.skip_build:
        runtime.build_environment_image(runtime.DEFAULT_IMAGE)
        runtime.build_proxy_image(runtime.DEFAULT_PROXY_IMAGE)
    networks = [(runtime.shared_resource_name(run_id, f'runtime_{i:02d}'), subnets[i]) for i in range(workers)]
    # Keep the original proxy files intact and isolate every retry's networks.
    proxy_root = root / 'retry_runtime' / run_id if args.retry_run else root
    proxy_dir = runtime.write_shared_proxy(proxy_root, runtime.DEFAULT_PROXY_IMAGE, networks)
    proxy_env = os.environ.copy()
    proxy_env['COMPOSE_PROJECT_NAME'] = runtime.shared_resource_name(run_id, 'proxy')
    slots = queue.Queue()
    for i in range(workers):
        slots.put(runtime.WorkerSlot(i, port + i))
    stop, active = threading.Event(), runtime.ActiveProcesses()

    def run(job):
        model, task = job
        slot = slots.get()
        try:
            return runtime.run_task(task, slot, root / model, runtime.DEFAULT_IMAGE,
                runtime.DEFAULT_PROXY_IMAGE, False, networks[slot.number][0], stop, active,
                None, None, environment_overrides={
                    'ORCHESTRATOR_CONFIG': str(root / model / 'orchestrator_config.json'),
                    'COMPOSE_PROJECT_NAME': runtime.compose_project_name(run_id + '_' + model, slot.number)})
        finally:
            slots.put(slot)

    finished_jobs = set()

    def record(future, job):
        if future.cancelled():
            return
        key = '/'.join(job)
        try:
            manifest['results'][key] = asdict(future.result())
        except Exception as error:
            manifest['results'][key] = dict(returncode=1, error=str(error))
        finished_jobs.add(key)
        runtime.update_score_summary(root / job[0])
        save()
        print(f"[{len(finished_jobs)}/{len(jobs)}] {key}: exit={manifest['results'][key]['returncode']}", flush=True)

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    old = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    pool, pending = None, {}
    try:
        runtime.start_shared_proxy(proxy_dir, proxy_env)
        pool = futures.ThreadPoolExecutor(max_workers=workers)
        remaining = iter(jobs)
        def submit():
            job = next(remaining, None)
            if job is not None:
                pending[pool.submit(run, job)] = job
        for _ in range(workers):
            submit()
        while pending:
            done, _ = futures.wait(pending, return_when=futures.FIRST_COMPLETED)
            for future in done:
                record(future, pending.pop(future))
                submit()
    except KeyboardInterrupt:
        manifest['interrupted'] = True
    finally:
        for sig in old:
            signal.signal(sig, signal.SIG_IGN)
        stop.set()
        try:
            for future in pending:
                future.cancel()
            active.terminate_all()
            if pool:
                pool.shutdown(wait=True, cancel_futures=True)
            for future, job in pending.items():
                record(future, job)
        finally:
            runtime.cleanup_shared_proxy(proxy_dir, proxy_env)
            rows = save()
            for sig, handler in old.items():
                signal.signal(sig, handler)
    for row in rows:
        print(f"{row['model']:16} mean_score={row['mean_score']} ({row['scored_tasks']}/15 scored)")
    print(f"Report: {root / 'model_scores.csv'}")
    return 130 if manifest['interrupted'] else int(any(not completed(root, manifest, model, task) for model, task in jobs))


if __name__ == '__main__':
    sys.exit(main())
