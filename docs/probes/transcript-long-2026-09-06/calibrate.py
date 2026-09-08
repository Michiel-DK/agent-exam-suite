#!/usr/bin/env python3
"""Reads results/transcript-en__ollama__gemma4-e4b-ctx16k.json and prints, for
every longcall-* TRAIN case (never heldout -- calibration must not look at
heldout output before setting max_ratio), input length / summary length /
ratio / wall_ms, plus the timing measurement for the >=30000-char heldout
case (timing is not a content calibration -- reading a wall clock number is
not "seeing the heldout number" the brief's own rule is about)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
path = ROOT / "results" / "transcript-en__ollama__gemma4-e4b-ctx16k.json"
data = json.loads(path.read_text())
cases = {c["id"]: c for c in data["cases"]}
cases_json = json.loads((ROOT / "evals" / "transcript-en" / "cases.json").read_text())
input_len_by_id = {c["id"]: len(c["input"]) for c in cases_json["cases"]}

print("TRAIN longcall-* calibration (max_ratio input):")
for cid, c in cases.items():
    if not cid.startswith("longcall-") or c["split"] != "train":
        continue
    got = c.get("got") or {}
    summary = got.get("summary") or "" if isinstance(got, dict) else ""
    inp_len = input_len_by_id.get(cid)
    wall = ((c.get("detail") or {}).get("metrics") or {}).get("wall_ms")
    ratio = len(summary) / inp_len if inp_len else None
    print(f"  {cid:32s} input={inp_len:6d} summary={len(summary):5d} chars  "
         f"ratio={ratio:.3f}  wall={wall}")

print("\nTiming for the >=30000-char case (longcall-support-heldout-2):")
c = cases.get("longcall-support-heldout-2")
if c:
    wall = ((c.get("detail") or {}).get("metrics") or {}).get("wall_ms")
    passed = c.get("passed")
    failed = [f["check"] for f in c.get("failed_checks", [])]
    print(f"  wall_ms={wall}  passed={passed}  failed_checks={failed}")

print("\nAll longcall-* cases, pass/fail summary (heldout numbers -- read once):")
for cid, c in sorted(cases.items()):
    if not cid.startswith("longcall-"):
        continue
    failed = [f["check"] for f in c.get("failed_checks", [])]
    wall = ((c.get("detail") or {}).get("metrics") or {}).get("wall_ms")
    print(f"  {cid:32s} split={c['split']:8s} passed={c['passed']!s:5s} "
         f"wall_ms={wall}  failed={failed}")
