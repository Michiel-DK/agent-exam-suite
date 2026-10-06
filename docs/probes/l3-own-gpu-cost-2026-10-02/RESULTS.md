# L3 — the modelled own-GPU cost column (2 Oct 2026; $0; no inference)

> **STATUS: every figure here is MODELLED.** Nothing in this folder is a measurement of a GPU. The wall seconds were measured on
> the hosted API (OpenRouter, 27 Sep matrix + 25 Sep call-fields) and are *assumed* to hold on the named card, one request at a
> time. The card prices are the providers' public on-demand rates as read on 2 Oct 2026 (URLs in repo-radar
> `data/prices/gpu-hours.tsv`). This sheet belongs in the pilot conversation, **never in the results table**
> (`docs/tiers-and-results-table.md` §1: "No own-VM rent column in the table").
>
> **Not evidence:** all of it. What would make a row `metered`: the runner's own `wall_ms` from a `run` ON that card
> (a rented-card day, K5 / J11b) — then `cost_per_10k.py --gpu` prints the same line from a measured wall, and the tag changes.

**Builder:** `python3 docs/probes/l3-own-gpu-cost-2026-10-02/build.py` (from the repo root). It shells out to repo-radar
`scripts/cost_per_10k.py --gpu <cards> --volumes <results.json>` per (task, model) — the only place a dollar figure is computed
(CLAUDE.md gotcha 20) — and pastes the printed lines (appendix). Self-test: `python3 scripts/cost_per_10k.py --self-test`
(the `--gpu` branch: 3.6 s/call × $0.36/h = $3.60 per 10k reproduced; a `--gpu` line can never carry `metered`; an unknown card is refused).

## 1. The model, in one line

```
$ per 10k tasks  =  10,000 × (mean hosted wall s/call) / 3600  ×  (card $ per hour)        — serial: one request at a time
tasks per card-month  =  30 × 24 × 3600 / (mean hosted wall s/call)
```

**Assumptions, each one unmeasured and stated:**
1. *The hosted wall transfers to the card.* OpenRouter's providers serve these weights on hardware they do not name, with
   batching we cannot see. A single L4 is a slower card than anything a provider batches on, so the real serial wall is probably
   **longer** than the table's. Direction known, size unknown.
2. *Serial.* One request in flight. A card serving several requests at once (vLLM-style continuous batching) divides the cost by
   roughly the concurrency it sustains. Direction known, size unknown. This is the lever that could make own-card cheaper than
   hosted per-token; it is unmeasured here.
3. *Card choice* follows the tiers doc's hand-maintained CAN map: 24 GB (L4) for gemma-4-26b-a4b, gpt-oss-20b, qwen3-14b,
   mistral-small-24b; 48 GB (L40S) for gemma-4-31b. Whether a quantised build fits and holds its score is a re-sit, not an
   assumption (gotcha 15).
4. *Prices are on-demand, ex-VAT, read on 2 Oct 2026*; RunPod's page says it was updated 27 Sep 2026; Scaleway's L40S price is the
   "start at" figure for PAR-2 (not offered in PAR-1). EUR and USD are not converted; each column stays in its currency.
5. *Rent is per month, tasks are per month.* The per-10k figure hides the fact that a rented card at pilot volume is mostly idle;
   §3 carries the break-even.

## 2. The column (held-out score and hosted price from `docs/probes/matrix-2026-09-27/tables.md`)

Cards: 24 GB = NVIDIA L4 (RunPod secure $0.49/h · Scaleway PAR-1 €0.79/h); 48 GB = NVIDIA L40S (RunPod secure $1.09/h · Scaleway PAR-2 €1.47/h).
Cheaper 24 GB cards exist (RunPod A5000 $0.27/h, community-cloud L4 $0.44/h) and are in `gpu-hours.tsv`; the L4 is the one a client's
IT department would buy or rent, so it is the column.

