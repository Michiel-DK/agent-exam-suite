"""Property checks for transcript-en (S-TRANSCRIPT-EN-EXAM): English business
call-transcript summarisation — the pilot-shaped exam (post-call summary + action
items, long transcripts included).

Each check_* takes (input_text, output: dict) and returns (ok: bool, msg: str), and
declares a `bucket` marker ("format" | "quality") — the runner REFUSES to load a
check without one (C5(a), fail loud, never a default). This file is a direct port of
evals/recap/properties.py's SHAPE, not a copy-paste: the output schema here has three
top-level fields instead of two (`summary`, `action_items`, `nothing_important`), and
adds check_action_items, which recap has no equivalent of — action items are the lead's
actual output, a recap has none.

WHY THIS FILE READS ITS OWN cases.json
--------------------------------------
Same reason as recap (docs/exam-audit-2026-07-22.md, ledger 017): per-case
expectations (`must_mention`, `must_commit`, `max_ratio`, `nothing_important`,
`abstain_max_chars`) are parameterised per case, the properties signature is fixed at
(input_text, output) with no `expected`, and this exam looks up its own metadata by
EXACT input text rather than changing the shared runner for one exam's needs.

An input that is NOT a committed case RAISES rather than resolving to {} and passing
every parameterised check vacuously — the ledger-017 invariant, asserted mechanically
in evals/test_transcript_en.py exactly as evals/test_recap_vacuous_green.py does for
recap. A new case must be a NEW committed entry in cases.json with its own `expected`
block; never a mutation of an existing case's input at runtime.

THE DIRECTIONALITY RULE (docs/exam-audit-2026-07-22.md — shipped broken TWICE in recap)
-----------------------------------------------------------------------------------
  check_grounded       tests ABSENCE — an invented number must NOT appear (in EITHER
                        `summary` or `action_items` — a fabricated figure is just as
                        much a fabrication in an action item as in the summary).
  check_coverage       tests PRESENCE — a required item MUST appear in `summary`.
  check_action_items   tests PRESENCE — a required commitment MUST appear somewhere
                        in the `action_items` list. Scoped to `action_items` ONLY,
                        deliberately: check_coverage reads `summary` only. That split
                        is what makes isolating check_action_items possible — a
                        synthetic output with a correct, covering summary but an
                        `action_items` list missing one required commitment fails
                        ONLY this check (see evals/test_transcript_en.py).
They therefore normalise DIFFERENTLY and must never share a helper. Numbers go
through sandbox/numnorm.strip_thousands ONLY (the single shared implementation);
nothing here strips decimal points, because '65.00' and '6500' are different
amounts (CLAUDE.md gotcha 4).
"""
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SANDBOX = str(_HERE.parents[1] / "sandbox")
if _SANDBOX not in sys.path:
    sys.path.insert(0, _SANDBOX)
from numnorm import strip_thousands as _strip_thousands  # noqa: E402


@lru_cache(maxsize=1)
def _expectations_by_input() -> dict:
    """{input_text: expected_dict} for the committed cases. Cached: read once per
    process, cases.json is immutable during a run.

    Raises if cases.json is missing — a deleted or misplaced cases.json must not
    score every case a silent vacuous pass (recap's ledger-017 lesson, applied here
    from the start rather than discovered the hard way twice).
    """
    path = _HERE / "cases.json"
    if not path.exists():
        raise FileNotFoundError(
            f"transcript-en properties: {path} is missing. Every check here "
            "resolves its expectations from that file; without it each check would "
            "find nothing to assert and pass vacuously."
        )
    data = json.loads(path.read_text())
    return {c["input"]: (c.get("expected") or {}) for c in data.get("cases", [])}


def _exp(input_text: str) -> dict:
    """Expectations for one case, resolved by EXACT input text.

    THE LEDGER-017 INVARIANT (recap's own docstring explains the mechanism in
    full; reproduced here because this file must carry the same guarantee on its
    own, not by reference). Every check in this file does `_exp(input_text).get(key)`
    and returns pass when the key is absent — correct for a case that genuinely
    declares no such expectation, catastrophic for an input that is not a committed
    case at all. Raising here converts that into a loud, scored failure
    (`run_properties` turns an exception into a FAILED check, runner.py) instead of
    a silent full-marks pass. A new exam case must be a NEW committed entry in
    cases.json with its own `expected` block — never a mutation of an existing
    case's input at runtime.
    """
    table = _expectations_by_input()
    if input_text not in table:
        preview = input_text[:60].replace("\n", " ") if isinstance(input_text, str) else input_text
        raise KeyError(
            "transcript-en properties: this input does not match any committed "
            "case in evals/transcript-en/cases.json "
            f"(len={len(input_text) if isinstance(input_text, str) else '?'}, "
            f"starts {preview!r}). Expectations resolve by EXACT input text, so "
            "scoring it would pass every check vacuously. Add it to cases.json "
            "with its own `expected` block rather than mutating an existing "
            "case's input."
        )
    return table[input_text]


