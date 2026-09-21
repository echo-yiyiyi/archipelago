#!/usr/bin/env python3
"""Run the same paired watcher settings with Gemini 3.5 Flash."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('paired_watcher_runner', ROOT/'run_gemini36.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.MODEL_ID = 'gemini35'
runner.MODEL_NAME = 'vertex_ai/gemini-3.5-flash'
runner.MODEL_LABEL = 'Gemini 3.5 Flash'
runner.MODEL_CONFIG = runner.REPO/'benchmark/orchestrator_config_gemini35.json'
runner.__doc__ = __doc__

if __name__ == '__main__':
    raise SystemExit(runner.main())
