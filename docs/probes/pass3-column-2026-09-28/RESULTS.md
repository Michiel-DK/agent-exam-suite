# pass^3 column — RESULTS (RAN 2 Oct 2026, CPU only, $0, no inference; designed 28 Sep)

> **EVIDENCE CELL:** GLM-5.3 on call summaries (`transcript-en`, 1 Sep case set, 13 held-out): single run **10/13**, pass^6 over
> the six same-day runs **6/13** — 0.60 of the single-run score. Registered prediction "≤ 0.60" **holds**, at the boundary.
>
> **Not evidence:** the local rows (they confirm an identity, pass^3 = single-run, 0 unstable — the gate already enforces it);
> the Kimi rows (one or two flips per exam, the quiet arm); the candidate-count table (a denominator, not a measurement).

**Script:** `python3 docs/probes/pass3-column-2026-09-28/pass_k.py` (reads the committed snapshots, the pin day's six runs, and
the matrix tables; prints the three tables below). **Table change shipped the same day:** `build_tables.py` carries a `pass^k`
column (local row: pass^3 from the snapshot's `stable` flags; every single-pass row: "1 run") and the heading counts candidates
and the tie band. **Rule change:** loop doc rule 6 (winner's denominator + confirmation set).

## What it says

1. **Local: pass^3 equals the single-run score on all 8 exams, 0 unstable cases** (at Ollama 0.33.2; the 0.35.0 re-snapshot ran
   the same evening — its table is appended below when it lands). That identity is the point: the gate IS pass^3.
2. **Hosted: the six-run pass^6 sits below the single run on every exam for both models.** GLM-5.3 loses 4 of 10 on call
   summaries and 2 of 10 on the CRM brief across six runs; Kimi loses 1 and 0. Pinning the creator endpoint narrows GLM's
   spread (pass^3 pinned 8/13 vs unpinned 6/13 on call summaries) but does not close it.
3. **The tie band is wide on the small exams:** on email triage, expense fields and reply draft every candidate sits within one
   case of the best, so "cheapest that passes" there is decided by price alone, which is the intended behaviour; on call
   summaries and the CRM brief 3 of 12 compete at the top and one case is 5.3–5.6 points.
4. **The 27 Sep matrix rows all read "1 run"** until the three same-day repeats (≈$20). A tier letter needs pass^3; none can be
   assigned today for a hosted model on the current case sets.

## Tables (Ollama 0.33.2 snapshots, as committed before the 2 Oct re-snapshot)

## Local champions — pass^3 from the committed 3-load snapshots

| exam | model | runtime | held-out n | single-run (held-out) | pass^3 | unstable cases |
|---|---|---|---|---|---|---|
| transcript-en | gemma4-e4b-ctx16k | ollama 0.33.2 | 19 | 10/19 | **10**/19 | 0 |
| call-fields | gemma4-e4b-ctx16k | ollama 0.33.2 | 19 | 14/19 | **14**/19 | 0 |
| crm-followup | gemma4-e2b-ctx16k | ollama 0.33.2 | 18 | 15/18 | **15**/18 | 0 |
| recap | gemma4:e4b-it-qat | ollama 0.33.2 | 10 | 7/10 | **7**/10 | 0 |
| email-triage | gemma4:e2b-it-qat | ollama 0.33.2 | 11 | 10/11 | **10**/11 | 0 |
| expense-categorization | gemma4:e2b-it-qat | ollama 0.33.2 | 9 | 8/9 | **8**/9 | 0 |
| reply-draft | gemma4:e2b-it-qat | ollama 0.33.2 | 10 | 10/10 | **10**/10 | 0 |
| task-intake | gemma4:e2b-it-qat | ollama 0.33.2 | 22 | 21/22 | **21**/22 | 0 |

## Hosted — pass^k from the 1 Sep pin day (six runs; 1 Sep case sets)

| exam | model | held-out n (1 Sep set) | single run (pinned rep1) | pass^3 pinned | pass^3 unpinned | pass^6 all | cases flipping across the six |
|---|---|---|---|---|---|---|---|
| transcript-en | z-ai/glm-5.3 | 13 | 10/13 | 8/13 | 6/13 | **6**/13 | 5: discovery-heldout-hard, mixed-heldout-dense, renewal-heldout-digits, renewal-heldout-medium, support-heldout-long |
| transcript-en | moonshotai/kimi-k3 | 13 | 10/13 | 10/13 | 9/13 | **9**/13 | 2: renewal-heldout-digits, support-heldout-long |
| crm-followup | z-ai/glm-5.3 | 16 | 10/16 | 10/16 | 9/16 | **8**/16 | 4: crm-outage-mid-sweep, peeters-outage-fill-in, peeters-outage-honest-ack, peeters-partial-honest-control |
| crm-followup | moonshotai/kimi-k3 | 16 | 9/16 | 9/16 | 9/16 | **9**/16 | 1: peeters-outage-fill-in |
| recap | z-ai/glm-5.3 | 10 | 5/10 | 5/10 | 4/10 | **4**/10 | 3: buried-critical, long-quiet-day, rounding-bait |
| recap | moonshotai/kimi-k3 | 10 | 6/10 | 4/10 | 6/10 | **4**/10 | 3: amounts-at-length, long-quiet-day, rounding-bait |
| email-triage | z-ai/glm-5.3 | 11 | 11/11 | 10/11 | 10/11 | **10**/11 | 1: paid-workshop-invite |
| email-triage | moonshotai/kimi-k3 | 11 | 11/11 | 10/11 | 10/11 | **10**/11 | 1: paid-workshop-invite |
| expense-categorization | z-ai/glm-5.3 | 9 | 8/9 | 8/9 | 8/9 | **8**/9 | 1: google-ads |
| expense-categorization | moonshotai/kimi-k3 | 9 | 9/9 | 9/9 | 8/9 | **8**/9 | 1: google-ads |
| reply-draft | z-ai/glm-5.3 | 10 | 10/10 | 9/10 | 9/10 | **9**/10 | 1: long-thread-buried-ask-en |
| reply-draft | moonshotai/kimi-k3 | 10 | 10/10 | 9/10 | 10/10 | **9**/10 | 1: september-firm-day-en |

## Candidates per table (27 Sep matrix + call-fields) — the selection-bias denominator

| exam | held-out n | candidates that competed | one case = | tie band (best or one case below) |
|---|---|---|---|---|