def _summary(output) -> str:
    return (output or {}).get("summary") or "" if isinstance(output, dict) else ""


def _action_items(output) -> list:
    items = (output or {}).get("action_items") if isinstance(output, dict) else None
    return items if isinstance(items, list) else []


def _action_items_text(output) -> str:
    """Joined lowercase text of the action_items list, for PRESENCE matching."""
    return " | ".join(str(i) for i in _action_items(output))


# ------------------------------------------------------------------ format

def check_output_shape(input_text, output):
    """Fail loud on a malformed answer instead of letting a later check read a
    default. Validates PRESENCE and TYPE only — never content. check_action_items
    is the check that validates action_items' content; keeping that split is what
    lets a synthetic output fail check_action_items alone (see the isolation test)."""
    if not isinstance(output, dict):
        return False, f"output is {type(output).__name__}, not a JSON object"
    summary = output.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return False, "missing or empty 'summary' string"
    items = output.get("action_items")
    if not isinstance(items, list):
        return False, f"'action_items' must be a list, got {type(items).__name__}"
    if not all(isinstance(i, str) for i in items):
        return False, "'action_items' must be a list of strings"
    if not isinstance(output.get("nothing_important"), bool):
        return False, ("'nothing_important' must be a bool, got "
                       f"{type(output.get('nothing_important')).__name__}")
    return True, ""


check_output_shape.bucket = "format"


# ------------------------------------------------------------------ quality

_NUM_RE = re.compile(r"\d[\d.,]*\d|\d")


def check_grounded(input_text, output):
    """ABSENCE check: every number in the summary AND action_items must appear in
    the source transcript. The fabrication check — an invented figure in an action
    item ('Rep to send the 5000 EUR discount') is just as much a fabrication as one
    in the summary, so both fields are scanned together against the source.

    Normalisation is deliberately MINIMAL (thousands separators only, shared
    helper). Decimal points are load-bearing and never stripped — '65.00' and
    '6500' are different amounts (CLAUDE.md gotcha 4).
    """
    src_nums = {_strip_thousands(n) for n in _NUM_RE.findall(input_text)}
    combined = _summary(output) + " " + _action_items_text(output)
    invented = []
    for raw in _NUM_RE.findall(combined):
        n = _strip_thousands(raw)
        # Substring, not equality: "40" inside a source "40217" (LC-40217) reads as
        # grounded while a genuinely new figure does not. Matches recap's rule.
        if not any(n in s for s in src_nums):
            invented.append(raw)
    if invented:
        return False, f"number(s) not in the source: {', '.join(sorted(set(invented)))}"
    return True, ""


check_grounded.bucket = "quality"


def check_coverage(input_text, output):
    """PRESENCE check: the items a correct summary cannot omit are all mentioned,
    in `summary`. Case-insensitive substring, deliberately generous — must never
    fail an honest summary over phrasing."""
    required = _exp(input_text).get("must_mention") or []
    if not required:
        return True, ""
    summary = _summary(output).lower()
    missing = [t for t in required if str(t).lower() not in summary]
    if missing:
        return False, f"omitted required item(s) from summary: {', '.join(missing)}"
    return True, ""


check_coverage.bucket = "quality"


def check_action_items(input_text, output):
    """PRESENCE check, NEW for this exam: the commitments made on the call must be
    listed in `action_items`. This is the lead's actual output — a post-call summary
    without the list of what was agreed is not the product being piloted — and
    recap has no equivalent (a day's messages carry no 'commitments made').

    Scoped to `action_items` ONLY (never `summary`) so this check can be isolated:
    a synthetic output with a fully correct, covering summary but an action_items
    list that omits one required commitment fails ONLY here. See
    evals/test_transcript_en.py's isolation test, built the same way
    test_e13_recap.py isolates recap's checks.

    Case-insensitive substring, same generosity as check_coverage — this must
    never fail an action item over phrasing, only over the commitment being
    genuinely absent from the list.
    """
    required = _exp(input_text).get("must_commit") or []
    if not required:
        return True, ""
    text = _action_items_text(output).lower()
    missing = [t for t in required if str(t).lower() not in text]
    if missing:
        return False, f"commitment(s) missing from action_items: {', '.join(missing)}"
    return True, ""


