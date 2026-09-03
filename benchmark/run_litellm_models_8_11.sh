#!/usr/bin/env bash
#
# Run the 8-task (cotfresh) + 11-task (py/pyc/elf) prompt-injection experiments
# for three OpenAI-compatible models defined in archipelago/litellm_configs:
#   - GLM-5.3-flash        (litellm_configs/glm_5_3_flash.json,   key: ZAI_API_KEY)
#   - DeepSeek-v4-flash    (litellm_configs/deepseek_v4_flash.json, key: DEEPSEEK_API_KEY)
#   - Kimi-k3-max          (litellm_configs/kimi_k3_max.json,     key: KIMI_API_KEY)
#
# Each model runs 19 tasks split into 4 task-id-disjoint runs:
#   <tag>_8task  (8) + <tag>_batch1 (5 py) + <tag>_batch2 (5 pyc/elf) + <tag>_batch3 (1 pyc)
#
# All 12 runs launch in parallel on isolated ports/subnets. Total concurrency
# = 3 * (8+5+5+1) = 57 tasks, which fits the 64-way CPU budget.
#
# Prereqs: Docker up; images built (archipelago-hf-environment:concurrency etc.);
#          export ZAI_API_KEY / DEEPSEEK_API_KEY / KIMI_API_KEY first.
#
# Usage (from repo root):
#   export ZAI_API_KEY=...  DEEPSEEK_API_KEY=...  KIMI_API_KEY=...
#   bash benchmark/run_litellm_models_8_11.sh            # all 3 models
#   bash benchmark/run_litellm_models_8_11.sh glm dsv4   # subset by tag
#
set -uo pipefail

REPO=/data/ziyi/archipelago
cd "$REPO"
PY=/data/ziyi/.venv/bin/python
BM=benchmark
LLC=litellm_configs
OUT=$BM/generate_attack_config/output
NEWCOT=$BM/generate_attack_config/output_newcot
SC=/tmp/claude-1005/-data-ziyi/6800d4a4-f311-4c63-b09e-747ef69dce3e/scratchpad
GEN=$SC/orch_configs                     # generated orchestrator configs (contain keys)
mkdir -p "$SC" "$GEN"

# Task-json inputs (shared across all models). Batch configs already point at the
# regenerated py/pyc/elf payloads + txt lures.
TJ_8TASK="$NEWCOT/1_to_8_with_attack_config.json"
TJ_B1="$OUT/batch1_11_with_attack_config.json"
TJ_B2="$OUT/batch2_11_with_attack_config.json"
TJ_B3="$OUT/batch3_11_with_attack_config.json"

# Model table:  tag | litellm_configs file | key env var | port block base | cidr block base(2nd octet)
#   ports:  <tag>_8task=BASE, batch1=BASE+20, batch2=BASE+30, batch3=BASE+40
#   cidrs:  10.<C>.0.0/16, 10.<C+1>.0.0/16, 10.<C+2>.0.0/16, 10.<C+3>.0.0/16
declare -A CFG=(  [glm]=$LLC/glm_5_3_flash.json     [dsv4]=$LLC/deepseek_v4_flash.json  [kimik3]=$LLC/kimi_k3_max.json )
declare -A PORT=( [glm]=18600                       [dsv4]=18700                        [kimik3]=18800 )
declare -A CIDR=( [glm]=200                         [dsv4]=204                          [kimik3]=208 )

TAGS=("$@"); [ ${#TAGS[@]} -eq 0 ] && TAGS=(glm dsv4 kimik3)

# --- resolve keys / build one orchestrator config per model ------------------
build_config () {  # $1=tag -> writes $GEN/<tag>.json, echoes path; non-zero on failure
  local tag=$1 src=${CFG[$tag]}
  [ -f "$src" ] || { echo "MISSING config $src" >&2; return 1; }
  "$PY" - "$src" "$GEN/$tag.json" <<'PY' || return 1
import json, os, sys
src, dst = sys.argv[1], sys.argv[2]
c = json.load(open(src))
env = c["api_key_env"]
key = os.getenv(env)
if not key:
    sys.exit(f"env {env} is not set (needed for {c['model']})")
extra = dict(c.get("extra_args", {}))
extra["api_base"] = c["api_base"]
extra["api_key"] = key
json.dump({"model": c["model"], "max_steps": c.get("max_steps"), "extra_args": extra}, open(dst, "w"), indent=2, ensure_ascii=False)
print(c["model"])
PY
}

# --- launch one run ----------------------------------------------------------
launch () {  # $1=run-id $2=orch-config $3=task-json $4=base-port $5=cidr-octet $6=concurrency
  ORCHESTRATOR_CONFIG="$2" RUNTIME_NETWORK_CIDR="10.$5.0.0/16" \
  nohup "$PY" -m benchmark.main_concurrency \
    --task-json "$3" --run-id "$1" \
    --concurrency "$6" --base-port "$4" --skip-build \
    > "$SC/$1.out" 2>&1 &
  echo "  launched $1 -> port $4  cidr 10.$5.0.0/16  conc $6  pid $!"
}

echo "=== building orchestrator configs (injecting API keys from env) ==="
declare -a READY=()
for tag in "${TAGS[@]}"; do
  if model=$(build_config "$tag"); then
    echo "  $tag OK  -> $model  ($GEN/$tag.json)"
    READY+=("$tag")
  else
    echo "  $tag SKIPPED (see error above)"
  fi
done
[ ${#READY[@]} -eq 0 ] && { echo "No models ready (set the API key env vars). Aborting."; exit 1; }

echo "=== launching runs (8task + batch1/2/3) for: ${READY[*]} ==="
for tag in "${READY[@]}"; do
  cfg="$GEN/$tag.json"; base=${PORT[$tag]}; c=${CIDR[$tag]}
  echo "--- $tag ---"
  launch "${tag}_8task"  "$cfg" "$TJ_8TASK" "$base"          "$c"        8
  launch "${tag}_batch1" "$cfg" "$TJ_B1"    "$((base+20))"   "$((c+1))"  5
  launch "${tag}_batch2" "$cfg" "$TJ_B2"    "$((base+30))"   "$((c+2))"  5
  launch "${tag}_batch3" "$cfg" "$TJ_B3"    "$((base+40))"   "$((c+3))"  1
done

echo
echo "=== all launched. total concurrent tasks = ${#READY[@]} x 19 ==="
echo "logs:      $SC/<tag>_{8task,batch1,batch2,batch3}.out"
echo "outputs:   $BM/output/concurrent/<tag>_{8task,batch1,batch2,batch3}/"
echo "progress:  grep -c TASK_FINISHED $SC/glm_8task.out   (etc.)"
echo "results:   <run>/tasks/task_*/grades.json  -> attack_success / prompt_exposure"
