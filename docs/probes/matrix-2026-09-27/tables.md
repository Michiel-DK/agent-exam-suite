
### Call summary + action items (`transcript-en`, 19 held-out cases; 12 candidates competed, 3 within one case of the best)

| model | can run on | heldout | pass^k | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|---|
| x-ai/grok-4.6 | vendor only | **14**/19 | 1 run | 17.2 | 1360 | 0 | 133 (ledger) | pinned |
| moonshotai/kimi-k3 | own VM, GPU node | **14**/19 | 1 run | 25.6 | 788 | 1 | 167 (ledger) | pinned |
| openai/gpt-5.6-sol | vendor only | **13**/19 | 1 run | 4.7 | 309 | 0 | 78 (ledger) | pinned |
| openai/gpt-5.4-mini | vendor only | **12**/19 | 1 run | 1.4 | 145 | 0 | 24 (ledger) | pinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **12**/19 | 1 run | 3.2 | 135 | 0 | 2.68 (ledger) | unpinned |
| deepseek/deepseek-v4-pro-0813 | own VM, GPU node | **12**/19 | 1 run | 9.3 | 446 | 7 | 21 (ledger) | unpinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **11**/19 | 1 run | 4.3 | 124 | 0 | 2.70 (ledger) | unpinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **11**/19 | 1 run | 8.7 | 519 | 0 | 4.14 (ledger) | unpinned |
| z-ai/glm-5.3 | own VM, GPU node | **10**/19 | 1 run | 9.9 | 821 | 4 | 62 (ledger) | pinned |
| gemma4-e4b-ctx16k (local champion, 3-load snapshot 2026-09-08) | local machine | **10**/19 | pass^3 10/19 | 26.1 | 813 | 0 | ≈0 | snapshot |
| openai/gpt-oss-20b | own VM, one 24 GB card | **9**/19 | 1 run | 5.5 | 419 | 1 | 0.78 (ledger) | unpinned |
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **6**/19 | 1 run | 2.8 | 141 | 0 | 2.72 (ledger) | unpinned |

### CRM field write-back from a call (`call-fields`, 19 held-out cases; 10 candidates competed, 1 within one case of the best)

| model | can run on | heldout | pass^k | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|---|
| moonshotai/kimi-k3 | own VM, GPU node | **17**/19 | 1 run | 12.8 | 480 | 0 | 140 (ledger) | pinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **15**/19 | 1 run | 2.7 | 75 | 0 | 2.88 (ledger) | unpinned |
| openai/gpt-5.6-sol | vendor only | **15**/19 | 1 run | 3.2 | 116 | 0 | 65 (ledger) | pinned |
| openai/gpt-oss-20b | own VM, one 24 GB card | **15**/19 | 1 run | 7.9 | 367 | 0 | 0.83 (ledger) | unpinned |
| z-ai/glm-5.3 | own VM, GPU node | **15**/19 | 1 run | 27.4 | 733 | 1 | 69 (ledger) | pinned |
| gemma4-e4b-ctx16k (local champion, 3-load snapshot 2026-09-26) | local machine | **14**/19 | pass^3 14/19 | | | 0 | ≈0 | snapshot |
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **13**/19 | 1 run | 4.3 | 81 | 0 | 2.92 (ledger) | unpinned |
| openai/gpt-5.4-mini | vendor only | **11**/19 | 1 run | 1.4 | 53 | 0 | 23 (ledger) | pinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **11**/19 | 1 run | 4.0 | 75 | 0 | 2.85 (ledger) | unpinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **11**/19 | 1 run | 9.2 | 441 | 0 | 4.39 (ledger) | unpinned |

### Account brief over the CRM (tool calls) (`crm-followup`, 18 held-out cases; 12 candidates competed, 3 within one case of the best)

