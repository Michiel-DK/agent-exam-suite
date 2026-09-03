#!/usr/bin/env python3
"""recap — ADVERSARIAL FIXTURES: strategies that must NOT survive the exam.

WHY THIS FILE EXISTS (ledger 014, and the mistake that produced it)
-------------------------------------------------------------------
`test_e13_recap.py` asserts ISOLATION: for each check, some case fails ONLY that check.
That is necessary and it is not sufficient. Lane A shipped two cases as "guardrails"
against a strategy that wins on compression by DROPPING content, asserted in a commit
message and a PR body that the band now caught such a strategy — and it did not. A
hand-built degenerate output tied the champion. Isolation was green the whole time,
because isolation asks "can this check fire?", never "can something cheap beat it?".

This is mutation testing, applied to the model's OUTPUT space instead of source code:
deliberately construct the outputs a lazy or degenerate strategy would produce, and
assert the exam rejects them. It is deterministic, needs no inference, and runs in
milliseconds — the check that would have caught Lane A's error automatically.

THE INVARIANTS. Each is a property of the INSTRUMENT, not of any model, so a champion
swap cannot silently disarm them (the failure mode that dormant-ed E10's error_recovery
rung).

  1. A content-free recap must fail EVERY long case.
  2. A recap that echoes its input must fail compression EVERYWHERE.
  3. Abstaining on a day that needed attention must fail.
  4. Padding while abstaining must fail on every quiet day that caps it.
  5. An invented figure must fail grounding.

If a future case is added to the long band without a coverage floor, invariant 1 fails
and this file says so by name.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import runner as R  # noqa: E402

FAILED = []
LONG_MIN = 4200  # the band E13 measured the length effect on; see docs/e13-brief.md


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


CASES = json.loads((ROOT / "evals" / "recap" / "cases.json").read_text())["cases"]
PROPS = R.load_properties("recap")
BY_ID = {c["id"]: c for c in CASES}
LONG = [c for c in CASES if len(c["input"]) >= LONG_MIN]
QUIET = [c for c in CASES if (c.get("expected") or {}).get("nothing_important") is True]
BUSY = [c for c in CASES if (c.get("expected") or {}).get("nothing_important") is False]


def verdict(case, output):
    """(passed, [check names]) through the REAL scoring path, never a reimplementation."""
    ok, _failures, failed = R.run_properties(PROPS, case["input"], output)
    return ok, [f["check"] for f in failed]


# ------------------------------------------------------------------ the fixtures

# The degenerate chunk-and-reduce / over-compressing strategy: fluent, short, grounded
# by vacuity (NO numbers at all, so the absence-style check_grounded CANNOT fire), and
# naming nobody. This is the one that tied the champion before the coverage floors.
CONTENT_FREE = {"recap": "A number of messages came in today, including some client "
                         "correspondence and several automated notices.",
                "nothing_important": False}

ECHOES_INPUT = {"recap": None, "nothing_important": False}  # filled per case
ABSTAINS_ON_BUSY = {"recap": "Nothing important today.", "nothing_important": True}
PADS_WHILE_ABSTAINING = {"recap": "Nothing needed your attention today. " * 30,
                         "nothing_important": True}


def test_1_content_free_recap_fails_every_long_case():
    """THE invariant Lane A got wrong. A recap that names nothing must survive nowhere
    in the long band — via coverage where items are required, via abstention on a quiet
    day (it wrongly claims the day mattered)."""
    for c in LONG:
        ok, checks = verdict(c, CONTENT_FREE)
        check(f"content-free rejected by {c['id']} ({len(c['input'])} ch)",
              not ok, f"PASSED with checks={checks} — this case has no coverage floor")


def test_1b_salience_only_recap_fails_where_the_day_has_several_items():
    """The REALISTIC degenerate strategy, and the one that actually beat us.

    `content-free` above names nobody, which is a strawman — it was already rejected
    before this lane. The observed failure (llama3.1, sweep 2026-07-29) is subtler: a
    fluent 104-225 char recap that names the single most salient item and silently drops
    the rest. It passed 6 of 8 long cases.

    Invariant: naming ONE required item must not be enough on a day that has several.
    Cases declaring exactly one anchor are exempt by design — `buried-critical-xl` tests
    retrieval of one buried item, so naming it IS the correct answer there.
    """
    for c in LONG:
        anchors = (c.get("expected") or {}).get("must_mention") or []
        if len(anchors) < 2:
            continue
        out = {"recap": f"The main item today was from {anchors[0]}.",
               "nothing_important": False}
        _ok, checks = verdict(c, out)
        check(f"salience-only rejected by {c['id']} ({len(anchors)} anchors)",
              "check_coverage" in checks,
              f"naming only {anchors[0]!r} survived — checks={checks}")


def test_2_content_free_is_not_rejected_for_the_wrong_reason():
    """It must fail on SUBSTANCE (coverage/abstention), not merely on compression —
    otherwise the rejection is an artifact of its length and a slightly longer
    degenerate output would slip through."""
    for c in LONG:
        _ok, checks = verdict(c, CONTENT_FREE)
        substantive = {"check_coverage", "check_abstention"} & set(checks)
        check(f"{c['id']} rejects content-free on substance",
              bool(substantive), f"only tripped {checks}")


def test_3_echoing_the_input_fails_compression_everywhere():
    """A 'summary' the length of its source has not summarised. Holds on every case
    that declares a ratio, long or short."""
    for c in CASES:
        if (c.get("expected") or {}).get("max_ratio") is None:
            continue
        out = {"recap": c["input"], "nothing_important": False}
        _ok, checks = verdict(c, out)
        check(f"echo fails compression on {c['id']}",
              "check_compression" in checks, f"checks={checks}")


def test_4_abstaining_on_a_busy_day_fails():
    """The inverse of over-significance, and just as wrong: declaring a day quiet when
    it needed the owner."""
    for c in BUSY:
        _ok, checks = verdict(c, ABSTAINS_ON_BUSY)
        check(f"false abstention caught on {c['id']}",
              "check_abstention" in checks, f"checks={checks}")


def test_5_padding_while_abstaining_fails_where_capped():
    """A model can set the flag honestly and still pad three paragraphs."""
    for c in QUIET:
        if (c.get("expected") or {}).get("abstain_max_chars") is None:
            check(f"{c['id']} declares an abstain cap", False,
                  "quiet case with no abstain_max_chars — padding is unchecked here")
            continue
        _ok, checks = verdict(c, PADS_WHILE_ABSTAINING)
        check(f"padded abstention caught on {c['id']}",
              "check_abstention" in checks, f"checks={checks}")


def test_6_an_invented_figure_fails_grounding():
    """check_grounded is an ABSENCE check, so it is proven by injecting a figure that is
    demonstrably not in the source — not by observing an honest recap pass."""
    for c in CASES:
        needle = "999777333"  # absent from every committed case by construction
        assert needle not in c["input"], f"{c['id']} contains the sentinel"
        out = {"recap": f"Total outstanding was {needle} EUR.", "nothing_important": False}
        _ok, checks = verdict(c, out)
        check(f"invented figure caught on {c['id']}",
              "check_grounded" in checks, f"checks={checks}")


# Long cases allowed to require exactly ONE item, with the reason. This list is the
# whole exemption surface: anything not named here needs a real floor. Adding to it is
# a deliberate, reviewable act — which is the point, since the last hole was created by
# nobody having to justify a one-item floor.
SINGLE_ANCHOR_BY_DESIGN = {
    "buried-critical-xl": "tests retrieval of ONE item buried mid-list ('lost in the "
                          "middle'); the day contains exactly one item needing the owner, "
                          "so naming it IS the correct answer",
}


def test_7_long_band_floors_are_proportionate_not_merely_present():
    """THE structural guard, and the one that had to be strengthened to be worth having.

    A first draft of this test only asserted `must_mention` was non-empty. That was
    already true of every long case when the hole existed — three of them declared ONE
    anchor, and a recap naming that single item sailed through. A guard that is green on
    the broken state is not a guard.

    So the rule is proportionality: a long, non-quiet case requires >= 2 items unless it
    is explicitly exempted above with a stated reason.
    """
    for c in LONG:
        exp = c.get("expected") or {}
        anchors = exp.get("must_mention") or []
        if exp.get("nothing_important") is True:
            check(f"{c['id']} is a declared quiet day (no floor needed)",
                  not anchors, "quiet day should not also demand items")
            continue
        if c["id"] in SINGLE_ANCHOR_BY_DESIGN:
            check(f"{c['id']} exempted: {SINGLE_ANCHOR_BY_DESIGN[c['id']][:48]}...",
                  len(anchors) >= 1, "exempted case still needs at least one anchor")
            continue
        check(f"{c['id']} declares >=2 required items ({len(anchors)})",
              len(anchors) >= 2,
              f"long non-quiet case with {len(anchors)} anchor(s) — a recap naming just "
              f"that one passes for free; add anchors or exempt it with a reason")


def main() -> int:
    print(f"recap adversarial fixtures — {len(CASES)} cases, {len(LONG)} in the long band")
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)), key=lambda f: f.__name__):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all green'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
