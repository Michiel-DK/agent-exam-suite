# E31 quantisation bake-off — RESULTS (night run 2026-09-17 18:03–20:59, 2 h 57 min, Ollama 0.33.2)

> **EVIDENCE CELL:** `crm-followup @ gemma4-e4b-ctx16k` (QAT Q4_0) **vs** `crm-followup @ gemma4-e4b-ctx16k-plain` (post-hoc Q4_K_M), same Modelfile window (16k), 3 loads each, 0 of 38 cases unstable on either arm — **plain 6 up / 0 down** over QAT (train 6/20 → 10/20, heldout 8/18 → 10/18). The brief's prediction was the opposite direction.
>
> **Not evidence:** the qwen pair (a 2-case train-only movement, 0 heldout, in the other direction from the brief — reported below, not the verdict); the wall-time rows (speed, one machine, uninstrumented); the 10 Sep 16k q8 arm (killed, never scored).

Brief: `docs/e31-quantisation-bakeoff-brief-2026-09-09.md`. Rescope: `STATUS-paused-2026-09-10.md` (window held FIXED per pair; gemma at 16k on crm, qwen at the default 4k on task-intake). Script: `e31-night.sh`. Log: `logs/e31-night.log`. Snapshots: the four `<exam>.<tag>.json` files beside this file (rule-A, 3 loads, majority verdict, unstable cases exempt).

## Tags, as loaded (`ollama show`)

| tag | FROM | quant | disk | resident on GPU (`ollama ps`) | window |
|---|---|---|---|---|---|
| gemma4-e4b-ctx16k | gemma4:e4b-it-qat | Q4_0, QAT | 6.1 GB | 3.3 GB | 16k |
| gemma4-e4b-ctx16k-plain | gemma4:e4b | Q4_K_M, post-hoc | 9.6 GB | 3.4 GB | 16k |
| qwen3:8b | library | Q4_K_M | 5.2 GB | 5.6 GB | 4k (default) |
| qwen3:8b-q8_0 | library | Q8_0 | 8.9 GB | 8.9 GB | 4k (default) |

**Confound checked:** the `-plain` Modelfile carries `PARAMETER temperature 1`. It does not reach the run — the Ollama provider sends `temperature` in every request body (`sandbox/router.py`, the `generate` payload), which overrides the Modelfile; both snapshots record `temperature 0.0`, and 0 flips across 3 loads corroborate it.

The gemma disk-size gap is the vision/audio towers, which never load: both tags sit at ~3.4 GB resident. The predicted "size-vs-window wall at a second size point" did not appear because there is no second size point — the plain tag is not bigger in memory.

## Noise floor

0 flips between loads on every arm (3 loads × 4 arms; 38 + 38 + 46 + 46 cases). Every movement below is above the floor by construction; small N (brief: "two exams of ~10–20 cases detect a large effect only") is the remaining caveat.

## Pair 1 — crm-followup, gemma e4b, QAT vs plain, 16k

| arm | train | heldout | wall (3 loads) | unstable |
|---|---|---|---|---|
| QAT Q4_0 (`gemma4-e4b-ctx16k`) | 6/20 | 8/18 | 41.5 min | 0/38 |
| plain Q4_K_M (`-plain`) | **10/20** | **10/18** | 50.5 min (+22%) | 0/38 |

Per case, plain vs QAT: **6 up, 0 down.** Up: `status-churned` (train), `briefing-devos` (train), `active-client-stage` (heldout), `sofie-deal-stage` (heldout), `redundant-stale-refresh` (train), `three-tools-one-thread-janssens` (train).

**Mechanism, from the stored strings (load 1, identical on loads 2–3):** 5 of the 6 QAT failures are `unparseable … no final answer emitted` — the QAT tag writes the right content as prose (`'The status of Vitrine Restaurant is **churned**.'`, `'Your contact at Devos Garage is Jan De Vos.'`) and never emits the protocol's final-answer form, so the grader sees no answer. The 6th (`redundant-stale-refresh`) is a plain `no final answer emitted`. This is a **format-protocol failure of the QAT tag**, not a knowledge failure: the answer text is in the transcript. Neither arm touches the 2B champion (heldout 15/18); no champion moves.

## Pair 2 — task-intake, qwen3 8B, 4-bit vs 8-bit, 4k

| arm | train | heldout | wall (3 loads) | unstable |
|---|---|---|---|---|
| Q4_K_M (`qwen3:8b`) | 22/26 | 17/20 | 33.0 min | 0/46 |
| Q8_0 (`qwen3:8b-q8_0`) | 20/26 | 17/20 | 51.5 min (+56%) | 0/46 |

Per case, q8 vs 4-bit: **0 up, 2 down**, both train: `triage-bare-recruiter` (labels mismatch), `none-chitchat` (`check_none_hands_over_nothing`: q8 hands something over on "hey are you there?"). Heldout identical, 17/20 both. The 10 Sep 16k 4-bit arm (`task-intake.qwen3-8b-ctx16k.json`, same runtime) also reads 22/26 · 17/20 — the window did not move task-intake's verdicts, as the rescope assumed.