| task | model | heldout | hosted $/10k (ledger, from tables.md) | card | hosted wall s/call | own card, cheapest datacenter (RunPod secure) | own card, EU (Scaleway Paris) | tasks per card-month, serial |
|---|---|---|---|---|---|---|---|---|
| transcript-en | google/gemma-4-26b-a4b-it | **12**/19 | 2.01 (ledger) | L4 24 GB | 3.20 | $4.35 | €7.02 | 810,473 |
| transcript-en | google/gemma-4-31b-it | **11**/19 | 2.70 (ledger) | L40S 48 GB | 4.35 | $13.16 | €17.75 | 596,174 |
| transcript-en | mistralai/mistral-small-3.2-24b-instruct | **6**/19 | 2.72 (ledger) | L4 24 GB | 2.79 | $3.80 | €6.13 | 928,532 |
| transcript-en | openai/gpt-oss-20b | **9**/19 | 0.78 (ledger) | L4 24 GB | 5.49 | $7.48 | €12.06 | 471,705 |
| transcript-en | qwen/qwen3-14b | **11**/19 | 4.14 (ledger) | L4 24 GB | 8.71 | $11.86 | €19.12 | 297,491 |
| call-fields | google/gemma-4-26b-a4b-it | **11**/19 | 2.14 (ledger) | L4 24 GB | 4.02 | $5.47 | €8.82 | 644,923 |
| call-fields | google/gemma-4-31b-it | **15**/19 | 2.88 (ledger) | L40S 48 GB | 2.72 | $8.25 | €11.13 | 951,194 |
| call-fields | mistralai/mistral-small-3.2-24b-instruct | **13**/19 | 2.92 (ledger) | L4 24 GB | 4.34 | $5.91 | €9.53 | 596,929 |
| call-fields | openai/gpt-oss-20b | **15**/19 | 0.83 (ledger) | L4 24 GB | 7.89 | $10.74 | €17.32 | 328,472 |
| call-fields | qwen/qwen3-14b | **11**/19 | 4.39 (ledger) | L4 24 GB | 9.17 | $12.49 | €20.13 | 282,517 |
| crm-followup | google/gemma-4-26b-a4b-it | **13**/18 | 3.76 (ledger) | L4 24 GB | 4.16 | $5.66 | €9.13 | 623,293 |
| crm-followup | google/gemma-4-31b-it | **14**/18 | 5.41 (ledger) | L40S 48 GB | 5.34 | $16.16 | €21.80 | 485,579 |
| crm-followup | mistralai/mistral-small-3.2-24b-instruct | **10**/18 | 4.79 (ledger) | L4 24 GB | 3.66 | $4.99 | €8.04 | 707,236 |
| crm-followup | openai/gpt-oss-20b | **1**/18 | 0.16 (ledger) | L4 24 GB | 3.37 | $4.59 | €7.41 | 768,065 |
| crm-followup | qwen/qwen3-14b | **11**/18 | 7.48 (ledger) | L4 24 GB | 21.29 | $28.98 | €46.73 | 121,724 |
| recap | google/gemma-4-26b-a4b-it | **7**/10 | 1.14 (ledger) | L4 24 GB | 3.04 | $4.14 | €6.68 | 851,491 |
| recap | google/gemma-4-31b-it | **7**/10 | 1.53 (ledger) | L40S 48 GB | 5.09 | $15.41 | €20.78 | 509,283 |
| recap | mistralai/mistral-small-3.2-24b-instruct | **7**/10 | 1.59 (ledger) | L4 24 GB | 2.18 | $2.96 | €4.78 | 1,190,346 |
| recap | openai/gpt-oss-20b | **3**/10 | 0.70 (ledger) | L4 24 GB | 6.07 | $8.27 | €13.33 | 426,843 |
| recap | qwen/qwen3-14b | **6**/10 | 3.11 (ledger) | L4 24 GB | 8.66 | $11.79 | €19.00 | 299,305 |
| email-triage | google/gemma-4-26b-a4b-it | **10**/11 | 0.17 (ledger) | L4 24 GB | 0.87 | $1.19 | €1.92 | 2,967,462 |
| email-triage | google/gemma-4-31b-it | **10**/11 | 0.24 (ledger) | L40S 48 GB | 2.22 | $6.72 | €9.06 | 1,167,576 |
| email-triage | mistralai/mistral-small-3.2-24b-instruct | **10**/11 | 0.22 (ledger) | L4 24 GB | 0.74 | $1.01 | €1.63 | 3,489,400 |
| email-triage | openai/gpt-oss-20b | **9**/11 | 0.11 (ledger) | L4 24 GB | 1.35 | $1.83 | €2.96 | 1,923,457 |
| email-triage | qwen/qwen3-14b | **9**/11 | 1.02 (ledger) | L4 24 GB | 5.10 | $6.94 | €11.19 | 508,492 |
| expense-categorization | google/gemma-4-26b-a4b-it | **9**/9 | 0.17 (ledger) | L4 24 GB | 0.76 | $1.03 | €1.66 | 3,422,626 |
| expense-categorization | google/gemma-4-31b-it | **9**/9 | 0.23 (ledger) | L40S 48 GB | 1.36 | $4.13 | €5.57 | 1,899,875 |
| expense-categorization | mistralai/mistral-small-3.2-24b-instruct | **9**/9 | 0.22 (ledger) | L4 24 GB | 0.75 | $1.02 | €1.65 | 3,451,643 |
| expense-categorization | openai/gpt-oss-20b | **8**/9 | 0.16 (ledger) | L4 24 GB | 2.22 | $3.02 | €4.88 | 1,166,440 |
| expense-categorization | qwen/qwen3-14b | **8**/9 | 0.78 (ledger) | L4 24 GB | 3.83 | $5.22 | €8.41 | 676,147 |
| reply-draft | google/gemma-4-26b-a4b-it | **10**/10 | 0.37 (ledger) | L4 24 GB | 2.16 | $2.94 | €4.74 | 1,200,016 |
| reply-draft | google/gemma-4-31b-it | **10**/10 | 0.50 (ledger) | L40S 48 GB | 2.17 | $6.56 | €8.85 | 1,196,335 |
| reply-draft | mistralai/mistral-small-3.2-24b-instruct | **10**/10 | 0.39 (ledger) | L4 24 GB | 1.43 | $1.95 | €3.14 | 1,812,625 |
| reply-draft | openai/gpt-oss-20b | **9**/10 | 0.19 (ledger) | L4 24 GB | 3.01 | $4.09 | €6.60 | 862,194 |
| reply-draft | qwen/qwen3-14b | **10**/10 | 0.89 (ledger) | L4 24 GB | 4.17 | $5.67 | €9.14 | 622,163 |


## 3. What it says

**At serial, owning the card costs at least as much per task as the hosted per-token price on every row, and usually several times more** — RunPod column over the hosted ledger figure: L4 rows 1.0× (mistralai/mistral-small-3.2-24b-instruct) to 29× (openai/gpt-oss-20b; gpt-oss-20b is priced far below the others per token, so its rows are the extreme — 1.0–7.9× without it), L40S rows 2.9× to 28.0×, with the same hosted wall). Example, call-fields on gemma-4-26b-a4b: hosted $2.14 per 10k (ledger)
vs $5.47 on a RunPod L4 vs €8.82 on a Scaleway L4. The hosted providers are charging less per task than the card-hour the same
task would occupy on an L4, because they batch and we modelled no batching. So **the own-card tier is not a price argument at
these volumes; it is a residency / ownership / pin-the-runtime argument** (tiers doc §1). Say that in the pilot, not "cheaper".

**Break-even against renting the card full time** (cheapest-datacenter column; rent = price/h × 720 h): the hosted volume per
month at which the hosted bill equals one dedicated card's rent. Every figure is far above any pilot's volume:

