# Agents are disposable. The eval suite is the asset.

> **Frozen write-up, 2026-08-14.** The repo keeps moving; this page doesn't. Every number
> below traces to a committed file (named inline) — none of it is recalled impression.
> Where the measurements are unflattering, they are left in. That is the point.
>
> **One dated progress section was appended 2026-08-24** (see the end). The 08-14 body
> above it is unchanged — receipts don't get retouched.

## The one-paragraph version

agent-sandbox runs five small office agents — email triage, CRM follow-up, expense
categorization, meeting recap, reply drafting — on local models (4B–14B, on a 16 GB
M1 Pro laptop). The agents are deliberately boring: each is a prompt, a tool list, and
one model-config line. The thing that took **235 commits** is the exam suite around
them: **86 committed cases** across 5 exams, **20 test files**, train/heldout splits,
deterministic scoring with **no LLM judge anywhere in the suite**. Exams decide which
model ships — and when the exams *can't* decide, the system says `cannot-distinguish`
instead of guessing (`sandbox/policy.py`).

## The scoreboard, failures included

Heldout scores as of 2026-08-05 (committed `evals/*/snapshot.json` at that date):

| exam | heldout | honest note |
|---|---|---|
| reply-draft | 1.00 | saturated — currently useless for ranking, and we say so |
| crm-followup | 0.909 | de-saturated, but 1 failing case ≈ 9% — inside the noise band |
| expense-categorization | 0.89 | |
| email-triage | 0.73 | |
| recap | 0.70 | the hardest exam, on purpose |

A 1.00 here is reported as a *defect of the exam*, not a win for the model. That
inversion — treating a saturated score as an instrument failure — is the whole method.

## Five receipts

### 1. A 72-minute sweep whose headline indicted its own instrument

`docs/e8-sweep-2026-07-23.md`: six challenger models swept against four exams,
**71.9 minutes wall-clock on the M1 Pro**, with the champions' noise band computed
*before* any ranking, so a delta on a flaky case can't be sold as capability. The
sweep did find a real capability edge — `gemma4:e4b-it-qat` was the **only** model to
pass `two-tool-combo`, a case the then-champion failed deterministically at 0.0. But
the headline finding, reported in the doc's own words: **"2 of 4 exams no longer
discriminate."** The sweep's biggest output was discovering the measuring instrument
was half-blind — and publishing that instead of the leaderboard.

### 2. Model size is not the lever

`docs/model-size-probe-2026-08-05.md`: `gemma4:e4b` (~4B), `qwen3:8b` (8.2B), and
`qwen3:14b` (14B) — two families, a 3.4× parameter range — all score an **identical
7/10 heldout** on the recap exam. The controlled pair (8B vs 14B, same family, same
prompt) shows why: the 8B writes short and drops items (1 compression / 6 coverage
failures); the 14B writes long and blows the length bar (5 / 5). Not different
heights on one axis — different points on the same trade-off curve. Conclusion in the
doc: **do not buy hardware to raise this score; the lever is the target, not the
parameters.** That's a spend decision settled by ~40 minutes of measurement, for €0.

(The probe also nearly lied: the first run used the 120 s default timeout and returned
zero completed cases — timeouts that would have read as capability failures. It was
killed and rerun with `--timeout 900` rather than interpreted.)

### 3. An experiment killed by its own pre-registered falsifier

Commit `0bc8c73` — "step 0a RAN and KILLED the lane." E20 was to be the first
multi-turn exam, built on the field's claim that instruction-following degrades
across turns. Before building anything, a falsifier ran: 3 conversations × 3 turns
with constraints accumulating, kill criterion written down in advance. **9 model
calls, zero code, under an hour — and the criterion fired: the champion held all
constraints 3/3, with zero drift.** It actually gets *better* across turns. The lane
died before a line of it was built. The follow-up doc also records that the probe
itself was wrong twice in the direction its author hoped — a falsifier gets audited
like everything else (`docs/e20-brief.md`).

### 4. 1,150 merged PRs → 13 admissible tasks, against a bar of ≥12

`docs/e-corpus-sweep-2026-08-14.md`: to build a real-code exam, every merged PR from
a real production repo went through a measured funnel — 1,150 merged → 261 mechanical
fits → **125 after dropping tests that grade source *text* instead of behaviour (the
filter removed 52%)** → 89 in the discriminating difficulty band → **13 that
reproduce red→green at their base commit**. The pre-registered success bar was ≥12;
it clears by one, and the doc says "clears by one," not "success." It also states a
count it could not reconcile with an earlier probe rather than smoothing it over, and
notes the sweep made **zero model calls** — so nothing in it can be a model result.

### 5. Failure signatures, not vibes

