#!/bin/bash
# I0 arms, take 2 — the runner must send model="default_model": mlx_lm.server maps that to the CLI --model
# AND the CLI --adapter-path (server.py _model_map/_adapter_map); any other string is treated as a repo id
# to load fresh (404 for a bare name, adapter silently dropped for the HF id). Base and adapter arms.
set -u
ROOT=${AGENT_SANDBOX_ROOT:-$HOME/code/Michiel-DK/agent-sandbox}
WT=$ROOT/.claude/worktrees/lane-mlx-provider
P=$ROOT/docs/probes/i0-mlx-lora-2026-09-18
MODEL=$(python3 -c "from huggingface_hub import snapshot_download as s; print(s('mlx-community/gemma-4-e2b-it-4bit'))")
echo "I0-ARMS START $(date '+%F %T')"
serve() { pkill -f 'mlx_lm.server' 2>/dev/null; sleep 2
  if [ -n "$1" ]; then python3 -m mlx_lm.server --model "$MODEL" --adapter-path "$1" --port 8080 > "$P/logs/server2-$2.log" 2>&1 &
  else python3 -m mlx_lm.server --model "$MODEL" --port 8080 > "$P/logs/server2-$2.log" 2>&1 & fi
  for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8080/v1/models >/dev/null && sleep 3 && return 0; sleep 2; done
  echo "SERVER DID NOT COME UP ($2)"; return 1; }
run_exam() { cd "$WT" && rm -f results/task-intake__mlx__*.json
  t0=$(date +%s); python3 -u sandbox/runner.py run task-intake --provider mlx --model default_model --timeout 300 > "$P/logs/run2-$1.log" 2>&1; rc=$?
  echo "arm $1 rc=$rc wall=$(( $(date +%s) - t0 ))s"; grep -E 'train +[0-9]+/|heldout +[0-9]+/|Traceback|HTTPError' "$P/logs/run2-$1.log" | tail -3
  f=$(ls results/task-intake__mlx__*.json 2>/dev/null | head -1); [ -n "$f" ] && cp "$f" "$P/results-$1.json" && echo "results -> $P/results-$1.json" || echo "no results file for $1"; }
echo "=== ARM base $(date +%T) ==="; serve "" base && run_exam base
if [ -f "$P/adapters/adapters.safetensors" ]; then echo "=== ARM adapter $(date +%T) ==="; serve "$P/adapters" adapter && run_exam adapter; else echo "=== NO ADAPTER FILE — training did not finish ==="; fi
pkill -f 'mlx_lm.server' 2>/dev/null
echo "I0-ARMS DONE $(date '+%F %T')"
