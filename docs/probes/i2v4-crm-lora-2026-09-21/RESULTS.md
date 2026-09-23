# I2 v4 — v3's rows, one example per assistant step, prompt masked (2026-09-21, night)

> **EVIDENCE CELL:** `crm-followup @ gemma-4-e2b-it-4bit via mlx_lm.server, base` (v3's rule-A snapshot, reused: same evening, same stamp, case-for-case equal to v2's) **vs** `+ LoRA (8 layers, 400 iters, --mask-prompt, 96 per-step examples cut from v3's 28 train rows)`, rule-A adapter snapshot (3 samples, 0/38 unstable, mlx 0.31.3 / model_sha 35f96acf / adapter_sha e92eb96c): **heldout 12/18 → 9/18, 1 up / 7 down (4 stable heldout down) → the kill FIRES; train 16/20 → 13/20 with three training rows down → registered prediction (1) FAILS. REFUTED.** And yet the case the whole I2 line is about flipped: **`two-tool-combo` passes 3/3 for the first time on any adapter** (crm_lookup → deals_list → grounded answer), `briefing-devos` is back. The masked loss taught the second call; the per-step cut also taught "after a tool result, call again" without the stop condition — 3 of the 7 downs are the identical call repeated, 4 are loops that hit `max_steps` with no final answer.
>
> **Not evidence:** the train score; the loss-share numbers (a description of the data, not a result).

## Registered before the run (21 Sep, before `logs/i2v4.log` START — compare mtimes)

- **Hypothesis under test (from v3):** v1–v3 failed because the loss covered every token of payload-heavy rows, so the adapter fit the CRM payloads and not the assistant's decisions. Falsifier: with the loss on the decisions only, the adapter must at least replay its own training rows.
- **Data:** no new harvest. Each v3 row (train 28, valid 2) is cut into one example per assistant message: example = the history up to and including that step. `--mask-prompt` (mlx_lm 0.31.3: offset = tokens of `messages[:-1]`, generation prompt added) puts the loss on that one step. Every example is a prefix of a row that passed v3's leak guard, so the guard is inherited. The builder prints the character share the loss sees: whole-row (v1–v3 style) vs last-step (v4).
- **Recipe:** v3's (8 layers, lr 1e-4, batch 1, max-seq 6144, grad-checkpoint) + `--mask-prompt`, **400 iters** over ~75 train examples (~5 epochs; per-step examples repeat the long prefixes, so tokens per epoch roughly double — 400 is the wall-clock-bounded choice, registered here). Base snapshot reused from v3 (15 min saved; v3's base reproduced v2's base case-for-case, 0/38 unstable).
- **Prediction:** (1) **training rows replay**: train ≥ 16/20 with `briefing-devos` and `portfolio-status-check` passing (both were 3/3 down on v3) — if this fails, the loop has a second defect and masking was not the cause; (2) `two-tool-combo` passes (calls both tools) — the case the whole I2 line is about; (3) **heldout holds under rule A: 0 stable heldout down** vs base; a gain is not predicted; (4) wall ≤ v3's adapter (7.2 min for 3 samples) — no thinking.
- **Kill:** any heldout case stable on both arms, passed on base, failed on the adapter (`compare.py`). Also kill: prediction (1) fails.
- **Cost:** $0; one GPU hour-and-a-half.

### Amendment, registered before the RERUN (21 Sep, 19:4x — `logs/i2v4-attempt1-nan.log` is attempt 1)
- **Attempt 1 died silently:** `Train loss nan` from iter 30 (`logs/lora-attempt1-nan.log`), tokens/sec ~3 — mlx_lm printed NaN and kept training. Cause, measured with the model's tokenizer over all 103 examples: exactly one example (train #96, the 5th step = the final answer of the four-call single-turn variant `v3aug-two-company-contacts-deals`: 6,666 tokens, prompt 6,572) exceeds `--max-seq-length 6144`; truncation leaves it **zero target tokens** → NaN → the adapter is poisoned from that step on. No example has a zero target otherwise; none exceeds 8,192.
- **Change:** the builder drops any example over 6,144 tokens (rule registered here: 1 example, train 97 → 96; the other 4 examples of that row stay); the chain kills training on the first NaN line and refuses to snapshot a log that contains one. Everything else as registered above. Peak memory at 6,144 is already 18.4 GB on 16 GB, so the limit is not raised.
- **Lesson (gotcha candidate):** a masked example whose prompt alone hits the sequence limit trains on nothing and NaNs the run; check the loss log for `nan`, never only the tail.

## What ran (21 Sep, 19:15–20:46, $0; attempt 1 NaN'd at 19:15–19:3x, rerun 19:36 → `logs/i2v4.log`)

