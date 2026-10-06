# call-fields — first hosted pass (2026-09-25)

> **EVIDENCE CELL:** the four hosted arms on the 19 held-out cases under the committed 4096-token
> output budget, one pass each, same afternoon, provider pinned to the creator endpoint:
> **Kimi K3 17/19 · GPT-5.6-Sol 15/19 · GLM-5.3 15/19 · GPT-5.4-mini 11/19.**
> Verdict this cell carries: on CRM field extraction from a call transcript, the hosted flagships
> miss one held-out call in five or better, and 13 of their 15 held-out misses are the
> `next_step_date` field. **Local row added 26 Sep 11:51:** the 4B champion, 3 fresh loads, 0 of 32
> unstable, **14/19 held-out**, one call behind the 15/19 group and three behind Kimi, at ≈$0.
>
> **Not evidence:** the 1024-budget first passes of GLM (7 deaths) and Kimi (2 deaths) — diagnostic
> for the budget finding below, superseded by the reruns; the local champion's train-split smoke —
> train is the iteration split, not the reported one; per-10k dollar figures — metered on THIS
> run's tokens at today's ledger rates, not on the lead's call lengths.

## Table (all 32 cases, one pass; `results/hosted-*.json`; rates `repo-radar data/prices/ledger.tsv` 2026-09-25)

| arm | budget | train | heldout | died | mean s/call | max s/call | out tok/call | $/pass | $/10k calls (metered) |
|---|---|---|---|---|---|---|---|---|---|
| Kimi K3 (rerun) | 4096 | 12/13 | **17/19** | 0 | 12.8 | 33.9 | 480 | 0.50 | 156 |
| GPT-5.6-Sol | 1024* | 12/13 | 15/19 | 0 | 3.2 | 6.9 | 116 | 0.21 | 65 |
| GLM-5.3 (rerun) | 4096 | 11/13 | 15/19 | 1 | 27.4 | 107.6 | 733 | 0.22 | 69 |
| GPT-5.4-mini | 1024* | 9/13 | 11/19 | 0 | 1.4 | 3.3 | 53 | 0.07 | 23 |
| **Gemma 4B local, 16k window (champion, rule-A snapshot 26 Sep)** | 4096 | 10/13 | **14/19** | 0 | 20.2 | 27.1 | 598 | 0 | ≈0 |
| Kimi K3 (first pass) | 1024 | 12/13 | 16/19 | 2 | 13.0 | 24.5 | 375 | 0.43 | 133 |
| GLM-5.3 (first pass) | 1024 | 9/13 | 15/19 | 7 | 17.6 | 57.6 | 349 | 0.14 | 44 |

\* ran before the budget change; never reached the 1024 ceiling (`truncated_calls` 0, no
`finish_reason=length`), so the number stands under either budget. Latency is per request as
measured by the runner; the four first-pass arms ran in parallel, the reruns sequentially.

## Findings

1. **The budget is a precondition, like the window.** GLM-5.3 and Kimi K3 reason before the JSON;
   at `max_tokens` 1024 GLM spent the whole budget thinking on 7 of 32 calls (`finish_reason=length`,
   1024 completion tokens, 0 content chars, ~4,200 reasoning chars) and Kimi on 2. Committed budget
   is now 4096 (`agents/call-fields/agent.yaml`, with the evidence). At 4096 GLM still died once:
   `longcall-renewal-train-1`, 17,218 reasoning chars. A verdict on a reasoning model is a verdict
   about the budget until the budget is stated.
2. **Almost every remaining miss is one field.** Held-out misses at 4096 across Kimi, Sol, GLM:
   `next_step_date` 8 of 10; the other 2 are the same case (`longcall-mixed-heldout-3`: `49`, the
   per-seat rate, for `2058`, the monthly total — both flagships). Mini's misses are different in
   kind: 9 of 20 are a ROLE written as decision maker (`our CFO`, `ops director`) against the
   named-person rule, and it wrote a disputed invoice amount (`1284.50`) into the deal field on
   `support-heldout-long` — the abstention the field exists to test.
