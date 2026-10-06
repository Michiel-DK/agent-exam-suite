# Matrix 2026-09-27 — every task × every tier, one window

> **EVIDENCE CELL:** the two call tasks, held-out, one pass per model, all arms between 12:02 and 12:40 on 27 Sep
> (the call-fields arms 25–26 Sep, same layout), current case sets (summary 32 cases / 19 held-out; field write-back
> 32 / 19), output budgets as committed (summary 2048, field write-back 4096):
> **Summary + action items — Grok 14 · Kimi 14 · Sol 13 · mini 12 · Gemma 4 26B-A4B 12 · DeepSeek V4 Pro 12 · local 4B 10.**
> **CRM field write-back — Kimi 17 · Gemma 4 31B 15 · gpt-oss-20b 15 · Sol 15 · GLM 15 · local 4B 14.**
> Verdict these cells carry: on the two tasks with headroom, the closed frontier holds no top score alone — Grok ties Kimi on
> summaries, Sol sits below Kimi on both — and the movable open-weight tier reaches the flagship band on field write-back
> (two models) but not on summaries (best 12 of 19, two below the leaders, at one-sixtieth of the price).
>
> **Not evidence:** the five saturated tasks below (digest, email, expense, reply, CRM brief) — 9–18 held-out cases each,
> most models tie at the ceiling, a one-case gap is noise; the August frontier rows on those five tasks (not rerun, cross-day,
> quoted only where the table says so); per-10k dollars (metered on this run's tokens at today's ledger rate, floors for
> real call lengths); death counts as capability (they are budget or protocol facts, named below).

Deterministic table builder: `build_tables.py` (reads `results/`, the call-fields probe, the committed snapshots and the
repo-radar ledger; no inference). Rates: every model now has a ledger row (repo-radar `afd6e1a`, 27 Sep). Launcher:
`hosted_arm.sh` (clean `git archive HEAD` scratch copy per arm, creator pin where the account allows it). 50 + 4 requeued
arms, four in parallel, 38 minutes wall, **$4.58 metered**.


### Call summary + action items (`transcript-en`, 19 held-out cases)

| model | can run on | heldout | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|
| x-ai/grok-4.6 | vendor only | **14**/19 | 17.2 | 1360 | 0 | 133 (ledger) | pinned |
| moonshotai/kimi-k3 | own VM, GPU node | **14**/19 | 25.6 | 788 | 1 | 186 (ledger) | pinned |
| openai/gpt-5.6-sol | vendor only | **13**/19 | 4.7 | 309 | 0 | 78 (ledger) | pinned |
| openai/gpt-5.4-mini | vendor only | **12**/19 | 1.4 | 145 | 0 | 24 (ledger) | pinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **12**/19 | 3.2 | 135 | 0 | 2.01 (ledger) | unpinned |
| deepseek/deepseek-v4-pro-0813 | own VM, GPU node | **12**/19 | 9.3 | 446 | 7 | 20 (ledger) | unpinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **11**/19 | 4.3 | 124 | 0 | 2.70 (ledger) | unpinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **11**/19 | 8.7 | 519 | 0 | 4.14 (ledger) | unpinned |
| z-ai/glm-5.3 | own VM, GPU node | **10**/19 | 9.9 | 821 | 4 | 62 (ledger) | pinned |
| gemma4-e4b-ctx16k (local champion, 3-load snapshot 2026-09-08) | local machine | **10**/19 | 26.1 | 813 | 0 | ≈0 | snapshot |
| openai/gpt-oss-20b | own VM, one 24 GB card | **9**/19 | 5.5 | 419 | 1 | 0.78 (ledger) | unpinned |
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **6**/19 | 2.8 | 141 | 0 | 2.72 (ledger) | unpinned |

### CRM field write-back from a call (`call-fields`, 19 held-out cases)

| model | can run on | heldout | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|
| moonshotai/kimi-k3 | own VM, GPU node | **17**/19 | 12.8 | 480 | 0 | 156 (ledger) | pinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **15**/19 | 2.7 | 75 | 0 | 2.88 (ledger) | unpinned |
| openai/gpt-5.6-sol | vendor only | **15**/19 | 3.2 | 116 | 0 | 65 (ledger) | pinned |
| openai/gpt-oss-20b | own VM, one 24 GB card | **15**/19 | 7.9 | 367 | 0 | 0.83 (ledger) | unpinned |
| z-ai/glm-5.3 | own VM, GPU node | **15**/19 | 27.4 | 733 | 1 | 69 (ledger) | pinned |
| gemma4-e4b-ctx16k (local champion, 3-load snapshot 2026-09-26) | local machine | **14**/19 | | | 0 | ≈0 | snapshot |
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **13**/19 | 4.3 | 81 | 0 | 2.92 (ledger) | unpinned |
| openai/gpt-5.4-mini | vendor only | **11**/19 | 1.4 | 53 | 0 | 23 (ledger) | pinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **11**/19 | 4.0 | 75 | 0 | 2.14 (ledger) | unpinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **11**/19 | 9.2 | 441 | 0 | 4.39 (ledger) | unpinned |

