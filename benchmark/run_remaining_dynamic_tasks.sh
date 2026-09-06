#!/usr/bin/env bash
# Remaining model/vector combinations: 76 tasks, at most 16 concurrent.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RUNNER="$ROOT/benchmark/run_tasks_models.sh"
BASE_PORT=${BASE_PORT:-30080}
CIDR_START=${CIDR_START:-220}
DRY_ARGS=()
case "${1:-}" in
  --dry-run) DRY_ARGS=(--dry-run); shift ;;
  -h|--help) echo "Usage: bash $0 [--dry-run]"; exit 0 ;;
esac
[[ $# == 0 ]] || { echo "Unexpected argument: $1" >&2; exit 2; }
[[ "$BASE_PORT" =~ ^[1-9][0-9]*$ && "$CIDR_START" =~ ^[1-9][0-9]*$ ]] || exit 2
((BASE_PORT + 708 <= 65536 && CIDR_START + 7 <= 255)) || exit 2

MODELS=(sol sol glm53 glm53 deepseekv4 deepseekv4 opus5 gemini)
VECTORS=(prompt script prompt script prompt script prompt script)
PIDS=()
command_for() {
  local slot=$1
  local vector=${VECTORS[$slot]}
  local model=${MODELS[$slot]}
  local count=8
  [[ "$vector" == script ]] && count=11
  COMMAND=(bash "$RUNNER"
    --task-json "$ROOT/benchmark/generate_attack_config/output/dynamic_${vector}_${count}_tasks/tasks_with_attack_config.json"
    --models "$model" --concurrency 2
    --base-port "$((BASE_PORT + slot * 100))" --cidr-start "$((CIDR_START + slot))")
  [[ "$vector" != script ]] || COMMAND+=(--user-allow-addtional-instruction)
  [[ "$model" != gemini ]] || COMMAND+=(--max-steps 100)
}

# Validate all bundles before launching any model.
for slot in "${!MODELS[@]}"; do
  command_for "$slot"
  "${COMMAND[@]}" --dry-run
done
if ((${#DRY_ARGS[@]})); then exit 0; fi
[[ -n "${ZAI_API_KEY:-}" ]] || { echo "Missing ZAI_API_KEY" >&2; exit 1; }
[[ -n "${DEEPSEEK_API_KEY:-}" ]] || { echo "Missing DEEPSEEK_API_KEY" >&2; exit 1; }
for slot in "${!MODELS[@]}"; do
  command_for "$slot"
  "${COMMAND[@]}" &
  PIDS+=("$!")
done
status=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || status=1
done
exit "$status"