| task | model | card | rent / month | hosted $/10k | hosted tasks/month that cost the same as the rent |
|---|---|---|---|---|---|
| transcript-en | google/gemma-4-26b-a4b-it | L4 24 GB | $352.80 | $2.01 | 1,755,224 |
| transcript-en | google/gemma-4-31b-it | L40S 48 GB | $784.80 | $2.70 | 2,906,667 |
| transcript-en | mistralai/mistral-small-3.2-24b-instruct | L4 24 GB | $352.80 | $2.72 | 1,297,059 |
| transcript-en | openai/gpt-oss-20b | L4 24 GB | $352.80 | $0.78 | 4,523,077 |
| transcript-en | qwen/qwen3-14b | L4 24 GB | $352.80 | $4.14 | 852,174 |
| call-fields | google/gemma-4-26b-a4b-it | L4 24 GB | $352.80 | $2.14 | 1,648,598 |
| call-fields | google/gemma-4-31b-it | L40S 48 GB | $784.80 | $2.88 | 2,725,000 |
| call-fields | mistralai/mistral-small-3.2-24b-instruct | L4 24 GB | $352.80 | $2.92 | 1,208,219 |
| call-fields | openai/gpt-oss-20b | L4 24 GB | $352.80 | $0.83 | 4,250,602 |
| call-fields | qwen/qwen3-14b | L4 24 GB | $352.80 | $4.39 | 803,645 |
| crm-followup | google/gemma-4-26b-a4b-it | L4 24 GB | $352.80 | $3.76 | 938,298 |
| crm-followup | google/gemma-4-31b-it | L40S 48 GB | $784.80 | $5.41 | 1,450,647 |
| crm-followup | mistralai/mistral-small-3.2-24b-instruct | L4 24 GB | $352.80 | $4.79 | 736,534 |
| crm-followup | openai/gpt-oss-20b | L4 24 GB | $352.80 | $0.16 | 22,050,000 |
| crm-followup | qwen/qwen3-14b | L4 24 GB | $352.80 | $7.48 | 471,658 |
| recap | google/gemma-4-26b-a4b-it | L4 24 GB | $352.80 | $1.14 | 3,094,737 |
| recap | google/gemma-4-31b-it | L40S 48 GB | $784.80 | $1.53 | 5,129,412 |
| recap | mistralai/mistral-small-3.2-24b-instruct | L4 24 GB | $352.80 | $1.59 | 2,218,868 |
| recap | openai/gpt-oss-20b | L4 24 GB | $352.80 | $0.70 | 5,040,000 |
| recap | qwen/qwen3-14b | L4 24 GB | $352.80 | $3.11 | 1,134,405 |
| email-triage | google/gemma-4-26b-a4b-it | L4 24 GB | $352.80 | $0.17 | 20,752,941 |
| email-triage | google/gemma-4-31b-it | L40S 48 GB | $784.80 | $0.24 | 32,700,000 |
| email-triage | mistralai/mistral-small-3.2-24b-instruct | L4 24 GB | $352.80 | $0.22 | 16,036,364 |
| email-triage | openai/gpt-oss-20b | L4 24 GB | $352.80 | $0.11 | 32,072,727 |
| email-triage | qwen/qwen3-14b | L4 24 GB | $352.80 | $1.02 | 3,458,824 |
| expense-categorization | google/gemma-4-26b-a4b-it | L4 24 GB | $352.80 | $0.17 | 20,752,941 |
| expense-categorization | google/gemma-4-31b-it | L40S 48 GB | $784.80 | $0.23 | 34,121,739 |
| expense-categorization | mistralai/mistral-small-3.2-24b-instruct | L4 24 GB | $352.80 | $0.22 | 16,036,364 |
| expense-categorization | openai/gpt-oss-20b | L4 24 GB | $352.80 | $0.16 | 22,050,000 |
| expense-categorization | qwen/qwen3-14b | L4 24 GB | $352.80 | $0.78 | 4,523,077 |
| reply-draft | google/gemma-4-26b-a4b-it | L4 24 GB | $352.80 | $0.37 | 9,535,135 |
| reply-draft | google/gemma-4-31b-it | L40S 48 GB | $784.80 | $0.50 | 15,696,000 |
| reply-draft | mistralai/mistral-small-3.2-24b-instruct | L4 24 GB | $352.80 | $0.39 | 9,046,154 |
| reply-draft | openai/gpt-oss-20b | L4 24 GB | $352.80 | $0.19 | 18,568,421 |
| reply-draft | qwen/qwen3-14b | L4 24 GB | $352.80 | $0.89 | 3,964,045 |

**Pilot-sheet lines (modelled; paste with the tag):**
- A dedicated NVIDIA L4 in Paris is **€574.87 per month** (Scaleway's page, 2 Oct 2026, ex-VAT) or **$352.80** (RunPod secure,
  $0.49/h × 720 h). At the hosted wall it serves ~645k CRM field write-backs or ~810k call summaries a month on
  gemma-4-26b-a4b, one at a time — a pilot of a few hundred calls a month uses under an hour of it.
- Per task at pilot volume the number is therefore the rent, not the per-10k figure: 300 calls a month on a dedicated L4 is
  €1.92 per call (€574.87 / 300), against $0.0002 hosted. A **shared** card or a **per-second** rental (RunPod bills per second)
  removes that: 300 × 4.0 s = 20 min ≈ $0.16 per month on the L4.
