#!/usr/bin/env bash
set -euo pipefail
umask 077
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd -- "$SCRIPT_DIR/../../../.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
unset ATTACK_CONFIG_FILE ATTACK_CONFIG_BASE_DIR ATTACK_TASK_SELECTOR
unset EXAMPLE_DIR ARCHIPELAGO_DIR TASK_OUTPUT_ROOT SCORE_SUMMARY_FILENAME
unset AGENT_TIMER_SECONDS ORCHESTRATOR_CONFIG
export PYTHONUNBUFFERED=1
cd "$REPO"
# 3 categories x 3 formats x 5 tasks = 45 runs.
exec "$PY" "$SCRIPT_DIR/run_models.py" --models gemini36 --concurrency 64 --max-steps 150 "$@"
