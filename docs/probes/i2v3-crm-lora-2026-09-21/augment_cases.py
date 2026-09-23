#!/usr/bin/env python3
"""Merge variants.json into a WORKTREE's evals/crm-followup/cases.json (split train, ids v3aug-*) for the harvest
run; --restore puts the committed file back. Preflight: a variant input may not share any 40-char window with a
heldout input (stride 1 — stricter than the row-builder's stride-20 guard) and every id must be new. --selftest
proves the preflight RED on a planted heldout window."""
import json, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
WT = pathlib.Path(sys.argv[1]).resolve()
CASES = WT / "evals/crm-followup/cases.json"
committed = json.loads((HERE.parents[2] / "evals/crm-followup/cases.json").read_text())
heldout_texts = [c["input"] for c in committed["cases"] if c["split"] == "heldout"] + \
                [t for c in committed["cases"] if c["split"] == "heldout" for t in c.get("turns", [])]
def preflight(variants):
    ids = {c["id"] for c in committed["cases"]}
    for v in variants:
        if v["id"] in ids: raise SystemExit(f"id collision: {v['id']}")
        if not v["id"].startswith("v3aug-"): raise SystemExit(f"bad id prefix: {v['id']}")
        for h in heldout_texts:
            for i in range(0, max(1, len(h) - 40)):
                w = h[i:i + 40]
                if w in v["input"]: raise SystemExit(f"HELDOUT WINDOW in variant {v['id']!r}: {w!r}")
if "--selftest" in sys.argv:
    try:
        preflight([{"id": "v3aug-planted", "input": "x " + heldout_texts[0][:45] + " y"}]); print("SELFTEST FAILED"); sys.exit(1)
    except SystemExit as e:
        if "HELDOUT WINDOW" in str(e): print("selftest: preflight RED as required ->", str(e)[:70]); sys.exit(0)
        raise
if "--restore" in sys.argv:
    import subprocess; subprocess.run(["git", "-C", str(WT), "checkout", "--", "evals/crm-followup/cases.json"], check=True)
    n = len(json.loads(CASES.read_text())["cases"]); print(f"restored: {n} cases"); sys.exit(0 if n == len(committed["cases"]) else 5)
variants = json.loads((HERE / "variants.json").read_text())["cases"]
preflight(variants)
d = json.loads(CASES.read_text())
if any(c["id"].startswith("v3aug-") for c in d["cases"]): raise SystemExit("worktree cases.json already augmented")
for v in variants: d["cases"].append({"id": v["id"], "split": "train", "input": v["input"], "expected": v["expected"]})
CASES.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n")
print(f"augmented: {len(committed['cases'])} committed + {len(variants)} variants = {len(d['cases'])}")
