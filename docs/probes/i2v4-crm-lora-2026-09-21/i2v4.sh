#!/bin/bash
# I2 v4 — v3's 30 rows recut as one example per assistant step, prompt MASKED. Worktree probe-i2v4 (detached at master).
set -u; ROOT=${AGENT_SANDBOX_ROOT:-$HOME/code/Michiel-DK/agent-sandbox}; WT=$ROOT/.claude/worktrees/probe-i2v4; P=$ROOT/docs/probes/i2v4-crm-lora-2026-09-21
MODEL=$(python3 -c "from huggingface_hub import snapshot_download as s; print(s('mlx-community/gemma-4-e2b-it-4bit'))")
cd "$WT"; echo "I2v4 START $(date '+%F %T') master=$(git rev-parse --short HEAD) mlx_lm=$(python3 -c 'import mlx_lm;print(mlx_lm.__version__)')"
echo "=== (c) examples $(date +%T) ==="; python3 "$P/build_data_crm_v4.py" || exit 4
echo "=== (d) LoRA 400 iters, --mask-prompt $(date +%T) ==="; t0=$(date +%s)
python3 -m mlx_lm.lora --model "$MODEL" --train --data "$P/data" --fine-tune-type lora --num-layers 8 --batch-size 1 --iters 400 --learning-rate 1e-4 --max-seq-length 6144 --grad-checkpoint --mask-prompt --adapter-path "$P/adapters" > "$P/logs/lora.log" 2>&1 &
LORA=$!
# NaN guard (attempt 1): mlx_lm prints "Train loss nan" and keeps going; a NaN step poisons the adapter for good. Kill on the first one.
while kill -0 $LORA 2>/dev/null; do if grep -q -E 'loss nan' "$P/logs/lora.log"; then kill $LORA; echo "NAN GUARD FIRED: $(grep -m1 -E 'loss nan' "$P/logs/lora.log" | cut -c1-80)"; exit 6; fi; sleep 20; done
wait $LORA; lrc=$?; grep -E 'Iter [0-9]+: (Train|Val)|Saved|Trainable|Error|Traceback' "$P/logs/lora.log" | tail -8
echo "=== LoRA DONE rc=$lrc wall=$(( $(date +%s) - t0 ))s $(date +%T) ==="; grep -q -E 'loss nan' "$P/logs/lora.log" && { echo "NAN IN LOG — stopping"; exit 6; }
[ -f "$P/adapters/adapters.safetensors" ] || { echo "NO ADAPTER"; exit 3; }
git -C "$WT" status --short evals agents | grep . && { echo "WORKTREE NOT CLEAN — stopping"; exit 5; } || echo "worktree evals/agents clean"
serve() { pkill -f mlx_lm.server 2>/dev/null; sleep 2; python3 -m mlx_lm.server --model "$MODEL" --port 8080 > "$P/logs/server.log" 2>&1 &
  for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8080/v1/models >/dev/null && sleep 3 && return 0; sleep 2; done; echo "SERVER DID NOT COME UP"; return 1; }
snap() { cd "$WT" && rm -f evals/crm-followup/snapshot.json; t0=$(date +%s)
  if [ "$1" = adapter ]; then export MLX_ADAPTER_PATH="$P/adapters"; else unset MLX_ADAPTER_PATH; fi
  MLX_MODEL_PATH="$MODEL" python3 -u sandbox/runner.py run crm-followup --provider mlx --model default_model --snapshot --loads 3 --timeout 300 > "$P/logs/snap-$1.log" 2>&1; rc=$?
  echo "snapshot $1 rc=$rc wall=$(( $(date +%s) - t0 ))s"; grep -E 'load [123]/3|unstable|snapshot written|refus|Traceback' "$P/logs/snap-$1.log" | tail -5
  [ -f evals/crm-followup/snapshot.json ] && cp evals/crm-followup/snapshot.json "$P/snapshot-$1.json" && echo "snapshot -> snapshot-$1.json" || echo "NO SNAPSHOT for $1"; }
echo "=== base snapshot: REUSED from v3 (same evening, same stamp, reproduced v2 exactly) — no rerun ==="
echo "=== rule-A snapshot: adapter $(date +%T) ==="; serve && snap adapter
pkill -f mlx_lm.server 2>/dev/null; git -C "$WT" checkout -- evals/crm-followup/snapshot.json
echo "=== verdict $(date +%T) ==="; python3 "$P/compare.py"
echo "I2v4 DONE $(date '+%F %T')"
