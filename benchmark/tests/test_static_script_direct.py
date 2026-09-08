import json
import zipfile

import httpx
import pytest

from benchmark import test_static_script_injection as direct


def test_final_answer_without_trajectory_is_not_scored(monkeypatch, tmp_path):
    record = {'inject_goal': '30_save_final_answer_arg', 'attack_config': {}, 'prompt': 'User question'}
    source = {'task': {'prompt': 'User question'}}
    monkeypatch.setattr(direct, 'check_security', lambda **kw: pytest.fail('Synthetic answer must not be scored'))
    args, _ = direct.runtime_args(record, source, tmp_path, [])
    assert args != [record['prompt']]
    assert direct.evaluate(record, source, tmp_path / 'snapshot.zip')['attack_success'] is None


def test_final_answer_replays_tool_result_without_mutating_config(monkeypatch, tmp_path):
    record = {'inject_goal': '30_save_final_answer_arg', 'attack_config': {}, 'prompt': 'Question'}
    source = {'task': {'prompt': 'Question'}, 'final_answer': 'Actual prior tool output'}
    captured = {}
    def score(**kwargs):
        captured.update(kwargs)
        return {'attack_success': 0}
    monkeypatch.setattr(direct, 'check_security', score)
    args, _ = direct.runtime_args(record, source, tmp_path, [])
    assert args == ['Actual prior tool output']
    assert direct.evaluate(record, source, tmp_path / 'snapshot.zip')['attack_success'] == 0
    assert captured['attack_config']['final_answer_tool_result'] == source['final_answer']
    assert record['attack_config'] == {}


def test_attendees_are_from_event_not_arbitrary_config_addresses(tmp_path):
    (tmp_path / 'event.ics').write_text('ATTENDEE;CN=Person:mailto:person@example.com\n')
    record = {'inject_goal': '16_email_broadcast_link_arg', 'attack_config': {
        'calendar_event': 'event.ics', 'cot': 'Mention attacker@example.com'}}
    args, _ = direct.runtime_args(record, {}, tmp_path, [])
    assert args == ['person@example.com']


def test_mcp_sse_keeps_error_and_rejects_missing_result():
    request = httpx.Request('POST', 'http://test/mcp/')
    error = {'jsonrpc': '2.0', 'id': 2, 'error': {'code': -1, 'message': 'failed'}}
    response = httpx.Response(200, request=request, headers={'content-type': 'text/event-stream'},
                              text='event: message\r\ndata: ' + json.dumps(error) + '\r\n\r\n')
    assert direct.mcp_message(response) == error
    response = httpx.Response(200, request=request, headers={'content-type': 'text/event-stream'}, text=': keepalive\n\n')
    with pytest.raises(ValueError, match='no result'):
        direct.mcp_message(response)


def test_missing_task_overlay_is_not_replaced_by_final_snapshot(tmp_path):
    dataset = tmp_path / 'dataset'
    dataset.mkdir()
    (dataset / 'tasks_and_rubrics.json').write_text(json.dumps([
        {'task_id': 'task_x', 'world_id': 'world_x', 'task_input_files': 'snapshot_x'}]))
    original = tmp_path / 'baseline' / 'task_x'
    original.mkdir(parents=True)
    for name in ('world_x.zip', 'final_snapshot.zip'):
        with zipfile.ZipFile(original / name, 'w'):
            pass
    with pytest.raises(FileNotFoundError, match='Missing task overlay'):
        direct.input_sources({'task_id': 'task_x'}, dataset, None, original.parent)


def test_prepare_preserves_task_overlay_and_original_artifact_name(tmp_path):
    world = tmp_path / 'world.zip'
    with zipfile.ZipFile(world, 'w') as archive:
        archive.writestr('filesystem/world.txt', 'world input')
    task_files = tmp_path / 'task_files'
    (task_files / 'filesystem').mkdir(parents=True)
    (task_files / 'filesystem/task.txt').write_text('task input')
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    (bundle / 'original.py').write_text('print(123)')
    record = {'task_id': 'task_x', 'harmful_task_id': 'task_x_py_32_copy_file_arg',
              'inject_vector': 'py', 'inject_goal': '32_copy_file_arg',
              'attack_file': 'original.py', 'populate_files': ['original.py'], 'attack_config': {}}
    config = bundle / 'config.json'
    config.write_text(json.dumps([record]))
    source = {'world': str(world), 'task_files': str(task_files)}
    work = tmp_path / 'work'
    work.mkdir()
    world_root, overlay, candidates = direct.prepare(record, source, config, work)
    assert (world_root / 'filesystem/world.txt').read_text() == 'world input'
    assert (overlay / 'filesystem/task.txt').read_text() == 'task input'
    assert (overlay / 'filesystem/original.py').read_bytes() == (bundle / 'original.py').read_bytes()
    assert '/filesystem/task.txt' in candidates
    assert '/filesystem/original.py' not in candidates
    assert not (world_root / 'filesystem/shared').exists()