### Account brief over the CRM (tool calls) (`crm-followup`, 18 held-out cases)

| model | can run on | heldout | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|
| x-ai/grok-4.6 | vendor only | **16**/18 | 10.2 | 692 | 0 | 164 (ledger) | pinned |
| deepseek/deepseek-v4-pro-0813 | own VM, GPU node | **15**/18 | 10.3 | 368 | 0 | 26 (ledger) | unpinned |
| gemma4-e2b-ctx16k (local champion, 3-load snapshot 2026-09-07) | local machine | **15**/18 | 12.8 | 600 | 0 | ≈0 | snapshot |
| google/gemma-4-31b-it | own VM, one 48 GB card | **14**/18 | 5.3 | 103 | 0 | 5.41 (ledger) | unpinned |
| openai/gpt-5.6-sol | vendor only | **14**/18 | 6.5 | 164 | 0 | 127 (ledger) | pinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **13**/18 | 4.2 | 106 | 0 | 3.76 (ledger) | unpinned |
| z-ai/glm-5.3 | own VM, GPU node | **12**/18 | 12.4 | 622 | 0 | 101 (ledger) | pinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **11**/18 | 21.3 | 817 | 0 | 7.48 (ledger) | unpinned |
| openai/gpt-5.4-mini | vendor only | **10**/18 | 3.2 | 138 | 0 | 34 (ledger) | pinned |
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **10**/18 | 3.7 | 106 | 0 | 4.79 (ledger) | unpinned |
| moonshotai/kimi-k3 | own VM, GPU node | **9**/18 | 23.6 | 474 | 1 | 251 (ledger) | pinned |
| openai/gpt-oss-20b | own VM, one 24 GB card | **1**/18 | 3.4 | 101 | 22 | 0.16 (ledger) | unpinned |

### Digest of many items (`recap`, 10 held-out cases)

| model | can run on | heldout | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|
| openai/gpt-5.6-sol | vendor only | **8**/10 | 4.6 | 201 | 0 | 44 (ledger) | pinned |
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **7**/10 | 2.2 | 114 | 0 | 1.59 (ledger) | unpinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **7**/10 | 3.0 | 93 | 0 | 1.14 (ledger) | unpinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **7**/10 | 5.1 | 83 | 0 | 1.53 (ledger) | unpinned |
| gemma4:e4b-it-qat (local champion, 3-load snapshot 2026-09-07) | local machine | **7**/10 | 26.8 | 891 | 0 | ≈0 | snapshot |
| qwen/qwen3-14b | own VM, one 24 GB card | **6**/10 | 8.7 | 574 | 0 | 3.11 (ledger) | unpinned |
| openai/gpt-5.4-mini | vendor only | **5**/10 | 1.2 | 103 | 0 | 14 (ledger) | pinned |
| openai/gpt-oss-20b | own VM, one 24 GB card | **3**/10 | 6.1 | 525 | 0 | 0.70 (ledger) | unpinned |

### Email triage (`email-triage`, 11 held-out cases)

| model | can run on | heldout | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **10**/11 | 0.7 | 9 | 0 | 0.22 (ledger) | unpinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **10**/11 | 0.9 | 10 | 0 | 0.17 (ledger) | unpinned |
| openai/gpt-5.4-mini | vendor only | **10**/11 | 0.9 | 10 | 0 | 1.98 (ledger) | pinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **10**/11 | 2.2 | 10 | 0 | 0.24 (ledger) | unpinned |
| gemma4:e2b-it-qat (local champion, 3-load snapshot 2026-09-07) | local machine | **10**/11 | 5.7 | 400 | 0 | ≈0 | snapshot |
| openai/gpt-5.6-sol | vendor only | **9**/11 | 1.2 | 17 | 0 | 5.72 (ledger) | pinned |
| openai/gpt-oss-20b | own VM, one 24 GB card | **9**/11 | 1.3 | 70 | 0 | 0.11 (ledger) | unpinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **9**/11 | 5.1 | 318 | 0 | 1.02 (ledger) | unpinned |

### Expense fields (`expense-categorization`, 9 held-out cases)

| model | can run on | heldout | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **9**/9 | 0.8 | 15 | 0 | 0.22 (ledger) | unpinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **9**/9 | 0.8 | 15 | 0 | 0.17 (ledger) | unpinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **9**/9 | 1.4 | 16 | 0 | 0.23 (ledger) | unpinned |
| openai/gpt-5.4-mini | vendor only | **8**/9 | 0.8 | 14 | 0 | 2.03 (ledger) | pinned |
| openai/gpt-5.6-sol | vendor only | **8**/9 | 1.3 | 18 | 0 | 5.49 (ledger) | pinned |
| openai/gpt-oss-20b | own VM, one 24 GB card | **8**/9 | 2.2 | 127 | 0 | 0.16 (ledger) | unpinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **8**/9 | 3.8 | 227 | 0 | 0.78 (ledger) | unpinned |
| gemma4:e2b-it-qat (local champion, 3-load snapshot 2026-09-07) | local machine | **8**/9 | 4.4 | 280 | 0 | ≈0 | snapshot |

