#!/usr/bin/env python3
"""Run model/category/task combinations through one shared pool of at most 64 slots."""
from __future__ import annotations

import argparse
import concurrent.futures as futures
from dataclasses import asdict, dataclass
import json
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

# Support both direct execution and importing in tests.
if __package__:
    from . import main_concurrency as runtime
    from .final_benchmark.run_experiments import discover, metrics
else:
    import main_concurrency as runtime
    from final_benchmark.run_experiments import discover, metrics

BENCHMARK = Path(__file__).resolve().parent
DEFAULT_MODELS = ['gemini36', 'gemini37', 'gemini38', 'gpt_astra_low', 'sonnet5']


@dataclass(frozen=True)
class Job:
    model: str
    category: str
    selector: str
    dataset_selector: str
    source: Path
    model_config: Path
    goal: str
    link_host: str | None

    @property
    def key(self) -> str:
        return f'{self.model}/{self.category}/{self.selector}'


def plan_jobs(input_root: Path, models: list[str], categories: list[str] | None = None) -> list[Job]:
    if not models or len(set(models)) != len(models):
        raise ValueError('provide distinct model config names')
    configs = {}
    for model in models:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', model):
            raise ValueError(f'invalid model config name: {model}')
        path = BENCHMARK / f'orchestrator_config_{model}.json'
        config = json.loads(path.read_text())
        if not isinstance(config.get('model'), str) or not config['model']:
            raise ValueError(f'{path}: missing model')
        configs[model] = path
    batches = []
    discovered = {}
    for selection in categories or ['all']:
        for category, path, count in discover(selection, root=input_root):
            discovered[category] = (category, path, count)
    for category, path, _ in discovered.values():
        rows = json.loads(path.read_text())
        hosts = runtime.link_hosts_from_attack_config(path)
        batches.append((category, path, rows, hosts))
    jobs = []
    # Interleave models AND categories, including in the first wave of slots.
    for index in range(max(len(rows) for _, _, rows, _ in batches)):
        for category, path, rows, hosts in batches:
            if index >= len(rows):
                continue
            row = rows[index]
            for model in models:
                jobs.append(Job(model, category, row['harmful_task_id'], row['task_id'],
                                path, configs[model], row['inject_goal'],
                                hosts.get(row['harmful_task_id'])))
    return jobs


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def execute(args, jobs):
    worker_count = min(args.concurrency, len(jobs))
    base_port = args.base_port or runtime.choose_available_base_port(worker_count)
    runtime.validate_ports(base_port, worker_count)
    subnets = runtime.allocate_runtime_subnets(worker_count)
    run_id = 'parallel_' + time.strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8]
    root = args.output_root.resolve() / run_id
    root.mkdir(parents=True, exist_ok=False)
    runtime._run_logger = runtime.RunLogger(root)
    batches = {}
    for job in jobs:
        key = (job.model, job.category)
        if key in batches:
            continue
        directory = root / job.model / job.category
        (directory / 'logs').mkdir(parents=True)
        attack_config = runtime.freeze_attack_config(job.source, directory)
        model_config = directory / 'orchestrator_config.json'
        shutil.copy2(job.model_config, model_config)
        batches[key] = (directory, attack_config, model_config)
        runtime.update_score_summary(directory)

    results = {}
    interrupted = False
    report = {'run_id': run_id, 'requested_concurrency': args.concurrency,
              'worker_count': worker_count, 'requested_task_count': len(jobs),
              'models': args.models, 'input_root': str(args.input_root.resolve()),
              'timer': args.timer, 'jobs': [job.key for job in jobs]}

    def save_report():
        summaries = []
        for (model, category), (directory, _, _) in batches.items():
            summary = json.loads((directory / runtime.SCORE_SUMMARY_FILENAME).read_text())
            subset = [j for j in jobs if j.model == model and j.category == category]
            done = [results[j.key] for j in subset if j.key in results]
            summaries.append({'model': model, 'category': category,
                              'requested_task_count': len(subset), 'finished_task_count': len(done),
                              'failed_task_count': sum(r['returncode'] != 0 for r in done),
                              'score_summary': str(directory / runtime.SCORE_SUMMARY_FILENAME),
                              **metrics(summary)})
        report.update(interrupted=interrupted, finished_task_count=len(results),
                      results=results, batches=summaries)
        write_json(root / 'manifest.json', report)

    save_report()
    print(f'Run: {root}\nTasks: {len(jobs)}; global concurrency: {worker_count}', flush=True)
    if not args.skip_build:
        runtime.build_environment_image(runtime.DEFAULT_IMAGE)
        runtime.build_proxy_image(runtime.DEFAULT_PROXY_IMAGE)
    networks = [(runtime.shared_resource_name(run_id, f'runtime_{i:02d}'), subnets[i])
                for i in range(worker_count)]
    proxy_dir = runtime.write_shared_proxy(root, runtime.DEFAULT_PROXY_IMAGE, networks)
    proxy_env = os.environ.copy()
    proxy_env['COMPOSE_PROJECT_NAME'] = runtime.shared_resource_name(run_id, 'proxy')
    slots = queue.Queue()
    for i in range(worker_count):
        slots.put(runtime.WorkerSlot(i, base_port + i))
    stop = threading.Event()
    active = runtime.ActiveProcesses()
    touched = {}
    touched_lock = threading.Lock()

    def scheduled(job):
        slot = slots.get()
        directory, attack_config, model_config = batches[(job.model, job.category)]
        project = runtime.compose_project_name(f'{run_id}_{job.model}_{job.category}', slot.number)
        overrides = {'ORCHESTRATOR_CONFIG': str(model_config),
                     'ATTACK_CONFIG_FILE': str(attack_config),
                     'ATTACK_CONFIG_BASE_DIR': str(job.source.parent),
                     'COMPOSE_PROJECT_NAME': project}
        try:
            if stop.is_set():
                raise futures.CancelledError()
            with touched_lock:
                touched[(directory, slot.number)] = project
            runtime.log('Task started', event='task_started', task=job.key,
                        worker=slot.number, port=slot.port)
            mode, script = runtime.collector_settings(job.goal)
            return runtime.run_task(
                job.selector, slot, directory, runtime.DEFAULT_IMAGE, runtime.DEFAULT_PROXY_IMAGE,
                False, networks[slot.number][0], stop, active, mode, job.link_host,
                script, args.timer, job.dataset_selector, environment_overrides=overrides)
        except futures.CancelledError:
            raise
        except Exception as error:
            return runtime.TaskResult(job.selector, slot.number, slot.port, 1, '', 0,
                                      f'{type(error).__name__}: {error}')
        finally:
            slots.put(slot)

    def record(job, future):
        if future.cancelled():
            return
        try:
            result = future.result()
        except futures.CancelledError:
            return
        results[job.key] = asdict(result)
        runtime.update_score_summary(batches[(job.model, job.category)][0])
        save_report()
        runtime.log('Task finished', event='task_finished', task=job.key,
                    returncode=result.returncode, completed=len(results), total=len(jobs))

    pool = None
    pending = {}
    old_sigint = signal.getsignal(signal.SIGINT)
    old_sigterm = signal.getsignal(signal.SIGTERM)

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        runtime.start_shared_proxy(proxy_dir, proxy_env)
        pool = futures.ThreadPoolExecutor(max_workers=worker_count)
        remaining = iter(jobs)

        def submit_next():
            job = next(remaining, None)
            if job is not None and not stop.is_set():
                pending[pool.submit(scheduled, job)] = job

        for _ in range(worker_count):
            submit_next()
        while pending:
            done, _ = futures.wait(pending, return_when=futures.FIRST_COMPLETED)
            for future in done:
                job = pending.pop(future)
                record(job, future)
                submit_next()
    except KeyboardInterrupt:
        interrupted = True
        stop.set()
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for future in pending:
            future.cancel()
        active.terminate_all()
    finally:
        stop.set()
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            if pool:
                # Also stop subprocesses if the launcher itself failed.
                if pending:
                    active.terminate_all()
                pool.shutdown(wait=True, cancel_futures=True)
                for future, job in pending.items():
                    record(job, future)
            if interrupted:
                for (directory, slot_number), project in touched.items():
                    env = os.environ.copy()
                    env['COMPOSE_PROJECT_NAME'] = project
                    runtime.cleanup_environment(directory / 'environments' / f'worker-{slot_number:02d}', env)
        finally:
            runtime.cleanup_shared_proxy(proxy_dir, proxy_env)
            save_report()
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)
    return 130 if interrupted else int(
        len(results) != len(jobs) or any(r['returncode'] != 0 for r in results.values())
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', nargs='+', default=DEFAULT_MODELS)
    parser.add_argument('--categories', nargs='+', help='Only run the specified categories (default: all)')
    parser.add_argument('--input-root', type=Path, default=BENCHMARK / 'all_category_test')
    parser.add_argument('--output-root', type=Path, default=BENCHMARK / 'output/all_category_test')
    parser.add_argument('--concurrency', type=int, default=64)
    parser.add_argument('--base-port', type=int)
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--timer', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.concurrency <= 64:
        parser.error('--concurrency must be between 1 and 64')
    if args.base_port is not None and not 1 <= args.base_port <= 65536 - args.concurrency:
        parser.error('--base-port leaves insufficient valid ports')
    try:
        jobs = plan_jobs(args.input_root.resolve(), args.models, args.categories)
        if args.dry_run:
            print(json.dumps({'task_count': len(jobs), 'global_concurrency': min(args.concurrency, len(jobs)),
                              'jobs': [job.key for job in jobs]}, indent=2))
            return 0
        return execute(args, jobs)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    sys.exit(main())
