# E38 — encoder extractors sit the labels/fields exams — RESULTS (2026-09-18)

> **EVIDENCE CELL:** `fastino/gliner2.5-small-v1` (74M, the smallest GLiNER2 that supports
> classification + structured extraction — the selection rule this probe was given), schema
> `desc` (label set derived from cases.json + each label's definition copied verbatim from the
> champion's committed `agents/<exam>/prompt.md`), scored through `runner.score_labels` /
> `runner.score_fields` (+ `properties.py` for task-intake) — three exams, both splits, vs the
> committed champion snapshots (`gemma4:e2b-it-qat`, 7 Sep).
>
> **Not evidence** (diagnostic arms beside it): the `bare` schema (label names only) on the same
> model · `fastino/gliner2-base-v1` (205M, the GLiNER2 paper's model) on both schemas ·
> `knowledgator/gliformer-base-v1` (264M, the model the sprint-map bullet actually sized, a
> different package) on a bare schema with my own label wording.

## Pre-registration (written BEFORE the run — file mtime vs raw-*.json stamps)

Sprint-map E38 prediction, restated with the current committed case counts (verified from
`evals/<exam>/cases.json` and `snapshot.json` this session):

| exam | mode | train / heldout | champion snapshot (7 Sep, 3 loads) | prediction |
|---|---|---|---|---|
| expense-categorization | fields | 6 / 9 | 6/6 · **8/9** (0.8889) | P1: the encoder passes at the ceiling — heldout **9/9**. (The bullet says "six models already do" 9/9; the committed champion snapshot is 8/9.) |
| email-triage | labels | 8 / 11 | 7/8 · **10/11** (0.9091) | P2: the encoder misses the judgement labels — heldout **< 10/11**. |
| task-intake | labels + properties | 26 / 20 | 24/26 · **19/20** (0.95) | P3: no prediction ("unknown"); reported. |

Verdict rules: P1 holds iff the evidence cell's expense heldout = 9/9. P2 holds iff its
email-triage heldout ≤ 9/11. "Passes anywhere" (the sprint-map's trigger for a `router.py`
adapter lane) = evidence-cell heldout ≥ champion heldout on at least one exam.

Design fixed before running:
- Label sets derive from `expected` blocks; `office` (in prompt.md, expected by no case) is
  therefore NOT offered to the encoder on expense — a mild asymmetry in the encoder's favour.
- task-intake's hand-over (`input`) is a code rule — whole request, or `""` for `none` —
  because `properties.py` declares a whole-request hand-over as passing. The task-intake
  number is agent selection + the none/not-none call only.
- The encoder is arg-max per task (single-label); no threshold is tuned. One pass per arm;
  heldout is run once and reported.
- Environment: NOT the repo's `python3` (its `transformers 4.34.0` fails to import against
  `huggingface_hub 1.8.0`, and fixing that means upgrading the operator's shared pyenv env
  while a GPU run uses it). Two isolated venvs on the same interpreter (pyenv 3.10.6), in the
  session scratchpad; `sandbox/runner.py` is imported from the repo unchanged.

## Setup (verified this session)

| model | params / encoder | licence (model card, rank A) | package | arch class loaded |
|---|---|---|---|---|
| `fastino/gliner2.5-small-v1` (evidence) | 74M, `microsoft/deberta-v3-xsmall` | Apache-2.0 | `gliner2==2.0.0` | `BoundaryExtractor` |
| `fastino/gliner2-base-v1` | 205M, DeBERTa-v3-base | Apache-2.0 | `gliner2==2.0.0` | `SpanExtractor` |
| `knowledgator/gliformer-base-v1` | 264.2M, DeBERTa | Apache-2.0 | `gliformer==0.1.2` | `GLiFormerLayout` |

Correction to the sprint-map bullet: GLiNER2 is **Fastino's** (github.com/fastino-ai/GLiNER2,
PyPI `gliner2`); GLiFormer is Knowledgator's, and "264M–576M" are GLiFormer's two sizes
(base 264.2M, large 575.6M). GLiNER2's own sizes are 74M / 194M / 205M / 287M / 340M.

Install (scratchpad venvs on pyenv 3.10.6, the interpreter that runs `sandbox/runner.py`):

```sh
python3 -m venv e38venv && e38venv/bin/pip install "gliner2[local]==2.0.0" protobuf sentencepiece pyyaml requests
python3 -m venv gfvenv  && gfvenv/bin/pip  install "gliformer==0.1.2" pyyaml requests
```

