# Replay harness — real merged PRs, graded by the CI tests that shipped

**Status: PROBE APPARATUS, not an exam.** No `evals/replay/cases.json` exists, nothing here is
wired into `runner.py`, and no committed score depends on it. It produced
`docs/e-corpus-probe-2026-08-01.md` and is preserved so that session's work is reproducible.
**"No exam, no agent" is not violated because there is no agent** — this is a measuring
instrument in its own right.

## What it does

Takes a merged PR from a real repo, rewinds to the commit it branched from, asks a model to
make the change, and grades it with **the test that actually gated that PR in CI**. Ground
truth is free: nobody labelled anything, CI already did.

## Run it in order

```sh
export REPLAY_WORK=~/.cache/agent-sandbox-replay      # holds the clone + venv + intermediates

# 0. prerequisites: the `gh` CLI, authenticated with access to the corpus repo
#    (step 1's merged-PR list is a live GitHub query), plus corpus + a venv that
#    reproduces the target repo's CI exactly.
#    For `mast` this is .github/workflows/test.yml's `unit-tests` job (service-free):
mkdir -p "$REPLAY_WORK" && git clone git@github.com:Michiel-DK/mast.git "$REPLAY_WORK/mast"
python3.12 -m venv "$REPLAY_WORK/venv"
"$REPLAY_WORK/venv/bin/pip" install pytest httpx google-genai beautifulsoup4 lxml \
    tldextract python-dateutil
"$REPLAY_WORK/venv/bin/pip" install -e "$REPLAY_WORK/mast" --no-deps

# 1. selection: every merged PR touching >=1 unit-test file and 1–3 source files,
#    banded by added source lines, then the cheap behaviour-not-source-text filter.
#    Both write into $REPLAY_WORK; nothing generated is committed.
python3 build_candidates.py                # -> $REPLAY_WORK/candidates.json (full corpus)
python3 band_filter.py                     # -> $REPLAY_WORK/candidates_behaviour.json
#    Pick the band you want (the >=80-line bands are the ones that discriminate),
#    stage those survivors back as $REPLAY_WORK/candidates.json — admit.py reads that.
# 2. which candidates reproduce red->green at their base commit
python3 admit.py
# 3. turn admissible PRs into tasks (prompt pieces + ground truth)
python3 build_tasks.py
# 4. ⛔ ALWAYS BEFORE ANY MODEL CALL — can the harness grade a KNOWN-GOOD answer?
python3 oracle.py 973,941,937
# 5. only now spend model calls
MAX_TOKENS=14000 python3 attempt.py qwen3-8b-ctx16k 973,941,937 myrun
```

Model calls go through the repo's real `sandbox/router.py` adapter, never a hand-rolled HTTP
call — rule A4, measure through the real entry point.

## The three things that made the probe's numbers trustworthy

**1. `oracle.py` runs before any model call.** It feeds the *human's own merged functions*
through the model's identical parse → apply → pytest path. If a known-correct answer cannot
score green, the harness cannot grade, and a model's zero would be uninterpretable. It earned
this on the first run: PR #1005 came back RED (its real diff also changed module-level
constants the function-extraction format cannot represent) and was **dropped rather than
debugged**. Without the oracle it would have been reported as model incapacity.

**2. Grading is staged, never binary.** `s1 responded → s2 parsed → s3 compiles → s4 gating
test → s5 no regression`. A bare 0/3 is an aggregate with no cause (rule A3), and the stages
are what let each zero be attributed:
- `s5` caught PR #937 **passing its own gate while breaking four other tests** — a binary score
  calls that a clean win.
- `s2` vs `s4` separated "the model never produced an answer" from "the model produced wrong
  code", which route in opposite directions.

**3. `MAX_TOKENS` must scale with the answer length asked for, and is recorded per attempt.**
A fixed cap silently converts long-answer tasks into parse failures. This bit for real: at
4,000 tokens both models scored 0 on PR #1008; at 14,000 `gemma4:e4b` **passes** it while
`qwen3:8b` still emits zero answer characters. **One budget had merged two opposite causes.**
Never attribute a zero without re-running at a larger budget.

## Known limits — read before extending

- **Task format is FUNCTION-LEVEL.** Tasks are built by extracting the top-level functions the
  human's diff touched. A PR that also changes module-level constants, imports, or adds a new
  file **cannot be represented** — the oracle detects these; do not work around it by hand.
- **The spec is deliberately generous** — PR title + body + the gating test verbatim + the
  exact functions to change. That hands over localisation, and the test file often contains
  the fix's key tokens, so a pass measures *test-guided implementation*, not derivation.
- **Corpus property that limits what any of this measures:** 172 of `mast`'s 384 unit-test
  files assert on **source text** (`read_text()` / `inspect.getsource` / `REPO_ROOT`) rather
  than behaviour. Some "regressions" are lost source shape, not broken code.
- **The easy band is ceiling-saturated.** Three local models tie at 2/3 on small-diff tasks.
  Build any real exam from the **long-function** band — that is where separation appeared.
- **Never point `REPLAY_REPO` at a working copy you use.** It checks out old commits and
  hard-resets. ~4 sessions run in parallel here; the clone under `$REPLAY_WORK` is disposable
  on purpose.
