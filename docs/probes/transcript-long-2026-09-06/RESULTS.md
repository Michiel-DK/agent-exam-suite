# transcript-long — lane 1 scorecard (2026-09-06)

Lane 1 of `docs/sprint-map.md` STATE 5 Sep
(`docs/transcript-long-brief-2026-09-06.md`). Same-day, foreground, one model
per run (qwen killed and re-run alone after being started concurrently with
the champion by mistake — see the non-determinism note below). Champion
field and split assignment are **PROPOSED — operator signs at merge**
(build criterion clause 8).

## Timing: the >=30000-char case

`longcall-support-heldout-2`, 32,739 chars, timed on `gemma4-e4b-ctx16k`
before being kept in the committed band (criterion clause 2's escape
clause): **48.4s** (exploratory run) / reproduced within the same order of
magnitude on the official `--snapshot` run and again on `check` — comfortably
under the untunable 120s `check` ceiling, ~2.4x headroom. No `timeout_s` set.

## An observed non-determinism (honest finding, not hidden)

Two consecutive local runs of the exact same 32-case exam on the exact same
model/config (`gemma4-e4b-ctx16k`, temp 0, samples 1) produced a DIFFERENT
verdict on one case: `support-heldout-long` (an OLD, pre-existing case)
PASSED on the first (exploratory) run and FAILED on the second (the
`--snapshot` run actually committed). `check_coverage`'s failing substring on
the second run was `1284.50` — a number the model included on one run and
omitted on the other, with everything else about the run identical (same
process, same weights, same prompt, temp 0). This repo's own convention
("Gates are deterministic — committed configs reproduce at samples=1, temp
0") is therefore not perfectly true at the wall-clock level on this machine
for at least this model/backend (Ollama's Metal path on Apple Silicon) — a
finding for the suite generally, not specific to this lane's two new checks.
Consequence: the committed `snapshot.json` is the `--snapshot` run's output
(the one actually written to disk), and `check`'s own reproduction (below)
is the load-bearing evidence for clause 1, not the earlier exploratory run.

> **Pass-2 pointer (not itself SUPERSEDED, but incomplete on its own):** the
> "one-run anomaly, not a recurring instability" framing above was written
> before the instrument lane. `docs/probes/snapshot-reproducibility-2026-09-07/RESULTS.md`
> (master, 7 Sep) settled what the instrument was blind to: `check` compared
> only the heldout aggregate, so cancelling per-case flips printed `ok` —
> master's own 26 Aug transcript-en snapshot diverged on 5 of 22 cases while
> `check` said fine. The CAUSE was the Ollama 0.33.2 runtime bump (31 Aug),
> deterministic today; the 6 Sep "temp-0 differs across model loads" reading
> did NOT reproduce (174 cases × 4 fresh loads, 0 unstable on all 7 exams).
> This lane's pass-1 non-reproduction is therefore unexplained at n=2 runs —
> not attributed to across-load variance — and pass 3's rule-A re-snapshot
> (3 fresh loads, per-case `stable`) is what settles it. Fixed on master as
> rule A (per-case `check`, runtime version pinned);
> pass 2 does not re-run inference (no local model in this pass) and keeps
> this branch's stale, pre-instrument-fix snapshot — see clause 6 below.

## max_ratio timing — a disclosure, not a claim of strict blindness

`max_ratio=0.05` was added to the 9 non-quiet `longcall-*` cases' `expected`
blocks (train AND heldout) AFTER one exploratory (non-`--snapshot`,
uncommitted) run had already produced pass/fail verdicts on the `longcall-*`
heldout band — so this is NOT the strictly-blind sequencing the brief's
"instrument fix designed blind" language describes for the speaker-token fix
above. Flagged explicitly rather than left for a reviewer to find. Three
facts bound the risk: (1) the ratio was derived exclusively from the TRAIN
cases' observed summary lengths (`calibrate.py`), never from heldout output;
(2) it was applied by one uniform rule to every non-quiet case, not
cherry-picked per case; (3) empirically, `check_compression` fires on ZERO
of the 10 `longcall-*` cases across all three measured models (champion,
qwen3:8b, Kimi) — so this addition had NO causal effect on any reported
verdict in this scorecard, checkable directly against the tables below. The
heldout cases' load-bearing content — input transcript, `must_commit`,
`commit_owner`, `must_not_commit`, `speakers` — was authored and committed
before any model ever saw it and was never touched afterward.

## Champion run: `gemma4-e4b-ctx16k` (PROPOSED) — SUPERSEDED by pass 3

> **SUPERSEDED (pass-2 python-reviewer major, actioned in pass 3).** The
> `8/19` heldout count and `0.4211` score below were computed on pass 1's
> `--snapshot` run (6 Sep, single-load, no runtime stamp, pre-rule-A) against
> pass 1's `check_action_owner` (every-hit) AND pass 1's answer key (before
> the three 8-Sep-signed corrections above). Pass 3 re-runs `--snapshot`
> under rule A (3 fresh loads, per-case `stable`, live `runtime.version`) on
> the corrected `cases.json` and the fixed `properties.py` — see "Pass 3 —
> live re-run" below, which replaces every number in this section and the
> next.

`--snapshot` run: **train 6/13, heldout 8/19** (13 pre-existing train + 4
`longcall-*` train = 13; 13 pre-existing heldout + 6 `longcall-*` heldout =
19).

`check transcript-en` reproduction: **`ok: heldout 0.4211 vs snapshot 0.4211`**
— and stronger than the aggregate score match the command itself checks: all
32 cases' individual pass/fail verdicts AND failure messages reproduced
EXACTLY, word for word, against the committed snapshot (diffed by hand
against the `--snapshot` run's own console log). Clause 1 satisfied with the
strongest evidence the tool can produce. This is also the answer to the
non-determinism note above: it was a one-run anomaly between the
EXPLORATORY run and the `--snapshot` run, not a recurring instability — the
`--snapshot` run and the subsequent `check` run (a third, independent
process) agree on every one of the 32 cases.

## 22 pre-existing cases: old champion (`gemma4:e4b-it-qat`) vs new champion
(`gemma4-e4b-ctx16k`) — 4 flips (programmatic diff, not eyeballed) — SUPERSEDED by pass 3

> **SUPERSEDED.** This table diffs pass 1's own two runs (old champion vs
> new champion, both pre-rule-A, single load) against EACH OTHER — a
> different comparison from criterion clause (5)'s "22 pre-existing cases vs
> MASTER's 7 Sep snapshot", which pass 3 adds below. Kept for the record,
> not restated.

| direction | case | old failed | new failed |
|---|---|---|---|
| GAIN | `pricing-objection-medium-train` | `check_action_items` | (none) |
| LOSS | `quiet-checkin-medium-train` | (none) | `check_abstention` |
| LOSS | `renewal-heldout-digits` | (none) | `check_coverage` |
| LOSS | `support-long-train` | (none) | `check_coverage` |

Net: **-2** on the 22 pre-existing cases (old-band pass count 14/22 -> 12/22:
train 6/9->5/9, heldout 8/13->7/13). The brief's own prediction ("no losses —
none exceeds ~2k prompt tokens") is **falsified** — the window swap has a
real cost on cases that never approach the old 4,096-token ceiling. This
looks like the same non-determinism noted above rather than a systematic
regression mechanism (none of the 3 losses' failure reasons — an omitted
figure, an omitted name, a flipped abstention flag — are connected to
context length), but it is reported as observed, not explained away.

## `longcall-*` heldout scorecard (clause 5/6/7) — SUPERSEDED by pass 2

> **SUPERSEDED.** Every verdict below was computed under pass 1's EVERY-HIT
> `check_action_owner` rule (ledger 041 finding 1: a `commit_owner` key with
> >= 2 hits failed unless ALL of them were correctly owned — rejected a
> genuinely correct output where both sides legitimately say "follow up").
> Pass 2 ships ANY-HIT-CORRECT instead. The corrected, per-model,
> per-check_action_owner-rule table — including which of the FAILs below
> flip to PASS solely from that fix — is the **PROVISIONAL** table near the
> end of this file. Read that table for the current verdicts; everything
> below this point down to "## Verdict" is the pass-1 record, kept for the
> paper trail, not the current answer.

All three models run through the SAME scratch-copy technique
(`docs/probes/transcript-long-2026-09-06/{qwen,kimi}_scratch_run.sh` +
`scratch_setup.py`) scoped to the `longcall-*` band only — a `git archive`
copy of this branch's HEAD with `cases.json` filtered to the 10 `longcall-*`
cases, run through the real `sandbox/runner.py run` entry point. Raw
per-case results committed at
`docs/probes/transcript-long-2026-09-06/results/*.json`.

| id | chars | gemma4-e4b-ctx16k (champion, PROPOSED) | qwen3:8b | moonshotai/kimi-k3 (pinned) |
|---|---|---|---|---|
| `longcall-pricing-heldout-1` | 16,002 | FAIL (`check_action_items`) | FAIL (`error` — dead run) | FAIL (`check_withdrawn_excluded`) |
| `longcall-scoping-heldout-1` | 19,529 | FAIL (`check_coverage`, `check_grounded`) | FAIL (`error` — dead run) | FAIL (`check_coverage`) |
| `longcall-discovery-heldout-2` | 21,555 | **PASS** | FAIL (`error` — dead run) | FAIL (`check_action_items`) |
| `longcall-renewal-heldout-2` | 25,377 | FAIL (`check_action_owner`, `check_grounded`) | FAIL (`error` — dead run) | FAIL (`check_action_items`, `check_action_owner`) |
| `longcall-support-heldout-2` | 32,739 | FAIL (`check_action_owner` ONLY) | FAIL (`error` — dead run) | FAIL (`check_action_owner`) |
| `longcall-mixed-heldout-3` | 20,034 | FAIL (`check_action_items`, `check_action_owner`) | FAIL (`error` — dead run) | FAIL (`check_action_items`, `check_action_owner`) |

(train band, for completeness: champion 1/4 pass, qwen3:8b 1/4 pass — only
the 12.4k-char quiet case, which needed no `action_items` at all — Kimi 1/4
pass, same quiet case.)

**Champion heldout pass count: 1/6** (`longcall-discovery-heldout-2` only) —
strictly between 1 and N_heldout-1=5, per clause 5. Discriminating check
present on multiple heldout failures: `check_action_owner` fires on 3 of 5
champion failures (`renewal-heldout-2`, `support-heldout-2`, `mixed-heldout-3`);
`longcall-support-heldout-2` fails ONLY `check_action_owner` — a live
isolation on a real case, cited per the brief's own note that this outranks
a fixture.
>
> **SUPERSEDED (this paragraph specifically):** under the shipped any-hit
> rule, `longcall-support-heldout-2` FLIPS to PASS on `check_action_owner`
> (see the PROVISIONAL table — this is the exact case ledger 041 finding 1
> names), so "fails ONLY check_action_owner" / "fires on 3 of 5" are pass-1
> numbers, not the current ones. The champion's current heldout pass count
> is in the PROVISIONAL table's per-case rows, not restated as a new
> headline number here — that composite re-count is pass 3's job (this
> pass's PROVISIONAL table reports the `check_action_owner` column only,
> not a re-aggregated heldout pass/fail count for the whole case, since
> `--snapshot` was not re-run).

**qwen3:8b heldout pass count: 0/6** — dies outright (`error`, R7's
unparseable-after-every-retry gap) on every `longcall-*` case above 16k
chars, confirming the brief's own prediction ("it WILL die on long calls at
4k; that is the finding, recorded, tiers untouched"). routes.yaml tier 1 is
left as committed per the brief's explicit instruction — this is the
recorded finding, not a fix.

**Kimi (pinned `moonshotai`) heldout pass count: 0/6.** Champion (1/6) vs
Kimi (0/6): **not a tie** — clause 7's HALT condition does not apply on
either count (champion vs Kimi is not a tie; clause 5 is satisfied). Kimi
also independently trips `check_withdrawn_excluded` on
`longcall-pricing-heldout-1` (the "premium support add-on" it was told was
withdrawn resurfaces as a Kimi commitment) — a second, model-independent
live isolation of that check, and Kimi separately trips `check_compression`
on 2 of 4 train cases (767/766 and 892/849 chars — its summaries run
measurably longer than gemma's, which never approaches the 0.05 cap on any
of the 10 cases).

Kimi cost: 10 calls (scoped to the `longcall-*` band only), consistent with
step-0's ~$0.05-0.07/long-call rate.

## Verdict — pass 1's, SUPERSEDED where it rests on the every-hit count

> **SUPERSEDED (in part).** This section is pass 1's verdict, computed under
> the every-hit `check_action_owner` rule. It is kept for the record, not
> restated as pass 2's verdict — pass 2 ships code only (no local model run,
> no `--snapshot`), so it produces no new heldout pass-count or merge-gate
> recommendation of its own; that composite judgment is pass 3's job, per
> the PR body's "what pass 3 must do" list. What IS current: the per-case,
> per-model `check_action_owner` verdict comparison in the PROVISIONAL table
> below, which supersedes the specific clause-5 discriminating-check claims
> this paragraph makes (`longcall-support-heldout-2` "fails ONLY
> check_action_owner" no longer holds under the shipped rule — see above).

**PROCEED to the merge gate** (not a HALT): clause 5 is satisfied (champion
heldout pass count 1, strictly between 1 and 5; `check_action_owner` is the
discriminating check on `longcall-support-heldout-2`, isolated alone); the
champion (1/6) and Kimi (0/6) do NOT tie on `longcall-*` heldout, so
clause 7's HALT trigger does not fire. The band ranks: it separates the
champion from both a same-tier local model (qwen3:8b, dead on every case
above ~16k chars under its default window — the SAME measurement defect
this lane's own champion-window fix was built to correct, left in place per
the brief's explicit "tiers untouched" instruction) and a larger hosted
model (Kimi, 0/6, tripping both new checks and — independently —
compression). Two honest, non-blocking findings carried into the PR body
rather than smoothed over: (1) a one-off run-to-run non-determinism was
observed on this machine (see above), resolved by treating the actual
`--snapshot` output as canonical and confirming `check` reproduces it
exactly; (2) the window swap costs 3 losses (net -2) on the 22 pre-existing
cases, falsifying the brief's own "no losses" prediction. Champion field
(`gemma4-e4b-ctx16k`) and every `longcall-*` case's `split` remain
PROPOSED — operator signs at merge.

---

## PROVISIONAL — pass 2's re-score of pass 1's recorded outputs (SUPERSEDED by pass 3's live re-run, below)

The section below is generated content — see the header comment in
`docs/probes/transcript-long-2026-09-06/rescore_pass2_provisional.py` for
exactly what it does and does not do. Regenerate with:

```
python3 docs/probes/transcript-long-2026-09-06/rescore_pass2_provisional.py
```

### PROVISIONAL — pass-2 re-score of pass-1's recorded outputs (criterion clause 5, pure, no inference) — SUPERSEDED by pass 3

Generated by `docs/probes/transcript-long-2026-09-06/rescore_pass2_provisional.py`. Applies the SHIPPED, fixed `evals/transcript-en/properties.py` (any-hit-correct `check_action_owner`, self-joining `check_withdrawn_excluded`) via the real `R.run_properties`, to pass 1's recorded `got` output (6 Sep, pre-rebase), resolved by case id into the CURRENT `evals/transcript-en/cases.json` and scored against THAT entry's `input`/`expected` — never the `expected` block embedded in the results files. Champion and hosted rows are NOT same-day with each other's re-run (CLAUDE.md gotcha 14 — a same-day comparison is pass 3's job). Pass 3's live re-run REPLACES this table.

#### gemma4-e4b-ctx16k (champion, PROPOSED)

| id | split | shipped verdict (all checks) | check_action_owner — SHIPPED (any-hit) | check_action_owner — pass-1 ref (every-hit) | flip? |
|---|---|---|---|---|---|
| `discovery-short-train` | train | PASS | PASS | PASS | no |
| `renewal-medium-train` | train | PASS | PASS | PASS | no |
| `support-long-train` | train | FAIL (`check_coverage`) | PASS | PASS | no |
| `quiet-checkin-short-train` | train | FAIL (`check_abstention`) | PASS | PASS | no |
| `pricing-objection-medium-train` | train | PASS | PASS | PASS | no |
| `discovery-long-train` | train | PASS | PASS | PASS | no |
| `renewal-short-train` | train | PASS | PASS | PASS | no |
| `support-medium-train` | train | FAIL (`check_coverage`) | PASS | PASS | no |
| `quiet-checkin-medium-train` | train | FAIL (`check_abstention`) | PASS | PASS | no |
| `discovery-heldout-easy` | heldout | PASS | PASS | PASS | no |
| `discovery-heldout-hard` | heldout | FAIL (`check_coverage`) | PASS | PASS | no |
| `discovery-heldout-long` | heldout | FAIL (`check_coverage, check_grounded`) | PASS | PASS | no |
| `renewal-heldout-medium` | heldout | FAIL (`check_coverage`) | PASS | PASS | no |
| `renewal-heldout-digits` | heldout | FAIL (`check_coverage`) | PASS | PASS | no |
| `renewal-heldout-short` | heldout | PASS | PASS | PASS | no |
| `support-heldout-short` | heldout | PASS | PASS | PASS | no |
| `support-heldout-long` | heldout | FAIL (`check_coverage`) | PASS | PASS | no |
| `pricing-objection-heldout-medium` | heldout | PASS | PASS | PASS | no |
| `pricing-objection-heldout-short` | heldout | PASS | PASS | PASS | no |
| `quiet-checkin-heldout-short` | heldout | PASS | PASS | PASS | no |
| `quiet-checkin-heldout-medium` | heldout | FAIL (`check_abstention`) | PASS | PASS | no |
| `mixed-heldout-dense` | heldout | PASS | PASS | PASS | no |
| `longcall-quiet-train-1` | train | PASS | PASS | PASS | no |
| `longcall-discovery-train-1` | train | FAIL (`check_action_items, check_coverage`) | PASS | FAIL | **YES** |
| `longcall-renewal-train-1` | train | FAIL (`check_coverage`) | PASS | PASS | no |
| `longcall-support-train-1` | train | PASS | PASS | FAIL | **YES** |
| `longcall-pricing-heldout-1` | heldout | FAIL (`check_action_items`) | PASS | PASS | no |
| `longcall-scoping-heldout-1` | heldout | FAIL (`check_coverage, check_grounded`) | PASS | PASS | no |
| `longcall-discovery-heldout-2` | heldout | PASS | PASS | PASS | no |
| `longcall-renewal-heldout-2` | heldout | FAIL (`check_action_owner, check_grounded`) | FAIL | FAIL | no |
| `longcall-support-heldout-2` | heldout | PASS | PASS | FAIL | **YES** |
| `longcall-mixed-heldout-3` | heldout | FAIL (`check_action_items, check_action_owner`) | FAIL | FAIL | no |

**gemma4-e4b-ctx16k (champion, PROPOSED): 3 flip(s)** FAIL-to-PASS on `check_action_owner` solely from the any-hit-correct semantic change (0 dead run(s) excluded from this count); `check_action_owner` FAILS under the SHIPPED rule on **2 of 32** scoreable case(s).

#### qwen3:8b

| id | split | shipped verdict (all checks) | check_action_owner — SHIPPED (any-hit) | check_action_owner — pass-1 ref (every-hit) | flip? |
|---|---|---|---|---|---|
| `longcall-quiet-train-1` | train | PASS | PASS | PASS | no |
| `longcall-discovery-train-1` | train | dead run | dead run | dead run | n/a (excluded) |
| `longcall-renewal-train-1` | train | dead run | dead run | dead run | n/a (excluded) |
| `longcall-support-train-1` | train | FAIL (`check_action_items, check_output_shape`) | PASS | PASS | no |
| `longcall-pricing-heldout-1` | heldout | dead run | dead run | dead run | n/a (excluded) |
| `longcall-scoping-heldout-1` | heldout | dead run | dead run | dead run | n/a (excluded) |
| `longcall-discovery-heldout-2` | heldout | dead run | dead run | dead run | n/a (excluded) |
| `longcall-renewal-heldout-2` | heldout | dead run | dead run | dead run | n/a (excluded) |
| `longcall-support-heldout-2` | heldout | dead run | dead run | dead run | n/a (excluded) |
| `longcall-mixed-heldout-3` | heldout | dead run | dead run | dead run | n/a (excluded) |

**qwen3:8b: 0 flip(s)** FAIL-to-PASS on `check_action_owner` solely from the any-hit-correct semantic change (8 dead run(s) excluded from this count); `check_action_owner` FAILS under the SHIPPED rule on **0 of 2** scoreable case(s).

#### moonshotai/kimi-k3 (pinned)

| id | split | shipped verdict (all checks) | check_action_owner — SHIPPED (any-hit) | check_action_owner — pass-1 ref (every-hit) | flip? |
|---|---|---|---|---|---|
| `longcall-quiet-train-1` | train | PASS | PASS | PASS | no |
| `longcall-discovery-train-1` | train | FAIL (`check_compression, check_coverage`) | PASS | PASS | no |
| `longcall-renewal-train-1` | train | FAIL (`check_compression`) | PASS | PASS | no |
| `longcall-support-train-1` | train | PASS | PASS | FAIL | **YES** |
| `longcall-pricing-heldout-1` | heldout | FAIL (`check_withdrawn_excluded`) | PASS | PASS | no |
| `longcall-scoping-heldout-1` | heldout | FAIL (`check_coverage`) | PASS | PASS | no |
| `longcall-discovery-heldout-2` | heldout | FAIL (`check_action_items`) | PASS | PASS | no |
| `longcall-renewal-heldout-2` | heldout | FAIL (`check_action_items, check_action_owner`) | FAIL | FAIL | no |
| `longcall-support-heldout-2` | heldout | FAIL (`check_action_owner`) | FAIL | FAIL | no |
| `longcall-mixed-heldout-3` | heldout | FAIL (`check_action_items, check_action_owner`) | FAIL | FAIL | no |

**moonshotai/kimi-k3 (pinned): 1 flip(s)** FAIL-to-PASS on `check_action_owner` solely from the any-hit-correct semantic change (0 dead run(s) excluded from this count); `check_action_owner` FAILS under the SHIPPED rule on **3 of 10** scoreable case(s).

**Total across all 3 models: 4 flip(s); check_action_owner fails the SHIPPED rule on 5 of 44 scoreable recorded case(s) (8 dead run(s) excluded).**

---

## Pass 3 (8 Sep 2026) — live re-run, CURRENT — supersedes every table above

Everything above this line is pass 1/pass 2 record-keeping, kept for the
paper trail and explicitly marked SUPERSEDED or PROVISIONAL-replaced. This
section is the current, load-bearing answer: a real `--snapshot`/`check`
re-run on the corrected `cases.json` (the three operator-signed corrections
below) and the fixed `_leading_owner_token` parser (`evals/transcript-en/properties.py`,
commit `83f47d2`), plus same-day hosted rows for the `longcall-*` band.
**DO NOT run any model to reproduce this section** — it is assembled from
the committed run artifacts named throughout.

### The three operator-signed heldout corrections (signed 8 Sep, BEFORE this pass's numbers were read)

Pass 2's `check_action_owner` fix (any-hit-correct) and pass 3's parser
tolerance fix (`_leading_owner_token`, whole-word/clause/parenthetical
resolution) exposed three `commit_owner` entries in `cases.json` that were
authored under the wrong reading of the transcript — not scorer bugs, spec
bugs in the answer key itself. All three are `git diff cfde8e4 21f4fc1 --
evals/transcript-en/cases.json` (verified: this is the ENTIRE diff to that
file for pass 3 — no other line changed):

1. **`longcall-renewal-heldout-2`** — `commit_owner["confirm the seat
   count"]`: `"rep"` -> `"customer"`. Transcript line (verified against the
   committed `input`): *"CUSTOMER: On a separate note, could you confirm
   the seat count with HR one more time before we finalise the MSA
   numbers?"* — the customer, not the rep, raises and owns this follow-up
   (the rep's reply is "I'll double check with your HR contact," a
   different, rep-owned commitment already covered by a separate key).
2. **`longcall-support-heldout-2`** — `must_commit` entry `"follow up"` ->
   `"report scope"`, and `commit_owner["follow up"]` -> `commit_owner["report
   scope"]` = `"customer"` (unchanged owner, renamed key). Transcript:
   *"CUSTOMER: I'll also follow up internally with our data team about
   whether we can trim the report scope as a workaround..."* and, separately,
   *"REP: I'll get the escalation ticket, the SLA document and the usage
   report sent today, and follow up once engineering confirms a fix
   window."* — both speakers legitimately say "follow up" about different
   things; the original key collided across both correct, independent
   commitments. Renaming the customer-owned key to `"report scope"` (a
   substring that appears only in the customer's line) makes the two
   commitments distinguishable again, restoring the check's ability to
   isolate the customer side without touching the rep's genuinely separate
   "follow up" commitment.
3. **`longcall-mixed-heldout-3`** — `commit_owner["confirm the final start
   date"]`: `"rep"` -> `"customer"`. Transcript line (verified): *"CUSTOMER:
   I'll confirm the final start date for the new project team with our PMO
   by next week."* — the customer, not the rep, owns confirming the date.

Each correction is a one-key edit to an existing `commit_owner` value (or,
for case 2, a key rename with the value unchanged); no `must_commit`/
`must_not_commit`/`speakers`/input text was touched beyond the one renamed
key in case 2. **Heldout is untouchable beyond these three** — no
expectation was edited after this pass's `check`/hosted numbers were read;
the corrections were signed first, the runs came after.

### (2) Parser fixtures — RED demos, real `run_properties`, pasted from `evals/test_transcript_en.py`

`python3 -u evals/test_transcript_en.py` (full run: `./.cline/test.sh` — 35
files, 1119 assertions, all green). The three fixtures for clause (2),
verbatim:

```
test_2n_parenthetical_owner_resolves
  [PASS] parenthetical fixture: 'Customer (Emeka) to ...' resolves to customer and PASSES (shipped rule, real run_properties)
  [PASS] RED: identical fixture, pass-2's set-equality parser swapped in: FAILS check_action_owner ('customer (emeka)' != 'customer')

test_2o_clause_prefixed_owner_resolves
  [PASS] clause-prefixed fixture: 'After confirming budget with finance, Sana will ...' resolves to rep and PASSES (shipped rule, real run_properties)
  [PASS] RED: identical fixture, pass-2's set-equality parser swapped in: FAILS check_action_owner (the whole clause != 'sana')

test_2q_fixture_c_wrong_build_twin_still_fails
  [PASS] longcall-discovery-train-1: fails ONLY check_action_owner
```

`test_2n`/`test_2o` each assert two things through the real
`run_properties`: the shipped pass-3 parser resolves the fixture correctly
(PASS), and swapping pass-2's set-equality parser back in on the identical
fixture makes it FAIL (RED) — the fixture only exists because it exercises
a real change in behavior. `test_2q` re-runs fixture C (`test_2j`'s
anywhere-substring wrong-build twin: `"Rep to loop in the finance lead
Renata once the customer signs off on the plan"` — a genuinely
rep-mis-owned item that also mentions "customer" later in the sentence)
against the shipped code and confirms it **still FAILs check_action_owner
alone** — the tolerance fix (parenthetical stripping, clause-prefix
matching) did not widen the leading-segment read far enough to swallow a
later mention past the first delimiter. `_leading_owner_token` slices on
the first of `" to "` / `" will "` / `":"` and never looks past that point
(`evals/transcript-en/properties.py:300-332`).

**Naming note, and the real-recorded case behind the parenthetical shape.**
`test_2n`'s fixture uses `"Customer (Emeka) to ..."` (Emeka is
`longcall-discovery-train-1`'s own declared customer — fixtures run
against a committed case's real `speakers` block, and that train case is
the one this file's isolation fixtures are built on throughout). It is
NOT literally the `"Customer (Callan) to ..."` shape named in the build
criterion — but that shape is not hypothetical either: it is `longcall-
renewal-heldout-2`'s own real pass-1 recorded Kimi output (Callan is that
case's declared customer), preserved verbatim in
`docs/probes/transcript-long-2026-09-06/results/kimi-k3-longcall-pass1-2026-09-06.json`
(`"Customer (Callan) to get budget sign-off / final go-ahead from the
regional director by the fifteenth"`) — the exact recorded output that
made pass 2's set-equality parser silently read the attribution as
unrecognised (`check_action_owner: 'budget sign-off' expected owner
'customer', got leading token 'customer (callan)'`, same file). **Ad-hoc
direct verification, not gated evidence** (CLAUDE.md gotcha 5 — this is a
hand-run `python3 -c` calling `check_action_owner` directly, not a
committed test through `run_properties`; the gated, re-run-on-every-CI
evidence for this parser behavior is `test_2n`/`test_2o`/`test_2q` above,
which cover the same two shapes on committed fixtures). Re-run directly
against this head's shipped code, on the real recorded item:

```
>>> P.check_action_owner(input_text, {"action_items": [
        "Customer (Callan) to get budget sign-off / final go-ahead from the regional director by the fifteenth",
        ... (the other 4 real recorded items) ...
    ], ...})
    ok=True, msg=""
```

The parenthetical shape named in the criterion is resolved on the actual
real-recorded output it came from, not only on a synthetic fixture that
happens to share its shape.

### (4) Snapshot + check, this head

`evals/transcript-en/snapshot.json` was written by `run transcript-en
--snapshot` on `21f4fc1` (rule A): **3 fresh Ollama loads** (7 Sep 23:43 ->
8 Sep 00:23), runtime `{"name": "ollama", "version": "0.33.2"}` as stamped
by the rule-A writer at run time — re-checked live in this pass
(`curl http://localhost:11434/api/version` -> `{"version":"0.33.2"}`,
metadata only, no inference): the runtime is still 0.33.2 today, 8 Sep,
consistent with (though not proof of identity with) the stamped value —
**0/32 cases unstable** (every case agreed across all 3 loads),
`train_score=0.5385` (7/13), `heldout_score=0.5263` (10/19). Verified
directly from the committed JSON (`evals/transcript-en/snapshot.json`:
`loads: 3`, `cases`: 32 entries, 0 with `stable: false`).

**The `--snapshot` run's own console output was not captured** — the
builder session that produced it (`wf_98de11d8-714`, per the pass-3
commit message) was sleep-killed mid-lane; only the resulting
`evals/transcript-en/snapshot.json` and the per-load result files
(`docs/probes/transcript-long-2026-09-06/results/transcript-en__ollama__gemma4-e4b-ctx16k__load{1,2,3}.json`)
survive. Named plainly rather than left implicit: criterion clause (4)
asks for both the `--snapshot` output and a subsequent `check` output
pasted; only the second exists as a pasted console log. The snapshot's own
evidence is the committed JSON's `loads`/`stable`/`runtime` fields (cited
above) and the per-load result files, not a captured run transcript.

One subsequent `check transcript-en` (8 Sep 09:13-09:26, a 4th fresh load,
independent process) reproduced it exactly
(`docs/probes/transcript-long-2026-09-06/logs/pass3-check.log`):

```
ok: heldout 0.5263 vs snapshot 0.5263 (32 stable, 0 unstable exempt)
```

Per-case, from that same `check` log, the `longcall-*` heldout rows (6
cases):

| id | chars | verdict | failed checks |
|---|---|---|---|
| `longcall-pricing-heldout-1` | 16,002 | FAIL | `check_action_items` (missing: sign-off) |
| `longcall-scoping-heldout-1` | 19,529 | FAIL | `check_coverage` (omitted: eight locations); `check_grounded` (ungrounded: 10, 2, 8) |
| `longcall-discovery-heldout-2` | 21,555 | **PASS** | — |
| `longcall-renewal-heldout-2` | 25,377 | FAIL | `check_grounded` (ungrounded: 15) |
| `longcall-support-heldout-2` | 32,739 | **PASS** | — |
| `longcall-mixed-heldout-3` | 20,034 | FAIL | `check_action_items` (missing: confirm the exact new headcount) |

**Champion `longcall-*` heldout: 2/6.** `check_action_owner` fires on **no**
case for **any** of the three models measured this pass (champion, Kimi,
GLM).

**Is the check live or just neutered? The arithmetic, not just the
assertion.** 9 of the 10 committed `longcall-*` cases carry a
`commit_owner` block (36 keys total, `longcall-quiet-train-1` has none —
verified against the committed `cases.json`). Of those 36 keys, per model
this pass, the number that got at least one real substring hit in the
model's own `action_items` (i.e. `check_action_owner` actually evaluated an
attribution, not a vacuous zero-hits pass) — computed directly against the
committed results JSON via the real `_leading_owner_token`/
`_owner_side_tokens_present` code path: **champion 33/36, Kimi-K3 32/36,
GLM 19/36** (GLM lower because 3 of its 9 relevant cases are dead/
unparseable runs with no `action_items` to check at all). **84 of 108
model x key combinations across the three models were genuinely evaluated,
and 0 failed.** That is the mechanism firing and passing, not the
mechanism sitting inert — the three signed corrections fixed the answer
key on exactly the keys that were previously wrong, and `test_2q` (above)
is the standing proof that the pass-3 tolerance fix did not also widen the
leading-segment read far enough to let a genuinely mis-attributed item
through. Pass 2's own PROVISIONAL table (above) found the pre-correction
rule failing 5 of 44 scoreable cases — this pass's zero is the corrected
answer key plus the corrected parser converging, not a check that stopped
looking.

