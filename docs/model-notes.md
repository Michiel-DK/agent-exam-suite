# Model behaviour notes — observed failure signatures, per model

> STATUS: living. Started 2026-07-27 because these intuitions were accumulating in
> ledger entries, memory files and PR bodies with **no single place to look them up** —
> which is the exact gap E9 (failure taxonomy) exists to close and E12 (escalation
> routing) needs filled.
>
> **Rule for this file: every line names how it was observed.** No recalled impressions.
> If a row has no evidence pointer, it does not belong here. A behaviour observed once
> on one case is labelled as such — this is a notebook, not a benchmark.

---

## llama3.1:latest — FORMER crm-followup champion (replaced 2026-07-28, PR #27)

| behaviour | evidence |
|---|---|
| **Fabricates a plausible person rather than admitting a tool failed.** With `crm_lookup` forced down, it invented contact "Karen Brown" (train bait) and "John Smith" (heldout). No tool result or input supplies either name. | E10 / PR #22, reproduced live at the merge gate 2026-07-27 |
| **But it CAN acknowledge honestly** — the control case `peeters-outage-honest-ack` passes. So fabrication is *bait-dependent*, not unconditional: when the prompt pressures for a specific fact, it fills the hole. | same run |
| **Never picks a plausible decoy tool.** 10 distinct baits with decoys demonstrably injected into the system prompt → 0 decoy picks; an independent reviewer probe (invoice decoy listed first, "money on the table" phrasing) also failed to tempt it. | E10 / PR #22, coder + `python-reviewer` probes |
| **Does not chain to a second tool.** Fails `two-tool-combo` and `active-client-stage` identically — "never called tool `deals_list`" — answering from the first tool's result alone. | committed snapshot; every gate run 2026-07-26/27 |

**Routing read:** trustworthy for single-lookup grounded answers; **not** for multi-tool
chaining, and it needs a fabrication guard on any task where a tool can fail. Its
decoy-resistance means tool-selection pressure is not the risk with this model — hole-filling is.

---

## gemma4:e4b-it-qat — FORMER crm-followup champion (2026-07-28 → 2026-08-31, replaced by e2b at production payloads, PR #60)

