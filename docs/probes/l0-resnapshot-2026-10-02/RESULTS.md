# L0 — re-snapshot of all 8 exams at Ollama 0.35.0 (RAN 2 Oct 2026 18:25–20:55, unattended, $0)

> **EVIDENCE CELL:** the per-case diff below — 0.33.2 → 0.35.0 moved **1 of 220 cases** (`recap-end-of-day`, task-intake,
> TRAIN, fail → pass), **0 held-out cases, 0 unstable** on every exam. The gate debt from the 30 Sep upgrade is cleared: `check`
> runs again on all eight.
>
> **Not evidence:** the wall times (one laptop, other work running beside it); the one train flip (a single case on one
> load-triple; the gate ignores train).

**How:** `l0.sh` (this folder) from a clean master worktree at `84b6973` — never the shared checkout, which sits on
`lane/systemone-tier` with a modified `runner.py`. Per exam: `python3 -u sandbox/runner.py run <agent> --snapshot --loads 3`
(rule A: three fresh loads at temperature 0; a case is stable iff all three agree). Champion models unchanged
(`agent.yaml` untouched). Every snapshot now carries `runtime.version = 0.35.0`.

## Per-case diff, committed 0.33.2 snapshot → new 0.35.0 snapshot (same case sets, same models)

| exam | model | held-out old → new | train old → new | unstable old → new | cases moved |
|---|---|---|---|---|---|
| expense-categorization | gemma4:e2b-it-qat | 8/9 → 8/9 | 6/6 → 6/6 | 0 → 0 | none |
| email-triage | gemma4:e2b-it-qat | 10/11 → 10/11 | 7/8 → 7/8 | 0 → 0 | none |
| reply-draft | gemma4:e2b-it-qat | 10/10 → 10/10 | 7/7 → 7/7 | 0 → 0 | none |
| recap | gemma4:e4b-it-qat | 7/10 → 7/10 | 3/7 → 3/7 | 0 → 0 | none |
| task-intake | gemma4:e2b-it-qat | 21/22 → 21/22 | 24/28 → 25/28 | 0 → 0 | recap-end-of-day (train: F→P) |
| call-fields | gemma4-e4b-ctx16k | 14/19 → 14/19 | 10/13 → 10/13 | 0 → 0 | none |
| crm-followup | gemma4-e2b-ctx16k | 15/18 → 15/18 | 12/20 → 12/20 | 0 → 0 | none |
| transcript-en | gemma4-e4b-ctx16k | 10/19 → 10/19 | 7/13 → 7/13 | 0 → 0 | none |

cases up 1, down 0.

## Wall per exam (3 loads each; laptop in use beside it)

```
=== expense-categorization rc=0 wall=180s 2026-10-02T18:28:02+01:00
=== email-triage rc=0 wall=318s 2026-10-02T18:33:20+01:00
=== reply-draft rc=0 wall=408s 2026-10-02T18:40:08+01:00
=== recap rc=0 wall=1454s 2026-10-02T19:04:22+01:00
=== task-intake rc=0 wall=952s 2026-10-02T19:20:14+01:00
=== call-fields rc=0 wall=1944s 2026-10-02T19:52:38+01:00
=== crm-followup rc=0 wall=1406s 2026-10-02T20:16:04+01:00
=== transcript-en rc=0 wall=2385s 2026-10-02T20:55:49+01:00
```

**What it says:** this runtime bump did not re-roll a single held-out verdict on these champions, unlike 0.33.2 on 31 Aug
(5 of 22 transcript-en verdicts moved in both directions). The gate is what tells the two apart; the result is one data point,
not a rule — the next bump gets the same evening.
