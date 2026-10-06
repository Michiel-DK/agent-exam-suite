#!/bin/bash
# L0 — re-snapshot all 8 exams at Ollama 0.35.0, from a clean master worktree (never the shared checkout on the lane branch).
cd "$1" || exit 2
echo "L0 start $(date -Iseconds) ollama=$(ollama --version 2>&1) head=$(git rev-parse --short HEAD)"
for a in expense-categorization email-triage reply-draft recap task-intake call-fields crm-followup transcript-en; do
  t0=$(date +%s); echo "=== $a start $(date -Iseconds)"
  python3 -u sandbox/runner.py run "$a" --snapshot --loads 3; rc=$?
  echo "=== $a rc=$rc wall=$(( $(date +%s) - t0 ))s $(date -Iseconds)"
done
echo "L0 done $(date -Iseconds)"
