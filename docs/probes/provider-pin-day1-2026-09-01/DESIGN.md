# Provider-pin probes — pre-registered design (day 1: 2026-09-01)

Operator authorization (2026-09-01): "$11 of credits in total … run frontier + local if
needed … done by evening". Key state at start: total_credits 20, total_usage $8.706
(→ $11.29 available). Uses the `provider_routing` knob merged this morning (PR #63 →
`27c5e67`, ledger 030). The full drift answer is TWO-day by construction — day 2 is a
separate window (kit at the bottom); everything else completes today.

## Probes, in run order

### A — knob validation (presence is not effect; ~$0.05)
The merged knob is an opaque passthrough validated only by unit tests against a mocked
`requests.post`. Before spending on it:
- **GREEN:** one live call per model through the REAL entry point (`sandbox/runner.py run`,
  worktree agent.yaml carrying `provider_routing: {order: [<pin>], allow_fallbacks: false}`)
  must be SERVED BY the pinned provider — read the response's provider metadata via a raw
  paired call (metadata check is supporting evidence; the runner path is the witness).
- **RED:** the same call with `order: ["bogus-provider-zzz"], allow_fallbacks: false` must
  FAIL LOUDLY (provider-side error surfaced), not silently fall back.
- **Kill rule:** if GREEN is served by a non-pinned provider or RED silently succeeds, the
  knob (or the recalled schema) is wrong → STOP probes B and D, report, spend nothing more.

Pins (chosen from `GET /models/<id>/endpoints`, 2026-09-01, creator-endpoint rule —
canonical weights, top uptime): GLM-5.3 → `z-ai` (Z.AI, fp8, uptime 100); Kimi K3 →
`moonshotai` (Moonshot AI, mxfp4, uptime 99.93). Exact `order` slug syntax is validated
empirically in A (provider slug first; endpoint tag form as fallback).

### B — the missing GLM×crm trajectory row (~$0.3, retries ≤$0.9)
crm-followup (FAT, 28 cases) × z-ai/glm-5.3, PINNED to z-ai. Driver: per-exam 3 tries,
75 s cooldown. Unpinned attempts have 429-gapped 3 arms + a 6/6 quiet-window refutation;
the pin is the last known path. **Outcomes:** row lands → gap filled, scores reported
train/heldout; still 429s ×3 → try ONE alternate pin (deepinfra); that also gaps →
"pin does not rescue GLM trajectory bursts" is the (negative) result. Comparability note:
this is the FAT exam — NOT comparable to the A/B's slim crm rows.

### C — Mistral flagship, id recorded this time (~$0.4)
`mistralai/mistral-medium-3-5` (newest non-batch top-tier on OpenRouter as of today;
$1.5/$7.5 per M) × the 6-exam suite, unpinned, 1 rep. Purpose: replace the unevidenced
"Mistral Large" row with a labeled, reproducible one. The exact model id + endpoint list
goes in RESULTS.md.

### D — drift probe day 1 (~$4)
2 models (GLM-5.3, Kimi K3) × 2 arms (pinned to creator endpoint / unpinned) × 2 reps ×
6 exams (crm-followup email-triage expense-categorization recap reply-draft
transcript-en), all in ONE window (gotcha 14), interleaved by arm so pinned and unpinned
see the same window. Committed configs otherwise untouched: json_mode off,
reasoning_effort unset. Day-1 questions (same-day claims only):
- **D1:** does pinning change the same-day pooled heldout score? (Prediction: no —
  within the 0–4/17 within-day flip bar.)
- **D2:** does pinning change within-day rerun stability (rep1 vs rep2 verdict flips,
  pinned vs unpinned)? (Prediction: pinned ≤ unpinned flips.)
- **The drift question itself (pinned vs unpinned cross-day delta) is NOT answerable
  today** — day 2 reruns 1 rep per arm per model in a fresh window and compares.

## Guards (all mechanical, in the driver)
- **Budget:** abort everything when total_usage > $18.00 (leaves ≥$2 for day 2).
- **Order:** A gates B and D (kill rule above). C is independent of the knob.
- **429s:** 3 tries, 75 s cooldown, then recorded as a GAP, never a score.
- **Tokens pooled from `metrics_totals` ONLY** (gotcha 13).
- Worktree pinned at master `ce094af` + noted in every log line (probe-kit rule).

## Pre-registered claim discipline
Same-day pooled comparisons only; per-case claims and cross-day claims are out of scope
until day 2. A pinned arm landing below the unpinned arm beyond the flip bar is reported
as-is (numbers accepted as they land, never chased).

## Day-2 kit (fire in any later window, ~$2)
Same worktree or a fresh one at the same SHA; rerun D at 1 rep per (model × arm), same
pins, same driver with `REPS=1`; then compute per-model: cross-day heldout verdict flips
pinned vs unpinned against day-1 rep1. Deliverable: the drift verdict — does pinning
collapse the −5/−6 cross-day case drift toward the within-day bar?
