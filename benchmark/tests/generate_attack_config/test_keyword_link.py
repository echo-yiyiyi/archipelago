"""URL generation keeps a simple remote schema and strict local validation."""
import unittest
from unittest.mock import patch

from benchmark.generate_attack_config.prompt import common


class KeywordLinkTests(unittest.TestCase):
    def generate(self, value, **kwargs):
        with patch.object(common, 'generate_structured_payload',
                          return_value={'attacker_link': value}) as call:
            result = common.generate_keyword_link(['Quarterly review'], client=object(), **kwargs)
        return result, call

    def test_plain_remote_schema_preserves_generated_link(self):
        value = 'https://review.example/quarterly-review'
        result, call = self.generate(value)
        self.assertEqual(result, value)
        self.assertEqual(call.call_args.args[2]['properties']['attacker_link'], {'type': 'string'})
        self.assertEqual(call.call_args.args[2]['required'], ['attacker_link'])
        self.assertFalse(call.call_args.args[2]['additionalProperties'])

    def test_invalid_urls_fail_locally(self):
        for value in [None, 42, 'https://review.example/single',
                      'https://review.example/a-b?x=1', 'https://review.example/a-b#fragment',
                      'https://user:pass@review.example/a-b', 'https://review.example:8080/a-b',
                      'https://review.example/a/b-c', 'ftp://review.example/a-b',
                      'https://review.example/Upper-case',
                      'https://' + 'a'*90 + '.example/a-b']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.generate(value)

    def test_http_conversion_and_suffix_rules(self):
        result, _ = self.generate('https://review.example/quarterly-review', require_http=True)
        self.assertEqual(result, 'http://review.example/quarterly-review')
        self.generate('https://review.example/quarterly-review-download', path_suffix='download')
        with self.assertRaises(ValueError):
            self.generate('https://review.example/quarterly-review', path_suffix='download')


if __name__ == '__main__':
    unittest.main()