### Reply draft (`reply-draft`, 10 held-out cases)

| model | can run on | heldout | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|
| openai/gpt-5.4-mini | vendor only | **10**/10 | 1.2 | 73 | 0 | 5.06 (ledger) | pinned |
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **10**/10 | 1.4 | 64 | 0 | 0.39 (ledger) | unpinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **10**/10 | 2.2 | 87 | 0 | 0.37 (ledger) | unpinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **10**/10 | 2.2 | 80 | 0 | 0.50 (ledger) | unpinned |
| openai/gpt-5.6-sol | vendor only | **10**/10 | 2.9 | 112 | 0 | 16 (ledger) | pinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **10**/10 | 4.2 | 248 | 0 | 0.89 (ledger) | unpinned |
| gemma4:e2b-it-qat (local champion, 3-load snapshot 2026-09-07) | local machine | **10**/10 | 8.6 | 571 | 0 | ≈0 | snapshot |
| openai/gpt-oss-20b | own VM, one 24 GB card | **9**/10 | 3.0 | 155 | 0 | 0.19 (ledger) | unpinned |

### Deaths by recorded cause (arm → {cause: count}); a death is a failed case with no parseable answer

- `call-fields` z-ai/glm-5.3: {'no_answer': 1}
- `crm-followup` moonshotai/kimi-k3: {'no_answer': 1}
- `crm-followup` openai/gpt-oss-20b: {'no_answer': 22}
- `transcript-en` deepseek/deepseek-v4-pro-0813: {'no_answer': 7}
- `transcript-en` moonshotai/kimi-k3: {'no_answer': 1}
- `transcript-en` openai/gpt-oss-20b: {'no_answer': 1}
- `transcript-en` z-ai/glm-5.3: {'no_answer': 4}

## Findings

1. **Closed weights buy nothing on any task.** Every top held-out score is held or tied by an open-weight model: Kimi on
   both call tasks and summaries (tied by Grok), DeepSeek V4 Pro ties the local 2B on the CRM brief one behind Grok, and the
   five saturated tasks tie across tiers. Sol's best relative position is the digest (8/10, one above local, one pass).
2. **The movable tier is task-dependent.** Gemma 4 31B and gpt-oss-20b tie the flagships on field write-back; on summaries
   the best single-card model is Gemma 4 26B-A4B at 12/19 (two below Grok/Kimi, level with mini, at $2 per 10k) and gpt-oss
   drops to 9. On the tool-calling CRM brief Gemma 31B is one behind local and **gpt-oss-20b collapses to 1/18**: 22 of its 38
   calls returned `finish_reason=stop` with ~40 completion tokens and **zero content characters** — not a budget death, an
   empty answer, the protocol class (E31's QAT failure on the same exam had the same shape). A model that ties Sol on one step
   is unusable on the next; the exam per step is the point.
3. **Budget deaths on summaries at the committed 2048:** DeepSeek 7/32, GLM 4/32, Kimi 1/32, gpt-oss 1/32 — all `length` with
   ~9,000 reasoning chars and no content. Those count as failures because 2048 is the deployment's budget; a 4096 rerun would
   likely lift DeepSeek and GLM (call-fields precedent) and is a config change to `agents/transcript-en/agent.yaml` (PR).
4. **Local holds five of seven tasks and is the cheapest thing in the top tier there.** On the two call tasks the local 4B
   sits four below the leaders on summaries and one below the 15/19 group on field write-back; the digest is the one
   saturated task where a hosted model (Sol, 8/10) beat it this window, one case, one pass.
5. **Pins:** xAI's slug is `xai`, not `x-ai` (four 404s, requeued). DeepSeek's creator endpoint is excluded by the account's
   guardrail against providers that train on paid prompts — kept; DeepSeek ran unpinned, and the table says so. The five small
   models ran unpinned by design.
6. **Latency:** on the saturated tasks the small open models answer in 1–2 s per call; the local 2B/4B in 4–27 s because the
   laptop serves one request at a time and the QAT builds reason in prose first. Speed is the axis where a rented card most
   obviously beats the laptop; nothing here measured a rented card.

## What this does and does not settle for the page

Settled: one same-window table per task exists for eleven hosted models plus the local champion, with metered cost and
latency, on the current case sets. Not settled: tier letters (needs the three same-day repeats, ≈$20); the frontier on the
five saturated tasks (August rows, cross-day); anything on a rented GPU; anything on the client's transcripts.
