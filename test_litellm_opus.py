"""Send one tool-calling request to Claude Opus through LiteLLM."""

import argparse
import asyncio
import json

from litellm import acompletion


DEFAULT_MODEL = "anthropic/claude-opus-5"

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
        description="Test a Claude Opus tool call through LiteLLM."
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"LiteLLM model identifier (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--effort",
        default="max",
        choices=("low", "medium", "high", "xhigh", "max"),
        help="Reasoning effort to request (default: max).",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    extra_args = {
        "reasoning_effort": args.effort,
        "max_tokens": 16000,
        "tool_choice": "auto",
        "stream": False,
    }

    print(f"model: {args.model}")
    print(f"extra_args: {json.dumps(extra_args, ensure_ascii=False)}")

    response = await acompletion(
        model=args.model,
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
