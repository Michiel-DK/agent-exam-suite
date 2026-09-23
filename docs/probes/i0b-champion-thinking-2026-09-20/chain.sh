#!/bin/bash
# I0b (2026-09-20): (a) same-day read of the Ollama champion's thinking spend on task-intake — the number the
# I0 "−85% output tokens" must be quoted against; (b) precondition for I2-on-crm: does the crm trajectory exam
# (tools in the request) pass through mlx_lm.server at all, base model, no adapter?
set -u
ROOT=${AGENT_SANDBOX_ROOT:-$HOME/code/Michiel-DK/agent-sandbox}; P=$ROOT/docs/probes/i0b-champion-thinking-2026-09-20
cd "$ROOT"; echo "I0b START $(date '+%F %T') ollama=$(ollama --version 2>&1 | tail -1)"
echo "=== (a) task-intake @ champion gemma4:e2b-it-qat via ollama, plain run $(date +%T) ==="
python3 -u sandbox/runner.py run task-intake --timeout 300 > "$P/logs/run-champion.log" 2>&1; rc=$?
grep -E 'train +[0-9]+/|heldout +[0-9]+/' "$P/logs/run-champion.log" | tail -1; echo "rc=$rc"
cp results/task-intake__ollama__gemma4_e2b-it-qat.json "$P/results-champion-ollama.json" 2>/dev/null && echo "results copied"
ollama stop gemma4:e2b-it-qat 2>/dev/null
echo "=== (b) crm-followup @ mlx base (no adapter) — precondition for I2 $(date +%T) ==="
MODEL=$(python3 -c "from huggingface_hub import snapshot_download as s; print(s('mlx-community/gemma-4-e2b-it-4bit'))")
pkill -f mlx_lm.server 2>/dev/null; sleep 2
python3 -m mlx_lm.server --model "$MODEL" --port 8080 > "$P/logs/server-crm.log" 2>&1 &
for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8080/v1/models >/dev/null && sleep 3 && break; sleep 2; done
rm -f results/crm-followup__mlx__*.json
python3 -u sandbox/runner.py run crm-followup --provider mlx --model default_model --timeout 300 > "$P/logs/run-crm-mlx.log" 2>&1; rc=$?
echo "crm via mlx rc=$rc"; grep -E 'train +[0-9]+/|heldout +[0-9]+/|Traceback|HTTPError|Error' "$P/logs/run-crm-mlx.log" | tail -3
f=$(ls results/crm-followup__mlx__*.json 2>/dev/null | head -1); [ -n "$f" ] && cp "$f" "$P/results-crm-mlx-base.json" && echo "crm results copied" || echo "no crm results file"
pkill -f mlx_lm.server 2>/dev/null; echo "I0b DONE $(date '+%F %T')"