3. **The `next_step_date` misses split into two classes, and the exam should say which is which.**
   Token-form variants of the committed label: `in three business days` / `three business days`
   (Kimi, Sol), `next Tuesday` / `Tuesday` (Kimi first pass, GLM), `tomorrow morning` / `tomorrow`
   (Kimi rerun, GLM), `by next Wednesday` / `next Wednesday` (mini). Rule disagreements: `Fridays`
   (the moved recurring call) for `next quarter` on the quiet check-in (Kimi, Sol, mini);
   `end of week` for `today` on `longcall-scoping-heldout-1` (Sol, GLM, mini). The first class is
   instrument strictness (declared in `not_verified`; a leading `in`/`by` or trailing `morning`
   would be a one-line normalisation, NOT done, because it is directional and needs its own red
   case); the second is the rule as written, applied.
4. **Same-day rerun variance, Kimi:** 2 of 32 verdicts flipped between the two passes
   (`discovery-heldout-easy` fail→pass, `support-medium-train` pass→fail), both on `next_step_date`,
   both token-form. Consistent with gotcha 14's 0–4 band.
5. **Speed.** Sol is the fastest model that scores in the top band (3.2 s/call); the reasoning
   models and the local 4B sit at 13–27 s/call. The local model's held-out score decides whether
   ≈$0 buys the same band; that run is `run-overnight.sh`.

## Local champion — rule-A snapshot (26 Sep 11:18–11:51, Ollama 0.33.2, budget 4096)

`run call-fields --snapshot`: three fresh loads, every case identical across loads (unstable 0/32).
**Train 10/13, held-out 14/19**, 20 s/call, 598 output tokens/call (the 4B reasons in prose before the
JSON). Held-out misses, all five: `discovery-heldout-easy` (`next Tuesday` for `Tuesday`),
`longcall-scoping-heldout-1` (`end of week` for `today`), `longcall-pricing-heldout-1` (`CFO`, a role),
`mixed-heldout-dense` (`Dov`, a named non-approver), `discovery-heldout-long` (`Meredith`/`end of day`,
the contested label). Two date-token misses shared with the flagships, two decision-maker misses shared
with the small models, one contested label shared with every small model. Train moved 9 → 10 after the
25 Sep prompt clarifications (monthly-over-annual, role-is-not-a-name, unnamed competitor).

## Local ladder (26 Sep 11:51–13:15, one load each, laptop, Ollama 0.33.2, budget 4096)

| arm | window | heldout | died | mean s/call | out tok/call | passes a case the champion fails |
|---|---|---|---|---|---|---|
| gemma4-e4b-ctx16k (champion, QAT, 3 loads) | 16k | **14/19** | 0 | 20.2 | 598 | — |
| qwen3-8b-ctx16k | 16k | 12/19 | 1 (longcall-renewal-heldout-2) | 39.2 | 637 | 3 (2 held-out) |
| gemma4-e2b-ctx16k | 16k | 11/19 | 0 | 14.8 | 793 | 1 |
| gemma4-e4b-ctx16k-plain (Q4_K_M, not QAT) | 16k | 11/19 | 0 | 9.1 | 93 | 0 |
| qwen3:14b (stock tag) | **4,096** | 10/19 | 10: all 9 longcall-* + 1 timeout | 43.0 | 301 | 2 |

- **Tier 1 confirmed: `qwen3-8b-ctx16k`.** Two held-out cases the champion fails, it passes — the fallback
  rule (`routes.yaml` header: a fallback earns its slot on the case shape the champion fails, never as an
  accuracy pick). It is also the slowest 16k arm.
- **QAT beats plain here, the reverse of E31 on crm.** Same weights, same window: the QAT build reasons
  (598 tokens/call) and lands 14/19; the plain build answers straight (93 tokens, 9 s) and lands 11/19,
  missing `decision_maker` 8 times (roles as names). On crm (17 Sep) plain beat QAT 6/0 because QAT dropped
  the answer protocol. The build is a per-task decision, which is what the exam is for.
- **qwen3:14b is a window verdict, not a model verdict.** The stock tag runs at Ollama's 4,096 default
  (gotcha 16): every long call died unparsed, 0/10 on the band; on the 22 short cases it scored 10/13
  held-out, level with the 16k Qwen 8B. No 16k Modelfile exists for it; not built, not compared row-for-row.
- The 2B is three held-out calls behind the 4B at 15 s/call — the size step pays on this task, unlike recap.

