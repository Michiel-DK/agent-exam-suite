#!/usr/bin/env python3
"""I0 training set for task-intake — TRAIN split only, chat-format jsonl for mlx_lm.lora.
Target per case: {"agent": expected.agent, "input": <the champion's own passing output's input
field when its results file has one, else the case input, else "" for none>} — self-distilled
targets on TRAIN cases (feasibility spike; NOT a claim about accuracy). Leak guard: no heldout
case input text (or a 40-char window of it) may appear in any written line; the guard is
exercised RED by --selftest before it is trusted.
"""
import json, pathlib, random, sys
ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = pathlib.Path(__file__).resolve().parent / "data"
cases = json.loads((ROOT / "evals/task-intake/cases.json").read_text())["cases"]
system = (ROOT / "agents/task-intake/prompt.md").read_text()
got = {}
rf = ROOT / "results/task-intake__ollama__gemma4_e2b-it-qat.json"
if rf.exists():
    for c in json.loads(rf.read_text())["cases"]:
        if c.get("passed") and isinstance(c.get("got"), dict):
            got[c["id"]] = c["got"]
train = [c for c in cases if c["split"] == "train"]
heldout = [c for c in cases if c["split"] == "heldout"]

def target(c):
    agent = c["expected"]["agent"]
    if agent == "none":
        return {"agent": "none", "input": ""}
    g = got.get(c["id"])
    return {"agent": agent, "input": g["input"] if g and isinstance(g.get("input"), str) else c["input"]}

def row(c):
    return {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": c["input"]},
                         {"role": "assistant", "content": json.dumps(target(c), ensure_ascii=False)}]}

def leak_guard(lines: list[str]):
    blob = "\n".join(lines)
    for h in heldout:
        t = h["input"].strip()
        needles = {t} | {t[i:i + 40] for i in range(0, max(1, len(t) - 40), 20)} if len(t) >= 40 else {t}
        for n in needles:
            if n and n in blob:
                raise SystemExit(f"LEAK: heldout case {h['id']!r} text found in training data: {n[:60]!r}")

if "--selftest" in sys.argv:  # the guard must fire on a planted heldout line
    try:
        leak_guard([json.dumps(row(heldout[0]))]); print("SELFTEST FAILED: guard stayed green"); sys.exit(1)
    except SystemExit as e:
        if str(e).startswith("LEAK"): print("selftest: guard RED as required ->", str(e)[:80]); sys.exit(0)
        raise

random.Random(31).shuffle(train)
valid, tr = train[:4], train[4:]
OUT.mkdir(exist_ok=True)
tl = [json.dumps(row(c), ensure_ascii=False) for c in tr]
vl = [json.dumps(row(c), ensure_ascii=False) for c in valid]
leak_guard(tl + vl)
(OUT / "train.jsonl").write_text("\n".join(tl) + "\n"); (OUT / "valid.jsonl").write_text("\n".join(vl) + "\n")
(OUT / "test.jsonl").write_text("\n".join(vl) + "\n")  # mlx_lm wants the file; never heldout
print(f"train {len(tl)} rows, valid {len(vl)} rows, targets from champion outputs: {sum(c['id'] in got for c in train)}/{len(train)}; heldout untouched ({len(heldout)})")
