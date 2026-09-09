"""GPT-5.4 structured-output client for fixture content generation.

This module performs no request at import time. The caller must explicitly call
``generate_payload``; local tests can continue using fake payloads without an
API key or network access.
"""

from __future__ import annotations

import os
import logging
from typing import Any

from .prompt import build_file_generation_prompt
from .templates import parse_llm_json


DEFAULT_AZURE_ENDPOINT = "https://aoai-swedencentral-aii-02.openai.azure.com"
DEFAULT_MODEL = "aoai-swedencentral-aii-02-gpt-5.4-sol"
DEFAULT_KEY_VAULT_URL = "https://kv-aii.vault.azure.net"
DEFAULT_SECRET_NAME = "hinojoc-aoai-swedencentral-aii-02"
LOGGER = logging.getLogger(__name__)


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _schema(properties: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


STRING = {"type": "string"}
SCHEMAS: dict[str, dict[str, Any]] = {
    "html": _schema(
        {
            "file_name": STRING,
            "title": STRING,
            "heading": STRING,
            "keyword_summary": STRING,
            "reference_note": STRING,
        }
    ),
    "md": _schema(
        {
            "file_name": STRING,
            "title": STRING,
            "keywords": {"type": "array", "items": STRING},
            "reference_note": STRING,
        }
    ),
    "xlsx": _schema(
        {
            "file_name": STRING,
            "sheet_name": STRING,
            "rows": {
                "type": "array",
                "items": {
                    "type": "array",
                "items": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
            },
        }
    ),
    "txt": _schema(
        {
            "file_name": STRING,
            "title": STRING,
            "keyword_line": STRING,
            "reference_note": STRING,
        }
    ),
    "chat": _schema(
        {
            "group_name": STRING,
            "creator_name": STRING,
            "creator_email": STRING,
            "created_date": STRING,
            "text": STRING,
            "topic_id": STRING,
            "message_id": STRING,
        }
    ),
    "email": _schema(
        {
            "sender_name": STRING,
            "sender_email": STRING,
            "recipient_email": STRING,
            "date": STRING,
            "message_id": STRING,
            "subject": STRING,
            "body": STRING,
        }
    ),
    "calendar": _schema(
        {
            "file_name": STRING,
            "uid": STRING,
            "start": STRING,
            "end": STRING,
            "summary": STRING,
            "description": STRING,
            "location": STRING,
        }
    ),
    "py": _schema({"file_name": STRING}),
    "pyc": _schema({"file_name": STRING}),
    "elf": _schema({"file_name": STRING}),
}


def _setting(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def get_azure_api_key() -> str:
    """Read the existing Azure OpenAI key from the configured Key Vault."""
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    credential = DefaultAzureCredential()
    client = SecretClient(
        vault_url=_setting("AZURE_KEY_VAULT_URL", DEFAULT_KEY_VAULT_URL),
        credential=credential,
    )
    secret = client.get_secret(
        _setting("AZURE_OPENAI_KEY_SECRET", DEFAULT_SECRET_NAME)
    )
    if not secret.value:
        raise RuntimeError("Azure OpenAI Key Vault secret is empty")
    return secret.value


def build_client() -> Any:
    """Build an Azure OpenAI client using the existing Key Vault credential."""
    from openai import OpenAI

    endpoint = _setting("AZURE_OPENAI_ENDPOINT", DEFAULT_AZURE_ENDPOINT).rstrip("/")
    return OpenAI(
        api_key=get_azure_api_key(),
        base_url=f"{endpoint}/openai/v1/",
    )


def generate_structured_payload(
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    *,
    client: Any | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int = 8192,
) -> dict[str, Any]:
    """Call the configured model with any strict JSON schema.

    This is the shared structured-output primitive used by fixture generation
    and by other benchmark configuration generators.
    """
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    if not schema_name.strip():
        raise ValueError("schema_name must not be empty")

    active_client = client or build_client()
    request: dict[str, Any] = {
        "model": _setting("AZURE_OPENAI_MODEL", DEFAULT_MODEL),
        "input": prompt,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
        "max_output_tokens": max_output_tokens,
    }
    if reasoning_effort and reasoning_effort.lower() != "auto":
        request["reasoning"] = {"effort": reasoning_effort}

    for attempt in range(3):
        response = active_client.responses.create(**request)
        status = _field(response, "status")
        reason = _field(_field(response, "incomplete_details"), "reason")
        text = _field(response, "output_text", "") or ""
        refused = any(
            _field(content, "type") == "refusal"
            for item in (_field(response, "output", []) or [])
            for content in (_field(item, "content", []) or [])
        )
        diagnostic = (
            f"schema={schema_name}, response_id={_field(response, 'id')}, "
            f"status={status}, reason={reason}, refused={refused}, "
            f"max_output_tokens={request['max_output_tokens']}, "
            f"output_tokens={_field(_field(response, 'usage'), 'output_tokens')}"
        )
        if not refused and status in (None, "completed") and text.strip():
            payload = parse_llm_json(text)
            if not isinstance(payload, dict):
                raise ValueError("structured output must be a JSON object")
            return payload
        exhausted = status == "incomplete" and reason == "max_output_tokens"
        empty = status in (None, "completed") and not text.strip()
        if not refused and attempt < 2 and (exhausted or empty):
            if exhausted:
                # The API budget includes reasoning. Grow only after confirmed
                # exhaustion, bounded to 32K (or the caller's larger budget).
                request["max_output_tokens"] = min(
                    max(max_output_tokens, 32768), max(2048, request["max_output_tokens"] * 2)
                )
            LOGGER.warning("Retrying structured generation (%s), attempt %s/3", diagnostic, attempt + 2)
            continue
        raise RuntimeError(f"model returned no complete structured output: {diagnostic}")


def generate_payload(
    file_type: str,
    keywords: list[str],
    *,
    client: Any | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Call GPT-5.4 with strict structured output and return a Python dict.

    By default ``reasoning_effort`` is omitted so GPT-5.4 selects its service
    default. Set it explicitly only when a deployment requires a fixed level.
    """
    normalized_type = file_type.lower().lstrip(".")
    if normalized_type not in SCHEMAS:
        supported = ", ".join(SCHEMAS)
        raise ValueError(
            f"Unsupported file type {file_type!r}; expected one of: {supported}"
        )
    if not keywords:
        raise ValueError("keywords must not be empty")

    return generate_structured_payload(
        build_file_generation_prompt(normalized_type, keywords),
        f"{normalized_type}_fixture_payload",
        SCHEMAS[normalized_type],
        client=client,
        reasoning_effort=reasoning_effort,
    )
