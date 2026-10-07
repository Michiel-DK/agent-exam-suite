# agent-exam-suite

![last commit](https://img.shields.io/github/last-commit/Michiel-DK/agent-exam-suite)
![python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![eval cases](https://img.shields.io/badge/eval%20cases-220%20%28118%20held--out%29-2b8a7e)
![LLM judge](https://img.shields.io/badge/LLM%20judge-none%2C%20deterministic%20scoring-2b8a7e)
![tests](https://github.com/Michiel-DK/agent-exam-suite/actions/workflows/tests.yml/badge.svg)

**You do not need a frontier model for every task.** For most routine office jobs, a small open model that
passes the task's own exam does the work, on a laptop or in your own cloud, for about $0 in tokens. This repo is
the exam: the way to find out which model passes *your* task, what it costs, and how to know the day it gets worse.

Eight example tasks are in here (email triage, expense fields, weekly recap, reply drafts, CRM follow-up over
tool calls, call summaries, CRM fields from a call, request intake). Every model, local or hosted, sits the same
cases through the same entry point. Results: [**the October results page**](https://michiel-dk.github.io/agent-exam-suite/results-2026-10.html).

## How it works, in four steps

**1. Name the tasks you already send to a model.** Triage, extraction, drafting, summaries. The only requirement is
that a person can say, case by case, whether the answer was right. If nobody can check it, this suite will not
score it and says so.

**2. Write down what a correct answer looks like.** Twenty to forty cases per task, each with its checks: the label,
the fields, the facts that must appear, the tools that must be called. A third is held out and never tuned on.
Scoring is deterministic. No model grades another model's answer, anywhere. Every local case runs three times at
temperature 0 and counts only if all three agree.

**3. The cheapest model that passes wins.** Every candidate sits the exam. Models below the bar drop out. The bar is
the best score any model reached, or one case from it. The cheapest model left takes the job, and its score is
committed as the snapshot that every later change is checked against.

| CRM follow-up over tool calls, 18 held-out cases, 27 Sep 2026 | passed | $ per 10k tasks (2 Oct ledger) | runs on |
|---|---|---|---|
| Gemma 4 2B (local champion, 3-load snapshot) | 15 of 18 | ≈0 | your laptop |
| DeepSeek V4 Pro | 15 of 18 | 43 | GPU node |
| Gemma 4 31B | 14 of 18 | 5.41 | one 48 GB card |
| GPT-5.6-Sol | 14 of 18 | 127 | vendor API |

**4. A fine-tune ships only if it passes the same exam.** When a small model almost passes, it is fine-tuned on the
task's own training cases, on the machine it runs on, in minutes. Then it sits the exam. If any held-out case that
used to pass now fails, the new version is refused, even when the total went up. The gate has refused four CRM
fine-tunes and a no-training "thinking off" switch; one request-intake adapter held within a case (−87% output tokens,
4.2× faster, held-out 19 → 18 of 20, one pass) and was not promoted. The table is on the results page; the write-ups
are under `docs/probes/i0-*` and `i2*`.

Then the loop: every model release, runtime bump or price change re-sits the exam per case, and the report lists
what moved in both directions. On 2 Oct a runtime upgrade moved 1 of 220 cases, none held-out.

## Where the model runs

| tier | what it means | examples here |
|---|---|---|
| your laptop | small enough for a 16 GB machine; nothing leaves it; ≈$0 per task | Gemma 4 2B / 4B, Qwen3 8B |
| your own cloud | open weights on a GPU you rent or own; data stays in your account | Gemma 4 26B / 31B, Qwen3 14B, Mistral Small 24B, gpt-oss-20b; Kimi K3, GLM-5.3, DeepSeek V4 on a node |
| vendor API | closed weights, pay per call | GPT-5.6-Sol, GPT-5.4-mini, Grok 4.6 |

The score in a table was taken on the runtime the row names. A build on your own card re-sits the exam before the
row is claimed for it.

## What we measured (October 2026)

1. **A 2B–4B model on a laptop holds every short decision task and loses only long summaries.** Level with the hosted
   flagships on email triage, expense fields, reply drafts, the CRM brief over tool calls and the digest; one case
   behind on CRM field write-back, four behind on long call summaries. Local ≈ $0, open weights hosted $0.23–$5.41,
   the vendor flagship $5–$127 per 10k tasks (metered, 27 Sep matrix, 2 Oct ledger).
2. **Temperature zero is not determinism on hosted APIs.** GLM-5.3: 10/13 call summaries on one run, 6/13 across six
   same-day runs. The local champions pass every case on all three loads. Reproduce from the committed files, no model
   needed: `python3 docs/probes/pass3-column-2026-09-28/pass_k.py`.
3. **Four fine-tunes of the local champion, four refusals, the cause named**: an unmasked loss that was 95% tool payload,
   then a per-step cut that taught a "call again" reflex. Each killed by its pre-registered rule (`docs/probes/i2v*`).

The chart for all eight tasks, score against cost per 10k, is on the
[results page](https://michiel-dk.github.io/agent-exam-suite/results-2026-10.html); it is built from the committed
files by `scripts/build_results_page.py`, never drawn by hand. Three times the instrument itself was wrong, and what
fixed it: [`docs/post-mortems/`](docs/post-mortems/).

## Try it on your own task

```
pip install -r requirements.txt                       # requests, PyYAML; Ollama for local models
python3 sandbox/runner.py list                        # the eight example tasks, their champions
# 1. copy evals/email-triage/ to evals/<task>/; write cases.json (split: train | heldout) and the checks
python3 sandbox/runner.py diff <task> --models m1,m2   # 2. same cases, several models, one table
python3 sandbox/runner.py run <task> --snapshot        # 3. commit the winner: 3 loads at temperature 0
python3 sandbox/runner.py check <task>                 # 4. after any change: exit 1 if a stable case moved
python3 sandbox/runner.py run <task> --provider openrouter --model <id>   # a hosted model, same entry point
./.cline/test.sh                                      # the test gate: one process per file, exit code captured
```

Hosted providers need their key in the environment; nothing is read from a file. `pytest` runs in CI but is blind to
this repo's `check()`-style test files (post-mortem 3); the gate is `./.cline/test.sh`.

## Scoreboard

Held-out score of the committed champion per task, from `evals/<agent>/snapshot.json` at the 2026-10-07 repo state;
generated by the snapshot script, never typed.

| agent | exam mode | champion | held-out | snapshot date | note |
|---|---|---|---|---|---|
| reply-draft | properties | gemma4:e2b-it-qat | 1.000 (10/10) | 2026-10-02 | saturated, useless for ranking |
| task-intake | labels | gemma4:e2b-it-qat | 0.955 (21/22) | 2026-10-02 | seventh agent: routes a typed request to the right specialist, or refuses |
| email-triage | labels | gemma4:e2b-it-qat | 0.909 (10/11) | 2026-10-02 |  |
| expense-categorization | fields | gemma4:e2b-it-qat | 0.889 (8/9) | 2026-10-02 |  |
| crm-followup | trajectory | gemma4-e2b-ctx16k | 0.833 (15/18) | 2026-10-02 | production-size payloads; 4 multi-turn cases; champion swapped 4B to 2B (PR #60) |
| call-fields | fields | gemma4-e4b-ctx16k | 0.737 (14/19) | 2026-10-02 |  |
| recap | properties | gemma4:e4b-it-qat | 0.700 (7/10) | 2026-10-02 | the hardest exam, on purpose |
| transcript-en | properties | gemma4-e4b-ctx16k | 0.526 (10/19) | 2026-10-02 | English call transcripts incl. a 10-case long-call band (12k-33k chars); local 4B ties Kimi-K3 2/6 on it |

## Where to look

| folder | what is in it |
|---|---|
| [`docs/results-2026-10.html`](https://michiel-dk.github.io/agent-exam-suite/results-2026-10.html) | the page: three findings, the chart, the reproduce command |
| [`evals/`](evals/) | one exam per task: `cases.json` (train / held-out), deterministic checks, the committed 3-load snapshot |
| [`agents/`](agents/) | one folder per task: a prompt, a tool list, one model line; deliberately boring |
| [`docs/probes/`](docs/probes/) | the experiments behind every number; each `RESULTS.md` opens with the one cell that carries the verdict |
| [`docs/post-mortems/`](docs/post-mortems/) | three times the instrument was wrong: belief, probe, fix |
| [`sandbox/`](sandbox/) | `runner.py` (run · check · diff · snapshot · route), the provider router, the tests |

## Status and limits

**Status (2026-10-07):** 8 tasks, 220 committed cases (102 train / 118 held-out),
39 test files; judge-free and deterministic. Every snapshot is three fresh loads at temperature 0 with a
runtime stamp, so a runtime bump or a model swap re-sits the exam per case. Limits, stated plainly: held-out sets are
9–22 cases, so the suite ranks bad models out but cannot separate two good ones (the results table prints how many
candidates competed and calls a one-case gap noise); every case input is hand-authored. Getting real inputs in is the
active work.

> **Public snapshot (repo state 2026-10-07, published 2026-10-07).** A curated, sanitized cut of a private
> working repo: the tasks, the exams, the runner and the write-ups are the real working tree. Kept private on purpose:
> the per-lane build ledger, the build-harness submodule, the sprint queue, lane briefs, competitor notes, per-probe
> result archives, a task corpus mined from private production repos, and anything naming a client. Some links in the
> older write-up therefore point at files that are not in this snapshot. History: the August write-up that argued
> the case before the October matrix, [`docs/eval-suite-is-the-asset.md`](docs/eval-suite-is-the-asset.md), stays
> for the record; its numbers are from the 3 Sep repo state. A client's exam is never published; the
> exams here are demo exams on synthetic cases, and because their held-out cases are public, no routing decision is
> taken on them alone once a model could have seen them.