- The honest offer shape for the lead: (a) hosted open weights at the per-token price (the table's `$ / 10k` column, metered);
  (b) the same weights on a per-second-billed card in an EU region when residency requires it, cost ≈ the per-10k figure here
  (modelled, serial, pessimistic); (c) a dedicated card only when they already run one.

## 4. What changes the numbers (in payoff order)

1. **One rented-card day measures the wall** (K5 / J11b, ~€20): `run` on the L4 writes `wall_ms` per case; `cost_per_10k.py --gpu`
   then prints the same line from a measured wall and the row becomes `metered` for that card. Also answers assumption 1.
2. **Concurrency** on that same day: the runner has no concurrent mode; a 4-in-flight probe is a small script against the card's
   OpenAI-compatible server, not an exam. Answers assumption 2.
3. A price re-read before any outward use (the sheet is dated; GPU rental prices move monthly).

## Appendix — the pasted lines


**transcript-en · google/gemma-4-26b-a4b-it**
```
wall: 3.20 s/call mean over 32 of 32 cases (transcript-en__google_gemma-4-26b-a4b-it-2026-09-27.json, model google/gemma-4-26b-a4b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-26b-a4b-it on L4 24 GB (RunPod, secure cloud): $4.35 per 10k tasks — 3.20 s/call mean over 32 cases x $0.49/h as of 2026-10-02 — serial, 810,473 tasks per card-month — modelled on transcript-en__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x runpod/l4-secure
google/gemma-4-26b-a4b-it on L4 24 GB (Scaleway, on-demand PAR-1): €7.02 per 10k tasks — 3.20 s/call mean over 32 cases x €0.79/h as of 2026-10-02 — serial, 810,473 tasks per card-month — modelled on transcript-en__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**transcript-en · google/gemma-4-31b-it**
```
wall: 4.35 s/call mean over 32 of 32 cases (transcript-en__google_gemma-4-31b-it-2026-09-27.json, model google/gemma-4-31b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-31b-it on L40S 48 GB (RunPod, secure cloud): $13.16 per 10k tasks — 4.35 s/call mean over 32 cases x $1.09/h as of 2026-10-02 — serial, 596,174 tasks per card-month — modelled on transcript-en__google_gemma-4-31b-it-2026-09-27.json hosted wall x runpod/l40s-secure
google/gemma-4-31b-it on L40S 48 GB (Scaleway, on-demand PAR-2): €17.75 per 10k tasks — 4.35 s/call mean over 32 cases x €1.47/h as of 2026-10-02 — serial, 596,174 tasks per card-month — modelled on transcript-en__google_gemma-4-31b-it-2026-09-27.json hosted wall x scaleway/l40s-1-48g
```
**transcript-en · mistralai/mistral-small-3.2-24b-instruct**
```
wall: 2.79 s/call mean over 32 of 32 cases (transcript-en__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json, model mistralai/mistral-small-3.2-24b-instruct) — measured on the HOSTED endpoint, not on the card
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (RunPod, secure cloud): $3.80 per 10k tasks — 2.79 s/call mean over 32 cases x $0.49/h as of 2026-10-02 — serial, 928,532 tasks per card-month — modelled on transcript-en__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x runpod/l4-secure
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (Scaleway, on-demand PAR-1): €6.13 per 10k tasks — 2.79 s/call mean over 32 cases x €0.79/h as of 2026-10-02 — serial, 928,532 tasks per card-month — modelled on transcript-en__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**transcript-en · openai/gpt-oss-20b**
```
wall: 5.49 s/call mean over 31 of 32 cases (transcript-en__openai_gpt-oss-20b-2026-09-27.json, model openai/gpt-oss-20b) — measured on the HOSTED endpoint, not on the card
openai/gpt-oss-20b on L4 24 GB (RunPod, secure cloud): $7.48 per 10k tasks — 5.49 s/call mean over 31 cases x $0.49/h as of 2026-10-02 — serial, 471,705 tasks per card-month — modelled on transcript-en__openai_gpt-oss-20b-2026-09-27.json hosted wall x runpod/l4-secure
openai/gpt-oss-20b on L4 24 GB (Scaleway, on-demand PAR-1): €12.06 per 10k tasks — 5.49 s/call mean over 31 cases x €0.79/h as of 2026-10-02 — serial, 471,705 tasks per card-month — modelled on transcript-en__openai_gpt-oss-20b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**transcript-en · qwen/qwen3-14b**
```
wall: 8.71 s/call mean over 32 of 32 cases (transcript-en__qwen_qwen3-14b-2026-09-27.json, model qwen/qwen3-14b) — measured on the HOSTED endpoint, not on the card
qwen/qwen3-14b on L4 24 GB (RunPod, secure cloud): $11.86 per 10k tasks — 8.71 s/call mean over 32 cases x $0.49/h as of 2026-10-02 — serial, 297,491 tasks per card-month — modelled on transcript-en__qwen_qwen3-14b-2026-09-27.json hosted wall x runpod/l4-secure
qwen/qwen3-14b on L4 24 GB (Scaleway, on-demand PAR-1): €19.12 per 10k tasks — 8.71 s/call mean over 32 cases x €0.79/h as of 2026-10-02 — serial, 297,491 tasks per card-month — modelled on transcript-en__qwen_qwen3-14b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**call-fields · google/gemma-4-26b-a4b-it**
```
wall: 4.02 s/call mean over 32 of 32 cases (hosted-google_gemma-4-26b-a4b-it-2026-09-25-small.json, model google/gemma-4-26b-a4b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-26b-a4b-it on L4 24 GB (RunPod, secure cloud): $5.47 per 10k tasks — 4.02 s/call mean over 32 cases x $0.49/h as of 2026-10-02 — serial, 644,923 tasks per card-month — modelled on hosted-google_gemma-4-26b-a4b-it-2026-09-25-small.json hosted wall x runpod/l4-secure
google/gemma-4-26b-a4b-it on L4 24 GB (Scaleway, on-demand PAR-1): €8.82 per 10k tasks — 4.02 s/call mean over 32 cases x €0.79/h as of 2026-10-02 — serial, 644,923 tasks per card-month — modelled on hosted-google_gemma-4-26b-a4b-it-2026-09-25-small.json hosted wall x scaleway/l4-1-24g
```
**call-fields · google/gemma-4-31b-it**
```
wall: 2.72 s/call mean over 32 of 32 cases (hosted-google_gemma-4-31b-it-2026-09-25-small.json, model google/gemma-4-31b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-31b-it on L40S 48 GB (RunPod, secure cloud): $8.25 per 10k tasks — 2.72 s/call mean over 32 cases x $1.09/h as of 2026-10-02 — serial, 951,194 tasks per card-month — modelled on hosted-google_gemma-4-31b-it-2026-09-25-small.json hosted wall x runpod/l40s-secure
google/gemma-4-31b-it on L40S 48 GB (Scaleway, on-demand PAR-2): €11.13 per 10k tasks — 2.72 s/call mean over 32 cases x €1.47/h as of 2026-10-02 — serial, 951,194 tasks per card-month — modelled on hosted-google_gemma-4-31b-it-2026-09-25-small.json hosted wall x scaleway/l40s-1-48g
```
**call-fields · mistralai/mistral-small-3.2-24b-instruct**
```
wall: 4.34 s/call mean over 32 of 32 cases (hosted-mistralai_mistral-small-3.2-24b-instruct-2026-09-25-small.json, model mistralai/mistral-small-3.2-24b-instruct) — measured on the HOSTED endpoint, not on the card
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (RunPod, secure cloud): $5.91 per 10k tasks — 4.34 s/call mean over 32 cases x $0.49/h as of 2026-10-02 — serial, 596,929 tasks per card-month — modelled on hosted-mistralai_mistral-small-3.2-24b-instruct-2026-09-25-small.json hosted wall x runpod/l4-secure
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (Scaleway, on-demand PAR-1): €9.53 per 10k tasks — 4.34 s/call mean over 32 cases x €0.79/h as of 2026-10-02 — serial, 596,929 tasks per card-month — modelled on hosted-mistralai_mistral-small-3.2-24b-instruct-2026-09-25-small.json hosted wall x scaleway/l4-1-24g
```
**call-fields · openai/gpt-oss-20b**
```
wall: 7.89 s/call mean over 32 of 32 cases (hosted-openai_gpt-oss-20b-2026-09-25-small.json, model openai/gpt-oss-20b) — measured on the HOSTED endpoint, not on the card
openai/gpt-oss-20b on L4 24 GB (RunPod, secure cloud): $10.74 per 10k tasks — 7.89 s/call mean over 32 cases x $0.49/h as of 2026-10-02 — serial, 328,472 tasks per card-month — modelled on hosted-openai_gpt-oss-20b-2026-09-25-small.json hosted wall x runpod/l4-secure
openai/gpt-oss-20b on L4 24 GB (Scaleway, on-demand PAR-1): €17.32 per 10k tasks — 7.89 s/call mean over 32 cases x €0.79/h as of 2026-10-02 — serial, 328,472 tasks per card-month — modelled on hosted-openai_gpt-oss-20b-2026-09-25-small.json hosted wall x scaleway/l4-1-24g
```
**call-fields · qwen/qwen3-14b**
```
wall: 9.17 s/call mean over 32 of 32 cases (hosted-qwen_qwen3-14b-2026-09-25-small.json, model qwen/qwen3-14b) — measured on the HOSTED endpoint, not on the card
qwen/qwen3-14b on L4 24 GB (RunPod, secure cloud): $12.49 per 10k tasks — 9.17 s/call mean over 32 cases x $0.49/h as of 2026-10-02 — serial, 282,517 tasks per card-month — modelled on hosted-qwen_qwen3-14b-2026-09-25-small.json hosted wall x runpod/l4-secure
qwen/qwen3-14b on L4 24 GB (Scaleway, on-demand PAR-1): €20.13 per 10k tasks — 9.17 s/call mean over 32 cases x €0.79/h as of 2026-10-02 — serial, 282,517 tasks per card-month — modelled on hosted-qwen_qwen3-14b-2026-09-25-small.json hosted wall x scaleway/l4-1-24g
```
**crm-followup · google/gemma-4-26b-a4b-it**
```
wall: 4.16 s/call mean over 38 of 38 cases (crm-followup__google_gemma-4-26b-a4b-it-2026-09-27.json, model google/gemma-4-26b-a4b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-26b-a4b-it on L4 24 GB (RunPod, secure cloud): $5.66 per 10k tasks — 4.16 s/call mean over 38 cases x $0.49/h as of 2026-10-02 — serial, 623,293 tasks per card-month — modelled on crm-followup__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x runpod/l4-secure
google/gemma-4-26b-a4b-it on L4 24 GB (Scaleway, on-demand PAR-1): €9.13 per 10k tasks — 4.16 s/call mean over 38 cases x €0.79/h as of 2026-10-02 — serial, 623,293 tasks per card-month — modelled on crm-followup__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**crm-followup · google/gemma-4-31b-it**
```
wall: 5.34 s/call mean over 38 of 38 cases (crm-followup__google_gemma-4-31b-it-2026-09-27.json, model google/gemma-4-31b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-31b-it on L40S 48 GB (RunPod, secure cloud): $16.16 per 10k tasks — 5.34 s/call mean over 38 cases x $1.09/h as of 2026-10-02 — serial, 485,579 tasks per card-month — modelled on crm-followup__google_gemma-4-31b-it-2026-09-27.json hosted wall x runpod/l40s-secure
google/gemma-4-31b-it on L40S 48 GB (Scaleway, on-demand PAR-2): €21.80 per 10k tasks — 5.34 s/call mean over 38 cases x €1.47/h as of 2026-10-02 — serial, 485,579 tasks per card-month — modelled on crm-followup__google_gemma-4-31b-it-2026-09-27.json hosted wall x scaleway/l40s-1-48g
```
**crm-followup · mistralai/mistral-small-3.2-24b-instruct**
```
wall: 3.66 s/call mean over 38 of 38 cases (crm-followup__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json, model mistralai/mistral-small-3.2-24b-instruct) — measured on the HOSTED endpoint, not on the card
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (RunPod, secure cloud): $4.99 per 10k tasks — 3.66 s/call mean over 38 cases x $0.49/h as of 2026-10-02 — serial, 707,236 tasks per card-month — modelled on crm-followup__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x runpod/l4-secure
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (Scaleway, on-demand PAR-1): €8.04 per 10k tasks — 3.66 s/call mean over 38 cases x €0.79/h as of 2026-10-02 — serial, 707,236 tasks per card-month — modelled on crm-followup__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**crm-followup · openai/gpt-oss-20b**
```
wall: 3.37 s/call mean over 16 of 38 cases (crm-followup__openai_gpt-oss-20b-2026-09-27.json, model openai/gpt-oss-20b) — measured on the HOSTED endpoint, not on the card
openai/gpt-oss-20b on L4 24 GB (RunPod, secure cloud): $4.59 per 10k tasks — 3.37 s/call mean over 16 cases x $0.49/h as of 2026-10-02 — serial, 768,065 tasks per card-month — modelled on crm-followup__openai_gpt-oss-20b-2026-09-27.json hosted wall x runpod/l4-secure
openai/gpt-oss-20b on L4 24 GB (Scaleway, on-demand PAR-1): €7.41 per 10k tasks — 3.37 s/call mean over 16 cases x €0.79/h as of 2026-10-02 — serial, 768,065 tasks per card-month — modelled on crm-followup__openai_gpt-oss-20b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**crm-followup · qwen/qwen3-14b**
```
wall: 21.29 s/call mean over 38 of 38 cases (crm-followup__qwen_qwen3-14b-2026-09-27.json, model qwen/qwen3-14b) — measured on the HOSTED endpoint, not on the card
qwen/qwen3-14b on L4 24 GB (RunPod, secure cloud): $28.98 per 10k tasks — 21.29 s/call mean over 38 cases x $0.49/h as of 2026-10-02 — serial, 121,724 tasks per card-month — modelled on crm-followup__qwen_qwen3-14b-2026-09-27.json hosted wall x runpod/l4-secure
qwen/qwen3-14b on L4 24 GB (Scaleway, on-demand PAR-1): €46.73 per 10k tasks — 21.29 s/call mean over 38 cases x €0.79/h as of 2026-10-02 — serial, 121,724 tasks per card-month — modelled on crm-followup__qwen_qwen3-14b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**recap · google/gemma-4-26b-a4b-it**
```
wall: 3.04 s/call mean over 17 of 17 cases (recap__google_gemma-4-26b-a4b-it-2026-09-27.json, model google/gemma-4-26b-a4b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-26b-a4b-it on L4 24 GB (RunPod, secure cloud): $4.14 per 10k tasks — 3.04 s/call mean over 17 cases x $0.49/h as of 2026-10-02 — serial, 851,491 tasks per card-month — modelled on recap__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x runpod/l4-secure
google/gemma-4-26b-a4b-it on L4 24 GB (Scaleway, on-demand PAR-1): €6.68 per 10k tasks — 3.04 s/call mean over 17 cases x €0.79/h as of 2026-10-02 — serial, 851,491 tasks per card-month — modelled on recap__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**recap · google/gemma-4-31b-it**
```
wall: 5.09 s/call mean over 17 of 17 cases (recap__google_gemma-4-31b-it-2026-09-27.json, model google/gemma-4-31b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-31b-it on L40S 48 GB (RunPod, secure cloud): $15.41 per 10k tasks — 5.09 s/call mean over 17 cases x $1.09/h as of 2026-10-02 — serial, 509,283 tasks per card-month — modelled on recap__google_gemma-4-31b-it-2026-09-27.json hosted wall x runpod/l40s-secure
google/gemma-4-31b-it on L40S 48 GB (Scaleway, on-demand PAR-2): €20.78 per 10k tasks — 5.09 s/call mean over 17 cases x €1.47/h as of 2026-10-02 — serial, 509,283 tasks per card-month — modelled on recap__google_gemma-4-31b-it-2026-09-27.json hosted wall x scaleway/l40s-1-48g
```
**recap · mistralai/mistral-small-3.2-24b-instruct**
```
wall: 2.18 s/call mean over 17 of 17 cases (recap__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json, model mistralai/mistral-small-3.2-24b-instruct) — measured on the HOSTED endpoint, not on the card
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (RunPod, secure cloud): $2.96 per 10k tasks — 2.18 s/call mean over 17 cases x $0.49/h as of 2026-10-02 — serial, 1,190,346 tasks per card-month — modelled on recap__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x runpod/l4-secure
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (Scaleway, on-demand PAR-1): €4.78 per 10k tasks — 2.18 s/call mean over 17 cases x €0.79/h as of 2026-10-02 — serial, 1,190,346 tasks per card-month — modelled on recap__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**recap · openai/gpt-oss-20b**
```
wall: 6.07 s/call mean over 17 of 17 cases (recap__openai_gpt-oss-20b-2026-09-27.json, model openai/gpt-oss-20b) — measured on the HOSTED endpoint, not on the card
openai/gpt-oss-20b on L4 24 GB (RunPod, secure cloud): $8.27 per 10k tasks — 6.07 s/call mean over 17 cases x $0.49/h as of 2026-10-02 — serial, 426,843 tasks per card-month — modelled on recap__openai_gpt-oss-20b-2026-09-27.json hosted wall x runpod/l4-secure
openai/gpt-oss-20b on L4 24 GB (Scaleway, on-demand PAR-1): €13.33 per 10k tasks — 6.07 s/call mean over 17 cases x €0.79/h as of 2026-10-02 — serial, 426,843 tasks per card-month — modelled on recap__openai_gpt-oss-20b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**recap · qwen/qwen3-14b**
```
wall: 8.66 s/call mean over 17 of 17 cases (recap__qwen_qwen3-14b-2026-09-27.json, model qwen/qwen3-14b) — measured on the HOSTED endpoint, not on the card
qwen/qwen3-14b on L4 24 GB (RunPod, secure cloud): $11.79 per 10k tasks — 8.66 s/call mean over 17 cases x $0.49/h as of 2026-10-02 — serial, 299,305 tasks per card-month — modelled on recap__qwen_qwen3-14b-2026-09-27.json hosted wall x runpod/l4-secure
qwen/qwen3-14b on L4 24 GB (Scaleway, on-demand PAR-1): €19.00 per 10k tasks — 8.66 s/call mean over 17 cases x €0.79/h as of 2026-10-02 — serial, 299,305 tasks per card-month — modelled on recap__qwen_qwen3-14b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**email-triage · google/gemma-4-26b-a4b-it**
```
wall: 0.87 s/call mean over 19 of 19 cases (email-triage__google_gemma-4-26b-a4b-it-2026-09-27.json, model google/gemma-4-26b-a4b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-26b-a4b-it on L4 24 GB (RunPod, secure cloud): $1.19 per 10k tasks — 0.87 s/call mean over 19 cases x $0.49/h as of 2026-10-02 — serial, 2,967,462 tasks per card-month — modelled on email-triage__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x runpod/l4-secure
google/gemma-4-26b-a4b-it on L4 24 GB (Scaleway, on-demand PAR-1): €1.92 per 10k tasks — 0.87 s/call mean over 19 cases x €0.79/h as of 2026-10-02 — serial, 2,967,462 tasks per card-month — modelled on email-triage__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**email-triage · google/gemma-4-31b-it**
```
wall: 2.22 s/call mean over 19 of 19 cases (email-triage__google_gemma-4-31b-it-2026-09-27.json, model google/gemma-4-31b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-31b-it on L40S 48 GB (RunPod, secure cloud): $6.72 per 10k tasks — 2.22 s/call mean over 19 cases x $1.09/h as of 2026-10-02 — serial, 1,167,576 tasks per card-month — modelled on email-triage__google_gemma-4-31b-it-2026-09-27.json hosted wall x runpod/l40s-secure
google/gemma-4-31b-it on L40S 48 GB (Scaleway, on-demand PAR-2): €9.06 per 10k tasks — 2.22 s/call mean over 19 cases x €1.47/h as of 2026-10-02 — serial, 1,167,576 tasks per card-month — modelled on email-triage__google_gemma-4-31b-it-2026-09-27.json hosted wall x scaleway/l40s-1-48g
```
**email-triage · mistralai/mistral-small-3.2-24b-instruct**
```
wall: 0.74 s/call mean over 19 of 19 cases (email-triage__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json, model mistralai/mistral-small-3.2-24b-instruct) — measured on the HOSTED endpoint, not on the card
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (RunPod, secure cloud): $1.01 per 10k tasks — 0.74 s/call mean over 19 cases x $0.49/h as of 2026-10-02 — serial, 3,489,400 tasks per card-month — modelled on email-triage__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x runpod/l4-secure
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (Scaleway, on-demand PAR-1): €1.63 per 10k tasks — 0.74 s/call mean over 19 cases x €0.79/h as of 2026-10-02 — serial, 3,489,400 tasks per card-month — modelled on email-triage__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**email-triage · openai/gpt-oss-20b**
```
wall: 1.35 s/call mean over 19 of 19 cases (email-triage__openai_gpt-oss-20b-2026-09-27.json, model openai/gpt-oss-20b) — measured on the HOSTED endpoint, not on the card
openai/gpt-oss-20b on L4 24 GB (RunPod, secure cloud): $1.83 per 10k tasks — 1.35 s/call mean over 19 cases x $0.49/h as of 2026-10-02 — serial, 1,923,457 tasks per card-month — modelled on email-triage__openai_gpt-oss-20b-2026-09-27.json hosted wall x runpod/l4-secure
openai/gpt-oss-20b on L4 24 GB (Scaleway, on-demand PAR-1): €2.96 per 10k tasks — 1.35 s/call mean over 19 cases x €0.79/h as of 2026-10-02 — serial, 1,923,457 tasks per card-month — modelled on email-triage__openai_gpt-oss-20b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**email-triage · qwen/qwen3-14b**
```
wall: 5.10 s/call mean over 19 of 19 cases (email-triage__qwen_qwen3-14b-2026-09-27.json, model qwen/qwen3-14b) — measured on the HOSTED endpoint, not on the card
qwen/qwen3-14b on L4 24 GB (RunPod, secure cloud): $6.94 per 10k tasks — 5.10 s/call mean over 19 cases x $0.49/h as of 2026-10-02 — serial, 508,492 tasks per card-month — modelled on email-triage__qwen_qwen3-14b-2026-09-27.json hosted wall x runpod/l4-secure
qwen/qwen3-14b on L4 24 GB (Scaleway, on-demand PAR-1): €11.19 per 10k tasks — 5.10 s/call mean over 19 cases x €0.79/h as of 2026-10-02 — serial, 508,492 tasks per card-month — modelled on email-triage__qwen_qwen3-14b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**expense-categorization · google/gemma-4-26b-a4b-it**
```
wall: 0.76 s/call mean over 15 of 15 cases (expense-categorization__google_gemma-4-26b-a4b-it-2026-09-27.json, model google/gemma-4-26b-a4b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-26b-a4b-it on L4 24 GB (RunPod, secure cloud): $1.03 per 10k tasks — 0.76 s/call mean over 15 cases x $0.49/h as of 2026-10-02 — serial, 3,422,626 tasks per card-month — modelled on expense-categorization__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x runpod/l4-secure
google/gemma-4-26b-a4b-it on L4 24 GB (Scaleway, on-demand PAR-1): €1.66 per 10k tasks — 0.76 s/call mean over 15 cases x €0.79/h as of 2026-10-02 — serial, 3,422,626 tasks per card-month — modelled on expense-categorization__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**expense-categorization · google/gemma-4-31b-it**
```
wall: 1.36 s/call mean over 15 of 15 cases (expense-categorization__google_gemma-4-31b-it-2026-09-27.json, model google/gemma-4-31b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-31b-it on L40S 48 GB (RunPod, secure cloud): $4.13 per 10k tasks — 1.36 s/call mean over 15 cases x $1.09/h as of 2026-10-02 — serial, 1,899,875 tasks per card-month — modelled on expense-categorization__google_gemma-4-31b-it-2026-09-27.json hosted wall x runpod/l40s-secure
google/gemma-4-31b-it on L40S 48 GB (Scaleway, on-demand PAR-2): €5.57 per 10k tasks — 1.36 s/call mean over 15 cases x €1.47/h as of 2026-10-02 — serial, 1,899,875 tasks per card-month — modelled on expense-categorization__google_gemma-4-31b-it-2026-09-27.json hosted wall x scaleway/l40s-1-48g
```
**expense-categorization · mistralai/mistral-small-3.2-24b-instruct**
```
wall: 0.75 s/call mean over 15 of 15 cases (expense-categorization__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json, model mistralai/mistral-small-3.2-24b-instruct) — measured on the HOSTED endpoint, not on the card
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (RunPod, secure cloud): $1.02 per 10k tasks — 0.75 s/call mean over 15 cases x $0.49/h as of 2026-10-02 — serial, 3,451,643 tasks per card-month — modelled on expense-categorization__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x runpod/l4-secure
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (Scaleway, on-demand PAR-1): €1.65 per 10k tasks — 0.75 s/call mean over 15 cases x €0.79/h as of 2026-10-02 — serial, 3,451,643 tasks per card-month — modelled on expense-categorization__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**expense-categorization · openai/gpt-oss-20b**
```
wall: 2.22 s/call mean over 15 of 15 cases (expense-categorization__openai_gpt-oss-20b-2026-09-27.json, model openai/gpt-oss-20b) — measured on the HOSTED endpoint, not on the card
openai/gpt-oss-20b on L4 24 GB (RunPod, secure cloud): $3.02 per 10k tasks — 2.22 s/call mean over 15 cases x $0.49/h as of 2026-10-02 — serial, 1,166,440 tasks per card-month — modelled on expense-categorization__openai_gpt-oss-20b-2026-09-27.json hosted wall x runpod/l4-secure
openai/gpt-oss-20b on L4 24 GB (Scaleway, on-demand PAR-1): €4.88 per 10k tasks — 2.22 s/call mean over 15 cases x €0.79/h as of 2026-10-02 — serial, 1,166,440 tasks per card-month — modelled on expense-categorization__openai_gpt-oss-20b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**expense-categorization · qwen/qwen3-14b**
```
wall: 3.83 s/call mean over 15 of 15 cases (expense-categorization__qwen_qwen3-14b-2026-09-27.json, model qwen/qwen3-14b) — measured on the HOSTED endpoint, not on the card
qwen/qwen3-14b on L4 24 GB (RunPod, secure cloud): $5.22 per 10k tasks — 3.83 s/call mean over 15 cases x $0.49/h as of 2026-10-02 — serial, 676,147 tasks per card-month — modelled on expense-categorization__qwen_qwen3-14b-2026-09-27.json hosted wall x runpod/l4-secure
qwen/qwen3-14b on L4 24 GB (Scaleway, on-demand PAR-1): €8.41 per 10k tasks — 3.83 s/call mean over 15 cases x €0.79/h as of 2026-10-02 — serial, 676,147 tasks per card-month — modelled on expense-categorization__qwen_qwen3-14b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**reply-draft · google/gemma-4-26b-a4b-it**
```
wall: 2.16 s/call mean over 17 of 17 cases (reply-draft__google_gemma-4-26b-a4b-it-2026-09-27.json, model google/gemma-4-26b-a4b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-26b-a4b-it on L4 24 GB (RunPod, secure cloud): $2.94 per 10k tasks — 2.16 s/call mean over 17 cases x $0.49/h as of 2026-10-02 — serial, 1,200,016 tasks per card-month — modelled on reply-draft__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x runpod/l4-secure
google/gemma-4-26b-a4b-it on L4 24 GB (Scaleway, on-demand PAR-1): €4.74 per 10k tasks — 2.16 s/call mean over 17 cases x €0.79/h as of 2026-10-02 — serial, 1,200,016 tasks per card-month — modelled on reply-draft__google_gemma-4-26b-a4b-it-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**reply-draft · google/gemma-4-31b-it**
```
wall: 2.17 s/call mean over 17 of 17 cases (reply-draft__google_gemma-4-31b-it-2026-09-27.json, model google/gemma-4-31b-it) — measured on the HOSTED endpoint, not on the card
google/gemma-4-31b-it on L40S 48 GB (RunPod, secure cloud): $6.56 per 10k tasks — 2.17 s/call mean over 17 cases x $1.09/h as of 2026-10-02 — serial, 1,196,335 tasks per card-month — modelled on reply-draft__google_gemma-4-31b-it-2026-09-27.json hosted wall x runpod/l40s-secure
google/gemma-4-31b-it on L40S 48 GB (Scaleway, on-demand PAR-2): €8.85 per 10k tasks — 2.17 s/call mean over 17 cases x €1.47/h as of 2026-10-02 — serial, 1,196,335 tasks per card-month — modelled on reply-draft__google_gemma-4-31b-it-2026-09-27.json hosted wall x scaleway/l40s-1-48g
```
**reply-draft · mistralai/mistral-small-3.2-24b-instruct**
```
wall: 1.43 s/call mean over 17 of 17 cases (reply-draft__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json, model mistralai/mistral-small-3.2-24b-instruct) — measured on the HOSTED endpoint, not on the card
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (RunPod, secure cloud): $1.95 per 10k tasks — 1.43 s/call mean over 17 cases x $0.49/h as of 2026-10-02 — serial, 1,812,625 tasks per card-month — modelled on reply-draft__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x runpod/l4-secure
mistralai/mistral-small-3.2-24b-instruct on L4 24 GB (Scaleway, on-demand PAR-1): €3.14 per 10k tasks — 1.43 s/call mean over 17 cases x €0.79/h as of 2026-10-02 — serial, 1,812,625 tasks per card-month — modelled on reply-draft__mistralai_mistral-small-3.2-24b-instruct-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**reply-draft · openai/gpt-oss-20b**
```
wall: 3.01 s/call mean over 17 of 17 cases (reply-draft__openai_gpt-oss-20b-2026-09-27.json, model openai/gpt-oss-20b) — measured on the HOSTED endpoint, not on the card
openai/gpt-oss-20b on L4 24 GB (RunPod, secure cloud): $4.09 per 10k tasks — 3.01 s/call mean over 17 cases x $0.49/h as of 2026-10-02 — serial, 862,194 tasks per card-month — modelled on reply-draft__openai_gpt-oss-20b-2026-09-27.json hosted wall x runpod/l4-secure
openai/gpt-oss-20b on L4 24 GB (Scaleway, on-demand PAR-1): €6.60 per 10k tasks — 3.01 s/call mean over 17 cases x €0.79/h as of 2026-10-02 — serial, 862,194 tasks per card-month — modelled on reply-draft__openai_gpt-oss-20b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
**reply-draft · qwen/qwen3-14b**
```
wall: 4.17 s/call mean over 17 of 17 cases (reply-draft__qwen_qwen3-14b-2026-09-27.json, model qwen/qwen3-14b) — measured on the HOSTED endpoint, not on the card
qwen/qwen3-14b on L4 24 GB (RunPod, secure cloud): $5.67 per 10k tasks — 4.17 s/call mean over 17 cases x $0.49/h as of 2026-10-02 — serial, 622,163 tasks per card-month — modelled on reply-draft__qwen_qwen3-14b-2026-09-27.json hosted wall x runpod/l4-secure
qwen/qwen3-14b on L4 24 GB (Scaleway, on-demand PAR-1): €9.14 per 10k tasks — 4.17 s/call mean over 17 cases x €0.79/h as of 2026-10-02 — serial, 622,163 tasks per card-month — modelled on reply-draft__qwen_qwen3-14b-2026-09-27.json hosted wall x scaleway/l4-1-24g
```