check_action_items.bucket = "quality"


def check_compression(input_text, output):
    """The `summary` must be materially shorter than the call it summarises. Ratio
    is per-case, set from the calibration probe (2026-08-26) with margin over the
    measured tier — see cases.json's `note`. Scoped to `summary` ONLY: folding
    `action_items` into the length measurement would make compression and
    check_action_items fight each other (a model padding action_items to be safe
    would also blow the ratio), which is exactly the coupling recap's own
    check_compression avoids by measuring one field."""
    ratio = _exp(input_text).get("max_ratio")
    if ratio is None:
        return True, ""
    limit = int(len(input_text) * float(ratio))
    got = len(_summary(output))
    if got > limit:
        return False, (f"summary is {got} chars vs limit {limit} "
                       f"({float(ratio):.2f} x {len(input_text)} source chars)")
    return True, ""


check_compression.bucket = "quality"


def check_abstention(input_text, output):
    """A quiet call — no decision, no commitment from either side — must say so on
    the structured flag, NOT pad, and NOT list action items that were not really
    commitments. The tempting fabrication here is inventing a commitment or a
    decision that was not there (manufactured significance, recap's diary-adjacent
    failure) — observed for real on quiet-checkin-short-train, where the champion
    set nothing_important=False and invented a 'schedule the next check-in' action
    item on a call that agreed nothing.

    Both directions are real failures, matching recap:
      quiet call -> flag must be True, summary must stay under abstain_max_chars,
                    AND action_items must be empty (a routine 'same time next
                    month' is not a business commitment)
      busy call  -> flag must be False; abstaining on a call that produced a real
                    decision is the opposite error and just as wrong
    Checked on the STRUCTURED flag (and the empty-list requirement), not on prose,
    so it cannot be gamed by phrasing and cannot false-fail an honest summary over
    wording.
    """
    exp = _exp(input_text)
    want = exp.get("nothing_important")
    if want is None:
        return True, ""
    got = output.get("nothing_important") if isinstance(output, dict) else None
    if got is not want:
        if want:
            return False, (f"quiet call: expected nothing_important=true, got "
                           f"{got!r} — manufactured significance")
        return False, (f"busy call: expected nothing_important=false, got "
                       f"{got!r} — abstained on a call that needed attention")
    if want:
        cap = exp.get("abstain_max_chars")
        if cap is not None and len(_summary(output)) > int(cap):
            return False, (f"abstained but padded: summary {len(_summary(output))} "
                           f"chars exceeds the {cap}-char quiet-call cap")
        items = _action_items(output)
        if items:
            return False, (f"abstained (nothing_important=true) but listed "
                           f"{len(items)} action item(s) — a quiet call has no "
                           "real commitments to list")
    return True, ""


check_abstention.bucket = "quality"


# ------------------------------------------------------------- quality (lane 1, longcall-*)

_LEAD_DELIMS = (" to ", " will ", ":")

_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")


def _leading_owner_token(item: str) -> str | None:
    """The text before the FIRST of ' to ' / ' will ' / ':' in an action item,
    lowercased, stripped, and with any parenthetical asides removed — the
    leading segment check_action_owner's whole-word owner search reads.
    None when no delimiter is found at all (an item with no recognisable shape).

    LEADING SEGMENT, NEVER ANYWHERE-SUBSTRING (step-0's own scorer bug,
    RESULTS.md finding 3): an anywhere-substring match on 'customer' or 'rep'
    collides with words like 'report' or a mid-sentence mention of "the
    customer's ops manager" in a REP-owned item. Reading only the text before
    the first delimiter is what makes the isolation fixture's wrong-build twin
    (test_2j) fail the way it's supposed to.

    PASS-2 PARSER BUG (ledger 041, pass 3 fix): this function used to be the
    exact string check_action_owner tested for SET-EQUALITY against a fixed
    token ("rep", "sana", ...) — so a leading segment that is a whole clause
    ('after confirming budget with finance, sana') or carries a parenthetical
    aside ('customer (callan)') never equalled any token and silently read as
    unrecognised on real Kimi output. Parentheticals are stripped HERE (after
    the leading segment is sliced, so a parenthetical containing a delimiter
    word never shifts where the segment ends); the WHOLE-WORD search against
    each side's token set now lives in check_action_owner, which is what
    lets 'customer (callan)' and 'after confirming budget with finance, sana
    will ...' resolve without also matching an anywhere-substring hit.
    """
    lower = item.lower()
    idxs = [lower.find(d) for d in _LEAD_DELIMS]
    idxs = [i for i in idxs if i != -1]
    if not idxs:
        return None
    leading = lower[: min(idxs)]
    leading = _PARENTHETICAL_RE.sub(" ", leading)
    return leading.strip()


