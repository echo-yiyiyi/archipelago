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
# GLM uses the OpenAI-compatible Z.ai endpoint. Scope its credential to this process.
DRY_RUN=false
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" || "$arg" == "--summarize-only" ]]; then DRY_RUN=true; fi
done
if [[ "$DRY_RUN" == false && -z "${ZAI_API_KEY:-}" ]]; then
  echo "Export ZAI_API_KEY before running GLM 5.3 Flash." >&2
  exit 1
fi
export OPENAI_API_KEY="${ZAI_API_KEY:-}"
export HF_MAX_STEPS=150
# 20 tasks x 2 keyword settings = 40 runs.
exec "$PY" "$SCRIPT_DIR/run_models.py" --models glm53 --settings with without --concurrency 64 "$@"
