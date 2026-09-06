#!/usr/bin/env bash
# Re-run failed tasks twice: original settings, then script without user allow.
set -u
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: bash $0 [manifest-glob]"
  echo "Default: benchmark/output/concurrent/tasks_20260906_000954_*/manifest.json"
  exit 0
fi
MANIFEST_GLOB=${1:-$ROOT/benchmark/output/concurrent/tasks_20260906_000954_*/manifest.json}

choose_cidr() {
  local used start n ok
  used=$(docker network ls -q | xargs -r docker network inspect --format '{{range .IPAM.Config}}{{.Subnet}}{{"\n"}}{{end}}' 2>/dev/null || true)
  for start in $(seq 10 247); do
    ok=1
    for n in $(seq "$start" $((start + 7))); do
      if grep -Eq "^10\\.${n}\\." <<<"$used"; then ok=0; break; fi
    done
    ((ok)) && { echo "$start"; return; }
  done
  echo "No eight consecutive free Docker CIDR blocks found" >&2; exit 1
}
choose_port() {
  local base used ok p
  used=$(ss -ltnH 2>/dev/null | awk '{print $4}' || true)
  for base in $(seq 30080 100 60080); do
    ok=1
    for p in $(seq "$base" $((base + 7))); do
      if grep -Eq "[:.]${p}$" <<<"$used"; then ok=0; break; fi
    done
    ((ok)) && { echo "$base"; return; }
  done
  echo "No eight consecutive free host ports found" >&2; exit 1
}

run_phase() {
  local allow=$1
  local cidr port
  cidr=$(choose_cidr)
  port=$(choose_port)
  if (( allow )); then
    BASE_PORT="$port" CIDR_START="$cidr" bash "$ROOT/benchmark/run_failed_dynamic_tasks.sh" "$MANIFEST_GLOB"
  else
    BASE_PORT="$port" CIDR_START="$cidr" NO_ALLOW_SCRIPT=1 bash "$ROOT/benchmark/run_failed_dynamic_tasks.sh" "$MANIFEST_GLOB"
  fi
}

echo "[1/2] Re-running failed tasks with their original settings"
run_phase 1
first_status=$?

echo "[2/2] Re-running failed tasks with --user-allow-addtional-instruction disabled for script tasks"
run_phase 0
second_status=$?

if (( first_status != 0 || second_status != 0 )); then
  echo "One or both rerun phases failed (original=$first_status, no_allow_script=$second_status)." >&2
  exit 1
fi
echo "Both rerun phases completed successfully."
