# Build ledger

> One entry per `single-lane-build` lane, written by the main loop at merge time.
> **Purpose:** capture what the FIRST draft got wrong and whether the reviewers called it
> right — the thing the structured build report and `check-all` both hide. The lane's
> ~500k subagent tokens of discarded attempts are otherwise unreadable.
>
> **Why this file exists (operator asked 2026-07-22):** "every first build fails review"
> looked like a pattern, but the evidence is small and confounded. This is the log that
> will eventually say whether it is signal or noise. Do NOT generalize from it yet — see
> the honest-count column. Append-only; never rewrite a past entry, correct in a new one.
>
> **Later consumer:** E6 (reasoning library, `experiments.md`) can read this once there
> are enough entries. Manual for now — automating a lessons-miner on n<10 would be the
> same premature-build reflex this session has been correcting.

## Columns each entry should answer

- **first-draft defect** — what the coder got wrong before review (not the final state).
- **who caught it** — a reviewer, a refuter, or the main loop's own verification.
- **refuter accuracy** — did the adversarial pass call it right? over-claim? miss it?
- **cost** — subagent tokens, wall-clock, round-trips.
- **transferable lesson** — what a future brief should say to prevent it. Promote the
  durable ones into `CLAUDE.md` "Gotchas".

---

## Running tally (update at each entry — this is the "signal or noise" counter)