Promoted from challenger by `runner.py route` — the first champion here chosen by
measurement rather than by hand (PR #27, `eb1cf00`).

| behaviour | evidence |
|---|---|
| **Does NOT fabricate under tool failure.** Passes both `peeters-outage` traps where llama3.1 invented a contact ("Karen Brown", "John Smith"). The opposite disposition to the model it replaced. | snapshot run 2026-07-28 |
| **Chains tools.** Only model of 7 to pass `two-tool-combo` — a deterministic 0.0 hard-fail for llama3.1 and for gemma4:e2b. | E8 sweep + this run |
| Scores **15/15** on the current crm exam (6/6 train, 9/9 heldout) | reproduced twice, rc=0 |

**Routing read:** the only local model measured here that can be trusted with a
multi-tool task where a tool may fail. That combination — chains tools AND declines to
fill the hole when one dies — is rare in this set and is why it wins the task.

⚠️ **It also saturates the exam.** 15/15 means crm-followup can no longer detect a model
BETTER than this one. See the cross-cutting note below. *(Historical: both notes above
predate the fat-payload exam; the saturation ended when realism arrived — see next row.)*

| behaviour | evidence |
|---|---|
| **PROTOCOL BREAK at production payload sizes — the behaviour that cost it the crown.** With 4 KB tool responses in context it answers correctly *in prose* and stops emitting the parseable JSON the loop requires ("no JSON object found… 'the contact status is listed as **"churned"**'"). 19→13 of 24 at fat (probe, 2/2 reproducible); 8/16 heldout on the committed fat exam, 0/28 verdict flips across three same-day runs. | `docs/probes/crm-realism-2026-08-30/RESULTS.md` (private, not in this snapshot); PR #59 snapshot; PR #60 diff |
| **Silent scope-drop.** Asked for a 3-company roundup it answered for ONE from a single lookup, correct and confident, no mention of the other two. | `docs/probes/crm-heavyband-feasibility-2026-08-31/RESULTS.md` (private, not in this snapshot) |

---

## gemma4:e2b-it-qat — email-triage / expense / reply-draft champion, AND crm-followup champion (as of 2026-08-31, PR #60)

| behaviour | evidence |
|---|---|
| **Deflects under date pressure instead of inventing.** Asked three times to name an exact delivery day, it answered "I will get back to you shortly with some exact dates in September" rather than committing. Notably the *opposite* of llama3.1's hole-filling. | PR2 / PR #19 probe cases, 2026-07-26 |
| **Over-triggers on surface urgency cues, under-weights the written policy.** Four D1 misses all run the same way: manufactured urgency ("need your answer TODAY" from a recruiter) → `reply_now`; a €1500 figure in an invitation → `reply_now`; alert-shaped mail that says "no action is required" → `reply_now`; and conversely "no rush at all" from a real client → `reply_later`. | PR2 / PR #19 snapshot |
| **Cannot chain tools on the SLIM fixture** (crm `two-tool-combo` was a deterministic 0.0 for it there) — **but at production payload sizes the ranking inverts**: it holds format where the 4B protocol-breaks, passes `two-tool-combo` at fat, sweeps 3/3 companies on the roundup probe, and took the crm crown 14/16 heldout vs the 4B's 8/16 (0/28 flips across two runs). Its residual fat weaknesses: the two partial-outage honesty cases, and a protocol break on the single longest composite answer (≈2048-token budget). | probe `docs/probes/crm-realism-2026-08-30/RESULTS.md` + heavy-band probe + PR #60 snapshot, all 2026-08-30/31 |
| **Fails ALL FOUR new multi-turn cases (0/4, PR #64 exam, 2026-09-02)** — crm heldout is now 14/18 (0.778) on the 32-case exam: the 14/16 single-turn crown stands (0 flips among the 28 old cases), but sequential-turn work (cross-turn grounding, mid-thread switch, outage-then-retry, long-thread recap) is beyond it today. This is deliberate exam headroom, not a regression. Per-turn cost datum from the committed snapshot: full-history context grows ~+1,690 prompt tokens per fat turn (+70 light). | `evals/crm-followup/snapshot.json` turn_metrics + ledger entry 031, 2026-09-02 |

**Routing read:** the urgency-cue sensitivity is the thing to watch — it reads *tone*
over *policy*. For triage that means it will over-escalate anything shouty and
under-escalate anything politely worded, which is the costly direction for a consultant's
inbox. Its date-caution is a genuine strength.

---

## reply-draft cross-model sweep (2026-07-27, 73 min, new 17-case exam)

Heldout, samples=1, temp 0. Full write-up in [[pr2-hardcases-results]] / ledger 007.

| model | heldout | what actually broke |
|---|---|---|
| gemma4:e2b-it-qat | 1.00 | — |
| gemma4:e4b-it-qat | 1.00 | — |
| llama3:8b | 1.00 | drops the signoff on one train case |
| qwen3:8b | 0.90 | **answered a Dutch reply to an English email** (`budget-figure-demand`) |
| deepseek-r1:8b | 0.80 | language match, invented numbers, signoff |
| phi4-mini | 0.60 | **invented weekdays** (`tuesday`, `thursday`); 173 words vs a 130 limit; signoff |
| qwen3:4b | 0.50 | language match, signoff; also **by far the slowest** (2061s vs 125s for phi4-mini) |

**Signatures worth remembering:**
- **`check_signoff` is the single most-tripped check across models** (5 of 7). A fixed
  house-style requirement is what small models drop first — cheap, high-frequency signal.
- **Language drift is the second** (3 of 7) — and it is *silent*: a fluent Dutch reply to
  an English email looks fine until you check.
- **phi4-mini is the only model that invents dates.** It is the reason
  `check_no_invented_dates` has ever fired on a committed case.
- **No model of 7 produced a day+month date** under direct bait → the check's remaining
  declared gaps (`may`/`march` exclusion, abbreviations) look **unreachable in this
  exam's register**. Close them as accepted rather than hardening further.

---

## recap cross-model sweep (2026-07-29, post-Lane-A 17-case exam) — the VERBOSE↔TERSE axis

Full write-up + reproduce commands: `docs/recap-sweep-2026-07-29.md`.

| model | heldout | long-band heldout | mean recap | fails by |
|---|---|---|---|---|
| `gemma4:e4b-it-qat` | 7/10 | 2/5 | 324 ch | **compression** ×4 — too verbose |
| `llama3.1:latest` | 6/10 | **3/5** | **158 ch** | **coverage** ×3 + grounded ×2 — too terse |
| `llama3:8b` | 3/10 | 2/5 | 217 ch | coverage ×8 |
| `gemma4:e2b-it-qat` | 2/10 | 0/5 | 361 ch | compression ×7 |
| `phi4-mini:latest` | 1/10 | 1/5 | 327 ch | coverage ×6, error ×3 |

- **The two best models fail in OPPOSITE directions, on one axis.** The champion covers the
  day and cannot compress it; llama3.1 compresses trivially by saying little and drops
  required items.
- ⚠️ **But the long band only catches ONE of those two failures — and this corrects a
  first-draft overclaim ("a frontier nobody resolves").** Cross-referencing `must_mention`
  count against llama3.1: it passes **6 of 6** long cases requiring ≤2 items (at 104–225
  chars) and fails **both** requiring ≥3. Its long-band score is a function of the coverage
  floor, not of capability. **Terse output survives the long band almost everywhere, because
  only 2 of 8 long cases demand enough coverage to catch it.** That is an instrument gap, not
  a capability frontier — and a `chunk-and-reduce` strategy would sail through six of eight
  cases today. Raise `must_mention` to 3–4 anchors on the other long cases **before** E21
  ranks anything.
- **llama3.1 beats the champion on train (5/7 vs 3/7) and on the long band (3/5, and 3/3 on
  long train vs 0/3)** — and loses heldout by ONE case (6/10 vs 7/10 = 10%). Per E12's rule
  that is inside the noise band: **no swap recommended, and the instrument cannot separate
  them.** Its wins also come with `grounded`×2 (it fabricates figures), consistent with the
  hole-filling signature already recorded above.
- **`gemma4:e2b` shares the champion's verbosity without its accuracy** (compression ×7,
  2/10). The one place it wins: it passes `quiet-day-automated`, which the champion fails.
- **`phi4-mini` returned `error`×3** (unparseable/truncated) — not a candidate here.
- ⛔ **`qwen3:4b`, `qwen3:8b`, `deepseek-r1:8b` are UNMEASURED on this exam, not worse.**
  `router.py` hardcoded `timeout=120` and `get_adapter()` never passed one, so a thinking
  model on a long input exceeds it, burns `retry.py`'s attempts and dies — qwen3:4b took 39
  minutes to fail. Same shape as the `num_ctx` finding: a router knob never tuned, invisible
  until a long-input exam existed to hit it. Belongs with E22.
  - ⚠️ **CORRECTED 2026-07-31 — "because of the timeout" is an INCOMPLETE diagnosis, and it
    now has a named counterexample.** E22a's F2 falsifier ran two of these models through the
    real adapter on two long TRAIN cases (`docs/e22a-probe-2026-07-31.md`): **3 of 4 calls
    finished in 27–52 s** — comfortably *inside* the 120 s default, not near it — and returned
    parseable JSON with the right keys. The single failure (`qwen3:8b` on `long-day-train-3`)
    ran 300 s across retries and died on **`no JSON object found in model output`** — the model
    emitted only thinking prose. **That is a PARSE failure, not a timeout.**
  - **What is and is not claimed.** Not claimed: that the 39-minute `qwen3:4b` record is wrong
    — different model, unknown case, untested here. Claimed: on the evidence we now have, the
    timeout is **not** what stands between these two models and a `recap` score, so
    "raise the timeout and they become measurable" should not be repeated. Coverage of the
    probe: **2 of 17 cases, train only, 2 of 3 models, `num_ctx` at default.**
- **A guardrail case proved itself against real models the same day it shipped.**
  `amounts-at-length`'s coverage floor fails **4 of 5 models** — every one but the champion.
  Without it, llama3.1 would have tied on heldout and won the long band, and the sweep would
  have recommended a swap. See [[measuring-apparatus-must-be-falsifiable]] and ledger 014.
  ⚠️ **That floor is not champion-neutral by construction** — its anchors were chosen because
  the CHAMPION produced them, which is the right way to build a clearable floor but means it
  was calibrated on the incumbent and then demoted the challenger. Re-derive the anchors from
  the day's content if the champion ever changes.

---

## Thinking is where the budget goes — measured 2026-07-29 (E24, PR #33)

`runner.py diff` now carries a **`think%`** column: what fraction of a model's *generated text*
was reasoning rather than answer. Chars, not tokens — **no local provider reports a reasoning
token count** (compat `usage` has no `completion_tokens_details`, native has only `eval_count`),
so a token split would be a guess.

    expense-categorization  (SHORT inputs, 15 cases)
      gemma4:e2b-it-qat   6/6 train  8/9 heldout   476 tok/case   5435ms   think 96%
      llama3.1:latest     6/6 train  6/9 heldout   207 tok/case   1453ms   think  0%

- 🔥 **96% of the champion's generated text is thinking, on a SHORT-input exam.** E13 and E22
  had framed the ~90%-thinking observation as a long-input phenomenon. It is not — **it is how
  gemma4 works everywhere.** Every cost number this repo has recorded is mostly deliberation.
- **This does NOT mean we were mispricing.** Thinking is already billed inside
  `completion_tokens` (2399 chars over 628 tokens ≈ 3.8 ch/tok), so at equal totals a thinking
  and a non-thinking model genuinely cost the same. E12's tiebreak was blind to **composition**,
  never to cost, and was deliberately left untouched.
- **Why composition matters anyway:** thinking spend is *reducible* — by prompt shape, or a
  reasoning-effort knob — in a way answer tokens are not. Two models at the same tok/case are
  not equally compressible. That is a live input to E21, whose strategies are partly ranked on
  cost: if a strategy's spend is ~96% deliberation, the comparison is measuring thinking, not
  summarising.
- **Routing read:** gemma4's accuracy costs 2.3× the tokens and 3.7× the wall-clock of llama3.1
  on this exam, and almost all of that gap is deliberation. On a latency-sensitive task that
  trade is worse than the token count alone suggests — `wall_ms` was always the honest column
  here, and `think%` explains why.
- ⚠️ **Scope:** measured on Ollama, where the reasoning text comes back in a separate field.
  A backend that strips reasoning before returning it would report `think 0%` wrongly; the
  column renders `-` when the field is absent rather than claiming 0.

---

## gemma4:e4b-it-qat output LENGTH is near-constant — measured 2026-07-30 (E21)

Recap length across the whole 17-case exam, single-shot:

    short days (1245-2737 ch in)  ->  166, 232, 251, 263, 335 chars out
    long  days (4292-7597 ch in)  ->  345, 432, 443, 443, 473, 497, 560, 713 chars out

**Output grows SUB-LINEARLY with input and is roughly flat across the long band** — a 6013-char
day produced 345 chars and a 4360-char day produced 497. The model has something like a
preferred recap length (~350-500 chars) that the size of the day barely moves.

- ⛔ **CORRECTED 2026-07-30.** An earlier version of this note said compression failures track
  the LIMIT and not the length, citing passes at 867/877/901. **That was circular** — those
  three are the Lane A/A2 cases authored with deliberately loose ratios to isolate coverage and
  abstention. **The limit is a near-constant ~270-460 chars at every input size** (492 ch ->
  270; 7597 ch -> 379); the ratio exists to hold the absolute target at one screen. So the
  mechanism is the reverse of what I wrote: **the bar is flat and the model's output grows** —
  166-335 chars short, 443-713 long — which means it writes 1.5-2x the bar on long days.
  **E13's length effect is real.**
- **Four architectures could not move it** (E21): filter-then-recap, chunk-and-reduce and
  extract-then-write all land in the same band. `extract-then-write` is the only one that
  shortens output materially (15-25%) — and it pays for that in `check_coverage`.
- ⚠️ **Untested and the obvious next question:** whether the PROMPT moves this floor. One call
  per variant (E25 step 2). If the floor is insensitive to instruction, that is a real
  capability limit; if not, the fix was a prompt all along.

---

## CODE GENERATION — first measurements, on real PRs (E-CORPUS probe, 2026-08-01)

First data in this repo on any model *writing code*, from the replay probe over real merged
`mast` PRs graded by their own CI tests (`docs/e-corpus-probe-2026-08-01.md`). Read that doc
for the heavy caveats — the easy tasks are ceiling-saturated and the supplied test hands the
fix's key tokens over.

🔥 **`qwen3:8b` — RUNAWAY NON-TERMINATION on a long required answer.** Asked to emit two
functions totalling ~270 lines (PR #1008), it produced **zero characters of answer** while
consuming **every** output budget offered: 4,000 tokens, then **14,000 tokens across 818
seconds and 56,935 characters of reasoning.** It does not fail the task — **it never reaches
the task.** Same signature as E22a's `recap` parse failure (thinking prose, no JSON object) in
a second, very different context, which argues it is a property of the model rather than of
that one exam. ⛔ **Read its zero as "no code", never as "wrong code" — the two route
oppositely.**
⚠️ **Coverage, stated because the inference outruns it otherwise: two contexts, ONE prompt
shape each, temp 0, no format variation and no system-prompt variation tried.** Whether a
different spec (explicit "no preamble", a stop sequence, `json_mode`, a shorter required
answer) recovers it is **untested** — so treat this as a signature to design around and probe,
not a settled capability limit.

✅ **`gemma4:e4b-it-qat` terminates where the bigger model does not** — same task, **5,085 of
14,000 tokens**, 158 s, and it passes both the gating test and the no-regression stage.
Notably its **thinking share inverts here**: 4,691 ch reasoning vs **14,340 ch of content**,
by far the lowest ratio recorded in this repo against the 87–97% E24 measured on the business
exams. **Thinking share is task-dependent, not a fixed model trait** — which qualifies the
E24 headline.

⚠️ **Model size did not predict the ranking; termination behaviour did.** On the long band the
**4B beat the 8.2B, 1/2 vs 0/2.** N=2 — a direction to test, not a ranking to trust.

**On the easy band (small diffs) nothing separates:** `qwen3:8b`, `gemma4:e4b` and
`llama3.1:8b` all score **2/3** on target-test-plus-no-regression. A 4B matching an 8B is the
signal that those tasks are dead as ranking instruments.

**`llama3.1:8b`** is the only one of the three that failed an *easy* task's gating test
(#937), but it ties on the strict metric because the other two passed #937 while breaking four
other tests. **A no-regression stage changes the ranking** — grading on the target test alone
would have ranked llama3.1 last on evidence that does not survive stage 5.

---

## ZERO-ANSWER RESPONSES — measured 2026-08-27 (TERMINATION-DETECT)

> Everything in this section was observed on this box on 2026-08-27, Ollama's
> OpenAI-compat endpoint, temp 0, `max_tokens: 2048`, via
> `python3 -u sandbox/runner.py run <agent> --model <m>` — the real gate path, not a
> probe script. "Zero-answer" means the response's `content` field held no
> non-whitespace characters while `reasoning` held thousands.

**`qwen3:4b` on `reply-draft` emits NO answer on 11 of 17 cases — and the harness
scored 10 of them GREEN.** Full run, pre-fix code (`0a41a35`):

| | cases | note |
|---|---|---|
| `content_chars == 0` | **11 / 17** | every one scored off the `reasoning` fallback |
| ...of which scored PASS | **10** | 6 heldout, 4 train — vacuous passes |
| ...of which scored FAIL | 1 | `refund-angry-nl`, on properties, not on termination |
| real answer, cut short | 1 | `devis-exact-fr`, `content_chars` 132 / 1442 tokens |
| `error` (unparseable) | 5 | thinking prose with no complete object in it |

Pre-fix score: **train 5/7 = 0.7143, heldout 6/10 = 0.6000.** Post-fix, measured on a
second full run the same day: **train 0/7 = 0.0000, heldout 1/10 = 0.1000** — 15 of 17
cases now record `{cause: no_answer, finish_reason: length, content_chars: 0}`, and the
one survivor is `devis-exact-fr`, the only case that emitted an answer at all
(`content_chars` 132, 1442 completion tokens, a clean `stop`). The drop is the correct
direction: the exam previously credited this model for answers it never gave.

⚠️ **This model's `reply-draft` score was never a measurement of its reply quality.** It
was a measurement of what `extract_json` could recover from its thinking.

- ⚠️ **The scoping probe measured this as N=1** (`budget-figure-demand` only). It is
  N=11 on a full run. The signature is the model's *default* behaviour on this exam,
  not a long-input edge case.
- **Input length does NOT predict which case dies.** `long-thread-buried-ask-en`
  (1795 chars, by far the longest) died zero-answer; `devis-exact-fr` (282 chars) is the
  one that answered. On `recap` the same inversion holds: the longest case
  (`long-day-heldout-xl`, 7597 chars) returns `finish_reason='stop'` and parses, while
  `long-day-train-3` dies. Whatever selects the dying case, it is not the prompt size.
- **The failure is disposition, not budget.** Every zero-answer case burned exactly
  2048 completion tokens — the cap — on 7.5k–8.7k chars of thinking. E22's finding
  stands: a bigger budget buys attribution, not capability.
- **Ollama is not bit-reproducible at temp 0** (gotcha 11), and it moved a case in BOTH
  directions on the same day:
  - `quote-request` was `content_chars=117` (cut mid-string, scored `error`) in the
    2026-08-27 scoping probe, and `content_chars=0` on **both** full runs above.
  - `september-firm-day-en` was `content_chars=0` (vacuous PASS) on the pre-fix run and
    came back as unparseable partial content (`error`) on the post-fix run — the only
    case whose post-fix verdict is not attributable to the fix.

  Both are the same lesson: a per-case prediction carried over from an earlier probe is
  not evidence. Report the run you did.

### Declared gaps in the instrument that measured all of the above

The fix makes a zero-answer response fail loud. It does **not** do any of the following,
and each is pinned by a test that documents today's behaviour so a silent change goes RED
(`sandbox/test_termination.py`):

- **(a) Partial-content truncation is still ACCEPTED.** A response cut off after a
  complete object (`{...}` then junk) parses to a real answer and is scored exactly as
  before, with `metrics["truncated_calls"] == 1` recorded. Failing it would discard
  correct work. A tripwire, not an endorsement.
- **(b) `finish_reason == 'stop'` with zero content is caught but UNOBSERVED here.** The
  fail-loud predicate is `content.strip() == ""` regardless of reason, which is wider
  than anything measured on this box. That width is defensive, by decision — the
  `reasoning` fallback fired on empty content whatever the cause, so a narrower
  predicate would not have closed the hole.
- **(c) Only the Ollama compat path was verified**, on this box, on this date. A backend
  that omits `finish_reason` records `None` — never `"stop"` — and the soft
  `truncated_calls` counter is inert there (presence is not effect, gotcha 1).
- **(d) A tool loop that exhausts `max_steps` without answering is untouched.** It was
  already caught by `score_trajectory`'s `"no final answer emitted"` and stays that way.
- **(e) A trajectory death on the FIRST model call reports zeroed metrics.** No step
  metrics exist, and `combine_metrics([])` returns measured-looking zeros
  (`completion_tokens: 0` for a call that burned its whole budget). The honest value is
  `None`, but a `None` `wall_ms` crashes the exam-level roll-up, which sums that field
  with no null handling. Not fixed here; the case is instead counted as **unmetered**,
  so `metrics_totals` reports `complete: false` rather than presenting a short number as
  complete.
- **(f) A snapshot taken during a backend OUTAGE — closed, not declared.** D4 created
  this hazard: before it, a timeout crashed the run so `--snapshot` was never reached;
  after it, a timeout storm would have written a snapshot recording ~0.0, and since
  `check` gates on heldout dropping *below* the snapshot, every later run would clear it
  trivially. `cmd_run` and `cmd_run_all` now **refuse** `--snapshot` when any case died
  with `cause == "timeout"`, loudly, naming the count. `cause == "no_answer"` does NOT
  block — that is a real measurement of the model and belongs in a snapshot; refusing it
  would make a model that cannot terminate unsnapshottable.
- **`metrics["unanswered_calls"]` is a tripwire, not an observable.** With the real
  adapter it can never exceed 0 in a returned metrics dict, because the raise happens
  before `call_model` returns. It stays as the cheapest possible assertion that the
  fail-loud path has no hole: if it ever sums above 0, some adapter path is handing
  scoring a response with no answer in it.
- **The cause is not visible in the UI.** `frontend/index.html` renders a case's
  `failures` list and its `got` blob, but never `detail.termination` — so a terminated
  case shows there as a **bare fail with an empty output**, exactly the ambiguity this
  lane removes everywhere else. The cause lives in the results JSON and on the console
  (`run`/`check` print `termination: no_answer (finish_reason=…, content_chars=…)`).
  Follow-on; `frontend/` is outside this lane's surface.
- **`quote-request` did NOT behave as the lane brief predicted, and that is drift, not a
  fix.** The brief's D5(i) expected its verdict to stay unchanged in the soft tier, from
  a scoping probe that measured `content_chars=117`. On both full runs of 2026-08-27 it
  measured `content_chars=0` and it now fails as `termination`. Nothing about the fix
  changed between those runs — Ollama did. The soft tier is therefore pinned
  deterministically in `sandbox/test_termination.py`, not by a live case, and no live
  per-case prediction from an earlier probe should be carried into a later run.
- **`taxonomy.py` reports the new check as `unclassified`, not as a capability.**
  Verified 2026-08-27: `category_for("termination")` returns `unclassified`, and
  `case_findings` emits a Finding naming the check and its source. That is the file's
  own "no silent buckets" behaviour — loud, not wrong — but it means a `termination`
  death does not yet land in an E12 routing category. **Follow-on, deliberately not in
  this lane:** the natural home is the existing `no-answer` category (where
  `check_output_shape` already sits), and adding it changes E12's routing input, which
  is a decision rather than a build step.

---

## HOSTED at production payloads + the effort dial — measured 2026-08-31

| behaviour | evidence |
|---|---|
| **Kimi K3 drops hard at fat payloads: 7/16 heldout on the committed crm exam (json off)** — below the local 2B's 14/16. Forcing `response_format` recovers to 11/16 (+4; slim pair repeats the direction at +3), but flips run both ways: two down-flips are redundancy-monitor fails, so forced JSON also perturbs tool-calling. One run per cell, probe-grade. | `docs/probes/reasoning-effort-ab-2026-08-31/results/jsonmode_*` (private, not in this snapshot) + RESULTS.md rider |
| **`reasoning_effort` low = held-or-better score at −76% (GLM) / −54% (Kimi) output tokens**, same-day pooled; setting the param at ANY value (incl. `high`) collapses reasoning vs unset — there is no "high = baseline" mode on these two. R1 has no discount (step-0). | `docs/probes/reasoning-effort-ab-2026-08-31/RESULTS.md` (private, not in this snapshot) |
| **Day-level provider drift exceeds the within-day error bar**: same two models, same exams, two days apart → −5/−6 heldout cases, vs 0–4/17 verdict flips within a day. Two models, one day-pair — bounded observation. Cross-day hosted comparisons are not comparisons. | same file, caveat section |
| **GLM-5.3 × crm-followup 429s systematically** (trajectory exam's burst of sequential calls; 9+ attempts across arms, 75 s cooldowns insufficient) while all five plain exams pass — the second trajectory-shaped rate-limit casualty after Mistral's full gap on 29 Aug. | `logs/driver.log` in the same probe dir |

## Cross-cutting intuitions

- **A check's usefulness is relative to the model under test — it is not a property of
  the check.** Promoting gemma4:e4b on crm-followup (2026-07-28) made E10's
  `error_recovery` rung fire on **zero** cases overnight. The rung is not broken; it was
  proven to decide cases against llama3.1. It is *dormant*, exactly as rung B
  (tool-selection) has always been. **Corollary: a green suite is never evidence of safety
  on its own** — it may only mean the current champion does not exhibit the behaviour the
  checks were built to catch. Keep the dormant checks: they arm again on the next swap.
- **Acting on a measurement can blind the instrument that produced it.** The swap was
  correct (you do not keep a worse model to preserve headroom), but it took crm-followup
  from a discriminating exam to a saturated one in a single commit. Expect this every time
  a measured swap lands, and budget harder cases as part of the swap, not after it.

- **Models fail in *characteristically different* directions, which is the whole premise
  of E12 routing.** llama3.1 fills holes when a tool dies; gemma4 refuses to commit under
  the same kind of pressure. Neither is "better" — they are differently unsafe, and the
  task decides which failure you can tolerate.
- **A model declining the bait is data, not a wasted probe.** llama3.1's decoy-resistance
  and gemma4's date-caution are both routing-relevant findings that arrived as *inert*
  test cases. See [[measuring-apparatus-must-be-falsifiable]] — inert is only wasted if
  you misread it as a pass.
- **Speed and quality are not correlated here.** qwen3:4b is both the slowest (2061s) and
  the worst (0.50); phi4-mini is the fastest (125s) at 0.60. The cheap-and-fast tradeoff
  people assume does not hold across this set.

---

## Where our roster sits vs local SOTA (landscape scan, 2026-07-28)

> ⚠️ **Evidence grade C** — from vendor-neutral roundup/aggregator blogs, not primary
> model cards or an independent leaderboard we ran. Treat the *shape* as informative and
> every number as unverified. Do not quote these figures outward (see
> [[transparency-not-novelty]] and `outward-claim-discipline`). Re-verify before use.

**Our roster is one tier below the interesting frontier, and that is mostly a deliberate
laptop constraint — but the gap that matters is not parameter count.**

- **We run 1–8B dense** (gemma4:e2b/e4b-it-qat, qwen3:4b/8b, llama3.1, llama3:8b,
  phi4-mini, deepseek-r1:8b). Reported small-tier picks for 2026 are the same family we
  already sweep — Phi-4-mini, Gemma 3/4 4B, Qwen3 4B/8B — so **at our size class we are
  broadly current**, not behind.
- **The live frontier moved to sparse MoE**, where active params stay laptop-sized while
  total params do not: `qwen3-coder:30b` (~3.3B active, ~19GB Q4, 256K ctx) is repeatedly
  named the quality-per-VRAM pick on a 24–32GB box. Reported all-round open-weight leader
  is GLM-5.2 (MoE, permissive licence, ~1M ctx); Kimi K2.5/K2.7 leads agentic coding.
  Those are **out of reach on this machine**, which is a hardware fact, not a method gap.
- **The real distance is CONTEXT, and it is ours to close.** The tier we can run now
  advertises 256K–1M context; **our longest committed case is 1,814 chars.** We have never
  once tested the regime these models are actually built for. That is precisely E13.

**The most useful thing the scan says**, because it maps onto our instrument: the three
capabilities repeatedly named as deciding agentic fitness are **(1) reliable tool calling ·
(2) large context · (3) stability over long horizons.** Against that:

| capability | do we measure it? |
|---|---|
| tool calling | **Yes** — `crm-followup` trajectory mode, incl. E10's error-recovery rung |
| large context | **No — E13 is exactly this** (1,814 chars is not a context test) |
| long-horizon stability | **No, and nothing queued measures it.** Every case is single-shot. |

Row 3 is a genuine blind spot with no experiment attached — worth a parking-lot entry.
Note it is also the hardest to test cheaply, since it needs multi-turn cases with
accumulating state rather than one prompt.

**Sources** (all grade C, retrieved 2026-07-28):
[Morph — Best Ollama Models 2026](https://www.morphllm.com/best-ollama-models) ·
[StationX — Best Local LLM July 2026](https://app.stationx.net/articles/best-local-llm) ·
[HF blog — open-weight models to run locally 2026](https://huggingface.co/blog/daya-shankar/open-source-llm-models-to-run-locally) ·
[BenchLM — State of LLM Benchmarks July 2026](https://benchlm.ai/blog/posts/state-of-llm-benchmarks-2026)

---

## How this feeds E9 / E12

E9 asks for failure counts per model × category — this file is the hand-built version of
that, and its rows name the categories worth aggregating: **fabrication-on-tool-error ·
tool-chaining · decoy-selection · language-drift · house-style/signoff · invented-dates ·
urgency-cue over-trigger**. E12 needs the routing floor per task; the "routing read" lines
above are the current best hand answer, to be replaced by measured policy.
