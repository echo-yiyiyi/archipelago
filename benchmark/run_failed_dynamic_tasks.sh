#!/usr/bin/env bash
# Re-run only failed tasks from a completed remaining-dynamic batch.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RUNNER="$ROOT/benchmark/run_tasks_models.sh"
SOURCE_PROMPT="$ROOT/benchmark/generate_attack_config/output/dynamic_prompt_8_tasks/tasks_with_attack_config.json"
SOURCE_SCRIPT="$ROOT/benchmark/generate_attack_config/output/dynamic_script_11_tasks/tasks_with_attack_config.json"
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
BASE_PORT=${BASE_PORT:-$(choose_port)}
CIDR_START=${CIDR_START:-$(choose_cidr)}
MANIFEST_GLOB=${1:-$ROOT/benchmark/output/concurrent/tasks_20260906_000954_*/manifest.json}

TMP_ROOT=$(mktemp -d /tmp/archipelago_failed_dynamic.XXXXXX)
trap 'rm -rf "$TMP_ROOT"' EXIT

python3 - "$MANIFEST_GLOB" "$SOURCE_PROMPT" "$SOURCE_SCRIPT" "$TMP_ROOT" <<'PY'
import glob, json, pathlib, shutil, sys
pattern, prompt_path, script_path, out_dir = sys.argv[1:]
failed = {}
for manifest_path in glob.glob(pattern):
    manifest = json.load(open(manifest_path))
    model = pathlib.Path(manifest_path).parent.name.rsplit('_', 1)[-1]
    # The model suffix is unambiguous for the current batch names.
    if model not in {'sol','glm53','deepseekv4','opus5','gemini'}:
        continue
    for result in manifest.get('results', []):
        if result.get('returncode') != 0:
            selector = result['selector']
            vector = 'script' if selector.endswith('_arg') else 'prompt'
            failed.setdefault((model, vector), set()).add(selector)

for (model, vector), selectors in sorted(failed.items()):
    source_file = pathlib.Path(script_path if vector == 'script' else prompt_path)
    source = json.load(open(source_file))
    selected = [r for r in source if (r.get('harmful_task_id') or r.get('task_id')) in selectors]
    if len(selected) != len(selectors):
        missing = selectors - {(r.get('harmful_task_id') or r.get('task_id')) for r in selected}
        raise SystemExit(f'missing selectors for {model}/{vector}: {sorted(missing)}')
    path = pathlib.Path(out_dir) / f'{model}_{vector}.json'
    path.write_text(json.dumps(selected, indent=2))
    # populate_files are relative to the generated bundle directory; copy them
    # alongside the filtered JSON so run_tasks_models can validate and package them.
    for record in selected:
        for name in record.get('populate_files', []):
            src = source_file.parent / name
            dst = pathlib.Path(out_dir) / name
            if not src.is_file():
                raise SystemExit(f'missing artifact in source bundle: {src}')
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    print(model, vector, len(selected), path)
PY

slot=0
pids=()
for cfg in "$TMP_ROOT"/*.json; do
    [ -e "$cfg" ] || continue
    base=$(basename "$cfg" .json)
    model=${base%_*}; vector=${base##*_}
    # At most eight model/vector groups: 2 workers each, 16 total.
    args=(bash "$RUNNER" --task-json "$cfg" --models "$model" --concurrency 2
          --base-port "$((BASE_PORT + slot * 20))" --cidr-start "$((CIDR_START + slot))")
    if [[ "$vector" == script && "${NO_ALLOW_SCRIPT:-0}" != 1 ]]; then args+=(--user-allow-addtional-instruction); fi
    if [[ "$model" == gemini ]]; then args+=(--max-steps 100); fi
    "${args[@]}" &
    pids+=("$!")
    slot=$((slot + 1))
done
status=0
for pid in "${pids[@]}"; do wait "$pid" || status=1; done
exit "$status"
