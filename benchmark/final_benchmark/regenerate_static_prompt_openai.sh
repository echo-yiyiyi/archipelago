#!/usr/bin/env bash
# Historical filename; generation now defaults to the original Azure pipeline.
set -euo pipefail
umask 077
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd -- "$SCRIPT_DIR/../.." && pwd)
PY=${PY:-/data/ziyi/.venv/bin/python}
SKIP_RANKING=0
case "${1:-}" in
  --skip-ranking) SKIP_RANKING=1; shift ;;
  --help|-h)
    echo "Usage: bash $0 [--skip-ranking]"
    echo "--skip-ranking reuses saved vector assignments and restarts config generation."
    exit 0 ;;
  "") ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
if (( $# )); then echo "Unexpected arguments: $*" >&2; exit 2; fi
export BENCHMARK_GENERATION_PROVIDER="${BENCHMARK_GENERATION_PROVIDER:-azure}"
case "$BENCHMARK_GENERATION_PROVIDER" in
  azure)
    export AZURE_OPENAI_MODEL="${AZURE_OPENAI_MODEL:-aoai-swedencentral-aii-02-gpt-5.6-sol}"
    echo "Generation provider: Azure; deployment: $AZURE_OPENAI_MODEL" ;;
  openai)
    : "${OPENAI_API_KEY:?Export OPENAI_API_KEY in the launching terminal}"
    export OPENAI_GENERATION_MODEL="${OPENAI_GENERATION_MODEL:-gpt-5.6-sol}"
    echo "Generation provider: OpenAI; model: $OPENAI_GENERATION_MODEL" ;;
  *) echo "BENCHMARK_GENERATION_PROVIDER must be azure or openai" >&2; exit 2 ;;
esac
OUTPUT_DIR=${OUTPUT_DIR:-"$SCRIPT_DIR/static_prompt_injection_openai"}
cd "$REPO"
if (( SKIP_RANKING )); then
  if [[ ! -s "$OUTPUT_DIR/selected_30_tasks_with_inject_goals.json" ]]; then
    echo "Missing saved vector assignments in $OUTPUT_DIR; run without --skip-ranking first." >&2
    exit 1
  fi
  echo "Reusing saved vector assignments; restarting config generation."
else
  "$PY" -m benchmark.sample_inject_vector.rerank_task_goal_vectors \
    --input "$SCRIPT_DIR/static_prompt_injection/selected_30_tasks_with_inject_goals.json" \
    --output-dir "$OUTPUT_DIR" --provider "$BENCHMARK_GENERATION_PROVIDER" --strategy balanced
fi
"$PY" -m benchmark.generate_attack_config.generate \
  "$OUTPUT_DIR/selected_30_tasks_with_inject_goals.json" \
  --output "$OUTPUT_DIR/selected_30_tasks_with_attack_config.json" --provider "$BENCHMARK_GENERATION_PROVIDER"
