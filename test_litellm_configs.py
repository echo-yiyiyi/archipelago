"""Smoke-test model configs with one weather tool-call request per model.

Run without arguments to test Gemini 3.6/3.7/3.8, Astra low, and Sonnet 5.
Credentials use the normal provider environment or the config's Azure Key Vault.
This only requests a tool call; it does not execute a weather service.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIGS = [
    ROOT / "benchmark" / f"orchestrator_config_{name}.json"
    for name in ("gemini36", "gemini37", "gemini38", "gpt_astra_low", "sonnet5")
]
PROMPT = (
    "What is the current weather in Riyadh? "
    "Explain why you need the tool before calling it."
)


def azure_key(vault: dict) -> str:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    with DefaultAzureCredential() as credential:
        with SecretClient(vault_url=vault["vault_url"], credential=credential) as client:
            value = client.get_secret(vault["secret_name"]).value
    if not value:
        raise RuntimeError("Azure Key Vault returned an empty API key")
    return value


async def request(config: dict, timeout: float) -> dict:
    sys.path.insert(0, str(ROOT / "agents"))
    from runner.utils.llm import generate_response
    from test_litellm_gemini import TOOLS

    model = config["model"]
    extra = dict(config.get("extra_args", {}))
    if extra.get("stream"):
        raise ValueError("This smoke test requires stream=false")
    extra.update(timeout=timeout, num_retries=0)
    secret = None
    try:
        if config.get("azure_key_vault"):
            secret = await asyncio.to_thread(azure_key, config["azure_key_vault"])
            extra["api_key"] = secret
        messages = [{"role": "user", "content": PROMPT}]
        # Use the production agent path, including LiteLLM parameter validation
        # and Responses-to-Chat conversion. A native aresponses smoke test can
        # pass while this path fails. Disable only the outer retry loop here.
        response = await generate_response.__wrapped__(
            model=model, messages=messages, tools=TOOLS,
            llm_response_timeout=timeout, extra_args=extra,
        )
        message = response.choices[0].message
        content = message.content
        calls = [
            {"name": call.function.name, "arguments": call.function.arguments}
            for call in message.tool_calls or []
        ]
        valid = False
        for call in calls:
            try:
                arguments = json.loads(call["arguments"])
                valid |= call["name"] == "get_weather" and arguments == {"city": "Riyadh"}
            except (TypeError, ValueError):
                pass
        return {
            "status": "PASS" if valid else "FAIL",
            "api_ok": True,
            "valid_tool_call": valid,
            "has_explanation": bool(content and content.strip()),
            "explanation": content,
            "tool_calls": calls,
            "usage": response.usage.model_dump() if response.usage else None,
        }
    except Exception as exc:
        detail = str(exc)
        for value in (secret, extra.get("api_key")):
            if value:
                detail = detail.replace(value, "[REDACTED]")
        raise RuntimeError(f"{type(exc).__name__}: {detail}") from None


async def run(args: argparse.Namespace) -> list[dict]:
    results = []
    for path in args.configs:
        started = time.monotonic()
        result = {"config": str(path.resolve())}
        print(f"\nTesting {path.name}", flush=True)
        try:
            config = json.loads(path.read_text())
            result["model"] = config["model"]
            if not isinstance(config["model"], str) or not config["model"]:
                raise ValueError("model must be a nonempty string")
            if not isinstance(config.get("extra_args", {}), dict):
                raise ValueError("extra_args must be an object")
            if args.dry_run:
                result.update(status="DRY_RUN", extra_args=config.get("extra_args", {}))
            else:
                result.update(await asyncio.wait_for(request(config, args.timeout), args.timeout))
        except Exception as exc:
            result.update(status="ERROR", error=f"{type(exc).__name__}: {exc}")
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)

    print("\nSummary (PASS = correct weather tool call; explanation is reported separately)")
    for result in results:
        print(
            f"{result['status']:8} {Path(result['config']).name} "
            f"explanation={result.get('has_explanation', '-')} "
            f"{result['elapsed_seconds']}s"
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        print(f"Results saved to {args.output}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configs", nargs="*", type=Path, default=DEFAULT_CONFIGS)
    parser.add_argument("--timeout", type=float, default=120, help="Timeout per model in seconds")
    parser.add_argument("--output", type=Path, help="Save a JSON report")
    parser.add_argument("--dry-run", action="store_true", help="Validate configs without API calls")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    results = asyncio.run(run(args))
    return int(any(result["status"] in ("FAIL", "ERROR") for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
