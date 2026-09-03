#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
TASK_JSON=${TASK_JSON:-$ROOT/benchmark/generate_attack_config/output/args_user_prompt_v3/args_goals_1_to_5.json}
LOG_DIR=${LOG_DIR:-$ROOT/benchmark/output/concurrent/args_5tasks_4models_logs}
CONFIG_DIR="$LOG_DIR/configs"
STAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$LOG_DIR" "$CONFIG_DIR"
test -f "$TASK_JSON" || { echo "Missing task JSON: $TASK_JSON"; exit 1; }

build_litellm_config() {
  local src=$1 dst=$2
  "$PY" - "$src" "$dst" <<'PY'
import json
import os
import sys

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
output = {
    "model": config["model"],
    "max_steps": config["max_steps"],
    "extra_args": extra,
}
with open(dst, "w", encoding="utf-8") as handle:
    json.dump(output, handle, indent=2)
PY
}

build_litellm_config "$ROOT/litellm_configs/kimi_k3_max.json" "$CONFIG_DIR/kimi.json"
build_litellm_config "$ROOT/litellm_configs/deepseek_v4_flash.json" "$CONFIG_DIR/deepseek.json"
build_litellm_config "$ROOT/litellm_configs/glm_5_3_flash.json" "$CONFIG_DIR/glm.json"

declare -A CONFIG=(
  [kimi]="$CONFIG_DIR/kimi.json"
  [gemini]="$ROOT/benchmark/orchestrator_config_gemini35.json"
  [glm]="$CONFIG_DIR/glm.json"
  [deepseek]="$CONFIG_DIR/deepseek.json"
)
declare -A PORT=(
  [kimi]=21280
  [gemini]=21380
  [glm]=21480
  [deepseek]=21580
)
declare -A CIDR=(
  [kimi]=242
  [gemini]=243
  [glm]=244
  [deepseek]=245
)

MODELS=(kimi gemini glm deepseek)
PIDS=()
RUN_IDS=()

stop_children() {
  trap - INT TERM EXIT
  if ((${#PIDS[@]})); then
    kill -TERM "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
}
trap stop_children INT TERM EXIT

for model in "${MODELS[@]}"; do
  run_id="args5_${model}_${STAMP}"
  log="$LOG_DIR/${run_id}.out"
  RUN_IDS+=("$run_id")
  echo "Launching $model: 5 tasks, max_steps=$(jq -r .max_steps "${CONFIG[$model]}")"
  echo "  run_id=$run_id log=$log"
  ORCHESTRATOR_CONFIG="${CONFIG[$model]}" \
  RUNTIME_NETWORK_CIDR="10.${CIDR[$model]}.0.0/16" \
  "$PY" -m benchmark.main_concurrency \
    --task-json "$TASK_JSON" \
    --concurrency 5 \
    --base-port "${PORT[$model]}" \
    --run-id "$run_id" \
    --skip-build \
    >"$log" 2>&1 &
  PIDS+=("$!")
done

status=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || status=1
done
PIDS=()
trap - INT TERM EXIT

echo
echo "Final ASR and task-score summary"
"$PY" - "$ROOT/benchmark/output/concurrent" "${RUN_IDS[@]}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
print(f"{'model':<12} {'completed':>9} {'ASR':>10} {'avg_score':>12} {'pass@1':>10}")
for run_id in sys.argv[2:]:
    model = run_id.split("_")[1]
    path = root / run_id / "score_summary.json"
    if not path.exists():
        print(f"{model:<12} {'missing':>9}")
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    evaluated = int(data.get("attack_evaluated_count", 0))
    successes = int(data.get("attack_success_count", 0))
    asr = successes / evaluated if evaluated else 0.0
    print(
        f"{model:<12} {data.get('completed_task_count', 0):>9} "
        f"{asr:>9.1%} {data.get('average_mean_score', 0):>12.4f} "
        f"{data.get('average_pass_at_1_percent', 0):>9.1%}"
    )
PY

echo "Logs: $LOG_DIR"
exit "$status"
