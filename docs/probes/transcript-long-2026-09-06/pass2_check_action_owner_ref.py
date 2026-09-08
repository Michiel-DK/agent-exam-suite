"""Reference copy of pass 2's `check_action_owner` / `_leading_owner_token`
BODY — the SET-EQUALITY parser (pass-2 head `cfde8e4`, byte-for-byte; pinned
by blob `b379bb8be74a982d3e88d554752fcaf1836302c1` -- `git show
b379bb8be74a982d3e88d554752fcaf1836302c1` reproduces the exact source these
two functions were copied from, so this reference cannot silently drift if
`evals/transcript-en/properties.py` is edited again for an unrelated reason;
CLAUDE.md gotcha 15's "pin a blob" lesson, applied here to a hand-frozen copy
rather than a live import).

WHY THIS FILE EXISTS, NOT A DEAD BRANCH IN properties.py: pass-3 criterion
clause (2) requires demonstrating, on the fixtures that PASS under the
pass-3 whole-word/parenthetical-tolerant parser, that pass 2's set-equality
parser FAILS them (RED) -- a parenthetical aside ('customer (callan)') or a
clause-prefixed lead ('after confirming budget with finance, sana') never
equalled a bare owner token, so pass 2 silently read both as unrecognised.
`evals/transcript-en/properties.py` carries no dead rule (pass-2 criterion
v4's own text, extended here to pass 3): pass 2's rejected parser lives here
instead, as an importable module, NOT matching the `test_*.py` glob
`.cline/test.sh` sweeps (it is not a test file and asserts nothing).

This module reuses `_exp` and `_action_items` from the SHIPPED
`evals/transcript-en/properties.py` unchanged -- those two helpers were not
the pass-2 defect; only `_leading_owner_token`'s extraction and
`check_action_owner`'s set-equality match were. `_leading_owner_token` and
`check_action_owner` themselves are FORKED here (not imported), because the
whole point is to freeze the code the pass-3 fix replaced -- importing the
shipped versions would just re-test pass 3's own fix under a different name.
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

_LEAD_DELIMS = (" to ", " will ", ":")


def _leading_owner_token_pass2(item: str) -> str | None:
    """Byte-for-byte pass 2 (`cfde8e4`, blob b379bb8): the text before the
    FIRST of ' to ' / ' will ' / ':', lowercased and stripped -- no
    parenthetical stripping, no whole-word search downstream. This is the
    REJECTED parser, kept here only as a fixture for clause (2)'s RED demo,
    never imported by evals/transcript-en/properties.py."""
    lower = item.lower()
    idxs = [lower.find(d) for d in _LEAD_DELIMS]
    idxs = [i for i in idxs if i != -1]
    if not idxs:
        return None
    return lower[: min(idxs)].strip()


def check_action_owner_pass2(input_text, output):
    """Byte-for-byte pass 2's `check_action_owner` (`cfde8e4`, blob
    b379bb8): any-hit-correct AGGREGATION (pass 2's real fix, unchanged and
    not itself in question here) over `leading in want` SET-EQUALITY
    matching (the pass-3 defect -- a leading segment that is a whole clause
    or carries a parenthetical never equals a bare token in `want`, so a
    correct real attribution reads as unrecognised and the key fails). The
    REJECTED rule -- kept here only as a fixture for clause (2)'s RED demo
    and never imported by evals/transcript-en/properties.py."""
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
                f"check_action_owner_pass2: commit_owner[{substring!r}] must be "
                f"'rep' or 'customer', got {owner!r} — a cases.json authoring bug")
        needle = str(substring).lower()
        hits = [it for it, low in zip(orig, items_lower) if needle in low]
        if not hits:
            continue  # absence is check_action_items' job, not this check's
        leadings = [_leading_owner_token_pass2(it) for it in hits]
        if not any(leading in want for leading in leadings):
            bad.append(f"{substring!r} expected owner {owner!r}, no hit carried "
                      f"that owner's leading token — leading token(s) seen: "
                      f"{leadings!r} across item(s) {hits!r}")
    if bad:
        return False, "; ".join(bad)
    return True, ""


check_action_owner_pass2.bucket = "quality"
