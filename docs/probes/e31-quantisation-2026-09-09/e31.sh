#!/bin/sh
# E31 quantisation ladder — 4 tags x 2 exams x 3 loads, rule-A snapshots as the
# noise floor + flip source. Brief: docs/e31-quantisation-bakeoff-brief-2026-09-09.md
# (prepped 9 Sep: tags pulled + verified, ctx16k clones created — STEPS.md).
# Window held FIXED per pair via the ctx16k clones; the model axis is the only axis.
# Runs in the probe worktree (snapshot.json there is disposable); each tag's
# aggregate is copied aside as <exam>.<tag>.json. snapshot.json is REMOVED before
# each run so a refused/failed arm can never silently hand the previous tag's
# file to the copy (refuse_snapshot_on_outage sys.exits mid-arm).
ROOT=${AGENT_SANDBOX_ROOT:-$HOME/code/Michiel-DK/agent-sandbox}
WT=$ROOT/.claude/worktrees/probe-e6-ab
OUT=$ROOT/docs/probes/e31-quantisation-2026-09-09
cd "$WT" || exit 1
for exam in task-intake crm-followup; do
  for tag in qwen3-8b-ctx16k qwen3-8b-ctx16k-q8 gemma4-e4b-ctx16k gemma4-e4b-ctx16k-plain; do
    echo "=== E31 $exam @ $tag $(date +%H:%M:%S) ==="
    rm -f "evals/$exam/snapshot.json"
    python3 -u sandbox/runner.py run "$exam" --model "$tag" --snapshot --loads 3 --timeout 900
    rc=$?
    echo "=== $exam @ $tag rc=$rc ==="
    if [ -f "evals/$exam/snapshot.json" ]; then
      cp "evals/$exam/snapshot.json" "$OUT/$exam.$tag.json"
    else
      echo "=== $exam @ $tag NO SNAPSHOT WRITTEN (refused or crashed) ==="
    fi
  done
done
echo "E31 DONE $(date +%H:%M:%S)"
