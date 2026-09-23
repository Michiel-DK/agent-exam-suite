#!/bin/bash
# I2 v3 — augment the two-calls-in-ONE-turn shape. Worktree probe-i2v3 (detached at master 4da06df).
set -u; ROOT=${AGENT_SANDBOX_ROOT:-$HOME/code/Michiel-DK/agent-sandbox}; WT=$ROOT/.claude/worktrees/probe-i2v3; P=$ROOT/docs/probes/i2v3-crm-lora-2026-09-21
set -a; . "$ROOT/.env"; set +a   # OPENROUTER_API_KEY only for the conditional GLM pass; never echoed
MODEL=$(python3 -c "from huggingface_hub import snapshot_download as s; print(s('mlx-community/gemma-4-e2b-it-4bit'))")
cd "$WT"; echo "I2v3 START $(date '+%F %T') master=$(git rev-parse --short HEAD) ollama=$(ollama --version 2>&1 | tail -1)"
echo "=== (a) augment worktree cases $(date +%T) ==="
python3 "$P/augment_cases.py" "$WT" --selftest && python3 "$P/augment_cases.py" "$WT" || { echo "AUGMENT FAILED"; exit 2; }
echo "=== (b1) champion harvest via Ollama on committed+variants $(date +%T) ==="
python3 -u sandbox/runner.py run crm-followup --timeout 300 > "$P/logs/run-variants-champion.log" 2>&1; echo "rc=$?"; grep -E 'train +[0-9]+/|heldout +[0-9]+/' "$P/logs/run-variants-champion.log" | tail -1
cp results/crm-followup__ollama__gemma4-e2b-ctx16k.json "$P/results-variants-champion.json" && echo "champion results copied"; ollama stop gemma4-e2b-ctx16k 2>/dev/null
python3 - "$P/results-variants-champion.json" <<'PY'
import json,sys; r=json.load(open(sys.argv[1])); v=[c for c in r["cases"] if c["id"].startswith("v3aug-")]
print(f"variants passed {sum(1 for c in v if c.get('passed'))}/{len(v)}:", [ (c['id'][6:], len((c.get('detail') or {}).get('tool_results') or []), 'ok' if c.get('passed') else [f['check'] for f in (c.get('failed_checks') or [])]) for c in v])
PY
echo "=== (c) rows, floor 24 $(date +%T) ==="; cd "$P" && python3 build_data_crm_v3.py --selftest && python3 build_data_crm_v3.py; rc=$?
if [ $rc -eq 4 ]; then
  echo "=== (b2) floor missed → GLM-5.3 pinned z-ai pass on the variants (~\$0.30) $(date +%T) ==="; cd "$WT"
  python3 "$ROOT/docs/probes/provider-pin-day1-2026-09-01/set_pin.py" agents/crm-followup/agent.yaml z-ai
  python3 -u sandbox/runner.py run crm-followup --provider openrouter --model z-ai/glm-5.3 --timeout 300 > "$P/logs/run-variants-glm.log" 2>&1; echo "rc=$?"
  f=$(ls results/crm-followup__openrouter__z-ai_glm-5.3.json 2>/dev/null | head -1); [ -n "$f" ] && cp "$f" "$P/results-variants-glm.json" && echo "glm results copied" || echo "no glm results file"
  python3 "$ROOT/docs/probes/provider-pin-day1-2026-09-01/set_pin.py" agents/crm-followup/agent.yaml unset
  cd "$P" && python3 build_data_crm_v3.py; rc=$?
fi
echo "=== restore worktree cases.json $(date +%T) ==="; python3 "$P/augment_cases.py" "$WT" --restore || { echo "RESTORE FAILED"; exit 5; }
git -C "$WT" checkout -- agents/crm-followup/agent.yaml 2>/dev/null; git -C "$WT" status --short evals agents | grep . && { echo "WORKTREE NOT CLEAN — stopping"; exit 5; } || echo "worktree evals/agents clean"
[ $rc -eq 0 ] || { echo "ROWS NOT BUILT rc=$rc — stopping before training"; exit $rc; }
echo "=== (d) LoRA 250 iters $(date +%T) ==="; t0=$(date +%s)
python3 -m mlx_lm.lora --model "$MODEL" --train --data "$P/data" --fine-tune-type lora --num-layers 8 --batch-size 1 --iters 250 --learning-rate 1e-4 --max-seq-length 6144 --grad-checkpoint --adapter-path "$P/adapters" 2>&1 | tee "$P/logs/lora.log" | grep -E 'Iter [0-9]+: (Train|Val)|Saved|Trainable|Error|Traceback' | tail -8
echo "=== LoRA DONE wall=$(( $(date +%s) - t0 ))s $(date +%T) ==="; [ -f "$P/adapters/adapters.safetensors" ] || { echo "NO ADAPTER"; exit 3; }
serve() { pkill -f mlx_lm.server 2>/dev/null; sleep 2; python3 -m mlx_lm.server --model "$MODEL" --port 8080 > "$P/logs/server.log" 2>&1 &
  for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8080/v1/models >/dev/null && sleep 3 && return 0; sleep 2; done; echo "SERVER DID NOT COME UP"; return 1; }
snap() { cd "$WT" && rm -f evals/crm-followup/snapshot.json; t0=$(date +%s)
  if [ "$1" = adapter ]; then export MLX_ADAPTER_PATH="$P/adapters"; else unset MLX_ADAPTER_PATH; fi
  MLX_MODEL_PATH="$MODEL" python3 -u sandbox/runner.py run crm-followup --provider mlx --model default_model --snapshot --loads 3 --timeout 300 > "$P/logs/snap-$1.log" 2>&1; rc=$?
  echo "snapshot $1 rc=$rc wall=$(( $(date +%s) - t0 ))s"; grep -E 'load [123]/3|unstable|snapshot written|refus|Traceback' "$P/logs/snap-$1.log" | tail -5
  [ -f evals/crm-followup/snapshot.json ] && cp evals/crm-followup/snapshot.json "$P/snapshot-$1.json" && echo "snapshot -> snapshot-$1.json" || echo "NO SNAPSHOT for $1"; }
echo "=== rule-A snapshot: base $(date +%T) ==="; serve && snap base
echo "=== rule-A snapshot: adapter $(date +%T) ==="; snap adapter
pkill -f mlx_lm.server 2>/dev/null; git -C "$WT" checkout -- evals/crm-followup/snapshot.json
echo "=== verdict $(date +%T) ==="; python3 "$P/compare.py"
echo "I2v3 DONE $(date '+%F %T')"
