#!/usr/bin/env bash
# Two models x two conditions x 10 tasks = 40 runs in one shared pool.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$SCRIPT_DIR/../../../.." && pwd)
PY=${PY:-python3}
CONDITION=both
CONCURRENCY=${CONCURRENCY:-20}
MAX_STEPS=${MAX_STEPS:-50}
EXTRA=()

usage() {
  cat <<'EOF'
Usage: bash run_sol_gemini.sh [options]
  --condition both|with|without  Task variants (default: both)
  --concurrency N           Global concurrent runs, 1-64 (default: 20)
  --max-steps N             Shared agent step limit (default: 50)
  --base-port N             First worker port (default: automatically selected)
  --skip-build              Reuse existing Docker images
  --dry-run                 Validate inputs and print jobs; no model calls
  --summarize RUN_DIR        Refresh exposure/ASR/score reports only
  -h, --help                Show this help

Models: GPT 5.6 Sol (xhigh) and Gemini 3.6 Flash (high).
Timer is off. PY and OUTPUT_ROOT may be overridden via environment variables.
Reports: comparison.md, comparison.csv, comparison.json, by model/condition/category.
EOF
}
while (($#)); do
  case "$1" in
    --condition) CONDITION=${2:?missing condition}; shift 2 ;;
    --concurrency) CONCURRENCY=${2:?missing concurrency}; shift 2 ;;
    --max-steps) MAX_STEPS=${2:?missing step limit}; shift 2 ;;
    --base-port) EXTRA+=(--base-port "${2:?missing port}"); shift 2 ;;
    --summarize) EXTRA+=(--summarize "${2:?missing run directory}"); shift 2 ;;
    --skip-build|--dry-run) EXTRA+=("$1"); shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ "$CONDITION" == both || "$CONDITION" == with || "$CONDITION" == without ]] || { echo 'Condition must be both, with or without' >&2; exit 2; }
[[ "$MAX_STEPS" =~ ^[1-9][0-9]*$ ]] || { echo 'max-steps must be a positive integer' >&2; exit 2; }
[[ -x "$PY" ]] || { echo "Python executable not found: $PY" >&2; exit 2; }

# Keep task overlays and timer settings independent of the calling shell.
unset ATTACK_CONFIG_FILE ATTACK_CONFIG_BASE_DIR ATTACK_TASK_SELECTOR
unset EXAMPLE_DIR ARCHIPELAGO_DIR TASK_OUTPUT_ROOT SCORE_SUMMARY_FILENAME
unset AGENT_TIMER_SECONDS ORCHESTRATOR_CONFIG
export HF_MAX_STEPS="$MAX_STEPS" PYTHONUNBUFFERED=1
OUTPUT_ROOT=${OUTPUT_ROOT:-$ROOT/benchmark/output/ablation/hideen}
cd "$ROOT"
exec "$PY" "$SCRIPT_DIR/run_hidden.py" \
  --condition "$CONDITION" \
  --input-root "$SCRIPT_DIR" \
  --output-root "$OUTPUT_ROOT" \
  --concurrency "$CONCURRENCY" "${EXTRA[@]}"
