#!/bin/bash
# Run local sampled tasks across orchestrator configs with runtime-only file injection.
# Usage: ./run_inject.sh configs.jsonl injections.jsonl [task IDs/indices or --all] [options]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIPELAGO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKSPACE_DIR="$(cd "$ARCHIPELAGO_DIR/.." && pwd)"

export EXAMPLE_DIR="$SCRIPT_DIR"
export ARCHIPELAGO_DIR
export ENVIRONMENT_DIR="$ARCHIPELAGO_DIR/environment"
export AGENTS_DIR="$ARCHIPELAGO_DIR/agents"
export GRADING_DIR="$ARCHIPELAGO_DIR/grading"
export PYTHONUNBUFFERED=1

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
unset http_proxy https_proxy all_proxy no_proxy

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 CONFIGS.jsonl INJECTIONS.jsonl TASK... [options]" >&2
  echo "       $0 CONFIGS.jsonl INJECTIONS.jsonl --all [options]" >&2
  exit 2
fi

CONFIGS_JSONL="$(realpath "$1")"
INJECTIONS_JSONL="$(realpath "$2")"
shift 2

cd "$AGENTS_DIR"
uv sync --locked
cd "$GRADING_DIR"
uv sync --locked
cd "$AGENTS_DIR"
uv run python "$EXAMPLE_DIR/main_inject.py" \
  "$CONFIGS_JSONL" "$INJECTIONS_JSONL" \
  --dataset-dir "$WORKSPACE_DIR/sampled_tasks/dataset" \
  --injection-goals "$WORKSPACE_DIR/sampled_tasks/prompt_inject/inject_goal.py" \
  "$@"
