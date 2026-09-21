import argparse
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import Mock

from benchmark import run_models_parallel as parallel


def test_retry_only_process_failures_preserves_frozen_config(tmp_path):
    assets = tmp_path / 'inputs' / 'with'
    assets.mkdir(parents=True)
    (assets / 'payload.txt').write_text('payload')
    run = tmp_path / 'old'
    directory = run / 'gemini36' / 'with' / 'repeat_02'
    directory.mkdir(parents=True)
    rows = [dict(harmful_task_id=s, task_id=s, inject_goal='18_copy_file',
                 populate_files=['payload.txt']) for s in ['failed', 'passed', 'pending']]
    (directory / 'attack_config.json').write_text(json.dumps(rows))
    (directory / 'orchestrator_config.json').write_text('{"model":"saved-model"}')
    keys = [f'gemini36/with/repeat_02/{s}' for s in ['failed', 'passed', 'pending']]
    (run / 'manifest.json').write_text(json.dumps(dict(input_root=str(tmp_path / 'inputs'),
        jobs=keys, results={keys[0]: {'returncode': 1}, keys[1]: {'returncode': 0}})))
    _, _, jobs = parallel.plan_failed_batch(str(run))
    assert [j.key for j in jobs] == keys[:1]
    assert jobs[0].asset_base == assets
    assert jobs[0].model_config == directory / 'orchestrator_config.json'
    _, _, resumed = parallel.plan_failed_batch(str(run), include_unstarted=True)
    assert [j.key for j in resumed] == [keys[0], keys[2]]


def test_merge_retry_backs_up_failure_and_preserves_other_results(tmp_path):
    old, retry = tmp_path / 'old', tmp_path / 'retry'
    old.mkdir()
    job = parallel.Job('model', 'with', 'task', 'dataset', tmp_path, tmp_path, 'goal', None)
    relative = Path('model/with/tasks/task')
    for root, content in [(old, 'old'), (retry, 'new')]:
        (root / relative).mkdir(parents=True)
        (root / relative / 'artifact').write_text(content)
    other = {'returncode': 0}
    (old / 'manifest.json').write_text(json.dumps(dict(jobs=[job.key, 'other'],
        results={job.key: {'returncode': 1}, 'other': other})))
    parallel.merge_retry_result(old, retry, job, {'returncode': 0})
    assert (old / relative / 'artifact').read_text() == 'new'
    assert (old / 'retry_backups/retry' / relative / 'artifact').read_text() == 'old'
    result = json.loads((old / 'manifest.json').read_text())
    assert result['failed_task_count'] == 0
    assert result['results']['other'] == other


def test_plan_interleaves_all_models_and_categories():
    jobs = parallel.plan_jobs(parallel.BENCHMARK / 'all_category_test', parallel.DEFAULT_MODELS)
    assert len(jobs) == len({job.key for job in jobs}) == 120
    assert {job.model for job in jobs[:5]} == set(parallel.DEFAULT_MODELS)
    assert len({job.category for job in jobs[:40]}) == 8
    assert all(sum(j.model == model for j in jobs) == 24 for model in parallel.DEFAULT_MODELS)


