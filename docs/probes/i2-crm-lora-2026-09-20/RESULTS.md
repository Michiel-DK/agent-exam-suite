# I2 — LoRA on the crm champion family from replayed passing TRAIN trajectories (2026-09-20)

> **EVIDENCE CELL:** `crm-followup @ mlx-community/gemma-4-e2b-it-4bit via mlx_lm.server, base` **vs** `+ LoRA (8 layers, 100 iters, 11 replayed passing single-turn TRAIN trajectories)`, both through `runner.py run --provider mlx`, one pass each, 38 cases: **heldout 12/18 → 12/18 but 2 up / 3 down; train 16/20 → 13/20 (1 up / 4 down, two of the downs ARE training rows); completion tokens 13,807 → 3,465 (−75%), reasoning chars 35,590 → 0, wall 299 s → 146 s.** Prediction 2 ("heldout holds, 0 down") **REFUTED**; the kill ("any stable heldout case down") would fire on the rule-A snapshot, so it was not run.
>
> **Not evidence:** the train score (the rows ARE the train cases); I0b(b)'s one-pass base read.

## Registered before the run (20 Sep, before `logs/i2.log` START)
- Rows: the champion's passing single-turn train trajectories + the local 14B's for the ones the champion fails; multi-turn train cases skipped (per-turn answers are not stored — declared); heldout untouched, guard seen red first.
- **Prediction:** (1) training fits in memory at max-seq 6144 / batch 1 / grad-checkpoint and finishes < 30 min; (2) adapter base-vs-adapter: heldout **holds** (0 down) on the one-pass read — small N, one pass, no gain predicted; (3) the multi-turn heldout cases (not in training) are where a loss would show first — if ≥2 of them go down, the single-turn-only training set is the cause to name.
- **Kill:** training OOM/does not finish; any stable heldout case down on the rule-A snapshot.

## What ran (20 Sep, 15:38–16:08)

| step | result |
|---|---|
| data | `build_data_crm.py`: 11 rows (9 train / 2 valid) = the champion's 9 passing single-turn train trajectories + the 14B's for 2 more; `redundant-retry-outage` had no passing trajectory anywhere; 8 multi-turn train cases skipped (per-turn answers are not stored). Guard seen RED on a planted heldout row; 5 declared overlaps (heldout question text that is verbatim inside committed train inputs — the outage variants), recorded in `data/provenance.json`. Median row 6,078 chars, max 16,200 |
| LoRA | 8 layers, batch 1, 100 iters, max-seq 6144, grad-checkpoint → **21 min 50 s**, train loss 0.005 (memorised), val loss 0.31, **peak mem 18.1 GB on a 16 GB box (swapping)** |
| base arm | train 16/20 · heldout 12/18, 299 s (`results-base.json`) — reproduces I0b(b) exactly |
| adapter arm | train 13/20 · heldout 12/18, 146 s (`results-adapter.json`) |

**Per case, adapter vs base.** Up 3: `redundant-retry-outage` (train, the case with no training row), `redundant-retry-outage-deals` (heldout), `mid-thread-switch-referential-callback` (heldout, multi-turn). Down 6: `two-tool-combo` (heldout), `active-client-stage` (heldout), `briefing-devos` (train, **a training row**), `portfolio-status-check` (train, **a training row**), `decoy-owner-after-deals-janssens` (train, multi-turn), `long-thread-recap-with-outage-train` (train, multi-turn).

**Mechanism, from the failure strings:** 3 of the 6 downs read `never called tool 'deals_list'` — the adapter answers after ONE tool call. 9 of the 11 training rows are single-lookup trajectories, so the adapter learned "one lookup, then answer" and stopped making the second call the two-tool cases need. Two training rows themselves went down (`briefing-devos`, `portfolio-status-check`): at loss 0.005 on 9 rows the adapter memorised strings, not the procedure, and the memorised answer lacks the numbers the grader wants when the served context differs by a token. The multi-turn losses are the declared risk (prediction 3): no multi-turn rows in training.

**What held, again:** the thinking channel is gone (35,590 → 0 reasoning chars), **−75% completion tokens, 2× wall** — the same effect as I0, now on a trajectory exam. Prompt tokens also fell (203,919 → 167,887) because fewer steps were taken — which is the failure.

## Verdicts
| registered | verdict |
|---|---|
| (1) fits in memory, < 30 min | **Held on time (21:50), not on memory** — peak 18.1 GB > 16 GB physical; it swapped and finished. A 16 GB client box can train this, slowly |
| (2) heldout holds, 0 down, one pass | **REFUTED** — 3 heldout cases down (2 up), net 12/18 = 12/18 hides it; rule A would refuse |
| (3) multi-turn heldout is where a loss shows first | Not as predicted — the two multi-turn heldout cases went 1 up / 0 down; the losses are single-turn TWO-TOOL cases |
| kill: OOM / no finish | did not fire (swap) |
| kill: any stable heldout down on the snapshot | **would fire** — snapshot not run, refutation stands on the one-pass read |

## What this changes
- **I2 as scoped (replay passing single-turn train trajectories) does not produce a crm champion candidate.** The training set is the cause to name: 11 rows, 9 of them one-tool, 0 multi-turn. The loop itself worked end to end again (data → LoRA → served → real runner → refuted by the exam).
- **Next I2 attempt needs different DATA, not different training:** (a) multi-tool and multi-turn trajectories — requires the runner to store per-turn `got` (a small `full`-file change) or a teacher run that logs full message lists; (b) more rows — variants of the train cases with tool fixtures kept consistent, or a hosted teacher over the failing train cases; (c) a row-count floor before training (a distillation vendor quotes ≥32 tasks; our 11 confirms why).
- The −75% token / 2× wall effect is now measured on two exams. It is the fine-tune line for the page once a variant HOLDS heldout.

## What this cannot say
- One pass per arm; no rule-A snapshot (refused by prediction). The 3 heldout downs could include a flip on a re-run — but 3 at once, all with the same `never called deals_list` signature, is a mechanism, not noise.
- Nothing about the champion on Ollama; both arms are the MLX post-hoc 4-bit build (base heldout 12/18 vs the champion's 15/18 — E31b/I0b already showed the QAT-vs-plain gap at e2b).
