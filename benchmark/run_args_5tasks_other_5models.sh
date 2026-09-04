#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
TASK_JSON="$ROOT/benchmark/generate_attack_config/output/args_user_prompt_v3/args_goals_13_to_17.json"
LOG_DIR="$ROOT/benchmark/output/concurrent/args_5tasks_other_5models_logs"
GEN_DIR="$LOG_DIR/configs"
mkdir -p "$LOG_DIR" "$GEN_DIR"

test -f "$TASK_JSON" || { echo "Missing task JSON: $TASK_JSON"; exit 1; }

build_litellm_config() {
  local src=$1 dst=$2
  "$PY" - "$src" "$dst" <<'PY'
import json, os, sys
src, dst = sys.argv[1:]
with open(src, encoding="utf-8") as handle:
    config = json.load(handle)
env_name = config["api_key_env"]
api_key = os.getenv(env_name)
if not api_key:
    raise SystemExit(f"missing required environment variable: {env_name}")
extra = dict(config.get("extra_args", {}))
extra["api_base"] = config["api_base"]
extra["api_key"] = api_key
with open(dst, "w", encoding="utf-8") as handle:
    json.dump({"model": config["model"], "max_steps": config.get("max_steps"), "extra_args": extra}, handle, indent=2)
PY
}

build_litellm_config "$ROOT/litellm_configs/deepseek_v4_flash.json" "$GEN_DIR/deepseek_v4_flash.json"
build_litellm_config "$ROOT/litellm_configs/glm_5_3_flash.json" "$GEN_DIR/glm_5_3_flash.json"
build_litellm_config "$ROOT/litellm_configs/kimi_k3_max.json" "$GEN_DIR/kimi_k3.json"

declare -A CFG=(
  [opus5]="$ROOT/benchmark/orchestrator_config_opus.json"
  [kimik3]="$GEN_DIR/kimi_k3.json"
  [deepseekv4]="$GEN_DIR/deepseek_v4_flash.json"
  [gemini35]="$ROOT/benchmark/orchestrator_config_gemini35.json"
  [glm53]="$GEN_DIR/glm_5_3_flash.json"
)

# These ranges deliberately avoid the current GPT run on port 19180 and
# 10.221.0.0/16, as well as the stopped networks from the earlier batch.
declare -A PORT=(
  [opus5]=20080
  [kimik3]=20180
  [deepseekv4]=20280
  [gemini35]=20380
  [glm53]=20480
)
declare -A CIDR=(
  [opus5]=230
  [kimik3]=231
  [deepseekv4]=232
  [gemini35]=233
  [glm53]=234
)

PIDS=()
stop_children() {
  trap - INT TERM EXIT
  if ((${#PIDS[@]})); then
    kill -TERM "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
}
trap stop_children INT TERM EXIT

stamp=$(date +%Y%m%d_%H%M%S)
for tag in opus5 kimik3 deepseekv4 gemini35 glm53; do
  run_id="args5_${tag}_fixed_${stamp}"
  log="$LOG_DIR/${run_id}.out"
  echo "Launching $tag: 5 tasks, port ${PORT[$tag]}, CIDR 10.${CIDR[$tag]}.0.0/16"
  ORCHESTRATOR_CONFIG="${CFG[$tag]}" \
  RUNTIME_NETWORK_CIDR="10.${CIDR[$tag]}.0.0/16" \
  HF_MAX_STEPS=150 \
  "$PY" -m benchmark.main_concurrency \
    --task-json "$TASK_JSON" \
    --concurrency 5 \
    --base-port "${PORT[$tag]}" \
    --run-id "$run_id" \
    --skip-build \
    >"$log" 2>&1 &
  PIDS+=("$!")
  echo "  pid=$! log=$log"
done

echo "Started 5 models x 5 tasks = 25 tasks."
status=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || status=1
done
PIDS=()
trap - INT TERM EXIT
echo "All runs finished. Logs: $LOG_DIR"
exit "$status"
