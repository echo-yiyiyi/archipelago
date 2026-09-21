#!/usr/bin/env python3
"""Run paired with/direct_arg script watchers with GPT-5.6 Terra."""
import sys

from run_gemini36 import runner

runner.MODEL_ID = 'gpt_terra_high'
runner.MODEL_NAME = 'openai/responses/gpt-5.6-terra'
runner.MODEL_LABEL = 'GPT-5.6 Terra'
runner.MODEL_CONFIG = runner.REPO/'benchmark/orchestrator_config_gpt_terra_high.json'
runner.__doc__ = __doc__

if __name__ == '__main__':
    # Keep the experiment default at 150; later CLI arguments can override it.
    sys.argv[1:1] = ['--max-steps', '150']
    raise SystemExit(runner.main())
