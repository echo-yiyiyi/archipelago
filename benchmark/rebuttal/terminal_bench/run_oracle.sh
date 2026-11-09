#!/usr/bin/env bash
set -euo pipefail

TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uvx >/dev/null 2>&1; then
    echo 'uvx is required. Install uv before running this script.' >&2
    exit 1
fi

exec uvx --python 3.13 --from harbor==0.24.0 harbor run \
    --path "$TASK_ROOT/schemelike-metacircular-eval" \
    --agent oracle \
    --env docker \
    --force-build \
    --n-concurrent 1 \
    --max-retries 0 \
    --jobs-dir "$TASK_ROOT/oracle_runs" \
    "$@"
