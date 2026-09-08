#!/usr/bin/env python3
"""Append the generated longcall-* cases to evals/transcript-en/cases.json.

Verified once (this comment is the record): the committed cases.json is
byte-identical to json.dumps(data, indent=2, ensure_ascii=False) with no
trailing newline, so round-tripping through json.load/json.dump here is safe
PROVIDED nothing about the 22 existing entries changes -- this script never
mutates data["cases"][:22], only appends. `git diff` after running this
must show ONLY added lines, never a `-` inside any of the 22 pre-existing
case objects (checked below, mechanically, before writing anything).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES_PATH = HERE.parents[2] / "evals" / "transcript-en" / "cases.json"
GENERATED_PATH = HERE / "generated_cases.json"

data = json.loads(CASES_PATH.read_text())
generated = json.loads(GENERATED_PATH.read_text())
before = json.dumps(data, indent=2, ensure_ascii=False)
assert before == CASES_PATH.read_text(), (
    "cases.json is not byte-identical to its own json.dumps(indent=2) round-trip "
    "BEFORE any edit -- refusing to proceed, this script's safety argument depends "
    "on that being true")

n_before = len(data["cases"])
existing_ids = {c["id"] for c in data["cases"]}
for c in generated:
    if c["id"] in existing_ids:
        sys.exit(f"error: {c['id']} already present in cases.json")
    entry = {"id": c["id"], "split": c["split"], "input": c["input"], "expected": dict(c["expected"])}
    if "speakers" in c:
        entry["expected"] = {**entry["expected"]}
        entry["expected"]["speakers"] = c["speakers"]
    data["cases"].append(entry)

after = json.dumps(data, indent=2, ensure_ascii=False)
# `before` ends in the array/object closers "  ]\n}" (2 lines). Strip exactly
# those and the trailing case's own closing "}" must still be an exact
# PREFIX of `after` -- i.e. every byte of the 22 pre-existing cases is
# untouched; `after` only ever appends more array elements before the
# closers.
closer = "\n  ]\n}"
assert before.endswith(closer), f"unexpected file tail: {before[-20:]!r}"
old_prefix = before[: -len(closer)]
assert after.startswith(old_prefix), (
    "the 22 pre-existing cases are NOT byte-identical in the spliced output "
    "-- refusing to write")
assert after[len(old_prefix):].startswith(",\n"), (
    "expected new case objects to be appended as additional array elements")

CASES_PATH.write_text(after)
print(f"cases.json: {n_before} -> {len(data['cases'])} cases "
      f"(+{len(data['cases']) - n_before} longcall-*)")
