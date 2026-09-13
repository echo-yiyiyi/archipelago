"""Check routing and model selection without network access or real keys."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from benchmark.utils import azure_openai, generation_provider
from benchmark.generate_attack_file import api


class GenerationProviderTests(unittest.TestCase):
    @patch.dict(os.environ, {'BENCHMARK_GENERATION_PROVIDER':'openai',
                             'OPENAI_API_KEY':'test-only',
                             'OPENAI_GENERATION_MODEL':'gpt-5.6-sol',
                             'AZURE_OPENAI_MODEL':'azure-deployment'}, clear=True)
    def test_both_clients_use_public_endpoint_without_keyvault(self):
        with patch('openai.OpenAI') as client, patch.object(azure_openai, 'get_azure_api_key') as vault:
            azure_openai.build_client()
            api.build_client()
            self.assertEqual(client.call_count, 2)
            for call in client.call_args_list:
                self.assertEqual(call.kwargs['base_url'], 'https://api.openai.com/v1')
                self.assertEqual(call.kwargs['api_key'], 'test-only')
            vault.assert_not_called()
        create = Mock(return_value=SimpleNamespace(output_text='{"value":1}', status='completed'))
        fake = SimpleNamespace(responses=SimpleNamespace(create=create))
        azure_openai.responses_json(client=fake, prompt='Return 1', schema_name='value', schema={})
        api.generate_structured_payload('Return 1', 'value', {}, client=fake)
        self.assertTrue(all(c.kwargs['model']=='gpt-5.6-sol' for c in create.call_args_list))

    @patch.dict(os.environ, {'BENCHMARK_GENERATION_PROVIDER':'openai'}, clear=True)
    def test_missing_key_fails_before_network(self):
        with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
            generation_provider.openai_client()

    @patch.dict(os.environ, {}, clear=True)
    def test_azure_remains_default(self):
        self.assertEqual(generation_provider.provider(), 'azure')
        self.assertEqual(generation_provider.model_name('existing-model'), 'existing-model')
