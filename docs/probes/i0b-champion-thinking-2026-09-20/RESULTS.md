# I0b / I0c — is the I0 token cut a champion delta, and is it just a template switch? (2026-09-20, 15:18–15:36)

> **EVIDENCE CELL (I0c):** `task-intake @ mlx-community/gemma-4-e2b-it-4bit, thinking OFF via the chat template (chat_template_kwargs.enable_thinking=false)` **vs** the same model **+ the I0 LoRA adapter** (18 Sep, `docs/probes/i0-mlx-lora-2026-09-18/results-adapter.json`) — same output-token regime (2,848 vs 2,636 completion tokens over 46 cases, 0 reasoning chars both), **switch heldout 17/20 · train 15/26 vs adapter heldout 18/20 · train 25/26**; the switch loses 7 cases against the thinking base (0 up), the adapter passes 5 of those 7. **The fine-tune's value is the judgement it keeps without thinking, not the tokens — the tokens a template flag buys for free.**
>
> **Not evidence:** I0b(a) (a same-day champion read — a reference row, not a pair); I0b(b) (a precondition, one pass); the switch probe's default arm (a faithfulness check of the probe path: it reproduces the runner's base arm exactly — 20/26 · 19/20 · 17,357 tokens).

## I0b(a) — the same-day champion row (through the real runner, `run task-intake`, Ollama 0.33.2)

| task-intake, 46 cases, 20 Sep | train | heldout | completion tokens | reasoning chars | wall |
|---|---|---|---|---|---|
| **champion** `gemma4:e2b-it-qat` via Ollama | 24/26 | 19/20 | 20,307 | 66,164 | 310 s |
| MLX base `gemma-4-e2b-it-4bit` (18 Sep) | 20/26 | 19/20 | 17,357 | 52,168 | 294 s |
| MLX + LoRA (18 Sep) | 25/26 | 18/20 | 2,636 | 0 | 73 s |

The champion thinks as much as the MLX base does, so the I0 delta is a champion delta: **−87% completion tokens, 4.2× wall, heldout −1 at N=20 (one pass).** Reference row, not a pair (different runtime, different build).

## I0b(b) — precondition for I2-on-crm: do tool trajectories pass through mlx_lm.server?

`run crm-followup --provider mlx --model default_model` (base, no adapter, one pass): **rc 0, train 16/20, heldout 12/18** (`results-crm-mlx-base.json`). The crm protocol is text-JSON (`{"tool":…}` / `{"answer":…}`), not native tool calls, so it needs nothing from the server. Champion on Ollama for reference: 12/20 · 15/18. Mixed like the plain-e2b Ollama arm (E31b); one pass, not a verdict. **I2 on crm is buildable.**

## I0c — the thinking switch (NOT through the real entry point — declared)

The gemma-4 chat template injects `<|think|>` unless `enable_thinking=False`; mlx_lm.server accepts `chat_template_kwargs` in the request body; the router's `body_from_env` carries strings only, so this probe called the server directly for all 46 cases, parsed with `runner.extract_json` (same parser, **no re-ask retry** — harsher than the runner) and scored with `runner.score_labels` + the exam's `properties.py` (E38 pattern). `thinking_switch_probe.py`, raw in `thinking_switch_raw.json`.

| arm | train | heldout | completion tokens | reasoning chars | wall |
|---|---|---|---|---|---|
| default (thinking on) — faithfulness check | 20/26 | 19/20 | 17,357 | 52,168 | 304 s |
| **thinking OFF** (template flag) | **15/26** | **17/20** | 2,848 | 0 | 59 s |
| + LoRA adapter (18 Sep, through the runner) | 25/26 | 18/20 | 2,636 | 0 | 73 s |

Switch vs default: **0 up / 7 down** — none are parse failures (every output was a fenced JSON the parser read); 4 are the wrong agent (`triage-bare-recruiter`, `triage-sort-accountant`, `transcript-bare` → reply-draft; `expense-book-anthropic` → none), 3 are hand-over rule failures (`recap-daily-please` verbatim span; `none-book-train`, `none-translate-contract-bait` hand something over on a `none`). **The adapter passes 5 of the 7** (all but `expense-book-anthropic` and `transcript-bare`, which the adapter also fails).

## Verdicts

- **Check 1 (champion delta): upheld.** The Ollama champion spends the thinking preamble too (66k reasoning chars); −87% tokens is against the champion, not an artefact of the MLX build.
- **Check 2 (is it a switch?): the tokens are, the score is not.** Turning thinking off costs 2 heldout + 5 train cases; the fine-tune keeps the score (−1 heldout) at the same token cost. Registered reading for the page: *"the fine-tune keeps the model's judgement after you remove its thinking; the flag alone does not."*
- Small N throughout (one pass each; 20 heldout cases). The probe's no-retry harshness did not bite (default arm reproduced the runner exactly).

## What this cannot say
- Whether the champion on Ollama has an equivalent thinking-off switch (its template was not probed; the Modelfile carries none).
- Whether the adapter's judgement holds on a bigger or different heldout — that is the pilot's data.