| step | result |
|---|---|
| (c) examples | 28 train rows → 97 per-step examples, **1 dropped** (over 6,144 tokens, see the amendment) → **96**; valid 2 rows → 6; step-index histogram 1·28 2·28 3·21 4·9 5·5 6·4 7·1; the target is 2.4% of characters (v1–v3 trained on all 100%, of which the assistant was 5.0%) |
| (d) LoRA | 400 iters, --mask-prompt, 60 min, NaN guard armed and silent; val loss 1.48 → **0.29 at iter 200 → 0.40 at iter 400** (on the 6 masked valid steps; rising after 200 = overfitting); train loss 0.08–0.10 from iter 200; peak 18.4 GB |
| base snapshot | reused from v3 (16/20 · 12/18, 0/38 unstable, identical to v2's base) |
| adapter snapshot | 3 samples all **13/20 · 9/18**, 8.7 min, 0/38 unstable, adapter_sha stamped |

**Per case, adapter vs base (all stable, 3/3 samples):** UP `mid-thread-switch-referential-callback` (heldout, multi-turn — the third adapter in a row to lift it). **DOWN, three signatures:** (i) *identical call repeated* — `lookup-last-contact` (train), `redundant-stale-refresh` (train), `redundant-sibling-refresh` (heldout), `sofie-deal-stage` (heldout): `crm_lookup Janssens Bakery` twice, then a correct answer that the redundancy check fails; (ii) *looping past `max_steps`* — `portfolio-status-check` (train: crm_lookup ×5, the three companies then the first two again, no answer), `redundant-stale-refresh-deals` (heldout), `redundant-retry-outage-deals` (heldout, was UP on v2/v3); (iii) `active-client-stage` (heldout, missing 'discovery' — calls both tools now, answer drops the stage). **Passes worth naming:** `two-tool-combo` 3/3, `briefing-devos` 3/3, `no-deals-known-company` back to passing (v3's phrasing drop gone).

## Verdicts
| registered | verdict |
|---|---|
| (1) training rows replay, `briefing-devos` + `portfolio-status-check` pass | **Failed** — `briefing-devos` passes, `portfolio-status-check` loops; three OTHER training rows down (`lookup-last-contact`, `redundant-stale-refresh`, `redundant-retry-outage`), all by repeating a call |
| (2) `two-tool-combo` passes | **Held — first time in four attempts** |
| (3) heldout holds, 0 stable down | **REFUTED — 4 stable heldout down; kill fires** (v1 3 → v2 2 → v3 3 → v4 4) |
| (4) wall ≤ v3's adapter | Held-ish: 8.7 vs 7.2 min (more steps per case now) |

## Mechanism
The v3 hypothesis was half right. Masking put the loss on the decisions and the decision "after the first result, call the
second tool" was learned — the exact miss of v1–v3 is gone. What the per-step cut ALSO taught is the marginal: in 96
examples the target after a tool result is *another call* in 40 (steps 2–6 of multi-call rows) and *the answer* in 56, and
the two look identical up to the history — a 400-iteration LoRA on ~50 target tokens per example learned "a result was
just returned → a call is likely" faster than it learned "→ which tool is still missing". The tell is that every repeat
is the SAME company and the SAME tool: the model has the second-call reflex, not the second-call reason. The champion's
own rows contain seven single-call trajectories that end after one result; they were not enough counterweight.

**Registered prediction (1) said "if the training rows fail to replay, the loop has a second defect".** It does: the
per-step recut is a defect of its own kind — it changes the base rate the model sees. Candidate fixes, none run: (a) weight
the answer-step examples (or duplicate them) so "stop" has parity with "call"; (b) **the iter-200 checkpoint** — val loss was 0.29 at iter 200 and ROSE to 0.40 at 400 (overfitting the
targets after ~2 epochs), and `adapters/0000200_adapters.safetensors` is on disk: one 9-minute adapter snapshot, no training; (c) keep whole-row examples but mask the
tool-result payloads only (a custom collator; mlx_lm has no per-message mask) — the cleanest, since it preserves the
sequence base rate. Each is one free GPU hour; none is authorised.

## What this changes
- **First positive signal on the crm adapter line**: the two-call shape is learnable on 30 rows once the loss sees the
  decisions. The line "does not hold yet" stands; the reason moved from data to training recipe and is now specific.
- **Two gotcha candidates**: (1) a masked example whose prompt alone reaches `--max-seq-length` trains on zero tokens and
  NaNs the whole run silently — grep the loss log for `nan`, never only its tail; (2) a per-step recut changes the
  call/answer base rate the model learns — count targets by kind before training, as we counted shapes before v3.
- **The gate did its job four times** and the failure signatures are all different: under-call (v1–v3), over-call (v4).

## What this cannot say
- Nothing about the Ollama champion (15/18); both arms are the MLX 4-bit build at 12/18 base.
- Whether (a), (b) or (c) fixes the reflex without losing the second call — unrun.
