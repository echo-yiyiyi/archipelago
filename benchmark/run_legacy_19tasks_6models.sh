#!/usr/bin/env bash
# Run the legacy 8+11 task set for six models.
# This excludes the newer dynamic_prompt_8_tasks and dynamic_script_11_tasks.
# Usage from tmux: bash benchmark/run_legacy_19tasks_6models.sh
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RUNNER="$ROOT/benchmark/run_tasks_models.sh"
CONCURRENCY=${CONCURRENCY:-64}
BASE_PORT=${BASE_PORT:-30080}
CIDR_START=${CIDR_START:-180}
LOG_ROOT=${LOG_ROOT:-$ROOT/examples/hugging_face_task/output/concurrent/legacy_19tasks_6models_$(date +%Y%m%d_%H%M%S)}

TASK_8="$ROOT/benchmark/generate_attack_config/output_newcot/1_to_8_with_attack_config.json"
TASK_B1="$ROOT/benchmark/generate_attack_config/output/batch1_with_attack_config.json"
TASK_B2="$ROOT/benchmark/generate_attack_config/output/batch2_with_attack_config.json"
TASK_B3="$ROOT/benchmark/generate_attack_config/output/batch3_with_attack_config.json"
for path in "$TASK_8" "$TASK_B1" "$TASK_B2" "$TASK_B3"; do
  [[ -f "$path" ]] || { echo "Missing task JSON: $path" >&2; exit 1; }
done
[[ "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]] || { echo "CONCURRENCY must be positive" >&2; exit 2; }
mkdir -p "$LOG_ROOT"

# dpsk is represented by the runner's configured deepseekv4 alias.
MODELS=(sol glm53 deepseekv4 opus5 gemini kimik3)
TASKS=("$TASK_8" "$TASK_B1" "$TASK_B2" "$TASK_B3")
TASK_NAMES=(8task batch1 batch2 batch3)
PIDS=()
launch_count=0
for model_index in "${!MODELS[@]}"; do
  model=${MODELS[$model_index]}
  for task_index in "${!TASKS[@]}"; do
    slot=$((model_index * ${#TASKS[@]} + task_index))
    port=$((BASE_PORT + slot * 100))
    cidr=$((CIDR_START + slot))
    run_id="legacy19_${model}_${TASK_NAMES[$task_index]}_$(date +%H%M%S)_$$"
    log="$LOG_ROOT/${run_id}.out"
    echo "launch $model/${TASK_NAMES[$task_index]}: concurrency=$CONCURRENCY port=$port cidr=10.$cidr.0.0/16"
    bash "$RUNNER" \
      --task-json "${TASKS[$task_index]}" \
      --models "$model" \
      --concurrency "$CONCURRENCY" \
      --base-port "$port" \
      --cidr-start "$cidr" \
      >"$log" 2>&1 &
    PIDS+=("$!")
    launch_count=$((launch_count + 1))
  done
done

status=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || status=1
done
echo "Finished $launch_count runs (status=$status). Logs: $LOG_ROOT"
exit "$status"
