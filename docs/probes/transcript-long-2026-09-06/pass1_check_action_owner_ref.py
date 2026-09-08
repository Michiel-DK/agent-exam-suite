"""Reference copy of pass 1's `check_action_owner` body — the EVERY-HIT rule
(ledger 041 finding 1: a `commit_owner` key with >= 2 hits FAILED unless EVERY
hit's leading token carried the declared owner, which rejected the champion's
genuinely correct real output on longcall-support-heldout-2 where both "Rep to
follow up" and "Customer to follow up" legitimately contain the same
`commit_owner` substring).

WHY THIS FILE EXISTS, NOT A DEAD BRANCH IN properties.py: pass-2 criterion
clause (2) requires demonstrating, on the identical fixture that PASSES under
the shipped any-hit-correct rule, that the OLD every-hit rule FAILS it — and
clause (5) requires the same old-vs-new comparison over every recorded real
output. `evals/transcript-en/properties.py` is not allowed to carry a dead
rule (pass-2 criterion v4, clause 5's own text), so pass 1's exact aggregation
logic is preserved here instead, as an importable module, NOT matching the
`test_*.py` glob `.cline/test.sh` sweeps (it is not a test file and asserts
nothing).

This module reuses `_exp`, `_action_items`, and `_leading_owner_token` from
the SHIPPED `evals/transcript-en/properties.py` unchanged — those three
helpers were not the pass-1 defect; only the per-key hit-aggregation rule
below was. Reusing them (rather than forking them too) keeps this reference
copy from silently drifting into testing something else if those helpers are
ever legitimately changed for an unrelated reason.
"""
import importlib.util as _ilu
import sys
from pathlib import Path

_PROPS_PATH = Path(__file__).resolve().parents[3] / "evals" / "transcript-en" / "properties.py"
# Loaded BY PATH under a private module name: under pytest (one process for every exam's
# tests) a bare `import properties` returns whichever exam's properties.py was imported
# first — recap's, in the public repo's CI on 8 Sep — and this module then fails to find
# `_action_items`. `.cline/test.sh` never saw it (one process per file).
_spec = _ilu.spec_from_file_location("_transcript_en_properties_ref", _PROPS_PATH)
_P = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_P)
_exp = _P._exp
_action_items = _P._action_items
_leading_owner_token = _P._leading_owner_token


def check_action_owner_every_hit(input_text, output):
    """Pass 1's rule, byte-for-byte in its aggregation logic: a `commit_owner`
    key with >= 1 hit requires EVERY hit's leading owner token to match the
    declared owner, not just one. This is the REJECTED rule — kept here only
    as a fixture for clause (2)'s revert-demo and clause (5)'s flip count,
    never imported by evals/transcript-en/properties.py."""
    exp = _exp(input_text)
    commit_owner = exp.get("commit_owner")
    if not commit_owner:
        return True, ""
    speakers = exp.get("speakers") or {}
    rep_name = str(speakers.get("rep") or "").strip().lower()
    cust_name = str(speakers.get("customer") or "").strip().lower()
    rep_tokens = {"rep", "the rep"} | ({rep_name} if rep_name else set()) | set(rep_name.split())
    cust_tokens = {"customer", "the customer", "client", "the client"} | (
        {cust_name} if cust_name else set()) | set(cust_name.split())
    items = _action_items(output)
    items_lower = [str(i).lower() for i in items]
    bad = []
    for substring, owner in commit_owner.items():
        owner = str(owner).strip().lower()
        if owner == "rep":
            want, orig = rep_tokens, items
        elif owner == "customer":
            want, orig = cust_tokens, items
        else:
            raise ValueError(
                f"check_action_owner_every_hit: commit_owner[{substring!r}] must be "
                f"'rep' or 'customer', got {owner!r} — a cases.json authoring bug")
        needle = str(substring).lower()
        hits = [it for it, low in zip(orig, items_lower) if needle in low]
        if not hits:
            continue  # absence is check_action_items' job, not this check's
        for it in hits:  # EVERY-HIT: one bad apple fails the whole key
            leading = _leading_owner_token(it)
            if leading not in want:
                bad.append(f"{substring!r} expected owner {owner!r}, got leading "
                          f"token {leading!r} in item {it!r}")
    if bad:
        return False, "; ".join(bad)
    return True, ""


check_action_owner_every_hit.bucket = "quality"