### (5) 22 pre-existing cases: byte-identical to master's, AND identical verdicts — both verified programmatically

Two separate checks, not one:

**Case text/expected, byte-identical.** Diffed `evals/transcript-en/cases.json`
(this head) against `git show master:evals/transcript-en/cases.json`,
restricted to the 22 non-`longcall-*` case ids, comparing each case's full
JSON object (`json.dumps(..., sort_keys=True)` equality, not just the
verdict it produces): **0 of the 22 differ** — every field (`input`,
`expected`, everything) is identical to master's. This is the direct
evidence clause (5) asks for (case *text*, not case *verdict*); the earlier
draft of this section cited only the verdict diff below, which is a
different, weaker claim (a case's text could change while its verdict
happens not to) — corrected here to cite the actual byte-identity check.

**Verdicts, also identical.** Diffed `evals/transcript-en/snapshot.json`
(this head, dated `2026-09-08T00:23:57`) against `git show
master:evals/transcript-en/snapshot.json` (dated `2026-09-07T12:43:40`,
same runtime `ollama 0.33.2`), restricted to the same 22 ids, comparing
`passed` AND `failed_checks` per case:

- **0 flips** — every one of the 22 pre-existing cases has the identical
  verdict (and, where failing, the identical failed-check set) on both
  snapshots.
