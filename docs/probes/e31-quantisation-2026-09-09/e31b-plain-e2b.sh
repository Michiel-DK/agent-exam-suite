#!/bin/bash
# E31b — the lead from RESULTS.md (17 Sep): the crm champion gemma4-e2b-ctx16k is FROM the -it-qat tag.
# Does the QAT protocol drop (no final answer emitted) generalise to e2b? One arm, same window (16k),
# same exam, rule-A snapshot (3 loads). Comparator = the committed champion snapshot (15/18 heldout).
# The worktree's evals/crm-followup/snapshot.json is overwritten by the run; the main loop restores it after.
set -u
ROOT=${AGENT_SANDBOX_ROOT:-$HOME/code/Michiel-DK/agent-sandbox}
WT=$ROOT/.claude/worktrees/probe-e31
OUT=$ROOT/docs/probes/e31-quantisation-2026-09-09
echo "E31b START $(date '+%F %T') ollama=$(ollama --version 2>&1 | tail -1)"
ollama pull gemma4:e2b 2>&1 | tail -2 || { echo "PULL FAILED — gemma4:e2b not in the library; arm dropped, not substituted"; exit 2; }
printf 'FROM gemma4:e2b\nPARAMETER num_ctx 16384\n' > "$OUT/Modelfile.gemma4-e2b-ctx16k-plain"
ollama create gemma4-e2b-ctx16k-plain -f "$OUT/Modelfile.gemma4-e2b-ctx16k-plain" 2>&1 | tail -1
ollama show gemma4-e2b-ctx16k-plain | grep -E 'quantization|parameters' | head -2
cd "$WT" || exit 1
rm -f evals/crm-followup/snapshot.json
t0=$(date +%s)
echo "=== E31b crm-followup @ gemma4-e2b-ctx16k-plain START $(date +%T) ==="
python3 -u sandbox/runner.py run crm-followup --model gemma4-e2b-ctx16k-plain --snapshot --loads 3 --timeout 900
rc=$?
echo "=== crm-followup @ gemma4-e2b-ctx16k-plain rc=$rc wall=$(( $(date +%s) - t0 ))s $(date +%T) ==="
if [ -f evals/crm-followup/snapshot.json ]; then cp evals/crm-followup/snapshot.json "$OUT/crm-followup.gemma4-e2b-ctx16k-plain.json"; else echo "=== NO SNAPSHOT WRITTEN ==="; fi
echo "E31b DONE $(date '+%F %T')"
