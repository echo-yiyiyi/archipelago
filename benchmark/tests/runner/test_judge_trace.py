import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from benchmark.utils.azure_openai import responses_json
from benchmark.utils.judge_trace import capture_judges
from benchmark.runner.security_check import check_security


class JudgeTraceTests(unittest.TestCase):
    def client(self, value):
        return SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs:SimpleNamespace(output_text=json.dumps(value))))

    def test_dispatch_preserves_actual_request_response(self):
        def checker(snapshot, config):
            value=responses_json(client=self.client({'passed':1,'rationale':'Matched'}),prompt='Exact reference and candidate',
                                 schema_name='example',schema={'type':'object'},model='judge-model')
            return {'attack_success':value['passed'],'attack_rules':{'llm_judge_1':value}}
        with patch.dict('benchmark.runner.security_check.SECURITY_CHECKERS',{'test_trace':checker}):
            result=check_security(inject_goal='test_trace',final_snapshot='unused',attack_config={})
        saved=result['attack_rules']['llm_judge_1']
        self.assertEqual(saved['request']['prompt'],'Exact reference and candidate')
        self.assertEqual(saved['response'],{'passed':1,'rationale':'Matched'})
        self.assertEqual(saved['model'],'judge-model')
        self.assertNotIn('client',saved['request'])

    def test_failures_record_and_reraise(self):
        def fail(**kwargs): raise RuntimeError('Network unavailable')
        client=SimpleNamespace(responses=SimpleNamespace(create=fail))
        with capture_judges() as traces:
            with self.assertRaises(RuntimeError):
                responses_json(client=client,prompt='Original input',schema_name='test',schema={},model='test')
        self.assertIn('Network unavailable',traces[0]['error'])
        self.assertEqual(traces[0]['request']['prompt'],'Original input')

    def test_parallel_requests_do_not_share_trace_context(self):
        def work(i):
            with capture_judges() as traces:
                responses_json(client=self.client({'passed':i}),prompt=str(i),schema_name='test',schema={},model='test')
            return traces
        with ThreadPoolExecutor(max_workers=4) as pool: rows=list(pool.map(work,range(8)))
        for i,row in enumerate(rows):
            self.assertEqual(len(row),1)
            self.assertEqual(row[0]['request']['prompt'],str(i))

if __name__=='__main__':unittest.main()
