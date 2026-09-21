#!/usr/bin/env python3
"""Run existing-file head and keyword-position tasks with GPT-5.6 Terra."""
from pathlib import Path

import run_gemini36 as runner

runner.MODEL = "gpt_terra_high"
runner.MODEL_NAME = "openai/responses/gpt-5.6-terra"
runner.MODEL_CONFIG = runner.REPO / "benchmark/orchestrator_config_gpt_terra_high.json"


if __name__ == "__main__":
    raise SystemExit(runner.main())

