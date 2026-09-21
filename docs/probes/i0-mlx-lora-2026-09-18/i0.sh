#!/bin/bash
# I0 — sprint I feasibility spike: LoRA a 2B on this 16 GB Mac, serve it, sit ONE exam through the REAL runner.
# Kill: training > 2 h, or the served model cannot pass through `runner.py run`. Score is reported, not claimed.
set -u
ROOT=/Users/michieldekoninck/code/Michiel-DK/agent-sandbox
WT=$ROOT/.claude/worktrees/lane-mlx-provider        # carries the one-line "mlx" PROVIDERS entry
P=$ROOT/docs/probes/i0-mlx-lora-2026-09-18
MODEL=$(python3 -c "from huggingface_hub import snapshot_download as s; print(s('mlx-community/gemma-4-e2b-it-4bit'))")
echo "I0 START $(date '+%F %T') model=$MODEL mlx_lm=$(python3 -c 'import mlx_lm;print(mlx_lm.__version__)')"
cd "$P" && python3 build_data.py --selftest && python3 build_data.py || { echo "DATA/GUARD FAILED"; exit 2; }

serve() {  # adapter-or-empty -> starts server, waits for /v1/models
  pkill -f 'mlx_lm.server' 2>/dev/null; sleep 2
  if [ -n "$1" ]; then python3 -m mlx_lm.server --model "$MODEL" --adapter-path "$1" --port 8080 > "$P/logs/server-$2.log" 2>&1 &
  else python3 -m mlx_lm.server --model "$MODEL" --port 8080 > "$P/logs/server-$2.log" 2>&1 & fi
  for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8080/v1/models >/dev/null && return 0; sleep 2; done
  echo "SERVER DID NOT COME UP ($2)"; return 1
}
run_exam() {  # tag -> runs task-intake through the real runner against the mlx provider
  cd "$WT" && python3 -u sandbox/runner.py run task-intake --provider mlx --model gemma-4-e2b-it-4bit --timeout 300 2>&1 | tee "$P/logs/run-$1.log" | grep -E 'train|heldout|Traceback|Error' | tail -4
  cp "$WT/results/task-intake__mlx__gemma-4-e2b-it-4bit.json" "$P/results-$1.json" 2>/dev/null || echo "no results file for $1"
}

echo "=== ARM base (no adapter) $(date +%T) ==="; serve "" base && run_exam base
echo "=== LoRA train START $(date +%T) ==="; t0=$(date +%s)
python3 -m mlx_lm.lora --model "$MODEL" --train --data "$P/data" --fine-tune-type lora --num-layers 8 --batch-size 2 --iters 120 --learning-rate 1e-4 --max-seq-length 1536 --adapter-path "$P/adapters" 2>&1 | tee "$P/logs/lora.log" | grep -E 'Iter|Val loss|Saved|Trainable|Error|Traceback' | tail -8
echo "=== LoRA train DONE wall=$(( $(date +%s) - t0 ))s $(date +%T) ==="
echo "=== ARM adapter $(date +%T) ==="; serve "$P/adapters" adapter && run_exam adapter
pkill -f 'mlx_lm.server' 2>/dev/null
echo "I0 DONE $(date '+%F %T')"
