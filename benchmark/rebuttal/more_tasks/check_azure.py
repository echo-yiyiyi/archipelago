#!/usr/bin/env python3
"""Send one small Responses request using the selector's Azure configuration."""
import argparse
import json
from pathlib import Path
import sys

from filter_more_tasks import azure_config, credential, HERE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpt-config", type=Path, default=HERE / "orchestrator_config_gpt_azure.json")
    args = parser.parse_args()
    config, identity = azure_config("gpt_5_6_sol", args.gpt_config)
    key = credential(config, "AZURE_API_KEY")
    model = config["model"]
    for prefix in ("openai/responses/", "azure/responses/", "azure/"):
        if model.startswith(prefix):
            model = model.removeprefix(prefix)
            break
    base = identity["api_base"].rstrip("/")
    if not base.endswith("/openai/v1"):
        base += "/openai/v1"
    print(json.dumps({"model": model, "responses_endpoint": base + "/responses"}), flush=True)
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=base + "/", timeout=45, max_retries=0)
    try:
        response = client.responses.create(
            model=model, input="Reply with only OK.", max_output_tokens=128,
            reasoning={"effort": "low"},
        )
    except Exception as error:
        print(json.dumps({"success": False, "error_type": type(error).__name__,
                          "http_status": getattr(error, "status_code", None)}), file=sys.stderr)
        return 3
    print(json.dumps({"success": response.status == "completed", "status": response.status,
                      "text": response.output_text}, ensure_ascii=False))
    return 0 if response.status == "completed" and response.output_text else 4


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2)
