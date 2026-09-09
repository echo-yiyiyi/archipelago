from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from benchmark.generate_attack_file.api import generate_structured_payload


def response(text='', status='completed', reason=None, **kwargs):
    return SimpleNamespace(output_text=text, status=status,
                           incomplete_details=SimpleNamespace(reason=reason), **kwargs)


class StructuredApiTests(unittest.TestCase):
    def call(self, responses, **kwargs):
        client = SimpleNamespace(responses=SimpleNamespace(create=Mock(side_effect=responses)))
        result = generate_structured_payload('Generate a number', 'value', {}, client=client, **kwargs)
        return result, client.responses.create

    def test_success_does_not_retry(self):
        result, create = self.call([response('{"value": 5}')])
        self.assertEqual(result, {'value': 5})
        self.assertEqual(create.call_count, 1)

    def test_empty_reasoning_and_partial_json_retry_with_more_tokens(self):
        for text in ('', '{"value":', '{"value": 999}'):
            result, create = self.call([
                response(text, 'incomplete', 'max_output_tokens'), response('{"value": 5}')
            ], max_output_tokens=128, reasoning_effort='low')
            self.assertEqual(result, {'value': 5})
            self.assertEqual([c.kwargs['max_output_tokens'] for c in create.call_args_list], [128, 2048])
            self.assertEqual(create.call_args.kwargs['reasoning'], {'effort': 'low'})

    def test_empty_completed_response_retries_without_budget_increase(self):
        _, create = self.call([response('  '), response('{"value": 5}')], max_output_tokens=2048)
        self.assertEqual([c.kwargs['max_output_tokens'] for c in create.call_args_list], [2048, 2048])

    def test_retry_limit_preserves_diagnostics(self):
        create = Mock(return_value=response('', 'incomplete', 'max_output_tokens', id='resp_test'))
        client = SimpleNamespace(responses=SimpleNamespace(create=create))
        with self.assertRaisesRegex(RuntimeError, 'response_id=resp_test, status=incomplete, reason=max_output_tokens'):
            generate_structured_payload('test', 'value', {}, client=client, max_output_tokens=2048)
        self.assertEqual(create.call_count, 3)

    def test_refusal_and_other_failures_do_not_retry(self):
        for failed in (response('', output=[{'content': [{'type': 'refusal'}]}]),
                       response('', 'incomplete', 'content_filter'), response('', 'failed')):
            create = Mock(return_value=failed)
            with self.assertRaises(RuntimeError):
                generate_structured_payload('test', 'value', {}, client=SimpleNamespace(responses=SimpleNamespace(create=create)))
            self.assertEqual(create.call_count, 1)

    def test_malformed_completed_json_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            self.call([response('not JSON')])


if __name__ == '__main__':
    unittest.main()
