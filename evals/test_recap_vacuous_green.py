#!/usr/bin/env python3
"""The ledger-017 invariant, asserted mechanically: an uncommitted input must NOT score.

THE HOLE THIS CLOSES. Every check in evals/recap/properties.py resolves its expectations
with `_exp(input_text).get(<key>)` and returns pass when the key is absent — correct for a
case that declares no such expectation, catastrophic for an input that is not a committed
case at all. `_exp` used to be:

    return _expectations_by_input().get(input_text, {})

so an unmatched input returned {} and passed ALL FOUR checks at once. Nothing was red.
Nothing was logged. The case simply scored full marks for being unrecognisable.

WHY IT IS NOT HYPOTHETICAL. That is exactly what happens when a case's input is built by
appending a constraint to an existing case's text — E26's first design, caught on paper by
the falsifier-first doctrine. The appended text no longer matches any committed key, so the
case scores a silent vacuous green while appearing to test something new.

WHY IT MATTERS MORE THAN A NORMAL BUG. This repo's whole product is that its scores mean
something. A check that cannot fail is worse than a missing check: a missing check is
visibly missing, while a vacuous one reports success.

ASSERTED THROUGH THE REAL SCORING PATH (A4 / ledger 012 — an ad-hoc probe is not a witness
for the tool). Everything below goes through R.run_properties, the same function
runner.py uses to score a committed case, not by calling the check functions directly.
"""
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import runner as R  # noqa: E402

sys.path.insert(0, str(ROOT / "evals" / "recap"))
import properties as P  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


CASES = json.loads((ROOT / "evals" / "recap" / "cases.json").read_text())["cases"]
PROPS = R.load_properties("recap")

# A committed case, and an output good enough that the scoring path has to consult the
# expectations rather than bailing early on shape.
BASE = CASES[0]
GOOD_ENOUGH = {"recap": "x", "nothing_important": False}


print("== committed inputs still resolve (the guard must not break scoring) ==")

resolved = 0
for c in CASES:
    try:
        P._exp(c["input"])
        resolved += 1
    except Exception as exc:  # noqa: BLE001
        check(f"committed case {c['id']} resolves", False, repr(exc))
check(f"all {len(CASES)} committed cases resolve their expectations", resolved == len(CASES),
      f"{resolved}/{len(CASES)}")

# The guard must not turn a legitimately-empty expectation into a failure. A case whose
# `expected` block omits a key must still pass that key's check — that is the behaviour
# the permissive `.get(key)` inside each check is FOR, and the guard sits above it.
check("a committed case's expectations are returned as a dict",
      isinstance(P._exp(BASE["input"]), dict))


print()
print("== an UNCOMMITTED input must fail loudly, not score ==")

# THE ATTACK, built by hand rather than imagined (Lane A2's rule): take a real case and
# append a constraint to its input, which is how a plausible new case gets authored.
MUTATED = BASE["input"] + "\n\nExtra constraint: keep the recap under 200 characters."

raised = False
try:
    P._exp(MUTATED)
except KeyError:
    raised = True
except Exception as exc:  # noqa: BLE001
    check("mutated input raises KeyError specifically", False, f"raised {type(exc).__name__}")
check("appending a constraint to a committed input raises rather than returning {}", raised)

# The one that actually matters: through run_properties, the way a case is really scored.
ok, failures, failed = R.run_properties(PROPS, MUTATED, GOOD_ENOUGH)
check("run_properties REJECTS an uncommitted input (was: silent 4/4 pass)", ok is False,
      f"ok={ok} failed={[f['check'] for f in failed]}")
check("the rejection names the cause rather than failing opaquely",
      any("does not match any committed case" in f for f in failures),
      f"failures={failures}")

# Truncation is the other half of the same mutation family — a case built by cutting an
# input short also stops matching, and must not score either.
TRUNCATED = BASE["input"][: len(BASE["input"]) // 2]
ok_t, _f_t, _fc_t = R.run_properties(PROPS, TRUNCATED, GOOD_ENOUGH)
check("run_properties REJECTS a truncated committed input", ok_t is False, f"ok={ok_t}")

# An empty input is the degenerate case and the cheapest possible vacuous green.
ok_e, _f_e, _fc_e = R.run_properties(PROPS, "", GOOD_ENOUGH)
check("run_properties REJECTS an empty input", ok_e is False, f"ok={ok_e}")


print()
print("== the guard cannot be satisfied by a partial match ==")

# Substring containment must not be enough — expectations key on the WHOLE text.
PREFIX = BASE["input"][:-1]
ok_p, _f_p, _fc_p = R.run_properties(PROPS, PREFIX, GOOD_ENOUGH)
check("a one-character-short prefix of a committed input is REJECTED", ok_p is False,
      f"ok={ok_p}")


print()
print("== structural: no check may silently tolerate a missing expectations table ==")

# `_expectations_by_input` used to return {} when cases.json was absent, which made a
# deleted or misplaced cases.json score every case 4/4. Assert the source no longer
# contains that fallback. Read as text on purpose: this is a claim about the file, and
# monkeypatching the path would test our patch rather than the shipped code.
SRC = (ROOT / "evals" / "recap" / "properties.py").read_text()
check("_expectations_by_input raises on a missing cases.json (no `return {}` fallback)",
      "raise FileNotFoundError" in SRC and "if not path.exists():\n        return {}" not in SRC)

# Read the BODY, not the file: _exp's docstring quotes the old permissive line verbatim as
# documentation, so a naive text search over the file matches its own explanation and this
# assertion fails while the code is correct. (It did, on first run — a green-looking guard
# would have been the worse outcome, but a red-looking correct one is still a wrong test.)
_EXP_BODY = inspect.getsource(P._exp).replace(P._exp.__doc__ or "", "")
check("_exp's body no longer uses a permissive .get(input_text, {})",
      ".get(input_text, {})" not in _EXP_BODY)
check("_exp's body raises on an unknown input",
      "raise KeyError" in _EXP_BODY)


print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
    sys.exit(1)
print("all vacuous-green invariants hold")
