"""Read-only judge case discovery, offline inputs, and separate human annotations."""
from __future__ import annotations
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

from flask import Blueprint, abort, jsonify, render_template, request, Response
from judge_capture import exposure_instructions, split_prompt

APP_DIR = Path(__file__).resolve().parent
REPO = APP_DIR.parent
SKIP = {'_exposure_rejudge', '__pycache__', '.git', '.venv', 'node_modules',
        'backups', 'backup', 'inputs', 'environments', 'logs', 'proxy', '_attack_task_files'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def grade_files(roots):
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in SKIP and 'backup' not in d.lower() and not d.startswith('.')]
            if 'grades.json' in files:
                path = (Path(directory) / 'grades.json').resolve()
                dirs[:] = []
                if path not in seen:
                    seen.add(path)
                    yield path


class JudgeStore:
    def __init__(self, roots=None, audit_roots=None, data_dir=None):
        configured = os.environ.get('ARCHIPELAGO_JUDGE_RUNS_DIR') or os.environ.get('ARCHIPELAGO_RUNS_DIR')
        self.roots = roots if roots is not None else ([Path(configured).resolve()] if configured else [
            REPO / 'benchmark/output', REPO / 'examples/hugging_face_task/output'])
        audit = os.environ.get('ARCHIPELAGO_JUDGE_AUDIT_DIR')
        self.audit_roots = audit_roots if audit_roots is not None else (
            [Path(audit).resolve()] if audit else list((REPO.parent / 'benchmark_document_stats').glob('exposure_judge_*')))
        self.data_dir = Path(data_dir or os.environ.get('ARCHIPELAGO_JUDGE_DATA_DIR', APP_DIR / 'data/judge_review'))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = self.data_dir / 'annotations.sqlite3'
        with self.connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS annotations (
                case_id TEXT PRIMARY KEY, version TEXT NOT NULL, verdict TEXT NOT NULL,
                message_numbers TEXT NOT NULL, notes TEXT NOT NULL, reviewer TEXT NOT NULL,
                updated_at TEXT NOT NULL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY, case_id TEXT NOT NULL, payload TEXT NOT NULL)''')
            if 'input_version' not in {r['name'] for r in conn.execute('PRAGMA table_info(annotations)')}:
                conn.execute('ALTER TABLE annotations ADD COLUMN input_version TEXT')
        self.lock = threading.RLock()
        self.cases = {}
        self.inputs = {}
        self.detail_cache = {}
        self.scanned_at = 0
        self.errors = []

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db, timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def annotations(self):
        with self.connect() as conn:
            return {r['case_id']: {**dict(r), 'message_numbers': json.loads(r['message_numbers'])}
                    for r in conn.execute('SELECT * FROM annotations')}

    def scan(self, force=False):
        with self.lock:
            if self.scanned_at and not force:
                return
            cases, inputs, errors = {}, {}, []
            exclusion_file = self.data_dir / 'excluded_cases.json'
            excluded = {str(Path(item['path']).resolve()) for item in read(exclusion_file)} if exclusion_file.exists() else set()
            for root in self.audit_roots:
                path = root / 'requests.json'
                if not path.exists():
                    continue
                try:
                    for item in read(path):
                        if 'path' in item and 'request' in item:
                            inputs[str(Path(item['path']).resolve())] = {'value': item['request'], 'root': str(root), 'hash': item.get('hash')}
                except (ValueError, OSError, TypeError) as error:
                    errors.append(f'{path}: {error}')
            configs = {}
            for path in grade_files(self.roots):
                if str(path) in excluded:
                    continue
                try:
                    grade = read(path)
                    if not isinstance(grade, dict):
                        continue
                    task = path.parent
                    run = task.parent.parent if task.parent.name == 'tasks' else task.parent
                    config_path = run / 'orchestrator_config.json'
                    if config_path not in configs:
                        try:
                            configs[config_path] = read(config_path).get('model', '')
                        except (ValueError, OSError, AttributeError):
                            configs[config_path] = ''
                    model = configs[config_path] or run.parent.name
                    relative = next((str(path.relative_to(root)) for root in self.roots if path.is_relative_to(root)), str(path))
                    parts = Path(relative).parts
                    experiment = parts[1] if len(parts) > 1 and parts[0] == 'ablation' else parts[0]
                    trajectory = task / 'trajectory.json'
                    date = datetime.fromtimestamp((trajectory if trajectory.exists() else path).stat().st_mtime, timezone.utc).isoformat()
                    entries = []
                    if isinstance(grade.get('prompt_exposure_llm_judge'), dict):
                        entries.append(('exposure', 'prompt_exposure_llm_judge', grade['prompt_exposure_llm_judge']))
                    rules = grade.get('attack_rules') or {}
                    if isinstance(rules, dict):
                        entries.extend(('security', key, value) for key, value in rules.items()
                                       if key.startswith('llm_judge') and isinstance(value, dict) and isinstance(value.get('request'), dict))
                    for kind, key, output in entries:
                        case_id = digest([str(path), kind, key])[:24]
                        value = output.get('exposure' if kind == 'exposure' else 'passed')
                        value = value if type(value) is int and value in (0, 1) else None
                        error = output.get('error') or grade.get('prompt_exposure_error' if kind == 'exposure' else 'attack_error')
                        case = {'id': case_id, 'kind': kind, 'rule_key': key, 'task': task.name,
                                'run': str(run), 'path': str(path), 'relative_path': relative,
                                'experiment': experiment, 'model': model, 'judge_model': output.get('model'),
                                'result': value, 'output': output, 'error': error, 'date': date,
                                'description': output.get('description', 'Prompt content exposure'),
                                'version': digest(output), 'has_saved_input': str(path) in inputs}
                        logged = output.get('request') or {}
                        evidence = logged.get('input')
                        if evidence is None and kind == 'exposure' and str(path) in inputs:
                            saved = inputs[str(path)]['value']
                            evidence = {'reference_prompts': saved.get('expected_prompts', saved.get('reference_prompts', [])),
                                        'tool_results': saved.get('tool_results', [])}
                        if evidence is None and logged.get('prompt'):
                            _, sections = split_prompt(logged['prompt'])
                            evidence = {'sections': sections} if sections else {'prompt': logged['prompt']}
                        case['input_version'] = digest(evidence) if evidence is not None else None
                        case['search'] = ' '.join(str(case[k]) for k in ('task','relative_path','model','experiment','kind','description')) + ' ' + str(output.get('rationale',''))
                        cases[case_id] = case
                except (ValueError, OSError, TypeError, AttributeError) as error:
                    errors.append(f'{path}: {error}')
            self.cases, self.inputs, self.errors = cases, inputs, errors
            # Upgrade legacy labels only when their exact reviewed result still exists.
            with self.connect() as conn:
                for case in cases.values():
                    if case['input_version']:
                        conn.execute('UPDATE annotations SET input_version=? WHERE case_id=? AND version=? AND input_version IS NULL',
                                     (case['input_version'], case['id'], case['version']))
            self.detail_cache.clear()
            self.scanned_at = time.time()

    def get(self, case_id):
        self.scan()
        case = self.cases.get(case_id)
        if not case:
            abort(404, description='Judge case not found')
        return case

    def decorate(self, case, annotations):
        annotation = annotations.get(case['id'])
        stale = bool(annotation and (
            annotation['input_version'] != case['input_version'] if annotation.get('input_version')
            else annotation['version'] != case['version']))
        disagreement = bool(annotation and not stale and annotation['verdict'] in ('0','1')
                            and case['result'] is not None and int(annotation['verdict']) != case['result'])
        return {k: v for k, v in case.items() if k not in ('search','output')} | {
            'annotation': annotation, 'stale': stale, 'disagreement': disagreement,
            'rationale': case['output'].get('rationale', '')}

    def detail(self, case_id):
        case = self.get(case_id)
        with self.lock:
            cached = self.detail_cache.get(case_id)
        if cached is None:
            saved = self.inputs.get(case['path']) if case['kind'] == 'exposure' else None
            logged = case['output'].get('request')
            if isinstance(logged, dict):
                prompt, blocks = split_prompt(logged.get('prompt', ''))
                cached = {'prompt': prompt, 'input': logged.get('input', {'sections': blocks}),
                          'raw_request': logged, 'input_source': 'saved', 'prompt_source': 'saved', 'note': 'Saved request.'}
            elif saved:
                value = saved['value']
                cached = {'prompt': exposure_instructions(), 'input': {
                    'reference_prompts': value.get('expected_prompts', value.get('reference_prompts', [])),
                    'tool_results': value.get('tool_results', [])},
                    'input_source': 'saved', 'prompt_source': 'reconstructed',
                    'note': 'Reference text and every tool result are saved inputs. The system prompt is reconstructed from the current checker; historical wording may differ.'}
                example = Path(saved['root']) / 'example_prompt_input_output.json'
                frozen_prompt = Path(saved['root']) / 'reconstructed_system_prompt.txt'
                if frozen_prompt.exists():
                    cached['prompt'] = frozen_prompt.read_text()
                    cached['note'] = 'Saved reference text and tool results. System prompt reconstructed and frozen before later checker changes; historical wording may differ.'
                if example.exists():
                    try:
                        sample = read(example)
                        if str(Path(sample.get('task','')).resolve()) == case['path']:
                            cached['prompt'] = sample['request']['messages'][0]['content']
                            cached['prompt_source'] = 'reconstructed'
                    except (ValueError, OSError, KeyError, TypeError):
                        pass
                history = Path(saved['root']) / 'judgments_round1' / f"{saved['hash']}.json"
                if history.exists():
                    try:
                        cached['previous_output'] = read(history).get('judgment')
                    except (OSError, ValueError):
                        pass
            else:
                python = os.environ.get('ARCHIPELAGO_JUDGE_PYTHON', sys.executable)
                try:
                    proc = subprocess.run([python, str(APP_DIR / 'judge_capture.py')],
                        input=json.dumps({'kind': case['kind'], 'grade_path': case['path'], 'rule_key': case['rule_key']}),
                        text=True, capture_output=True, timeout=60, cwd=REPO)
                    cached = json.loads(proc.stdout) if proc.returncode == 0 else {'error': proc.stderr[-2000:]}
                except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                    cached = {'error': str(error)}
                if 'error' in cached:
                    cached = {'prompt': '', 'input': {}, 'input_source': 'unavailable', 'prompt_source': 'unavailable',
                              'note': 'Input could not be reconstructed: ' + cached['error']}
            with self.lock:
                self.detail_cache[case_id] = cached
        data = self.decorate(case, self.annotations())
        data.update(cached)
        data['output'] = {k: v for k, v in case['output'].items() if k not in ('request', 'raw_output')}
        data['raw_output'] = case['output'].get('raw_output')
        data['schema'] = {'exposure' if case['kind'] == 'exposure' else 'passed': '0 or 1',
                          'message_numbers': 'original 1-based tool message numbers (exposure only)', 'rationale': 'judgment explanation'}
        return data

    def save(self, case_id, payload):
        case = self.get(case_id)
        current_grade = read(Path(case['path']))
        current_output = (current_grade.get('prompt_exposure_llm_judge') if case['kind'] == 'exposure'
                          else current_grade.get('attack_rules', {}).get(case['rule_key']))
        if digest(current_output) != case['version']:
            self.scan(force=True)
            abort(409, description='The model result changed. Reload the case before saving.')
        if payload.get('version') != case['version']:
            abort(409, description='The model result changed. Reload the case before saving.')
        verdict = payload.get('verdict')
        numbers = payload.get('message_numbers', [])
        notes, reviewer = payload.get('notes', ''), payload.get('reviewer', '')
        if verdict not in ('0','1','uncertain'):
            abort(400, description='Choose 0, 1, or uncertain')
        if not isinstance(numbers, list) or any(type(n) is not int or n < 1 for n in numbers):
            abort(400, description='Message numbers must be positive integers')
        if not isinstance(notes, str) or len(notes) > 20000 or not isinstance(reviewer, str) or len(reviewer) > 120:
            abort(400, description='Invalid notes or reviewer')
        if numbers:
            if case['kind'] != 'exposure' or verdict == '0':
                abort(400, description='Message numbers apply to positive or uncertain exposure reviews')
            detail = self.detail(case_id)
            valid = {m['message_number'] for m in detail.get('input',{}).get('tool_results',[])}
            if any(n not in valid for n in numbers):
                abort(400, description='A message number is not among the tool results')
        annotation = {'case_id': case_id, 'version': case['version'], 'verdict': verdict,
                      'input_version': case['input_version'],
                      'message_numbers': sorted(set(numbers)), 'notes': notes, 'reviewer': reviewer.strip(),
                      'updated_at': datetime.now(timezone.utc).isoformat()}
        with self.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO annotations (case_id,version,verdict,message_numbers,notes,reviewer,updated_at,input_version) VALUES (?,?,?,?,?,?,?,?)', (
                case_id, case['version'], verdict, json.dumps(annotation['message_numbers']), notes, reviewer.strip(), annotation['updated_at'], case['input_version']))
            conn.execute('INSERT INTO history (case_id,payload) VALUES (?,?)', (case_id, json.dumps(annotation)))
        return annotation


def register_judge_review(app, store=None):
    store = store or JudgeStore()
    app.extensions['judge_store'] = store
    bp = Blueprint('judge_review', __name__)

    @bp.get('/judges')
    def page():
        return render_template('judges.html')

    @bp.get('/api/judges')
    def listing():
        store.scan()
        annotations = store.annotations()
        all_cases = [store.decorate(c, annotations) for c in store.cases.values()]
        query = request.args.get('q','').casefold().strip()
        values = []
        for case in all_cases:
            if query and query not in (store.cases[case['id']]['search'] + ' ' + str((case['annotation'] or {}).get('notes',''))).casefold():
                continue
            if any(request.args.get(k) and str(case[k]) != request.args[k] for k in ('kind','model','experiment','result')):
                continue
            state = request.args.get('review','')
            if state == 'unreviewed' and case['annotation'] and not case['stale']: continue
            if state == 'reviewed' and (not case['annotation'] or case['stale']): continue
            if state == 'disagreement' and not case['disagreement']: continue
            if state == 'stale' and not case['stale']: continue
            values.append(case)
        values.sort(key=lambda c: (c['date'], c['id']), reverse=True)
        try:
            offset = max(0, int(request.args.get('offset', 0)))
            limit = max(1, min(200, int(request.args.get('limit', 60))))
        except ValueError:
            abort(400, description='Invalid pagination')
        return jsonify({'cases': values[offset:offset+limit], 'total': len(values), 'offset': offset,
            'facets': {k: sorted({c[k] for c in all_cases}) for k in ('model','experiment')},
            'stats': {'total': len(all_cases), 'exposure': sum(c['kind']=='exposure' for c in all_cases),
                      'security': sum(c['kind']=='security' for c in all_cases),
                      'reviewed': sum(bool(c['annotation']) and not c['stale'] for c in all_cases),
                      'disagreements': sum(c['disagreement'] for c in all_cases)},
            'scan_errors': store.errors, 'scanned_at': store.scanned_at})

    @bp.post('/api/judges/refresh')
    def refresh():
        store.scan(force=True)
        return jsonify({'count': len(store.cases), 'errors': store.errors})

    @bp.get('/api/judges/export')
    def export():
        store.scan()
        annotations = store.annotations()
        rows = [store.decorate(c, annotations) for c in store.cases.values()]
        rows = [r for r in rows if r['annotation']]
        return Response(json.dumps(rows, ensure_ascii=False, indent=2), mimetype='application/json',
                        headers={'Content-Disposition': 'attachment; filename="judge_annotations.json"'})

    @bp.get('/api/judges/<case_id>')
    def detail(case_id):
        return jsonify(store.detail(case_id))

    @bp.post('/api/judges/<case_id>/annotation')
    def annotate(case_id):
        if request.headers.get('X-Judge-Review') != '1':
            abort(400, description='Missing review request header')
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            abort(400, description='JSON object required')
        return jsonify(store.save(case_id, body))

    @bp.delete('/api/judges/<case_id>/annotation')
    def remove(case_id):
        if request.headers.get('X-Judge-Review') != '1': abort(400)
        store.get(case_id)
        with store.connect() as conn:
            conn.execute('DELETE FROM annotations WHERE case_id=?', (case_id,))
            conn.execute('INSERT INTO history (case_id,payload) VALUES (?,?)', (case_id, json.dumps({'deleted_at': datetime.now(timezone.utc).isoformat()})))
        return jsonify({'deleted': True})

    app.register_blueprint(bp)
