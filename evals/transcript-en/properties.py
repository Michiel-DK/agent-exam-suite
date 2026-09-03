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
