#!/usr/bin/env python3
"""I2 v4 = I2 v3's rows, recut: ONE example per assistant step. example k of a row = messages[:k+1] where message k is
an assistant step (a tool call or the answer); mlx_lm.lora --mask-prompt then puts the loss on that step only (mlx_lm
0.31.3 tuner/datasets.py: offset = tokens of messages[:-1], add_generation_prompt when the last role is assistant).
Rows are read from the committed v3 data (train.jsonl / valid.jsonl) — no new harvest, no new leak surface: every
example is a prefix of a row that passed the v3 leak guard. Prints the share of characters the loss sees, v3-style
(whole row) vs v4-style (last assistant message per example)."""
import json, pathlib
HERE = pathlib.Path(__file__).resolve().parent; V3 = HERE.parent / "i2v3-crm-lora-2026-09-21" / "data"; OUT = HERE / "data"
def cut(rows):
    ex = []
    for m in rows:
        for k, msg in enumerate(m):
            if msg["role"] == "assistant": ex.append(m[:k + 1])
    return ex
def share_v3(rows): return sum(len(x["content"]) for m in rows for x in m if x["role"] == "assistant") / sum(len(x["content"]) for m in rows for x in m)
def share_v4(exs): return sum(len(e[-1]["content"]) for e in exs) / sum(len(x["content"]) for e in exs for x in e)
MAX_SEQ = 6144   # must equal --max-seq-length: an example whose PROMPT alone exceeds it is truncated to zero target tokens
                 # and mlx_lm's masked loss goes NaN (attempt 1, 21 Sep 19:15: NaN from iter 30, one such example) and poisons the adapter
from huggingface_hub import snapshot_download
from mlx_lm import load
_, tok = load(snapshot_download("mlx-community/gemma-4-e2b-it-4bit"))   # the model's own tokenizer (mlx_lm 0.31.3 has no standalone loader)
def ntok(m): return len(tok.apply_chat_template(m, tokenize=True, add_generation_prompt=False))
prov = {}
for split in ("train", "valid"):
    rows = [json.loads(l)["messages"] for l in (V3 / f"{split}.jsonl").read_text().splitlines() if l.strip()]
    exs = cut(rows)
    dropped = [(i, ntok(e)) for i, e in enumerate(exs) if ntok(e) > MAX_SEQ]
    exs = [e for i, e in enumerate(exs) if i not in {d[0] for d in dropped}]
    print(f"{split}: dropped {len(dropped)} example(s) over {MAX_SEQ} tokens: {dropped}")
    for e in exs: assert e[-1]["role"] == "assistant" and e[-1]["content"].lstrip().startswith(("{", "```"))  # 2 rows carry fenced JSON; the runner parses fences
    OUT.mkdir(exist_ok=True)
    (OUT / f"{split}.jsonl").write_text("\n".join(json.dumps({"messages": e}, ensure_ascii=False) for e in exs) + "\n")
    steps = {}
    for e in exs: steps[len([x for x in e if x["role"] == "assistant"])] = steps.get(len([x for x in e if x["role"] == "assistant"]), 0) + 1
    prov[split] = {"rows": len(rows), "examples": len(exs), "examples_by_step_index": steps,
                   "loss_char_share_v3_whole_row": round(share_v3(rows), 4), "loss_char_share_v4_masked": round(share_v4(exs), 4), "dropped_over_max_seq": dropped}
    print(f"{split}: {len(rows)} rows -> {len(exs)} examples; step index histogram {dict(sorted(steps.items()))}; "
          f"loss sees {prov[split]['loss_char_share_v3_whole_row']:.1%} of chars unmasked (v1–v3) vs {prov[split]['loss_char_share_v4_masked']:.1%} of chars as the target (v4, the rest masked)")
(OUT / "test.jsonl").write_text((OUT / "valid.jsonl").read_text())
(OUT / "provenance.json").write_text(json.dumps({"source": "docs/probes/i2v3-crm-lora-2026-09-21/data (v3 provenance applies)", **prov}, indent=1))
