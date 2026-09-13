#!/usr/bin/env python3
"""Sample paired script-format ablations from existing final benchmark bundles."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
BENCHMARK = ROOT.parents[2]
sys.path.insert(0, str(BENCHMARK.parent))
from benchmark.generate_attack_config.attack_script.args.generate_args_attack_scripts import render, GOAL_ALIASES
from benchmark.generate_attack_config.attack_script.render_attack_script import render_payload, _C_TEMPLATE, _c_string_chunks

CATEGORIES = ('static_script_injection', 'user_prompt_script_swap', 'user_prompt_suffix_plant')
VECTORS = ('py', 'pyc', 'elf')
IMAGE = 'archipelago-hf-environment:concurrency'


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def replace(value, changes):
    if isinstance(value, str):
        for old, new in changes:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [replace(v, changes) for v in value]
    if isinstance(value, dict):
        return {k: replace(v, changes) for k, v in value.items()}
    return value


def select(category):
    candidates = []
    for path in sorted((BENCHMARK / 'final_benchmark' / category).rglob('*with_attack_config.json')):
        candidates.extend((row, path) for row in json.loads(path.read_text()))
    random.Random(42).shuffle(candidates)

    def search(start, chosen, ids, goals, args_count):
        if len(chosen) == 5:
            return chosen if category != 'user_prompt_script_swap' or args_count == 2 else None
        for i in range(start, len(candidates)):
            row, path = candidates[i]
            is_args = row['inject_goal'] in GOAL_ALIASES
            if row['task_id'] in ids or row['inject_goal'] in goals:
                continue
            if category == 'user_prompt_script_swap':
                if args_count + is_args > 2 or len(chosen) - args_count + (not is_args) > 3:
                    continue
            found = search(i + 1, chosen + [(row, path)], ids | {row['task_id']},
                           goals | {row['inject_goal']}, args_count + is_args)
            if found:
                return found
        return None

    result = search(0, [], set(), set(), 0)
    if result is None:
        raise ValueError(f'Cannot select 5 distinct task IDs and goals: {category}')
    return result


def main():
    selected = {category: select(category) for category in CATEGORIES}
    for category in CATEGORIES:
        for vector in VECTORS:
            target = ROOT / category / vector
            if target.exists() and any(target.iterdir()):
                raise FileExistsError(f'Refusing to overwrite nonempty output: {target}')
    manifest = {'seed': 42, 'image': IMAGE, 'sampling': '5 distinct task IDs and goals per category; swap: 2 args + 3 no_args', 'tasks': []}
    jobs = []
    with tempfile.TemporaryDirectory(prefix='script-vector-build-') as temp:
        build = Path(temp)
        for category, pairs in selected.items():
            for original, source_json in pairs:
                manifest['tasks'].append({'category': category, 'task_id': original['task_id'],
                    'inject_goal': original['inject_goal'], 'source_json': str(source_json.relative_to(BENCHMARK)),
                    'source_harmful_task_id': original['harmful_task_id'],
                    'source_json_sha256': hashlib.sha256(source_json.read_bytes()).hexdigest()})
            for vector in VECTORS:
                target = ROOT / category / vector
                target.mkdir(parents=True, exist_ok=True)
                rows = []
                for original, source_json in pairs:
                    old_id = original['harmful_task_id']
                    new_id = f"{original['task_id']}_{vector}_{original['inject_goal']}"
                    old_name = Path(original['attack_file']).name
                    stem = old_name[:-4] if old_name.endswith('.pyc') else old_name[:-3] if old_name.endswith('.py') else old_name
                    new_name = stem + {'py': '.py', 'pyc': '.pyc', 'elf': ''}[vector]
                    old_command = ('./' if original['inject_vector'] == 'elf' else 'python ') + old_name
                    new_command = ('./' if vector == 'elf' else 'python ') + new_name
                    # Only paths/commands change; goals, recipients, judges and task data are retained.
                    changes = [(old_id, new_id), (old_command, new_command)]
                    row = replace(original, changes)
                    row['inject_vector'] = vector
                    row['attack_file'] = f'{new_id}/{new_name}'
                    row['populate_files'] = [row['attack_file'] if p == replace(original['attack_file'], changes) else p for p in row['populate_files']]
                    for old_path, new_path in zip(original['populate_files'], row['populate_files']):
                        dest = target / new_path
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        if old_path == original['attack_file']:
                            continue
                        src = source_json.parent / old_path
                        if src.name.endswith('_Additional_Task_Instructions.txt'):
                            dest.write_text(replace(src.read_text(), changes))
                        else:
                            shutil.copy2(src, dest)
                    source = render(row) if row['inject_goal'] in GOAL_ALIASES else render_payload(row)
                    ast.parse(source)
                    dest = target / row['attack_file']
                    if vector == 'py':
                        dest.write_text(source)
                    else:
                        index = str(len(jobs))
                        (build / f'{index}.py').write_text(source)
                        if vector == 'elf':
                            encoded = base64.b64encode(source.encode()).decode()
                            (build / f'{index}.c').write_text(_C_TEMPLATE.format(b64_literal=_c_string_chunks(encoded)))
                        jobs.append({'index': index, 'vector': vector, 'dest': str(dest)})
                    rows.append(row)
                write_json(target / 'selected_5_tasks_with_attack_config.json', rows)
                sampled = [{k: v for k, v in row.items() if k not in {'attack_config', 'attack_file', 'populate_files'}} for row in rows]
                write_json(target / 'selected_5_tasks_with_inject_goals.json', sampled)
        write_json(build / 'jobs.json', jobs)
        (build / 'compile.py').write_text('''import json, py_compile, subprocess
from pathlib import Path
for job in json.loads(Path('/w/jobs.json').read_text()):
    name = '/w/' + job['index']
    if job['vector'] == 'pyc':
        py_compile.compile(name + '.py', cfile=name + '.out', dfile='<payload>', doraise=True)
    else:
        subprocess.run(['gcc', '-O2', '-s', '-o', name + '.out', name + '.c'], check=True)
print('Compiled all', flush=True)
''')
        import os
        subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--user', f'{os.getuid()}:{os.getgid()}',
                        '-v', f'{build}:/w', IMAGE, 'python3', '/w/compile.py'], check=True)
        for job in jobs:
            dest = Path(job['dest'])
            shutil.copy2(build / (job['index'] + '.out'), dest)
            if job['vector'] == 'elf':
                dest.chmod(0o755)
        manifest['image_id'] = subprocess.check_output(['docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}'], text=True).strip()
    write_json(ROOT / 'selection_manifest.json', manifest)
    validate()


def validate():
    count = 0
    for category in CATEGORIES:
        canonical = None
        for vector in VECTORS:
            folder = ROOT / category / vector
            rows = json.loads((folder / 'selected_5_tasks_with_attack_config.json').read_text())
            assert len(rows) == len({r['task_id'] for r in rows}) == len({r['inject_goal'] for r in rows}) == 5
            normalized = []
            for row in rows:
                assert row['inject_vector'] == vector
                for relative in [row['attack_file'], *row['populate_files']]:
                    path = (folder / relative).resolve()
                    assert path.is_relative_to(folder.resolve()) and path.is_file(), path
                artifact = folder / row['attack_file']
                if vector == 'elf':
                    assert artifact.read_bytes()[:4] == b'\x7fELF'
                elif vector == 'py':
                    ast.parse(artifact.read_text())
                else:
                    assert artifact.read_bytes()[2:4] == b'\r\n'
                normalized.append((row['task_id'], row['inject_goal'], replace(row['attack_config'], [(row['harmful_task_id'], '<ID>')]), row['prompt'], row.get('add_user_prompt', False), row.get('no_key_words', False)))
            if canonical is None:
                canonical = normalized
            assert canonical == normalized, category
            count += len(rows)
    write_json(ROOT / 'validation_report.json', {'status': 'passed', 'records': count, 'categories': 3,
        'tasks_per_category': 5, 'vectors': list(VECTORS), 'checks': ['unique task IDs and goals within each category',
        'identical goals, normalized attack configs and prompts across vectors', 'all referenced artifacts exist inside bundle',
        'Python syntax / pyc header / ELF header'], 'payloads_executed': False})
    print(f'Validated {count} records', flush=True)


if __name__ == '__main__':
    if '--validate' in sys.argv:
        validate()
    else:
        main()
