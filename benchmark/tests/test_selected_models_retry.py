import json
import sys
from types import SimpleNamespace

import pytest

from benchmark.filter_task_difficulty import run_selected_models as selected


def test_retry_unstarted_task_backs_up_config_without_touching_completed(tmp_path, monkeypatch):
    root = tmp_path / 'run'
    config_dir = tmp_path / 'configs'
    config_dir.mkdir()
    model_dir = root / 'luna'
    model_dir.mkdir(parents=True)
    old_config = {'model': 'test-model', 'max_steps': 100}
    new_config = {'model': 'test-model', 'max_steps': 150}
    (model_dir / 'orchestrator_config.json').write_text(json.dumps(old_config))
    (config_dir / 'orchestrator_config_luna.json').write_text(json.dumps(new_config))
    tasks = [f'task_{i}' for i in range(15)]
    (root / 'selected_tasks.json').write_text(json.dumps([{'task_id': t} for t in tasks]))
    results = {}
    for task in tasks[:-1]:
        directory = model_dir / 'tasks' / task
        directory.mkdir(parents=True)
        (directory / 'grades.json').write_text('{"scoring_results":{"final_score":1}}')
        results[f'luna/{task}'] = {'returncode': 0}
    (root / 'manifest.json').write_text(json.dumps({
        'models': {'luna': {'model_id': 'test-model'}},
        'task_ids': tasks, 'results': results, 'interrupted': True,
    }))
    monkeypatch.setattr(selected, 'BENCHMARK', config_dir)

    def stop_before_execution(*args):
        raise RuntimeError('test stops before launching Docker')

    runtime = SimpleNamespace(
        choose_available_base_port=lambda n: 20000,
        validate_ports=lambda *args: None,
        allocate_runtime_subnets=lambda n: ['test-subnet'] * n,
        shared_resource_name=lambda *args: 'test-network',
        DEFAULT_PROXY_IMAGE='test',
        write_shared_proxy=stop_before_execution,
    )
    monkeypatch.setitem(sys.modules, 'main_concurrency', runtime)
    with pytest.raises(RuntimeError, match='test stops before launching Docker'):
        selected.main(['--retry-run', str(root), '--models', 'luna', '--skip-build'])
    backups = list((root / 'retry_backups').glob('*/luna/orchestrator_config.json'))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == old_config
    assert json.loads((model_dir / 'orchestrator_config.json').read_text()) == new_config
    manifest = json.loads((root / 'manifest.json').read_text())
    assert manifest['results'] == results
    assert manifest['retries'][-1]['jobs'] == ['luna/task_14']
    for task in tasks[:-1]:
        assert selected.completed(root, manifest, 'luna', task)


def test_repeated_retry_creates_distinct_proxies_and_merges_results(tmp_path, monkeypatch):
    from dataclasses import dataclass
    import main_concurrency as real_runtime

    root = tmp_path / 'run'
    model_dir = root / 'luna'
    model_dir.mkdir(parents=True)
    config = '{"model":"test-model","max_steps":150}'
    (tmp_path / 'orchestrator_config_luna.json').write_text(config)
    (model_dir / 'orchestrator_config.json').write_text(config)
    tasks = [f'task_{i}' for i in range(15)]
    (root / 'selected_tasks.json').write_text(json.dumps([{'task_id': t} for t in tasks]))
    results = {}
    for task in tasks[:-1]:
        directory = model_dir / 'tasks' / task
        directory.mkdir(parents=True)
        (directory / 'grades.json').write_text('{"scoring_results":{"final_score":1}}')
        results[f'luna/{task}'] = {'returncode': 0}
    (root / 'manifest.json').write_text(json.dumps({
        'models': {'luna': {'model_id': 'test-model'}}, 'task_ids': tasks,
        'results': results, 'interrupted': False,
    }))
    (root / 'proxy').mkdir()
    original_proxy = root / 'proxy/docker-compose.yml'
    original_proxy.write_text('original proxy')
    monkeypatch.setattr(selected, 'BENCHMARK', tmp_path)
    proxies, cleanups, calls = [], [], []

    @dataclass
    class Result:
        returncode: int

    def run_task(task, slot, output, *args, **kwargs):
        calls.append(task)
        directory = output / 'tasks' / task
        directory.mkdir(parents=True, exist_ok=True)
        if len(calls) == 1:
            (directory / 'partial').write_text('preserve me')
            return Result(1)
        (directory / 'grades.json').write_text('{"scoring_results":{"final_score":0.5}}')
        return Result(0)

    runtime = SimpleNamespace(
        choose_available_base_port=lambda n: 20000,
        validate_ports=lambda *args: None,
        allocate_runtime_subnets=lambda n: ['172.25.0.0/24'] * n,
        shared_resource_name=real_runtime.shared_resource_name,
        compose_project_name=real_runtime.compose_project_name,
        DEFAULT_IMAGE='test', DEFAULT_PROXY_IMAGE='test',
        write_shared_proxy=real_runtime.write_shared_proxy,
        start_shared_proxy=lambda p, e: proxies.append(p),
        cleanup_shared_proxy=lambda p, e: cleanups.append(p),
        WorkerSlot=real_runtime.WorkerSlot,
        ActiveProcesses=lambda: SimpleNamespace(terminate_all=lambda: None),
        run_task=run_task, update_score_summary=lambda *args: None,
    )
    monkeypatch.setitem(sys.modules, 'main_concurrency', runtime)
    args = ['--retry-run', str(root), '--models', 'luna', '--skip-build']
    assert selected.main(args) == 1
    assert selected.main(args) == 0
    assert selected.main(args) == 0  # Completed tasks are not rerun.
    assert calls == ['task_14', 'task_14']
    assert len(proxies) == 2 and proxies[0] != proxies[1]
    assert all(p.parent.parent == root / 'retry_runtime' for p in proxies)
    assert cleanups == proxies
    assert original_proxy.read_text() == 'original proxy'
    assert len(list((root / 'retry_backups').glob('*/luna/tasks/task_14/partial'))) == 1
    manifest = json.loads((root / 'manifest.json').read_text())
    assert all(selected.completed(root, manifest, 'luna', task) for task in tasks)
    assert all(manifest['results'][k] == v for k, v in results.items())
    assert json.loads((root / 'model_scores.json').read_text())[0]['scored_tasks'] == 15