- **Heldout: 8/13 on master, 8/13 on this head** — identical.

(Scripts used, inline, not committed separately — trivial dict comparisons
over the committed JSON files; re-run the byte-identity check: load both
`cases.json` files, filter `cases` to ids not starting `longcall-`, compare
`json.dumps(case, sort_keys=True)` per id; re-run the verdict check the
same way against both `snapshot.json` files, comparing `(passed,
failed_checks)`.)

This settles the non-determinism this branch's pass-1 section (above)
flagged as unresolved: under rule A (3 fresh loads, per-case `stable`,
pinned runtime), the champion's pre-existing 22-case behavior is now
byte-for-byte reproducible against master, one day apart, same runtime
version. The earlier "net -2 on the 22 pre-existing cases" finding (pass
1's single-load, pre-rule-A comparison) does not reproduce and is
superseded by this measurement.

### (6) Same-day `longcall-*` scorecard — champion vs Kimi (pinned) vs GLM (pinned), 8 Sep 2026

All three runs same-day (champion snapshot loads 7 Sep 23:43 - 8 Sep 00:23;
Kimi 8 Sep 09:26; GLM 8 Sep 09:32 — CLAUDE.md gotcha 14 satisfied). Kimi and
GLM scoped to the 10 `longcall-*` cases only, via the same scratch-copy
technique as pass 1
(`docs/probes/transcript-long-2026-09-06/{kimi,glm}_scratch_run.sh`),
through the real `sandbox/runner.py run` entry point. Raw results:
`docs/probes/transcript-long-2026-09-06/results/{kimi-k3,glm-5.3}-longcall-2026-09-08.json`.

All 10 committed `longcall-*` cases (4 train, 6 heldout):

| id | split | chars | champion (`gemma4-e4b-ctx16k`) | Kimi-K3 (pinned) | GLM-5.3 (pinned) |
|---|---|---|---|---|---|
| `longcall-quiet-train-1` | train | 12,433 | **PASS** | **PASS** | **PASS** |
| `longcall-discovery-train-1` | train | 15,331 | FAIL (`check_action_items`: missing confirm a time; `check_coverage`: missing Renata) | FAIL (`check_coverage`: missing Renata) | FAIL (`check_compression`: 917 vs 766 limit; `check_coverage`: missing Renata) |
| `longcall-renewal-train-1` | train | 16,990 | FAIL (`check_coverage`: missing 49) | **PASS** | FAIL (`check_action_items`: missing updated MSA) |
| `longcall-support-train-1` | train | 14,466 | **PASS** | FAIL (`check_compression`: 790 vs 723 limit) | FAIL (`check_compression`: 904 vs 723 limit) |
| `longcall-pricing-heldout-1` | heldout | 16,002 | FAIL (`check_action_items`: missing sign-off) | FAIL (`check_action_items`: missing sign-off) | FAIL (`termination`: no_answer, finish_reason=length, 0 content) |
| `longcall-scoping-heldout-1` | heldout | 19,529 | FAIL (`check_coverage`, `check_grounded`) | FAIL (`check_coverage`: missing eight locations) | FAIL (`termination`: no_answer, finish_reason=length, 0 content) |
| `longcall-discovery-heldout-2` | heldout | 21,555 | **PASS** | **PASS** | **PASS** |
| `longcall-renewal-heldout-2` | heldout | 25,377 | FAIL (`check_grounded`) | FAIL (`check_action_items`: missing budget sign-off) | FAIL (`check_action_items`: missing updated MSA) |
| `longcall-support-heldout-2` | heldout | 32,739 | **PASS** | **PASS** | FAIL (`error`: unparseable output — no JSON object found) |
| `longcall-mixed-heldout-3` | heldout | 20,034 | FAIL (`check_action_items`) | FAIL (`check_action_items`: missing 2 items) | FAIL (`check_action_items`: missing 3 items) |

**Heldout pass counts: champion 2/6, Kimi-K3 (pinned) 2/6, GLM-5.3 (pinned)
1/6. Train pass counts: champion 2/4 (`longcall-quiet-train-1`,
`longcall-support-train-1`), Kimi-K3 2/4 (`longcall-quiet-train-1`,
`longcall-renewal-train-1`), GLM-5.3 1/4 (the quiet case only).** Cross-check
on the champion's train count: the snapshot's `train_score=0.5385` over 13
train cases is 7/13; the 9 pre-existing train cases score 5/9 on the same
`check` log (`discovery-short-train`, `renewal-medium-train`,
`pricing-objection-medium-train`, `discovery-long-train`,
`renewal-short-train` PASS) — 5 + 2 = 7, consistent with 2/4 on the
`longcall-*` train cases (an earlier draft of this table wrongly carried
pass-1's stale "1/4" champion train figure forward; corrected here against
`pass3-check.log` directly).

**`check_action_owner` fires on zero cases for any of the three models this
pass** (champion, Kimi, GLM) — the three corrected `commit_owner` entries
now score as intended under the fixed parser, and no live case isolates
`check_action_owner` alone any more. GLM's headline problems across the
band are `check_action_items` (missing commitments), two dead heldout runs
(`termination`: `finish_reason=length`, 0 content — the same
window-truncation failure mode CLAUDE.md gotcha 16 documents, here on the
*hosted* side despite GLM's own advertised window, not a local `num_ctx`
issue), and one unparseable-output `error` on `longcall-support-heldout-2`
(verified from the committed results JSON: `"error": "no JSON object found
in model output: ..."`, `content_chars` truncated by the same 32,739-char
input the champion and Kimi both handle correctly) — not an attribution
miss.

**Wall time per call** (`metrics_totals.wall_ms` / call count, from the
committed results JSON — no per-case timing is recorded, only the
aggregate):

| model | scope | wall_ms total | calls | wall/call |
|---|---|---|---|---|
| champion (`gemma4-e4b-ctx16k`) | full 32-case exam, avg of 3 snapshot loads | 800,377.8 (avg) | 32 | ~25.0s |
| Kimi-K3 (pinned) | 10-case `longcall-*` band only | 329,554.9 | 10 | ~33.0s |
| GLM-5.3 (pinned) | 10-case `longcall-*` band only (2 dead runs, 2 retries) | 228,116.0 | 10 | ~22.8s |

### HALT-and-report (clause 6)

**Champion (2/6) and Kimi-K3 pinned (2/6) TIE on `longcall-*` heldout.**
Per the build criterion's own rule ("If the champion and both hosted rows
tie on longcall-* heldout verdicts, the PR body says HALT-and-report"),
this pass reports rather than recommending a merge-gate verdict. The tie is
exact at the per-case level, not just the count: both PASS
`longcall-discovery-heldout-2` and `longcall-support-heldout-2` and FAIL
the other four (Kimi's specific failed checks differ from the champion's on
3 of those 4, but the pass/fail split is identical). GLM (1/6) sits below
both, losing `longcall-support-heldout-2` to an unparseable-output `error`
(not an attribution miss — `check_action_owner` fires on none of the three
models' runs this pass) where champion and Kimi both produced parseable,
correctly-attributed output — GLM is not the tiebreaker either way. No heldout expectation is edited after these
numbers were read (the three corrections above were signed before this
run). Champion field (`agents/transcript-en/agent.yaml` ->
`gemma4-e4b-ctx16k`) and every `longcall-*` case's `split` remain
**PROPOSED** — the operator signs at merge, and this HALT-and-report is
handed to that decision, not a recommendation to proceed.
