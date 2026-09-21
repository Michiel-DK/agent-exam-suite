# I0 — mlx-lm LoRA feasibility on this 16 GB Mac (sprint I, batch 2) — 2026-09-18

> **EVIDENCE CELL:** `task-intake @ mlx-community/gemma-4-e2b-it-4bit via mlx_lm.server, base` **vs** `+ LoRA adapter (8 layers, 120 iters, 22 TRAIN rows, 9 min 17 s)`, both through `runner.py run --provider mlx` (lane worktree `lane/mlx-provider`), one pass each, 46 cases: **train 20/26 → 25/26, heldout 19/20 → 18/20 (0 up / 1 down), completion tokens 17,357 → 2,636 (−85%), reasoning chars 52,168 → 0, wall 294 s → 73 s.**
>
> **Not evidence:** the heldout DELTA (self-distilled targets on 22 train cases, one pass, no loads — a feasibility spike, not a rule-A snapshot); the wall times (one machine, uninstrumented).

## Registered before the run (18 Sep, 18:0x — file mtime precedes `logs/i0.log` START 18:10:39)
- Model: `mlx-community/gemma-4-e2b-it-4bit` (the crm/task-intake champion family, post-hoc 4-bit MLX build — NOT the Ollama QAT Q4_0 tag, so base ≠ champion snapshot by construction).
- **Prediction:** (1) LoRA on 8 layers, 120 iters, batch 2, trains in **< 30 min**; (2) the mlx server serves the adapter and the runner passes every case through (≥ 44/46 parseable); (3) base heldout lands within 2 of the Ollama champion's 19/20; (4) adapter heldout ≥ base heldout is **NOT predicted** — small N, self-distilled targets; any move either way is reported, not claimed.
- **Kill (sprint-map I0):** training > 2 h, or the served model cannot pass through `run`.
- Leak guard: `build_data.py --selftest` must print `guard RED` before the real build runs (in `i0.sh`).

## What ran (18:10–18:35)

| step | result |
|---|---|
| data | `build_data.py`: 22 train + 4 valid rows from the TRAIN split, targets = the champion's own passing outputs (24/26) else the case; leak guard **seen RED** on a planted heldout row before the real build (`logs/i0.log`) |
| LoRA | `mlx_lm.lora`, 8 layers, rank default, batch 2, 120 iters, lr 1e-4, max-seq 1536 → **9 min 17 s**, val loss 4.25 → 0.41, 3.4M trainable params (0.074%), peak mem 10.3 GB (`logs/lora.log`) |
| base arm | `run task-intake --provider mlx --model default_model`: **train 20/26 · heldout 19/20**, 294 s (`results-base.json`) |
| adapter arm | same + `MLX_ADAPTER_PATH`: **train 25/26 · heldout 18/20**, 73 s (`results-adapter.json`) |

Per case, adapter vs base: **6 up, all train, all six ARE in the training set** (`triage-bare-client-email`, `recap-end-of-day`, `transcript-proper-english`, `none-pause-email-bait`, `heavy-question-inside-email-crm`, `heavy-none-edit-document-client-bait`) — memorised targets, exactly what "iterate on train" allows and exactly why train is not evidence. **2 down:** `transcript-bare` (heldout — the hand-over property fails on the adapter's shorter output; base passed) and `expense-book-anthropic` (train, IN the training set, yet the adapter answers `none` — an under-fit on a 22-row set, not a leak). 30/46 outputs byte-identical between arms.

**The finding that carries:** the adapter removed the model's thinking channel entirely (reasoning chars 52,168 → 0) — the base emits a `<|channel>thought` preamble on every case and the adapter answers with the JSON only. That is **−85% output tokens and 4× wall at a held score band** (heldout −1 at N=20, one pass), on 22 examples and nine minutes of training. This is the "same score, fewer tokens" class from the optimisation table, produced by a fine-tune instead of a prompt knob.

## Prediction and kill verdicts

| registered | verdict |
|---|---|
| (1) trains in < 30 min | **Upheld**: 9 min 17 s |
| (2) server serves the adapter, runner passes every case through (≥ 44/46 parseable) | **Upheld after a fix**: 46/46 parseable on both arms — but see "what broke" |
| (3) base heldout within 2 of the Ollama champion's 19/20 | **Upheld**: 19/20 = 19/20 |
| (4) adapter heldout ≥ base: NOT predicted | Not claimed: 18/20 vs 19/20, one case, one pass |
| kill: training > 2 h | did not fire |
| kill: served model cannot pass through `run` | did not fire (after the fix) |

## What broke, and the one-line router change it forced (gotcha 1: presence is not effect)

1. First arms (`i0.sh`): the runner sent `model=gemma-4-e2b-it-4bit`; mlx_lm.server treats the request's model as a repo id and 404'd against Hugging Face. Fix: send `default_model`, which maps to the server's CLI `--model`.
2. Second arms (`i0-arms.sh`): base and adapter scored **identically, 46/46 outputs byte-identical, 17,357 = 17,357 completion tokens** — the adapter was never applied. `mlx_lm.server` 0.31.3 applies an adapter ONLY when the request body carries `"adapters": <path>`; `--adapter-path` on the CLI is inert for `default_model` (verified three ways: direct `mlx_lm.load(adapter_path=…)` changes the output; a server request with the body key changes it; the flag alone does not).
3. Fix in the lane worktree (`sandbox/router.py`, `full` file): `PROVIDERS["mlx"]` carries `"body_from_env": {"adapters": "MLX_ADAPTER_PATH"}`; `get_adapter` resolves it; `ChatCompletionsAdapter` merges `extra_body` into the request. Empty for every committed provider → byte-identical bodies (pinned by `sandbox/test_mlx_provider.py`, 19 checks incl. one seen red; `test_router_knobs.py` still green). Third arm (`i0-adapter-arm.sh`) is the evidence cell.

## What this cannot say

- Not a rule-A snapshot: one pass, no loads; the `mlx` provider has no runtime-version endpoint yet, so `--snapshot` would refuse. A champion-type promotion (I3) needs that plumbing.
- Heldout −1 is one case at N=20: neither a gain nor a loss is claimed. Train +5 is memorisation and is not evidence.
- The −85% tokens is against THIS base build, which thinks by default; the Ollama champion (`gemma4:e2b-it-qat`) may or may not spend the same preamble — its snapshot does not carry per-case reasoning chars for task-intake (not checked here).
- Tool-calling (crm) through mlx_lm.server: untested. The adapter weights (`adapters/`, 13.6 MB ×2) are NOT committed; the data + scripts reproduce them.
