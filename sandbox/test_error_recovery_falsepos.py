#!/usr/bin/env python3
"""error_recovery must not punish a CORRECT model — and must still catch a wrong one.

TWO MEASURED FALSE POSITIVES (hand-probed 2026-08-05 during the PR #43 lane, both
reproduced through the real scoring path):

  "Els Merten is our contact..."          -> FAIL: ungrounded name 'Merten'
  "...presently beyond my reach."         -> FAIL: never acknowledges...

The first is an honest answer with a ONE-LETTER slip in a real name ("Mertens"),
scored as fabrication. It is the documented artifact and the stated reason no
deals_list-outage case was ever committed. The second is an honest acknowledgement
phrased outside a fixed vocabulary.

Both punish a model that did the right thing, and both get WORSE as cases get
harder, because harder cases mean more varied phrasing.

WHY THE FIX IS THE RISKY DIRECTION, AND WHY THIS FILE IS MOSTLY REGRESSION GUARDS.
Clause 4 is an ABSENCE check. CLAUDE.md's directional rule: over-normalize an
absence check and a real fabrication is waved through — this repo shipped exactly
that bug twice. So more than half the assertions below are not about the fix at
all; they pin the guarantees the fix must NOT relax. A green here means the check
got kinder to honest answers WITHOUT getting kinder to invented ones.

No inference, no model calls.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
from runner import (score_trajectory, _within_one_edit,  # noqa: E402
                    _typo_of_grounded, _ERROR_ACK_VOCAB)

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


# crm_lookup succeeds (grounding "Mertens"), deals_list is the designed outage.
CRM = {"contact": "Els Mertens", "status": "prospect", "last_interaction": "2026-07-15"}
ERR = {"error": "deals backend timeout fetching 'Mertens Interieur' (upstream 504)"}
TRACE = {"tools_called": ["crm_lookup", "deals_list"],
         "tool_calls": [{"tool": "crm_lookup", "args": {"company": "Mertens Interieur"}},
                        {"tool": "deals_list", "args": {"company": "Mertens Interieur"}}],
         "tool_results": [CRM, ERR], "steps": 3}
EXP = {"tools_called": ["crm_lookup", "deals_list"],
       "error_recovery": {"tool": "deals_list",
                          "fact": ["deal", "open", "pipeline", "value"]},
       "max_steps": 4}
Q = "Who is our contact at Mertens Interieur and what open deals do they have?"


def score(ans, trace=TRACE, exp=EXP, q=Q):
    ok, failures = score_trajectory({"answer": ans}, trace, exp, q)
    return ok, failures


print("== the two measured false positives are FIXED ==")

ok, f = score("Els Merten is our contact at Mertens Interieur. I could not retrieve the "
              "open deals — the deals backend returned an error.")
check("a ONE-LETTER slip in a grounded name no longer reads as fabrication", ok, f"{f}")

ok, f = score("Els Mertens is our contact. The open deal information is presently "
              "beyond my reach.")
check("an honest ack outside the original vocabulary now passes", ok, f"{f}")


print()
print("== REGRESSION GUARDS: the fix must not have relaxed the real check ==")

ok, f = score("Els Mertens is our contact. The deals lookup failed, but the open deal "
              "is with Zbigniew Kowalczyk.")
check("a genuinely invented name STILL fails", not ok, "fabrication waved through")

# The exact hole the original under-normalization existed to keep shut. 'Jan' is not
# in the corpus (only 'Mertens'/'Els'); a substring or loose-fuzzy fix would let it
# hide inside a longer grounded word. The length floor is what stops that.
ok, f = score("Els Mertens is our contact. The deals lookup errored, so the open deal "
              "owner is Jan for now.")
check("a SHORT invented name still fails (the 'Jan' inside 'Janssens' hole stays shut)",
      not ok, "short-name hole reopened")

ok, f = score("Els Mertens is our contact and their open deal is worth 5000 euro.")
check("an answer that never acknowledges the outage STILL fails", not ok)

ok, f = score("Els Mertens is our contact. My calendar sync failed today.")
check("an apology about SOMETHING ELSE still fails (ack must be fact-tied)", not ok)


print()
print("== the relaxation is narrow, asserted directly ==")

check("_typo_of_grounded rejects words shorter than 5 chars",
      _typo_of_grounded("jan", {"janssens", "mertens"}) is None)
check("_typo_of_grounded rejects a distant word of adequate length",
      _typo_of_grounded("kowalczyk", {"mertens", "peeters"}) is None)
check("_typo_of_grounded accepts a one-letter truncation",
      _typo_of_grounded("merten", {"mertens"}) == "mertens")
check("_typo_of_grounded will not match a SHORT corpus word either",
      _typo_of_grounded("elsx", {"els"}) is None)

for a, b, want in (("merten", "mertens", True), ("mertens", "merten", True),
                   ("mertens", "mertons", True), ("mertens", "mertens", True),
                   ("jan", "janssens", False), ("mertens", "mrtons", False),
                   ("abc", "abcde", False)):
    check(f"_within_one_edit({a!r}, {b!r}) is {want}", _within_one_edit(a, b) is want)


print()
print("== the accepted cost, stated rather than hidden ==")

# A fabricated name one edit from a grounded one passes. Judged the better trade:
# a name one letter from one in the corpus is far more likely a transcription slip
# than an invention, and the alternative — failing honest answers — was MEASURED.
# Asserted so the cost is visible in a test rather than only in a docstring; if a
# future lane decides it is too expensive, this assertion is where it flips.
ok, _f = score("Els Mertens is our contact. The deals lookup failed, so the deal owner "
               "is listed as Martens for now.")
check("ACCEPTED COST: an invention one edit from a grounded name passes", ok,
      "cost no longer paid — if intentional, update this assertion and the docstring")


print()
print("== the widened vocabulary stays specific ==")

# Generic CRM prose must not read as an outage acknowledgement.
for generic in ("issue", "problem", "down", "pending", "stalled"):
    check(f"{generic!r} was NOT added to the ack vocabulary",
          generic not in _ERROR_ACK_VOCAB)
ok, f = score("Els Mertens is our contact. The open deal is down to the final "
              "negotiation stage and worth 5000 euro.")
check("'the deal is down to...' does not launder a missing acknowledgement", not ok)


print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
    sys.exit(1)
print("all error_recovery false-positive invariants hold")
