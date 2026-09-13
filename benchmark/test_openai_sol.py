#!/usr/bin/env python3
"""Check the Sol config through the actual agent/LiteLLM transport; --live uses one API call."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP', 'True')
REPO = Path(__file__).resolve().parent.parent
# Avoid benchmark/runner shadowing the agent's namespace package.
sys.path[:] = [str(REPO / 'agents')] + [p for p in sys.path if Path(p).resolve() != REPO / 'benchmark']

CONFIG = REPO / 'benchmark/orchestrator_config_gpt_sol_high.json'
TOOLS = [{'type': 'function', 'function': {'name': 'report_result', 'description': 'Report the calculation result.',
          'parameters': {'type': 'object', 'properties': {'result': {'type': 'integer'}},
                         'required': ['result'], 'additionalProperties': False}}}]


async def check(live, config_path=CONFIG):
    import httpx
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
    from runner.utils.llm import generate_response
    config = json.loads(config_path.read_text())
    assert config['model'].startswith('openai/responses/')
    model_id = config['model'].removeprefix('openai/responses/')
    assert 'azure_key_vault' not in config
    calls = []

    async def request(extra=None):
        # One attempt: test transport and response conversion without retry/backoff.
        response = await generate_response.__wrapped__(
            model=config['model'], messages=[{'role': 'user', 'content': 'Calculate 1 + 1 and call report_result with the answer.'}],
            tools=TOOLS, llm_response_timeout=30,
            extra_args={**config['extra_args'], 'max_tokens': 1024, 'num_retries': 0,
                        **(extra or {})})
        tools = response.choices[0].message.tool_calls or []
        assert len(tools) == 1 and tools[0].function.name == 'report_result'
        assert json.loads(tools[0].function.arguments) == {'result': 2}

    if live:
        await request()
    else:
        def handler(request):
            body = json.loads(request.content)
            assert str(request.url) == 'https://api.openai.com/v1/responses'
            assert request.headers['authorization'] == 'Bearer offline-test-key'
            assert body['model'] == model_id
            assert body['reasoning']['effort'] == 'high'
            assert body['tools'][0]['name'] == 'report_result'
            calls.append(body)
            return httpx.Response(200, json={
                'id': 'resp_test', 'object': 'response', 'created_at': 1, 'status': 'completed',
                'model': model_id, 'output': [{'id': 'fc_test', 'call_id': 'call_test',
                'type': 'function_call', 'name': 'report_result', 'arguments': '{"result":2}', 'status': 'completed'}],
                'parallel_tool_calls': True, 'usage': {'input_tokens': 10, 'output_tokens': 10, 'total_tokens': 20}})
        async def mock_post(self, url, data=None, json=None, headers=None, content=None, **kwargs):
            body = content if content is not None else data
            request = httpx.Request('POST', url, headers=headers, json=json, content=body)
            response = handler(request)
            response.request = request
            return response
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-test-key'}), \
             patch.object(AsyncHTTPHandler, 'post', mock_post):
            await request({'api_key': 'offline-test-key'})
        assert len(calls) == 1
    print(('LIVE' if live else 'OFFLINE TRANSPORT') + f' PASS: {model_id}, OpenAI Responses, high reasoning, tool result=2')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--config', type=Path, default=CONFIG)
    args = parser.parse_args()
    if args.live and not os.environ.get('OPENAI_API_KEY'):
        parser.error('OPENAI_API_KEY is not set; live API access cannot be tested.')
    asyncio.run(asyncio.wait_for(check(args.live, args.config), timeout=45))


if __name__ == '__main__':
    main()