| metric | count |
|---|---|
| lanes merged | 22 |
| lanes whose FIRST draft passed all refuters clean | **1 (entry 028, reasoning_effort)** — previously 0; E12 v2 was the first to return `ready-for-merge-gate`, but as a v2 |
| lanes that needed a round-trip | 7 (F1/F2; **PR #18 THREE**; **E10 PR #20 → #22**; **E12 PR #24 → #25**; **transcript-en PR #50 → #51**; **CRM-realism PR #58 → #59**; **MULTITURN PR #64 — passes 1→2→3 + main-loop merge-gate fixes**) |
| refutations issued | ~40 |
| refutations that were RIGHT in conclusion | ~26 (entry 023 adds 5 refuters on one shared cause, all right — plus a 6th, scope-adherence, right; acted on in entry 024; entry 029 adds 9 right across two passes, incl. one empirical injection refuting a guard; entry 030 adds 1, correctly narrow) |
| refutations right in observation but WRONG/OVERSTATED in conclusion | 6 (PR #19 test-honesty) |
| lanes merged against a `round-trip` recommendation on verified evidence | 8 (E10 v2, E9; entry 029 — both pass-2 defects fixed and witnessed by the main loop before merge; entry 030 — PR-body-only defect, fixed by the main loop, no rebuild) |
| **lanes halted by the criterion PRE-review, before any build** | **19 — entry 023 ×2, entry 029 ×4, entry 030 ×3, entry 031 ×10 (v1→v12; reviewer-authored text passed every review, fresh-drafted text blocked ~every time → reviewer-authors-first)** |
| **lanes whose defect was in the SPEC, not the build** | **1 (entry 023, all three passes)** |

Reading so far (n=2, one harness — NOT a general claim): the deterministic gate
(`check-all`) has been green on every first draft, and the adversarial reviewers have
found a real defect in every first draft. The gate catches regressions; it does not catch
a new check wrong in the same direction as the code. Also: refuters over-claim about as
often as they land, so a refutation is a lead, not a verdict.

---

## Entry 031 — MULTITURN-EXAM: ten criterion blocks, three build passes, one cross-pass diagnosis, and the instrument grew a new dimension (PR #64, MERGED `087963e`, 2026-09-02)

**What shipped:** turns-aware multi-turn scoring for trajectory exams — a case may carry
`turns`; each turn runs an independent tool loop over FULL-history context, is scored
against its own expected block, and the case passes iff all turns pass. Structurally:
`score_case()` is now the SINGLE verdict chokepoint (the old outer `score_trajectory`
call and the D2 termination-override were deleted from `attempt()` and relocated — one
scoring path, grep-witnessed). Per-turn metrics land in the committed snapshot
(prompt_tokens = first call of the turn; dead turns carry an honest incomplete marker,
never a fabricated 0). 4 new multi-turn cases (32 total; split PROPOSED, operator
ratifies): cross-turn grounding, mid-thread switch, outage-then-retry (max_steps=6
multi-turn depth), long-thread recap. Champion (2B) fails all 4 — real headroom.
First chained result, computable from the committed file alone: **full-history context
grows ~+1,690 prompt tokens per fat turn** (+70 for a light turn) — E27's scoped-assembly
A/B and context-growth pricing now have their substrate and baseline.

**The story — the criterion gate ate TEN blocks (v1→v12) before the build could live:**
3 on 31 Aug (sum-vs-loop budget; satisfiable-by-existing-case; declared-files fence),
then 7 across 1-2 Sep: verdict-only diff blind to record widening (v5); the outer-scorer
overwrite path un-gated (v6); the D2 second assignment my clause missed (v8-block — both
blockers in MAIN-LOOP-authored text); an unscoped quantifier that would kill a correct
build (v9); brief-only gates for critical fixes (v10); P1 unencoded + a carve-out whose
stated cause our own diagnosis had falsified (v11); a witness test that could not be red
because the bug was a blanket false-FAIL (v12 — reason-level red instead). Every block
verified real. **The split is now data: reviewer-authored criterion text passed or drew
advisories every time; freshly-drafted text (operator sprint drafts + main-loop
additions) blocked ~every time. Criterion authoring is the pipeline's highest-defect
artifact — adopt reviewer-authors-first.**

**Build passes:** pass 1 landed the structural refactor and honestly marked itself
INCOMPLETE (turn-budget death). Pass 2 completed R1-R8; refuters then REPRODUCED a real
instrument bug: per-turn `tool_calls` zipped against ACCUMULATED `tool_results` made
error_recovery blanket-false-FAIL every turn after the first — on the lane's own outage
showcase case. The pass-3 circuit breaker forced a CROSS-PASS DIAGNOSIS that named the
shared root cause: producer-side shape changes without auditing pre-existing consumers
(P1+P2 mechanically identical; P3 the same pattern at the evidence layer). Pass 3 ran a
consumer audit, fixed P1 with dual reds (verdict-level + failure-identity), restored the
dedupe test to exact-shape kind-aware assertions, and refreshed stale probe evidence.

**Who caught what:** criterion reviewers 10/10 real; correctness refuter reproduced the
zip bug from scratch; test-honesty refuter proved the step-counter red DECORATIVE by
injection (slack `max_steps: 4` budget hid the leak — gotcha 2 inside the witness file
itself); scope refuter found one inert 5-line aggregate (gotcha 1) after proving two
other suspects load-bearing by reversion. Main loop fixed both merge-gate findings
on-branch with the refuters' exact injections as reds (fixture tightened to
`max_steps: 2` → the same injection now fails turn 1 loud; inert field deleted), reran
the paired double snapshot (0 flips, 0 field-diffs among the 28, 0 verdict movement —
fixes proven scoring-inert), merged. Merge API returned a spurious race error after
creating the merge commit; PR closed manually with the explanation.

**Cost:** ~4.3M subagent tokens (3 build passes + 8 criterion reviews + diagnosis),
~2,000 tool calls, spread over 1-2 Sep. Zero hosted spend.

**Transferable lessons:** (1) reviewer-authors-first for criteria — the 10-block split
is the strongest process datum this repo has. (2) A shape change to a shared structure
requires a CONSUMER AUDIT (grep-driven, table pasted) — three defects, one cause.
(3) A witness test is only a witness if its fixture is TIGHT: slack budgets hide leaks;
verify red-capability against the named injection class, not just any injection.
(4) When a bug is a blanket false-FAIL, a verdict-level red is impossible for the
still-failing scenario — assert on failure identity. (5) The pass>=3 diagnosis breaker
earned its keep: it converted pass-bouncing into a named root cause.

## Entry 030 — PROVIDER-PIN-KNOB: the code survived every refuter; the PR body's arithmetic did not (PR #63, MERGED `27c5e67`, 2026-09-01)

**What:** third sibling knob `provider_routing` (opaque routing-payload dict) through
`ChatCompletionsAdapter`/`get_adapter` (router.py) and `adapter_for` (runner.py), mirroring
json_mode/reasoning_effort — added only when set, raw-read (no bool coercion), zero
validation of contents, explicit `{}` documented-and-tested as OFF. +6 isolated checks in
`sandbox/test_router_knobs.py` (gate 805 → 811), each RED-demoed by a named injection with
a one-entry FAILED list. OpenRouter `provider` schema (order/allow_fallbacks) fetched live
on build day and cited by URL. Diff confined to the 3 declared files; zero model calls.
Rung 1 of the day-level-drift answer; the pinned-vs-unpinned probe stays operator-gated.

**Lane history:** THREE criterion pre-review halts before this pass (2026-08-31 sprint,
all spec defects, zero build tokens: adapter_for/get_adapter conflation; failed_checks
demanded in a lane that grades no eval case; the DO-NOT-validate rule enforced by no
numbered item). Fired fresh from the v4 kit (`docs/provider-pin-lane-resume-2026-09-01.md`);
v4 criterion reviewed sound — 2 advisories only (terminology rule not restated as a
checkable item; three ±1 line-number citations).

**First-draft defect (the only one):** PR-body count decomposition under criterion 7 —
"21→27 `check(` call-sites" counted the `def check(` line (true call-sites 20→26), and
"31 = 25 static − 1 + 6" used master's runtime count as the branch's static count
(25−1+6=30 ≠ 31; truth: 26−1+6). The CODE survived everything: all six isolation
injections, both RED demos, byte-identity, gate runs, and diff confinement were
independently reproduced by the refuters and again by the main loop.

**Who caught it:** python-reviewer (major) and the test-honesty refuter (refuted, high),
independently, same defect. **Refuter accuracy:** 5 lenses, 1 refutation, right in
observation AND conclusion, correctly narrow ("mechanism sound, body arithmetic wrong").
Main loop reproduced the counts, fixed the body via `gh api -X PATCH` (the `gh pr edit`
no-op gotcha), reran the gate on the branch (25 files / 811, green), merged under the
standing delegation against a round-trip on verified evidence — no rebuild needed.

**Cost:** 9 agents, ~624k subagent tokens, 317 tool calls, ~45 min wall.

**Transferable lessons:** (1) `grep -c "check("` counts the definition line — call-site
counts must exclude `def`; two counts on different grep bases in one sentence must name
their bases. (2) The criterion-halt pattern held: 3 pre-review halts on first-draft
criteria, then the reviewer-authored v4 passed sound first try — same shape as entry 029.
Criterion authoring, not building, remains the pipeline's highest-defect artifact.

## Entry 029 — CRM-realism: four criterion halts, one class rule, and a guard refuted by injection (PR #58 → #59, MERGED `9480d1c`, 2026-08-31)

**What:** production-sized tool envelopes on crm-followup (`crm_lookup`/`deals_list`
4.27–4.50 KB/company, facts byte-identical to slim, hashlib-deterministic) + 4 new
heavy-band cases (silent scope-drop / protocol-break isolators, one at `max_steps=6` —
**the loop-detect un-park trigger is now armed**) + the operator's digit-token-uniqueness
CLASS RULE as a committed test (no normalized ≥3-digit token in two companies' payloads,
token grammar imported from the runner) + a needle collision guard with positive AND
negative controls over the five-company payload domain. Snapshot drop owned in advance
and landed: slim heldout 0.786 → repaired fat exam **0.5 heldout / 0.4167 train**
(28 cases; two back-to-back runs verdict-identical, 0/28 flips). All 4 new cases FAIL
for the champion — a red-capable band, not decoration. Gate: 25 files / 805 checks.

**The story:** pass 1 (PR #58) built the whole apparatus and was REFUTED on reproduced
defects (postal-code '9000' grounding a cross-company needle; 'Jan'⊂'Janssens' vacuous
coverage; fat corpus waving a fabricated '4871 EUR' through grounded_answer; a committed
citation to a nonexistent file; self-contradicting not_verified prose). The criterion
pre-review then halted pass 2 FOUR times, each halt catching a NEW instance of one root
cause — shared digit-runs weakening the anti-fabrication check. Operator decision at
parking: replace field enumeration with the class rule. Pass 2 (fresh invocation, PR #59,
branch `crm-realism-lane-pass2`) implemented items 7–14 with all red demos reproduced;
two defects remained at review: (a) the builder's turn budget died mid-snapshot-rerun —
self-reported `success_criterion_met=false`, clean handoff; (b) the test-honesty refuter
REFUTED the uniqueness guard **by injection**: the scored-fact exclusion was one GLOBAL
set, so a peeters filler equal to Mertens's un-needled scored date passed both guards
with 0 failures. Main loop finished the lane: per-owner exclusion + a directed
cross-company scored-fact check (red-demoed with the refuter's exact injection — exactly
ONE failing check), snapshot rerun ×2, merged under the operator's same-day authorization
("merge when necessary"); new-case split merged as PROPOSED under that authorization.

**Refuter accuracy:** pass-2's five refutations shared one cause (stale snapshot) and all
were right; the test-honesty injection was a model refutation — a live witness against a
guard the builder believed complete, exactly gotcha-2 executed by the harness itself.

**Transferable:** (1) when halts keep finding the same defect CLASS, stop enumerating and
write the class rule (now standing memory). (2) An exclusion "as a class" in a uniqueness
guard is an OWNER-SCOPED question — a global exclusion set silently exempts every other
company; pair per-owner exclusion with a directed cross-set check. (3) Budget the
snapshot rerun (~10 min ×2 at fat payloads) into the build turn — a builder that dies
mid-snapshot but self-reports false and hands off cleanly costs the main loop 30 minutes,
not a pass.

**Cost:** pass 1 ≈ 0.92M + pass 2 ≈ 0.91M subagent tokens, 4 criterion halts (~100k each,
prior session), ~40 min main-loop finish incl. two local snapshot runs.

## Entry 028 — reasoning_effort knob: the first FIRST draft to survive every refuter (PR #57, MERGED `f3f2067`, 2026-08-31)

**What:** `reasoning_effort` passthrough on the router, mirroring `json_mode` exactly —
constructor param (default None), `body["reasoning_effort"] = <value>` added only when
truthy (the top-level openai-dialect key step-0 measured HONOURED: GLM 1002→155, Kimi
682→150 completion tokens at effort-low), `adapter_for` reads it from agent config, +6
guards in `test_router_knobs.py` incl. a full-body byte-identity check against a literal
of master's body. Every committed agent leaves it off → default request byte-identical →
no snapshot rerun needed, and that claim is asserted by a test, not prose. Gate: 24 files
/ 780 assertions. Unblocks the $3 three-arm A/B (unset/low/high, GLM+Kimi — spend still
operator-gated).

**The story:** pass 1, zero round-trips — 2 reviewers pass, 4 refuter lenses
(correctness / regression / test-honesty / scope-adherence) all SURVIVES at high
confidence, each independently REPRODUCING the red demos rather than trusting the pasted
transcripts. First lane in the ledger whose first draft cleared the full round (E12 v2
returned ready-for-merge-gate, but as a v2). The only findings were two stale COUNTS in
the PR prose (an isolation-demo total and the master assertion baseline) — corrected in a
merge-gate note appended to the PR body, not silently.

**Near-false-refutation, caught by the refuter itself (gotcha-11 in action):** the
regression refuter's first gate run FAILED deterministically on exactly the two new
checks — root cause was a stale gitignored `sandbox/__pycache__/router.cpython-310.pyc`
in the REUSED worktree whose embedded mtime collided with router.py's checkout mtime, so
CPython served stale bytecode. Cleared, reran twice, green 780/780. **Transferable: a
reused lane worktree can serve stale .pyc at matching mtimes — clear `__pycache__` before
trusting a red gate in a reused worktree.**

**Criterion-review note:** the pre-review returned sound=true with 5 advisories (one
genuinely useful: a refuter reading `git log --stat` instead of `git diff master...branch`
could false-flag the guard-(e) hand-inject-and-revert — the 08-02 false-refutation shape).
The same gate had earlier halted the CRM lane's criterion with 3 BLOCKING letter-traps —
two lanes through the gate today, one halt, one clean: the gate discriminates.

**Cost:** 9 agents ≈ 0.52M subagent tokens; $0 inference (zero model calls in-lane, by
operator constraint — the gate is deterministic).

## Entry 027 — OpenRouter provider: 3 code lines, and the refuter refuted the WARRANT, not the code (PR #56, MERGED `d81ba09`, 2026-08-29)

**What:** `openrouter` PROVIDERS entry + response-dialect hardening in `router.py`, so exams
can run against hosted models (GLM/Kimi/DeepSeek/large open-weight/frontier) with one key.
Final surface: choices-less error envelope → attributed `TerminationError` (was: uncatchable
KeyError killing the whole run — pre-existing on master, reachable on every provider);
message-absent-in-choice hardened (labeled UNDOCUMENTED-defensive); reasoning extraction
reads both `reasoning` and `reasoning_content` dialects, first-non-empty, ollama-byte-identical
(pinned); partial-content-plus-error declared as a tripwired scoring gap ("TODAY (not
endorsed)" — a scoring decision the operator owns). Gate: 24 files / 774 assertions.
10 mutation kills, incl. the F-revert whose evidence is the escaping-KeyError traceback itself.
First merge under the 28 Aug standing delegation (review round clean → merged by main loop).

**The story:** pass-1 refuter returned REFUTED (high confidence) with the code fully
SURVIVING — every finding was about the *warrant*: the builder's headline "real bug" cited a
doc sentence that actually describes a different, documented envelope (which remained an open
run-killer), the docs-derived mechanism claim was false, and a stated precedence invariant was
violated by its own falsy-`or`. Round-trip fixed the real hole, requalified every comment to
its measured strength (one warrant deliberately labeled "inference, not pinned"), and pinned
current behavior in both directions. The builder also caught its own overclaim ("the gate says
no consumer enumerates details" — the gate said no such thing) and fixed it by adding a
real-`run_exam` end-to-end witness rather than softening the sentence.

**Transferable lesson (third instance this week — now a pattern):** on small surgical lanes
the refuters keep finding FALSE WARRANTS, not broken code — comments and PR claims justifying
correct code with wrong reasons, in files where prose is a code path. Review prose against
primary sources with the same rigor as diffs. Corollary confirmed again: read RAW docs
(`.md` URLs), never a fetch paraphrase — one paraphrase invented a response-side field.

**Caveats shipped with the lane:** OpenRouter routes per-call to varying backends —
openrouter runs are probe-grade, never gate-grade (snapshots stay ollama); `--snapshot`
non-enforcement for hosted providers is documented, not coded (follow-up); `tier:` in
agent.yaml remains INERT (scout finding, operator policy call before any hosted key is used).

**Cost:** 1 builder (2 passes) + 1 refuter + 1 research scout ≈ 0.52M subagent tokens; $0
inference (no key exists; everything fixture-driven, the slate priced from the free catalog).

## Entry 026 — termination detection: the instrument was passing zero-answer runs (PR #54, MERGED `68dd06a`, 2026-08-27)

**What:** fail-loud termination detection, reshaped during scoping from "runtime guard with an
on/off A/B" to unconditional INSTRUMENT HARDENING. The scoping scout's headline: a committed
**heldout** case scored GREEN on a run that emitted **zero answer characters** — `router.py`'s
`reasoning` fallback substituted the model's thinking text and `extract_json` lifted a drafted
object out of it. The build then found exposure was **11× the estimate**: 11/17 reply-draft ×
qwen3:4b cases return zero answer chars, **10 scored green**. After the fix that model reads
train 0.71→0.00, heldout 0.60→0.10 — **a drop, and the correct direction**. Shipped: typed
`TerminationError` (fallback deleted), `finish_reason` captured as cause attribution,
timeouts fail the CASE not the run, a distinct `termination` bucket (runner-emitted only),
snapshot-outage guard on `run`/`run-all` (a timeout storm could write a 0.0 snapshot that
makes every later check trivially green), judges/live boundaries mirrored. Gate after: 23
files / 698 assertions. **All six champions reproduce their snapshots per-case — verified
three times independently** (builder, correctness refuter across three scoring modes, and
main loop). Brief: `docs/termination-detect-lane-brief-2026-08-27.md`.

**Build method:** scout-drafted brief (Opus) with main-loop decisions + one main-loop review
catch (a D2/D5 self-contradiction on trajectory attribution — the ledger-023 defect class,
caught pre-build this time); Opus builder, 2 passes; 2 Opus refuters, **both SURVIVES at high
confidence** — the cleanest review record of the week's three lanes. 23 mutations all killed,
matrix independently reproduced. The builder reported **4 defects in the brief** rather than
improvising (incl. a false "zero snapshots carry an error check" claim), and 2 false rationale
comments were fixed after the refuter disproved them by probe.

**Incident, disclosed:** the snapshot-guard mutation test did exactly what the guard prevents —
overwrote `evals/reply-draft/snapshot.json` in the builder's worktree. Caught via `git status`,
restored from the committed blob, test now self-restores in a `finally`; main-loop verified the
file byte-clean against origin. The hazard is reproduced-real, not theoretical.

**Transferable lessons:** (1) the vacuous-green class hides in FALLBACKS, not just checks — a
convenience substitution ("use the thinking text") is a placeholder in disguise, and it survived
21 prior lanes. (2) Comments defending a correct decision with a false mechanism are a defect in
a score-defining file — two were shipped, disproved by probe, and rewritten to the measured
rationale. (3) Ollama is not bit-reproducible across runs at temp 0 for borderline cases
(`quote-request` flipped modes between runs) — before/after claims must come from the lane's own
paired runs, never a recorded baseline.

**Cost:** 1 scout (2 passes) + 1 builder (2 passes) + 2 refuters ≈ 1.19M subagent tokens; zero
frontier inference (all measurement local).

## Entry 025 — gate-0 exposure: the smoke is real, and the spec broke twice more (PR #53, MERGED `2a86adf`, 2026-08-26)

**What:** unblocked gate 0 per the exposure finding's option (a). Six committed `crm-followup`
cases with inputs taken VERBATIM from a bait probe (champion repeats an identical tool call
under two families — outage+retry-permission and stale-data-refresh — 3/3 reproducible at
temp 0, each with a near-identical passing sibling); plus `--dedupe-tools`, the runtime half of
the redundancy monitor (default OFF, serve-cached on duplicate non-raising calls). Snapshot
rerun in the same merge: crm train 1.0→0.8, heldout 0.9091→0.7857 — the four exposure cases
landing RED at baseline, by design. Gate after: 22 files / 582 check() assertions.

**Build method:** the workflow engine launch was permission-blocked, so the lane ran as direct
agent dispatch with the same structure — Opus builder in an isolated worktree, 4 fresh-context
reviewers (3 refuter lenses + python), a pass-2 re-verify pair, three passes total. Operator
directive held throughout: Fable authored only the brief, amendment, and dispatches; all code,
review, and inference ran on Opus/Sonnet + local ollama.

**The story:** pass 1 — three refuters REFUTED with reproduced evidence and python BLOCKED,
converging from different angles on the step-refund mechanism (unbounded under alternating
keys: 7 real calls vs an advertised ceiling of 5; its own test survived deletion of the branch)
and on error-caching silently killing `error_recovery`'s spiralled clause. **Both root causes
were the BRIEF's D2** — "don't count the step" and unqualified caching — extending entry 023's
spec-not-build pattern to a fourth and fifth instance. Amendment 1 (`21efaec`): a suppressed
duplicate charges its step; a raising execution is never cached. Pass 2 — correctness refuter
returned SURVIVES with flag-off behavior identical to master on 30/30 scenarios compared on
full trace values; test-honesty refuted once more, narrowly: an orthogonal mutation-killing
assertion had been deleted with the dead refund test, leaving two cache mutants alive. Pass 3
killed them, made `steps` identical ON/OFF for the same script, and fenced the two remaining
survivors. Final matrix: every required mutant red, independently reproduced; one survivor by
design (a semantics-preserving refactor no behavioral test can distinguish).

**Honest scope of the A/B this enables:** the moving set is the TWO stale-refresh cases —
outage-retry repeats involve a raise, are never deduped (so `error_recovery` stays fireable),
and stay RED on both sides. Effect size must be reported with exposure counts (amended rule in
`docs/gate0-exposure-finding-2026-08-26.md`).

**Transferable lessons:** (1) mutation testing was the workhorse of both review rounds — the
assertion-count floor was structurally blind here because the count went UP while coverage was
lost. (2) When deleting a dead test, audit each assertion for intent orthogonal to the dead
premise before it goes. (3) Two subagents independently hit "green-looking tool that did
nothing" (`gh pr edit --body-file` silently no-ops on this repo — use
`gh api -X PATCH repos/…/pulls/N`; a mutation harness whose anchor regex over-matched) —
presence-is-not-effect applies to tooling, not just code under test.

**Cost:** 1 bait probe + 1 builder (3 passes) + 6 reviewer/refuter agents ≈ 1.26M subagent
tokens, zero frontier tokens on inference (all measurement on local ollama).

## Entry 024 — transcript-en test cleanup: acting on the scope refuter (PR #52, MERGED `a64e7db`, 2026-08-26)

**What:** deletion-only follow-up to entry 023 — removed the two over-built tests the
scope-adherence refuter flagged on PR #51. `test_13` asserted on the **source text** of
`properties.py` (`"raise KeyError" in src`) where `test_12` already proves the same
fail-loud contract behaviourally through `run_properties` on a hand-built attack input;
`test_10` enforced a repo-wide ">=2 must_mention anchors" policy no brief asked for.
30 lines deleted, nothing added. Gate after: **21 files / 535 check() assertions**
(floors 20/505 clear), re-verified green on master post-merge.

**Build method:** main-loop inline (no harness pass, no reviewers) — a deletion whose
justification was already adversarially reviewed in the prior lane. Cost: minutes.

**Signal:** the refuter's finding sat "right, not yet acted on" in the 26 Aug LATE STATE
block for less than a day. Closing a confirmed refutation is cheap when done adjacent to
the lane that produced it; the expensive version is rediscovering it cold later.

## Entry 023 — transcript-en exam: three passes, three defective SPECS, zero defective builds (PR #51, MERGED `c442483`, 2026-08-26; PR #50 closed as superseded)

**Lane:** sprint queue item 1 — a new English business call-transcript summarisation exam, the
pilot-shaped demo (`recap` is 17/17 Dutch; 0 of 86 cases were English business content).
Method: `single-lane-build`, `buildModel: sonnet`, full tier, `blastRadius: claim`, closed
7-file `declaredFiles`. Brief: `docs/transcript-en-brief.md`.

**What shipped:** `evals/transcript-en/` + `agents/transcript-en/` + `evals/test_transcript_en.py`
+ one row in `sandbox/taxonomy.py`. **22 cases (9 train / 13 heldout), train 0.667, heldout
0.6154** — inside the band pre-registered in the success criterion, with 5 heldout failures all
in the `quality` bucket (`check_coverage` ×4, `check_abstention` ×1). Sixth agent in the suite.

**first-draft defect:** `./.cline/test.sh` red on the branch (2 of 21) while green on master —
`test_router_knobs.py` (a committed `agent.yaml` set `timeout_s`) and `test_taxonomy.py`
(`check_action_items` had no `CATEGORY_BY_CHECK` row). **who caught it:** all five refuter
lenses, on one shared cause, each reproducing it live rather than reading the PR body.

**⚠️ The defect was in the BRIEF, not the build** — it demanded a green gate AND forbade the
`sandbox/` edit that green requires. The builder detected the contradiction, refused to touch
`sandbox/`, and reported it as a finding, exactly as instructed. Its own cross-pass summary is
the entry's headline: *"Three passes, three defective specifications, zero defective builds. No
single pass could see this because each one only receives its own brief."*

The three spec failures, all main-loop authored:
1. **Pass 1 criterion — not runnable at all.** It said `check transcript-en --timeout 900`;
   `--timeout` exists on `run`/`diff` only (`runner.py:1577-1584`, deliberate). The criterion
   pre-review halted the lane in ~4 min / 80k tokens, **before any build agent spawned**. Root
   cause: memory [[model-size-is-not-the-lever]] said "`--timeout 900` is load-bearing" without
   naming the subcommand; it was learned during a **sweep**. Memory corrected at merge time.
2. **Pass 2 criterion — under-fenced.** It barred `test_router_knobs.py` from the diff by name
   but not `test_taxonomy.py`, leaving a hole where loosening the very guard the pass exists to
   satisfy would still pass the criterion's letter. Also "run from the repo root" is ambiguous
   for a lane running in a worktree — the exact ambiguity that gave pass 1's reviewers phantom
   failures. Halted again pre-build, ~8 min / 97k tokens.
3. **Pass 3 brief — self-contradictory.** It said both "do NOT push to `feat/transcript-en-exam`"
   and "update PR #50 on the same branch". The builder resolved it explicitly (new branch off the
   same tip → PR #51, cross-linked on #50) instead of guessing, and disclosed it.

**🔥 The keeper, and it is a REVERSAL:** the brief made `timeout_s: 900` mandatory on the
assumption that ~8k-char inputs would blow the 120 s default. The lane's own calibration probe
**measured 26.9 / 26.8 / 32.2 s** at 1.4k / 3.8k / 8.0k chars, and the builder wrote that
measurement into the file it was told to create — disproving the instruction that created it.
Pass 3 removed the field. `recap` corroborates: 7597-char inputs, same champion, no `timeout_s`,
green at the default. **A mandatory instruction was refuted by the measurement it required.**

**Also earned its place:** the probe-before-writing-cases step (E20 step-0a's shape). It found
the champion's summary length is a **near-flat 400–530 char floor regardless of input length**,
which made a first-pass tiered percentage ratio arithmetically unreachable on short inputs —
caught and fixed by a uniform rule *before* any heldout inference ran (`ccea0c3` precedes
`12a4708`). Guessing `recap`'s `max_ratio: 0.22` would have shipped a broken bar.

**Refuter accuracy:** 3 of 4 failed to refute at pass 3 (correctness + regression at HIGH
confidence, both re-running the full 22-case live check and matching the snapshot case-for-case,
ruling out a compensating swap). The one refutation — scope-adherence, medium — is **right**:
`test_13` asserts on the SOURCE TEXT of `properties.py` where `test_12` already proves the same
guarantee behaviourally (the [[next-build-replay-exam-from-real-pr-history]] anti-pattern, 45% of
mast's tests), and `test_10` invents an unasked repo-wide case-authoring policy. **Not fixed —
open cleanup**, both deletions, neither affects a score.

**Declared gap, disclosed by the builder rather than found:** `check_compression` fired on **0 of
13** heldout cases, so its limits were never exercised by a live model failure. A deterministic
guard does exist (`test_2e_isolation_check_compression`, real `run_properties` path) but drives a
hand-built **output** against a committed input. Recorded in `cases.json`'s `not_verified`.

**Cost:** 3 launches — 2 pre-build criterion halts (~180k tokens, no worktree, no PR) + 1 full
lane (886k) + 1 round-trip (708k). **The two halts were the cheap ones**: S-101's criterion
pre-review paid for itself twice over by killing an unrunnable criterion before ~48 min of build.

---

## Entry 022 — create-task shape: the oracle rewrites the headcount (PR #47, MERGED `ee97133`, 2026-08-15)

**Lane:** Road B steps 1–4 (operator-authorized same day, "new-module harness first" over
the thin 13-task exam). Teach `sandbox/replay/` the task shape that dominates the hard
band — PRs that CREATE a module — and re-run admissibility + oracle over the whole
≥80-line band. **Zero model calls; the lane stops where a local model would start.**
Method: inline main-loop build in a worktree, deterministic tests extended (+28 checks,
floor 477 → 505), python-reviewer + verify-gate fresh-context round.

**What shipped:** `admit.py` classifies modify/create/mixed (`--diff-filter=A`); a create
red must be a collection error NAMING a module the PR adds, boundary-anchored.
`attempt.py` speaks `### FILE:` whole-file blocks; write locations are triple-gated
(parse whitelist, task-record iteration, structural containment). `oracle.py create`
grades the human's merged files through the identical path. Probe doc:
`docs/e-corpus-create-2026-08-15.md`; artifacts under `docs/e-corpus-results/`.

**The story — the oracle demoted the headline number.** 89 hard-band candidates → 22
admissible {10 modify, 12 create}, 50 mixed, 17 invalid red. Then the oracle: **12/12
create GREEN, 3/10 modify GREEN → the real gradeable pool is 15.** The 2026-08-14 "13
admissible, clears the bar by one" was an *admissibility* count that had never been
oracle-checked end-to-end: 3 of the 13 were mixed-shaped (admissible on paper,
unbuildable in practice — `build_tasks.py` would have crashed on their added file), and 7
more fail the documented #1005 function-splice limitation. Also corrected: "84% of the
band is new-module" was a misread — the dominant shape is **mixed** (50), which needs a
third task shape before it counts.

**Adversarial inputs earned their keep three times:** (1) the sibling-prefix module-name
attack, hand-built, seen RED against a substring match *before* the sweep trusted the
check — sweep killed and rerun on the fix; (2) verify-gate mutation-tested the boundary
regex and the parse whitelist — both suites flip RED on the mutants; (3) the review round
found the parser truncating a file at its own inner ```` ```python ```` docstring fence —
a loss that would read as model incapacity — seen RED, fixed, oracle re-run 12/12.
One reviewer false alarm: the "dirty worktree" it blocked on was the *other* reviewer's
mutation test caught mid-flight (both agents ran concurrently on the same worktree);
tree verified clean against HEAD before push. Lesson: worktree-isolate mutation-testing
reviewers from each other, not just from the build.

**Next (parked, each needs its own go):** local Qwen ladder over the 15 tasks
(`MAX_TOKENS` scaled per task from `merged_chars`, identical across models); the 50-task
mixed shape; the Scaleway key for the frontier half.

## Entry 021 — replay selection committed, and the fail-loud fix that fired on run one (PR #46, MERGED `9e673ff`, 2026-08-15)

**Lane:** preservation, operator-authorized 15 Aug. Commit `build_candidates.py` +
`band_filter.py` into `sandbox/replay/` — the first two funnel steps of the 2026-08-14
corpus sweep, until now parked in the disposable `$REPLAY_WORK`, leaving the sweep
unreproducible from a clean clone (the gap `docs/e-corpus-sweep-2026-08-14.md` names).
Method: inline main-loop build in a worktree + two fresh-context reviewers
(python-reviewer, verify-gate), delegated build-method authority.

**Falsifier for the lane, run before review:** the committed scripts must regenerate the
committed sweep artifacts from their new location. They did — **byte-identical** to
`docs/e-corpus-results/candidates_2026-08-14_{full,behaviour}.json` (1,150 → 261 → 125).
verify-gate then reproduced independently from a **genuinely fresh clone**: also
byte-identical. Survives, high confidence.

**The story — the review's HIGH finding proved itself on the very next run.**
python-reviewer flagged that the original `git()` swallowed failures into `''`: a failing
git call silently drops a PR from the funnel uncounted, or misfiles it as `lines=0`.
Hardened to fail loud, the first rerun aborted on a merge commit absent from the frozen
clone — and the counted-skip fix (`merge_not_in_clone`) then showed **2**: two PRs merged
upstream since the 14-Aug clone were being dropped invisibly, *including by the original
sweep run*. Reference artifacts unaffected (those commits were never in the clone), but
the funnel's "1,150 merged PRs" headline silently contained two unexaminable rows nothing
counted. Same shape as ledger 018's oracle lesson: the instrument's blind spot was on the
failure path, exactly where the green byte-identical check cannot see.

**Also disclosed rather than fixed:** the merged-PR list is a live `gh` query, not pinned
— byte-identical reproduction of a past sweep holds only until upstream drifts past the
clone (docstring + README). Skipped deliberately: shared-helper refactor of the
duplicated clone-check/banding (kept the diff minimal, matches file-local style).
Gate green at final commit (20 test files / 477 checks).

## Entry 020 — guards, cases and a settled hardware question (PR #41–#43 MERGED, #44 open, 2026-08-05)

**Lane:** none — main loop, one research subagent (CAPITU), one advisor pass. Tally NOT
incremented; no `single-lane-build` ran. Same caveat as 018/019.

**Shipped.** #41 `_exp` fail-loud guard · #42 replay behaviour filter · #43 crm partial-failure
cases (heldout 1.00 → 0.909) · #44 `error_recovery` false-positive fix (open).

**🔥 The through-line: three vacuous-green holes, same shape, found in one day.**
1. `evals/recap/properties.py` `_exp` returned `{}` for an unmatched input → **all four checks
   passed at once**. An unrecognised case scored full marks.
2. `sandbox/replay/admit.py` accepted PRs whose gating test asserts on **source text**. Both
   kinds reproduce red→green identically, so the criterion could not see the difference —
   and **a third or more of `mast`'s tests are that kind** (measured: 180/505 files).
3. `sandbox/runner.py` `error_recovery` — the inverse: it **failed honest answers**. A
   one-letter typo in a real name scored as fabrication; an honest ack outside a fixed
   vocabulary scored as no ack.

(1) and (2) pass while measuring nothing. (3) punishes a correct model. **All three were found
by hand-building the input and running the real scoring path — seconds, no inference.**

**first-draft defect (mine, four):**
1. **A PR body claimed "the diff is the submodule SHA only"** — it carried 8 unpushed docs
   commits. Caught by `gh pr diff --name-only`, *after* writing the claim.
2. **`| tail -2 && echo "body updated"` reported success for a `gh pr edit` that FAILED** —
   the `&&` read `tail`'s status. Gotcha 7, committed by the session that had just re-read it.
3. **`.cline/test.sh`'s file floor claimed to notice a vanished test.** It noticed only a NET
   decrease; delete one test, add a stub, count holds. Fixed with an assertion floor.
4. **A crm case failed for the wrong reason and I predicted the wrong cause.** I hypothesised
   that pre-announcing the outage let the model skip the lookup, rephrased, and **the rephrase
   changed nothing.** Only then did I read the trace.

**who caught it:** the advisor for 3 (plus the `.claude/worktrees` sweep); my own verification
for 1, 2 and 4. No reviewer, no refuter — no lane.

**⚠️ THE NEAR-MISS WORTH THE WHOLE ENTRY.** The first crm run reported **exactly the number the
lane wanted** — heldout 1.00 → 0.909 — while a case was failing for an entirely unrelated
reason (`tools_called`, not fabrication; the rung was never exercised). *The score moved in the
intended direction, which is what made it look like it worked.* Reading only the headline would
have shipped it. This is ledger 006–008's shape recurring, and the countermeasure that worked
was mechanical: check `failed_checks` has exactly ONE entry naming the intended check.

**🔥 Findings, each with evidence:**
- **Model size is not the lever.** Three models, two families, 3.4× range — all **7/10 heldout**
  on recap. The 8B/14B pair is controlled. Failure modes differ (8B: 1 compression / 6 coverage;
  14B: 5/5), which is E25's brief-or-complete trade-off made visible *across* models rather than
  within one. **A hardware purchase would have bought nothing.**
  ⛔ Nearly ruined by the router's 120 s default: the first run completed zero cases, and its
  timeouts would have read as capability failures. Killed and rerun with `--timeout 900` rather
  than interpreted — ledger 018's "one number merging two opposite causes", caught this time.
- **Permission to guess suppresses tool use.** Controlled contrast, phrasing the only variable:
  *"your best estimate is fine"* → the champion skips `crm_lookup` entirely and answers honestly
  that it lacks the name. Not fabrication. **Designed as an `error_recovery` bait and
  RECLASSIFIED rather than tuned** — the case now measures what it found, and `error_recovery`
  was removed from its `expected` because that rung cannot fire when the tool is never called.
- **CAPITU is Apache-2.0**, ships no copyrighted literary text, and 51 of 59 instruction types
  are language-neutral. ⚠️ The arXiv page's "CC BY 4.0" is the *paper's* licence — grepping the
  paper returns the wrong answer.
- **`test_ratchet.sh` is ~98% blind here** (7 `assert` lines vs 421 `check()` calls). Filed
  upstream as roger3000-dev S-111. *Presence is not effect, inside the tool bought to catch it.*

**Transferable lessons:**
- **A branch cut from an unpushed local `master` carries every unpushed commit into its PR.**
  Describe scope from `gh pr diff --name-only`, never from what you meant to commit. And the
  part the operator needs: **merging such a PR publishes those commits anyway** — merging is not
  a way to defer that decision, it *is* the decision.
- **A count floor catches only a NET decrease.** Delete a real test, add a stub, and it holds.
  Floor the assertions too.
- **When a fix does not work, stop predicting and read the trace.** Two of the four defects above
  were mis-explained before being understood; the second explanation was only right because I
  stopped guessing.
- **Relaxing an ABSENCE check is the dangerous direction** (#44). More than half that PR's test
  file is regression guards, and the demo that mattered was: reverting the fix leaves **every
  guard green** and fails only the three fix-assertions — which is what proves the guards pin
  invariants rather than the fix.
- **State an accepted cost as an assertion, not a docstring.** #44 knowingly lets an invented
  name one edit from a grounded one pass; there is a test saying so, and that test is where a
  future lane flips the decision.

**refuter accuracy:** n/a — none spawned. The advisor was right on both blocking calls and both
were reproduced before acting.

**⛔ E20 step 0a ran the same day and KILLED the lane — the cheapest outcome of the session.**
9 model calls, zero repo code, under an hour, against a pre-registered criterion. 3 cases × 3
turns with accumulating constraints: **zero drift, 3/3 held everything at turn 3, and the
champion got BETTER across turns** — each further instruction acted as a correction. Multi-IF's
degradation (`o1-preview` 0.877 → 0.707) **does not reproduce here.**

🔥 **And the probe printed "BUILD", wrongly, for two independent reasons:** it counted words on
the ```` ```json {"reply": ...} ```` wrapper rather than the extracted reply (adding ~2 words,
pushing one turn from 39 to 41 across the 40-word limit and inventing the entire drift finding),
and it counted "never satisfied" as "dropped" when drift requires satisfied-THEN-violated.
Either alone would have authorised a lane the evidence does not support.

**That is the entry's second lesson and it generalises past this repo: a falsifier can itself be
wrong in the direction its author was hoping for.** Step 0a is only cheap if the step-0a *code*
gets the same scepticism as the thing it tests — here, the same A4 rule (measure the answer, not
the envelope) that the repo already had written down.

**A third false-green from my own `echo`, same day, same shape.** `git push origin master` was
run while on a feature branch, so it pushed an unchanged master; the `echo pushed` that followed
was mine and meaningless, and the E20 brief sat on a local branch for hours believed shipped.
Caught only by `git ls-tree origin/master`. **Verify against the remote, not against your own
output** — that is now three instances today (`&&` after `tail`, `gh pr edit`, this).

**Cost:** one research subagent (~72k tokens), two advisor calls (one unavailable), ~50 min local
inference across 7 exam runs + the step-0a probe, one 9.3 GB model download. No lanes.

---

## Entry 019 — harness pin 7ab1339 + the cline test gate (PR #39 + #40, both MERGED, 2026-08-05)

**Lane:** none — main loop, no `single-lane-build`, no subagents, one advisor pass. Operator
authorized two steps ("oke go ahead"), then the push + merges. ⚠️ **The running tally is NOT
incremented** — no lane ran, so this is not evidence about "first builds fail review" in either
direction. Same caveat as 018.

**What shipped.** #39: harness `212aed9 → 7ab1339` (+14). #40: `.cline/test.sh`, the
deterministic gate `cship` resolves against. Neither touches a scoring path — no `sandbox/`,
`evals/`, `agents/` or `agent.yaml` file, so **no committed score moved** and `check-all` was
not re-run.

**Why #40 existed at all.** `cship` resolves fail-closed
(`$CLINE_TEST_CMD > ./.cline/test.sh > detect(pytest|npm test|make test)`) and this repo has no
`pyproject.toml` / `pytest.ini` / `tests/` / npm `test` / Makefile target — so detect found
nothing and **every cline lane aborted before running**. The near-miss it also closes: adding a
`pyproject.toml` would make cship auto-detect `pytest -q`, and pytest is the wrong runner here —
all 16 test files are module-level scripts ending in `sys.exit(1)`, and
`sandbox/test_router_knobs.py` has zero `def test_`, so pytest collects nothing from it and
reports success.

**first-draft defect (mine, five, none reached a merged artifact uncorrected):**
1. **The PR body claimed "the diff is the submodule SHA only."** It carried 8 unpushed docs
   commits, because the branch was cut from a local `master` 8 ahead of `origin/master`. Caught
   by running `gh pr diff --name-only` — *after* writing the claim, not before.
2. **`... | tail -2 && echo "body updated"` reported success for a `gh pr edit` that FAILED.**
   The `&&` read `tail`'s status. This is the `$?`-clobbering gotcha, fifth documented variant,
   committed by the session that had just re-read it. (`gh pr edit` is broken by the
   projects-classic GraphQL deprecation; `gh api -X PATCH` works.)
3. **`.cline/test.sh`'s file floor was claimed to "notice a test file disappearing." It did
   not** — only a NET decrease. Delete one real test, add a no-op placeholder, count stays 16.
4. **`find .` did not exclude `.claude/`**, where `.claude/worktrees/` holds full repo copies
   during a `single-lane-build` — the gate would have run another branch's tests and reported
   them as this branch's, with the inflated count also masking a deletion.
5. **Told the operator `CLINE_VERIFY_MODEL` was unset and blocking.** It is defaulted at
   `lane.sh:11`; `:=` sets a shell variable without exporting, so a subshell cannot see it.

**who caught it:** the advisor for #3 and #4; my own verification for #1, #2 and #5. **No
reviewer or refuter ran — there was no lane.**

**refuter accuracy:** n/a — none spawned. The advisor was right on both of its blocking calls
and both were reproduced before acting (#3 via RED 3, #4 by inspecting `.claude/`).

**Verification bar actually met.** #40 was demonstrated RED three times before being trusted
green — A2's rule: baseline `rc=0` (16 files / 421 assertions); RED 1 injected failing file →
`rc=1`, named; RED 2 `MIN_TEST_FILES=17` → `rc=2`; **RED 3** deleted `test_taxonomy.py` (51
checks) and added a placeholder → files stayed **16**, checks fell **421 → 370**, `rc=2`. RED 3
is what produced the second floor. #39 verified at the new pin rather than from the handoff:
drift `rc=0` clean, `single-lane-build.test.js` **169 passed** (136 at the old pin),
`repoInvariants` confirmed **absent** at `212aed9` and present at `7ab1339`. And cship's real
predicate `[ -x ./.cline/test.sh ]` was tested directly (A4) — it selects from the repo root and
**does not resolve from a subdirectory**.

**🔥 Transferable finding — `test_ratchet.sh` is ~98% blind in this repo.** The harness's new
assertion ratchet hardcodes `ASSERT_RE='\bassert\b|\bexpect\(|\bassert\.'` with no override
hook, and our tests use a custom `check(label, cond)` helper: **7 matching lines against 421
`check()` calls.** It printed `✓ both ratchets hold` because it can barely see anything. A
**seventh** instance of *presence is not effect*, and the sharpest yet — it is inside the tool
bought to catch exactly this. Worth a harness stub for a configurable `ASSERT_RE`;
`.cline/test.sh`'s `MIN_CHECKS` is the local substitute.

**Transferable lessons:**
- **A branch cut from an unpushed local `master` carries every unpushed commit into its PR.**
  Describe a PR's scope from `gh pr diff --name-only`, never from what you intended to commit.
  Corollary the operator needs stated: **merging such a PR publishes those commits anyway** —
  merging is not a way to defer that decision, it *is* the decision.
- **A count floor only catches a NET decrease.** The placeholder swap (delete a real test, add
  a stub) is the modal cheap-model failure and defeats it. Floor the assertions too.
- **`gh pr edit` currently fails** on this repo (projects-classic deprecation). Use
  `gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -F body=@file` and **verify by grepping the
  live body**, not by an exit code.
- A doc's own staleness warning does not keep it fresh: CLAUDE.md's test-file gotcha said
  "three files in `evals/`" and "the glob finds 9"; re-measured it is **four** and **12**. Its
  fifth staleness (11 → 14 → 15 → 16 → this).

**Cost:** no subagents, no lanes. One advisor pass, ~35 tool calls, no inference runs.

---

## Entry 018 — E-CORPUS replay probe (**PR #38 OPEN, NOT MERGED**, 2026-08-01)

**Lane:** none — main-loop probe, no `single-lane-build`, no subagents. Operator authorized the
falsifier only ("bora?"), then authorized preserving the harness via PR. Write-up
`docs/e-corpus-probe-2026-08-01.md`; raw results `docs/e-corpus-results/`.
⚠️ **Entered at merge time by convention, but nothing is merged** — #38 awaits the operator.
Update the tally when it lands, not now.

**What it did:** replayed real merged `mast` PRs — rewind to the base commit, model attempts
the change, grade with **the CI test that actually gated that PR**. Judge-free, ground truth
free.

**first-draft defect (mine, three of them, all caught before they reached the operator as fact):**
1. **Claimed "substantive, not vacuous" from reading the diff** — which distinguishes *changed*
   from *unchanged*, not *reasoned* from *transcribed*. A direct check showed the test file
   hands over the fix's exact tokens (`is_primary_in_cluster`, `db.rollback()`). Caught by the
   advisor, not by me.
2. **Wrote "#1008 is a harness artifact for BOTH models" before rerunning.** At 3.5× the output
   budget `gemma4` passes it (so its zero *was* mine) while `qwen3` still emits zero answer
   characters (so its zero was *not*). **One budget had merged two opposite causes.**
3. **Asserted `agent-sandbox` is a public repo.** `gh repo view` → `private=true`. Inferred
   from CLAUDE.md wording that described portfolio *intent*.

**who caught it:** the advisor for #1 and for auditing the load-bearing #1043 assertion; my own
rerun for #2; one `gh` call for #3. **No reviewer or refuter ran — there was no lane.** That is
the honest weakness of this entry: three self-caught defects is not the same evidence as three
refuter-caught ones, and the "first builds fail review" tally must not count it either way.

**refuter accuracy:** n/a — none spawned.

**cost:** ~4 h wall-clock, ~10k model tokens for the probe itself (3,375 tok/task × 3), plus
reruns. Cheap. The expensive part was environment setup (clone + a venv reproducing `mast`'s
CI), not inference.

**transferable lessons — the three worth carrying:**
- ⛔ **ORACLE BEFORE ANY MODEL CALL.** Feed the *human's own merged answer* through the model's
  identical parse→apply→grade path. It fired first run: PR #1005 came back RED (its diff also
  changed module-level constants the task format cannot represent) and was **dropped, not
  debugged**. Without it that zero reads as model incapacity. **A 0/N from a harness that cannot
  splice is indistinguishable from a 0/N from a model that cannot code.** Generalizes past
  replay: it is entry 015's "build the attacker's output by hand" aimed at the *grader* instead
  of the *check*.
- **Stage the grading; never report a bare N/M.** `responded → parsed → compiles → gating test
  → no regression`. Stage 5 caught PR #937 passing its own gate while breaking four other
  tests. Stages 2 vs 4 separated "never produced an answer" from "produced wrong code" — which
  route oppositely (rule A3, no cause from an aggregate).
- **Re-run at a larger budget before attributing any zero.** See defect #2.

**Findings that change future briefs:** the easy band is **ceiling-saturated** (3 models tie at
2/3, a 4B matches an 8B) so E-CORPUS's *"small-to-medium"* wording is wrong — build from the
**long-function** band, inside a window bounded by **termination** not difficulty. And **45% of
`mast`'s unit tests (172/384) assert on source text, not behaviour**, which caps what any replay
exam over this corpus can measure.

**PR #38's own build followed the standing bar:** RED demonstrated on two injected defects
before the new test was trusted green (`attempt.py` restored byte-identical after each), the
harness re-verified through the real entry point from its new location (2/2 ORACLE GREEN), and
the missing-corpus guard shown to exit 1 rather than return an empty result.

---

## Entry 017b — harness hand-back: the step-0b gate, declared per exam (no lane, docs-direct, 2026-07-30)

**Not a build lane** — pointer entry, so the correction is reachable from the canonical
post-mortem trail. Full text: `docs/harness-change-proposals-2026-07-30.md`, hand-back section.

This session's six harness proposals were synthesised with restaurant-brain's into
`roger3000-dev/docs/harness-change-synthesis-2026-07-30.md` (private, not in this snapshot) (`5aa1bba`). Doctrine agreed,
**nothing built.** P1/P2/P4/P5 became harness text; P3 stays repo-owned. Three things came back
to us, and one of them was wrong.

**The reusable finding: the handoff's evidence table was false for three exams, and its own
rule explains why.** It listed `crm-followup` / `email-triage` / `expense-categorization` as
"`cases.json` + `snapshot.json` only". They have `evals/test_e10_ladder.py` (180 ln) and
`evals/test_pr2_hardcases.py` (226 ln) — sitting **directly in `evals/`**, one level above the
per-exam directories, which is the glob trap `CLAUDE.md` already documents. **Second reader
caught by it.** The conclusion survived; the criterion did not. It is not *"does this exam have
a standing test file"* — all five do — but **"does something build a WRONG MODEL OUTPUT and
assert the REAL scoring path rejects it?"** Those two files pin the case set and the mocks,
never an output. A related category error in the same table: `properties.py` credited as a
guard, when it exists exactly for the two `properties`-mode exams — its presence tracks exam
MODE. And `recap`'s coverage was stronger than credited (two files, the second pinning that
every check has an isolating case).

**Deviation from what was asked, recorded deliberately:** the handoff said declare 0b OFF for
`recap` and `reply-draft`. `reply-draft`'s only wrong-output mechanism covers ONE check, so it
is declared **by surface** — OFF for a card touching `check_no_invented_dates`, ON for the rest
of the exam. Needs operator ratification; a narrowing of another session's request should not
be discovered later by a card that gets 0b'd unexpectedly.

**Filed not built:** adversarial fixtures (P3) for the three ❌ exams. `evals/` is PR-gated and
nothing is authorized. **Not claimed: those exams are unsafe. Claimed: nobody has checked** —
though Lane A2 found exactly this hole in `recap` within seconds of looking for it.

---

## Entry 017 — E21 long-input strategy bake-off (PR #34, MERGED `d762519`, 2026-07-30)

**Lane:** inline, main loop. The first experiment in this repo whose subject is **our own
architecture** rather than a vendor's model.

**Result: a NEGATIVE, and it is the deliverable.** Four architectures on the same committed
cases — single-shot 3/7 train, 7/10 heldout, **2/8 long**; filter-then-recap 4/7, 6/10,
**2/8** at 283 calls and 11648 tok/case; chunk-and-reduce 3/7, 6/10, **2/8**;
extract-then-write 3/7, 6/10, **2/8** at 1809 tok/case. **All four pass the same two long
cases and fail the same six.** `filter-then-recap` — the design's favourite, because it
composes two agents we already own — costs 5.5× the tokens and 18× the calls for the same
score.

**What the failure-MODE report bought.** `extract-then-write` shortens output 15–25%, which
flips ONE compression failure to a pass and TWO coverage passes to failures — net zero, and
the compression↔coverage frontier demonstrated on a SINGLE model, so the trade belongs to the
task and not to a model's temperament. And `long-day-heldout-xl` behaved exactly as the brief
warned: `error` under single-shot, `check_compression` under two strategies. **A pass-count
report would have read "strategy fixed the error" when the case merely stopped truncating.**

**⛔ A finding I got wrong the same day, corrected here (the entry's most useful part).** I
wrote that "compression tracks the LIMIT, not the length" and that E13's length effect was
"substantially an artifact of our own ratio schedule". **Both are wrong**, and one table shows
it: the limit is a near-constant ~270-460 chars at EVERY input size (492 ch -> 270; 7597 ch ->
379), because the per-case ratio exists to hold the ABSOLUTE target at one screen. The three
long cases I cited as passing at 867-901 are the Lane A/A2 cases I authored with deliberately
LOOSE ratios to isolate coverage and abstention — **citing them as a discovery was circular.**
The real mechanism SUPPORTS E13: a flat bar, against a model that writes 166-335 chars on short
days and 443-713 on long ones. What E21 legitimately adds is that no architecture fixes it.
**Third self-correction in two days from the same reflex** — see
[[structural-claims-need-one-cheap-query]]; the cross-tab that would have caught it took one
query, and I ran it only when the operator asked me to explain the mechanism in plain terms.

**Superseded claim, kept for the record:**
Cross-tabulating the committed cases: compression passes at limits 867/877/901 and fails at
386/392/429/458 — **perfect separation, and length does not predict it.** The two LONGEST long
cases pass; the shortest fails. The champion writes 166–713 chars across the whole suite and
~345–713 on long days *regardless of input size*, so output grows sub-linearly while we
tightened `max_ratio` AS input grew (0.18 → 0.05). **E13's "clean length effect" is
substantially an artifact of our own ratio schedule** — on the failing cases we ask for ~400
chars and get ~500. Found by one cross-tab, no inference, after the expensive run was done.

**The invariant the whole comparison rests on.** `properties.py` resolves expectations by
EXACT INPUT TEXT, so scoring a strategy against its own transformed day makes `must_mention`,
`max_ratio` and `nothing_important` **all pass vacuously** — every strategy posts a perfect
score while measuring nothing, silently. Strategies therefore only change what the MODEL sees;
scoring always uses the original committed input. `test_bakeoff.py` pins it and **constructs
the mistake deliberately** (`test_2`) so the guard has teeth — the red-then-green discipline
from entry 015, applied at design time instead of after.

**A phrasing correction the operator caught.** I wrote "ship none of these", which implied all
three lost. `extract-then-write` is actually **15% cheaper** than single-shot and ties on the
long band; its only deficit is ONE heldout case — **10% here, inside the noise band E12
refuses to rank on.** So the honest claim is that the instrument **cannot separate them**, and
single-shot wins on incumbency and simplicity, not on measured superiority.

**Cost:** ~2 h of local inference (68 case-runs, then 34 more after adding `out_chars`).
**Instrumentation gap, recorded:** `chunk-and-reduce` and `filter-then-recap` output LENGTHS
were never captured — `out_chars` was added after the four-way run and only the two cheap
strategies were re-run. Their pass/fail is unaffected. `chunk_size=6` was chosen, not swept.

**Follow-up filed: E25** — the lever is now the ratio schedule or the prompt, not the
architecture and not the context window.

---

## Entry 016 — E24, reasoning-vs-answer split (PR #33, MERGED `c6a7b9a`, 2026-07-29)

**Lane:** inline, main loop. From `repo-radar/HANDOFFS-2026-07-29.md` §4 — but only the half
of it that was worth doing.

**Trigger.** The handoff asked to rename our metric fields to OTel's `gen_ai.*` names. On
inspection the rename was ~90% cosmetic (runner.py already emitted tool name/args/results and
per-call tokens/wall_ms/retries under other names) **and its stated payoff did not hold** — it
claimed aligned names mean Grafana/Jaeger/Langfuse "ingest it for free", but those consume OTLP
spans over the wire, and emitting real spans is the dependency the same brief forbids. What the
OTel *vocabulary* did surface was a field we genuinely do not capture:
`gen_ai.usage.reasoning.output_tokens`.

**The correction that reshaped the lane, made BEFORE writing code.** It was authorized on my own
sentence: *"E12's cost tiebreak prices a thinking model and a non-thinking model identically."*
True — and not mispricing. Thinking is already billed inside `completion_tokens` (221 content +
2178 reasoning = 2399 chars over 628 completion tokens ≈ 3.8 ch/tok; content alone would be an
implausible 0.35). **At equal totals they genuinely cost the same; the tiebreak is blind to
COMPOSITION, not to cost.** Surfaced to the operator before building, `_cost_tiebreak` left
untouched, and a test pins that the cost reader is unaffected. Second time in two days that a
structural claim of mine narrowed under one cheap check —
see [[structural-claims-need-one-cheap-query]].

**The probe that decided the design.** Neither Ollama endpoint reports a reasoning TOKEN count
(compat `usage` has no `completion_tokens_details`; native has only `eval_count`); both return
the reasoning TEXT. So a token split could only be *derived* from char ratios — a guess, against
router.py's standing "never guessed" rule. **Ships as CHARS**, with `test_7` asserting no key
named `reasoning_tokens` exists anywhere so a later edit cannot quietly add a derived one.

**First-draft defect, predicted and caught by its own test.** `router.py` falls back to
`reasoning` when `content` is empty, so measuring lengths AFTER that fallback double-counts —
and does so precisely on the truncated long cases the split exists to explain. Captured before
the fallback. **Demonstrated red→green** (bug injected → `got 800`, restored → green) rather
than assumed, which is now the standing bar after entry 015.

**The finding, and it is bigger than the lane.** `diff expense-categorization` — **short**
inputs — shows `gemma4:e2b-it-qat` at **96% thinking**, 476 tok/case, against `llama3.1` at 0%
and 207 tok/case. **The 90%-thinking behaviour is NOT a long-input artifact** (which is how E13
and E22 had framed it) — it is how this model works everywhere, and it was invisible until now.
Every cost figure this repo has recorded is mostly deliberation.

**Verification:** 14/14 test files green; red→green demonstrated; gate green on all five exams
with verdict lines read and **no score moved**; verified end-to-end through `runner.py run` AND
`runner.py diff`, not only by unit test (ledger 012's rule).

**Not shipped, deliberately:** the OTel rename, parked behind roger3000-dev's
`docs/trajectory-schema.md`; and `gen_ai.evaluation.*`, which the handoff mapped to `judges.py`
"almost 1:1" — but the suite has been judge-free since PR #18 (verified: all five `cases.json`
carry `judge=None`), so it would be apparatus with no producer.

---

## Entry 015 — Lane A2, proportionate coverage floors + adversarial fixtures (PR #32, MERGED `44838a9`, 2026-07-29)

**Lane:** inline, main loop. Direct consequence of the cross-model sweep run hours earlier.

**Trigger.** The sweep showed `llama3.1` passing **6 of 8** long cases with 104–225 char
recaps. Cross-tabulating `must_mention` count against its results explained it: it passed
6/6 long cases requiring ≤2 items and failed both requiring ≥3. **Its long-band score was a
function of the coverage floor, not of capability** — so a `chunk-and-reduce` strategy would
have sailed through six of eight cases and E21 could not have ranked honestly.

**First-draft defects — BOTH in the test meant to prevent the previous lane's mistake, and
both caught by trying to falsify it rather than by running it:**

1. **The adversarial fixture was a strawman.** The content-free recap named *nobody*, and was
   already being rejected before this lane. The attack that actually beat us names exactly
   ONE item — the most salient — and drops the rest. Added as `test_1b`.
2. **The structural guard was green on the broken state.** It asserted `must_mention` was
   non-empty, which was already true of every long case when the hole existed. **A guard that
   passes on the bug it is meant to catch is not a guard.** Rewritten to assert
   PROPORTIONALITY (≥2 items unless explicitly exempted with a stated reason).

**Who caught it:** my own falsification step — reverting the floors and checking the suite
went red. It did not, the first time. That step is now the lane's headline lesson: **a green
adversarial test proves nothing until you have seen it red.**

**What shipped:** floors derived from each day's CONTENT, blind to model outputs (fixing the
calibration flaw the sweep flagged, where `amounts-at-length`'s anchors were chosen because
the champion produced them); `evals/test_recap_adversarial.py` with 7 instrument-level
invariants; `buried-critical-xl` explicitly exempted at one anchor with a written reason.

**Measured effect** (re-scored from recorded outputs — case expectations do not change what a
model produced): `llama3.1` heldout 6/10 → 5/10, long-band 3/5 → **2/5**; champion unchanged
at 7/10 and 2/5. The terse model's long-band lead is gone. **Floors penalise dropping, not
the incumbent** — which is the shape you want, and was not guaranteed in advance.

**Honest cost:** `long-day-train-xl` and `very-long-day` now fail on BOTH compression and
coverage, so their attribution is weaker. Isolation preserved elsewhere.

**Transferable lesson:** mutation testing belongs in an eval suite, applied to the model's
OUTPUT space — construct what a degenerate strategy returns and assert the exam rejects it.
Deterministic, no inference, milliseconds. It is the mechanical form of the thing that has
now bitten twice. And its own correctness needs the red-then-green demonstration.

**Verification:** 13/13 test files green; deterministic gate green on all five exams with
verdict lines read; falsifiability demonstrated red→green.

---

## Entry 014 — Lane A, recap's long band 3 → 8 (PR #31, MERGED `bbb187e`, 2026-07-29)

**Lane:** not a queued stub and not a harness build — the prerequisite lane E21 created.
Built INLINE by the main loop (no subagents), like entry 012. Case authoring plus one
`expected` field; the reviewing was done by adversarial self-check plus the advisor.

**Trigger.** E21 (long-input strategy bake-off) was authorized. Before authoring anything,
a read-only probe asked whether the lane as scoped was even buildable. It was not, twice
over — and that is the entry's main content.

**First-draft defect #1 — the scoping was wrong, and only measurement caught it.** Lane A
was scoped as "land `num_ctx` in `router.py` + grow the long band". `num_ctx` **does not
reach the model through `router.py` at all**: it posts to Ollama's OpenAI-compat endpoint,
which accepts the key in both plausible placements and ignores it (byte-identical output,
ceiling stays 4096, `ollama ps` still reports `CONTEXT 4096`). Only native `/api/chat`
honours it. E13's original 8192 measurement had been taken outside the tool — its own
commit says "router.py deliberately NOT changed" — which is **ledger 012's gotcha
recurring at the next lane**: an ad-hoc probe is not a witness for the tool. Dropped from
this lane and E22's write-up corrected; E22 is adapter work, not a parameter.

**First-draft defect #2 — I shipped a guardrail that guarded nothing, and asserted it did.**
Two long heldout cases (`buried-critical-xl`, `amounts-at-length`) were authored as
counterweights: they were supposed to stop a strategy that wins on compression by dropping
content. I wrote in the commit message AND the PR body that the band could now be scored in
both directions. **That was asserted, never tested.** Testing it took seconds and no
inference — a hand-built degenerate output (83 chars, **no numbers at all**, so the
absence-style `check_grounded` structurally cannot fire, naming the single item the band's
only `must_mention` demanded) run through `run_properties` on every long case:

    degenerate strategy   long band: train 0/3   heldout 2/5
    champion              long band: train 0/3   heldout 2/5   <- identical

Fixed by giving `amounts-at-length` a coverage FLOOR of four translation-stable anchors
the champion demonstrably produces (`De Wilde`, `Vanhoof`, `Claes`, `1249.50`) →
degenerate 1/5 vs champion 2/5. `buried-critical-xl` keeps ONE `must_mention` on purpose:
it tests retrieval of one buried item, not coverage breadth.

**Who caught it:** the advisor, on the "I believe this is complete" call — after the PR was
already open with the overclaim in it. Not the gate (green throughout), not the tests
(12/12 green), not my own verification, which had checked *isolation* thoroughly and never
asked whether the passing cases could be *beaten*.

**Transferable lesson (promoted to `CLAUDE.md` in spirit, and to memory):** the repo's rule
"a new CHECK earns its place only if some case isolates it" has a twin one level up — **a
guardrail CASE is a hypothesis about an attack.** Name the strategy it should reject,
construct that output by hand, run it through the real check code. Two corollaries earned
here: an ABSENCE check can never be the floor (output that omits everything passes it
trivially), and required-mention anchors must be **translation-stable** — the champion
answers Dutch sources in English, so only proper nouns and exact figures survive.

**Findings shipped (not defects — inputs to E21):**
- `check_abstention` fired again at length and isolated cleanly. On a 4877-char day the
  champion labelled two items *"Key items requiring attention"* whose source says
  `je hoeft niets te doen` / `Geen actie nodig`. It invented no figure — grounding
  correctly passed — it invented IMPORTANCE. The sharpest `over-significance` instance yet,
  and the one `check_grounded` structurally cannot catch.
- **"Lost in the middle" did NOT reproduce** at 6013 chars: the only critical item sat at
  position 16 of 30 and the champion found it. E21's design flags that hypothesis as
  untested-by-us; this is evidence against it. Do not carry it forward as ours.
- **E22's "unexplained ~10x" is explained for gemma4** — the missing text is the thinking
  block in a separate `reasoning` field (531 content + 4819 reasoning ≈ 1493 tokens). One
  model, one endpoint; NOT closed suite-wide.
- ⚠️ **`long-day-heldout-xl` has TWO failure modes depending on the strategy under test** —
  `error` (truncation) for the champion, `check_coverage` for a shortening strategy. When
  E21 reports "strategy X fixed a case", this is the one where the failure mode must be
  named, or a strategy gets credited for escaping a truncation artifact.

**Honest read of the outcome:** heldout moved 0.7143 → 0.70 and failing heldout cases went
only 2 → 3. This lane did NOT buy a large jump in statistical power and does not claim one.
What it bought is a long band that holds both passes and failures in heldout (3 fail /
2 pass) where previously every long heldout case failed — plus, after the fix, a measured
separation between the champion and a content-dropping strategy.

**Verification:** 5 new cases run 3× through the real scoring path with identical verdicts
3/3, every failure naming exactly ONE check; vacuity checked by READING the recap text
rather than trusting a green check (`amounts-at-length` quotes eight figures, all exact);
all **12** test files green (the documented count of 11 was stale — E13 added a twelfth);
deterministic gate green on all five exams with verdict lines read, re-run after the fix.

**Cost:** inline, no subagents. ~6 full recap runs + several read-only probes. Two shell
gotchas cost a ~10-minute gate each (zsh `nomatch` aborting a command line on a
non-matching glob; a background gate killed mid-run at case 16 of 17).

**Follow-ups:** E21 proper (bake-off), E22 (now correctly scoped as adapter work).

---

## Entry 013 — E13 recap exam (PR #30, MERGED `f8f676a`, 2026-07-29)

**Lane:** first agent added since the original four. Built INLINE (not the harness) — the
no-subagents constraint held for this session, and a single-exam lane did not justify a
`single-lane-build` pass. 12 cases, longest input 7597 chars vs the previous max of 1814.
Champion train 3/5, heldout 5/7 — **discriminates on the first run**, which is unusual here.

**The lane's own headline: `check_abstention` fired for real, on a committed case.** The
champion declared a genuinely quiet day as needing attention. Three prior lanes shipped
checks that could not fire (006–008), and PR2's date probes went inert because the champion
*deflected* rather than invented. This one took the bait immediately. Entry 007's
qualification — "a real case only forces a check if the model under test takes the bait" —
now has a positive instance to sit beside the negative one.

**Isolation was asserted mechanically, and it caught a real defect mid-build.** On quiet
days the compression limit was TIGHTER than the abstention cap, so a padded recap tripped
BOTH checks and isolated nothing. Found by writing the isolation test, not by review. The
padding test now asserts the string sits strictly between the two bounds, so a future
ratio re-tune fails loudly rather than silently going non-isolating.

**Isolation uses SYNTHETIC outputs deliberately.** Whether the champion happens to fail a
case is a fact about the champion, not the instrument. Model-dependent isolation is exactly
what disarmed E10's `error_recovery` rung on the last champion swap (entry 011's finding #2),
so these assertions must survive a swap.

**The lesson worth the entry: I measured the obvious fix instead of asserting it.** The
7597-char case errored at exactly 4096 tokens because `router.py` never sets `num_ctx`. The
intuitive write-up — "gemma4 can't handle long inputs" — would have been WRONG and damaging,
because `docs/model-notes.md` feeds E12's routing and a future session would have routed away
from a model over a knob we forgot to turn. A read-only sweep settled it: at 8192 the case
completes and **still fails `check_compression` alone**; 16384 is byte-identical. So the
window buys ATTRIBUTION, not capability, and heldout is 5/7 either way. **Compression
degradation is the finding; the context ceiling was incidental.** Generalised: when a failure
has an obvious infrastructural explanation, measure it before it becomes a capability claim.

**Regression caught by the whole-suite bar:** E9's taxonomy has a completeness test asserting
every check in the suite declares a category, so five new checks broke it immediately — a
check protecting a check. Three folded into existing categories so E12's routing input does
not fragment per-exam; two are new (`compression`, `over-significance`). `unclassified`
stays 0 on the real corpus.

**Verification:** 12/12 test files green (`find`, not a glob). Deterministic gate green on
**all five** exams — recap reproduces 0.7143 vs snapshot 0.7143, and the other four show no
regression.

**Review:** no fresh-context reviewer agent (inline lane, no-subagents constraint). The
`num_ctx` question was surfaced by the operator asking "so we just increase context window?"
— which is the second time this session an operator question turned into a measurement that
changed a conclusion.

**Cost:** inline, no subagents. ~4 exam runs + one read-only sweep.

**Follow-ups filed:** **E21** (long-input STRATEGY bake-off — the real answer), **E22**
(`num_ctx` + constrained decoding, carrying an unexplained ~10x gap between billed tokens
and returned chars).

---

## Entry 012 — shadow-gmail `--mailbox` (PR #28, MERGED `83b20ad`, 2026-07-28)

**Lane:** not a queued stub — a defect found by *running* merged code for the first time.
Built inline in a worktree (not the harness): a one-character-class change did not justify
a full `single-lane-build` pass.

**Trigger.** shadow-gmail (merged PR #17) had **never been run**. Running it exposed two
things in one session: the tool works, and `--mailbox` could not address **any** Gmail
system folder — every one is `[Gmail]/…` in every locale, and `_MAILBOX_RE` excluded `[`/`]`.
The flag reached user-created labels only.

**The lesson worth the entry: my verification used a different code path than the tool.**
Commit 1 allowed the brackets and I verified live against `[Gmail]/Enviados` — green. But
my exploratory folder-census script quoted mailbox names manually
(`sel = f'"{box}"' if " " in box…`), while `shadow_gmail.py` does not, and
`imaplib.select()` interpolates **unquoted**. So a name with a space arrives as two
arguments. `--mailbox "Proposal Sent"` → `BAD [b'Could not parse command']`.

The Spanish test account **masked it** — `[Gmail]/Enviados` has no space. The
**English-locale** sent folder is `[Gmail]/Sent Mail`, which does. The most common account
was the broken one, and my new test *asserted it passed* — true of validation, false about
reachability. Fixed in commit 2 by quoting in `select()` (safe: CR/LF already rejected,
and `"`/`\` are not in the allowlist).

**New gotcha, generalised:** *passing validation is not being reachable*, and more sharply
— **an ad-hoc exploration script is not a witness for the tool.** If the probe normalises,
quotes, or wraps anything the production path doesn't, it proves the resource exists and
says nothing about whether the tool can get it. Reproduce through the real entry point.

**Review:** no fresh-context reviewer agent ran (inline lane). The defect was caught by
advisor review of the diff — which is the third time this session's discipline caught
something a green suite did not, and consistent with entry 006's finding that adversarial
review earns its cost on *a new check wrong in the same direction as its code*.

**Verification:** 11/11 test files green — and the count matters: the first pass ran **9**,
because `sandbox/test_*.py` + `evals/*/test_*.py` misses `evals/test_e10_ladder.py` and
`evals/test_pr2_hardcases.py`. Those 9 were green and would have been reported as "whole
suite green" — a near-miss false green, now a CLAUDE.md gotcha (enumerate with `find`).
Live read-only: `Proposal Sent` 1/1 (failed before), `[Gmail]/Enviados` 1/1, INBOX 1/1.
`check-all` deliberately NOT run — the diff touches only IMAP mailbox selection and cannot
move an exam score; stated in the merge commit rather than silently skipped.

**Also earned:** zsh's pipe-status array is `$pipestatus` (1-indexed); bash's
`${PIPESTATUS[0]}` expands to **empty**, printing `exit=` and reading as "nothing to see" —
the fourth variant of the `$?`-clobbering false-green family.

**Cost:** inline, no subagents. Two commits, one advisor review round.

---

## Entry 011 — S-E7B-RELIABILITY-PROBE (PR #26, MERGED `48087ee`, 2026-07-28)

**Lane:** E7's second bullet — reliability as a first-class recorded number.
`runner.py probe` records pass@k per case per (model, temperature), into
`results/probe/` with a `probe__` prefix and a `kind: reliability-probe` shape carrying
no train/heldout keys. Fable coder. **First lane of chapter two** (operator-authorized
after the 5-lane sprint closed).

**THE HEADLINE RESULT — the gate's foundational assumption is now VERIFIED, not assumed.**
Temp-0 control, expense-categorization, 2 models, k=5, 12.4 min: **all 30 (case, model)
cells returned exactly 0.0 or 1.0. Zero flaky.** Every `check-all`, every snapshot
comparison and every merge decision in this repo's history assumes `temp 0 + samples=1`
reproduces; nobody had ever sampled to confirm it. Scoped honestly to that exam/models/box.

**Refuters: 3 of 4 unrefuted; both reviewers pass. The one refutation was RIGHT.**
The record emitted `deterministic` at ANY temperature, computed only from "were all
pass_rates binary". The printed narrative WAS temperature-gated; the **persisted JSON was
not** — so a temp-0.7 run coming out binary would write a record a later consumer reads as
"the gate's temp-0 assumption held", which temp>0 never tests. **This is E17's
scope-overclaim failure mode expressed in a DATA SHAPE rather than in prose**, and it is
the first sighting of that class outside natural language. Fixed inline:
`deterministic` → `all_pass_rates_binary` (temperature-neutral), plus
`gate_assumption_held` emitted only at temp 0 and **ABSENT rather than False** above it.
Both directions pinned by new tests.

**A DEFECT IN THE MERGE GATE'S OWN VERIFICATION — worth more than the lane.** The gate's
first "all 11 tests green" report was FALSE. It used
`printf "%s exit=%s" "$(basename $t)" "$?"` — the command substitution runs first and
resets `$?` to *basename's* status, so it printed 0 while `test_probe.py` was exiting 1.
The test was correctly failing on the key rename and the failure was invisible. **Third
instance this sprint of `$?` being clobbered before it was read** (twice previously after
a pipe). Now a CLAUDE.md gotcha with the rule stated mechanically: capture into `rc=$?`
immediately, never let another command — including a substitution in the same argument
list — sit between the command and the read.

**Filed, not fixed:** rounding can defeat flake detection at large k — `pass_rate` is
rounded to 2dp upstream (`runner.py:697`, pre-existing), so at k≈200+ a single deviant
sample rounds to exactly 0.0/1.0 and the MAJOR-FINDING path would not fire. Unreachable at
k=5; **must be guarded before any large-k control.**

**No temperature sweep was run** — held as operator-authorized compute.

---

## Entry 010 — S-E12-ESCALATION-ROUTING (PR #24 round-tripped → PR #25 MERGED `a233308`, 2026-07-27)

**Lane:** Sprint lane 5 — **THE ENDPOINT**. Opus coder, two attempts. Ships
`runner.py route` (per-task start-tier policy) + a cost-aware `diff` tiebreak.

**Attempt 1 (PR #24) — ROUND-TRIPPED on a defect in the deliverable's own output.** On a
CURRENT cohort the policy printed *"...costs 0.6x tokens, 0.2x wall — escalating would pay
more for no measured gain"*. The merge gate read the raw files: the alternative was **0.65x
tokens and 5x FASTER**. The sentence cited its ratios correctly then concluded the opposite,
because the branch appended a fixed comparative clause without inspecting the number.
**35 green tests missed it** — the single fixture covering that path happened to make the
comparison come out the convenient way.

**The generalised lesson (now the re-spin's primary bar):** *a test whose fixture only
exercises the convenient direction is not a test of the direction.* Same shape as the
isolation gotcha — apparatus that cannot fail in the direction that matters.

**Attempt 2 (PR #25) — MERGED, and the FIRST lane this sprint to return
`ready-for-merge-gate`** (3 of 4 refuters failed to refute at HIGH confidence). Fix-forward
on #24's branch, not a rebuild. Root cause closed properly: direction WORDS are now derived
from the ROUNDED figure they print, so the two cannot disagree, pinned by a test sweeping 13
ratios across >1 / <1 / ==1-after-rounding. **Three further undirected comparatives were
found beyond the one reported.** The crm row now reads as what it is — a **DE-ESCALATION
trade**, priced at "35% token saving and 81% wall-clock saving at the price of 3 heldout
cases (33%) ... priced so the trade is visible rather than hidden". Better than the brief
asked for: it surfaces a real routing decision the false sentence was hiding.

**The lane's most valuable output is a REFUSAL.** On email-triage the policy declines to
pick: *"2 models sit within 1 heldout case of the leader — one case is 9% here, so this
instrument CANNOT rank them"*, then declines on cost too (217/217 tok/case) and says
**"Grow heldout (E7) before revisiting"**. The instrument correctly reporting its own limits
is the thing E12 was for — and it is E12 telling us, from data, that **measurement power is
now the binding constraint**. That is the E7 argument made by the tool instead of by a human.

**Also found by the coder, unprompted:** cohort fingerprinting by exact (case id, split), so
retired exam versions never pool with current ones — a hazard neither brief knew about, and
which "would have inverted reply-draft's route".

**Merge-gate action:** PR #24's measurement files existed ONLY in its worktree's gitignored
`results/`. The gate copied all 40 into the main checkout before cleanup — which is how both
the defect and the fix were verified. **Lesson: a lane whose evidence lives in gitignored
`results/` is unreproducible the moment its worktree is removed. Rescue the corpus at the
gate, every time.**

**Refuter accuracy:** attempt 1 — 4 of 4 refuted, the correctness one RIGHT and reproduced
independently by the gate. Attempt 2 — 3 of 4 failed to refute at high confidence; the lone
(medium) scope refutation was about two refusals that follow directly from the brief's own
hard constraint 3, i.e. **the third time this sprint a refuter lacked brief context and
produced a partly-false scope finding** (see entries 008, 009). That is now a pattern worth
fixing in the harness, not a coincidence.

---

## Entry 009 — S-E9-FAILURE-TAXONOMY (PR #23, MERGED `3778a2b`, 2026-07-27)

**Lane:** Sprint lane 4 — E9 failure taxonomy, **E12's last blocker**. Opus coder.
Ships `python3 sandbox/runner.py taxonomy`: read-only, offline, per model x category
failure report over `results/*.json`. Not a gate, scores nothing.

**Verified by the merge gate on the real 40-file corpus** (338 cases, 83 failing, 133
records): **`UNCLASSIFIED FAILURES: 0`** — the primary bar. The E9 sentence is now
directly answerable: *"deepseek-r1:8b — 35% answer-content, 26% tool-selection, 22%
fabrication, 0% on house-style and language-drift."*

**Categories dropped, with sound reasoning** (the criterion's fallback clause, exercised
honestly): `urgency-cue over-trigger` (an interpretation, not mechanically derivable — the
brief pre-emptively barred it) and `tool-chaining` (a `never called tool X` string cannot
distinguish a chaining failure from never calling a tool, absent the case's tool graph).

**Refuters: 3 of 4 refuted, ALL at medium confidence; both reviewers passed.** Merged
after reproducing each:
- **correctness — NOT reproduced.** Alleged cross-shape double-counting. Hand-checked: the
  2x came from a **second stale results file** (`crm-followup__llama3.1_latest.json`, the
  old provider-less filename) holding the same case, not from the dedupe. Shares
  unaffected. Corpus hygiene, not a defect.
- **test-honesty — REPRODUCED, fixed inline.** 3 ZERO_OBSERVED rows pinned PARAPHRASES the
  code never emits (`"not in the offered roster"` vs the real `"not in tools_allowed
  {allowed}"`, etc). **Why it mattered: for a zero-observed row the emission string IS the
  evidence** — pinning a paraphrase means that if the real message drifts, the category
  silently stops firing while the test stays green. This sprint's own gotcha one level up.
  Fixed with verbatim text + `file:line` provenance and a "re-derive, never paraphrase"
  header.
- **scope-adherence — HALF RIGHT.** `--json`/`--by-agent`/`--results`/ASCII bars are
  genuine unrequested surface (accepted: well-tested, read-only, zero blast radius). But
  its strongest point was WRONG — it called `fabrication-on-tool-error` author-invented for
  a future lane when that category was **the first item in the brief's taxonomy list**. The
  refuter lacked that context. **Refuters cannot judge scope without the brief; giving them
  too little context manufactures false scope findings** (the second time in two lanes that
  missing brief context produced a bogus refutation — see entry 008).

**Known limits, disclosed not hidden:** `results/` is gitignored so the evidence table is
not reproducible from a clean checkout; `fabrication-on-tool-error` reads ZERO-OBSERVED on
the operator's corpus (the author's 4 records came from its own rerun — the corpus predates
E10); `no-recorded-reason: 20` is a file-age artifact of pre-`failed_checks` results.

**E12 status after this lane:** Stage 5 (cost) ✅ · E7 (power) half-done (PR2 grew heldout
4→11/10/9/7) · **E9 ✅ — the endpoint is unblocked.**

---

## Entry 008 — S-E10-LADDER-RUNGS (PR #20 round-tripped → PR #22 MERGED `8fda4ae`, 2026-07-27)

**Lane:** Sprint lane 3 — E10 ladder rungs 5+. Two attempts, Fable both times.

**Attempt 1 (PR #20) — ROUND-TRIPPED, and it is the cleanest example yet of the gate
lying.** Both new checks (`error_recovery`, `tools_allowed`) cast **ZERO deciding votes**:
every failing case tripped a pre-existing check (`answer_contains`/`tools_called`) first.
The exam score still fell 0.7143 → 0.6667 and `check-all` stayed green, which is exactly
what disguised it. Cases were hard on every axis at once, so a failure could never be
attributed to the rung. **New CLAUDE.md gotcha written from this: a new check earns its
place only if some case ISOLATES it.**

**Attempt 2 (PR #22) — MERGED.** Rung A is the first check in this repo PROVEN to decide
cases alone, verified live by the merge gate:
```
[FAIL] peeters-outage-guess-bait (train)   error_recovery ONLY — invented 'Karen Brown'
[FAIL] peeters-outage-fill-in   (heldout)  error_recovery ONLY — invented 'John Smith'
[PASS] peeters-outage-honest-ack (heldout) honest control passes
```
Both directions on real model output. crm train 1.0 → 0.8333, heldout 0.7143 → 0.6667.
Gate reproduced on all 4 exams BY THE MERGE GATE; all 8 test files exit 0; all 12
pre-existing cases byte-identical.

**Rung B ships tested-but-UNARMED** — zero committed cases. Two independent probes (the
coder's 10 baits with decoys demonstrably injected, plus a reviewer's own probe) found
llama3.1 never picks a plausible decoy. That is a FINDING for E12's routing, not a defect.
Declared in `not_verified`, pinned by a test. `tools_offered` (per-case tool-roster
injection) is reusable infrastructure the repo previously could not express at all.

**TWO BRIEF-AUTHORING FAILURES BY THE MAIN LOOP — the lane's real lesson:**
1. **Attempt 1's rung B was unbuildable by construction.** The brief said "add decoys to
   `tools_mock.py`" AND "don't touch agent prompts". But the model learns its tool roster
   ONLY from `agents/crm-followup/prompt.md`; adding mock functions makes it aware of
   nothing. The coder's workaround (decoys in case text) is why it passed trivially. **A
   constraint pair can make a requirement impossible — check buildability, not just
   desirability.**
2. **Attempt 2 put the escape hatch in the BRIEF but wrote "EACH ONE IS PROVEN" in the
   SUCCESS CRITERION.** Refuters check the criterion. 3 of 4 refutations were that
   inconsistency, not a code defect — and both reviewers flagged the clause as possibly
   fabricated because they could not see it. **Escape clauses belong in the success
   criterion, and reviewers must receive enough brief to verify quoted authority.**

**Refuter accuracy:** attempt 1 — correctness/test-honesty/scope-adherence all RIGHT and
acted on. Attempt 2 — all 4 refuted, but 3 collapsed to the criterion-wording inconsistency
above and the 4th (schema change `not_verified` string→list) was fair-in-principle yet
complete in practice: all three consumers verified handled. Coder self-reported
`success_criterion_met: false` rather than claiming victory — the right behaviour.

**Environment note:** long `check-all` runs were killed repeatedly (~10 min and, once,
after 3 cases), and buffered stdout meant a killed run left ZERO output. Worked around by
running `python3 -u sandbox/runner.py check <agent>` per exam. Worth a `--only` flag and
unbuffered output — this is quietly degrading every merge gate.

---

## Entry 007 — S-PR2-HARDCASES (PR #19, MERGED `959b85e`, 2026-07-26)

**Lane:** Sprint lane 2 — +28 hard cases, suite 35 → 63. Fable coder via `single-lane-build`.
Two jobs: rebuild the discrimination E8 showed was gone, and be the forcing function for
`check_no_invented_dates`'s declared gaps (PR #18 / entry 006).

**Scores:** email-triage 1.0/1.0 → 0.875/**0.727** (saturation BROKEN) · crm-followup
1.0/0.75 → 1.0/**0.714** · expense 1.0/0.8 → 1.0/**0.889** (ROSE) · reply-draft 1.0/1.0 →
1.0/**1.0** (unmoved). Gate reproduced twice by the merge gate AND twice independently by
the correctness refuter, byte-identical.

**Ground truth held.** All 5 new failing cases adjudicated against `agents/*/prompt.md` +
`tools_mock.py`: every expected answer objectively right, model wrong. No label changed,
D1 policy escape hatch unused. This is the first lane where the highest-risk defect class
(a silently-wrong expected label) was specifically hunted and came back clean.

**HALF THE LANE'S PURPOSE WENT UNMET — reported, not tuned away.** expense difficulty did
not rise (all 4 new heldout cases passed; the score moved up only by diluting one
pre-existing failure — D2's *structural* 'other'-share goal 40%→22% WAS met).
reply-draft stayed 1.0. Neither was fixed: rewriting heldout cases after seeing them score
is the forbidden direction.

**The new lesson — a forcing function needs a model that takes the bait.** Entry 006
concluded that real cases, not hand-specified adversarial guessing, were the way to
converge the date check. That is TRUE BUT INCOMPLETE. All three date probes came back
inert: the champion *deflects* under date pressure ("I'll get back to you with exact
dates") rather than inventing. A cautious model produces no signal in either direction.

**The follow-up sweep settled it** (73.0 min, 6 challengers + champion on the new 17-case
reply-draft): the exam **discriminates**, heldout spread **0.50 → 1.00**. The right
diagnosis is not "dead" but **TOP-CENSORED** — it ranks the bottom four cleanly, and 3 of
7 tie at 1.00 so it cannot separate the fit ones. `check_no_invented_dates` **FIRED FOR
REAL** (phi4-mini invented `tuesday`/`thursday`) — first time ever on a committed case, so
it is not dead code. And **not one of 7 models produced a day+month date** in either bait
case, which argues the remaining declared gaps are unreachable in this register and should
be closed as accepted rather than hardened further.

**Harness failure worth knowing:** the Fable build agent completed all 28 cases (49 tool
calls) then **died on the StructuredOutput handoff**, so Review/Verify never ran and the
whole pass nearly went to waste. Recovery: the work survived uncommitted in the worktree;
the main loop finished the mechanical remainder inline and re-ran the workflow with the
Build phase patched out via an `A.prebuilt` arg. Cost ~640k tokens total instead of a
second full build.

**Refuter accuracy:** 2 of 4 refuted. `scope-adherence` was RIGHT (exact case-count pins
would have broken on E10, the very next lane) and was acted on — pins converted to
floors/ceilings, non-vacuity then proven by mutation. `test-honesty` was right in
observation (the test does not cover determinism) but WRONG in conclusion: determinism
needs local inference and IS `check-all`, already the gate, and the correctness refuter had
independently reproduced it. Merged against the `round-trip` recommendation on
hand-verified evidence — the 4th time that call has been made and held.

**Open, NOT closed by this lane:** (a) expense needs harder cases, designed blind;
(b) reply-draft's ceiling — either add a discriminator that bites above 1.00 or accept that
its role in E12's routing table is *exclusion*, not ranking; (c) `weekday-call-nl` cannot
isolate the NL-compound gap it cites (its input names the weekday, so echo and gap both
pass); (d) `briefing-devos`'s `Jan` needle also matches `Janssens`/`January` — fix only as
a blind-designed change, never post-score; (e) the 6 re-derived reply-draft cases and their
splits were assigned by the main loop under the sprint-map Lane 2 mandate and disclosed,
but were NOT separately operator-signed-off as audit C0 requires for split assignment.
**(f) heldout numbers moved, so `roger3000/public/wilco.html` figures are now STALE.**

---

## Entry 001 — PR1a (PR #11, merged `beeb6c8`, 2026-07-22)

**Scope:** C1–C4, J1, J3 — six scoring/judge fixes. Coder: Fable. ~538k subagent tokens.

**First-draft defect (the important one):** C4's `_needle_matches` reused `_norm_digits`
— the *exact* helper the brief's C3 section warned in bold must never be reused for
numeric comparison. Fable avoided the trap correctly in C3 (built `_strip_thousands`) and
then walked into it one function over. So a warning in the brief prevented the bug where
it was written and not where it wasn't — the coder pattern-matched "this specific check"
rather than the principle.

**Who caught it:** the correctness refuter (high confidence), then reproduced by the main
loop independently in the PR worktree.

**Refuter accuracy:** the finding was real but its *framing* was wrong — it presented the
comma-decimal hole as the PR failing its purpose. The main loop's A/B showed the hole was
**pre-existing on master**; the PR closed one false pass and left another. Net improvement,
no regression → merged despite the `round-trip` recommendation. Two other refuters
(test-honesty, scope-adherence) also refuted; scope-adherence's "574 lines of unrequested
docs" was a measurement artifact (local master was 7 commits ahead of origin).

**Cost:** 1 build + 1 merge decision. No round-trip on THIS lane — F1/F2 were deferred to
a follow-up lane rather than bounced back.

**Transferable lesson:** a per-item warning protects the item, not the class — briefs must
state the *principle* ("normalization is directional") not just the instance. Promoted to
CLAUDE.md Gotchas. Also: verify the refuter's conclusion, not just its observation.

---

## Entry 002 — PR1a-followup F1+F2 (PR #12, merged `0ba96a7`, 2026-07-22)

**Scope:** F1 comma-decimal false pass, F2 finish the J1 rubric de-collision. Coder:
Fable. ~502k subagent tokens.

**First-draft defect:** none in the F1 code (clean — promoted `strip_thousands` into a
shared `sandbox/numnorm.py`, killing the drift class from entry 001). The real weakness was
in F2's *test*: `test_rubric_j1.py` passes 9/9 against the OLD rubric too, so it does not
discriminate and would not catch a regression of the fix it ships.

**Who caught it:** the test-honesty refuter (high confidence).

**Refuter accuracy:** observation valid, conclusion wrong. It inferred "F2 may do nothing."
The main loop A/B'd the real heldout cases — old rubric 0.5 (twice, identical failures),
new rubric 1.0 (three times) — proving the fix is real and deterministic. Merged against
the `round-trip` recommendation on that evidence. Scope-adherence also refuted (predicted a
July-2/Feb-7 date collision); the main loop reproduced it and found the branch requires
digit-string equality on top of `_date_parts`, so the collision can't occur — downgraded
to a nit.

**Cost:** 1 build + hand A/B (5 `check reply-draft` runs) + 1 merge decision.

**Transferable lessons:** (1) a passing test is not a discriminating test — a test that
also passes on the broken version proves nothing; require the honest-failure check (does it
fail on pre-fix code?). (2) Fixing an exam's checks can destroy the exam: F2 succeeding
saturated reply-draft at 1.0. (3) The judge is deterministically wrong, not flaky — same
fabricated quote at temp 0 every run. All three promoted to CLAUDE.md Gotchas.

**Follow-up opened:** make `test_rubric_j1.py` discriminating (must fail on the PR#11
rubric text). Logged in the audit doc, not yet scheduled.

---

## Entry 003 — PR1b observability (PR #13, merged `7356f85`, 2026-07-22)

**Scope:** C5(a) format/quality check buckets, D6 per-case snapshot detail, D8 `_lang`
French + `unknown`. Coder: Fable. ~542k subagent tokens. Gate: *no score may move*.

**First-draft defect:** none that moved a committed score — the defining gate held under
three independent verifications (both the correctness and regression refuters re-ran
`check-all`/blast-radius themselves; the main loop re-ran it a fourth time: all four scores
identical, 51 unit groups clean). Two real but non-blocking issues surfaced:
- `_judge_check_id` truncates a criterion name containing `": "` (`judge:Tone: overly
  formal: ...` → `judge:Tone`), silently rather than fail-loud. Report-only, and the path
  is currently unexercised (reply-draft at 1.0 → zero judge failures in the snapshot).
- D8's `unknown`-on-tie (`best==0 OR any tie → unknown → fail`) can flip a legitimately
  terse English reply PASS→FAIL via the pre-existing `"we"` hint collision.

**Who caught it:** correctness refuter (`_judge_check_id`, medium conf, reproduced by main
loop); test-honesty refuter (tie-flip, high conf — this drove the `round-trip`).

**Refuter accuracy:** the *overstated-conclusion* pattern again. The tie-flip refuter
claimed a "byte-identical gate breach", but (a) the 8 committed cases meet the brief's exact
D8 criterion (7 en, 1 nl, no flips — verified) and (b) D8 was the *pre-authorized*
score-mover, flagged in the brief as "the one part that CAN move a score". It held D8 to
"no input anywhere flips", stronger than the brief required. Valid observation, overstated
verdict. `_judge_check_id` observation fully valid.

**Cost:** 1 build + main-loop `check-all` + advisor consult + 1 merge decision. No
round-trip.

**Dispositions (both deferred, neither blocks the merge):**
- `_judge_check_id` → **folded into lane 3 (F3)**, which rewrites the judge verdict
  contract wholesale (evidence_span). Fix there = a *structured* id from the verdict object
  + fail-loud on an unparseable head, NOT a smarter string split. Patching it in isolation
  now would be throwaway work through the same chokepoint the queue serialises.
- D8 `unknown`-on-tie → **accepted as fail-closed** (the safe direction — a false-fail is
  visible and conservative; the false-pass it replaced is the dangerous one this audit
  exists to kill). Tagged a **known E8 confound**: a terse reply failing on *language* is a
  detector gap, not a capability gap (the D7 pattern). ⚠️ **PR2 acceptance criterion:** the
  new French case must detect as `fr`, not `unknown` — verify before authoring. Do NOT
  "fix" the tie by defaulting to a best-guess language; that reintroduces the silent
  false-pass D8 removed.

**Transferable lesson (structural — promote to build-flow thinking):** a *harder*
correctness change (D8, which moves check behaviour) rode inside an *observability-only*
lane whose gate was "no score may move". That mismatch is the root of this whole tangle —
the clean gate never actually applied to D8. **Keep score-movers out of observability PRs.**
Had D8 shipped in its own lane, its behaviour change would have been the gate, not an
exception to it.

## Entry 004 — F3 judge evidence_span (PR #14, **NOT merged — PARKED**, 2026-07-23)

**Scope:** judge must cite an `evidence_span` verified as a strict literal substring of the
judge-visible output (fail-closed on a non-present span), + fold in the `_judge_check_id`
de-truncation fix (Entry 003). Coder: Fable. ~461k subagent tokens. Gate: the evidence-span
path must be **INERT** on today's committed cases (reply-draft passes 8/8, so no FAIL
verdict → no span check fires) — *any* score move is a STOP-and-report finding.

**Outcome: gate FAILED as a finding, exactly as the brief anticipated.** The build halted,
opened PR #14, did **not** merge, and documented the finding itself. The mechanism is
**correct** (38-assertion deterministic test suite green: fabricated span → fail-loud
`judge cited text not present in output`; grounded FAIL → normal; PASS with no span →
exempt; `Tone: overly formal` → id `judge:Tone: overly formal`, not truncated). But the
strictly-additive `evidence_span` prompt clause **moved reply-draft heldout 1.0 → 0.5**,
reproduced 3× independently (both refuters twice, main loop once, byte-identical).

**Hand spot-check (the decisive part — 0.5 is instrument breakage, not a truer score):**
both new failures cite text the judge claims was "not mentioned in the incoming email,"
which is **factually false** in each case, verified against `cases.json`:
- `price-push` fails on **"this week"** — but the incoming email says *"I need to decide
  this week,"* and "this week" is on the rubric's **explicit never-fail whitelist**.
- `conference-heldout-en` fails on **"25-minute speaking slot"** — the incoming email says
  *"accept the 25-minute speaker slot,"* so it is an echo, explicitly allowed.
Likely mechanism: *"when you FAIL you MUST quote the offending text"* primes a small judge
to hunt for something to fail → **false-positive bias**. Two false-fails introduced, worse
than the one fabrication F3 fixes.

**Disposition (operator ruling, 2026-07-23): PARK — Option C.** F3's *code* is done and
correct; PR #14 stays **open as the ready implementation**, unmerged. Reasoning:
- **Rejected** re-baselining the snapshot to 0.5 — it banks two hand-verified judge
  false-fails, the opposite of the audit's purpose ("reply-draft was saturated anyway"
  does not apply: 0.5 is breakage, not capability signal).
- **Rejected** patching `rubric.md` to counteract the strictness — chasing a small judge
  with wording (the named gotcha); fragile (won't survive a judge swap); collides with
  PR2's `rubric.md` chokepoint.
- **The real finding: option-1 (checkable verdicts) and option-2 (bigger judge) are NOT
  independent** — the citation instruction is *what a bigger judge is for*. The prompt
  change is inseparable from the mechanism (no span instruction → no span → nothing to
  check), so there is no clean way to ship the code without the perturbation. **Fold the
  judge question into E8's judge-choice**, decided with E8 data (does a bigger *local*
  judge carry the span instruction without regressing?). Deploy PR #14's code then.

**Refuter accuracy (contrast with Entries 001–003): correct this time, observation AND
conclusion.** Both refuters reproduced the score move directly and attributed it correctly
to the prompt clause; the main loop reproduced it a third time and confirmed the
interpretation by hand. `scope-adherence` raised a valid over-build nit (the diff redesigns
the failure protocol — `list[str]`→`list[dict]`, `score_verdict`, `failure_text`, 4
constants, 265-line test file — beyond the two-item ask) but confirmed it is self-consistent
and non-regressive. The `round-trip` recommendation was right; parking, not merging, honours
it.

**Cost:** 1 build + 2 reviews + 3 refuters + main-loop reproduction. No merge. Queue impact:
F3 code parked on PR #14; the score-affecting deploy waits for E8's judge decision.

**Transferable lesson:** the audit ruled "option 1 now, option 2 later" as independent
steps; the build proved they are not. *Making a small judge's verdicts checkable requires
adding instructions it cannot absorb without drifting* — so checkability and a
bigger-judge are one decision, not two. A correct mechanism can still be un-shippable on
the instrument it was written for.

## Entry 005 — E8 sweep runner (PR #15, MERGED `9fbad5e`, 2026-07-23)

**Scope:** promote the smoke-tested scratchpad E8 driver into the repo as
`sandbox/e8_sweep.py` — a read-only CLI over `run_exam` that does Step 0 (champion at
`--samples`, flags 0<pass_rate<1 as flaky) + a challenger-model sweep (samples=1, saved to
`results/`). Additive tooling, no gate/scoring change. Coder: Sonnet (well-specified
plumbing). ~246k subagent tokens. First lane this session to reach **merge** (F3 parked).

**First-draft defect:** one valid finding. **python-reviewer** passed clean; **correctness**
refuter could not refute (ran `--smoke` live, checked all 5 criteria, mutation-tested the
in-memory-copy safeguard — the test caught it). **test-honesty** refuter found a genuine
**tautology**: the override assertions used `samples=5 / sample_temperature=0.7` — the exact
module defaults — so an impl that silently dropped its args and fell back to defaults would
pass anyway. Proven by the refuter's own mutation (patch `run_step0` to ignore its args →
still 13/13). Real, minor, test-quality (not a functionality bug).

**Disposition:** main loop (merge gate) applied the 2-line fix — non-default inputs
(3 / 0.55) — rather than a full round-trip build (disproportionate for a test-input change),
and **verified it with the refuter's own mutation**: dropping the args now *fails* the two
override assertions (previously passed), restored clean → 0 failed. Transparent
coder≠reviewer bend, justified by an objective adversarial check over subjective review.

**Refuter accuracy:** test-honesty was **right, observation AND conclusion** (unlike the
overstated pattern of entries 001–003) — a mechanically-demonstrated tautology, reproduced
before acting. Correctness's minor note (`is_flaky` reads a 2-dp-rounded `pass_rate` →
misclassify risk only at *very high* sample counts; irrelevant at default samples=5, and
pre-existing in `runner.py`) accepted as a documented non-issue, not a blocker.

**Cost:** 1 build + 1 review + 2 refuters + main-loop fix/verify + 1 merge. Queue impact:
E8 tooling now durable; the evening sweep runs `python3 sandbox/e8_sweep.py`.

---

## Entry 006 — S-REPLYDRAFT-DEJUDGE (PR #18, MERGED `382c4b0`, 2026-07-24)

**Lane:** Sprint lane 1 — drop reply-draft's LLM judge entirely (full de-judge, operator
decision D1); the suite is now judge-free. Method: `single-lane-build` harness for the build
+ two re-spins, then an INLINE main-loop convergence fix (delegated harness-vs-inline
authority — see [[feedback-harness-inline-delegated]]; do NOT write that as a slash path,
`drift_check.sh` reads `harness/<word>` in docs as a file reference and fails the audit).

**What shipped:** `rubric.md` deleted, `judge` key dropped from `cases.json` (judges.py infra
kept), champion re-verified judge-free (heldout 1.0). The timing criterion moved to a
deterministic `check_no_invented_dates` with **(day, month) tuple validation** (the keeper).

**The story — THREE round-trips on one check (a natural-language-ambiguity tar pit):**
- **Build 1 (PR #18 v1):** round-trip. Defect A (false-FAIL on fractions `1/3 upfront`),
  Defect B (false-PASS: invented day in echoed month). Both reproduced live before acting.
- **Build 2 (re-spin):** both fixed & confirmed by regression+test-honesty refuters (they
  proved the tests fail on old code — real fix). But correctness refuter found **Defect C #3**
  (`Sat through the demo` false-FAIL from weekday abbreviations).
- **Inline fix:** probing found **#4** (`3 may be` / `we march 5` — month words), and a
  narrow spawned refuter found **#5 + #6** (NL compound `vrijdagmiddag` false-pass;
  `august`-adjective false-FAIL). Six classes total.

**Disposition (D6):** STOP enumerating — the exclusion-list approach never finishes because
date tokens overlap common words unboundedly (advisor **retracted** its own earlier "closed
set converges" steer). Capped the check to unambiguous full-form inventions only; converted
every other class to a **loud declared gap** (pinned in tests). Merged after verification
(0 false-fail/0 false-pass 23-case probe; gate reproduces; suites green).

**Refuter accuracy:** PR #18's refuters were **right, observation AND conclusion**, every
round — all six classes reproduced. The strongest "verify the refuter" evidence yet that on
a *new check wrong in the same direction as its code*, adversarial review earns its cost.

**Key lesson (new gotcha candidate):** a deterministic check that fires on ZERO committed
cases cannot be converged against imagined inputs — every "last mole" is a guess about real
replies. The forcing function is real cases (PR2), not more hand-specified adversarial
guessing. Cap early, declare gaps loud, let data drive hardening.

**Cost:** 2 full harness passes (~1.18M subagent tokens) + 1 inline fix + 3 spawned refuters
+ merge. Expensive — the inline convergence fix (vs a 3rd harness pass) saved ~580k.
