# E20 brief — long-HORIZON: the first multi-turn exam

**Status: ⛔ STEP 0a RAN AND KILLED IT. Do not build as scoped.** Scoped 2026-08-05, falsified
the same day — 9 model calls, zero repo code, under an hour. Read the result block first; the
design it was testing is preserved unedited below.

---

## ⛔ STEP 0a RESULT — the regime is NOT binding for this champion

**Pre-registered criterion: "champion holds all three constraints at turn 3, all 3
conversations → STOP." It held 3 of 3.**

Three real `reply-draft` cases, three turns, constraints accumulating (C1 sign off as Michiel ·
C2 under 40 words · C3 no digits), checked on the **extracted reply**:

| case | turn 1 | turn 2 | turn 3 |
|---|---|---|---|
| `quote-request` | C1 ok | C1 ok · **C2 FAIL** (42w) | C1 ok · C2 ok (39w) · C3 ok |
| `price-push` | C1 ok | C1 ok · C2 ok | C1 ok · C2 ok · C3 ok |
| `budget-figure-demand` | **C1 FAIL** | C1 ok · C2 ok | C1 ok · C2 ok · C3 ok |

- **Drift instances (satisfied when introduced, then violated later): 0**
- Constraints failed when introduced and then **fixed** by a later turn: 2
- Conversations holding every constraint at turn 3: **3/3**

🔥 **The champion gets BETTER across turns, not worse.** Each further instruction acted as a
correction. That is the opposite of the degradation Multi-IF reports (`o1-preview`
0.877 → 0.707) — **their result does not reproduce here**, which is precisely why this brief
insisted the public numbers were not ours.

### ⚠️ The probe reported BUILD, and it was wrong twice

The script's own verdict line said *"BUILD — earlier constraints are being dropped"*. Both
reasons were bugs; the real answer only appeared after fixing them:

