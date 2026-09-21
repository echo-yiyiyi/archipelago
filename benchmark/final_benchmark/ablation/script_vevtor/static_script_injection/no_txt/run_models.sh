#!/usr/bin/env bash
# Terra, Kimi, DeepSeek: 5 tasks x 3 script formats x 3 models = 45 runs.
set -euo pipefail
umask 077
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PY=${PY:-python3}
unset ATTACK_CONFIG_FILE ATTACK_CONFIG_BASE_DIR ATTACK_TASK_SELECTOR
unset EXAMPLE_DIR ARCHIPELAGO_DIR TASK_OUTPUT_ROOT SCORE_SUMMARY_FILENAME
unset AGENT_TIMER_SECONDS ORCHESTRATOR_CONFIG
export PYTHONUNBUFFERED=1
REPO=$(cd -- "$SCRIPT_DIR/../../../../../.." && pwd)
cd "$REPO"
exec "$PY" "$SCRIPT_DIR/run_models.py" "$@"
