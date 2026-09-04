#!/usr/bin/env bash
# Run the same 11 py/pyc/elf tasks with gpt-5.6-sol, reasoning effort=high, max 150 turns.
# Uses fresh ports/subnets so it does NOT collide with any gemini-3.5 batches still running.
# Run from repo root (or anywhere): bash benchmark/generate_attack_config/run_gpt_sol_high.sh
set -u
cd /data/ziyi/archipelago
PY=/data/ziyi/.venv/bin/python
OUT=benchmark/generate_attack_config/output
SC=/tmp/claude-1005/-data-ziyi/f0f3d94e-fd61-4d38-9d90-3e298a806354/scratchpad
export HF_MAX_STEPS=150

echo "=== 1) 重新合并 3 批（pyc_2 已是新 goal-2 版本）==="
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
    assert len(set(ids))==len(ids), f"{b} dup: {ids}"
    json.dump(recs,open(f"{OUT}/{b}_with_attack_config.json","w"),indent=2,ensure_ascii=False)
    print(f"  {b}: {len(recs)} tasks vectors={[r['inject_vector'] for r in recs]}")
PYEOF

echo "=== 2) 并行启动 3 个 run (gpt-5.6-sol / effort=high / max_steps=150) ==="
launch () {  # $1=batch  $2=base-port  $3=cidr  $4=concurrency
  ORCHESTRATOR_CONFIG=orchestrator_config_gpt_sol_high.json RUNTIME_NETWORK_CIDR=$3 HF_MAX_STEPS=150 \
  nohup $PY -m benchmark.main_concurrency \
    --task-json "$OUT/$1_with_attack_config.json" \
    --concurrency $4 --base-port $2 --skip-build \
    > "$SC/gpt_$1.out" 2>&1 &
  echo "  launched $1 -> port $2, cidr $3, pid $!"
}
launch batch1 18760 10.226.0.0/16 5
launch batch2 18780 10.224.0.0/16 5
launch batch3 18800 10.222.0.0/16 1
sleep 12
echo "=== 启动日志 ==="
for b in batch1 batch2 batch3; do echo "--- $b ---"; grep -E "RUN_STARTED|run_dir=|error|Error|does not exist" "$SC/gpt_$b.out" | head -3; done
echo "（跑起来后我可只读 score_summary.json 监控。run_dir 见上面 run_dir= 行。）"
