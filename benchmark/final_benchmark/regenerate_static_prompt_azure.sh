#!/usr/bin/env bash
# Reuse the established output folder and assignments; force Azure explicitly.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export BENCHMARK_GENERATION_PROVIDER=azure
exec bash "$SCRIPT_DIR/regenerate_static_prompt_openai.sh" "$@"