`docs/model-notes.md` operates under one rule, printed at the top: **"every line
names how it was observed. No recalled impressions."** Sample entries: with the CRM
lookup tool forced down, `llama3.1` invented a contact named "Karen Brown" — no tool
result or input supplies that name — while `gemma4:e4b` passed the same traps by
declining to fill the hole. Opposite dispositions, both observed, both cited to the
runs that produced them. And the commercially scariest one (from the working repo's build ledger):
tell the model *"your best estimate is fine"* and it **skips the lookup tool
entirely** — not fabrication, worse, because it's invisible.

## What is honestly broken right now

- **The suite cannot currently rank two good models.** Heldout sets are 10–11 cases
  per exam, so one case ≈ 9–10% of a score — exactly the noise band the routing
  layer refuses to pick inside. The routing command's headline output on
  email-triage is a refusal: `cannot-distinguish`, "grow heldout before revisiting"
  (the working repo's build ledger, E12 entries).
- **reply-draft measures hallucination + format only.** When its small LLM judge
  proved unreliable (it mis-passed 3/3 invented-date replies), the judge was dropped
  entirely and the cost was written down: *a generic "thanks, I'll follow up" now
  passes*. Accepted, documented, on the fix list — not hidden.
- **Zero cases in Portuguese or Spanish** despite that being the target market
  (measured 2026-07-30 over the then-83 cases). Deliberately deferred: adding
  languages to exams that can't rank buys saturated scores in more languages.

## Why this transfers

None of the above is specific to these five agents — which is the thesis. The agents
are replaceable in an afternoon; what compounds is the discipline around them:

- **A check must be seen RED before it's trusted green** — every guard gets an
  adversarial input built by hand first (two looked green here while asserting nothing).
- **Kill criteria are pre-registered**, so an experiment can die cheap (receipt 3).
- **Noise bands are computed before rankings**, so a lucky case can't ship a model
  (receipt 1).
- **Fail loud, never a placeholder** — a null response raises; an unparseable verdict
  fails the case; an input matching no committed case raises rather than scoring
  vacuously.
- **The judge is never the model under test** — currently there is no judge at all.

Swap in your agents, your tools, your language, your compliance regime: the exam
harness and the habits are the part you'd keep. That's what "agents are disposable,
eval suites are the asset" means with the receipts attached.

---

## Progress since the freeze — appended 2026-08-24

Same rules as above: every number traces to a committed file, unflattering parts left in.
The repo is at 244 commits (was 235 at the freeze).

### 6. The oracle rewrote the headcount — in the honest direction

Receipt 4 ended at "13 admissible tasks, clears the bar by one." Running the **oracle**
over all of them (the human's own merged code through the identical parse → write →
pytest path the model will use) rewrote that count twice
(`docs/e-corpus-create-2026-08-15.md`): only **3 of 10** surviving modify-tasks are
gradeable end-to-end — 7 fail because function-level splicing cannot represent PRs that
also touch module-level constants and imports, the failure mode ledger entry 018 had
already documented. The harness then learned a second task shape — whole-file **create**
tasks — and the oracle is green **12/12 on the first try** (PR #47, build ledger
entry 022). Pool now: 15 gradeable tasks (12 create + 3 modify), and the sweep that built
it is reproducible from a clean clone because the selection step itself is committed
(PR #46). "Admissible" and "gradeable" turned out to be different claims; the doc says so
instead of keeping the bigger number.

### 7. First model on the pool: 0/9 strict — and that zero has structure

`docs/e-corpus-ladder-2026-08-15.md`: qwen3-8b (24k context baked in, temperature 0.0,
per-task token budgets sized so the 2026-08-01 flat-cap mistake can't recur) against the
new pool. **Strict CI gate: 0 of 9.** Run operator-stopped at task 10 of 14, so it is
titled PARTIAL, not rounded up. But the staged grading splits that zero into two clean
failure modes: **6 near-misses** passing 76–97% of the individual tests in their gating
file (#433 fails exactly one assert of 32), and **3 termination deaths** where the model
writes 22–41k characters and never completes a file — the documented qwen3 signature,
now reproduced at a 3–5× larger budget than the one first blamed for it. Two controls
make the zero trustworthy: the human oracle passes 12/12 through the same pipeline (so
the harness isn't the zero), and task #369 was **excluded rather than scored** because
its prompt exceeds the context window and would have graded a silently truncated input
as model incapacity. A 0/9 with named failure modes and a discriminating difficulty band
is worth more than the 1.00s the frozen scoreboard above calls defects — same inversion,
new instrument.

---

*Repo layout and commands: see the README; the live (moving) state stays in the
working repo.* Lineage of every claim above: the files named inline, all
committed in this repository.*
