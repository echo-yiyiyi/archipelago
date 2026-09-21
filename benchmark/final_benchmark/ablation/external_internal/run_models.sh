#!/usr/bin/env bash
# Three models x (30 static + 30 dynamic) = 180 evaluations.
set -euo pipefail
umask 077
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd -- "$SCRIPT_DIR/../../../.." && pwd)
PY=${PY:-python3}
unset ATTACK_CONFIG_FILE ATTACK_CONFIG_BASE_DIR ATTACK_TASK_SELECTOR
unset EXAMPLE_DIR ARCHIPELAGO_DIR TASK_OUTPUT_ROOT SCORE_SUMMARY_FILENAME
unset AGENT_TIMER_SECONDS ORCHESTRATOR_CONFIG
export PYTHONUNBUFFERED=1
cd "$REPO"
exec "$PY" "$SCRIPT_DIR/run_models.py" "$@"