def test_global_64_slot_pool_isolated_and_continues_after_failure(tmp_path, monkeypatch):
    runtime = parallel.runtime
    monkeypatch.setattr(runtime, '_run_logger', None)
    monkeypatch.setattr(runtime, 'choose_available_base_port', lambda count: 18080)
    monkeypatch.setattr(runtime, 'validate_ports', lambda *args: None)
    monkeypatch.setattr(runtime, 'allocate_runtime_subnets', lambda count: [f'10.200.{i}.0/28' for i in range(count)])
    build_environment = Mock()
    build_proxy = Mock()
    cleanup = Mock()
    monkeypatch.setattr(runtime, 'build_environment_image', build_environment)
    monkeypatch.setattr(runtime, 'build_proxy_image', build_proxy)
    monkeypatch.setattr(runtime, 'write_shared_proxy', lambda root, *args: root / 'proxy')
    monkeypatch.setattr(runtime, 'start_shared_proxy', lambda *args: None)
    monkeypatch.setattr(runtime, 'cleanup_shared_proxy', cleanup)
    barrier = threading.Barrier(64)
    lock = threading.Lock()
    running_ports = set()
    seen = []
    peak = 0
    original_environment = dict(os.environ)

    def fake_run(selector, slot, directory, *args, environment_overrides, **kwargs):
        nonlocal peak
        # Nested category paths require reading the frozen model configuration.
        config_path = Path(environment_overrides['ORCHESTRATOR_CONFIG'])
        config = json.loads(config_path.read_text())
        expected = json.loads(next((parallel.BENCHMARK).glob(
            f'orchestrator_config_{directory.relative_to(tmp_path).parts[1]}.json')).read_text())
        assert config == expected
        rows = json.loads(Path(environment_overrides['ATTACK_CONFIG_FILE']).read_text())
        assert selector in {row['harmful_task_id'] for row in rows}
        source_dir = Path(environment_overrides['ATTACK_CONFIG_BASE_DIR'])
        row = next(row for row in rows if row['harmful_task_id'] == selector)
        assert (source_dir / row['attack_file']).is_file()
        with lock:
            assert slot.port not in running_ports
            running_ports.add(slot.port)
            peak = max(peak, len(running_ports))
            seen.append((str(directory), selector, environment_overrides['COMPOSE_PROJECT_NAME']))
            number = len(seen)
        if number <= 64:
            barrier.wait(timeout=20)
        time.sleep(0.002)
        with lock:
            running_ports.remove(slot.port)
        return runtime.TaskResult(selector, slot.number, slot.port, int(number == 1), '', 0)

    monkeypatch.setattr(runtime, 'run_task', fake_run)
    args = argparse.Namespace(concurrency=64, base_port=None, output_root=tmp_path,
                              input_root=parallel.BENCHMARK / 'all_category_test',
                              models=parallel.DEFAULT_MODELS, timer=False, skip_build=False)
    jobs = parallel.plan_jobs(args.input_root, args.models)
    assert parallel.execute(args, jobs) == 1  # One failure must not stop the queue.
    assert peak == 64
    assert len(seen) == len({(directory, selector) for directory, selector, _ in seen}) == 120
    assert len({project for _, _, project in seen[:64]}) == 64
    assert dict(os.environ) == original_environment
    report = json.loads(next(tmp_path.glob('*/manifest.json')).read_text())
    assert report['finished_task_count'] == 120
    assert len(report['batches']) == 40
    assert sum(b['failed_task_count'] for b in report['batches']) == 1
    build_environment.assert_called_once()
    build_proxy.assert_called_once()
    cleanup.assert_called_once()


def test_run_task_passes_private_environment_and_unique_process_key(tmp_path, monkeypatch):
    runtime = parallel.runtime
    monkeypatch.setattr(runtime, 'write_worker_environment', lambda *args: None)
    monkeypatch.setattr(runtime, 'cleanup_environment', lambda *args: None)
    process = Mock()
    process.wait.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr(runtime.subprocess, 'Popen', popen)
    active = Mock()
    original_environment = dict(os.environ)
    for model in ('one', 'two'):
        directory = tmp_path / model
        (directory / 'logs').mkdir(parents=True)
        result = runtime.run_task(
            'same_selector', runtime.WorkerSlot(0, 18080), directory, 'image', 'proxy',
            False, 'network', threading.Event(), active, None, None,
            dataset_selector='dataset_id',
            environment_overrides={'ORCHESTRATOR_CONFIG': model, 'ATTACK_CONFIG_FILE': model + '.json',
                                   'COMPOSE_PROJECT_NAME': model + '_project'},
        )
        assert result.returncode == 0
        env = popen.call_args.kwargs['env']
        assert env['ORCHESTRATOR_CONFIG'] == model
        assert env['ATTACK_CONFIG_FILE'] == model + '.json'
        assert env['COMPOSE_PROJECT_NAME'] == model + '_project'
        assert env['ATTACK_TASK_SELECTOR'] == 'same_selector'
        assert popen.call_args.args[0][-1] == 'dataset_id'
    assert active.add.call_args_list[0].args[0] != active.add.call_args_list[1].args[0]
    assert dict(os.environ) == original_environment


