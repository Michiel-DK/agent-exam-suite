# I2 v2 — the data lane: crm LoRA from replayed single- AND multi-turn passing TRAIN trajectories (2026-09-21)

> **EVIDENCE CELL:** `crm-followup @ gemma-4-e2b-it-4bit via mlx_lm.server, base` **vs** `+ LoRA (8 layers, 150 iters, 16 rows: 12 from the champion's per-turn traces + 4 from one pinned GLM-5.3 pass)`, both **rule-A snapshots** (3 samples each, 0/38 unstable on both, mlx stamp version 0.31.3 / model_sha 35f96acf / adapter_sha None vs 3872f543): **heldout 12/18 → 12/18 with 2 up / 2 down — two STABLE heldout cases down (`two-tool-combo`, `active-client-stage`) → the registered kill FIRES. REFUTED**, one step closer than v1 (3 down, two training rows down) — no training row moved down this time. Train 16/20 → 17/20.
>
> **Not evidence:** the train score (the rows are the train cases); the champion and GLM passes themselves (data harvest, one pass each, hosted probe-grade).

## Registered before the run (21 Sep, before `logs/i2v2.log` START)
- **Data:** champion rerun on Ollama (PR #96 traces) supplies single- and multi-turn rows; GLM-5.3 pinned to `z-ai` supplies rows for train cases the champion fails; the two cases no local model ever passed may get a GLM row or none. **Row floor 16** — below it, no training, reported as such.
- **Prediction:** (1) ≥16 rows, ≥5 multi-turn; (2) the v1 failure signature (`never called deals_list`) disappears — the two-tool heldout cases `two-tool-combo` and `active-client-stage` pass on the adapter; (3) **heldout holds under rule A: 0 stable cases down** vs the base snapshot; a gain is not predicted. (4) −70–80% completion tokens, ≥2× wall, again.
- **Kill:** any stable heldout case down on the adapter snapshot vs the base snapshot. Also kill: row floor not met.
- Base snapshot on mlx is itself new (first mlx rule-A snapshot ever; `loads_are_samples: true`).

## What ran (21 Sep, 10:35–11:53, ~$0.25 on the key → $1.19 left)

| step | result |
|---|---|
| (b1) champion rerun, Ollama, per-turn traces | train 12/20 · heldout 15/18 (= its committed snapshot), 7.5 min |
| (b2) GLM-5.3 pinned `z-ai`, one pass | train 14/20 · heldout 13/18, 8 min — 4 rows the champion could not supply |
| (c) rows | **16 = the floor** (12 champion, 4 GLM); 6 multi-turn; 4 train cases with NO passing trajectory from either source (`peeters-partial-invite-bait`, `redundant-retry-outage`, `peeters-contact-followup-outage`, `decoy-owner-after-deals-devos`); 5 declared overlaps; guard seen red |
| (d) LoRA | 150 iters, batch 1, max-seq 6144, grad-checkpoint → 37 min, val loss 0.08, peak 18.4 GB (swap) |
| base snapshot | 3 samples all 16/20 · 12/18, 15 min, stamp accepted |
| adapter snapshot | 3 samples all 17/20 · 12/18, 8.4 min, stamp accepted (adapter_sha stamped) |

**Per case, adapter vs base (both stable everywhere):** UP `redundant-retry-outage` (train — the one case with no training row; base fails it on a redundant call), `redundant-retry-outage-deals` (heldout, same), `mid-thread-switch-referential-callback` (heldout, multi-turn). **DOWN** `two-tool-combo` (heldout — `never called tool 'deals_list'`, the v1 signature, 3/3 samples) and `active-client-stage` (heldout — `unparseable … no final answer emitted`, the QAT-style format drop from E31). The two v1 downs that were `peeters-hedge-suppresses-lookup` and `crm-outage-mid-sweep` are unchanged (base fails them too).

**Mechanism, from the rows:** of 16 rows, 7 are single-turn with ≤1 tool call and only **3 single-turn rows carry ≥2 calls in one turn** (`(user turns, tool calls)` histogram: (1,0)·1 (1,1)·6 (1,2)·1 (1,3)·2 (2,2)·1 (3,2)·1 (3,3)·3 (4,3)·1). The multi-turn rows spread their calls across turns, one per turn. So "one call per user message" is still the dominant shape and the adapter still under-calls on a single-turn two-tool case. The redundancy behaviour, by contrast, DID transfer: the adapter stopped repeating identical lookups (2 up on exactly those cases).

## Verdicts
| registered | verdict |
|---|---|
| (1) ≥16 rows, ≥5 multi-turn | **Met**, exactly at the floor (16 / 6) |
| (2) the v1 signature disappears; `two-tool-combo` and `active-client-stage` pass | **Refuted** — `two-tool-combo` still `never called deals_list`; `active-client-stage` now a format drop |
| (3) heldout holds under rule A, 0 stable down | **REFUTED — 2 stable heldout cases down (kill fires)** |
| (4) −70–80% tokens, ≥2× wall | Held: adapter 4,071 completion tokens / 0 reasoning chars per sample (base ~13,800 / 35,600), snapshot wall 8.4 vs 15 min |

## What this changes
- **The loop is now fully gated:** first-ever rule-A snapshots on the mlx provider, stamps recorded, `unstable 0/38` on both arms — a fine-tuned candidate is judged exactly like any other model. The verdict it got is a refusal, which is the gate working.
- **v1 → v2 moved the right way** (heldout 3 down → 2 down; training rows down 2 → 0; redundancy behaviour transferred) without a gain. **Two residues are named:** (a) too few rows with ≥2 tool calls inside ONE turn — the training set needs augmentation on that exact shape (variants of `briefing-devos`/`two-tool`-style cases with the fixture kept consistent), not more rows in general; (b) 4 train cases have no passing trajectory anywhere — a stronger teacher (Kimi ~$0.65) might supply 1–3.
- **Cost of the residue:** the 16-row set was the floor; the honest next step is a v3 with (a) + a floor of 24, ~one GPU night + ≤$1. Whether that is worth doing before a client's data exists is the operator's call — on synthetic cases a fine-tune can still only show "holds", never "gains".

## What this cannot say
- Nothing about the Ollama champion (15/18): both arms are the MLX post-hoc 4-bit build, which sits at 12/18 base (E31b/I0b).
- The hosted GLM rows are probe-grade trajectories; they passed the exam's own checks, which is the only thing that qualifies a row.
