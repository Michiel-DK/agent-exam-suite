"""Property checks for recap (E13): the first LONG-INPUT exam in this suite.

Each check_* takes (input_text, output: dict) and returns (ok: bool, msg: str), and
declares a `bucket` marker ("format" | "quality") — the runner REFUSES to load a check
without one (fail loud, never a default).

WHY THIS FILE READS ITS OWN cases.json
--------------------------------------
Three of the checks are per-case parameterised (which items may not be omitted, how hard
this day must compress, whether it is a quiet day). The properties signature is fixed at
(input_text, output) and carries no `expected`, so the options were: change the shared
runner, or let the exam look up its own metadata. This does the latter — a per-exam
convention costs nothing outside this directory, whereas changing sandbox/runner.py for
one exam's needs puts every other exam's score on the diff.

Lookup is by EXACT input text, and an input that is NOT a committed case now RAISES.

That paragraph used to read: "an input that is not a committed case (live traffic, a probe)
resolves to {} and the parameterised checks pass vacuously — grounding and shape still
apply, which is exactly right." It was wrong, and it was the most expensive kind of wrong:
a documented rationale for a hole. Three of the four checks resolve through _exp, so an
unmatched input passed all of them, and the case scored full marks for being unrecognisable
rather than for being correct. Ledger 017's invariant; closed by _exp's guard below and
asserted in evals/test_recap_vacuous_green.py.

If a genuine live-traffic use ever needs unparameterised scoring, it must ask for it
explicitly — a separate entry point, not a silent fallback. Nothing does today: every
run_properties call site passes case["input"] (runner.py:699 and :1389).

THE DIRECTIONALITY RULE (docs/exam-audit-2026-07-22.md — shipped broken TWICE)
-----------------------------------------------------------------------------
  check_grounded  tests ABSENCE  — an invented number must NOT appear. Over-normalising
                                   here waves a fabrication through.
  check_coverage  tests PRESENCE — a required item MUST appear. Under-normalising here
                                   fails an honest recap.
They therefore normalise DIFFERENTLY and must never share a helper. Numbers go through
sandbox/numnorm.strip_thousands ONLY (the single shared implementation); nothing here
strips decimal points, because '65.00' and '6500' are different amounts.
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
    """{input_text: expected_dict} for the committed cases. Cached: this is read once
    per process, and cases.json is immutable during a run.

    Raises if cases.json is missing. It used to return {} — which, with the old
    permissive _exp below, meant a deleted or misplaced cases.json scored every case a
    silent 4/4. Fail loud, never a placeholder.
    """
    path = _HERE / "cases.json"
    if not path.exists():
        raise FileNotFoundError(
            f"recap properties: {path} is missing. Every check here resolves its "
            "expectations from that file; without it each check would find nothing to "
            "assert and pass vacuously."
        )
    data = json.loads(path.read_text())
    return {c["input"]: (c.get("expected") or {}) for c in data.get("cases", [])}


def _exp(input_text: str) -> dict:
    """Expectations for one case, resolved by EXACT input text.

    THIS FUNCTION IS THE LEDGER-017 INVARIANT. Every check in this file does
    `_exp(input_text).get(<key>)` and returns pass when the key is absent — which is
    correct for a case that genuinely declares no such expectation, and catastrophic for
    an input that is not a committed case at all. The old body was:

        return _expectations_by_input().get(input_text, {})

    so an unmatched input returned {} and scored a **silent vacuous green on all four
    checks at once**. The failure mode is not hypothetical: it is exactly what happens
    when a case's input is built by appending a constraint to an existing case's text
    (E26's first design), because the appended text no longer matches any committed key.

    Raising is the whole point. `run_properties` converts an exception into a FAILED
    check ("a broken check is a failed check, loudly", runner.py:179), so an unmatched
    input now fails loudly through the real scoring path instead of passing silently.

    A new exam case must therefore be a NEW committed entry in cases.json with its own
    `expected` block — never a mutation of an existing case's input at runtime.
    """
    table = _expectations_by_input()
    if input_text not in table:
        preview = input_text[:60].replace("\n", " ") if isinstance(input_text, str) else input_text
        raise KeyError(
            "recap properties: this input does not match any committed case in "
            f"evals/recap/cases.json (len={len(input_text) if isinstance(input_text, str) else '?'}, "
            f"starts {preview!r}). Expectations resolve by EXACT input text, so scoring it "
            "would pass every check vacuously. Add it to cases.json with its own `expected` "
            "block rather than mutating an existing case's input."
        )
    return table[input_text]


def _recap(output) -> str:
    return (output or {}).get("recap") or "" if isinstance(output, dict) else ""


# ------------------------------------------------------------------ format

def check_output_shape(input_text, output):
    """Fail loud on a malformed answer instead of letting a later check read a default."""
    if not isinstance(output, dict):
        return False, f"output is {type(output).__name__}, not a JSON object"
    recap = output.get("recap")
    if not isinstance(recap, str) or not recap.strip():
        return False, "missing or empty 'recap' string"
    if not isinstance(output.get("nothing_important"), bool):
        return False, (f"'nothing_important' must be a bool, got "
                       f"{type(output.get('nothing_important')).__name__}")
    return True, ""


check_output_shape.bucket = "format"


# ------------------------------------------------------------------ quality

_NUM_RE = re.compile(r"\d[\d.,]*\d|\d")


def check_grounded(input_text, output):
    """ABSENCE check: every number in the recap must appear in the source.

    This is the fabrication check, and the one that carries to E19 — a diary that invents
    a figure you never wrote is worse than a wrong email, because you would believe it.
    Normalisation is deliberately MINIMAL (thousands separators only, shared helper).
    Decimal points are load-bearing and never stripped.
    """
    src_nums = {_strip_thousands(n) for n in _NUM_RE.findall(input_text)}
    invented = []
    for raw in _NUM_RE.findall(_recap(output)):
        n = _strip_thousands(raw)
        # Substring, not equality, so "6500" inside a source "6500.00" reads as grounded
        # while a genuinely new figure does not.
        if not any(n in s for s in src_nums):
            invented.append(raw)
    if invented:
        return False, f"number(s) not in the source: {', '.join(sorted(set(invented)))}"
    return True, ""


check_grounded.bucket = "quality"


def check_coverage(input_text, output):
    """PRESENCE check: the items a correct recap cannot omit are all mentioned.

    Case-insensitive substring, deliberately generous — this check must never fail an
    honest recap over phrasing, or it becomes a style check wearing a coverage costume.
    """
    required = _exp(input_text).get("must_mention") or []
    if not required:
        return True, ""
    recap = _recap(output).lower()
    missing = [t for t in required if str(t).lower() not in recap]
    if missing:
        return False, f"omitted required item(s): {', '.join(missing)}"
    return True, ""


check_coverage.bucket = "quality"


def check_compression(input_text, output):
    """The recap must be materially shorter than the day it summarises.

    A 'summary' the length of its source has not summarised, and that is checkable
    without a judge. Ratio is per-case: a 3-item quiet day cannot compress as hard as
    an 18-item one.
    """
    ratio = _exp(input_text).get("max_ratio")
    if ratio is None:
        return True, ""
    limit = int(len(input_text) * float(ratio))
    got = len(_recap(output))
    if got > limit:
        return False, (f"recap is {got} chars vs limit {limit} "
                       f"({float(ratio):.2f} x {len(input_text)} source chars)")
    return True, ""


check_compression.bucket = "quality"


def check_abstention(input_text, output):
    """A quiet day must produce 'nothing important', NOT padded filler.

    The tempting fabrication here is inventing SIGNIFICANCE — the same failure E19's
    diary half turns on (manufacturing a memory that was not there). Checked on the
    STRUCTURED flag, not on prose, so it cannot be gamed by phrasing and cannot
    false-fail an honest recap over wording.

    Both directions are real failures:
      quiet day -> flag must be True, AND the recap must stay under a tight char cap
                   (a model can set the flag honestly and still pad three paragraphs)
      busy day  -> flag must be False; abstaining on a day that needed attention is the
                   opposite error and is just as wrong
    """
    exp = _exp(input_text)
    want = exp.get("nothing_important")
    if want is None:
        return True, ""
    got = output.get("nothing_important") if isinstance(output, dict) else None
    if got is not want:
        if want:
            return False, (f"quiet day: expected nothing_important=true, got {got!r} "
                           f"— manufactured significance")
        return False, (f"busy day: expected nothing_important=false, got {got!r} "
                       f"— abstained on a day that needed attention")
    cap = exp.get("abstain_max_chars")
    if want and cap is not None and len(_recap(output)) > int(cap):
        return False, (f"abstained but padded: recap {len(_recap(output))} chars "
                       f"exceeds the {cap}-char quiet-day cap")
    return True, ""


check_abstention.bucket = "quality"
