# E-CORPUS create tasks, 2026-08-15 — the harness learns file creation, and the oracle rewrites the headcount

> Operator-authorized lane (the "new-module harness first" road, decided 2026-08-15).
> Extends `sandbox/replay/` to represent tasks where the PR CREATES a module, then re-runs
> admissibility and the oracle over the whole ≥80-line hard band. **Zero model calls** —
> this lane deliberately stops at the point where a local model would run.
>
> Raw results: `docs/e-corpus-results/admit_2026-08-15_hardband_shapes.json` (89 probes)
> and `docs/e-corpus-results/oracle_2026-08-15_all22.log` (all 22 oracle runs).

## Headline

**The gradeable hard-band pool is 15 tasks: 12 create + 3 modify.** Two corrections to
yesterday's picture, both in the honest direction:

1. **Create tasks work end-to-end, first try: the oracle is GREEN on 12/12.** The human's
   merged files, fed through the identical parse → write → pytest path the model will use,
   pass their own gating test in every admissible create task.
2. **Yesterday's "13 admissible" was an admissibility count, not a gradeability count** —
   the oracle had never been run over all 13. Run today, only **3/10** surviving modify
   tasks are gradeable end-to-end; 7 fail exactly the ledger-018 way (the PR's real diff
   also changed module-level constants/imports, which function-level splicing cannot
   represent — #1005, the documented example, is among the 7).

So the create shape is not just the bigger pool — **it is the better-behaved one**:
whole-file ground truth loses nothing at task-build time, function extraction demonstrably
does.

## The re-run funnel (89 hard-band behaviour candidates)

| verdict | n | note |
|---|---|---|
| admissible **create** | **12** | red is a collection error naming a module the PR adds |
| admissible **modify** | **10** | red is an ordinary test failure (rc=1), as before |
| **mixed** create+modify | **50** | dropped, counted — the future pool, needs a third task shape |
| invalid red | 17 | modify-shaped but the test cannot even collect at base |
| source-text | 0 | already filtered out of this band on 2026-08-14 |

Then the oracle: **12/12 create GREEN · 3/10 modify GREEN** (#795, #655, #369) → **15**.

### The falsifier's verdict on yesterday's 13

10 of the 13 reproduce unchanged. The other 3 (#680, #986, #988) are **reclassified
mixed**: each adds one source file and modifies others. The old admit could not see added
files, called them modify, and nobody noticed that `build_tasks.py` would have crashed on
`git show base:<added file>` — they were admissible on paper and unbuildable in practice.
Losing them from the modify column is a correction, not a regression.

### 84% was the wrong reading

Yesterday's sweep read "64 of 76 drops are ModuleNotFoundError" as one big new-module
pool. Shape-classified, most of that is **mixed** (50) — only 12 are pure create. The
dominant hard-band shape is "add a module AND touch existing files", which neither current
task format represents. That is the honest size of the remaining recoverable pool, and it
needs its own task shape (splice + create in one attempt) before it can be counted.

## What the code now does (PR'd with this doc)

- `admit.py` classifies every candidate `modify` / `create` / `mixed`
  (`git diff --diff-filter=A`), and a create red must be a collection error that **names a
  module this PR adds** — boundary-anchored, not substring: an added `…/social.py` cannot
  claim an error about `…/social_url`. That exact attacker input was built by hand first,
  seen RED against a substring version, and lives on as a committed check.
- `build_tasks.py` emits `create` records: paths to create + merged file sizes (so
  `MAX_TOKENS` can be scaled per task instead of silently truncating — the lesson that
  produced qwen3's zero on the old hard band). PR bodies are fetched per admissible PR via
  `gh`; the frozen selection artifacts are untouched.
- `attempt.py` speaks `### FILE: <path>` whole-file blocks for create tasks. The task
  record is the only authority on write locations — a hostile `### FILE: ../../evil.py`
  dies at parse, `apply_files` iterates the task's paths, never the model's keys, and a
  hostile task-record path raises before writing (all demonstrated RED in
  `sandbox/test_replay_splice.py`). Review round: body capture is per-header and greedy,
  so a file containing its own ```` ```python ```` docstring example is captured whole —
  the non-greedy version truncated it and the loss read as a model failure (seen RED,
  fixed, oracle re-run 12/12 GREEN through the new parser).
- `oracle.py create` grades every create task with the human's merged files. Staged
  s1–s5 grading is unchanged.
- +26 deterministic checks across `test_replay_admit_behaviour.py` /
  `test_replay_splice.py`; gate floor raised 477 → 503 in the same commit.

## What this licenses, and what it does not

✅ **Licensed:**
- A 15-task hard-band exam is buildable today, on owned hardware, no provider key —
  with the create tasks' N=12 alone nearly matching yesterday's entire (uncorrected) 13.
- "Write `mast/sales/triage.py` so this real CI test passes" is now a *graded* task
  shape, not a dropped failure code.

⛔ **Not licensed:**
- **No model result of any kind.** Zero model calls; the lane stops here by design.
  The next step is the local half of the Qwen ladder — separately authorized.
- **Not that 50 mixed tasks are recoverable** — that needs a third task shape
  (create + splice in one attempt) and its own oracle run. Untested.
- **Not that the modify column is done falling.** 3/10 gradeable is what the oracle says
  *today*, on this band; the 2026-08-14 easy-band oracle numbers are a different
  population.
- Same contamination rule as before: `mast` is Claude-authored — never Claude as the
  comparator model.

## Reproduce

```sh
export REPLAY_WORK=~/.cache/agent-sandbox-replay   # corpus + venv per sandbox/replay/README.md step 0
cd sandbox/replay
python3 build_candidates.py && python3 band_filter.py
python3 - <<'PY'                                   # stage the >=80-line band
import json, os
w = os.path.expanduser(os.environ.get("REPLAY_WORK", "~/.cache/agent-sandbox-replay"))
hard = [c for c in json.load(open(f"{w}/candidates_behaviour.json")) if c["lines"] >= 80]
json.dump(hard, open(f"{w}/candidates.json", "w"), indent=1)
PY
python3 -u admit.py            # 89 -> 22 admissible {modify: 10, create: 12}
python3 -u build_tasks.py      # 22 task records
python3 -u oracle.py create    # 12/12 GREEN
python3 -u oracle.py 808,1011,795,1005,655,369,769,771,602,658   # 3/10 GREEN
```

⚠️ Byte-identical reproduction of the selection step holds only while no further PR merges
in the corpus repo (live `gh` query — disclosed in `build_candidates.py`); the clone
already trails GitHub by 2 merges, counted as `merge_not_in_clone`.
