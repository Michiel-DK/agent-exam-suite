#!/bin/bash
# E31 — NIGHT RESCOPE (2026-09-15), per STATUS-paused-2026-09-10.md retrigger plan.
#   stage 1: gemma pair @16k on crm-followup   (gemma4-e4b-ctx16k 6.1 GB vs -plain 9.6 GB)
#   stage 2: qwen pair @4k  on task-intake     (qwen3:8b vs qwen3:8b-q8_0 — library tags,
#            default window; the killed q8 arm was q8 + a 16k KV cache)
# Window held FIXED per pair; the model axis is the only axis. Rule-A snapshots (3 loads).
# WATCHDOG: the 4-bit arm of each pair runs first and its wall is measured; the bigger
# arm is killed if it exceeds 4x that wall or ABS_CAP, whichever is smaller — the q8@16k
# arm ran 14x slower per case (8h38m, 7 ReadTimeouts) before anyone looked. A killed arm
# is itself the finding (size-vs-window wall at a second size point); it is logged as such.
# Fresh worktree from master (NOT probe-e6-ab: 14 behind, dirty snapshots, library.json).
#   nohup bash docs/probes/e31-quantisation-2026-09-09/e31-night.sh > docs/probes/e31-quantisation-2026-09-09/logs/e31-night.log 2>&1 &
set -u
WT=/Users/michieldekoninck/code/Michiel-DK/agent-sandbox/.claude/worktrees/probe-e31
OUT=/Users/michieldekoninck/code/Michiel-DK/agent-sandbox/docs/probes/e31-quantisation-2026-09-09
ABS_CAP=$((5*3600))   # seconds
cd "$WT" || exit 1
echo "E31-night START $(date '+%F %T') ollama=$(ollama --version 2>&1 | tail -1)"

run_arm() {  # exam tag cap_seconds -> prints wall seconds on stdout (last line)
  local exam=$1 tag=$2 cap=$3 t0 rc wall
  echo "=== E31 $exam @ $tag START $(date +%T) cap=${cap}s ==="
  rm -f "evals/$exam/snapshot.json"
  t0=$(date +%s)
  python3 -u sandbox/runner.py run "$exam" --model "$tag" --snapshot --loads 3 --timeout 900 &
  local pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if [ $(( $(date +%s) - t0 )) -gt "$cap" ]; then
      echo "=== WATCHDOG: $exam @ $tag exceeded ${cap}s — KILLED $(date +%T) (this is the finding, not a crash) ==="
      kill "$pid" 2>/dev/null; sleep 5; kill -9 "$pid" 2>/dev/null
      ollama stop "$tag" 2>/dev/null
      break
    fi
    sleep 30
  done
  wait "$pid" 2>/dev/null; rc=$?
  wall=$(( $(date +%s) - t0 ))
  echo "=== $exam @ $tag rc=$rc wall=${wall}s $(date +%T) ==="
  if [ -f "evals/$exam/snapshot.json" ]; then
    cp "evals/$exam/snapshot.json" "$OUT/$exam.$tag.json"
  else
    echo "=== $exam @ $tag NO SNAPSHOT WRITTEN (refused, killed or crashed) ==="
  fi
  echo "$wall"
}

pair() {  # exam small_tag big_tag
  local exam=$1 small=$2 big=$3 w cap
  w=$(run_arm "$exam" "$small" "$ABS_CAP" | tee /dev/stderr | tail -1)
  cap=$(( w * 4 )); [ "$cap" -gt "$ABS_CAP" ] && cap=$ABS_CAP
  [ "$cap" -lt 1800 ] && cap=1800
  run_arm "$exam" "$big" "$cap" | tee /dev/stderr | tail -1 >/dev/null
}

pair crm-followup gemma4-e4b-ctx16k gemma4-e4b-ctx16k-plain
pair task-intake  qwen3:8b          qwen3:8b-q8_0
echo "E31-night DONE $(date '+%F %T')"
