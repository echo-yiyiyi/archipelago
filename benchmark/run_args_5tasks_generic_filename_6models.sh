#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
TASK_JSON="$ROOT/benchmark/generate_attack_config/tmp/args_5_generic_filename/args_5_generic_filename.json"
LOG_DIR="$ROOT/examples/hugging_face_task/output/concurrent/args_5_generic_filename_models_logs"
GEN_DIR="$LOG_DIR/configs"
mkdir -p "$LOG_DIR" "$GEN_DIR"

"$PY" "$ROOT/benchmark/prepare_args_5_generic_filename.py"

MODELS=${MODELS:-opus5,luna,kimik3,deepseekv4,glm53,sol}
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
  [sol]="$ROOT/benchmark/orchestrator_config_gpt_sol_high.json"
)
declare -A PORT=( [opus5]=23080 [luna]=23180 [kimik3]=23280 [deepseekv4]=23380 [glm53]=23480 [sol]=23880 )
declare -A CIDR=( [opus5]=252 [luna]=253 [kimik3]=254 [deepseekv4]=255 [glm53]=242 [sol]=243 )

declare -A SEEN_MODELS=()
for tag in "${SELECTED_MODELS[@]}"; do
  [[ -n "${CFG[$tag]:-}" ]] || { echo "Unknown model: $tag"; exit 2; }
  [[ -z "${SEEN_MODELS[$tag]:-}" ]] || { echo "Duplicate model: $tag"; exit 2; }
  SEEN_MODELS[$tag]=1
done

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

PIDS=()
for tag in "${SELECTED_MODELS[@]}"; do
  case "$tag" in
    deepseekv4) build_litellm_config "$ROOT/litellm_configs/deepseek_v4_flash.json" "${CFG[$tag]}" ;;
    glm53) build_litellm_config "$ROOT/litellm_configs/glm_5_3_flash.json" "${CFG[$tag]}" ;;
  esac
  run_id="args5_generic_${tag}_$(date +%Y%m%d_%H%M%S)"
  log="$LOG_DIR/${run_id}.out"
  echo "Launching $tag: five args tasks, port ${PORT[$tag]}, CIDR 10.${CIDR[$tag]}.0.0/16"
  ORCHESTRATOR_CONFIG="${CFG[$tag]}" \
  RUNTIME_NETWORK_CIDR="10.${CIDR[$tag]}.0.0/16" \
  "$PY" -m benchmark.main_concurrency \
    --task-json "$TASK_JSON" --concurrency 5 \
    --base-port "${PORT[$tag]}" --run-id "$run_id" --skip-build \
    >"$log" 2>&1 &
  PIDS+=("$!")
  echo "  pid=$! log=$log"
done

echo "Started ${#SELECTED_MODELS[@]} models x 5 args tasks (max_steps from each model config)."
status=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || status=1
done
echo "All args generic-filename runs finished. Logs: $LOG_DIR"
exit "$status"
