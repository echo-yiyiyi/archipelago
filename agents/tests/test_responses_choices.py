import asyncio
from unittest.mock import AsyncMock

import pytest
from litellm import ModelResponse
from litellm.completion_extras.litellm_responses_transformation.transformation import (
    LiteLLMResponsesTransformationHandler,
)
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseReasoningItem,
)

from runner.utils import llm


def split_response():
    output = [
        ResponseReasoningItem(
            id="rs_test", type="reasoning", encrypted_content="encrypted-test",
            summary=[{"type": "summary_text", "text": "Check live weather."}],
        ),
        ResponseOutputMessage(
            id="msg_test", type="message", role="assistant", status="completed",
            content=[{"type": "output_text", "text": "I will check the weather.", "annotations": []}],
        ),
        *[
            ResponseFunctionToolCall(
                id=f"fc_{i}", call_id=f"call_{i}", type="function_call",
                name="get_weather", arguments=f'{{"city":"{city}"}}', status="completed",
            )
            for i, city in enumerate(("Riyadh", "London"))
        ],
    ]
    choices = LiteLLMResponsesTransformationHandler._convert_response_output_to_choices(output)
    return ModelResponse(choices=choices, usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30})


@pytest.mark.parametrize("model", ["openai/responses/gpt-6-astra", "azure/responses/deployment-gpt-5.6"])
def test_generate_response_keeps_text_and_all_tool_calls(monkeypatch, model):
    raw = split_response()
    assert not raw.choices[0].message.tool_calls
    monkeypatch.setattr(llm, "acompletion", AsyncMock(return_value=raw))
    monkeypatch.setattr(llm, "_emit_llm_latency_baseline", lambda **kwargs: None)
    response = asyncio.run(llm.generate_response(
        model=model, messages=[{"role": "user", "content": "Check weather"}],
        tools=[], llm_response_timeout=10, extra_args={"reasoning": {"effort": "low"}},
    ))
    assert len(response.choices) == 1
    message = response.choices[0].message
    assert message.content == "I will check the weather."
    assert [call.model_dump() for call in message.tool_calls] == [
        call.model_dump() for call in raw.choices[1].message.tool_calls
    ]
    assert [call.function.arguments for call in message.tool_calls] == [
        '{"city":"Riyadh"}', '{"city":"London"}',
    ]
    assert message.reasoning_content == raw.choices[0].message.reasoning_content
    assert message.reasoning_items == raw.choices[0].message.reasoning_items
    assert response.choices[0].finish_reason == "tool_calls"
    assert response.usage == raw.usage
    assert response.id == raw.id
    assert not raw.choices[0].message.tool_calls  # Original response stays intact.


@pytest.mark.parametrize("model", ["openai/gpt-6-astra", "vertex_ai/gemini-3.6-flash", "anthropic/claude-sonnet-5"])
def test_chat_completion_alternatives_are_not_merged(model):
    raw = ModelResponse(choices=[
        {"index": i, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        for i, text in enumerate(("First answer", "Alternative answer"))
    ])
    assert llm._merge_responses_choices(raw, model) is raw


def test_single_responses_choice_is_unchanged():
    raw = ModelResponse(choices=[split_response().choices[1]])
    assert llm._merge_responses_choices(raw, "openai/responses/gpt-6-astra") is raw


def test_astra_config_passes_real_litellm_validation_without_dropping_reasoning():
    import json
    from pathlib import Path
    from litellm.utils import get_optional_params

    config = json.loads((Path(__file__).resolve().parents[2] /
                         'benchmark/orchestrator_config_gpt_astra_low.json').read_text())
    extra = llm.responses_args_to_completions(config['extra_args'])
    # This is the real validation that rejected the production request; do not
    # mock acompletion or replace provider capabilities in this regression.
    params = get_optional_params(
        model='gpt-6-astra', custom_llm_provider='openai',
        reasoning_effort=extra['reasoning_effort'],
        allowed_openai_params=extra.get('allowed_openai_params'),
        drop_params=False,
    )
    assert params['reasoning_effort'] == 'low'
    handler = LiteLLMResponsesTransformationHandler()
    assert handler._map_reasoning_effort(params['reasoning_effort']) == {'effort': 'low'}
