# Qwen ladder, local rung — PARTIAL (9 of 14 tasks), 2026-08-15

> First model measurement on the oracle-verified replay pool (15 tasks, PR #47 / ledger
> 022). **PARTIAL: the run was operator-stopped mid-task 10 of 14** (machine-load
> concern); the 9 completed task results are preserved and analysed here, the remaining 5
> are queued. **The 14B rung is on operator hold** (9.3 GB weights + ~3.8 GB KV at 24k
> context against 16 GB unified memory). Raw results:
> `docs/e-corpus-results/attempts_qwen3-8b-ctx24k_2026-08-15_partial.json`.

## Design (the fairness rules, applied)

- Model: `qwen3-8b-ctx24k` — a `FROM qwen3:8b` variant with `num_ctx 24576` baked in
  (E22: a request-level `num_ctx` never reaches the model through the compat endpoint).
  Temperature 0.0 per request through the real `sandbox/router.py` adapter.
- **Per-task `MAX_TOKENS`**, identical across models: `answer_chars/2.5 + 6000` thinking
  headroom, capped to fit beside the prompt in context, floor 8000. The flat 4000 cap is
  what manufactured qwen3's zero on 2026-08-01; that mistake is not repeated here.
- **#369 excluded, recorded, NOT scored:** its 114k-char prompt (~33k tokens) exceeds
  num_ctx=24576 and Ollama truncates silently — a score would grade a mangled prompt and
  report it as model incapacity. Pool run = 12 create + #795 + #655 (modify).
- Human oracle baseline on these exact tasks, same pipeline: **12/12 create, 3/3 of the
  admitted modifies** — so every zero below is the model, not the harness.

## Result: strict CI gate 0/9 — but the failures have structure

| PR | type | reply | wall | died at | gating test detail |
|---|---|---|---|---|---|
| 422 | create | 2.5k ch | 697s | s4 test | **14/15 tests pass**, 1 fails |
| 1052 | create | 0.9k ch | 251s | s4 test | 8/11 pass |
| 423 | create | 2.6k ch | 157s | s4 test | 15/18 pass |
| 1058 | create | 38.8k ch | 801s | **s2 parse** | no complete file recovered |
| 1142 | create | 4.4k ch | 345s | s4 test | 17/19 pass |
| 1050 | create | 7.6k ch | 531s | s4 test | 7/21 pass |
| 1169 | create | 40.9k ch | 1410s | **s2 parse** | no complete file recovered |
| 636 | create | 22.3k ch | 1676s | **s2 parse** | no complete file recovered |
| 433 | create | 4.8k ch | 204s | s4 test | **31/32 tests pass**, 1 fails |

Two failure modes, cleanly separated by the staged grading:

1. **Near-miss (6/9):** the model writes a compiling module that passes **76–97% of the
   individual tests** in its gating file and misses 1–14. On #433 it is one assert away
   from a real CI pass. This is a *discriminating band* — exactly the structure a
   frontier comparison can bite on, and what the old easy band lacked.
2. **Termination death (3/9):** on the largest-answer tasks the model generates
   22k–41k chars over 13–28 minutes and no complete file can be recovered, at a 3–5×
   larger budget than the one first blamed for it. Budget was not the binding
   constraint; the disposition is.
   - ⚠️ **CORRECTED 2026-08-27 (TERMINATION-DETECT scoping).** These three are NOT all
     "thinking eats the budget". Budgets recomputed against
     `~/.cache/agent-sandbox-replay/tasks.json`: all three hit their cap EXACTLY (#1058
     9886, #1169 9955, #636 13386) while all six near-misses came in at 15–40 % of
     budget — so *hitting the cap* is what separates the two bands. But the deaths
     split into two different modes: **#1058 and #1169 emitted `content_chars == 0`**
     (thinking consumed the whole budget, the documented qwen3 signature), while
     **#636 emitted 22 349 chars of CONTENT and was cut off mid-answer** — it was
     writing the file, not thinking about it. One sentence cannot cover both, and the
     fix each needs is different.

## What is and is not claimed

✅ The local 8B currently passes **zero** of these real merged-PR tasks under the real CI
gate, while the human answers pass 12/12 — but on two-thirds of attempts it is within a
few asserts of green. ⛔ NOT claimed: a 14-task number (5 unrun), anything about the 14B
(held), anything about frontier models (key-gated), or per-test partial credit as a score
— the exam's gate is the PR's own CI test, pass/fail, and stays that way.

## Restart — everything needed, in one place

The driver is session-scratchpad-born, so it is preserved here verbatim (the
`build_candidates.py` preservation lesson, applied on day one). Save as
`$REPLAY_WORK/ladder.py`. To resume the 8B rung, set `POOL` to the 5 remaining:
`[801, 670, 993, 795, 655]`, then:

```sh
cd ~/.cache/agent-sandbox-replay && python3 -u ladder.py qwen3-8b-ctx24k q8
```

For the 14B rung (when the machine is free — or skip it; size-is-not-the-lever is
already documented for recap): recreate the variant first:

```sh
printf 'FROM qwen3:14b\nPARAMETER num_ctx 24576\n' > /tmp/Modelfile.q14
ollama create qwen3-14b-ctx24k -f /tmp/Modelfile.q14    # ~13 GB working set at 24k
python3 -u ladder.py qwen3-14b-ctx24k q14               # full POOL, same budgets
```

Per-task results land as `$REPLAY_WORK/attempts_<tag>_<pr>.json`; merge into
`docs/e-corpus-results/` like the partial file above. Frontier rung: same driver, a
`scaleway`-served large Qwen via `PROVIDERS` once a `SCALEWAY_API_KEY` exists — never a
Claude model (`mast` is Claude-authored; self-replay).

```python
"""Qwen ladder driver — per-task MAX_TOKENS, identical across models."""
import json, os, subprocess, sys

W = os.path.expanduser("~/.cache/agent-sandbox-replay")
REPLAY = os.path.expanduser("~/code/Michiel-DK/agent-sandbox/sandbox/replay")
POOL = [422, 1052, 423, 1058, 1142, 1050, 1169, 636, 433, 801, 670, 993, 795, 655]
CTX = 24576

def budget(t):
    if t.get("type") == "create":
        ans = sum(f["merged_chars"] for f in t["new_files"])
    else:
        ans = sum(len(p["text"]) for p in t["functions"])
    return max(8000, min(int(ans / 2.5) + 6000,
                         int(CTX - t["prompt_chars"] / 3.5 - 768)))

def main():
    model, tag = sys.argv[1], sys.argv[2]
    tasks = {t["pr"]: t for t in json.load(open(f"{W}/tasks.json"))}
    for pr in POOL:
        mt = budget(tasks[pr])
        print(f"=== {model} PR#{pr} MAX_TOKENS={mt}", flush=True)
        env = {**os.environ, "MAX_TOKENS": str(mt)}
        p = subprocess.run([sys.executable, "-u", "attempt.py", model, str(pr),
                            f"{tag}_{pr}"], cwd=REPLAY, env=env)
        if p.returncode != 0:
            print(f"!!! attempt.py rc={p.returncode} on PR#{pr}", flush=True)
    print(f"LADDER DONE {model}", flush=True)

if __name__ == "__main__":
    main()
```