| model | can run on | heldout | pass^k | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|---|
| x-ai/grok-4.6 | vendor only | **16**/18 | 1 run | 10.2 | 692 | 0 | 164 (ledger) | pinned |
| deepseek/deepseek-v4-pro-0813 | own VM, GPU node | **15**/18 | 1 run | 10.3 | 368 | 0 | 43 (ledger) | unpinned |
| gemma4-e2b-ctx16k (local champion, 3-load snapshot 2026-09-07) | local machine | **15**/18 | pass^3 15/18 | 12.8 | 600 | 0 | ≈0 | snapshot |
| google/gemma-4-31b-it | own VM, one 48 GB card | **14**/18 | 1 run | 5.3 | 103 | 0 | 5.41 (ledger) | unpinned |
| openai/gpt-5.6-sol | vendor only | **14**/18 | 1 run | 6.5 | 164 | 0 | 127 (ledger) | pinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **13**/18 | 1 run | 4.2 | 106 | 0 | 5.01 (ledger) | unpinned |
| z-ai/glm-5.3 | own VM, GPU node | **12**/18 | 1 run | 12.4 | 622 | 0 | 101 (ledger) | pinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **11**/18 | 1 run | 21.3 | 817 | 0 | 7.48 (ledger) | unpinned |
| openai/gpt-5.4-mini | vendor only | **10**/18 | 1 run | 3.2 | 138 | 0 | 34 (ledger) | pinned |
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **10**/18 | 1 run | 3.7 | 106 | 0 | 4.79 (ledger) | unpinned |
| moonshotai/kimi-k3 | own VM, GPU node | **9**/18 | 1 run | 23.6 | 474 | 1 | 226 (ledger) | pinned |
| openai/gpt-oss-20b | own VM, one 24 GB card | **1**/18 | 1 run | 3.4 | 101 | 22 | 0.16 (ledger) | unpinned |

### Digest of many items (`recap`, 10 held-out cases; 8 candidates competed, 5 within one case of the best)

| model | can run on | heldout | pass^k | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|---|
| openai/gpt-5.6-sol | vendor only | **8**/10 | 1 run | 4.6 | 201 | 0 | 44 (ledger) | pinned |
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **7**/10 | 1 run | 2.2 | 114 | 0 | 1.59 (ledger) | unpinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **7**/10 | 1 run | 3.0 | 93 | 0 | 1.53 (ledger) | unpinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **7**/10 | 1 run | 5.1 | 83 | 0 | 1.53 (ledger) | unpinned |
| gemma4:e4b-it-qat (local champion, 3-load snapshot 2026-09-07) | local machine | **7**/10 | pass^3 7/10 | 26.8 | 891 | 0 | ≈0 | snapshot |
| qwen/qwen3-14b | own VM, one 24 GB card | **6**/10 | 1 run | 8.7 | 574 | 0 | 3.11 (ledger) | unpinned |
| openai/gpt-5.4-mini | vendor only | **5**/10 | 1 run | 1.2 | 103 | 0 | 14 (ledger) | pinned |
| openai/gpt-oss-20b | own VM, one 24 GB card | **3**/10 | 1 run | 6.1 | 525 | 0 | 0.70 (ledger) | unpinned |

### Email triage (`email-triage`, 11 held-out cases; 8 candidates competed, 8 within one case of the best)

| model | can run on | heldout | pass^k | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|---|
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **10**/11 | 1 run | 0.7 | 9 | 0 | 0.22 (ledger) | unpinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **10**/11 | 1 run | 0.9 | 10 | 0 | 0.23 (ledger) | unpinned |
| openai/gpt-5.4-mini | vendor only | **10**/11 | 1 run | 0.9 | 10 | 0 | 1.98 (ledger) | pinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **10**/11 | 1 run | 2.2 | 10 | 0 | 0.24 (ledger) | unpinned |
| gemma4:e2b-it-qat (local champion, 3-load snapshot 2026-09-07) | local machine | **10**/11 | pass^3 10/11 | 5.7 | 400 | 0 | ≈0 | snapshot |
| openai/gpt-5.6-sol | vendor only | **9**/11 | 1 run | 1.2 | 17 | 0 | 5.72 (ledger) | pinned |
| openai/gpt-oss-20b | own VM, one 24 GB card | **9**/11 | 1 run | 1.3 | 70 | 0 | 0.11 (ledger) | unpinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **9**/11 | 1 run | 5.1 | 318 | 0 | 1.02 (ledger) | unpinned |

