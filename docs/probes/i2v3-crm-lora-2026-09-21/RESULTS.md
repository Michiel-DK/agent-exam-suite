# I2 v3 — augment the two-calls-in-ONE-turn shape (2026-09-21, evening)

> **EVIDENCE CELL:** `crm-followup @ gemma-4-e2b-it-4bit via mlx_lm.server, base` **vs** `+ LoRA (8 layers, 250 iters, 30 rows: v2's 16 + 14 replayed v3aug-* variant rows, 17/30 with ≥2 calls in one turn)`, both **rule-A snapshots** (3 samples each, 0/38 unstable on both, mlx 0.31.3 / model_sha 35f96acf / adapter_sha None vs f6c637d4): **heldout 12/18 → 11/18, 4 up / 5 down — THREE stable heldout cases down (`two-tool-combo`, `active-client-stage`, `no-deals-known-company`) and, for the first time, two TRAINING rows down (`briefing-devos`, `portfolio-status-check`) → the registered kill FIRES. REFUTED**, and the mechanism is now named: the adapter emits an answer after the first tool result on the very rows it was trained on at train loss 0.005 — the loss was over every token (no prompt mask), so the 4–5 KB tool payloads (95% of the characters), not the assistant decisions (5%), are what 250 iterations fit.
>
> **Not evidence:** the train score (the rows are the train cases and their variants); the champion harvest pass on the variants (data, one pass); the variants' own pass rate.

## Registered before the run (21 Sep, before `logs/i2v3.log` START — compare mtimes)

