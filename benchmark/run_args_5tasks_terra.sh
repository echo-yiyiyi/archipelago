#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
TASK_JSON=${TASK_JSON:-$ROOT/benchmark/generate_attack_config/output/args_user_prompt_v3/args_goals_1_to_5.json}
CONFIG=${CONFIG:-$ROOT/benchmark/orchestrator_config_gpt_terra.json}
LOG_DIR=${LOG_DIR:-$ROOT/benchmark/output/concurrent/args_5tasks_terra_logs}
STAMP=$(date +%Y%m%d_%H%M%S)
RUN_ID=${RUN_ID:-args5_terra_$STAMP}
CONCURRENCY=${CONCURRENCY:-5}
BASE_PORT=${BASE_PORT:-21780}
RUNTIME_NETWORK_CIDR=${RUNTIME_NETWORK_CIDR:-10.246.0.0/16}
HF_MAX_STEPS=${HF_MAX_STEPS:-150}
TIMER=${TIMER:-0}

mkdir -p "$LOG_DIR"
test -x "$PY" || { echo "Missing Python executable: $PY" >&2; exit 1; }
test -f "$TASK_JSON" || { echo "Missing task JSON: $TASK_JSON" >&2; exit 1; }
test -f "$CONFIG" || { echo "Missing Terra config: $CONFIG" >&2; exit 1; }

task_count=$("$PY" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$TASK_JSON")
if [[ "$task_count" != "5" ]]; then
  echo "Expected 5 tasks in $TASK_JSON, found $task_count" >&2
  exit 1
fi

timer_args=()
if [[ "$TIMER" == "1" ]]; then
  timer_args+=(--timer)
elif [[ "$TIMER" != "0" ]]; then
  echo "TIMER must be 0 or 1" >&2
  exit 1
fi

LOG="$LOG_DIR/$RUN_ID.out"
echo "Launching GPT-5.6 Terra: 5 tasks"
echo "run_id=$RUN_ID concurrency=$CONCURRENCY max_steps=$HF_MAX_STEPS timer=$TIMER"
echo "task_json=$TASK_JSON"
echo "log=$LOG"

ORCHESTRATOR_CONFIG="$CONFIG" \
RUNTIME_NETWORK_CIDR="$RUNTIME_NETWORK_CIDR" \
HF_MAX_STEPS="$HF_MAX_STEPS" \
"$PY" -m benchmark.main_concurrency \
  --task-json "$TASK_JSON" \
  --concurrency "$CONCURRENCY" \
  --base-port "$BASE_PORT" \
  --run-id "$RUN_ID" \
  --skip-build \
  "${timer_args[@]}" \
  2>&1 | tee "$LOG"

echo "Terra run finished. Log: $LOG"
