#!/usr/bin/env python3
"""Diff the 22 pre-existing cases' verdicts: old committed snapshot (master)
vs the new champion's results file. Programmatic, not eyeballed (advisor
note)."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
old_raw = subprocess.run(["git", "show", "master:evals/transcript-en/snapshot.json"],
                        cwd=ROOT, capture_output=True, text=True, check=True).stdout
old = json.loads(old_raw)
old_by_id = {c["id"]: c for c in old["cases"]}

results_path = ROOT / "results" / "transcript-en__ollama__gemma4-e4b-ctx16k.json"
new = json.loads(results_path.read_text())
new_by_id = {c["id"]: c for c in new["cases"] if not c["id"].startswith("longcall-")}

assert set(old_by_id) == set(new_by_id), (
    f"case set mismatch: only-old={set(old_by_id)-set(new_by_id)} "
    f"only-new={set(new_by_id)-set(old_by_id)}")

flips = []
for cid in sorted(old_by_id):
    o, n = old_by_id[cid], new_by_id[cid]
    if o["passed"] != n["passed"]:
        n_failed = [f["check"] for f in n.get("failed_checks", [])]
        o_failed = [f["check"] for f in o.get("failures", [])]
        flips.append((cid, o["passed"], n["passed"], o_failed, n_failed))

print(f"{len(old_by_id)} pre-existing cases compared, {len(flips)} flips\n")
for cid, op, np_, of, nf in flips:
    direction = "LOSS" if op and not np_ else "GAIN"
    print(f"  [{direction}] {cid}: old_passed={op} (failed={of}) -> "
         f"new_passed={np_} (failed={nf})")
if not flips:
    print("  0 flips")
