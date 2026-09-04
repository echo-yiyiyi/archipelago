#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
TASK_JSON=${TASK_JSON:-$ROOT/benchmark/generate_attack_config/output/args_user_prompt_v3/args_goals_13_to_17.json}
OPUS_CONFIG=${OPUS_CONFIG:-$ROOT/benchmark/orchestrator_config_opus.json}
KIMI_CONFIG=${KIMI_CONFIG:-$ROOT/benchmark/orchestrator_config_kimi.json}
LOG_DIR=${LOG_DIR:-$ROOT/benchmark/output/concurrent/args_elf_opus_other_kimi_logs}
STAMP=$(date +%Y%m%d_%H%M%S)
REVERSE=${REVERSE:-0}
if [[ "$REVERSE" == "1" ]]; then
  ELF_CONFIG="$KIMI_CONFIG"
  OTHER_CONFIG="$OPUS_CONFIG"
  ELF_MODEL=Kimi
  OTHER_MODEL=Opus
  OPUS_RUN_ID=${OPUS_RUN_ID:-args_elf_kimi_$STAMP}
  KIMI_RUN_ID=${KIMI_RUN_ID:-args_other3_opus_$STAMP}
else
  ELF_CONFIG="$OPUS_CONFIG"
  OTHER_CONFIG="$KIMI_CONFIG"
  ELF_MODEL=Opus
  OTHER_MODEL=Kimi
  OPUS_RUN_ID=${OPUS_RUN_ID:-args_elf_opus_$STAMP}
  KIMI_RUN_ID=${KIMI_RUN_ID:-args_other3_kimi_$STAMP}
fi
OPUS_BASE_PORT=${OPUS_BASE_PORT:-20780}
KIMI_BASE_PORT=${KIMI_BASE_PORT:-20880}
OPUS_NETWORK_CIDR=${OPUS_NETWORK_CIDR:-10.237.0.0/16}
KIMI_NETWORK_CIDR=${KIMI_NETWORK_CIDR:-10.238.0.0/16}

mkdir -p "$LOG_DIR"
test -f "$TASK_JSON" || { echo "Missing task JSON: $TASK_JSON"; exit 1; }
test -f "$OPUS_CONFIG" || { echo "Missing Opus config: $OPUS_CONFIG"; exit 1; }
test -f "$KIMI_CONFIG" || { echo "Missing Kimi config: $KIMI_CONFIG"; exit 1; }

TASK_DIR=$(cd "$(dirname "$TASK_JSON")" && pwd)
OPUS_TASKS=$(mktemp "$TASK_DIR/.args_elf_opus.XXXXXX.json")
KIMI_TASKS=$(mktemp "$TASK_DIR/.args_other_kimi.XXXXXX.json")
PIDS=()

cleanup() {
  trap - INT TERM EXIT
  if ((${#PIDS[@]})); then
    kill -TERM "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
  rm -f "$OPUS_TASKS" "$KIMI_TASKS"
}
trap cleanup INT TERM EXIT

"$PY" - "$TASK_JSON" "$OPUS_TASKS" "$KIMI_TASKS" <<'PY'
import json
import sys

source, opus_path, kimi_path = sys.argv[1:]
with open(source, encoding="utf-8") as handle:
    tasks = json.load(handle)
opus_tasks = [task for task in tasks if task.get("inject_vector") == "elf"]
kimi_tasks = [task for task in tasks if task.get("inject_vector") != "elf"]
if len(opus_tasks) != 2 or len(kimi_tasks) != 3:
    raise SystemExit(
        f"expected 2 ELF tasks and 3 other tasks, got "
        f"{len(opus_tasks)} ELF and {len(kimi_tasks)} other"
    )
for path, records in ((opus_path, opus_tasks), (kimi_path, kimi_tasks)):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
PY

OPUS_LOG="$LOG_DIR/$OPUS_RUN_ID.out"
KIMI_LOG="$LOG_DIR/$KIMI_RUN_ID.out"

echo "Launching $ELF_MODEL: 2 ELF tasks"
echo "  run_id=$OPUS_RUN_ID log=$OPUS_LOG"
ORCHESTRATOR_CONFIG="$ELF_CONFIG" \
RUNTIME_NETWORK_CIDR="$OPUS_NETWORK_CIDR" \
HF_MAX_STEPS=${HF_MAX_STEPS:-150} \
"$PY" -m benchmark.main_concurrency \
  --task-json "$OPUS_TASKS" \
  --concurrency 2 \
  --base-port "$OPUS_BASE_PORT" \
  --run-id "$OPUS_RUN_ID" \
  --skip-build \
  >"$OPUS_LOG" 2>&1 &
PIDS+=("$!")

echo "Launching $OTHER_MODEL: 1 PY task and 2 PYC tasks"
echo "  run_id=$KIMI_RUN_ID log=$KIMI_LOG"
ORCHESTRATOR_CONFIG="$OTHER_CONFIG" \
RUNTIME_NETWORK_CIDR="$KIMI_NETWORK_CIDR" \
HF_MAX_STEPS=${HF_MAX_STEPS:-150} \
"$PY" -m benchmark.main_concurrency \
  --task-json "$KIMI_TASKS" \
  --concurrency 3 \
  --base-port "$KIMI_BASE_PORT" \
  --run-id "$KIMI_RUN_ID" \
  --skip-build \
  >"$KIMI_LOG" 2>&1 &
PIDS+=("$!")

status=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || status=1
done
PIDS=()
rm -f "$OPUS_TASKS" "$KIMI_TASKS"
trap - INT TERM EXIT

echo "Runs finished. Logs: $LOG_DIR"
exit "$status"
