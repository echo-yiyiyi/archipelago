#!/bin/bash
set -e

ORCHESTRATOR_CONFIG="$PWD/benchmark/orchestrator_config_deepseekv4.json" \
bash benchmark/run_concurrency.sh \
  --task-json "$PWD/benchmark/rebuttal/subset/selected_15_tasks_with_attack_config.json" \
  --concurrency 15 \
  --run-id "deepseek_subset_$(python3 -c 'import uuid; print(uuid.uuid4().hex[:12])')" \
  --output-root "$PWD/benchmark/output/subset/deepseekv4"