def _leading_owner_segment(item: str, known_tokens: set) -> str | None:
    """`_leading_owner_token`, plus ONE tolerance the pass-3 review found missing
    (8 Sep, correctness refuter): a TOPIC LABEL before the owner — "Escalation:
    Rep to open a ticket" — where the earliest delimiter is the label's colon and
    the segment before it ("escalation") names nobody. When that segment carries
    NO known owner token, the label is dropped and the item is re-sliced after
    the colon, so the segment becomes "rep". "Rep: send the SLA document" is
    untouched: its pre-colon segment DOES carry a token, so it is the owner, not
    a label. Still leading-segment only — never an anywhere-substring search."""
    leading = _leading_owner_token(item)
    if leading is None:
        return None
    lower = item.lower()
    colon = lower.find(":")
    first = min(i for i in (lower.find(d) for d in _LEAD_DELIMS) if i != -1)
    if colon != -1 and colon == first and not _owner_side_tokens_present(leading, known_tokens):
        rest = _leading_owner_token(item[colon + 1:])
        if rest is not None:
            return rest
    return leading


def _owner_side_tokens_present(leading: str, tokens: set) -> bool:
    """True iff any token in `tokens` occurs in `leading` as a whole word (or,
    for a multi-word token like 'the rep' or a full name, a whole phrase) —
    never as a substring of a longer word ('report' must not match 'rep').
    `leading` is expected to already be `_leading_owner_token`'s output
    (lowercased, delimiter-sliced, parenthetical-stripped)."""
    for tok in tokens:
        if not tok:
            continue
        if re.search(r"(?<!\w)" + re.escape(tok) + r"(?!\w)", leading):
            return True
    return False


