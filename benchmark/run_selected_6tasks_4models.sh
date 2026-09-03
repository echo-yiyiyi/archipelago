#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
TASK_JSON="$ROOT/benchmark/generate_attack_config/output/selected_6_with_attack_config.json"
LOG_DIR="$ROOT/examples/hugging_face_task/output/concurrent/selected_6_models_logs"
GEN_DIR="$LOG_DIR/configs"
mkdir -p "$LOG_DIR"
mkdir -p "$GEN_DIR"

MODELS=${MODELS:-opus5,luna,kimik3,deepseekv4,glm53}
if [[ "${1:-}" == "--models" ]]; then
  MODELS=${2:?missing value for --models}
elif [[ -n "${1:-}" ]]; then
  MODELS=$1
fi
IFS=',' read -r -a SELECTED_MODELS <<< "$MODELS"

declare -A CFG=(
  [opus5]="$ROOT/benchmark/orchestrator_config_opus.json"
  [luna]="$ROOT/benchmark/orchestrator_config_luna.json"
  [kimik3]="$ROOT/benchmark/orchestrator_config_kimi.json"
  [deepseekv4]="$GEN_DIR/deepseek_v4_flash.json"
  [glm53]="$GEN_DIR/glm_5_3_flash.json"
)
declare -A PORT=( [opus5]=21080 [luna]=21180 [kimik3]=21280 [deepseekv4]=21380 [glm53]=21480 )
declare -A CIDR=( [opus5]=246 [luna]=247 [kimik3]=248 [deepseekv4]=249 [glm53]=250 )

test -f "$TASK_JSON" || { echo "Missing task JSON: $TASK_JSON"; exit 1; }

build_litellm_config() {
  local src=$1 dst=$2
  "$PY" - "$src" "$dst" <<'PY'
import json, os, sys
src, dst = sys.argv[1:]
c = json.load(open(src))
key = os.getenv(c["api_key_env"])
if not key:
    raise SystemExit(f"missing required environment variable: {c['api_key_env']}")
extra = dict(c.get("extra_args", {}))
extra["api_base"] = c["api_base"]
extra["api_key"] = key
json.dump({"model": c["model"], "max_steps": c.get("max_steps"), "extra_args": extra}, open(dst, "w"), indent=2)
PY
}

build_litellm_config "$ROOT/litellm_configs/deepseek_v4_flash.json" "${CFG[deepseekv4]}"
build_litellm_config "$ROOT/litellm_configs/glm_5_3_flash.json" "${CFG[glm53]}"

PIDS=()
for tag in "${SELECTED_MODELS[@]}"; do
  [[ -n "${CFG[$tag]:-}" ]] || { echo "Unknown model: $tag"; exit 2; }
  run_id="selected6_${tag}_$(date +%Y%m%d_%H%M%S)"
  log="$LOG_DIR/${run_id}.out"
  echo "Launching $tag: six tasks, port ${PORT[$tag]}, CIDR 10.${CIDR[$tag]}.0.0/16"
  ORCHESTRATOR_CONFIG="${CFG[$tag]}" \
  RUNTIME_NETWORK_CIDR="10.${CIDR[$tag]}.0.0/16" \
  "$PY" -m benchmark.main_concurrency \
    --task-json "$TASK_JSON" --concurrency 6 \
    --base-port "${PORT[$tag]}" --run-id "$run_id" --skip-build \
    >"$log" 2>&1 &
  PIDS+=("$!")
  echo "  pid=$! log=$log"
done

echo "Started ${#SELECTED_MODELS[@]} models x 6 tasks (max_steps from each model config)."
status=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || status=1
done
echo "All selected model runs finished. Logs: $LOG_DIR"
exit "$status"
