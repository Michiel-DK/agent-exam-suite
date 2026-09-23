#!/bin/bash
set -u; ROOT=${AGENT_SANDBOX_ROOT:-$HOME/code/Michiel-DK/agent-sandbox}; P=$ROOT/docs/probes/i0b-champion-thinking-2026-09-20
echo "I0c START $(date '+%F %T')"; MODEL=$(python3 -c "from huggingface_hub import snapshot_download as s; print(s('mlx-community/gemma-4-e2b-it-4bit'))")
pkill -f mlx_lm.server 2>/dev/null; sleep 2; python3 -m mlx_lm.server --model "$MODEL" --port 8080 > "$P/logs/server-i0c.log" 2>&1 &
for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8080/v1/models >/dev/null && sleep 3 && break; sleep 2; done
python3 -u "$P/thinking_switch_probe.py" 2>&1 | grep -vE 'Fetching|Warning|warn'; echo "probe rc=$?"
pkill -f mlx_lm.server 2>/dev/null; echo "I0c DONE $(date '+%F %T')"
