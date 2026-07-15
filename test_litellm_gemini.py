"""Send one request to LiteLLM using a Hugging Face task model config."""

import argparse
import asyncio
import json
from pathlib import Path

from litellm import acompletion


CONFIG_DIR = Path(__file__).parent / "examples" / "hugging_face_task"
ORCHESTRATOR_CONFIG_PATH = CONFIG_DIR / "orchestrator_config.json"
JUDGE_CONFIG_PATH = CONFIG_DIR / "grading_settings.json"


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
        messages=[{"role": "user", "content": "What is 17 * 24?"}],
        vertex_project="apex-safety",
        vertex_location="global",
        **extra_args,
    )

    print(f"response: {response.choices[0].message.content}")
    print(f"usage: {response.usage}")


if __name__ == "__main__":
    asyncio.run(main())
