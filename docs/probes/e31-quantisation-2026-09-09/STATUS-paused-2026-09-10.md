> **SUPERSEDED 2026-09-17 — the night run RAN end to end; verdicts in `RESULTS.md` beside this file.**

# E31 — PAUSED 2026-09-10 09:35 (operator call), one arm complete, one arm killed

> **EVIDENCE CELL:** none yet — arm 1 (`task-intake @ qwen3-8b-ctx16k`, 3 loads) is a baseline with no pair. The killed q8@16k arm is a *speed* finding (14× per case, 7 timeouts), never a score. Pairs arrive with `e31-night.sh`.

## State

- ✅ **Arm 1 complete:** `task-intake @ qwen3-8b-ctx16k` (4-bit), 3 loads, 39 min,
  snapshot saved (`task-intake.qwen3-8b-ctx16k.json`).
- ⛔ **Arm 2 killed at 8h38m:** `task-intake @ qwen3-8b-ctx16k-q8` (8-bit) had finished
  only ~44 of 138 case-runs (32 pass / 12 fail, 7 of them 900-s ReadTimeouts) —
  **~14× slower per case than the 4-bit arm** (~12 min vs ~0.85 min). Even at
  completion the snapshot would have been REFUSED (`refuse_snapshot_on_outage`,
  timeout deaths). Killed 09:33, model unloaded. Arms 3–8 never started.

## The finding the dead arm already gives us

**Q8_0 (8.9 GB weights) + a 16k window does not run at usable speed on this 16 GB
machine.** The 4-bit tag at the identical window and exam is 14× faster. This is
a direct answer to the customer-hardware question the brief exists for: on
16 GB-class hardware, 8-bit at long windows is not a real option, regardless of
what it scores. (⚠️ mechanism unverified — consistent with memory pressure /
swap from weights + 16k KV cache, but not instrumented.)

## Retrigger plan (operator picks; nothing fires without "go")

1. **Preferred: re-scope the qwen pair to the DEFAULT 4k window for task-intake** —
   the window rule is *held fixed per pair*, not "always 16k"; task-intake's own
   champion runs at 4k and its inputs fit. `run task-intake --model qwen3:8b` vs
   `--model qwen3:8b-q8_0` (library tags, both 4k) — q8 without the 16k KV may be
   usable. crm (needs 16k) then runs the gemma pair only.
2. **Gemma pair as scheduled** (`gemma4-e4b-ctx16k` 6.1 GB vs `-plain` 9.6 GB): the
   plain tag at 16k may hit the same wall as q8 — watch the first load's pace and
   kill early if ~10× slow; that repeat would confirm the size-vs-window wall at a
   second size point.
3. Rerun script: edit `e31.sh`'s tag/exam loops per the picked scope; arm 1's
   snapshot is reusable (same runtime 0.33.2) if the rerun happens while 0.33.2
   is still the runtime — else rerun arm 1 too (rule A).

Log of the killed run: `logs/e31.log` (kept verbatim).

## Night rescope prepared 2026-09-15 (operator: "we can run E31 at night") — NOT yet fired

`e31-night.sh` in this directory: stage 1 = gemma pair @16k on crm-followup (what the operator
asked about; the gemma arms NEVER ran on 10 Sep — only the qwen q8 arm was killed), stage 2 =
qwen pair at the default 4k window on task-intake (retrigger option 1). Fresh worktree
`.claude/worktrees/probe-e31` from master `8d4d139` (the E6 probe worktree is 14 behind and
carries `library.json` files). Watchdog: the 4-bit arm runs first, the bigger arm is killed at
4× its wall or 5 h — a kill IS the finding. Ollama still 0.33.2, so arm 1
(`task-intake.qwen3-8b-ctx16k.json`) stays reusable under rule A. Fire with:

    nohup bash docs/probes/e31-quantisation-2026-09-09/e31-night.sh > docs/probes/e31-quantisation-2026-09-09/logs/e31-night.log 2>&1 &

Bash background jobs in a Claude session die at 10 min — `nohup` from a real shell (`! ` prefix).
