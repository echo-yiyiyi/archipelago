#!/usr/bin/env python3
"""Rerun the missing GLM evaluation and merge it into its original batch."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
import run_models_parallel as parallel

ROOT = Path(__file__).resolve().parent
RUN = ROOT / 'output/final_benchmark/parallel_20260914_232848_b91cc5e4'
MODEL = 'glm53'
CATEGORY = 'dynamic_prompt_injection'
TASK = 'task_fe573b8ce38d4a9f9642fbe7b8f11358_dynamic_prompt_injection_1_email_send_file'
KEY = f'{MODEL}/{CATEGORY}/{TASK}'


def read(path):
    return json.loads(path.read_text())


def complete(path):
    try:
        g = read(path / 'grades.json')
        score = g['scoring_results']['final_score']
        return (type(score) in (int, float) and math.isfinite(score)
                and all(type(g.get(k)) in (int, float) and g[k] in (0, 1)
                        for k in ('attack_success', 'prompt_exposure')))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--skip-build', action='store_true', help='Reuse images only after rebuilding them with the latest fixes')
    parser.add_argument('--_worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    manifest = read(RUN / 'manifest.json')
    original = RUN / MODEL / CATEGORY
    target = original / 'tasks' / TASK
    rows = read(original / 'attack_config.json')
    row = next(r for r in rows if r['harmful_task_id'] == TASK)
    source = Path(manifest['input_root']) / CATEGORY
    names = set(row.get('populate_files', []))
    names.update(row[k] for k in ('attack_file', 'watcher_file', 'watcher_config') if row.get(k))
    for name in names:
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError(f'Invalid artifact path: {name}')
        if not (source / name).is_file():
            raise FileNotFoundError(source / name)
    if KEY not in manifest['jobs']:
        raise ValueError('Task absent from original manifest')
    if args.dry_run:
        print(json.dumps(dict(task=KEY, already_complete=complete(target), concurrency=1,
                              max_steps=150, timer=manifest.get('timer', False),
                              merge_into=str(RUN)), indent=2))
        return 0
    if not args._worker:
        env = os.environ.copy()
        if not env.get('ZAI_API_KEY'):
            parser.error('Export a valid ZAI_API_KEY before rerunning GLM')
        # The saved model uses LiteLLM's openai/ provider for the ZAI endpoint.
        env['OPENAI_API_KEY'] = env['ZAI_API_KEY']
        for key in ('ATTACK_CONFIG_FILE', 'ATTACK_CONFIG_BASE_DIR', 'ATTACK_TASK_SELECTOR',
                    'EXAMPLE_DIR', 'ARCHIPELAGO_DIR', 'AGENTS_DIR', 'ENVIRONMENT_DIR',
                    'TASK_OUTPUT_ROOT', 'SCORE_SUMMARY_FILENAME', 'AGENT_TIMER_SECONDS',
                    'ORCHESTRATOR_CONFIG', 'USER_ALLOW_ADDITIONAL_INSTRUCTION'):
            env.pop(key, None)
        return parallel.run_with_storage(
            [sys.executable, str(Path(__file__).resolve()), '--_worker',
             *(['--skip-build'] if args.skip_build else [])],
            cwd=ROOT.parent, env=env, temp_root=ROOT / 'output/tmp/full_benchmark',
            output_root=RUN, min_free_gb=30, min_system_free_gb=10).returncode
    os.umask(0o077)
    with (RUN / '.snapshot-rerun.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if complete(target):
            print('Task already has complete grades. No rerun needed.')
            return 0
        attempt = RUN / 'snapshot_reruns' / (time.strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:6])
        inputs = attempt / 'inputs'
        inputs.mkdir(parents=True)
        for name in names:
            destination = inputs / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, destination)
        config = inputs / 'attack_config.json'
        parallel.write_json(config, [row])
        model_config = inputs / 'orchestrator_config.json'
        shutil.copy2(original / 'orchestrator_config.json', model_config)
        hosts = parallel.runtime.link_hosts_from_attack_config(config)
        job = parallel.Job(MODEL, CATEGORY, TASK, row['task_id'], config,
                           model_config, row['inject_goal'], hosts.get(TASK))
        os.environ['HF_MAX_STEPS'] = '150'
        options = argparse.Namespace(concurrency=1, base_port=None, output_root=attempt,
                    input_root=Path(manifest['input_root']), models=[MODEL],
                    timer=manifest.get('timer', False), skip_build=args.skip_build)
        code = parallel.execute(options, [job])
        rerun = next(attempt.glob('parallel_*'))
        result = rerun / MODEL / CATEGORY / 'tasks' / TASK
        if code or not complete(result):
            print(f'Rerun incomplete. Original results unchanged. Inspect {rerun}')
            return code or 1
        # Archive the failed run outside tasks/ so it is never counted twice.
        shutil.copy2(RUN / 'manifest.json', attempt / 'original_manifest.json')
        if target.exists():
            target.rename(attempt / 'original_failed_task')
        target.symlink_to(result.resolve(), target_is_directory=True)
        manifest = read(RUN / 'manifest.json')
        manifest['results'][KEY] = read(rerun / 'manifest.json')['results'][KEY]
        manifest.setdefault('result_sources', {})[KEY] = str(rerun)
        for batch in manifest['batches']:
            directory = RUN / batch['model'] / batch['category']
            summary = parallel.runtime.update_score_summary(directory)
            batch.update(parallel.metrics(summary))
            keys = [k for k in manifest['jobs']
                    if k.rsplit('/', 1)[0] == f"{batch['model']}/{batch['category']}"]
            done = [manifest['results'][k] for k in keys if k in manifest['results']]
            batch.update(finished_task_count=len(done),
                         failed_task_count=sum(r['returncode'] != 0 for r in done))
        parallel.write_json(RUN / 'manifest.json', manifest)
        print(f'Merged graded rerun into {target}\nUpdated original score summaries and manifest.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
