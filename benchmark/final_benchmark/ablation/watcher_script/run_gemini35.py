#!/usr/bin/env python3
"""Run paired with/direct_arg script watchers with Gemini 3.5 Flash."""
import sys

from run_gemini36 import runner

runner.MODEL_ID = 'gemini35'
runner.MODEL_NAME = 'vertex_ai/gemini-3.5-flash'
runner.MODEL_LABEL = 'Gemini 3.5 Flash'
runner.MODEL_CONFIG = runner.REPO/'benchmark/orchestrator_config_gemini35.json'
runner.__doc__ = __doc__

if __name__ == '__main__':
    # Keep the experiment default at 150; later CLI arguments can override it.
    sys.argv[1:1] = ['--max-steps', '150']
    raise SystemExit(runner.main())