The bare `gliner2` wheel is an API client (no torch) — `[local]` is required for inference.
`protobuf` + `sentencepiece` are not pulled by `[local]` but are needed: under the resolved
`transformers 4.57.6` the fast DeBERTa-v2 tokenizer load raises
(`'list' object has no attribute 'keys'` in `_set_model_specific_special_tokens`) and the slow
fallback needs them. `gliformer` resolved `transformers 5.16.1` + `gliner 0.2.29`, hence the
second venv. Peak RSS: 1.5 GB (small), 1.7 GB (base), 2.5 GB (gliformer) — one model in RAM at a
time, no Ollama call anywhere (`grep -c ollama probe.py` → 0 calls; `runner` is imported for
`score_labels` / `score_fields` / `load_properties` / `run_properties` / `load_exam` only).

## Results — evidence cell vs champion (heldout run once)

| exam | champion `gemma4:e2b-it-qat` (snapshot 7 Sep) | **evidence: gliner2.5-small / desc** | up (encoder passes, champion fails) | down (encoder fails, champion passes) |
|---|---|---|---|---|
| email-triage (labels) | train 7/8 · heldout **10/11** | train 3/8 · heldout **7/11** | — | client-quote-request, overdue-invoice, newsletter-substack, seo-cold-spam, promo-code, invoice-error-client, dpa-signature-compliance |
| expense-categorization (fields) | train 6/6 · heldout **8/9** | train 1/6 · heldout **1/9** | — | railway-subscription, client-lunch, nmbs-ticket, coolblue-monitor, hotel-lisbon, paypal-cryptic, bank-transfer-savings, godaddy-domain-renewal, paypal-adobe-subscription, square-cafe-cryptic, uber-trip-cryptic, telenet-daypass |
| task-intake (labels + properties) | train 24/26 · heldout **19/20** | train 19/26 · heldout **14/20** | heavy-none-edit-document-client-bait | reply-nl-antwoord, recap-what-got-done, recap-highlights, recap-end-of-day, transcript-bare, transcript-proper-english, none-weather, none-generate-invoice-client-bait, none-chitchat, none-reminder, none-pause-email-bait |

### Prediction verdict

- **P1 REFUTED, in direction.** Predicted 9/9 on expense; measured **1/9** (the champion: 8/9).
  Anatomy from `raw-g25small.json`: `category` right 8/15, `recurring` right 5/15 — the 74M
  model answers `recurring=true` on 14 of 15 lines (confidence 0.76–0.99) and drifts to
  `telecom` on 7 of 15 (`ANTHROPIC PBC API CREDITS` → telecom 0.72). `score_fields` needs both
  fields; `fields_matched` is 1/2 on 10 cases and 0/2 on 3.
- **P2 HELD.** Email heldout 7/11 < 10/11. Confusion (expected→got, both splits): reply_now→
  reply_later 5, ignore→reply_later 2, ignore→reply_now 1, reply_later→reply_now 1. The
  bare schema is worse (4/11) and collapses to `reply_now` on 17/19.
- **P3 (no prediction): 14/20 vs 19/20.** The label-only half is 33/46 (both splits); every
  miss is a label miss — `properties.py` failed **0 of 160** rows across all arms, i.e. the
  whole-request hand-over rule passes the hand-over half exactly as the exam declares.
  Misses cluster on `recap` (0/5 — all sent to email-triage/crm-followup), `transcript-en`
  (2/6) and `none` (3/9 — chit-chat/weather/reminders dispatched to crm or expense).
- **"Passes anywhere" — NO.** No arm, evidence or diagnostic, reaches the champion's heldout on
  any exam. No `router.py` adapter lane follows from this run.

### Diagnostic arms (not evidence)

| exam | champion heldout | g2.5-small/bare | g2-base/bare | **g2-base/desc** | gliformer-base/bare |
|---|---|---|---|---|---|
| email-triage | 10/11 | 4/11 | 7/11 | **8/11** (train 6/8) | 2/11 |
| expense-categorization | 8/9 | 1/9 | **5/9** (train 4/6) | 4/9 | 1/9 |
| task-intake | 19/20 | 8/20 | 8/20 | **16/20** (train 17/26) | 7/20 |

