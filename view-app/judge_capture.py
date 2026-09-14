"""Offline reconstruction worker. Never calls a model or executes a task."""
from __future__ import annotations
import ast
import json
from pathlib import Path
import re
import socket
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def exposure_instructions():
    """Read the literal system prompt without importing the model SDK."""
    tree = ast.parse((REPO / 'benchmark/runner/exposure_judge.py').read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            fields = {k.value: v for k, v in zip(node.keys, node.values)
                      if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            role = fields.get('role')
            if isinstance(role, ast.Constant) and role.value == 'system':
                return ast.literal_eval(fields['content'])
    raise ValueError('System prompt unavailable')


def split_prompt(prompt):
    """Preserve the full prompt and also expose its data blocks for reading."""
    blocks = []
    pattern = re.compile(r'<([a-zA-Z_][\w-]*)>\s*([\s\S]*?)\s*</\1>')
    matches = list(pattern.finditer(prompt))
    for match in matches:
        value = match.group(2)
        try:
            value = json.loads(value)
        except ValueError:
            pass
        blocks.append({'name': match.group(1), 'value': value})
    if matches:
        return prompt[:matches[0].start()].strip(), blocks
    at = prompt.find('\n{')
    if at >= 0:
        try:
            value = json.loads(prompt[at:])
            return prompt[:at].strip(), [{'name': k, 'value': v} for k, v in value.items()]
        except ValueError:
            pass
    return prompt, blocks


def record_for(task):
    path = task.parent.parent / 'attack_config.json'
    data = json.loads(path.read_text())
    records = data if isinstance(data, list) else [data]
    matches = [r for r in records if r.get('harmful_task_id') == task.name]
    if not matches:
        matches = [r for r in records if r.get('task_id') == task.name]
    if len(matches) != 1:
        raise ValueError('Cannot unambiguously locate the saved task configuration')
    return matches[0], path.parent


def reconstruct(spec):
    task = Path(spec['grade_path']).parent
    grade = json.loads((task / 'grades.json').read_text())
    record, base = record_for(task)
    trajectory = json.loads((task / 'trajectory.json').read_text()) if (task / 'trajectory.json').exists() else {}
    from benchmark.runner import security_check
    captured = []
    if spec['kind'] == 'exposure':
        def judge(**kwargs):
            captured.append(kwargs)
            return {'exposure': 0, 'message_numbers': [], 'rationale': 'Offline reconstruction'}
        with patch('benchmark.runner.exposure_judge.judge_prompt_exposure', side_effect=judge):
            security_check.check_record_prompt_exposure(
                trajectory, record, base_dir=base,
                final_snapshot=task / 'final_snapshot.zip', force_llm=True)
        if not captured:
            raise ValueError('No reference text and tool results could be reconstructed')
        value = captured[0]
        return {'prompt': exposure_instructions(), 'input': {
            'reference_prompts': value['expected_prompts'], 'tool_results': value['tool_results']},
            'input_source': 'reconstructed', 'prompt_source': 'reconstructed',
            'note': 'Reconstructed using the current checker and saved run artifacts; the original request was not logged.'}
    raise ValueError('Historical security reconstruction is disabled')



if __name__ == '__main__':
    try:
        print(json.dumps(reconstruct(json.loads(sys.stdin.read())), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'error': f'{type(error).__name__}: {error}'}))
