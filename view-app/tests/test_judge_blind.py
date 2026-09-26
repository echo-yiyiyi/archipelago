import json
import copy
import random
from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from flask import Flask
from judge_review import JudgeStore, digest
from judge_blind import BlindStore, register_blind_review, goal_of, EXPOSURE_GOALS, SAFETY_GOALS, balanced_selection, review_goal


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.source=JudgeStore(roots=[],audit_roots=[],data_dir=self.tmp.name)
        self.source.scanned_at=1
        self.goal_sets={'exposure':[1,2],'security':[2]}
        for kind,g,result in [('exposure',1,0),('exposure',1,1),('exposure',2,0),('security',2,0),('security',2,1)]:
            cid=f'{kind}-{g}-{result}'
            evidence={'reference_prompts':['instruction'],'tool_results':[{'message_number':3,'content':'evidence'}]}
            output={'result':result,'rationale':'SECRET_MODEL_REASON','message_numbers':[3],
                    'request':{'prompt':'criterion','input':evidence},'raw_output':'SECRET_RAW'}
            case={'id':cid,'kind':kind,'rule_key':'llm_judge_1','task':f'task_abc_{g}_goal',
                  'run':'run','path':cid,'relative_path':cid,'experiment':'test','model':'model',
                  'judge_model':'judge','result':result,'output':output,'error':None,'date':'today',
                  'description':'description','version':digest(output),'input_version':digest(evidence),
                  'has_saved_input':True,'search':'SECRET_MODEL_REASON'}
            self.source.cases[cid]=case
        c=self.source.cases['exposure-1-1']
        with self.source.connect() as db:
            db.execute('INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?)',
                       (c['id'],c['version'],'1','[3]','LEGACY_SECRET','','yesterday',c['input_version']))
            db.execute('INSERT INTO history (case_id,payload) VALUES (?,?)',(c['id'],json.dumps({'verdict':'1','reviewer':''})))
        self.app=Flask(__name__)
        self.app.config['TESTING']=True
        register_blind_review(self.app,self.source)
        self.store=self.app.extensions['blind_store']
        self.report=self.store.create_round('round1',self.goal_sets)
        self.a=self.app.test_client();self.b=self.app.test_client()
        self.login(self.a,'alice')
        self.login(self.b,'legacy')

    def tearDown(self):
        self.tmp.cleanup()

    def login(self,client,name):
        return client.post('/api/judges/login',json={'name':name},headers={'X-Judge-Review':'1'})

    def save(self,client,cid,verdict):
        return client.post('/api/judges/'+cid+'/annotation',json={
            'version':self.source.cases[cid]['version'],'verdict':verdict,'notes':'new note',
            'reviewer':'legacy','message_numbers':[]},headers={'X-Judge-Review':'1'})

    def test_legacy_migration_idempotent(self):
        BlindStore(self.source)
        self.assertTrue((Path(self.tmp.name)/'annotations.before-multiuser.sqlite3').exists())
        self.assertEqual(self.source.annotations()['exposure-1-1']['reviewer'],'legacy')
        self.assertEqual(self.store.labels('round1','legacy')['exposure-1-1']['verdict'],'1')
        self.assertFalse(self.store.labels('round1','legacy')['exposure-1-1']['blind'])
        with self.source.connect() as c:
            self.assertEqual(json.loads(c.execute('SELECT payload FROM history').fetchone()[0])['reviewer'],'legacy')

    def test_blind_all_routes(self):
        for url in ['/api/judges','/api/judges/export','/api/judges/exposure-1-1']:
            r=self.a.get(url);self.assertEqual(r.status_code,200)
            text=r.get_data(as_text=True)
            for secret in ['SECRET_MODEL_REASON','SECRET_RAW','LEGACY_SECRET','"result"','other_annotations','previous_output']:
                self.assertNotIn(secret,text)
        # Old result/disagreement filters do not provide an oracle.
        self.assertEqual(self.a.get('/api/judges?result=0').json,self.a.get('/api/judges?result=1').json)
        self.assertEqual(self.a.get('/api/judges?q=SECRET_MODEL_REASON').json['cases'],[])

    def test_independent_reviews_and_reveal(self):
        self.assertEqual(self.save(self.a,'exposure-1-1','0').status_code,200)
        self.assertEqual(self.store.labels('round1','legacy')['exposure-1-1']['verdict'],'1')
        self.assertEqual(self.store.labels('round1','alice')['exposure-1-1']['verdict'],'0')
        d=self.a.get('/api/judges/exposure-1-1').json
        self.assertFalse(d['blind']);self.assertEqual(d['result'],1)
        self.assertEqual(d['other_annotations'][0]['reviewer'],'legacy')
        self.assertTrue(self.a.get('/api/judges/exposure-1-0').json['blind'])
        self.save(self.a,'exposure-1-1','1')
        d=self.a.get('/api/judges/exposure-1-1').json
        self.assertEqual(d['first_annotation']['verdict'],'0')
        self.assertTrue(d['first_annotation']['blind'])
        self.assertFalse(d['annotation']['blind'])
        self.assertEqual(self.a.delete('/api/judges/exposure-1-1/annotation',headers={'X-Judge-Review':'1'}).status_code,405)

    def test_auth(self):
        anon=self.app.test_client()
        self.assertEqual(anon.get('/api/judges/export').status_code,401)
        self.assertEqual(self.login(anon,' LEGACY ').status_code,200)
        self.assertEqual(anon.get('/api/judges/me').json['reviewer'],'legacy')
        self.assertEqual(self.login(anon,'new-reviewer').status_code,200)
        self.assertEqual(anon.get('/api/judges/me').json['reviewer'],'new-reviewer')
        self.assertEqual(self.login(anon,'').status_code,400)
        self.assertEqual(self.login(anon,{'bad':'name'}).status_code,400)
        self.assertEqual(anon.post('/api/judges/login',json={}).status_code,400)

    def test_sampling_shortages_and_freeze(self):
        self.assertIn({'kind':'exposure','goal':2,'predicted_label':1,'missing':1},self.report['shortages'])
        self.assertEqual(self.report['counts']['exposure'],{'0':2,'1':1})
        self.assertEqual(self.report['reused']['exposure'],1)
        ids=[x['id'] for x in self.store.snapshots('round1')]
        self.assertEqual(len(ids),len(set(ids)))
        with self.assertRaises(ValueError):self.store.create_round('round1',self.goal_sets)
        self.source.cases['exposure-1-1']['result']=0
        self.assertEqual(self.b.get('/api/judges/exposure-1-1').json['result'],1)

    def test_stale_annotation_not_reused(self):
        self.source.cases['exposure-1-1']['input_version']='new-input'
        report=self.store.create_round('round2',self.goal_sets)
        self.assertEqual(report['reused']['exposure'],0)
        self.assertEqual(self.store.labels('round2','legacy'),{})

    def test_version_and_evidence_validation(self):
        r=self.a.post('/api/judges/exposure-1-0/annotation',json={'version':'wrong','verdict':'1'},headers={'X-Judge-Review':'1'})
        self.assertEqual(r.status_code,409)
        r=self.a.post('/api/judges/exposure-1-0/annotation',json={'version':self.source.cases['exposure-1-0']['version'],
                    'verdict':'1','message_numbers':[999]},headers={'X-Judge-Review':'1'})
        self.assertEqual(r.status_code,400)

    def test_canonical_balanced_quotas(self):
        template = copy.deepcopy(self.source.cases['exposure-1-0'])
        self.source.cases.clear()
        goals = {'exposure': EXPOSURE_GOALS, 'security': SAFETY_GOALS}
        for kind, ids in goals.items():
            for g in ids:
                for label in (0, 1):
                    for i in range(4):
                        case = copy.deepcopy(template)
                        cid = f'{kind}-{g}-{label}-{i}'
                        raw = 14 if g == 2 and i % 2 else g
                        case.update(id=cid, path=cid, kind=kind, result=label,
                                    task=f'task_abc_{raw}_goal')
                        case['output']['result'] = label
                        self.source.cases[cid] = case
        report = self.store.create_round('balanced', goals, fill=True)
        self.assertEqual(report['counts']['exposure'], {'0': 20, '1': 20})
        self.assertEqual(report['counts']['security'], {'0': 10, '1': 10})
        self.assertEqual(report['shortages'], [])
        for row in report['goal_coverage']['security'].values():
            self.assertEqual(row['selected'], {0: 2, 1: 2})
        self.assertEqual(len(report['goal_coverage']['exposure']), 19)
        self.assertEqual(goal_of({'task': 'task_abc_32_copy_file_arg'}), (18, 'copy_file'))
        snapshots = self.store.snapshots('balanced')
        self.assertEqual(len(snapshots), len({(s['kind'], s['path']) for s in snapshots}))

    def test_raw_goal_policy(self):
        from collections import defaultdict
        pools = defaultdict(list)
        goals = {'exposure': [g for g in range(1,33) if g != 11], 'security': SAFETY_GOALS}
        for kind, ids in goals.items():
            for g in ids:
                for label in (0,1):
                    n = 4
                    if kind == 'security' and label == 0:
                        n = int(g in (6,7))
                    if kind == 'exposure' and label == 1 and g in (2,4,5,7,9,10,12,13,20,21,22,23,32):
                        n = 0
                    for i in range(n):
                        pools[kind,g,label].append({'id':f'{kind}-{g}-{label}-{i}',
                            'path':f'{kind}-{g}-{label}-{i}', 'kind':kind, 'result':label,
                            'task':f'task_abc_{g}_goal', 'old':i < 2})
        def choose():
            return balanced_selection(copy.deepcopy(pools), goals, lambda c:c['old'], random.Random(42))
        selected = choose()
        self.assertEqual(selected, choose())
        ex = [c for c in selected if c['kind']=='exposure']
        safety = [c for c in selected if c['kind']=='security']
        self.assertEqual(Counter(c['result'] for c in ex), {0:20,1:20})
        counts = Counter(review_goal(c,'goal-balanced')[0] for c in ex)
        self.assertEqual(set(counts), set(goals['exposure']))
        self.assertEqual(Counter(counts.values()), {1:22,2:9})
        self.assertEqual(Counter(goal_of(c)[0] for c in safety), {g:4 for g in SAFETY_GOALS})
        self.assertEqual(Counter(c['result'] for c in safety), {0:2,1:18})
        self.assertTrue(all(c['old'] for c in ex))
        self.assertEqual(sum(c['old'] for c in safety),12)
        for key in list(pools):
            if key[0]=='exposure' and key[2]==1:
                pools[key]=[]
        with self.assertRaises(ValueError):choose()


if __name__=='__main__':unittest.main()
