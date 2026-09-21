#!/bin/bash
# I2 — LoRA on the crm champion family from replayed passing TRAIN trajectories; base vs adapter through the
# real runner (plain run ×1 first; the rule-A --snapshot with the mlx stamp runs once PR #94 is merged).
set -u; ROOT=/Users/michieldekoninck/code/Michiel-DK/agent-sandbox; P=$ROOT/docs/probes/i2-crm-lora-2026-09-20
MODEL=$(python3 -c "from huggingface_hub import snapshot_download as s; print(s('mlx-community/gemma-4-e2b-it-4bit'))")
echo "I2 START $(date '+%F %T')"; cd "$P" && python3 build_data_crm.py --selftest && python3 build_data_crm.py || { echo "DATA/GUARD FAILED"; exit 2; }
echo "=== LoRA train START $(date +%T) ==="; t0=$(date +%s)
python3 -m mlx_lm.lora --model "$MODEL" --train --data "$P/data" --fine-tune-type lora --num-layers 8 --batch-size 1 --iters 100 --learning-rate 1e-4 --max-seq-length 6144 --grad-checkpoint --adapter-path "$P/adapters" 2>&1 | tee "$P/logs/lora.log" | grep -E 'Iter|Val loss|Saved|Trainable|Error|Traceback|memory' | tail -8
echo "=== LoRA train DONE wall=$(( $(date +%s) - t0 ))s $(date +%T) ==="
[ -f "$P/adapters/adapters.safetensors" ] || { echo "NO ADAPTER — training failed"; exit 3; }
serve() { pkill -f mlx_lm.server 2>/dev/null; sleep 2; python3 -m mlx_lm.server --model "$MODEL" --port 8080 > "$P/logs/server-$1.log" 2>&1 &
  for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8080/v1/models >/dev/null && sleep 3 && return 0; sleep 2; done; echo "SERVER DID NOT COME UP"; return 1; }
run_arm() { cd "$ROOT" && rm -f results/crm-followup__mlx__*.json; t0=$(date +%s)
  if [ "$1" = adapter ]; then export MLX_ADAPTER_PATH="$P/adapters"; else unset MLX_ADAPTER_PATH; fi
  python3 -u sandbox/runner.py run crm-followup --provider mlx --model default_model --timeout 300 > "$P/logs/run-$1.log" 2>&1; rc=$?
  echo "arm $1 rc=$rc wall=$(( $(date +%s) - t0 ))s"; grep -E 'train +[0-9]+/|heldout +[0-9]+/|Traceback|HTTPError' "$P/logs/run-$1.log" | tail -2
  f=$(ls results/crm-followup__mlx__*.json 2>/dev/null | head -1); [ -n "$f" ] && cp "$f" "$P/results-$1.json" && echo "results -> results-$1.json" || echo "no results file"; }
echo "=== ARM base $(date +%T) ==="; serve base && run_arm base
echo "=== ARM adapter $(date +%T) ==="; run_arm adapter
pkill -f mlx_lm.server 2>/dev/null; echo "I2 DONE $(date '+%F %T')"