- **Residue this targets** (v2 RESULTS): only 3/16 rows carried ≥2 tool calls inside ONE user turn; the adapter still stopped after one call on exactly that shape (`two-tool-combo`: `never called deals_list`, 3/3 samples). Multi-turn already transferred; no multi-turn rows are added.
- **Data:** the 16 v2 rows, byte-identical sources (v2's champion + GLM results files) **+** rows replayed from PASSING trajectories of 20 new single-turn variant inputs (`variants.json`: 12 Janssens/Devos contact+deal pairs, 2 Vitrine with an empty deals list, 3 outage pairs on Mertens/Peeters, 3 two-company inputs needing 2–4 calls). Each variant needs ≥2 calls in one turn. Harvest = the Ollama champion (`gemma4-e2b-ctx16k`) on the worktree's augmented cases.json; if the floor is missed, one pinned GLM-5.3 pass on the same file (≤$0.30). The variants live ONLY in the worktree copy for the harvest and are restored before any snapshot; they are never committed to the exam.
- **Preflights, seen red:** (1) no variant input shares a 40-char window (stride 1) with any heldout input — `augment_cases.py --selftest` RED on a planted window; (2) the v2 leak guard on every written row — `build_data_crm_v3.py --selftest` RED on a planted heldout input; (3) `git status` on the worktree's `evals/` + `agents/` must be empty before the snapshots or the chain stops.
- **Row floor 24** — below it, no training, reported as such. **Valid split = the 2 alphabetically-last passing variant rows** (the target shape sits in valid; `briefing-devos` stays in train — in v2 it fell into valid by the `ids[:2]` rule).
- **Recipe:** v2's (8 layers, lr 1e-4, batch 1, max-seq 6144, grad-checkpoint) with **250 iters instead of 150** — epoch-matched, not iteration-matched: v2 = 150 iters over 14 train rows (~10.7 epochs); v3 expects ~26–30 train rows, 250 iters ≈ 8–10 epochs. Registered here so it cannot be tuned after the fact.
- **Prediction:** (1) ≥8 of 20 variants pass on the champion → ≥24 rows, and single-turn rows with ≥2 calls become **≥40% of all rows** (v2: 19%); (2) the v2 signature disappears on the adapter: `two-tool-combo` passes (calls both tools) — this is the one heldout case the whole probe is about; (3) **heldout holds under rule A: 0 stable heldout cases down** vs the base snapshot; (4) −70–80% completion tokens vs base, again.
- **Kill:** any heldout case stable on both arms, passed on base, failed on the adapter (`compare.py`). Also kill: floor not met; worktree not clean before the snapshots.
- **What a "hold" would and would not mean:** on synthetic cases a fine-tune can show "holds at −75% tokens", never "gains"; a 1-up on `two-tool-combo` at 0 down would be the first crm adapter that survives the gate, on N=18 heldout — inside the Wilson band, said as such.

## What ran (21 Sep, 16:06–17:43, $0 — no GLM pass was needed; `logs/i2v3.log`)

| step | result |
|---|---|
| (a) augment | 38 committed + 20 variants = 58 in the worktree copy; preflight RED on a planted window, then clean |
| (b1) champion harvest, Ollama, per-turn traces | 12 min; **variants 14/20 pass**. The 6 misses: 5 stopped after ONE call (`never called deals_list` — the champion itself under-calls this shape 5/20), 1 grounded-date miss on a 3-call answer |
| (c) rows | **30** (12 v2-champion, 4 v2-GLM, 14 v3-champion); histogram (turns,calls): (1,1)·7 **(1,2)·14** (1,3)·2 (1,4)·1 (2,2)·1 (3,2)·1 (3,3)·3 (4,3)·1 → **17/30 = 57% two-or-more calls in one turn** (v2: 3/16 = 19%); train 28 / valid 2 (the two last variants); 6 declared overlaps; row chars max 21,057 median 10,999; worktree restored, `evals/` + `agents/` clean before the snapshots |
| (d) LoRA | 250 iters, 63 min, train loss 0.005 at iter 190, val loss 0.152 at 250 (on the variant rows — a different valid set from v2's 0.084, not comparable), peak 18.4 GB |
| base snapshot | 3 samples all 16/20 · 12/18, 15.0 min, 0/38 unstable — reproduces v2's base exactly |
| adapter snapshot | 3 samples all 16/20 · 11/18, 7.2 min (2.1× faster wall — the only token-cost proxy this run; the mlx results file carries no per-case metrics), 0/38 unstable, adapter_sha stamped |

**Per case, adapter vs base (all stable, 3/3 samples each way):** UP `decoy-owner-after-deals-devos` (train, no training row exists for it), `redundant-retry-outage` (train), `redundant-retry-outage-deals` (heldout), `mid-thread-switch-referential-callback` (heldout) — the same redundancy/multi-turn transfer v2 showed. **DOWN** `two-tool-combo` (heldout: `never called deals_list`, answer missing 6500), `active-client-stage` (heldout: same, missing 'discovery'), `briefing-devos` (**train, its own training row is a two-call trajectory**: `never called deals_list`), `portfolio-status-check` (**train**, a 3-call row: one call then an answer covering one company of three), `no-deals-known-company` (heldout: answers "I was unable to retrieve any open deals" — not in the abstention vocabulary; a phrasing outside `answer_contains_any`, flagged, not excused).

## Verdicts
| registered | verdict |
|---|---|
| (1) ≥8/20 variants pass, ≥24 rows, ≥40% of rows with ≥2 calls in one turn | **Met**: 14/20, 30 rows, 57% |
| (2) `two-tool-combo` passes on the adapter | **Refuted** — same signature as v1 and v2, 3/3 samples |
| (3) heldout holds, 0 stable down | **REFUTED — 3 stable heldout down; kill fires** (v1 3 → v2 2 → v3 3) |
| (4) −70–80% tokens | Not measured (no metrics in the mlx results file); wall 2.1× faster is consistent with v2 |

## The mechanism, and why "more rows of the right shape" was the wrong lever
The serve-time prompt for `briefing-devos` is byte-identical to its training row up to and including the first tool result
(`detail.tool_results[0] == the row's tool_result`, verified); the row's next assistant message is `{"tool": "deals_list", …}`;
the adapter, at temperature 0 after 250 iterations that reached train loss 0.005, emits `{"answer": …}` there instead. A model
that had fit the assistant tokens of its own training rows could not do that. It fit the rest: `mlx_lm.lora` was run without
`--mask-prompt` in v1, v2 and v3, so the loss covered every token of every row — the system prompt, the user line and the
4–5 KB JSON tool payloads — of which the assistant's decisions are **5.0% of the characters** (measured by the v4 builder on these rows, 21 Sep night; an earlier draft of this line estimated ~1%). Train loss 0.005 is the payloads memorised. The
shape histogram was the wrong instrument: it counts what the rows contain, not what the loss sees.

`--mask-prompt` as shipped (mlx_lm 0.31.3, `tuner/datasets.py`: offset = tokens of `messages[:-1]`) masks everything before
the LAST message, so on a multi-step row it would train only the final answer — the calls would be masked too. The fix is a
data cut, not a flag: **one example per assistant step** (prompt = the history up to that step, completion = that one JSON
step) with the prompt masked — 30 rows → ~80 examples, every one of them a decision token sequence. Free, one GPU hour,
and the prediction is sharp: the training rows must replay (train ≥ 16/20 with `briefing-devos` and `portfolio-status-check`
passing) or the loop has a second defect.

## What this changes
- **The gate held three times; the loop is proven as an instrument and refuted as a recipe.** v1/v2/v3 all trained on
  payload-dominated loss; the "thin data" (v1) and "wrong shape" (v2) diagnoses were true observations and incomplete
  conclusions — gotcha 11, again. The I0 task-intake result (19→18, −87% tokens) stands: task-intake rows have no tool
  payloads, so the unmasked loss there was mostly assistant tokens.
- **Next, on a "go" (I2 v4, free):** per-step examples + masked prompt on the same 30 rows, same base, rule-A snapshots,
  same kill. No new data is needed. Not started — outside the queue that was authorised.
- **One-pager CRM row wording stays** ("does not hold yet"); the mechanism sentence can be added once v4 has run.

## What this cannot say
- Nothing about the Ollama champion (15/18 heldout); both arms are the MLX post-hoc 4-bit build at 12/18 base.
- Whether masking alone flips `two-tool-combo`: the champion itself under-calls this shape on 5/20 fresh inputs, so the
  teacher's own ceiling on the shape is ~75%, and a student can at best match the rows it was given.
