# E38 lead — "encoder first, champion on low confidence" on task-intake (2026-09-21, CPU only, no inference)

> **EVIDENCE CELL:** the committed E38 rows (`raw-g25small.json`, schema `desc`, 46 task-intake cases with the encoder's
> per-case `confidence`) **combined per case** with the committed champion snapshot (`evals/task-intake/snapshot.json`,
> `gemma4:e2b-it-qat`, 7 Sep): a case is routed to the encoder iff its confidence ≥ τ, else it takes the champion's
> verdict. τ swept on TRAIN, read on HELDOUT. **Not evidence:** the same sweep on `raw-g2base.json` (diagnostic, below).

Registered (sprint-map, 21 Sep): "low odds, free". Falsifier: the mixed router beats the champion's heldout 19/20 at some τ
chosen on train.

| τ | train mixed (routed to encoder) | heldout mixed (routed) |
|---|---|---|
| champion alone | 24/26 | **19/20** |
| encoder alone | 19/26 | 14/20 |
| 0.5 | 21 (15) | 19 (11) |
| 0.7 | 23 (8) | 19 (8) |
| 0.85 | 24 (4) | 19 (2) |
| 0.95 | 24 (2) | 19 (1) |

**REFUTED.** No τ exceeds the champion on either split; the best train τ (≥0.85) reproduces the champion's heldout 19/20 exactly,
with 1–2 cases routed to the encoder. The lead was the two write-baits both gemmas miss. On the evidence model the encoder
passes `heavy-none-edit-document-client-bait` (train) at confidence **0.307** — the LOW end, where a confidence router hands
off to the champion — and fails `heavy-none-crm-write-bait` (heldout) outright (`crm-followup` at 0.40). Confidence does not
separate right from wrong on this model: wrong answers sit at 0.20–0.84 (median 0.42), right ones at 0.31–1.00 (median 0.68).
Diagnostic `g2base`: passes both baits (1.00 / 0.84) but is wrong at median confidence 0.97 — every τ below 1.0 routes ~20 of
26 train cases to it and lands at 16–18/20 heldout, below the champion. **No `router.py` lane follows.** The write-bait fact
stands as data for a `none`-class training row (sprint C/I), not for a router.
