"""Property checks for task-intake (A4, 2026-09-04): the label half of the verdict is
the exam's `labels` mode (`expected.agent`); these checks grade the OTHER half — the
hand-over. A dispatcher that names the right specialist but hands it a paraphrase, a
fragment, or an invented line has not dispatched anything.

Each check_* takes (input_text, output: dict) and returns (ok: bool, msg: str), with a
`bucket` marker ("format" | "quality") — same contract as every properties.py here.

DIRECTIONAL by design (CLAUDE.md gotcha 4): `check_input_is_verbatim_span` is a
PRESENCE check on the request (the hand-over must be a contiguous span OF the request)
plus a COVERAGE floor — it uses whitespace-collapse + lower-case only, never digit
normalization, so a hand-over that "fixes" a number is not a span and fails.
"""
import json
import re
from pathlib import Path

ROSTER = ("email-triage", "reply-draft", "crm-followup", "expense-categorization",
          "recap", "transcript-en")
NONE = "none"

# Coverage floor for a hand-over: a contiguous span of the request holding at least
# this share of the request's non-whitespace characters. Below it, the "span" is a
# cherry-picked fragment (a model that hands "the" to reply-draft has extracted
# nothing). The instruction sentence a request carries ("Draft a reply to this:") is
# typically 5–20% of it, which is why the floor sits at half, not near one.
MIN_COVERAGE = 0.5


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


_CASES = Path(__file__).with_name("cases.json")
_GOLDEN: dict | None = None


def _golden_handover(input_text: str):
    """The committed `handover` span for THIS request, resolved by EXACT input text —
    the recap `_exp` discipline (evals/recap/properties.py): a case is what its text
    says it is, never a fuzzy match. Cases without a `handover` key, and LIVE requests
    that match no committed case, resolve to None and fall back to the coverage floor
    below. Added 2026-09-05 after a refuter showed the floor made a multi-payload case
    unpassable: the correct hand-over (the crm question) is 26% of a request that also
    carries an embedded email, so only a span that INCLUDES the decoy could clear 50%."""
    global _GOLDEN
    if _GOLDEN is None:
        cases = json.loads(_CASES.read_text())["cases"]
        _GOLDEN = {c["input"]: c["handover"] for c in cases if c.get("handover")}
    return _GOLDEN.get(input_text)


def check_agent_in_roster(input_text, output):
    agent = output.get("agent")
    if agent in ROSTER or agent == NONE:
        return True, ""
    return False, f"agent {agent!r} is not one of {ROSTER + (NONE,)}"


check_agent_in_roster.bucket = "format"


def check_none_hands_over_nothing(input_text, output):
    """A 'none' verdict with material attached is a dispatch to nowhere — and the
    inverse, a specialist named with an empty hand-over, is a dispatch of nothing."""
    agent = output.get("agent")
    handed = _norm(output.get("input", ""))
    if agent == NONE:
        return (not handed), (f"agent is 'none' but input is {handed[:60]!r}" if handed else "")
    if agent in ROSTER:
        return bool(handed), ("" if handed else f"agent {agent!r} named but input is empty")
    return True, ""   # a bad roster value is check_agent_in_roster's finding, not this one's


check_none_hands_over_nothing.bucket = "format"


def check_input_is_verbatim_span(input_text, output):
    """The hand-over must be a contiguous span of the request (nothing invented, nothing
    paraphrased) covering at least MIN_COVERAGE of the request's non-whitespace
    characters (nothing cherry-picked). Quiet for 'none' — that is the check above."""
    agent = output.get("agent")
    if agent not in ROSTER:
        return True, ""
    handed, request = _norm(output.get("input", "")), _norm(input_text)
    if not handed:
        return True, ""   # the empty hand-over is check_none_hands_over_nothing's finding
    if handed not in request:
        return False, (f"input is not a verbatim span of the request (starts "
                       f"{handed[:50]!r})")
    golden = _golden_handover(input_text)
    if golden is not None:
        # Multi-payload request: the committed span IS the material; the hand-over
        # must contain it (a hand-over of the whole request still passes — the
        # instruction-stripping gap stays declared — but a span that drops the real
        # payload for the decoy one fails).
        if _norm(golden) in handed:
            return True, ""
        return False, f"input does not contain the committed hand-over ({golden[:50]!r})"
    cov = len(handed.replace(" ", "")) / max(1, len(request.replace(" ", "")))
    if cov < MIN_COVERAGE:
        return False, f"input covers only {cov:.0%} of the request (floor {MIN_COVERAGE:.0%})"
    return True, ""


check_input_is_verbatim_span.bucket = "quality"
