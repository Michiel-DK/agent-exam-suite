#!/bin/bash
# I0 adapter arm, take 3 — the router now sends "adapters" from MLX_ADAPTER_PATH (lane worktree).
set -u
ROOT=/Users/michieldekoninck/code/Michiel-DK/agent-sandbox; WT=$ROOT/.claude/worktrees/lane-mlx-provider; P=$ROOT/docs/probes/i0-mlx-lora-2026-09-18
MODEL=$(python3 -c "from huggingface_hub import snapshot_download as s; print(s('mlx-community/gemma-4-e2b-it-4bit'))")
echo "I0-ADAPTER START $(date '+%F %T')"; pkill -f mlx_lm.server 2>/dev/null; sleep 2
python3 -m mlx_lm.server --model "$MODEL" --port 8080 > "$P/logs/server4-adapter.log" 2>&1 &
for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8080/v1/models >/dev/null && sleep 3 && break; sleep 2; done
cd "$WT" && rm -f results/task-intake__mlx__*.json; t0=$(date +%s)
MLX_ADAPTER_PATH="$P/adapters" python3 -u sandbox/runner.py run task-intake --provider mlx --model default_model --timeout 300 > "$P/logs/run3-adapter.log" 2>&1; rc=$?
echo "arm adapter(take3) rc=$rc wall=$(( $(date +%s) - t0 ))s"; grep -E 'train +[0-9]+/|heldout +[0-9]+/|Traceback|HTTPError' "$P/logs/run3-adapter.log" | tail -3
f=$(ls results/task-intake__mlx__*.json 2>/dev/null | head -1); [ -n "$f" ] && cp "$f" "$P/results-adapter.json" && echo "results -> $P/results-adapter.json" || echo "no results file"
pkill -f mlx_lm.server 2>/dev/null; echo "I0-ADAPTER DONE $(date '+%F %T')"