def test_interrupt_cancels_queue_and_cleans_shared_proxy(tmp_path, monkeypatch):
    runtime = parallel.runtime
    monkeypatch.setattr(runtime, '_run_logger', None)
    monkeypatch.setattr(runtime, 'validate_ports', lambda *args: None)
    monkeypatch.setattr(runtime, 'allocate_runtime_subnets', lambda count: ['10.200.0.0/28'] * count)
    monkeypatch.setattr(runtime, 'write_shared_proxy', lambda root, *args: root / 'proxy')
    monkeypatch.setattr(runtime, 'start_shared_proxy', lambda *args: None)
    cleanup = Mock()
    monkeypatch.setattr(runtime, 'cleanup_shared_proxy', cleanup)
    monkeypatch.setattr(runtime, 'cleanup_environment', lambda *args: None)
    started = threading.Event()

    def fake_run(selector, slot, directory, image, proxy, keep, network, stop, *args, **kwargs):
        started.set()
        assert stop.wait(timeout=10)
        return runtime.TaskResult(selector, slot.number, slot.port, 130, '', 0)

    def interrupt(*args, **kwargs):
        assert started.wait(timeout=10)
        raise KeyboardInterrupt

    monkeypatch.setattr(runtime, 'run_task', fake_run)
    monkeypatch.setattr(parallel.futures, 'wait', interrupt)
    args = argparse.Namespace(concurrency=2, base_port=18080, output_root=tmp_path,
                              input_root=parallel.BENCHMARK / 'all_category_test',
                              models=parallel.DEFAULT_MODELS, timer=False, skip_build=True)
    jobs = parallel.plan_jobs(args.input_root, args.models)
    assert parallel.execute(args, jobs) == 130
    report = json.loads(next(tmp_path.glob('*/manifest.json')).read_text())
    assert report['interrupted'] is True
    assert report['finished_task_count'] <= 2
    cleanup.assert_called_once()


def test_full_benchmark_cli_defaults_and_multiple_models(capsys):
    assert parallel.main(['--models', 'deepseekv4', '--dry-run']) == 0
    single = json.loads(capsys.readouterr().out)
    assert single['task_count'] == 180
    assert single['global_concurrency'] == 64
    assert single['input_root'] == str(parallel.BENCHMARK / 'final_benchmark')
    assert len({key.rsplit('/', 1)[0] for key in single['jobs'][:64]}) == 8
    assert parallel.main(['--models', 'deepseekv4', 'gemini36', '--dry-run']) == 0
    multiple = json.loads(capsys.readouterr().out)
    assert multiple['task_count'] == 360
    assert multiple['global_concurrency'] == 64
    assert {key.split('/')[0] for key in multiple['jobs'][:64]} == {'deepseekv4', 'gemini36'}


def test_cli_uses_storage_guard_and_preserves_credentials(monkeypatch):
    from types import SimpleNamespace
    guard = Mock(return_value=SimpleNamespace(returncode=130))
    monkeypatch.setattr(parallel, 'run_with_storage', guard)
    execute = Mock()
    monkeypatch.setattr(parallel, 'execute', execute)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-credential')
    monkeypatch.setenv('ATTACK_TASK_SELECTOR', 'stale-task')
    assert parallel.main(['--models', 'deepseekv4']) == 130
    execute.assert_not_called()
    command = guard.call_args.args[0]
    assert command[-1] == '--_storage-worker'
    assert command.count('--_storage-worker') == 1
    assert guard.call_args.kwargs['env']['DEEPSEEK_API_KEY'] == 'test-credential'
    assert 'ATTACK_TASK_SELECTOR' not in guard.call_args.kwargs['env']
    assert guard.call_args.kwargs['min_free_gb'] == 30
    assert guard.call_args.kwargs['min_system_free_gb'] == 10


def test_storage_child_enters_existing_pool_without_recursion(monkeypatch):
    execute = Mock(return_value=0)
    guard = Mock()
    monkeypatch.setattr(parallel, 'execute', execute)
    monkeypatch.setattr(parallel, 'run_with_storage', guard)
    assert parallel.main(['--models', 'deepseekv4', '--_storage-worker']) == 0
    guard.assert_not_called()
    assert len(execute.call_args.args[1]) == 180


def test_merge_unstarted_reuses_snapshot_and_completes_batch(tmp_path):
    old, retry = tmp_path / 'old', tmp_path / 'retry'
    old.mkdir()
    job = parallel.Job('model', 'category', 'task', 'dataset', tmp_path, tmp_path, 'goal', None)
    relative = Path('model/category/tasks/task')
    (retry / relative).mkdir(parents=True)
    (retry / relative / 'final_snapshot.zip').write_bytes(b'snapshot')
    (old / 'manifest.json').write_text(json.dumps(dict(jobs=[job.key], results={}, interrupted=True)))
    parallel.merge_retry_result(old, retry, job, {'returncode': 0})
    assert (old / relative).is_symlink()
    assert (old / relative / 'final_snapshot.zip').read_bytes() == b'snapshot'
    result = json.loads((old / 'manifest.json').read_text())
    assert result['finished_task_count'] == 1
    assert result['interrupted'] is False
    import pytest
    with pytest.raises(ValueError):
        parallel.merge_retry_result(old, retry, job, {'returncode': 0})
