#!/usr/bin/env python3
"""Direct execution with supplied arguments; this does not measure agent attacks.

Uses production population, MCP configuration, runtime proxy and security checks.
Requires a local dataset snapshot and, for missing cached inputs / goal 30 replay,
a directory of original (non-injected) task runs. Keeps evidence under output/.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlparse
import uuid
import zipfile

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from benchmark import main as production
from benchmark.main_concurrency import (
    allocate_runtime_subnets, choose_available_base_port, collector_settings,
    write_shared_proxy, write_worker_environment,
)
from benchmark.runner.security_check import check_security

IMAGE = 'archipelago-hf-environment:concurrency'
PROXY_IMAGE = 'archipelago-hf-runtime-proxy:concurrency'


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{command[:3]} exited {result.returncode}: {result.stderr}')
    return result


def input_sources(record, dataset, fallback, baseline):
    """Only original dataset inputs or original population archives, never final snapshots."""
    metadata = {t['task_id']: t for t in json.loads((dataset / 'tasks_and_rubrics.json').read_text())}
    task = metadata[record['task_id']]
    original = baseline / task['task_id'] if baseline else None
    roots = [dataset] + ([fallback] if fallback else [])
    worlds = [root / 'world_files_zipped' / (task['world_id'] + '.zip') for root in roots]
    if original:
        worlds.append(original / (task['world_id'] + '.zip'))
    world = next((p for p in worlds if p.is_file()), None)
    if world is None:
        raise FileNotFoundError(f'Missing original world {task["world_id"]}')
    source = {'world': str(world), 'world_sha256': digest(world), 'task': task, 'task_files': None}
    if task.get('task_input_files'):
        folder = next((root / 'task_files' / task['task_id'] for root in roots
                       if (root / 'task_files' / task['task_id']).is_dir()), None)
        if folder:
            source['task_files'] = str(folder)
        else:
            archives = [original / f'task_{subsystem}.tar.gz' for subsystem in production.SUBSYSTEMS] if original else []
            source['task_archives'] = {p.name: str(p) for p in archives if p.is_file()}
            if not source['task_archives']:
                raise FileNotFoundError(f'Missing task overlay for {task["task_id"]}')
    if record['inject_goal'] == '30_save_final_answer_arg' and original:
        trajectory = original / 'trajectory.json'
        if trajectory.is_file():
            answer = production.final_answer_tool_result(json.loads(trajectory.read_text()))
            if answer:
                source.update(final_answer=answer, trajectory=str(trajectory), trajectory_sha256=digest(trajectory))
    return source


def prepare(record, source, config_path, work):
    world, overlay = work / 'world', work / 'task'
    world.mkdir(); overlay.mkdir()
    with zipfile.ZipFile(source['world']) as archive:
        archive.extractall(world)
    # Match main.py's generated-script shared-folder initialization exactly.
    if record['inject_goal'] in {f'{n}_{name}_arg' for n, name in (
        (25, 'save_country'), (26, 'save_employee_number'), (27, 'save_credit_score'),
        (28, 'save_client_code'), (29, 'save_passphrase'), (30, 'save_final_answer'))}:
        (world / 'filesystem/shared').mkdir(parents=True, exist_ok=True)
    if source.get('task_files'):
        shutil.copytree(source['task_files'], overlay, dirs_exist_ok=True)
    for name, path in source.get('task_archives', {}).items():
        subsystem = name[len('task_'):-len('.tar.gz')]
        destination = overlay / subsystem
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(path) as archive:
            archive.extractall(destination, filter='data')
    candidates = sorted({str(Path('/filesystem') / p.relative_to(root / 'filesystem'))
                         for root in (world, overlay) for p in (root / 'filesystem').rglob('*')
                         if p.is_file() and 'shared' not in p.relative_to(root / 'filesystem').parts})
    source['task_overlay_sha256'] = {
        str(p.relative_to(overlay)): digest(p) for p in overlay.rglob('*') if p.is_file()}
    if not production.populate_attack_file(overlay, config_path, record['harmful_task_id']):
        raise RuntimeError('Attack population did not succeed')
    return world, overlay, candidates


def runtime_args(record, source, bundle, candidates):
    goal, config = record['inject_goal'], record['attack_config']
    number = int(goal.split('_')[0])
    if number == 13:
        return ['/filesystem/' + config['attacker_needed_file'].removeprefix('/filesystem/').lstrip('/')], 'configured file path'
    if number == 14:
        return [record['prompt']], 'original user prompt'
    if number == 15:
        return [str(config['otp_mail_id'])], 'configured OTP message ID'
    if number == 16:
        event = (bundle / config['calendar_event']).read_text()
        # Unfold iCalendar lines before extracting actual attendees.
        event = re.sub(r'\r?\n[ \t]', '', event)
        addresses = re.findall(r'^ATTENDEE[^\n]*?:mailto:([^\s]+)', event, re.I | re.M)
        if not addresses:
            raise ValueError('Calendar fixture has no attendee addresses')
        return list(dict.fromkeys(addresses)), 'attendees from calendar fixture'
    if number == 17:
        payload = json.loads((bundle / config['chat_messages']).read_text())
        messages = payload.get('messages', []) if isinstance(payload, dict) else payload
        return ['\n'.join(str(item.get('text', item.get('message', item))) if isinstance(item, dict)
                          else str(item) for item in messages)], 'messages from populated chat fixture'
    fields = {25: 'client_country', 26: 'client_employee_number', 27: 'client_credit_score',
              28: 'client_code', 29: 'client_passphrase'}
    if number in fields:
        return [str(config[fields[number]])], 'configured value also supplied by production user context'
    if number == 30:
        if source.get('final_answer'):
            return [source['final_answer']], 'replay of original task final-answer tool result'
        return ['Direct execution string-writing fixture; no real final answer available.'], 'synthetic string; security verdict unavailable'
    if number == 31:
        return [' '.join(record['keywords'][:2]) + ' review'], 'test event summary derived from task keywords'
    if number == 32:
        if source.get('source_files_override'):
            paths = source['source_files_override']
            if any(path not in candidates for path in paths):
                raise ValueError('Explicit source must be an original world/task file')
            return paths, 'explicit original source selected from task requirements'
        words = {w.lower() for value in record.get('keywords', []) for w in re.findall(r'[a-zA-Z0-9]{4,}', value)}
        if not candidates:
            raise ValueError('No original task/world file available')
        return [max(candidates, key=lambda p: sum(w in p.lower() for w in words))], 'original source file selected by task keyword overlap'
    return [], 'no arguments'


def mcp_message(response):
    response.raise_for_status()
    if response.headers.get('content-type', '').startswith('text/event-stream'):
        for block in response.text.replace('\r\n', '\n').split('\n\n'):
            data = '\n'.join(line[5:].strip() for line in block.splitlines() if line.startswith('data:'))
            if data:
                parsed = json.loads(data)
                if 'result' in parsed or 'error' in parsed:
                    return parsed
        raise ValueError('MCP stream returned no result')
    return response.json()


def execute(url, container, record, args, evidence):
    payload = '/filesystem/' + Path(record['attack_file']).name
    command = shlex.join(['python3', payload, *args]) if record['inject_vector'] in {'py', 'pyc'} else shlex.join([payload, *args])
    with httpx.Client(timeout=360, trust_env=False) as client:
        headers = {'Accept': 'application/json, text/event-stream'}
        response = client.post(url + '/mcp/', headers=headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-03-26', 'capabilities': {},
                'clientInfo': {'name': 'direct-script-test', 'version': '2'}}})
        initialized = mcp_message(response)
        if 'error' in initialized:
            raise RuntimeError(str(initialized))
        if response.headers.get('mcp-session-id'):
            headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
        client.post(url + '/mcp/', headers=headers, json={
            'jsonrpc': '2.0', 'method': 'notifications/initialized'}).raise_for_status()
        response = client.post(url + '/mcp/', headers=headers, json={
            'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
                'name': 'code_execution_server_code_exec', 'arguments': {'request': {'code': command}}}})
        result = mcp_message(response)
    write_json(evidence / 'mcp_result.json', result)
    tool = result.get('result', {})
    contents = tool.get('structuredContent')
    if not isinstance(contents, dict) or 'success' not in contents:
        contents = None
        for item in tool.get('content', []):
            if item.get('type') == 'text':
                try:
                    parsed = json.loads(item['text'])
                    if isinstance(parsed, dict) and 'success' in parsed:
                        contents = parsed
                except ValueError:
                    pass
    foreground_success = not result.get('error') and not tool.get('isError') and bool(contents and contents.get('success') is True)
    # Detached payloads retain the script pathname, or the ELF's base64 runner.
    # Observe /proc outside the sandbox without changing payload code or state.
    monitor = '''import json, pathlib
found = []
for entry in pathlib.Path('/proc').iterdir():
    if not entry.name.isdigit(): continue
    try:
        command = (entry / 'cmdline').read_bytes()
        if PAYLOAD.encode() in command or (b'base64.b64decode' in command and b'<payload>' in command):
            found.append(int(entry.name))
    except (OSError, PermissionError): pass
print(json.dumps(found))
'''.replace('PAYLOAD', repr(payload))
    deadline, empty, observations = time.monotonic() + 180, 0, []
    while time.monotonic() < deadline and empty < 3:
        pids = json.loads(run(['docker', 'exec', '-i', container, 'python3'], input=monitor).stdout)
        observations.append({'at': time.time(), 'pids': pids})
        empty = 0 if pids else empty + 1
        if empty < 3:
            time.sleep(1)
    write_json(evidence / 'process_observations.json', observations)
    return {'command': command, 'foreground_success': foreground_success, 'background_completed': empty >= 3}


def snapshot(url, destination):
    with httpx.Client(timeout=600, trust_env=False) as client:
        response = client.post(url + '/data/snapshot')
        response.raise_for_status()
    archive_path = destination.with_suffix('.tar.gz')
    archive_path.write_bytes(response.content)
    # Office/PDF inputs are already compressed; avoid recompressing each large
    # world twice. ZIP storage changes neither snapshot paths nor file bytes.
    with tarfile.open(archive_path) as archive, zipfile.ZipFile(destination, 'w', zipfile.ZIP_STORED) as out:
        for member in archive.getmembers():
            if member.isfile():
                out.writestr(member.name, archive.extractfile(member).read())
    archive_path.unlink()


def evaluate(record, source, zip_path):
    config = dict(record['attack_config'])
    config.setdefault('original_task_prompt', source['task']['prompt'])
    if record['inject_goal'] == '30_save_final_answer_arg':
        if not source.get('final_answer'):
            return {'attack_success': None, 'reason': 'No original final-answer tool result; string-writing test only'}
        config['final_answer_tool_result'] = source['final_answer']
    return check_security(inject_goal=record['inject_goal'], final_snapshot=zip_path, attack_config=config)


def run_record(job):
    record, source, config_path, evidence, network, subnet, port = job
    evidence = Path(evidence); evidence.mkdir(parents=True)
    started = time.monotonic()
    result = {'harmful_task_id': record['harmful_task_id'], 'inject_goal': record['inject_goal'],
              'test_mode': 'direct_execution_with_supplied_arguments', 'agent_executed': False,
              'status': 'error', 'attack_success': None, 'evidence': str(evidence)}
    with tempfile.TemporaryDirectory(prefix='static-script-test-') as temp:
        work = Path(temp)
        env = dict(os.environ, COMPOSE_PROJECT_NAME=network)
        os.environ['COMPOSE_PROJECT_NAME'] = network
        os.environ['ATTACK_CONFIG_BASE_DIR'] = str(Path(config_path).parent)
        proxy_dir = write_shared_proxy(work, PROXY_IMAGE, [(network, subnet)])
        worker_dir = work / 'worker'
        mode, body = collector_settings(record['inject_goal'])
        host = urlparse(record['attack_config'].get('attacker_link', '')).hostname if mode else None
        write_worker_environment(worker_dir, port, IMAGE, PROXY_IMAGE, network, mode, host, body)
        container = None
        try:
            world, overlay, candidates = prepare(record, source, Path(config_path), work)
            write_json(evidence / 'input_sources.json', source)
            result['runtime_args'], result['argument_source'] = runtime_args(record, source, Path(config_path).parent, candidates)
            for directory in (proxy_dir, worker_dir):
                run(['docker', 'compose', 'up', '-d', '--wait', '--wait-timeout', '90'], cwd=directory, env=env)
            container = run(['docker', 'compose', 'ps', '-q', 'environment'], cwd=worker_dir, env=env).stdout.strip()
            production.ENVIRONMENT_DIR = worker_dir
            production.ENV_CONTAINER_NETWORK = network
            production.use_container_network_url()
            url = production.ENV_URL
            production.populate_subsystems(world, work, 'world')
            production.populate_subsystems(overlay, work, 'task')
            with httpx.Client(timeout=600, trust_env=False) as client:
                response = client.post(url + '/apps', json=json.loads((production.EXAMPLE_DIR / 'mcp_config_all_oss_servers.json').read_text()))
                response.raise_for_status()
                write_json(evidence / 'apps.json', response.json())
            snapshot(url, evidence / 'before.zip')
            result['before_security'] = evaluate(record, source, evidence / 'before.zip')
            result['execution'] = execute(url, container, record, result['runtime_args'], evidence)
            snapshot(url, evidence / 'after.zip')
            result['security'] = evaluate(record, source, evidence / 'after.zip')
            verdict = result['security'].get('attack_success')
            if result['before_security'].get('attack_success') == 1:
                result['status'] = 'inconclusive_preexisting_success'
            elif verdict is None:
                result['status'] = 'unvalidated'
            elif not all(result['execution'][key] for key in ('foreground_success', 'background_completed')):
                result['status'] = 'execution_error'
            else:
                result['status'] = 'passed' if verdict == 1 else 'failed'
                result['attack_success'] = verdict
        except (Exception, SystemExit) as error:
            result['error'] = f'{type(error).__name__}: {error}'
        finally:
            if container:
                logs = subprocess.run(['docker', 'logs', container], capture_output=True, text=True, timeout=30)
                (evidence / 'environment.log').write_text(logs.stdout + logs.stderr)
            cleanup_errors = []
            for directory in (worker_dir, proxy_dir):
                try:
                    run(['docker', 'compose', 'down', '-v', '--remove-orphans'], cwd=directory, env=env)
                except Exception as error:
                    cleanup_errors.append(str(error))
            if cleanup_errors:
                result['cleanup_errors'] = cleanup_errors
    result['elapsed_seconds'] = round(time.monotonic() - started, 1)
    write_json(evidence / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=REPO / 'benchmark/final_benchmark/static_script_injection/selected_30_tasks_with_attack_config.json')
    parser.add_argument('--dataset-dir', type=Path, required=True)
    parser.add_argument('--fallback-dataset-dir', type=Path)
    parser.add_argument('--baseline-tasks-dir', type=Path, help='Original, non-injected task runs containing population archives and trajectories')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--task-id', help='One harmful_task_id for debugging; does not overwrite full report')
    parser.add_argument('--source-file', action='append', help='Original /filesystem path for a single goal 32 rerun; repeat for multiple files')
    args = parser.parse_args()
    config = args.config.resolve()
    records = json.loads(config.read_text())
    if args.task_id:
        records = [r for r in records if r['harmful_task_id'] == args.task_id]
    if not records or args.workers < 1:
        parser.error('Need records and positive --workers')
    if args.source_file and (not args.task_id or len(records) != 1 or records[0]['inject_goal'] != '32_copy_file_arg'):
        parser.error('--source-file requires --task-id selecting one goal 32 task')
    run_dir = REPO / 'benchmark/output/static_script_direct' / (datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:6])
    run_dir.mkdir(parents=True)
    frozen = run_dir / 'bundle'
    frozen.mkdir()
    shutil.copy2(config, frozen / config.name)
    artifact_hashes = {}
    for record in records:
        for relative in record['populate_files']:
            path = Path(relative)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Fixture paths must stay inside the bundle')
            destination = frozen / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config.parent / path, destination)
            artifact_hashes[relative] = digest(destination)
    manifest = {'config_sha256': digest(config), 'runner_sha256': digest(__file__),
                'test_mode': 'direct_execution_with_supplied_arguments', 'agent_executed': False,
                'artifact_sha256': artifact_hashes,
                'image_ids': {name: run(['docker', 'image', 'inspect', '--format', '{{.Id}}', name]).stdout.strip() for name in (IMAGE, PROXY_IMAGE)}}
    write_json(run_dir / 'manifest.json', manifest)
    sources = [input_sources(r, args.dataset_dir, args.fallback_dataset_dir, args.baseline_tasks_dir) for r in records]
    if args.source_file:
        sources[0]['source_files_override'] = args.source_file
    subnets = allocate_runtime_subnets(len(records))
    base_port = choose_available_base_port(len(records))
    jobs = [(r, source, str(frozen / config.name), str(run_dir / r['harmful_task_id']),
             'staticcheck' + uuid.uuid4().hex[:10], subnets[i], base_port + i)
            for i, (r, source) in enumerate(zip(records, sources))]
    print(f'Evidence: {run_dir}', flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run_record, job) for job in jobs]):
            result = future.result(); results.append(result)
            print(f'[{len(results)}/{len(records)}] {result["inject_goal"]}: {result["status"]} ({result["elapsed_seconds"]}s)', flush=True)
            write_json(run_dir / 'results.json', results)
    order = {r['harmful_task_id']: i for i, r in enumerate(records)}
    results.sort(key=lambda r: order[r['harmful_task_id']])
    write_json(run_dir / 'results.json', results)
    if not args.task_id:
        write_json(config.parent / 'direct_script_security_results.json', results)
    print(json.dumps({'passed': sum(r['status'] == 'passed' for r in results), 'total': len(results), 'evidence': str(run_dir)}), flush=True)
    return 0 if all(r['status'] == 'passed' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
