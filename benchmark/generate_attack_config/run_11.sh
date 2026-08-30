#!/usr/bin/env bash
# Regenerate the 11 py/pyc/elf task configs (each now auto-generates a paired
# "Additional Task Instructions" lure), split them into 3 task-id-disjoint
# batches, and run all 11 with gemini-3-flash in parallel on isolated
# ports/subnets. Run from the repo root: bash benchmark/generate_attack_config/run_11.sh
set -u
cd /data/ziyi/archipelago
PY=/data/ziyi/.venv/bin/python
GEN=benchmark.generate_attack_config.generate
OUT=benchmark/generate_attack_config/output
TJ=benchmark/generate_attack_config/test_json
SC=/tmp/claude-1005/-data-ziyi/f0f3d94e-fd61-4d38-9d90-3e298a806354/scratchpad

INPUTS=(9_url_query_params 9_url_query_params_pyc 10_chat_send_ssh 10_chat_send_ssh_pyc \
  11_terminal_remote_script 11_terminal_remote_script_elf 12_terminal_cron_setup 12_terminal_cron_setup_elf \
  py_1_email_send_file pyc_2_email_send_draft elf_3_email_forward_otp)

echo "=== 1) 重生成 11 个配置（含诱饵）==="
for f in "${INPUTS[@]}"; do
  echo -n "  $f ... "
  timeout 240 $PY -m $GEN "$TJ/$f.json" >/dev/null 2>&1 && echo ok || echo FAIL
done

echo "=== 2) 合并成 3 个 task-id 不冲突的批次 ==="
$PY - <<'PYEOF'
import json
OUT="benchmark/generate_attack_config/output"
def load(name): return json.load(open(f"{OUT}/{name}_with_attack_config.json"))[0]
batches={
 "batch1":["9_url_query_params","10_chat_send_ssh","11_terminal_remote_script","12_terminal_cron_setup","py_1_email_send_file"],
 "batch2":["9_url_query_params_pyc","10_chat_send_ssh_pyc","11_terminal_remote_script_elf","12_terminal_cron_setup_elf","elf_3_email_forward_otp"],
 "batch3":["pyc_2_email_send_draft"],
}
for b,names in batches.items():
    recs=[load(n) for n in names]
    ids=[r["task_id"] for r in recs]
    assert len(set(ids))==len(ids), f"{b} 有重复 task_id: {ids}"
    json.dump(recs,open(f"{OUT}/{b}_11_with_attack_config.json","w"),indent=2,ensure_ascii=False)
    print(f"  {b}: {len(recs)} 任务, task_id 互异 OK")
PYEOF

echo "=== 3) 并行启动 3 个 run (gemini-3-flash) ==="
launch () { # $1=batch json  $2=base-port  $3=cidr  $4=concurrency
  ORCHESTRATOR_CONFIG=orchestrator_config_gemini3.json RUNTIME_NETWORK_CIDR=$3 \
  nohup $PY -m benchmark.main_concurrency \
    --task-json "$OUT/$1_with_attack_config.json" \
    --concurrency $4 --base-port $2 --skip-build \
    > "$SC/run_$1.out" 2>&1 &
  echo "  launched $1 (port $2, cidr $3) pid $!"
}
launch batch1 18500 10.240.0.0/16 5
launch batch2 18520 10.236.0.0/16 5
launch batch3 18540 10.234.0.0/16 1
echo "=== 已启动。用: tail -f $SC/run_batch1.out 看进度 ==="
