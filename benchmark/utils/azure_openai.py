"""Small, injectable Azure OpenAI Responses API helpers.

Imports that require Azure/OpenAI packages are intentionally lazy so local
tests can use a fake client without credentials, network access, or SDK setup.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from .generation_provider import provider, model_name, openai_client

DEFAULT_AZURE_ENDPOINT = "https://aoai-swedencentral-aii-02.openai.azure.com"
DEFAULT_MODEL = "aoai-swedencentral-aii-02-gpt-5.6-sol"
DEFAULT_KEY_VAULT_URL = "https://kv-aii.vault.azure.net"
DEFAULT_SECRET_NAME = "hinojoc-aoai-swedencentral-aii-02"


def setting(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def get_azure_api_key() -> str:
    """Read the existing Azure OpenAI key from Key Vault."""
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    client = SecretClient(
        vault_url=setting("AZURE_KEY_VAULT_URL", DEFAULT_KEY_VAULT_URL),
        credential=DefaultAzureCredential(),
    )
    secret = client.get_secret(setting("AZURE_OPENAI_KEY_SECRET", DEFAULT_SECRET_NAME))
    if not secret.value:
        raise RuntimeError("Azure OpenAI Key Vault secret is empty")
    return secret.value


def build_client() -> Any:
    """Build an Azure OpenAI client using the repository's Key Vault setup."""
    if provider() == 'openai':
        return openai_client()
    from openai import OpenAI

    endpoint = setting("AZURE_OPENAI_ENDPOINT", DEFAULT_AZURE_ENDPOINT).rstrip("/")
    return OpenAI(
        api_key=get_azure_api_key(),
        base_url=f"{endpoint}/openai/v1/",
    )


def parse_json_text(text: str) -> Any:
    """Parse plain or fenced JSON returned by a Responses API call."""
    value = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, re.DOTALL)
    if fenced:
        value = fenced.group(1)
    return json.loads(value)


def responses_json(
    *,
    client: Any,
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    model: str | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int = 1024,
) -> Any:
    """Call Responses API with strict JSON-schema output and parse the result."""
    request: dict[str, Any] = {
        "model": model or model_name(DEFAULT_MODEL),
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
    response = client.responses.create(**request)
    output_text = getattr(response, "output_text", None)
    if not output_text:
        raise RuntimeError("Responses API returned no output_text")
    return parse_json_text(output_text)
