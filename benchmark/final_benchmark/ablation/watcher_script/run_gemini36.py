#!/usr/bin/env python3
"""Run paired with/direct_arg script watchers with Gemini 3.6 Flash."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    'paired_watcher_runner', ROOT.parent/'watcher_prompt/run_gemini36.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.ROOT = ROOT
runner.SETTINGS = ('with', 'direct_arg')
runner.VECTOR = 'dynamic_script_execution'
runner.OUTPUT_ROOT = runner.REPO/'benchmark/output/ablation/watcher_script'
runner.__doc__ = __doc__

if __name__ == '__main__':
    raise SystemExit(runner.main())
