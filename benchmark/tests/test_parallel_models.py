import argparse
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import Mock

from benchmark import run_models_parallel as parallel


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
