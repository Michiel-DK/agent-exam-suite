# Post-mortem 2 — The gate said ok while five verdicts moved (31 August – 7 September 2026)

**What we believed.** The regression gate compared a fresh run's held-out score with the committed snapshot and exited 1 on a
drop. Green meant nothing had moved. The gate had been green for a week.

**What the probe showed.** A runtime upgrade (Ollama 0.33.2, 31 August) had moved 5 of 22 verdicts on the call-summary exam —
in **opposite directions**, so the aggregate score was unchanged and the gate printed `ok` every day. An aggregate gate is blind
to cancelling flips, and a runtime bump is a silent re-roll of every verdict.

**What changed (rule A).** A snapshot is now three fresh model loads at temperature 0; a case is *stable* only if all loads
agree, otherwise it is exempt. The snapshot carries the runtime name and version. The gate refuses before any inference on a
changed runtime version or a changed case set, then fails on **any stable case moving in either direction**. The pre-registered
prediction for the measurement that justified it — "at least one unstable case on the call-summary exam" — was **refuted**:
174 cases × 4 loads, 0 unstable. The instrument was justified by the finding it confirmed (per-case divergence hidden by the
aggregate), not by the one it predicted. On 2 October the next runtime upgrade re-sat all 8 exams through this gate: 1 of 220
cases moved, a training case, 0 held-out — this time the gate could say so per case.

**A defect inside the fix.** The test that demonstrated the old gate's blindness ran the pre-fix code by reading it from the
main branch — correct while the change was open, and the fix itself the moment it merged. Four reviewers and the author missed
it; the main branch went red on the merge commit. The test now pins the old code by its content hash and says `[SKIP]` loudly
when the history is absent, as it is in this public clone.

**The transferable rules.** A gate must compare per case, never per aggregate. A test that names "the old code" by a moving
reference is right exactly until it merges. A deterministic gate must never reach a live server or evict a model, so every
test that drives the CLI stubs those seams, seen red first.