## task-intake re-snapshot (26 Sep 13:15–13:32, 3 loads, 0/50 unstable)

The dispatcher exam grew 46 → 50 with the four call-fields dispatch cases. New snapshot: **heldout 21/22,
train 24/28** (old: 19/20, 24/26). All four new cases pass (both train, both heldout) — the champion 2B
dispatches "pull the CRM fields out of this call" to `call-fields` and leaves a bare or summarise-me
transcript on `transcript-en`. **Two pre-existing TRAIN cases flipped pass → fail:** `recap-end-of-day`
(now `none`) and `transcript-proper-english` (now `recap`). Neither went to `call-fields`; the 2B moved on
a longer specialist list. Held-out unchanged on all 20 old cases. Declared here and in the exam's
`not_verified`; not tuned.

## Small open-weight arms — the self-hostable ladder (same afternoon, unpinned, 4096 budget)

Question: for data residency the target is open weights on a small EU GPU (one 24–48 GB card) —
which of them reach the flagship band? Five candidates from OpenRouter's list, all ≤ 32B total
parameters. Rates are OpenRouter's listed price on 2026-09-25 (not in the ledger yet); volumes metered.

| arm | size | fits | train | heldout | died | mean s/call | out tok/call | $/10k calls |
|---|---|---|---|---|---|---|---|---|
| google/gemma-4-31b-it | 31B dense | 48 GB at 8-bit, 24 GB at 4-bit | 9/13 | **15/19** | 0 | 2.7 | 75 | 3 |
| openai/gpt-oss-20b | 20B MoE, ~4B active | 16–24 GB | 9/13 | **15/19** | 0 | 7.9 | 367 | 1 |
| mistralai/mistral-small-3.2-24b-instruct | 24B dense | 48 GB at 8-bit, 24 GB at 4-bit | 8/13 | 13/19 | 0 | 4.3 | 81 | 3 |
| google/gemma-4-26b-a4b-it | 26B MoE, 4B active | 24 GB | 9/13 | 11/19 | 0 | 4.0 | 75 | 2 |
| qwen/qwen3-14b | 14B dense | 24 GB | 10/13 | 11/19 | 0 | 9.2 | 441 | 4 |

- Gemma 4 31B and gpt-oss-20b tie Sol and GLM on held-out (15/19) at roughly a twentieth of Sol's
  token cost. Gemma 31B does it without reasoning (75 output tokens, 2.7 s); gpt-oss reasons
  (367 tokens, up to 34 s) and is therefore budget-sensitive like GLM.
- Miss profile of the two leaders is the flagship profile: `next_step_date` token forms
  (`next Tuesday`, `tomorrow morning`) plus the two declared `discovery-heldout-long` calls
  (`Meredith`/`4200` for `Idris`/`600`), which 5 of 5 small models and 0 of the flagships get
  "wrong" the same way — the label is defensible under the rule but it is the exam's most
  contestable call. Mistral, Gemma 26B-A4B and Qwen3 14B lose on the named-person rule
  (`CFO`, `ops director`, `Dov`) — the mini profile.
- These are hosted-provider verdicts, unpinned (the serving host is not recorded). A self-hosted
  quantised build is a different runtime and must sit the exam itself before anything ships
  (gotcha 15). Not a ranking of the whole open-weight field: five arms, chosen by size and recency.
- New ambiguity exposed, both splits, no label changed: a vendor name read as the customer's
  company (`Solvix` on renewal-medium-train, `Vantable` on renewal-heldout-medium — both are the
  REP's product/contract, labelled `not stated`). Declared in `not_verified`.

## Method

`hosted_run.sh <model> <pin> [timeout] [tag]`: `git archive HEAD` into a scratch dir, append
`provider_routing: {order: [<pin>], allow_fallbacks: false}` to the scratch `agent.yaml` (the
committed one is never edited), key from the main repo's gitignored `.env`, `runner.py run
call-fields --provider openrouter --model <id>`, copy the results file here. First launch failed on
CLAUDE.md gotcha 7 (zsh does not word-split: model and pin arrived as one string → 400).
Spend: ≈$1.60 metered across seven passes. Key after: see `curl /api/v1/auth/key`.
