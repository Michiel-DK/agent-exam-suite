#!/usr/bin/env python3
"""I2 v2 rows for crm-followup — TRAIN split, single-turn AND multi-turn, replayed from PASSING trajectories in
results files that carry the per-turn record (PR #96: raw_steps, per-turn tool_results, got). Reconstruction is the
runner's own rule (sandbox/test_per_turn_trace.py::_history): system → per turn: user line, then (assistant raw
step, user {"tool_result": …}) per tool call, then the assistant answer step. Sources in priority order; a case is
taken from the first source where it PASSED. Row floor: fewer than FLOOR rows → exit 4 and do not train.
Leak guard: heldout input text (or a 40-char window) in any written line is a LEAK unless that exact text sits in a
committed TRAIN input (declared overlap). --selftest proves the guard RED.
"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[3]; HERE = pathlib.Path(__file__).resolve().parent; OUT = HERE / "data"
FLOOR = 16
cases = {c["id"]: c for c in json.loads((ROOT / "evals/crm-followup/cases.json").read_text())["cases"]}
system = (ROOT / "agents/crm-followup/prompt.md").read_text()
heldout = [c for c in cases.values() if c["split"] == "heldout"]
TRAIN_INPUTS = "\n".join([c["input"] for c in cases.values() if c["split"] == "train"] +
                         [t for c in cases.values() if c["split"] == "train" for t in c.get("turns", [])])
SOURCES = [("champion", HERE / "results-champion-ollama.json"), ("glm-5.3", HERE / "results-glm.json")]
DECLARED = []

def single(c):
    d = c.get("detail") or {}
    rs, tr = d.get("raw_steps"), d.get("tool_results") or []
    if not rs or len(rs) != len(tr) + 1 or not isinstance(c.get("got"), dict) or "answer" not in c["got"]:
        return None
    m = [{"role": "system", "content": system}, {"role": "user", "content": cases[c["id"]]["input"]}]
    for i, res in enumerate(tr):
        m += [{"role": "assistant", "content": rs[i]}, {"role": "user", "content": json.dumps({"tool_result": res}, ensure_ascii=False)}]
    m.append({"role": "assistant", "content": rs[-1]})
    return m

def multi(c):
    turns = (c.get("detail") or {}).get("turns") or []
    case = cases[c["id"]]
    if len(turns) != len(case.get("turns", [])) or not all("raw_steps" in t and "tool_results" in t for t in turns):
        return None
    m = [{"role": "system", "content": system}]
    for k, t in enumerate(turns):
        if len(t["raw_steps"]) != len(t["tool_results"]) + 1 or not t.get("passed"):
            return None
        m.append({"role": "user", "content": case["turns"][k]})
        for i, res in enumerate(t["tool_results"]):
            m += [{"role": "assistant", "content": t["raw_steps"][i]}, {"role": "user", "content": json.dumps({"tool_result": res}, ensure_ascii=False)}]
        m.append({"role": "assistant", "content": t["raw_steps"][-1]})
    return m

def leak_guard(lines):
    blob = "\n".join(lines)
    for h in heldout:
        texts = [h["input"].strip()] + [t.strip() for t in h.get("turns", [])]
        for t in texts:
            needles = {t} | ({t[i:i + 40] for i in range(0, max(1, len(t) - 40), 20)} if len(t) >= 40 else set())
            for n in needles:
                if n and n in blob:
                    if n in TRAIN_INPUTS:
                        DECLARED.append({"heldout": h["id"], "text": n[:80]}); continue
                    raise SystemExit(f"LEAK: heldout {h['id']!r}: {n[:60]!r}")

if "--selftest" in sys.argv:
    planted = [h for h in heldout if h["input"].strip() not in TRAIN_INPUTS][0]
    try:
        leak_guard([json.dumps({"messages": [{"role": "user", "content": planted["input"]}]})]); print("SELFTEST FAILED"); sys.exit(1)
    except SystemExit as e:
        if str(e).startswith("LEAK"): print("selftest: guard RED as required ->", str(e)[:70]); sys.exit(0)
        raise

rows, origin, why_not = {}, {}, {}
for name, path in SOURCES:
    if not path.exists():
        print(f"source missing: {name} ({path.name})"); continue
    for c in json.loads(path.read_text())["cases"]:
        cid = c["id"]
        if cid not in cases or cases[cid]["split"] != "train" or cid in rows: continue
        if not c.get("passed"):
            why_not.setdefault(cid, []).append(f"{name}: failed"); continue
        m = multi(c) if "turns" in cases[cid] else single(c)
        if m: rows[cid], origin[cid] = m, name
        else: why_not.setdefault(cid, []).append(f"{name}: passed but not replayable")
ids = sorted(rows)
print(f"rows {len(ids)} (floor {FLOOR}); origin: " + ", ".join(f"{s} {sum(v==s for v in origin.values())}" for s, _ in SOURCES))
print("multi-turn rows:", sum('turns' in cases[k] for k in ids), "| train cases without a row:", {k: v for k, v in why_not.items() if k not in rows})
if len(ids) < FLOOR:
    print(f"ROW FLOOR NOT MET ({len(ids)} < {FLOOR}) — not training"); sys.exit(4)
valid_ids, train_ids = ids[:2], ids[2:]
tl = [json.dumps({"messages": rows[k]}, ensure_ascii=False) for k in train_ids]
vl = [json.dumps({"messages": rows[k]}, ensure_ascii=False) for k in valid_ids]
leak_guard(tl + vl)
OUT.mkdir(exist_ok=True)
(OUT / "train.jsonl").write_text("\n".join(tl) + "\n"); (OUT / "valid.jsonl").write_text("\n".join(vl) + "\n"); (OUT / "test.jsonl").write_text("\n".join(vl) + "\n")
(OUT / "provenance.json").write_text(json.dumps({"train": train_ids, "valid": valid_ids, "origin": origin, "no_row": why_not, "declared_overlaps": DECLARED}, indent=1))
import statistics; print(f"declared overlaps {len(DECLARED)}; row chars max {max(len(l) for l in tl+vl)} median {int(statistics.median(len(l) for l in tl+vl))}")
