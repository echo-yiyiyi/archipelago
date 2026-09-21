#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/../../../.." && pwd)"
PY="$REPO/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

unset ATTACK_CONFIG_FILE ATTACK_CONFIG_BASE_DIR ATTACK_TASK_SELECTOR
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"

exec "$PY" "$SCRIPT_DIR/run_gemini36.py" "$@"
