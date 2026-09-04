#!/usr/bin/env bash
# Run the same 11 py/pyc/elf tasks with claude-opus-4-8 (reasoning effort=max), max 150 turns.
# Parameters mirror the opus-5 run so the two are directly comparable.
# Needs ANTHROPIC_API_KEY exported in the shell (orchestrator_config_opus48.json has no vault).
# Fresh ports/subnets so it does NOT collide with any other batches.
# Run from repo root (or anywhere): bash benchmark/generate_attack_config/run_opus48.sh
set -u
cd /data/ziyi/archipelago
PY=/data/ziyi/.venv/bin/python
OUT=benchmark/generate_attack_config/output
SC=/tmp/claude-1005/-data-ziyi/f0f3d94e-fd61-4d38-9d90-3e298a806354/scratchpad
export HF_MAX_STEPS=150

echo "=== 0) 前置检查：ANTHROPIC_API_KEY 是否可用/有额度（claude-opus-4-8）==="
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "  ✗ ANTHROPIC_API_KEY 未设置，先 export 再跑。"; exit 1
fi
PF=$(curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-opus-4-8","max_tokens":1,"messages":[{"role":"user","content":"ping"}]}' 2>/dev/null)
if echo "$PF" | grep -qi 'credit balance is too low'; then
  echo "  ✗ 额度不足：$PF"; exit 1
fi
if echo "$PF" | grep -qiE 'not_found_error|does not exist|invalid model|unknown model'; then
  echo "  ✗ 模型 id 可能不对，Anthropic 返回：$PF"; echo "  确认 claude-opus-4-8 是有效模型名后再跑。"; exit 1
fi
echo "  ✓ key/model 可用。响应片段：$(echo "$PF" | head -c 160)"

echo "=== 1) 重新合并 3 批（用当前 output/ 里已修复的 payload）==="
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

echo "=== 2) 并行启动 3 个 run (claude-opus-4-8 / effort=max / max_steps=150) ==="
launch () {  # $1=batch  $2=base-port  $3=cidr  $4=concurrency
  ORCHESTRATOR_CONFIG=orchestrator_config_opus48.json RUNTIME_NETWORK_CIDR=$3 HF_MAX_STEPS=150 \
  nohup $PY -m benchmark.main_concurrency \
    --task-json "$OUT/$1_with_attack_config.json" \
    --concurrency $4 --base-port $2 --skip-build \
    > "$SC/opus48_$1.out" 2>&1 &
  echo "  launched $1 -> port $2, cidr $3, pid $!"
}
launch batch1 18940 10.208.0.0/16 5
launch batch2 18960 10.206.0.0/16 5
launch batch3 18980 10.204.0.0/16 1
sleep 12
echo "=== 启动日志 ==="
for b in batch1 batch2 batch3; do echo "--- $b ---"; grep -E "RUN_STARTED|run_dir=|error|Error|does not exist|credit|model" "$SC/opus48_$b.out" | head -4; done
echo "（run_dir 见上面 run_dir= 行。跑起来后我读 score_summary.json 监控。）"
