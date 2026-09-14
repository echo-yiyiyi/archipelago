import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from judge_review import JudgeStore, register_judge_review


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / 'runs'
        self.task = self.runs / 'batch/model/tasks/example'
        self.task.mkdir(parents=True)
        self.grade = {'attack_success': 0, 'prompt_exposure': 1,
            'prompt_exposure_llm_judge': {'exposure': 1, 'message_numbers': [3], 'rationale': '<script>alert(1)</script>',
                'model': 'gemini-test', 'request': {'prompt': 'Compare reference and results.', 'input': {
                    'reference_prompts': ['Copy the file'], 'tool_results': [
                        {'message_number': 3, 'content': [{'type':'text','text':'Copy the file'}]},
                        {'message_number': 8, 'content': 'No instruction'}]}}},
            'attack_rules': {'llm_judge_1': {'passed': 0, 'rationale': 'Historical, no request'}}}
        self.write_grade()
        self.store = JudgeStore(roots=[self.runs], audit_roots=[], data_dir=self.root / 'data')
        self.app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        self.app.config['TESTING'] = True
        register_judge_review(self.app, self.store)
        self.client = self.app.test_client()

    def write_grade(self):
        (self.task / 'grades.json').write_text(json.dumps(self.grade))

    def case(self):
        return self.client.get('/api/judges').get_json()['cases'][0]

    def save(self, **values):
        case = self.case()
        body = {'version': case['version'], 'verdict':'0', 'message_numbers':[], 'notes':'Different judgment', **values}
        return self.client.post(f"/api/judges/{case['id']}/annotation", json=body, headers={'X-Judge-Review':'1'})

    def test_saved_exposure_and_no_historical_security(self):
        with patch('judge_review.subprocess.run', side_effect=AssertionError('must not reconstruct')):
            data = self.client.get('/api/judges').get_json()
            self.assertEqual(data['stats']['total'], 1)
            self.assertEqual(data['stats']['security'], 0)
            detail = self.client.get('/api/judges/'+data['cases'][0]['id']).get_json()
        self.assertEqual(detail['prompt_source'],'saved')
        self.assertEqual(detail['input']['tool_results'][1]['message_number'],8)
        self.assertNotIn('request',detail['output'])
        self.assertEqual(self.client.get('/judges').status_code,200)

    def test_security_rejudge_overrides_review_without_changing_attack_score(self):
        self.grade['attack_error'] = 'Old Azure 403'
        self.grade['security_llm_rejudge'] = {'llm_judge_1': {
            'passed': 1, 'model': 'vertex_ai/gemini-3.6-flash', 'error': None,
            'rationale': 'Matches', 'response': {'passed': 1, 'rationale': 'Matches'},
            'request': {'prompt': 'Compare.\n<reference>Task</reference>\n<candidate>Task</candidate>'}}}
        self.write_grade()
        data = self.client.get('/api/judges?kind=security').get_json()
        self.assertEqual(data['total'], 1)
        case = data['cases'][0]
        self.assertEqual(case['result'], 1)
        self.assertEqual(case['judge_model'], 'vertex_ai/gemini-3.6-flash')
        self.assertFalse(case['error'])
        detail = self.client.get('/api/judges/'+case['id']).get_json()
        self.assertEqual(detail['input']['sections'][0]['value'], 'Task')
        self.assertEqual(json.loads((self.task/'grades.json').read_text())['attack_success'], 0)
        payload = {'version': case['version'], 'verdict': '1', 'message_numbers': [],
                   'notes': 'Verified against the candidate'}
        saved = self.client.post('/api/judges/'+case['id']+'/annotation', json=payload,
                                 headers={'X-Judge-Review': '1'})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.store.annotations()[case['id']]['verdict'], '1')
        self.grade['security_llm_rejudge']['llm_judge_1']['passed'] = 0
        self.write_grade()
        stale = self.client.post('/api/judges/'+case['id']+'/annotation', json=payload,
                                 headers={'X-Judge-Review': '1'})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.store.annotations()[case['id']]['verdict'], '1')

    def test_excluded_case_keeps_grade_and_annotation(self):
        self.assertEqual(self.save().status_code, 200)
        before = (self.task / 'grades.json').read_bytes()
        (self.store.data_dir / 'excluded_cases.json').write_text(json.dumps([
            {'path': str(self.task / 'grades.json'), 'reason': 'Superseded input'}]))
        self.store.scan(force=True)
        self.assertEqual(self.client.get('/api/judges').get_json()['total'], 0)
        self.assertEqual(len(self.store.annotations()), 1)
        self.assertEqual((self.task / 'grades.json').read_bytes(), before)

    def test_new_security_record_and_readable_blocks(self):
        self.grade['attack_rules']['llm_judge_1']['request'] = {
            'prompt': 'Compare these.\n<original_user_prompt>Write a report</original_user_prompt>\n<candidate_emails>["Write a report"]</candidate_emails>',
            'model':'security-model','schema':{}}
        self.write_grade()
        data = self.client.get('/api/judges?kind=security').get_json()
        self.assertEqual(data['total'],1)
        detail = self.client.get('/api/judges/'+data['cases'][0]['id']).get_json()
        self.assertEqual(detail['input']['sections'][1]['value'],['Write a report'])
        self.assertEqual(detail['prompt'],'Compare these.')

    def test_annotation_persists_separately_and_exports(self):
        before = (self.task/'grades.json').read_bytes()
        self.assertEqual(self.save().status_code,200)
        self.assertEqual(self.client.get('/api/judges?review=disagreement').get_json()['total'],1)
        store2 = JudgeStore(roots=[self.runs], audit_roots=[], data_dir=self.root/'data')
        self.assertEqual(next(iter(store2.annotations().values()))['verdict'],'0')
        self.assertEqual((self.task/'grades.json').read_bytes(),before)
        exported = json.loads(self.client.get('/api/judges/export').data)
        self.assertEqual(exported[0]['annotation']['notes'],'Different judgment')
        case = self.case()
        self.assertEqual(self.client.delete('/api/judges/'+case['id']+'/annotation',headers={'X-Judge-Review':'1'}).status_code,200)
        self.assertEqual(self.client.get('/api/judges?review=unreviewed').get_json()['total'],1)

    def test_bad_numbers_and_stale_result(self):
        self.assertEqual(self.save(verdict='1',message_numbers=[2]).status_code,400)
        self.assertEqual(self.save(verdict='1',message_numbers=[True]).status_code,400)
        self.assertEqual(self.save(verdict='1',message_numbers=[3]).status_code,200)
        old = self.case()
        self.grade['prompt_exposure_llm_judge']['exposure'] = 0
        self.write_grade()
        response = self.client.post('/api/judges/'+old['id']+'/annotation',json={
            'version':old['version'],'verdict':'1'},headers={'X-Judge-Review':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.client.get('/api/judges?review=stale').get_json()['total'],0)
        self.assertEqual(self.client.get('/api/judges?review=reviewed').get_json()['total'],1)
        self.assertEqual(self.client.get('/api/judges?review=disagreement').get_json()['total'],1)
        self.grade['prompt_exposure_llm_judge']['request']['prompt'] = 'Revised judge instructions'
        self.write_grade()
        self.store.scan(force=True)
        self.assertEqual(self.client.get('/api/judges?review=stale').get_json()['total'],0)
        self.grade['prompt_exposure_llm_judge']['request']['input']['reference_prompts'] = ['Different instruction']
        self.write_grade()
        self.store.scan(force=True)
        self.assertEqual(self.client.get('/api/judges?review=stale').get_json()['total'],1)

    def test_filters_errors_paths_and_mutation_headers(self):
        self.assertEqual(self.client.get('/api/judges?q=notpresent').get_json()['total'],0)
        self.assertEqual(self.client.get('/api/judges?result=1').get_json()['total'],1)
        self.assertEqual(self.client.get('/api/judges?offset=bad').status_code,400)
        self.assertEqual(self.client.get('/api/judges/not-a-case').status_code,404)
        case = self.case()
        self.assertEqual(self.client.post('/api/judges/'+case['id']+'/annotation',json={'verdict':'1'}).status_code,400)

    def test_saved_campaign_payload(self):
        del self.grade['prompt_exposure_llm_judge']['request']
        self.write_grade()
        audit = self.root/'audit';audit.mkdir()
        (audit/'requests.json').write_text(json.dumps([{'path':str(self.task/'grades.json'),'hash':'abc','request':{
            'expected_prompts':['Reference from historical run'], 'tool_results':[{'message_number':10,'content':'Actual output'}]}}]))
        self.store.audit_roots = [audit]
        detail = self.client.get('/api/judges/'+self.case()['id']).get_json()
        self.assertEqual(detail['input_source'],'saved')
        self.assertEqual(detail['prompt_source'],'reconstructed')
        self.assertEqual(detail['input']['reference_prompts'],['Reference from historical run'])


if __name__ == '__main__':
    unittest.main()
