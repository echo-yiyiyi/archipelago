#!/usr/bin/env bash
# Configs for the 11 py/pyc/elf tasks are already generated. This merges them
# into 3 task-id-disjoint batches (correct filenames) and launches all 11 with
# gemini-3-flash in parallel on isolated ports/subnets.
# Run from repo root:  bash benchmark/generate_attack_config/launch_11.sh
set -u
cd /data/ziyi/archipelago
PY=/data/ziyi/.venv/bin/python
OUT=benchmark/generate_attack_config/output
SC=/tmp/claude-1005/-data-ziyi/f0f3d94e-fd61-4d38-9d90-3e298a806354/scratchpad

echo "=== 合并成 3 批 (batch1/2/3_with_attack_config.json) ==="
$PY - <<'PYEOF'
import json
OUT="benchmark/generate_attack_config/output"
def load(n): return json.load(open(f"{OUT}/{n}_with_attack_config.json"))[0]
batches={
 "batch1":["9_url_query_params","10_chat_send_ssh","11_terminal_remote_script","12_terminal_cron_setup","py_1_email_send_file"],
 "batch2":["9_url_query_params_pyc","10_chat_send_ssh_pyc","11_terminal_remote_script_elf","12_terminal_cron_setup_elf","elf_3_email_forward_otp"],
 "batch3":["pyc_2_email_send_prompt"],
}
for b,names in batches.items():
    recs=[load(n) for n in names]; ids=[r["task_id"] for r in recs]
    assert len(set(ids))==len(ids), f"{b} dup task_id: {ids}"
    json.dump(recs,open(f"{OUT}/{b}_with_attack_config.json","w"),indent=2,ensure_ascii=False)
    print(f"  {b}: {len(recs)} tasks, vectors={[r['inject_vector'] for r in recs]}, goals={[r['inject_goal'] for r in recs]}")
PYEOF

echo "=== 并行启动 3 个 run (gemini-3-flash) ==="
launch () {  # $1=batch  $2=base-port  $3=cidr  $4=concurrency
  ORCHESTRATOR_CONFIG=orchestrator_config_gemini3.json RUNTIME_NETWORK_CIDR=$3 \
  nohup $PY -m benchmark.main_concurrency \
    --task-json "$OUT/$1_with_attack_config.json" \
    --concurrency $4 --base-port $2 --skip-build \
    > "$SC/run_$1.out" 2>&1 &
  echo "  launched $1 -> port $2, cidr $3, pid $!"
}
launch batch1 18500 10.240.0.0/16 5
launch batch2 18520 10.236.0.0/16 5
launch batch3 18540 10.234.0.0/16 1
sleep 10
echo "=== 启动日志 ==="
for b in batch1 batch2 batch3; do echo "--- $b ---"; grep -E "RUN_STARTED|error|Error|does not exist" "$SC/run_$b.out" | head -3; done
echo "完成后我可以只读监控这几个 run 的结果。"