### Expense fields (`expense-categorization`, 9 held-out cases; 8 candidates competed, 8 within one case of the best)

| model | can run on | heldout | pass^k | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|---|
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **9**/9 | 1 run | 0.8 | 15 | 0 | 0.22 (ledger) | unpinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **9**/9 | 1 run | 0.8 | 15 | 0 | 0.23 (ledger) | unpinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **9**/9 | 1 run | 1.4 | 16 | 0 | 0.23 (ledger) | unpinned |
| openai/gpt-5.4-mini | vendor only | **8**/9 | 1 run | 0.8 | 14 | 0 | 2.03 (ledger) | pinned |
| openai/gpt-5.6-sol | vendor only | **8**/9 | 1 run | 1.3 | 18 | 0 | 5.49 (ledger) | pinned |
| openai/gpt-oss-20b | own VM, one 24 GB card | **8**/9 | 1 run | 2.2 | 127 | 0 | 0.16 (ledger) | unpinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **8**/9 | 1 run | 3.8 | 227 | 0 | 0.78 (ledger) | unpinned |
| gemma4:e2b-it-qat (local champion, 3-load snapshot 2026-09-07) | local machine | **8**/9 | pass^3 8/9 | 4.4 | 280 | 0 | ≈0 | snapshot |

### Reply draft (`reply-draft`, 10 held-out cases; 8 candidates competed, 8 within one case of the best)

| model | can run on | heldout | pass^k | s/call | out tok/call | died | $/10k (rate) | run |
|---|---|---|---|---|---|---|---|---|
| openai/gpt-5.4-mini | vendor only | **10**/10 | 1 run | 1.2 | 73 | 0 | 5.06 (ledger) | pinned |
| mistralai/mistral-small-3.2-24b-instruct | own VM, one 24–48 GB card | **10**/10 | 1 run | 1.4 | 64 | 0 | 0.39 (ledger) | unpinned |
| google/gemma-4-26b-a4b-it | own VM, one 24 GB card | **10**/10 | 1 run | 2.2 | 87 | 0 | 0.49 (ledger) | unpinned |
| google/gemma-4-31b-it | own VM, one 48 GB card | **10**/10 | 1 run | 2.2 | 80 | 0 | 0.50 (ledger) | unpinned |
| openai/gpt-5.6-sol | vendor only | **10**/10 | 1 run | 2.9 | 112 | 0 | 16 (ledger) | pinned |
| qwen/qwen3-14b | own VM, one 24 GB card | **10**/10 | 1 run | 4.2 | 248 | 0 | 0.89 (ledger) | unpinned |
| gemma4:e2b-it-qat (local champion, 3-load snapshot 2026-09-07) | local machine | **10**/10 | pass^3 10/10 | 8.6 | 571 | 0 | ≈0 | snapshot |
| openai/gpt-oss-20b | own VM, one 24 GB card | **9**/10 | 1 run | 3.0 | 155 | 0 | 0.19 (ledger) | unpinned |

### Deaths by recorded cause (arm → {cause: count}); a death is a failed case with no parseable answer

- `call-fields` z-ai/glm-5.3: {'no_answer': 1}
- `crm-followup` moonshotai/kimi-k3: {'no_answer': 1}
- `crm-followup` openai/gpt-oss-20b: {'no_answer': 22}
- `transcript-en` deepseek/deepseek-v4-pro-0813: {'no_answer': 7}
- `transcript-en` moonshotai/kimi-k3: {'no_answer': 1}
- `transcript-en` openai/gpt-oss-20b: {'no_answer': 1}
- `transcript-en` z-ai/glm-5.3: {'no_answer': 4}
