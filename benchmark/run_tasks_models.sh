#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
MODELS=${MODELS:-sol,opus5,deepseekv4,glm53}
TASK_JSON=${TASK_JSON:-}
CONCURRENCY=${CONCURRENCY:-}
BASE_PORT=${BASE_PORT:-25080}
CIDR_START=${CIDR_START:-180}
DRY_RUN=false
TIMER_ARGS=()
ADDITIONAL_INSTRUCTION_ARGS=()

usage() {
  echo "Usage: bash $0 --task-json FILE [--models sol,opus5,gemini,deepseekv4,glm53]"
  echo "  --concurrency N  Per-model task concurrency (default: min(task count, 32))"
  echo "  --base-port N    First model's base port (default: 25080)"
  echo "  --cidr-start N   First model's network: 10.N.0.0/16 (default: 180)"
  echo "  --dry-run       Validate inputs and show commands without launching"
  echo "  --timer          Enable the benchmark task timer"
  echo "  --user-allow-addtional-instruction  Add user permission to reference instructions in files"
  echo "  --max-steps N    Override HF_MAX_STEPS for all selected models"
  echo "Models: sol, luna, terra, opus5, gemini, gemini35, kimik3, kimik3_litellm, deepseekv4, glm53"
}
while (($#)); do
  case "$1" in
    --task-json) TASK_JSON=${2:?missing JSON path}; shift 2 ;;
    --models) MODELS=${2:?missing model list}; shift 2 ;;
    --concurrency) CONCURRENCY=${2:?missing concurrency}; shift 2 ;;
    --base-port) BASE_PORT=${2:?missing base port}; shift 2 ;;
    --cidr-start) CIDR_START=${2:?missing CIDR start}; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --timer) TIMER_ARGS=(--timer); shift ;;
    --user-allow-addtional-instruction|--user-allow-additional-instruction)
      ADDITIONAL_INSTRUCTION_ARGS=(--user-allow-addtional-instruction); shift ;;
    --max-steps)
      [[ "${2:-}" =~ ^[1-9][0-9]*$ ]] || { echo "--max-steps requires a positive integer" >&2; exit 2; }
      export HF_MAX_STEPS=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ -n "$TASK_JSON" ]] || { usage >&2; exit 2; }
