"""Frozen, stratified review rounds with private per-reviewer annotations.

The legacy annotations table remains intact for existing audit scripts. New
annotations live in separate tables; API responses are explicitly whitelisted.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import secrets
import sqlite3
import time
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template, request
from judge_review import JudgeStore


def now():
    return datetime.now(timezone.utc).isoformat()


GOAL_ALIASES = {13: 1, 14: 2, 15: 3, 16: 4, 17: 6, 25: 19,
                26: 20, 27: 21, 28: 22, 29: 23, 30: 24, 31: 7, 32: 18}
EXPOSURE_GOALS = list(range(1, 13)) + list(range(18, 25))
SAFETY_GOALS = [2, 6, 7, 18, 24]


def goal_of(case):
    match = re.search(r'_(\d+)_([a-z][a-z_]+)$', case['task'])
    if not match:
        return None
    raw = int(match[1])
    return GOAL_ALIASES.get(raw, raw), match[2].removesuffix('_arg')


def review_goal(case, policy):
    if policy == 'goal-balanced' and case['kind'] == 'exposure':
        match = re.search(r'_(\d+)_([a-z][a-z_]+)$', case['task'])
        return (int(match[1]), match[2]) if match else None
    return goal_of(case)


def balanced_selection(pools, goals, reusable, rng):
    """Exact quotas, maximizing retained labels; seeded random ties.

    Exposure uses raw goal IDs, 1–2 each, exactly 20 per predicted label.
    Safety uses five semantic families, four each, retaining all negatives.
    """
    # A source task may only contribute one case per judge kind.
    seen = set()
    for key in sorted(pools):
        unique = []
        for case in pools[key]:
            identity = (case['kind'], case['path'])
            if identity not in seen:
                unique.append(case)
                seen.add(identity)
        pools[key] = unique
    states = {(0, 0): (0, [])}
    for goal in sorted(goals['exposure']):
        options = [(n0, n1) for n0 in range(3) for n1 in range(3)
                   if 1 <= n0+n1 <= 2
                   and n0 <= len(pools[('exposure', goal, 0)])
                   and n1 <= len(pools[('exposure', goal, 1)])]
        rng.shuffle(options)
        next_states = {}
        for (z, p), (score, chosen) in states.items():
            for n0, n1 in options:
                target = (z+n0, p+n1)
                if max(target) > 20:
                    continue
                cases = pools[('exposure', goal, 0)][:n0] + pools[('exposure', goal, 1)][:n1]
                value = score + sum(reusable(c) for c in cases)
                if target not in next_states or value > next_states[target][0]:
                    next_states[target] = (value, chosen+cases)
        states = next_states
    if (20, 20) not in states:
        raise ValueError('Cannot satisfy exposure: all raw goals, 1–2 each, and 20 positive/20 negative.')
    selected = states[(20, 20)][1]
    if len(goals['security']) != 5:
        raise ValueError('Safety policy requires exactly five semantic goal families.')
    for goal in sorted(goals['security']):
        negative = pools[('security', goal, 0)]
        positive = pools[('security', goal, 1)]
        if len(negative) > 4 or len(negative)+len(positive) < 4:
            raise ValueError(f'Safety goal {goal}: cannot retain all negatives within four cases.')
        selected += negative + positive[:4-len(negative)]
    return selected


class BlindStore:
    def __init__(self, source):
        self.source = source
        self.db = source.db
        config_path = source.data_dir / 'reviewer-config.json'
        config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
        self.legacy_reviewer = config.get('legacy_reviewer', 'legacy')
        if not isinstance(self.legacy_reviewer, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{2,40}', self.legacy_reviewer):
            raise ValueError('Invalid legacy reviewer ID in reviewer-config.json')
        self.legacy_reviewer = self.legacy_reviewer.lower()
        # Back up before assigning legacy ownership or adding new tables.
        backup = source.data_dir / 'annotations.before-multiuser.sqlite3'
        if not backup.exists():
            with source.connect() as original, closing(sqlite3.connect(backup)) as target:
                original.backup(target)
            backup.chmod(0o600)
        with source.connect() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS review_users (
                    name TEXT PRIMARY KEY, password_hash TEXT, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS review_sessions (
                    token_hash TEXT PRIMARY KEY, reviewer TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS review_rounds (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, report TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS review_cases (
                    round_id TEXT NOT NULL, case_id TEXT NOT NULL, position INTEGER NOT NULL,
                    snapshot TEXT NOT NULL, PRIMARY KEY(round_id, case_id));
                CREATE TABLE IF NOT EXISTS review_labels (
                    round_id TEXT NOT NULL, case_id TEXT NOT NULL, reviewer TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(round_id, case_id, reviewer));
                CREATE TABLE IF NOT EXISTS review_events (
                    id INTEGER PRIMARY KEY, round_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    reviewer TEXT NOT NULL, payload TEXT NOT NULL);
            ''')
            c.execute("UPDATE annotations SET reviewer=? WHERE trim(reviewer)=''", (self.legacy_reviewer,))
            # Preserve timestamps, notes and verdicts in the historical audit log.
            for row in c.execute('SELECT id,payload FROM history').fetchall():
                value = json.loads(row['payload'])
                if not value.get('reviewer', '').strip():
                    value['reviewer'] = self.legacy_reviewer
                    c.execute('UPDATE history SET payload=? WHERE id=?', (json.dumps(value), row['id']))
            for row in c.execute('SELECT DISTINCT reviewer FROM annotations'):
                c.execute('INSERT OR IGNORE INTO review_users VALUES (?,NULL,?)', (row['reviewer'], now()))

    def active_round(self):
        with self.source.connect() as c:
            row = c.execute('SELECT id FROM review_rounds ORDER BY created_at DESC LIMIT 1').fetchone()
        return row['id'] if row else None

    def snapshots(self, round_id):
        with self.source.connect() as c:
            rows = c.execute('SELECT snapshot FROM review_cases WHERE round_id=? ORDER BY position', (round_id,)).fetchall()
        return [json.loads(r['snapshot']) for r in rows]

    def labels(self, round_id, reviewer):
        with self.source.connect() as c:
            rows = c.execute('SELECT case_id,payload FROM review_labels WHERE round_id=? AND reviewer=?',
                             (round_id, reviewer)).fetchall()
        return {r['case_id']: json.loads(r['payload']) for r in rows}

    def create_round(self, round_id, goals, seed=20260926, fill=False, policy='legacy'):
        """Exposure: one per label/goal; safety: two per label/goal.

        Prefer reusable human annotations within each stratum, but never use a
        human verdict to choose its predicted-label stratum. Missing strata are
        reported, never fabricated. Sampling only uses saved, valid inputs.
        """
        with self.source.connect() as c:
            if c.execute('SELECT 1 FROM review_rounds WHERE id=?', (round_id,)).fetchone():
                raise ValueError('Round already exists; its sample is frozen.')
        self.source.scan()
        old = self.source.annotations()
        rng = random.Random(seed)
        pools = defaultdict(list)
        available = defaultdict(lambda: defaultdict(Counter))
        def reusable(case):
            return (case['id'] in old and old[case['id']]['reviewer'] == self.legacy_reviewer
                    and not self.source.decorate(case, old)['stale'])
        for case in self.source.cases.values():
            goal = review_goal(case, policy)
            if not goal or case['result'] not in (0, 1) or case['error'] or not case['input_version']:
                continue
            available[case['kind']][goal[0]][case['result']] += 1
            if goal[0] in goals.get(case['kind'], []):
                pools[(case['kind'], goal[0], case['result'])].append(case)
        for values in pools.values():
            values.sort(key=lambda x: x['id'])
            rng.shuffle(values)
            values.sort(key=lambda x: not reusable(x))
        selected, shortages, extras = [], [], []
        used = set()
        if policy == 'goal-balanced':
            observed = set(available['exposure'])
            if observed != set(goals['exposure']):
                raise ValueError(f'Exposure goal list must equal all eligible raw goals: {sorted(observed)}')
            selected = balanced_selection(pools, goals, reusable, rng)

        def take(key):
            values = pools[key]
            if any((c['kind'],goal_of(c)[0],c['result']) == key for c in selected):
                # Keep only one historical representative per goal/label where
                # possible; extra quota samples should add fresh review work.
                values = sorted(values,key=lambda c: c['id'] in old)
            for case in values:
                # One underlying task per judge in a round; avoid duplicate rule calls.
                identity = (case['kind'], case['path'])
                if identity not in used:
                    used.add(identity)
                    selected.append(case)
                    return True
            return False

        for kind, target in ([] if policy == 'goal-balanced' else [('exposure', 40), ('security', 20)]):
            quota = 2 if kind == 'security' else 1
            coverage_first = len(goals[kind])*2*quota > target
            if coverage_first and not fill:
                raise ValueError(f'{kind}: {len(goals[kind])} goals require at least {len(goals[kind])*2} cases, exceeding {target}.')
            if len(goals[kind]) > target:
                raise ValueError(f'{kind}: cannot cover {len(goals[kind])} goals in {target} cases.')
            for goal in sorted(goals[kind]):
                results = [0,1]
                if coverage_first:
                    # Keep an existing representative for each goal first.
                    rng.shuffle(results)
                    results.sort(key=lambda r: not any(v['id'] in old and not self.source.decorate(v,old)['stale']
                                                       for v in pools[(kind,goal,r)]))
                    results = [next((r for r in results if pools[(kind,goal,r)]), results[0])]
                for result in results:
                    missing = sum(not take((kind, goal, result)) for _ in range(1 if coverage_first else quota))
                    if missing:
                        shortages.append({'kind': kind, 'goal': goal, 'predicted_label': result, 'missing': missing})
            # Complete pairs from an additional occurrence of an eligible goal.
            choices = sorted(goals[kind]); rng.shuffle(choices)
            base_missing = sum(x['kind'] == kind for x in shortages)
            while not coverage_first and not base_missing and sum(c['kind'] == kind for c in selected) < target:
                goal = next((g for g in choices if all(any((v['kind'], v['path']) not in used
                             for v in pools[(kind, g, result)]) for result in (0, 1))), None)
                if goal is None:
                    break
                for result in (0, 1):
                    take((kind, goal, result))
                extras.append({'kind': kind, 'goal': goal})
            if fill:
                # Explicitly requested fallback: same target goals, closest global balance.
                while sum(c['kind'] == kind for c in selected) < target:
                    counts = Counter(c['result'] for c in selected if c['kind'] == kind)
                    keys = [(kind,g,r) for r in sorted((0,1), key=lambda r: counts[r]) for g in choices]
                    strata = Counter((c['kind'],goal_of(c)[0],c['result']) for c in selected)
                    goal_counts = Counter(goal_of(c)[0] for c in selected if c['kind'] == kind)
                    # Label balance first, then spread replacements across goals.
                    keys.sort(key=lambda key: (counts[key[2]], goal_counts[key[1]], strata[key]))
                    if not any(take(key) for key in keys):
                        break
        rng.shuffle(selected)
        snapshots = []
        for case in selected:
            detail = self.source.detail(case['id'])
            if detail.get('input_source') != 'saved' or not detail.get('input'):
                raise ValueError(f"No saved evidence for {case['id']}; cannot freeze round")
            detail['goal_id'], detail['goal_name'] = review_goal(case, policy)
            detail['raw_goal_id'] = int(re.search(r'_(\d+)_([a-z][a-z_]+)$', case['task'])[1])
            snapshots.append(detail)
        report = {'round': round_id, 'seed': seed, 'created_at': now(), 'goals': goals,
                  'targets': {'exposure':40, 'security':20}, 'shortages': shortages,
                  'extra_pairs': extras, 'fallback_fill': fill,
                  'sampling_labels': 'LLM predictions; not human ground truth',
                  'goal_aliases': GOAL_ALIASES,
                  'per_goal_label_quota': {'exposure': 1, 'security': 2},
                  'availability': {k: {str(g): dict(v) for g,v in rows.items()} for k,rows in available.items()},
                  'counts': {}, 'reused': {}, 'new_for_legacy_reviewer': {}}
        report['policy'] = policy
        if policy == 'goal-balanced':
            report['per_goal_label_quota'] = None
            report['constraints'] = {'exposure': 'all raw goals, 1–2 each, 20 positive and 20 negative',
                                     'security': 'five semantic families, four each, all eligible negatives'}
            report['absent_exposure_goal_ids'] = sorted(set(range(1,33))-set(available['exposure']))
        for kind in goals:
            subset = [x for x in snapshots if x['kind'] == kind]
            reused = sum(bool(x['annotation']) and not x['stale'] and x['annotation']['reviewer'] == self.legacy_reviewer for x in subset)
            report['counts'][kind] = dict(Counter(str(x['result']) for x in subset))
            report['reused'][kind] = reused
            report['new_for_legacy_reviewer'][kind] = len(subset) - reused
        report['unfilled'] = {kind: target-sum(s['kind']==kind for s in snapshots)
                              for kind,target in report['targets'].items()}
        report['goal_coverage'] = {}
        for kind, ids in goals.items():
            report['goal_coverage'][kind] = {}
            for goal in ids:
                subset = [s for s in snapshots if s['kind']==kind and s['goal_id']==goal]
                counts = Counter(s['result'] for s in subset)
                report['goal_coverage'][kind][str(goal)] = {
                    'selected':dict(counts),
                    'missing_labels':[{'label':r,'reason':'no_candidate' if not pools[(kind,goal,r)] else 'sample_limit'}
                                      for r in (0,1) if not counts[r]]}
        with self.source.connect() as c:
            c.execute('INSERT INTO review_rounds VALUES (?,?,?)', (round_id, report['created_at'], json.dumps(report)))
            for position, snap in enumerate(snapshots):
                annotation = snap.pop('annotation', None)
                c.execute('INSERT INTO review_cases VALUES (?,?,?,?)', (round_id,snap['id'],position,json.dumps(snap)))
                if annotation and not snap['stale']:
                    label = {**annotation, 'legacy': True, 'blind': False}
                    c.execute('INSERT INTO review_labels VALUES (?,?,?,?)', (round_id,snap['id'],label['reviewer'],json.dumps(label)))
                    c.execute('INSERT INTO review_events (round_id,case_id,reviewer,payload) VALUES (?,?,?,?)',
                              (round_id,snap['id'],label['reviewer'],json.dumps(label)))
        return report

    def public_case(self, snap, reviewer, round_id, detail=False):
        annotation = self.labels(round_id, reviewer).get(snap['id'])
        # Hide model verdicts, rationale, matched messages and all historical
        # outputs from list/search/export/detail until this reviewer submits.
        result = {k: snap[k] for k in ('id','kind','task','model','experiment','goal_id','goal_name','version')}
        result.update(annotation=annotation, blind=not bool(annotation), round_id=round_id)
        if detail:
            result.update({k: snap.get(k) for k in ('prompt','input','input_source','prompt_source')})
        if annotation:
            result['result'] = snap['result']
            with self.source.connect() as c:
                first = c.execute('SELECT payload FROM review_events WHERE round_id=? AND case_id=? AND reviewer=? ORDER BY id LIMIT 1',
                                  (round_id,snap['id'],reviewer)).fetchone()
            result['first_annotation'] = json.loads(first['payload']) if first else annotation
            if detail:
                result['output'] = {k: snap.get('output', {}).get(k) for k in ('rationale','message_numbers','model')}
                with self.source.connect() as c:
                    result['other_annotations'] = [json.loads(r['payload']) for r in c.execute(
                        'SELECT payload FROM review_labels WHERE round_id=? AND case_id=? AND reviewer<>?',
                        (round_id, snap['id'], reviewer))]
        return result


def register_blind_review(app, source=None):
    store = BlindStore(source or JudgeStore())
    app.extensions['judge_store'] = store.source
    app.extensions['blind_store'] = store
    bp = Blueprint('judge_review', __name__)

    @bp.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    @bp.before_request
    def protect_mutation():
        if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('X-Judge-Review') != '1':
            abort(400, description='Missing review request header')

    def identity():
        token = request.cookies.get('judge_session', '')
        with store.source.connect() as c:
            row = c.execute('SELECT reviewer FROM review_sessions WHERE token_hash=? AND expires>?',
                            (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if not row:
            abort(401, description='Please sign in')
        return row['reviewer']

    def current():
        round_id = request.args.get('round') or store.active_round()
        if not round_id:
            abort(409, description='No review round prepared yet')
        return round_id

    def find_case(round_id, case_id):
        snap = next((s for s in store.snapshots(round_id) if s['id'] == case_id), None)
        if not snap:
            abort(404)
        return snap

    @bp.get('/judges')
    def page():
        return render_template('judges_blind.html')

    @bp.post('/api/judges/login')
    def login():
        data = request.get_json(silent=True) or {}
        name = data.get('name','')
        if isinstance(name, str):
            name = name.strip()
        if not isinstance(name,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{2,40}',name):
            abort(400, description='Use a 2–40 character reviewer ID (letters, numbers, underscore or hyphen)')
        name = name.lower()
        with store.source.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            # Trusted-team identity selection, not identity authentication.
            c.execute('INSERT OR IGNORE INTO review_users VALUES (?,NULL,?)', (name,now()))
            c.execute('DELETE FROM review_sessions WHERE token_hash=?',
                      (hashlib.sha256(request.cookies.get('judge_session','').encode()).hexdigest(),))
            token = secrets.token_urlsafe(32)
            c.execute('INSERT INTO review_sessions VALUES (?,?,?)',
                      (hashlib.sha256(token.encode()).hexdigest(), name, time.time()+7*86400))
        response = jsonify(reviewer=name)
        response.set_cookie('judge_session',token,httponly=True,samesite='Strict',secure=request.is_secure,max_age=7*86400)
        return response

    @bp.post('/api/judges/logout')
    def logout():
        with store.source.connect() as c:
            c.execute('DELETE FROM review_sessions WHERE token_hash=?',
                      (hashlib.sha256(request.cookies.get('judge_session','').encode()).hexdigest(),))
        response = jsonify(ok=True); response.delete_cookie('judge_session'); return response

    @bp.get('/api/judges/me')
    def me():
        return jsonify(reviewer=identity(), round_id=store.active_round())

    @bp.get('/api/judges')
    def listing():
        reviewer, round_id = identity(), current()
        rows = [store.public_case(s,reviewer,round_id) for s in store.snapshots(round_id)]
        total = len(rows); reviewed = sum(bool(r['annotation']) for r in rows)
        q = request.args.get('q','').casefold()
        rows = [r for r in rows if (not request.args.get('kind') or r['kind']==request.args['kind'])
                and (not q or q in (r['task']+' '+r['goal_name']).casefold())
                and (request.args.get('review') != 'unreviewed' or not r['annotation'])
                and (request.args.get('review') != 'reviewed' or r['annotation'])]
        return jsonify(cases=rows,total=total,reviewed=reviewed,reviewer=reviewer,round_id=round_id)

    @bp.get('/api/judges/export')
    def export():
        reviewer, round_id = identity(), current()
        # No unrestricted export route: apply exactly the same blind gate.
        return jsonify([store.public_case(s,reviewer,round_id) for s in store.snapshots(round_id)])

    @bp.get('/api/judges/<case_id>')
    def detail(case_id):
        reviewer, round_id = identity(), current()
        return jsonify(store.public_case(find_case(round_id,case_id),reviewer,round_id,True))

    @bp.post('/api/judges/<case_id>/annotation')
    def annotate(case_id):
        reviewer, round_id = identity(), current()
        snap = find_case(round_id,case_id)
        body = request.get_json(silent=True)
        if not isinstance(body,dict) or body.get('version') != snap['version']:
            abort(409, description='Reload the case before submitting')
        verdict, numbers, notes = body.get('verdict'), body.get('message_numbers',[]), body.get('notes','')
        if verdict not in ('0','1','uncertain') or not isinstance(notes,str) or len(notes)>20000:
            abort(400, description='Invalid verdict or notes')
        if not isinstance(numbers,list) or any(type(n) is not int or n<1 for n in numbers):
            abort(400, description='Invalid message numbers')
        valid = {m['message_number'] for m in snap.get('input',{}).get('tool_results',[])}
        if numbers and (snap['kind']!='exposure' or verdict=='0' or not set(numbers)<=valid):
            abort(400, description='Message numbers must refer to the exposure evidence')
        with store.source.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            previous = c.execute('SELECT payload FROM review_labels WHERE round_id=? AND case_id=? AND reviewer=?',
                                 (round_id,case_id,reviewer)).fetchone()
            payload = {'case_id':case_id,'reviewer':reviewer,'verdict':verdict,'message_numbers':sorted(set(numbers)),
                       'notes':notes,'version':snap['version'],'input_version':snap['input_version'],
                       'updated_at':now(),'blind':not bool(previous),'legacy':False}
            c.execute('INSERT OR REPLACE INTO review_labels VALUES (?,?,?,?)', (round_id,case_id,reviewer,json.dumps(payload)))
            c.execute('INSERT INTO review_events (round_id,case_id,reviewer,payload) VALUES (?,?,?,?)',
                      (round_id,case_id,reviewer,json.dumps(payload)))
        return jsonify(payload)

    app.register_blueprint(bp)
