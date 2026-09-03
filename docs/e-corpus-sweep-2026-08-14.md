# E-CORPUS full-corpus sweep, 2026-08-14 — replay clears its bar by 1, and the hard band turns out to be a different exam

> Read-only probe, main loop. **Nothing committed to `sandbox/` or `evals/`; no committed score
> moved.** Answers the question the 2026-08-01 probe left open: *are there enough gradeable
> tasks in the band that actually discriminates?*
>
> Raw results: `docs/e-corpus-results/{candidates_2026-08-14_full,
> candidates_2026-08-14_behaviour,admit_2026-08-14_hardband}.json`.

## Headline

**13 admissible hard-band tasks.** The brief's success criterion was **≥12**. It clears by one.

And the 76 drops are not noise — **they are a second, larger exam wearing a failure code.**

## The funnel, each step measured

| step | filter | left |
|---|---|---|
| merged PRs (GitHub, `gh pr list --state merged`) | — | **1,150** |
| touches ≥1 `tests/unit/*.py` **and** 1–3 source `.py` | mechanical | **261** |
| test grades **behaviour**, not source text | `admit.grades_source_text`, pure fn | **125** |
| in the discriminating band (≥80 added source lines) | probe 2026-08-01 | **89** |
| reproduces **red→green** at its base commit | `admit.probe`, 2 pytest runs each | **13** |

Admissible by band: **9 medium** (80–199 lines) · **4 long** (≥200).

⚠️ **A count that does not reconcile, stated rather than smoothed.** The 2026-08-01 probe says
*"250 of 1,907 PRs"*; `gh` reports **1,150 merged** today. 1,907 was plausibly all PRs including
closed/unmerged, but that is a guess — **the earlier number is not reproduced here and should
not be quoted alongside this one** until someone checks which population it counted.

## ⭐ The real finding: the hard band is dominated by *new-module* PRs

75 of the 76 drops failed RED with `rc=2` — a pytest **collection** error, not an assertion
failure. Verified rather than assumed, by classifying every tail:

| cause | count |
|---|---|
| `ModuleNotFoundError` / `ImportError` — the module does not exist at base | **64** |
| other collection errors | 11 |
| `green_rc=1` — test fails even at the merge commit (PR #856, order-dependent routing test) | 1 |

Sample: `ModuleNotFoundError: No module named 'mast.utils.social_url'`.

**Why this happens is structural, and it inverts the plan.** Small PRs *modify* a function; big
PRs *create a module*. So the harder the band, the more the corpus stops being "patch this
function" and becomes "write this file from scratch." The 2026-08-01 probe saw this as 2 drops
out of 8 and correctly called it *"a different task shape, recoverable later"*. At hard-band
scale it is **84% of the band** — the dominant shape, not an edge case.

⛔ **So "76 dropped" must not be read as "76 unusable."** 64 of them are a coherent, larger task
pool that the current harness cannot *represent* — `build_tasks.py` splices a function into an
existing file and has no way to express "this file should not exist yet."

### And that shape is a better fit for the stated goal

The goal driving this lane is *how close are local models to frontier at writing real code*.
"Write `mast/utils/social_url.py` so that this real test passes" is a **stronger** test of that
than "rewrite this one function", and there are ~5× as many of them. Grading is unchanged and
still free: the PR's own CI test is the grader.

## What this licenses, and what it does not

✅ **Licensed:**
- Replay is buildable as an exam **today**, on hardware already owned, with no provider key.
- 13 tasks clears the pre-registered bar. 9 medium / 4 long is a real spread.
- The behaviour filter is load-bearing: it removed **136 of 261** (52%), close to the
  documented 45% base rate — those would have graded transcription and reported it as coding.

⛔ **Not licensed:**
- **Not** that 13 is comfortable. It clears by **one**, and the earlier band's 75% admission
  rate (6/8) collapsed to **15%** here. Any further tightening drops below the bar.
- **Not** that the 64 new-module tasks are usable — they are **untested** in that shape.
  `build_tasks.py` and `attempt.py` would need to express file *creation*, and the oracle must
  be re-run before any of it is trusted (a harness that cannot create a file would score every
  model 0 and look like incapacity — the exact confusion this harness exists to prevent).
- **Not** a model result of any kind. **Zero model calls were made in this sweep.**

## Contamination — unchanged and still binding

`mast` is Claude-authored. A Qwen or gemma candidate is a different family, so no self-replay.
⛔ **A Claude candidate carries a fair same-family objection** and must be flagged in any
outward claim — which is why a Qwen ladder (local 8B/14B vs a hosted large Qwen) is the clean
head-to-head design, not Claude-as-frontier.

## Reproduce

Corpus + venv per `sandbox/replay/README.md` step 0. Then:

```sh
export REPLAY_WORK=~/.cache/agent-sandbox-replay
python3 "$REPLAY_WORK/build_candidates.py"   # 1,150 PRs -> 261 candidates, banded by added lines
python3 "$REPLAY_WORK/band_filter.py"        # -> 125 behaviour-graded
# stage the >=80-line survivors as $REPLAY_WORK/candidates.json, then:
cd sandbox/replay && python3 -u admit.py
```

⛔ **`build_candidates.py` and `band_filter.py` are NOT in the repo.** The committed harness
starts at `admit.py`, which *reads* `candidates.json` — selection was never committed
(`README.md` step 1 says "see the probe doc for the query"). They were written for this sweep
and parked in `$REPLAY_WORK`, which is disposable. **Committing `build_candidates.py` into
`sandbox/replay/` is the next PR**; until then this sweep is not reproducible from a clean
clone, which is the same preservation gap PR #38 existed to close.

## What to decide next

1. **Build the 13-task exam as scoped** — clears the bar, no new harness work, no key.
2. **Or extend the harness to new-module tasks first** — ~5× the corpus, better matches the
   goal, but it is real work on `build_tasks.py`/`attempt.py` plus an oracle re-run.

(2) is the better exam and the slower road. (1) is available now and its N is thin.
**Not authorized either way** — a finding is not consent.
