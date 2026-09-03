#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
TASK_JSON="$ROOT/benchmark/generate_attack_config/output/args_user_prompt_v3/args_goals_1_to_5.json"
CONFIG="$ROOT/benchmark/orchestrator_config_opus.json"
LOG_DIR="$ROOT/benchmark/output/concurrent/args_5tasks_opus_logs"
STAMP=$(date +%Y%m%d_%H%M%S)
RUN_ID=${RUN_ID:-args5_opus5_noargs_$STAMP}
BASE_PORT=${BASE_PORT:-20680}
RUNTIME_NETWORK_CIDR=${RUNTIME_NETWORK_CIDR:-10.236.0.0/16}

mkdir -p "$LOG_DIR"
test -f "$TASK_JSON" || { echo "Missing task JSON: $TASK_JSON"; exit 1; }
test -f "$CONFIG" || { echo "Missing orchestrator config: $CONFIG"; exit 1; }

LOG="$LOG_DIR/$RUN_ID.out"
echo "Launching Claude Opus 5: 5 tasks sequentially"
echo "run_id=$RUN_ID"
echo "log=$LOG"

echo "=== Docker cleanup (images are preserved) ==="
docker container prune -f
docker network prune -f
docker volume prune -f
docker builder prune -f

ORCHESTRATOR_CONFIG="$CONFIG" \
RUNTIME_NETWORK_CIDR="$RUNTIME_NETWORK_CIDR" \
HF_MAX_STEPS=${HF_MAX_STEPS:-150} \
"$PY" -m benchmark.main_concurrency \
  --task-json "$TASK_JSON" \
  --concurrency 1 \
  --base-port "$BASE_PORT" \
  --run-id "$RUN_ID" \
  --skip-build \
  2>&1 | tee "$LOG"

echo "All tasks finished sequentially. Log: $LOG"