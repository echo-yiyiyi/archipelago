"""Test an OpenAI-compatible model configuration through LiteLLM."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from litellm import acompletion


TOOLS = [
    {
        "type": "function",
        "function": {
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
        },
    }
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test an OpenAI-compatible model config through LiteLLM."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a model configuration JSON file.",
    )
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text())
    required = ("model", "api_base", "api_key_env")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(
            f"Config {path} is missing required fields: {', '.join(missing)}"
        )
    return config


def get_api_key(config: dict[str, Any]) -> str:
    env_name = config["api_key_env"]
    api_key = os.getenv(env_name)
    if not api_key:
        raise RuntimeError(f"Set {env_name} before running this script")
    return api_key


async def main() -> None:
    args = parse_args()
    config_path = args.config.resolve()
    config = load_config(config_path)
    extra_args = config.get("extra_args", {})

    print(f"config: {config_path}")
    print(f"model: {config['model']}")
    print(f"api_base: {config['api_base']}")
    print(f"api_key_env: {config['api_key_env']}")
    print(f"extra_args: {json.dumps(extra_args, ensure_ascii=False)}")

    response = await acompletion(
        model=config["model"],
        api_base=config["api_base"],
        api_key=get_api_key(config),
        messages=[
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

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    print(f"message: {message}\n")
    print(f"explanation: {message.content}")
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