Reading: the 205M `gliner2-base-v1` with prompt.md definitions is the best encoder here and
still sits 2 / 3 / 3 heldout cases under the 2B champion. Its expense `category` is 14/15 with
definitions (12/15 bare) — the loss is `recurring` (7/15 with definitions, 11/15 bare: the
definition "true if this is clearly a subscription…" made it worse). Two flips UP worth noting
on g2-base/desc: `heavy-none-edit-document-client-bait` and `heavy-none-crm-write-bait` — the
two write/edit baits `agents/task-intake/agent.yaml` records both gemmas missing — the encoder
says `none` on both. A classifier with no tools has no urge to dispatch a write. It pays for
that with `triage-bare-client-email` / `triage-bare-recruiter` / `triage-bare-disk-alert`
(bare emails → reply-draft/none) and all three recap cases.

GLiFormer-base (bare, my label wording — `reply now`, `one-off charge`): 2/11 · 1/9 · 7/20.
Its `classify()` scores the label string as text (`reply_now` 0.11 vs `reply now` 0.99 on the
same mail in the smoke test), so this arm is a wording probe, not a model verdict.

### Determinism

`raw-g25small-rerun.json` (second process, same venv): **0 verdict flips, 0 label flips,
max |confidence delta| 0.00e+00** over 160 rows. On this machine the encoder is bit-reproducible
across loads; "deterministic by construction" holds for the evidence model. Not tested: across
machines / torch builds.

### Wall (CPU, Apple silicon, one model at a time)

| arm | load | total | per call (min–max, median) |
|---|---|---|---|
| gliner2.5-small (2 schemas × 80 cases = 160 calls) | 7.6 s | 21.6 s | 41–267 ms, 74 ms |
| gliner2-base (160 calls) | 9.7 s | 40.6 s | 71–426 ms, 179 ms |
| gliformer-base (80 calls) | 9.6 s | 23.8 s | 87–375 ms, 167 ms |
| gliner2.5-small rerun | 8.6 s | 20.9 s | — |

Total inference wall **106.9 s** for four processes; excludes the ~1.6 GB of venvs and ~1.3 GB
of weights downloaded (smoke tests included), roughly 15 min of set-up.

## What this cannot say

- Nothing about the larger checkpoints (`gliner2-large-v1` 340M, `gliformer-large-v1` 576M) or
  the multilingual ones — 6 of 46 task-intake cases are NL/FR and all arms are English models.
- Nothing about **fine-tuning**: `gliner2[local]` ships LoRA training and these exams have
  train splits of 8 / 6 / 26. That is sprint I's question (fine-tune where it pays), not E38's;
  a zero-shot encoder loses here, a tuned one is unmeasured.
- The expense schema omitted `office` (in prompt.md, expected by no case) — in the encoder's
  favour, and it still scored 1/9.
- task-intake measures agent choice only; hand-over quality is passed by rule, not by the model.
- The task-intake definitions carry the "Input = …" sentence verbatim — a hand-over instruction
  the classifier cannot act on; a trimmed definition was not tried (that would be tuning).
- One machine, one day; the champion column is the committed 7 Sep snapshot, not a same-day
  rerun (gotcha 14 is about hosted drift; local temp-0 is the 3-load gate, so the comparison
  stands as the exam defines it).
- Scorers are the real ones; the 10-line combination of label verdict + property checks
  (`run_exam.attempt`, runner.py ~1506–1517) is a closure over a live adapter and cannot be
  called without a model call, so `probe.score()` mirrors it line for line — that mirror, not
  the scorer, is the only re-implemented piece (gotcha 5).

## Decision input (not a decision)

Zero-shot encoder extractors do not sit these three exams at the champion's level, on any
arm, on any exam; the strongest (205M + the champion's own label definitions) is 2–3 heldout
cases short everywhere and fails `recurring` outright. The sprint-map's "if it passes
anywhere → adapter lane" trigger did not fire. Two leads survive for other sprints: (1) the
encoder refuses both write-baits the gemmas take (sprint C/I material on `none`); (2) LoRA on
the train split is a ~minutes CPU job with this package — that is sprint I, and it must be
predicted before it is run.

Files: `probe.py` · `raw-g25small.json` (evidence) · `raw-g25small-rerun.json` ·
`raw-g2base.json` · `raw-gfbase.json` · `logs/*.log` (per-case lines with got/expected and
wall). Nothing committed; no tracked file touched.
