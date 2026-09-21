#!/usr/bin/env bash
set -euo pipefail
cd /data/ziyi/archipelago
exec /data/ziyi/.venv/bin/python benchmark/rerun_glm_snapshot_task.py "$@"
