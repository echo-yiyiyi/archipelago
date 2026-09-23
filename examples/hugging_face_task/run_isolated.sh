#!/bin/bash
# Resume one incomplete trajectory in a fresh isolated environment.
# Usage: ./run_isolated.sh TRAJECTORY.json ADDITIONAL_TURNS [main_concurrency options]
# Filesystem overlay: add --world-overlay DIR; DIR contents are copied to /filesystem.
# Batch: ./run_isolated.sh TRAJECTORY.json ADDITIONAL_TURNS \
#          --text-variants variants.json [--parallel N] [main_concurrency options]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIPELAGO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKSPACE_DIR="$(cd "$ARCHIPELAGO_DIR/.." && pwd)"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 TRAJECTORY.json ADDITIONAL_TURNS [options]" >&2
  exit 2
fi

TRAJECTORY="$(realpath "$1")"
ADDITIONAL_TURNS="$2"
shift 2

TEXT_VARIANTS=""
PARALLEL=""
PREPARE_ONLY=false
MAIN_OPTIONS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --text-variants)
      [[ $# -ge 2 ]] || { echo "--text-variants requires a JSON path" >&2; exit 2; }
      TEXT_VARIANTS="$(realpath "$2")"
      shift 2
      ;;
    --parallel)
      [[ $# -ge 2 ]] || { echo "--parallel requires a positive integer" >&2; exit 2; }
      PARALLEL="$2"
      shift 2
      ;;
    --prepare-only)
      PREPARE_ONLY=true
      shift
      ;;
    *)
      MAIN_OPTIONS+=("$1")
      shift
      ;;
  esac
done

if [[ ! "$ADDITIONAL_TURNS" =~ ^[1-9][0-9]*$ ]]; then
  echo "ADDITIONAL_TURNS must be a positive integer" >&2
  exit 2
fi

TASK_DIR="$(basename "$(dirname "$TRAJECTORY")")"
TASK_ID="${TASK_DIR#task_}"
TASK_ID="task_${TASK_ID}"
RUN_ID="isolated_$(date +%Y%m%d_%H%M%S)_${TASK_ID#task_}"

export EXAMPLE_DIR="$SCRIPT_DIR"
export ARCHIPELAGO_DIR
export ENVIRONMENT_DIR="$ARCHIPELAGO_DIR/environment"
export AGENTS_DIR="$ARCHIPELAGO_DIR/agents"
export GRADING_DIR="$ARCHIPELAGO_DIR/grading"
export PYTHONUNBUFFERED=1

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
unset http_proxy https_proxy all_proxy no_proxy

cd "$AGENTS_DIR"
uv sync --locked
cd "$GRADING_DIR"
uv sync --locked
cd "$AGENTS_DIR"

if [[ -n "$TEXT_VARIANTS" ]]; then
  BATCH_ARGS=(
    "$EXAMPLE_DIR/run_isolated_batch.py"
    "$TRAJECTORY"
    "$ADDITIONAL_TURNS"
    "$TEXT_VARIANTS"
  )
  if [[ -n "$PARALLEL" ]]; then
    BATCH_ARGS+=(--parallel "$PARALLEL")
  fi
  if [[ "$PREPARE_ONLY" == true ]]; then
    BATCH_ARGS+=(--prepare-only)
  fi
  if [[ ${#MAIN_OPTIONS[@]} -gt 0 ]]; then
    BATCH_ARGS+=("${MAIN_OPTIONS[@]}")
  fi
  uv run python "${BATCH_ARGS[@]}"
  exit $?
fi

uv run python "$EXAMPLE_DIR/main_concurrency.py" \
  "$TASK_ID" \
  --resume-trajectory "$TRAJECTORY" \
  --additional-turns "$ADDITIONAL_TURNS" \
  --concurrency 1 \
  --run-id "$RUN_ID" \
  "${MAIN_OPTIONS[@]}"