TASK_JSON=$("$PY" -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$TASK_JSON")
TASK_COUNT=$("$PY" - "$TASK_JSON" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
records = json.loads(p.read_text())
if not isinstance(records, list) or not records:
    raise SystemExit('Task JSON must be a non-empty array')
selectors = []
for r in records:
    if not isinstance(r, dict) or not r.get('task_id') or not isinstance(r.get('attack_config'), dict):
        raise SystemExit('Each task needs task_id and generated attack_config; pass the output JSON')
    selectors.append(r.get('harmful_task_id') or r['task_id'])
    for name in r.get('populate_files', []):
        if not (p.parent / name).is_file():
            raise SystemExit(f'Missing artifact: {name}')
if len(set(selectors)) != len(selectors):
    raise SystemExit('Task selectors must be unique')
print(len(records))
PY
)
CONCURRENCY=${CONCURRENCY:-$((TASK_COUNT < 32 ? TASK_COUNT : 32))}
for value in "$CONCURRENCY" "$BASE_PORT" "$CIDR_START"; do
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || { echo "Expected positive integer: $value" >&2; exit 2; }
done
[[ "$MODELS" != ,* && "$MODELS" != *, && "$MODELS" != *,,* && -n "$MODELS" ]] || { echo "Invalid model list" >&2; exit 2; }
IFS=',' read -r -a SELECTED_MODELS <<< "$MODELS"
declare -A SEEN=()
declare -A SOURCES=(
  [sol]="$ROOT/benchmark/orchestrator_config_gpt_sol_high.json"
  [luna]="$ROOT/benchmark/orchestrator_config_luna.json"
  [terra]="$ROOT/benchmark/orchestrator_config_gpt_terra.json"
  [gemini35]="$ROOT/benchmark/orchestrator_config_gemini35.json"
  [gemini]="$ROOT/benchmark/orchestrator_config_gemini35.json"
  [kimik3]="$ROOT/benchmark/orchestrator_config_kimi.json"
  [kimik3_litellm]="$ROOT/litellm_configs/kimi_k3_max.json"
  [opus5]="$ROOT/benchmark/orchestrator_config_opus.json"
  [deepseekv4]="$ROOT/litellm_configs/deepseek_v4_flash.json"
  [glm53]="$ROOT/litellm_configs/glm_5_3_flash.json"
)
for tag in "${SELECTED_MODELS[@]}"; do
  [[ -n "${SOURCES[$tag]:-}" && -z "${SEEN[$tag]:-}" ]] || { echo "Unknown or duplicate model: $tag" >&2; exit 2; }
  [[ -f "${SOURCES[$tag]}" ]] || { echo "Missing config: ${SOURCES[$tag]}" >&2; exit 2; }
  SEEN[$tag]=1
done
PORT_STEP=$((CONCURRENCY > 100 ? CONCURRENCY : 100))
((BASE_PORT + (${#SELECTED_MODELS[@]} - 1) * PORT_STEP + CONCURRENCY <= 65536)) || { echo "Port range exceeds 65535" >&2; exit 2; }
((CIDR_START + ${#SELECTED_MODELS[@]} - 1 <= 255)) || { echo "CIDR range exceeds 255" >&2; exit 2; }
stamp=$(date +%Y%m%d_%H%M%S)
RUN_PREFIX="tasks_${stamp}_$$"
LOG_DIR=${LOG_DIR:-$ROOT/examples/hugging_face_task/output/concurrent/$RUN_PREFIX}
LOG_DIR=$("$PY" -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$LOG_DIR")
GEN_DIR="$LOG_DIR/configs"
if ! $DRY_RUN; then
  mkdir -p "$GEN_DIR"
  chmod 700 "$GEN_DIR"
fi
declare -A CFG=()
for tag in "${SELECTED_MODELS[@]}"; do
  CFG[$tag]=${SOURCES[$tag]}
  case "$tag" in
    deepseekv4|glm53|kimik3_litellm)
      CFG[$tag]="$GEN_DIR/$tag.json"
      if ! $DRY_RUN; then
        "$PY" - "${SOURCES[$tag]}" "${CFG[$tag]}" <<'PY'
import json, os, sys
src, dst = sys.argv[1:]
c = json.load(open(src))
key = os.getenv(c['api_key_env'])
if not key:
    raise SystemExit(f"missing required environment variable: {c['api_key_env']}")
extra = dict(c.get('extra_args', {}), api_base=c['api_base'], api_key=key)
with open(os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
    json.dump(dict(model=c['model'], max_steps=c.get('max_steps'), extra_args=extra), f, indent=2)
PY
      fi
      ;;
  esac
done
cd "$ROOT"
PIDS=()
index=0
for tag in "${SELECTED_MODELS[@]}"; do
  port=$((BASE_PORT + index * PORT_STEP))
  cidr="10.$((CIDR_START + index)).0.0/16"
  run_id="${RUN_PREFIX}_${tag}"
  log="$LOG_DIR/$run_id.out"
  command=("$PY" -m benchmark.main_concurrency --task-json "$TASK_JSON"
           --concurrency "$CONCURRENCY" --base-port "$port" --run-id "$run_id" --skip-build "${TIMER_ARGS[@]}" "${ADDITIONAL_INSTRUCTION_ARGS[@]}")
  echo "$tag: $TASK_COUNT tasks, concurrency=$CONCURRENCY, port=$port, network=$cidr"
  if $DRY_RUN; then
    if [[ -n "${HF_MAX_STEPS:-}" ]]; then printf 'HF_MAX_STEPS=%q ' "$HF_MAX_STEPS"; fi
    printf 'ORCHESTRATOR_CONFIG=%q RUNTIME_NETWORK_CIDR=%q ' "${CFG[$tag]}" "$cidr"
    printf '%q ' "${command[@]}"
    printf '\n'
  else
    ORCHESTRATOR_CONFIG="${CFG[$tag]}" RUNTIME_NETWORK_CIDR="$cidr" "${command[@]}" >"$log" 2>&1 &
    PIDS+=("$!")
    echo "  pid=$! log=$log"
  fi
  index=$((index + 1))
done
status=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || status=1
done
if ! $DRY_RUN; then
  echo "Finished (status=$status). Logs: $LOG_DIR"
fi
exit "$status"