**Speed:** q8 at 4k runs at 1.56× the 4-bit wall with 0 timeouts. The 10 Sep q8 arm at 16k ran ~14× slower with 7 ReadTimeouts. So the wall is **q8 weights + a 16k KV cache** on 16 GB, not q8 alone.

## Prediction and falsifier verdicts (brief §Prediction / §Falsifiers)

| registered | verdict |
|---|---|
| Qwen3-8B: 8-bit ties 4-bit inside the noise floor on both exams | **Not upheld on train** (2 down at floor 0), upheld on heldout (17/20 = 17/20). Direction: 8-bit is not better. No precision column earns its place — 4-bit stays the pick on score AND speed. |
| Qwen3-8B: wall rises with bytes | Upheld: +56% wall for q8 at 4k. |
| Gemma e4b: QAT beats plain by more than the floor, concentrated in the long band | **Refuted in direction**: plain beats QAT 6/0, all stable. Long band N/A (crm is not the long band). |
| Falsifier "QAT vs plain inside the floor" | Did not fire — the gap is 6 cases at floor 0, the wrong way round. |
| 16-bit arms | Never ran (fp16 ~16 GB does not fit; brief allowed dropping). |

## What this changes

- **Customer-hardware answer (the brief's purpose):** on a 16 GB machine, 4-bit is the right precision on both score and speed for both families tested; 8-bit at a 16k window is unusable (10 Sep), at 4k it is 1.56× slower and scores no better. Post-hoc Q4_K_M ≥ QAT Q4_0 on the one pair measured.
- **Champion-side:** nothing. crm stays on the 2B (15/18 vs 10/18 here); task-intake stays on its champion (19/20 vs 17/20 here).
- **A lead, not a verdict (gotcha 11):** the crm champion `gemma4-e2b-ctx16k` is ALSO built FROM a `-it-qat` tag. If the QAT protocol-drop generalises to e2b, a plain-e2b arm is the cheapest possible crm improvement to test (one arm, ~40 min, free). Not run tonight; queued in the sprint-map.

## What this cannot say

- Tokens per case: `run --snapshot` results carry no `metrics_totals` (checked on all four worktree results files), so the brief's tokens-and-`wall_ms`-per-case column is NOT delivered; only per-arm wall from the script's own timestamps. A rerun without `--snapshot` would capture them.
- The mechanism of the QAT protocol drop is read from failure strings, not instrumented; the 6 transcripts are in `crm-followup.gemma4-e4b-ctx16k.json`.
- e2b QAT-vs-plain, and any 16-bit arm: not measured.

## E31b — the lead, run 2026-09-18 17:46–18:09 (23 min): plain e2b vs the QAT e2b CHAMPION on crm at 16k — MIXED, champion holds

> **EVIDENCE CELL (E31b):** `crm-followup @ gemma4-e2b-ctx16k` (the committed champion snapshot, QAT Q4_0, 7 Sep runtime 0.33.2) **vs** `crm-followup @ gemma4-e2b-ctx16k-plain` (FROM `gemma4:e2b`, Q4_K_M, same 16k Modelfile, 3 loads, 0/38 unstable, same runtime) — **3 up / 4 down; heldout 15/18 → 13/18 (1 up / 3 down), train 12/20 → 13/20 (2 up / 1 down).**
>
> **Not evidence:** the e4b pair above (a different size point); the single-load reads.

| arm | train | heldout | wall (3 loads) |
|---|---|---|---|
| champion QAT Q4_0 (`gemma4-e2b-ctx16k`) | 12/20 | **15/18** | (committed snapshot) |
| plain Q4_K_M (`-plain`, 1.8 GB resident) | 13/20 | 13/18 | 23.3 min |

Up (plain passes, champion fails): `thread-followup-contact-reselection` (train), `peeters-contact-followup-outage` (train), `portfolio-recap-multiturn-fb2` (heldout).
Down (champion passes, plain fails): `two-tool-combo` (heldout — `unparseable … no final answer emitted`, the ONE e4b-style protocol drop), `peeters-hedge-suppresses-lookup` (heldout — never called `deals_list`), `portfolio-status-check` (train — two dates missing), `crm-outage-mid-sweep` (heldout — answer missing + the designed outage was not exercised).

**Verdict on the lead:** the e4b finding does NOT generalise to e2b. At e2b the QAT tag is not dropping the final-answer protocol (1 of 4 downs is that signature, the rest are ordinary trajectory failures), and the plain tag trades cases both ways with a net −2 on heldout. **The champion holds; nothing moves.** Rule A on the champion snapshot: 3 stable heldout cases down would fail `check` — so this is also a live demonstration that the gate would refuse this swap.

**What it says about QAT:** one size up, QAT lost 6/0 with a format signature; one size down, QAT is +2 heldout. QAT-vs-plain is per-checkpoint, not a rule — do not promote or demote QAT on principle (the brief's own falsifier wording).
