"""Structured security judgments with captured inputs and outputs."""
import json
import os

from .judge_trace import record_judge

DEFAULT_MODEL = "vertex_ai/gemini-3.6-flash"


def responses_json(*, prompt, schema_name, schema, max_output_tokens=1024):
    model = (os.environ.get("SECURITY_JUDGE_MODEL")
             or os.environ.get("AZURE_SECURITY_JUDGE_MODEL") or DEFAULT_MODEL)
    if not model.startswith("vertex_ai/"):
        from .azure_openai import build_client, responses_json as azure_json
        return azure_json(client=build_client(), prompt=prompt, schema_name=schema_name,
                          schema=schema, model=model, max_output_tokens=max_output_tokens)

    from litellm import completion
    trace = {"model": model, "prompt": prompt, "schema_name": schema_name,
             "schema": schema, "max_output_tokens": max_output_tokens}
    raw = None
    try:
        response = completion(
            model=model,
            vertex_project=os.environ.get("VERTEXAI_PROJECT") or "apex-safety",
            vertex_location=os.environ.get("VERTEXAI_LOCATION") or "global",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": {
                "name": schema_name, "strict": True, "schema": schema}},
            max_tokens=max_output_tokens, timeout=180, num_retries=2,
        )
        raw = response.choices[0].message.content
        if response.choices[0].finish_reason != "stop":
            raise ValueError("Security judge did not finish a complete response")
        parsed = json.loads(raw)
        from jsonschema import validate
        validate(parsed, schema)
    except Exception as error:
        record_judge(trace, raw_output=raw, error=f"{type(error).__name__}: {error}")
        raise
    record_judge(trace, response=parsed, raw_output=raw)
    return parsed
