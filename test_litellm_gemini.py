"""Send one tool-calling request through a LiteLLM model config."""

import argparse
import asyncio
import json
from pathlib import Path

from litellm import acompletion


CONFIG_DIR = Path(__file__).parent / "examples" / "hugging_face_task"
ORCHESTRATOR_CONFIG_PATH = CONFIG_DIR / "orchestrator_config.json"
JUDGE_CONFIG_PATH = CONFIG_DIR / "grading_settings.json"

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
        description="Test the orchestrator or judge LiteLLM configuration."
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Test grading_settings.json instead of orchestrator_config.json.",
    )
    return parser.parse_args()


def load_model_config(judge: bool) -> tuple[Path, str, dict]:
    config_path = JUDGE_CONFIG_PATH if judge else ORCHESTRATOR_CONFIG_PATH
    config = json.loads(config_path.read_text())

    if judge:
        model = config["llm_judge_model"]
        extra_args = config.get("llm_judge_extra_args", {})
    else:
        model = config["model"]
        extra_args = config.get("extra_args", {})

    return config_path, model, extra_args


async def main() -> None:
    args = parse_args()
    config_path, model, extra_args = load_model_config(args.judge)

    print(f"config: {config_path}")
    print(f"model: {model}")
    print(f"extra_args: {json.dumps(extra_args, ensure_ascii=False)}")

    response = await acompletion(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "What is the current weather in Riyadh? explain the reason of tool calls before call it.",
            }
        ],
        tools=TOOLS,
        vertex_project="apex-safety",
        vertex_location="global",
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

    # assert message.content and message.content.strip(), (
    #     "Model did not explain before calling the tool"
    # )
    # assert tool_calls, "Model did not call a tool"
    # assert tool_calls[0].function.name == "get_weather"


if __name__ == "__main__":
    asyncio.run(main())