1. **Word count ran on the JSON wrapper, not the reply.** The model returns
   ```` ```json {"reply": ...} ````; the envelope added ~2 words and pushed `quote-request`
   turn 3 from 39 to 41 — across the 40-word limit, inverting that row. **Measuring the
   envelope instead of the answer** is rule A4 in a new costume.
2. **"Never satisfied" was counted as "dropped".** A constraint failed at the moment it was
   introduced and still failing later is *single-shot difficulty*, not drift. Drift requires
   satisfied-then-violated. Correctly defined: **zero**.

Either bug alone would have authorised a lane the evidence does not support. **A falsifier can
itself be wrong in the direction you were hoping for** — this is the fourth instance this repo
has recorded of an instrument agreeing with its author.

### What this licenses

**Not** building E20 as scoped. The kill criterion fired; honour it rather than picking harder
constraints until it fails — that is tuning a probe toward a wanted answer.

**Legitimately open, as a NEW probe with its own pre-registered criterion, not a re-run:** the
constraint types here were easy and self-verifying. Multi-IF's degradation may come from harder
or more numerous constraints, more turns, or non-Latin scripts.

**Scope of the negative:** N=3, one champion, one exam, 3 turns, easy constraints. Reason not to
spend a lane — not proof the regime is inert.

---

**Everything below is the design as scoped BEFORE the probe. Preserved unedited.**

**Status when written: BRIEF ONLY, NOT AUTHORIZED.** Scoped 2026-08-05.

## Premise, one sentence

Every one of the 83 committed cases is single-shot, so the suite cannot see a model
contradict its own earlier correct answer — and that failure is the one a diary, a thread,
or any assistant with a memory actually commits.

## Why now, and why this rather than a fourth hard case

Two saturated exams (`reply-draft` 1.00; `crm-followup` 1.00 → 0.909 in PR #43, one failing
heldout case out of eleven) mean the suite still cannot **rank**. Adding another hard
single-shot case buys a fraction of a case.

**Multi-IF measured the alternative:** across 4,501 three-turn conversations in 8 languages,
**every model degrades with each turn** — `o1-preview` falls **0.877 → 0.707** from turn 1 to
turn 3. A frontier model losing 17 points to a regime our exams do not test is the strongest
available evidence about where ranking power is. CAPITU found the same shape independently
(conversation-level accuracy spread 60–96%).

**Two independent teams built this instrument and both report it discriminates.** That makes
it a measured regime, not a speculative one.

⚠️ **Neither result is ours.** They say the regime discriminates *for their models on their
tasks*. Step 0a exists to check it discriminates for **our** champion on **our** tasks before
any code is written.

## ⭐ Step 0a — the falsifier, and it runs BEFORE any code

**Claim to kill:** *our champion holds accumulated constraints across three turns as well as
it holds one, so the regime buys this suite nothing.*

**Cheapest test:** three hand-written 3-turn conversations, driven manually through
`router.py` with the history passed in the messages list. **No runner change, no cases.json,
no exam.** Each turn adds a constraint and keeps the previous ones:

```
turn 1  "Draft a reply to this email."                  -> C1: is a reply, grounded
turn 2  "Make it under 40 words."                       -> C1 still + C2: length
turn 3  "Don't mention the price."                      -> C1, C2 still + C3: forbidden
```

Then check **all** constraints at turn 3, not just the newest.

| outcome | action |
|---|---|
| champion holds all three at turn 3, all 3 conversations | ⛔ **STOP.** Regime is not binding here. Write it up, do not build. |
| champion drops an EARLIER constraint while satisfying the newest | ✅ build — that is exactly the drift this exam exists to catch |
| champion fails only the newest constraint | ⚠️ that is single-shot difficulty wearing a multi-turn costume. Re-scope, do not proceed. |

That third row is the one that would waste the lane, and it is the easiest to misread as
success. **A multi-turn exam that only ever fails on the newest constraint has measured
nothing a single-shot exam could not.**

⏱️ Cost: ~9 model calls, under an hour, zero code.

## The check that does not exist yet: `check_constraint_persistence`

The load-bearing check is not "did turn 3 satisfy turn 3's instruction". It is:

> **At turn N, do constraints C1..CN ALL still hold?**

**This is the vacuous-green trap for this design.** A checker that validates only the newest
constraint will pass, run, produce numbers, and measure exactly what a single-shot exam
measures. Same shape as `_exp` returning `{}` and `admit.py` accepting source-text tests —
the third instance this repo would have hit.

**Mechanical guard, written before any case:** build a model output by hand that satisfies C3
and violates C1, run it through the real scoring path, and assert it FAILS. Demonstrate RED.

## The second check: `check_no_self_contradiction` (E20's own failure mode)

Distinct from E10 rung A. Rung A is fabrication-from-*nothing* (invent a contact when a tool
dies). This is fabrication-from-*drift*: at turn 1 the model states a fact correctly from the
source; at turn 3 it states something incompatible with what it itself said.

Both turns can be individually plausible. Only the pair is wrong. ⚠️ This is the harder check
to build and the more likely to ship inert — treat it as the second deliverable, not the
first, and ship it dormant with a declared gap rather than tuning cases until it fires.

## Where it lands: extend `reply-draft`, do not create a sixth agent

Three reasons, in order:

1. **It is the saturated one that today's work did not touch.** `crm-followup` got partial-
   failure cases; `reply-draft` is still a flat 1.00 and is the harder of the two, because its
   1.00 comes from six checks a competent model simply passes.
2. **Drafting is naturally iterative.** "Now shorter", "now drop the price", "now keep the
   sign-off" is what actually happens to a draft — the register carries no explaining.
3. **Its checks are already deterministic and judge-free** (`check_word_limit`,
   `check_no_invented_numbers`, `check_signoff`, …). Constraint persistence can **reuse them
   per-turn** rather than inventing a parallel checking layer.

⚠️ **`evals/reply-draft/properties.py` is a `full`-tier `sensitivePaths` file → Claude lane,
not cline.** Case *volume* can be cline's once the checks exist and have been demonstrated RED.

## The cost nobody should discover mid-lane

**`runner.py` must learn a multi-turn case shape.** Today every case is `"input": "<string>"`
and `run_properties(props, input_text, output)` takes one string. A turns list means a new
case schema, a new execution path, and a checking loop over turns.

`sandbox/runner.py` is a **`full`-tier `sensitivePaths` file** — it scores every exam. A bug
there moves every committed score.

**Mitigation, and it is a hard requirement:** the multi-turn path must be **additive**. A case
with `"input"` behaves byte-identically to today. Pin that with a test asserting all five
existing exams' snapshots reproduce unchanged — the same discipline E22a used for the
`timeout`/`json_mode` knobs.

## Cost per run

3× the model calls per case. A 12-case exam is 36 calls; at the observed ~30 s/call on this
box that is **~20–30 minutes per full run**, versus ~5 for a single-shot exam. Acceptable, but
it makes `check-all` meaningfully slower and reinforces that `./.cline/test.sh` — not
`check-all` — is the build-lane gate.

## Non-goals

- **Importing Multi-IF or CAPITU data.** CAPITU is Apache-2.0 and usable
  (`docs/capitu-assessment-2026-08-05.md`); **Multi-IF's licence is unverified.** Borrow the
  *design*; author our own cases in our own domain. Revisit import only if authoring proves
  the bottleneck.
- **Portuguese.** The standing decision is instrument first, languages after, and the trigger
  is "when the suite can RANK again". This lane is *how* that trigger gets met, so it does not
  fire it. ⚠️ Note the market gap this research surfaced: EN and ES have public multi-turn
  coverage, **pt-PT has none** — a reason to keep the case format language-portable, not a
  reason to write Portuguese now.
- **More than 3 turns.** Both public benchmarks use 3. Match them; a longer horizon is a
  separate question once 3 discriminates.
- **A judge.** The suite is judge-free and stays so. Every constraint must define its own
  mechanical check — the CAPITU/IFEval pattern, `check(response) -> bool`.

## Kill criteria, pre-registered

1. **Step 0a shows no degradation across turns** for our champion → stop, write up, do not build.
2. **Failures land only on the newest constraint** → the exam is single-shot difficulty in a
   costume; re-scope.
3. **The multi-turn path moves any existing snapshot** → revert; the additive requirement failed.

## Deliverable order

1. Step 0a falsifier — hand-driven, no code, decides whether the rest happens
2. `check_constraint_persistence` + its RED demonstration, before any case
3. The `runner.py` turns schema, additive, with the five-snapshot regression test
4. Cases — a handful by hand to prove isolation, then volume by cline against the gate
5. `check_no_self_contradiction` — second, shipped dormant if it will not fire

⛔ Splits are operator-signed (audit C0). There is already one unresolved instance from PR #19
and a second pending in PR #43; do not add a third silently.
