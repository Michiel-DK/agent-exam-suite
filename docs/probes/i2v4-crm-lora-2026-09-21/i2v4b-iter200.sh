#!/bin/bash
# I2 v4b — snapshot the iteration-200 checkpoint of the v4 adapter (val loss 0.29 there vs 0.40 at 400). No training.
set -u; ROOT=${AGENT_SANDBOX_ROOT:-$HOME/code/Michiel-DK/agent-sandbox}; WT=$ROOT/.claude/worktrees/probe-i2v4b; P=$ROOT/docs/probes/i2v4-crm-lora-2026-09-21
MODEL=$(python3 -c "from huggingface_hub import snapshot_download as s; print(s('mlx-community/gemma-4-e2b-it-4bit'))")
cd "$WT"; echo "I2v4b START $(date '+%F %T') master=$(git rev-parse --short HEAD)"
pkill -f mlx_lm.server 2>/dev/null; sleep 2; python3 -m mlx_lm.server --model "$MODEL" --port 8080 > "$P/logs/server-iter200.log" 2>&1 &
for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8080/v1/models >/dev/null && sleep 3 && break; sleep 2; done
rm -f evals/crm-followup/snapshot.json; t0=$(date +%s)
MLX_MODEL_PATH="$MODEL" MLX_ADAPTER_PATH="$P/adapters-iter200" python3 -u sandbox/runner.py run crm-followup --provider mlx --model default_model --snapshot --loads 3 --timeout 300 > "$P/logs/snap-iter200.log" 2>&1; rc=$?
echo "snapshot iter200 rc=$rc wall=$(( $(date +%s) - t0 ))s"; grep -E 'unstable|refus|Traceback' "$P/logs/snap-iter200.log" | tail -3
[ -f evals/crm-followup/snapshot.json ] && cp evals/crm-followup/snapshot.json "$P/snapshot-adapter-iter200.json" && echo "snapshot -> snapshot-adapter-iter200.json"
pkill -f mlx_lm.server 2>/dev/null; git -C "$WT" checkout -- evals/crm-followup/snapshot.json
cd "$P" && python3 - <<'PY'
import json
b=json.load(open("snapshot-base.json")); a=json.load(open("snapshot-adapter-iter200.json")); bc={c["id"]:c for c in b["cases"]}; ac={c["id"]:c for c in a["cases"]}
for split in ("train","heldout"): print(f"{split}: base {sum(1 for c in bc.values() if c['split']==split and c['passed'])} -> iter200 {sum(1 for c in ac.values() if c['split']==split and c['passed'])} of {sum(1 for c in bc.values() if c['split']==split)}")
up=[i for i in bc if ac[i]["passed"] and not bc[i]["passed"]]; down=[i for i in bc if bc[i]["passed"] and not ac[i]["passed"]]
print("UP:",up); print("DOWN:",down); print("stable heldout down:",[i for i in down if bc[i]["split"]=="heldout" and bc[i].get("stable",True) and ac[i].get("stable",True)])
print("unstable:", sum(1 for c in a["cases"] if not c.get("stable",True)), "adapter_sha:", (a.get("runtime") or {}).get("adapter_sha","")[:8])
PY
echo "I2v4b DONE $(date '+%F %T')"
