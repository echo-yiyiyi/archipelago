"""GPT-5.4 structured-output client for fixture content generation.

This module performs no request at import time. The caller must explicitly call
``generate_payload``; local tests can continue using fake payloads without an
API key or network access.
"""

from __future__ import annotations

import os
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from openai import OpenAI

from .prompt import build_file_generation_prompt
from .templates import parse_llm_json


DEFAULT_AZURE_ENDPOINT = "https://aoai-swedencentral-aii-02.openai.azure.com"
DEFAULT_MODEL = "aoai-swedencentral-aii-02-gpt-5.4-sol"
DEFAULT_KEY_VAULT_URL = "https://kv-aii.vault.azure.net"
DEFAULT_SECRET_NAME = "hinojoc-aoai-swedencentral-aii-02"


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


def build_client() -> OpenAI:
    """Build an Azure OpenAI client using the existing Key Vault credential."""
    endpoint = _setting("AZURE_OPENAI_ENDPOINT", DEFAULT_AZURE_ENDPOINT).rstrip("/")
    return OpenAI(
        api_key=get_azure_api_key(),
        base_url=f"{endpoint}/openai/v1/",
    )


def generate_payload(
    file_type: str,
    keywords: list[str],
    *,
    client: OpenAI | None = None,
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

    active_client = client or build_client()
    model = _setting("AZURE_OPENAI_MODEL", DEFAULT_MODEL)
    request: dict[str, Any] = {
        "model": model,
        "input": build_file_generation_prompt(normalized_type, keywords),
        "text": {
            "format": {
                "type": "json_schema",
                "name": f"{normalized_type}_fixture_payload",
                "strict": True,
                "schema": SCHEMAS[normalized_type],
            }
        },
        "max_output_tokens": 8192,
    }
    if reasoning_effort and reasoning_effort.lower() != "auto":
        request["reasoning"] = {"effort": reasoning_effort}

    response = active_client.responses.create(**request)
    if not response.output_text:
        raise RuntimeError("GPT-5.4 returned no structured output text")
    return parse_llm_json(response.output_text)
