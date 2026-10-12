"""injection_column.py — the two pure helpers behind the "resists injection" column (M1, 2026-10-08), importable
without running build_tables.py (which reads the price ledger at module level). Pinned by evals/test_injection_cases.py."""
import json, os
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

def injection_ids_for(exam):
    """The `"class": "injection"` case ids an exam's committed cases.json carries,
    in file order. Empty for an exam with none (every exam but the 3 M1 touched)."""
    path = os.path.join(REPO, "evals", exam, "cases.json")
    if not os.path.exists(path):
        return []
    cases = json.load(open(path)).get("cases", [])
    return [c["id"] for c in cases if c.get("class") == "injection"]

def injection_cell(cases_list, ids):
    """k/m over the injection ids THIS row's own per-case list (`cases_list`, a
    results/*.json's or a snapshot.json's "cases" array) actually carries, joined
    by id. "—" when none of `ids` has a matching entry at all — distinct from
    "0/m", which would claim a verdict (resisted/obeyed) nothing measured."""
    if not ids:
        return "—"
    by_id = {c["id"]: c for c in cases_list}
    matched = [by_id[i] for i in ids if i in by_id]
    if not matched:
        return "—"
    k = sum(1 for c in matched if c.get("passed"))
    return f"{k}/{len(matched)}"
