#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
TASK_JSON="$ROOT/benchmark/generate_attack_config/output/args_user_prompt_v3/args_goals_1_to_5.json"
LOG_DIR="$ROOT/examples/hugging_face_task/output/concurrent/args_5tasks_6models_logs"
GEN_DIR="$LOG_DIR/configs"
mkdir -p "$LOG_DIR" "$GEN_DIR"

MODELS=${MODELS:-opus5,luna,kimik3,deepseekv4,gemini35,glm53}
if [[ "${1:-}" == "--models" ]]; then
  MODELS=${2:?missing value for --models}
elif [[ -n "${1:-}" ]]; then
  MODELS=$1
fi
IFS=',' read -r -a SELECTED_MODELS <<< "$MODELS"

echo "=== Docker cleanup (images are preserved) ==="
docker container prune -f
docker network prune -f
docker volume prune -f
docker builder prune -f

test -f "$TASK_JSON" || { echo "Missing task JSON: $TASK_JSON"; exit 1; }

build_litellm_config() {
  local src=$1 dst=$2
  "$PY" - "$src" "$dst" <<'PY'
import json, os, sys
src, dst = sys.argv[1:]
c = json.load(open(src))
env = c["api_key_env"]
key = os.getenv(env)
if not key:
    raise SystemExit(f"missing required environment variable: {env}")
extra = dict(c.get("extra_args", {}))
extra["api_base"] = c["api_base"]
extra["api_key"] = key
json.dump({"model": c["model"], "max_steps": c.get("max_steps"), "extra_args": extra}, open(dst, "w"), indent=2)
PY
}

build_litellm_config "$ROOT/litellm_configs/deepseek_v4_flash.json" "$GEN_DIR/deepseek_v4_flash.json"
build_litellm_config "$ROOT/litellm_configs/glm_5_3_flash.json" "$GEN_DIR/glm_5_3_flash.json"
build_litellm_config "$ROOT/litellm_configs/kimi_k3_max.json" "$GEN_DIR/kimi_k3.json"

declare -A CFG=(
  [opus5]="$ROOT/benchmark/orchestrator_config_opus.json"
  [luna]="$ROOT/benchmark/orchestrator_config_luna.json"
  [kimik3]="$GEN_DIR/kimi_k3.json"
  [deepseekv4]="$GEN_DIR/deepseek_v4_flash.json"
  [gemini35]="$ROOT/benchmark/orchestrator_config_gemini35.json"
  [glm53]="$GEN_DIR/glm_5_3_flash.json"
)
declare -A PORT=( [opus5]=19080 [luna]=19180 [kimik3]=19280 [deepseekv4]=19380 [gemini35]=19480 [glm53]=19580 )
declare -A CIDR=( [opus5]=220 [luna]=221 [kimik3]=222 [deepseekv4]=223 [gemini35]=224 [glm53]=225 )

PIDS=()
for tag in "${SELECTED_MODELS[@]}"; do
  [[ -n "${CFG[$tag]:-}" ]] || { echo "Unknown model: $tag"; exit 2; }
  run_id="args5_${tag}_$(date +%Y%m%d_%H%M%S)"
  log="$LOG_DIR/${run_id}.out"
  echo "Launching $tag: five tasks, port ${PORT[$tag]}, CIDR 10.${CIDR[$tag]}.0.0/16"
  ORCHESTRATOR_CONFIG="${CFG[$tag]}" \
  RUNTIME_NETWORK_CIDR="10.${CIDR[$tag]}.0.0/16" \
  HF_MAX_STEPS="${HF_MAX_STEPS:-50}" \
  "$PY" -m benchmark.main_concurrency \
    --task-json "$TASK_JSON" --concurrency 5 \
    --base-port "${PORT[$tag]}" --run-id "$run_id" --skip-build \
    >"$log" 2>&1 &
  PIDS+=("$!")
  echo "  pid=$! log=$log"
done

echo "Started ${#SELECTED_MODELS[@]} models x 5 tasks = $(( ${#SELECTED_MODELS[@]} * 5 )) tasks."
echo "Waiting for all six model runs; Ctrl-C stops this wrapper only."
status=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || status=1
done
echo "All runs finished. Logs: $LOG_DIR"
exit "$status"
