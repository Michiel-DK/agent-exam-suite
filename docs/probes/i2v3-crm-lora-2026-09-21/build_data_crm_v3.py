#!/usr/bin/env python3
"""I2 v3 rows = the 16 v2 rows (byte-identical sources: the v2 champion + GLM results files) + rows replayed from
PASSING v3aug-* variant trajectories (results-variants-*.json, first source where it passed). Reconstruction is the
runner's own rule (see v2). Floor 24 → else exit 4, no training. Valid = the 2 alphabetically-last passing variant
rows (the target shape sits in valid; briefing-devos stays in TRAIN this time — in v2 it fell into valid).
Leak guard as v2 (heldout text or a 40-char window in any line = LEAK unless it sits in a committed TRAIN input).
Prints the (user turns, tool calls) shape histogram and the share of rows with >=2 calls in one turn."""
import json, pathlib, sys, statistics
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[2]; OUT = HERE / "data"; V2 = ROOT / "docs/probes/i2v2-crm-lora-2026-09-21"
FLOOR = 24
committed = {c["id"]: c for c in json.loads((ROOT / "evals/crm-followup/cases.json").read_text())["cases"]}
variants = {c["id"]: dict(c, split="train") for c in json.loads((HERE / "variants.json").read_text())["cases"]}
cases = {**committed, **variants}
system = (ROOT / "agents/crm-followup/prompt.md").read_text()
heldout = [c for c in committed.values() if c["split"] == "heldout"]
TRAIN_INPUTS = "\n".join([c["input"] for c in committed.values() if c["split"] == "train"] +
                         [t for c in committed.values() if c["split"] == "train" for t in c.get("turns", [])])
SOURCES = [("v2-champion", V2 / "results-champion-ollama.json", committed), ("v2-glm-5.3", V2 / "results-glm.json", committed),
           ("v3-champion", HERE / "results-variants-champion.json", variants), ("v3-glm-5.3", HERE / "results-variants-glm.json", variants)]
DECLARED = []

def single(c):
    d = c.get("detail") or {}; rs, tr = d.get("raw_steps"), d.get("tool_results") or []
    if not rs or len(rs) != len(tr) + 1 or not isinstance(c.get("got"), dict) or "answer" not in c["got"]: return None
    m = [{"role": "system", "content": system}, {"role": "user", "content": cases[c["id"]]["input"]}]
    for i, res in enumerate(tr):
        m += [{"role": "assistant", "content": rs[i]}, {"role": "user", "content": json.dumps({"tool_result": res}, ensure_ascii=False)}]
    m.append({"role": "assistant", "content": rs[-1]}); return m

def multi(c):
    turns = (c.get("detail") or {}).get("turns") or []; case = cases[c["id"]]
    if len(turns) != len(case.get("turns", [])) or not all("raw_steps" in t and "tool_results" in t for t in turns): return None
    m = [{"role": "system", "content": system}]
    for k, t in enumerate(turns):
        if len(t["raw_steps"]) != len(t["tool_results"]) + 1 or not t.get("passed"): return None
        m.append({"role": "user", "content": case["turns"][k]})
        for i, res in enumerate(t["tool_results"]):
            m += [{"role": "assistant", "content": t["raw_steps"][i]}, {"role": "user", "content": json.dumps({"tool_result": res}, ensure_ascii=False)}]
        m.append({"role": "assistant", "content": t["raw_steps"][-1]})
    return m

def leak_guard(lines):
    blob = "\n".join(lines)
    for h in heldout:
        for t in [h["input"].strip()] + [x.strip() for x in h.get("turns", [])]:
            needles = {t} | ({t[i:i + 40] for i in range(0, max(1, len(t) - 40), 20)} if len(t) >= 40 else set())
            for n in needles:
                if n and n in blob:
                    if n in TRAIN_INPUTS: DECLARED.append({"heldout": h["id"], "text": n[:80]}); continue
                    raise SystemExit(f"LEAK: heldout {h['id']!r}: {n[:60]!r}")

def shape(m):
    users = [x for x in m if x["role"] == "user"]; calls = sum(1 for x in users if x["content"].startswith('{"tool_result"'))
    return (len(users) - calls, calls)

if "--selftest" in sys.argv:
    planted = [h for h in heldout if h["input"].strip() not in TRAIN_INPUTS][0]
    try: leak_guard([json.dumps({"messages": [{"role": "user", "content": planted["input"]}]})]); print("SELFTEST FAILED"); sys.exit(1)
    except SystemExit as e:
        if str(e).startswith("LEAK"): print("selftest: guard RED as required ->", str(e)[:70]); sys.exit(0)
        raise

rows, origin, why_not = {}, {}, {}
for name, path, pool in SOURCES:
    if not path.exists(): print(f"source missing: {name} ({path.name})"); continue
    for c in json.loads(path.read_text())["cases"]:
        cid = c["id"]
        if cid not in pool or pool[cid]["split"] != "train" or cid in rows: continue
        if not c.get("passed"): why_not.setdefault(cid, []).append(f"{name}: failed"); continue
        m = multi(c) if "turns" in cases[cid] else single(c)
        if m: rows[cid], origin[cid] = m, name
        else: why_not.setdefault(cid, []).append(f"{name}: passed but not replayable")
ids = sorted(rows); vids = sorted(k for k in ids if k.startswith("v3aug-"))
hist = {}
for k in ids: hist[shape(rows[k])] = hist.get(shape(rows[k]), 0) + 1
two_in_one = sum(1 for k in ids if shape(rows[k])[0] == 1 and shape(rows[k])[1] >= 2)
print(f"rows {len(ids)} (floor {FLOOR}); origin: " + ", ".join(f"{s} {sum(v==s for v in origin.values())}" for s, _, _ in SOURCES))
print(f"variant rows {len(vids)}/{len(variants)}; variants without a row: {sorted(k for k in variants if k not in rows)}")
print("shape histogram (user turns, tool calls):", " ".join(f"{k}·{v}" for k, v in sorted(hist.items())))
print(f"single-turn rows with >=2 calls in ONE turn: {two_in_one}/{len(ids)} = {two_in_one/len(ids):.0%}" if ids else "no rows")
if len(ids) < FLOOR: print(f"ROW FLOOR NOT MET ({len(ids)} < {FLOOR}) — not training"); sys.exit(4)
if len(vids) < 2: print("fewer than 2 variant rows — no valid split of the target shape"); sys.exit(4)
valid_ids = vids[-2:]; train_ids = [k for k in ids if k not in valid_ids]
tl = [json.dumps({"messages": rows[k]}, ensure_ascii=False) for k in train_ids]; vl = [json.dumps({"messages": rows[k]}, ensure_ascii=False) for k in valid_ids]
leak_guard(tl + vl); OUT.mkdir(exist_ok=True)
(OUT / "train.jsonl").write_text("\n".join(tl) + "\n"); (OUT / "valid.jsonl").write_text("\n".join(vl) + "\n"); (OUT / "test.jsonl").write_text("\n".join(vl) + "\n")
(OUT / "provenance.json").write_text(json.dumps({"train": train_ids, "valid": valid_ids, "origin": origin, "no_row": why_not, "declared_overlaps": DECLARED,
    "shape_histogram": {str(k): v for k, v in sorted(hist.items())}, "two_calls_in_one_turn": two_in_one}, indent=1))
print(f"train {len(tl)} valid {len(vl)}; declared overlaps {len(DECLARED)}; row chars max {max(len(l) for l in tl+vl)} median {int(statistics.median(len(l) for l in tl+vl))}")
