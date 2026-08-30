#!/usr/bin/env bash
# Re-run the 11 py/pyc/elf tasks with gemini-3.5-flash. pyc_2 (goal 2) is
# regenerated first so it uses the new read-Task_Brief.txt mechanism. Then the
# 3 task-id-disjoint batches are re-merged and launched in parallel on fresh
# isolated ports/subnets. Run from repo root: bash benchmark/generate_attack_config/rerun_35.sh
set -u
cd /data/ziyi/archipelago
PY=/data/ziyi/.venv/bin/python
OUT=benchmark/generate_attack_config/output
TJ=benchmark/generate_attack_config/test_json
SC=/tmp/claude-1005/-data-ziyi/f0f3d94e-fd61-4d38-9d90-3e298a806354/scratchpad

echo "=== 0) 重生成 pyc_2（新 goal-2：运行时读 Task_Brief.txt）==="
rm -rf $OUT/task_*_pyc_2_email_send_draft $OUT/pyc_2_email_send_draft_with_attack_config.json
timeout 240 $PY -m benchmark.generate_attack_config.generate "$TJ/pyc_2_email_send_draft.json" >/dev/null 2>&1 \
  && echo "  pyc_2 regenerated" || echo "  pyc_2 FAIL"
# sanity: show pyc_2 populate + confirm no baked prompt in payload source is not possible (pyc is compiled),
# so just show populate_files includes Task_Brief.txt
$PY - <<'PYEOF'
import json
OUT="benchmark/generate_attack_config/output"
d=json.load(open(f"{OUT}/pyc_2_email_send_draft_with_attack_config.json"))[0]
print("  pyc_2 populate:", [p.split("/")[-1] for p in d["populate_files"]])
print("  pyc_2 attacker_needed_file:", d["attack_config"].get("attacker_needed_file"))
PYEOF

echo "=== 1) 重新合并 3 批 ==="
$PY - <<'PYEOF'
import json
OUT="benchmark/generate_attack_config/output"
def load(n): return json.load(open(f"{OUT}/{n}_with_attack_config.json"))[0]
batches={
 "batch1":["9_url_query_params","10_chat_send_ssh","11_terminal_remote_script","12_terminal_cron_setup","py_1_email_send_file"],
 "batch2":["9_url_query_params_pyc","10_chat_send_ssh_pyc","11_terminal_remote_script_elf","12_terminal_cron_setup_elf","elf_3_email_forward_otp"],
 "batch3":["pyc_2_email_send_draft"],
}
for b,names in batches.items():
    recs=[load(n) for n in names]; ids=[r["task_id"] for r in recs]
    assert len(set(ids))==len(ids), f"{b} dup: {ids}"
    json.dump(recs,open(f"{OUT}/{b}_with_attack_config.json","w"),indent=2,ensure_ascii=False)
    print(f"  {b}: {len(recs)} tasks vectors={[r['inject_vector'] for r in recs]}")
PYEOF

echo "=== 2) 并行启动 3 个 run (gemini-3.5-flash) ==="
launch () {  # $1=batch  $2=base-port  $3=cidr  $4=concurrency
  ORCHESTRATOR_CONFIG=orchestrator_config.json RUNTIME_NETWORK_CIDR=$3 \
  nohup $PY -m benchmark.main_concurrency \
    --task-json "$OUT/$1_with_attack_config.json" \
    --concurrency $4 --base-port $2 --skip-build \
    > "$SC/run35_$1.out" 2>&1 &
  echo "  launched $1 -> port $2, cidr $3, pid $!"
}
launch batch1 18700 10.232.0.0/16 5
launch batch2 18720 10.230.0.0/16 5
launch batch3 18740 10.228.0.0/16 1
sleep 12
echo "=== 启动日志 ==="
for b in batch1 batch2 batch3; do echo "--- $b ---"; grep -E "RUN_STARTED|run_dir=|error|Error|does not exist" "$SC/run35_$b.out" | head -3; done
echo "（gemini-3.5 较慢；跑起来后我可只读监控结果。）"
