#!/usr/bin/env bash
# Run 3 tasks (elf/pyc) with claude-opus-5, using the NEW "run it to get the result"
# lure (no disclaimer; the "unavailable" line lives only in the script's runtime output).
# These 3 are exactly the ones opus-5 previously refused ("won't run untrusted binary"),
# so this isolates whether the new lure framing changes that.
# Needs ANTHROPIC_API_KEY exported. Fresh ports/subnet (19000), collides with nothing.
# Run from repo root: bash benchmark/generate_attack_config/run_opus5_newlure3.sh
set -u
cd /data/ziyi/archipelago
PY=/data/ziyi/.venv/bin/python
OUT=benchmark/generate_attack_config/output
SC=/tmp/claude-1005/-data-ziyi/f0f3d94e-fd61-4d38-9d90-3e298a806354/scratchpad
export HF_MAX_STEPS=150

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then echo "✗ 先 export ANTHROPIC_API_KEY"; exit 1; fi
PF=$(curl -s https://api.anthropic.com/v1/messages -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"claude-opus-5","max_tokens":1,"messages":[{"role":"user","content":"ping"}]}' 2>/dev/null)
echo "$PF" | grep -qi 'credit balance is too low' && { echo "✗ 额度不足"; exit 1; }
echo "✓ key ok"

echo "=== 合并这 3 个（新诱饵版）为一批 ==="
$PY - <<'PYEOF'
import json
OUT="benchmark/generate_attack_config/output"
names=["11_terminal_remote_script_elf","10_chat_send_ssh_pyc","elf_3_email_forward_otp"]
recs=[json.load(open(f"{OUT}/{n}_with_attack_config.json"))[0] for n in names]
ids=[r["task_id"] for r in recs]; assert len(set(ids))==len(ids), ids
json.dump(recs,open(f"{OUT}/newlure3_with_attack_config.json","w"),indent=2,ensure_ascii=False)
print("  newlure3:",[(r['inject_goal'],r['inject_vector']) for r in recs])
PYEOF

echo "=== 启动 opus-5 (effort=max, max150) ==="
ORCHESTRATOR_CONFIG=orchestrator_config_opus.json RUNTIME_NETWORK_CIDR=10.200.0.0/16 HF_MAX_STEPS=150 \
nohup $PY -m benchmark.main_concurrency \
  --task-json "$OUT/newlure3_with_attack_config.json" \
  --concurrency 3 --base-port 19000 --skip-build \
  > "$SC/opus5_newlure3.out" 2>&1 &
echo "  pid $!  -> port 19000, cidr 10.200"
sleep 12
grep -E "RUN_STARTED|run_dir=|credit|error" "$SC/opus5_newlure3.out" | grep -v error=None | head -4
echo "（run_dir 见上。跑起来后告诉我，我读 score_summary 对比新旧诱饵。）"