def check_action_owner(input_text, output):
    """PRESENCE-CONDITIONAL attribution check, NEW for lane 1 (the long-call
    band): fills the declared gap "speaker attribution correctness (REP vs
    CUSTOMER) is not checked" (this file's own `not_verified`, pre-lane-1).

    Expected keys on a case: `speakers` ({"rep": <name>, "customer": <name>})
    and `commit_owner` ({<must_commit substring>: "rep" | "customer"}, keys a
    SUBSET of that case's `must_commit`). For each `commit_owner` entry: find
    the action items containing the substring (case-insensitive); if NONE,
    PASS — presence is check_action_items' job, and this is what makes the two
    checks isolable from each other (this file's directionality-rule
    docstring).

    ANY-HIT-CORRECT (pass 2 fix; ledger 041 finding 1 — was every-hit): a key
    with >= 1 hit PASSES that key iff AT LEAST ONE hit's LEADING segment
    (`_leading_owner_token`) carries the declared owner's tokens — rep:
    {"rep", "the rep", <speakers.rep>}; customer: {"customer", "the
    customer", "client", "the client", <speakers.customer>}. It FAILS that
    key only when every hit's leading segment misses the declared owner's set.
    Every-hit (require ALL hits correctly owned) rejected a genuinely correct
    output on the champion's real longcall-support-heldout-2 run, where both
    "Rep to follow up" and "Customer to follow up" legitimately contain the
    same `commit_owner` substring — duplicate correct mentions are not an
    attribution error. Each key is evaluated independently; the check as a
    whole fails if any key fails. Reads only `action_items` and
    `speakers`/`commit_owner` from the case's `expected` block; no number
    normalisation of any kind (this is a text-attribution check, not a
    grounding check).

    WHOLE-WORD, ONE SIDE ONLY (pass 3 fix, `_owner_side_tokens_present`): a
    hit counts as carrying the declared owner iff that owner's tokens appear
    in the leading segment as a WHOLE WORD/PHRASE and the OTHER side's tokens
    do not. Set-equality against the whole leading segment (pass 2's rule)
    silently read 'customer (callan)' and 'after confirming budget with
    finance, sana' as unrecognised, because neither string equals a bare
    token — real Kimi/model output that is a clause or carries a
    parenthetical name never gets a fair check under set-equality. A leading
    segment naming BOTH sides (e.g. "rep and customer") is deliberately
    treated as unrecognised for either owner, not as a match for whichever
    owner happens to be declared — an ambiguous lead is not evidence.
    """
    exp = _exp(input_text)
    commit_owner = exp.get("commit_owner")
    if not commit_owner:
        return True, ""
    speakers = exp.get("speakers") or {}
    rep_name = str(speakers.get("rep") or "").strip().lower()
    cust_name = str(speakers.get("customer") or "").strip().lower()
    # A case's `speakers` may carry a full name ("sana malik"); a model's action
    # item leading token is realistically a FIRST name ("Sana to ..."), never the
    # full string. Every individual word of the declared name is added to that
    # side's token set (never split across sides — rep and customer names are
    # always distinct people in a case), alongside the full string itself.
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
                f"check_action_owner: commit_owner[{substring!r}] must be "
                f"'rep' or 'customer', got {owner!r} — a cases.json authoring bug")
        needle = str(substring).lower()
        hits = [it for it, low in zip(orig, items_lower) if needle in low]
        if not hits:
            continue  # absence is check_action_items' job, not this check's
        other = cust_tokens if want is rep_tokens else rep_tokens
        leadings = [_leading_owner_segment(it, rep_tokens | cust_tokens) for it in hits]
        matched = any(
            leading is not None
            and _owner_side_tokens_present(leading, want)
            and not _owner_side_tokens_present(leading, other)
            for leading in leadings)
        if not matched:
            bad.append(f"{substring!r} expected owner {owner!r}, no hit carried "
                      f"that owner's leading token — leading token(s) seen: "
                      f"{leadings!r} across item(s) {hits!r}")
    if bad:
        return False, "; ".join(bad)
    return True, ""


check_action_owner.bucket = "quality"


def check_withdrawn_excluded(input_text, output):
    """ABSENCE check, NEW for lane 1: fills the declared gap "does not check
    that action_items excludes ungrounded or duplicate items" (this file's own
    `not_verified`, pre-lane-1) for the WITHDRAWN-proposal case specifically —
    the crm `answer_not_contains` pattern (PR #72), unchanged, scoped to
    `action_items` the same way check_action_items is.

    Expected key: `must_not_commit` (a list of plain lowercase substrings). A
    proposal that was explicitly withdrawn on the call must not resurface as a
    commitment. Every `must_not_commit` substring is required, by the case-
    authoring rule (docs/transcript-long-brief-2026-09-06.md), to (a) appear in
    the transcript, (b) be cleanly cancelled at its LAST mention (never a
    hedge), and (c) appear in none of the same case's `must_commit` — (a) and
    (c) are asserted mechanically over every committed `longcall-*` case in
    evals/test_transcript_en.py; (b) is a per-case authorial judgment recorded
    in that case's `why` string. Case-insensitive substring, no number
    normalisation — this checks text presence of a cancelled proposal, not a
    figure.

    NORMALIZATION IS DIRECTIONAL (this file's own directionality-rule
    docstring, CLAUDE.md gotcha 4; ledger 041 finding 3): this is an ABSENCE
    check, so it builds its OWN joined/lowercased `action_items` string right
    here rather than calling `_action_items_text` — the PRESENCE join that
    `check_grounded` and `check_action_items` both call. Over-normalizing an
    absence check with a helper built for presence matching is exactly the
    hole that let a shared join slip through pass 1. The raw list accessor
    `_action_items(output)` is fine to reuse (it performs no joining or
    normalisation of its own); the join itself must stay private to this
    check.
    """
    forbidden = _exp(input_text).get("must_not_commit") or []
    if not forbidden:
        return True, ""
    text = " | ".join(str(i) for i in _action_items(output)).lower()
    present = [str(t) for t in forbidden if str(t).lower() in text]
    if present:
        return False, ("withdrawn proposal(s) present in action_items: "
                       f"{', '.join(present)}")
    return True, ""


check_withdrawn_excluded.bucket = "quality"
