"""Send one GPT-5.6 xHigh tool-calling request to Azure via LiteLLM."""

import argparse
import asyncio
import json

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from litellm import aresponses


AZURE_ENDPOINT = "https://aoai-swedencentral-aii-02.openai.azure.com/"
DEFAULT_DEPLOYMENT = "aoai-swedencentral-aii-02-gpt-5.6-sol"
KEY_VAULT_URL = "https://kv-aii.vault.azure.net"
SECRET_NAME = "hinojoc-aoai-swedencentral-aii-02"

TOOLS = [
    {
        "type": "function",
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "The city whose weather should be queried.",
                }
            },
            "required": ["city"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test GPT-5.6 xHigh tool calling on Azure through LiteLLM."
    )
    parser.add_argument(
        "--deployment",
        default=DEFAULT_DEPLOYMENT,
        help=f"Azure OpenAI deployment name (default: {DEFAULT_DEPLOYMENT}).",
    )
    return parser.parse_args()


def get_api_key() -> str:
    credential = DefaultAzureCredential()
    secret_client = SecretClient(vault_url=KEY_VAULT_URL, credential=credential)
    secret = secret_client.get_secret(SECRET_NAME)
    if not secret.value:
        raise RuntimeError(f"Key Vault secret {SECRET_NAME!r} has no value")
    return secret.value


async def main() -> None:
    args = parse_args()
    model = f"azure/{args.deployment}"
    extra_args = {
        "reasoning": {"effort": "xhigh"},
        "max_output_tokens": 16384,
        "tool_choice": "required",
        "stream": False,
    }

    print(f"model: {model}")
    print(f"azure_endpoint: {AZURE_ENDPOINT}")
    print("api_version: v1 (implicit)")
    print(f"extra_args: {json.dumps(extra_args, ensure_ascii=False)}")

    response = await aresponses(
        model=model,
        api_base=AZURE_ENDPOINT,
        api_key=get_api_key(),
        input=[
            {
                "role": "user",
                "content": (
                    "What is the current weather in Riyadh? "
                    "Explain why you need the tool before calling it."
                ),
            }
        ],
        tools=TOOLS,
        **extra_args,
    )

    tool_calls = [item for item in response.output if item.type == "function_call"]
    print(f"explanation: {response.output_text}")
    print(
        "tool_calls: "
        + json.dumps(
            [call.model_dump() for call in tool_calls],
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"usage: {response.usage}")


if __name__ == "__main__":
    asyncio.run(main())
