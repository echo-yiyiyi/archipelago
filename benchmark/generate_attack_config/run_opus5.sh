#!/usr/bin/env bash
# Re-run the same 11 py/pyc/elf tasks with claude-opus-5 (reasoning effort=max), max 150 turns.
#
# NOTE: the earlier opus run (run_20260831_012225_*) failed on EVERY task because the
# Anthropic key had no credit ("credit balance is too low"), so those runs did no real
# work and are not resumable -- the concurrency runner (benchmark/main.py) has no resume
# path. Now that credit is topped up, this simply re-runs all 11 fresh, which is the clean
# and correct way to finish the opus experiment.
#
# Needs ANTHROPIC_API_KEY exported in the shell (orchestrator_config_opus.json has no vault).
# Fresh ports/subnets so it does NOT collide with any gemini-3.5 / gpt-sol batches.
# Run from repo root (or anywhere): bash benchmark/generate_attack_config/run_opus5.sh
set -u
cd /data/ziyi/archipelago
PY=/data/ziyi/.venv/bin/python
OUT=benchmark/generate_attack_config/output
SC=/tmp/claude-1005/-data-ziyi/f0f3d94e-fd61-4d38-9d90-3e298a806354/scratchpad
export HF_MAX_STEPS=150

echo "=== 0a) 前置检查：ANTHROPIC_API_KEY 是否有额度 ==="
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "  ✗ ANTHROPIC_API_KEY 未设置，先 export 再跑。"; exit 1
fi
PF=$(curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-opus-5","max_tokens":1,"messages":[{"role":"user","content":"ping"}]}' 2>/dev/null)
if echo "$PF" | grep -qi 'credit balance is too low'; then
  echo "  ✗ 额度仍不足，Anthropic 返回：$PF"; echo "  充值后再跑。"; exit 1
fi
echo "  ✓ key 可用（未见额度不足）。响应片段：$(echo "$PF" | head -c 160)"

echo "=== 0b) 清理上一轮作废的 opus run_dir（额度不足全废）==="
for rd in output/concurrent/run_20260831_012225_5de17a19 \
          output/concurrent/run_20260831_012225_95349fbe \
          output/concurrent/run_20260831_012225_99158af5; do
  [ -d "benchmark/$rd" ] && rm -rf "benchmark/$rd" && echo "  removed benchmark/$rd" || true
done

echo "=== 1) 重新合并 3 批（pyc_2 已是新 goal-2 版本）==="
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

echo "=== 2) 并行启动 3 个 run (claude-opus-5 / effort=max / max_steps=150) ==="
launch () {  # $1=batch  $2=base-port  $3=cidr  $4=concurrency
  ORCHESTRATOR_CONFIG=orchestrator_config_opus.json RUNTIME_NETWORK_CIDR=$3 HF_MAX_STEPS=150 \
  nohup $PY -m benchmark.main_concurrency \
    --task-json "$OUT/$1_with_attack_config.json" \
    --concurrency $4 --base-port $2 --skip-build \
    > "$SC/opus_$1.out" 2>&1 &
  echo "  launched $1 -> port $2, cidr $3, pid $!"
}
launch batch1 18880 10.214.0.0/16 5
launch batch2 18900 10.212.0.0/16 5
launch batch3 18920 10.210.0.0/16 1
sleep 12
echo "=== 启动日志 ==="
for b in batch1 batch2 batch3; do echo "--- $b ---"; grep -E "RUN_STARTED|run_dir=|error|Error|does not exist|API|key" "$SC/opus_$b.out" | head -4; done
echo "（run_dir 见上面 run_dir= 行。跑起来后我可只读 score_summary.json 监控。）"
