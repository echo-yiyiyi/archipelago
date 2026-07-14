#!/bin/bash
# Run complete Hugging Face task pipelines in isolated Docker environments.
# Example: ./run_concurrency.sh 0-31

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIPELAGO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

export EXAMPLE_DIR="$SCRIPT_DIR"
export ARCHIPELAGO_DIR
export ENVIRONMENT_DIR="$ARCHIPELAGO_DIR/environment"
export AGENTS_DIR="$ARCHIPELAGO_DIR/agents"
export GRADING_DIR="$ARCHIPELAGO_DIR/grading"

# Runtime egress is controlled by the shared Squid sidecar. Host-side setup,
# image builds, agent execution, and grading use the hosts direct network.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
unset http_proxy https_proxy all_proxy no_proxy

cd "$AGENTS_DIR"
uv sync --locked
cd "$GRADING_DIR"
uv sync --locked
cd "$AGENTS_DIR"
uv run python "$EXAMPLE_DIR/main_concurrency.py" "$@"
