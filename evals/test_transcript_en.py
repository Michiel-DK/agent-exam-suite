#!/usr/bin/env python3
"""transcript-en (S-TRANSCRIPT-EN-EXAM) — check tests: isolation, adversarial
fixtures, and the ledger-017 vacuous-green guard, all in one file (this exam's
declaredFiles list ONE test file; recap split the same coverage across three —
test_e13_recap.py / test_recap_adversarial.py / test_recap_vacuous_green.py — this
file carries their combined role for transcript-en).

Every assertion below was built by hand and SEEN RED before being kept (CLAUDE.md
gotcha 2: "a green guard proves nothing until seen RED" — two adversarial tests in
this repo once looked green while asserting nothing). Concretely: each fixture in
this file was run once through R.run_properties with a manual print of the
resulting `failed_checks` BEFORE the `check(...)` assertion around it was written,
to confirm the fixture actually fails the way the assertion claims.

THREE THINGS THIS FILE PROVES, mirroring recap's three-file split:

  1. ISOLATION (mirrors test_e13_recap.py). For every check, a synthetic output
     fails ONLY that check on some committed case. This is the load-bearing part
     for check_action_items specifically — CLAUDE.md gotcha 3 / the build
     criterion require it, and it has been shipped unfalsifiable three times in
     this repo, each time disguised by a score moving the expected direction.

  2. ADVERSARIAL FIXTURES (mirrors test_recap_adversarial.py). Deliberately
     construct the outputs a lazy or degenerate strategy would produce —
     content-free, echoing, false-abstaining, padding, inventing a figure — and
     assert the exam rejects them. Mutation testing applied to the model's OUTPUT
     space: deterministic, no inference, catches exactly the failure mode that let
     a hand-built degenerate output tie recap's champion while isolation stayed
     green the whole time (recap's Lane A).

  3. THE LEDGER-017 VACUOUS-GREEN GUARD (mirrors test_recap_vacuous_green.py). An
     input that does not match any committed case must RAISE through the real
     scoring path (R.run_properties), never resolve to {} and pass every
     parameterised check for free.

Everything goes through R.run_properties, the SAME function runner.py uses to
score a committed case (CLAUDE.md gotcha 5: an ad-hoc probe is not a witness for
the tool) — never a reimplementation of the check logic.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import runner as R  # noqa: E402

sys.path.insert(0, str(ROOT / "evals" / "transcript-en"))
import properties as P  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


CASES = json.loads((ROOT / "evals" / "transcript-en" / "cases.json").read_text())["cases"]
BY_ID = {c["id"]: c for c in CASES}
PROPS = R.load_properties("transcript-en")
LONG_MIN = 3200  # this exam's shortest genuinely long-band case (discovery-heldout-long)
LONG = [c for c in CASES if len(c["input"]) >= LONG_MIN]
QUIET = [c for c in CASES if (c.get("expected") or {}).get("nothing_important") is True]
BUSY = [c for c in CASES if (c.get("expected") or {}).get("nothing_important") is False]


def verdict(case_id, output):
    """(ok, [check names]) through the REAL scoring path, never a reimplementation."""
    case = BY_ID[case_id]
    ok, _failures, failed = R.run_properties(PROPS, case["input"], output)
    return ok, [f["check"] for f in failed]


def only(case_id, output, expected_check):
    """Assert this output fails EXACTLY the named check and nothing else."""
    ok, names = verdict(case_id, output)
    check(f"{case_id}: fails ONLY {expected_check}",
          not ok and names == [expected_check], f"failed_checks={names}")


# ---------------------------------------------------------------- 0. sanity: cases load

def test_0_every_committed_case_has_a_bucket_marked_check_set():
    check("6 checks loaded, each with a valid bucket",
          len(PROPS) == 6, f"got {len(PROPS)}: {[n for n, _ in PROPS]}")
    check("22 committed cases", len(CASES) == 22, f"got {len(CASES)}")
    n_train = sum(1 for c in CASES if c["split"] == "train")
    n_heldout = sum(1 for c in CASES if c["split"] == "heldout")
    check("heldout N >= 12 (power requirement)", n_heldout >= 12,
          f"train={n_train} heldout={n_heldout}")


# ---------------------------------------------------------------- 1. baselines pass everything

# A correct summary for a busy call: covers must_mention, lists the required
# commitments, correct nothing_important, well under the ratio cap.
GOOD_BUSY = {
    "summary": "Dana spoke with Marcus at Beacon Freight about scaling shipment "
               "tracking beyond spreadsheets. Quoted 900 EUR per month. Marcus "
               "will loop in finance director Elena before committing.",
    "action_items": ["Rep to send a one-page proposal today",
                     "Rep and prospect to hold a follow-up call Thursday"],
    "nothing_important": False,
}

# A correct summary for a quiet call: abstains, empty action_items, short.
GOOD_QUIET = {
    "summary": "Routine monthly check-in with Sam. Everything running smoothly, "
               "no complaints, no new requests from the team.",
    "action_items": [],
    "nothing_important": True,
}


def test_1_good_outputs_pass_every_check():
    """Direction 2 of both-direction: the checks must be SILENT on a correct
    answer. A check that fires on a good summary is worse than no check."""
    ok, names = verdict("discovery-short-train", GOOD_BUSY)
    check("good busy-call summary passes ALL checks", ok, f"failed={names}")
    ok, names = verdict("quiet-checkin-short-train", GOOD_QUIET)
    check("good quiet-call summary passes ALL checks", ok, f"failed={names}")


# ---------------------------------------------------------------- 2. isolation (the load-bearing part)

def test_2_isolation_check_action_items():
    """THE isolation the build criterion names explicitly. A summary that covers
    every must_mention item, at a correct ratio, with the correct nothing_important
    flag, but whose action_items list omits ONE required commitment ('Thursday')
    fails check_action_items and NOTHING else.

    Verified RED before this assertion was kept: without this fixture,
    check_action_items has never been made to fail on its own by anything in this
    file, which is exactly the "unfalsifiable check" failure mode CLAUDE.md gotcha
    3 names — shipped three times in this repo, each disguised by a score moving
    the right way.
    """
    only("discovery-short-train",
         {"summary": "Dana spoke with Marcus at Beacon Freight about scaling "
                     "shipment tracking. Quoted 900 EUR per month. Marcus will "
                     "loop in Elena before committing.",
          "action_items": ["Rep to send a one-page proposal today"],  # Thursday missing
          "nothing_important": False},
         "check_action_items")


def test_2b_check_output_shape_fires_on_malformed_output():
    """check_output_shape is NOT required to isolate (recap's own
    check_output_shape isolation test uses `in names`, never `== [name]` —
    test_e13_recap.py lines 144-147 — because a malformed/empty output starves
    every other check's inputs too, so several fire together; only
    check_action_items, the NEW check, is required to isolate by the build
    criterion). Assert it FIRES, matching repo precedent."""
    ok, names = verdict("discovery-short-train",
                        {"summary": "", "action_items": [], "nothing_important": False})
    check("empty summary -> check_output_shape fires",
          not ok and "check_output_shape" in names, str(names))
    ok, names = verdict("discovery-short-train", "not a dict")
    check("non-dict output -> check_output_shape fires",
          not ok and "check_output_shape" in names, str(names))
    ok, names = verdict("discovery-short-train",
                        {"summary": "x", "action_items": "not a list", "nothing_important": False})
    check("non-list action_items -> check_output_shape fires",
          not ok and "check_output_shape" in names, str(names))


def test_2c_isolation_check_grounded():
    """Invents a figure. Coverage and action_items still satisfied, still short,
    flag still correct — the ONLY problem is the invented number."""
    only("discovery-short-train",
         {"summary": "Dana spoke with Marcus at Beacon Freight, quoting 900 EUR "
                     "per month plus a surprise 12345 EUR setup fee. Elena will "
                     "review.",
          "action_items": ["Rep to send a one-page proposal today",
                           "Rep and prospect to hold a follow-up call Thursday"],
          "nothing_important": False},
         "check_grounded")


def test_2d_isolation_check_coverage():
    """Omits a required must_mention item (Elena) from the summary while
    everything else — action_items, ratio, flag — stays correct."""
    only("discovery-short-train",
         {"summary": "Dana quoted Marcus 900 EUR per month for the platform "
                     "after discussing spreadsheet scaling issues.",
          "action_items": ["Rep to send a one-page proposal today",
                           "Rep and prospect to hold a follow-up call Thursday"],
          "nothing_important": False},
         "check_coverage")


def test_2e_isolation_check_compression():
    """Echoes most of the source into the summary field — covers everything,
    grounds cleanly, correct flag and action_items, but blows the ratio cap."""
    src = BY_ID["discovery-short-train"]["input"]
    only("discovery-short-train",
         {"summary": src,  # 1421 chars vs a 568-char (0.40 x 1421) cap
          "action_items": ["Rep to send a one-page proposal today",
                           "Rep and prospect to hold a follow-up call Thursday"],
          "nothing_important": False},
         "check_compression")


def test_2f_isolation_check_abstention():
    """Quiet call, correct short summary, but action_items is non-empty — a
    manufactured commitment on a call that agreed nothing. Isolated from
    check_compression by keeping the summary itself short."""
    only("quiet-checkin-short-train",
         {"summary": "Routine check-in, nothing needed attention.",
          "action_items": ["Schedule next check-in"],
          "nothing_important": True},
         "check_abstention")


# ---------------------------------------------------------------- 3. adversarial fixtures

CONTENT_FREE = {"summary": "A call took place covering a few topics and some "
                           "follow-up items were discussed.",
                "action_items": [], "nothing_important": False}


def test_3_content_free_summary_fails_every_long_case():
    """The degenerate over-compressing strategy: fluent, short, grounded by
    vacuity (no numbers at all, so the absence-style check_grounded cannot fire),
    naming nobody. Must be rejected everywhere in the long band, via coverage
    (named anchors missing) or action_items (no real commitments listed)."""
    for c in LONG:
        ok, checks = verdict(c["id"], CONTENT_FREE)
        check(f"content-free rejected by {c['id']} ({len(c['input'])} ch)",
              not ok, f"PASSED with checks={checks}")


def test_3b_content_free_rejected_on_substance():
    """Must fail on SUBSTANCE (coverage / action_items / abstention), not merely
    on compression — otherwise the rejection is an artifact of length alone."""
    for c in LONG:
        _ok, checks = verdict(c["id"], CONTENT_FREE)
        substantive = {"check_coverage", "check_action_items", "check_abstention"} & set(checks)
        check(f"{c['id']} rejects content-free on substance",
              bool(substantive), f"only tripped {checks}")


def test_4_echoing_the_input_fails_compression_everywhere():
    """A 'summary' the length of its source has not summarised."""
    for c in CASES:
        if (c.get("expected") or {}).get("max_ratio") is None:
            continue
        out = {"summary": c["input"], "action_items": [], "nothing_important": False}
        _ok, checks = verdict(c["id"], out)
        check(f"echo fails compression on {c['id']}",
              "check_compression" in checks, f"checks={checks}")


def test_5_abstaining_on_a_busy_call_fails():
    """The inverse of over-significance: declaring a call quiet when it produced
    a real decision."""
    for c in BUSY:
        out = {"summary": "Nothing important came up on this call.",
              "action_items": [], "nothing_important": True}
        _ok, checks = verdict(c["id"], out)
        check(f"false abstention caught on {c['id']}",
              "check_abstention" in checks, f"checks={checks}")


def test_6_false_busy_on_a_quiet_call_fails():
    """The other direction: claiming a decision was made on a call that agreed
    nothing."""
    for c in QUIET:
        out = {"summary": "The call resulted in a firm decision to proceed.",
              "action_items": ["Rep to follow up with next steps"],
              "nothing_important": False}
        _ok, checks = verdict(c["id"], out)
        check(f"false busy-flag caught on {c['id']}",
              "check_abstention" in checks, f"checks={checks}")


def test_7_padding_while_abstaining_fails_where_capped():
    for c in QUIET:
        exp = c.get("expected") or {}
        if exp.get("abstain_max_chars") is None:
            check(f"{c['id']} declares an abstain cap", False,
                  "quiet case with no abstain_max_chars — padding is unchecked here")
            continue
        out = {"summary": "Nothing needed your attention on this call. " * 30,
              "action_items": [], "nothing_important": True}
        _ok, checks = verdict(c["id"], out)
        check(f"padded abstention caught on {c['id']}",
              "check_abstention" in checks, f"checks={checks}")


def test_8_action_items_on_a_quiet_call_fails_even_if_short():
    """A model can set the flag honestly, keep the summary short, and still
    manufacture a 'commitment' in action_items — this is the FAILURE OBSERVED FOR
    REAL on quiet-checkin-short-train during the calibration probe (2026-08-26):
    the champion set nothing_important=False AND invented a 'schedule next
    check-in' action item on a call that agreed nothing. This test proves the
    check would catch it even in the (harder) case where the flag itself is set
    correctly and only action_items leaks a manufactured item."""
    for c in QUIET:
        out = {"summary": "A quiet call, nothing needed attention.",
              "action_items": ["Schedule the next check-in call"],
              "nothing_important": True}
        _ok, checks = verdict(c["id"], out)
        check(f"manufactured action item on quiet call caught on {c['id']}",
              "check_abstention" in checks, f"checks={checks}")


def test_9_an_invented_figure_fails_grounding_in_either_field():
    """check_grounded is an ABSENCE check, proven by injecting a figure that is
    demonstrably not in the source — not by observing an honest summary pass.
    Checked in BOTH `summary` and `action_items`, since a fabricated number in an
    action item is exactly as much a fabrication."""
    needle = "999777333"  # absent from every committed case by construction
    for c in CASES:
        assert needle not in c["input"], f"{c['id']} contains the sentinel"
    for c in CASES:
        out_summary = {"summary": f"Total discussed was {needle} EUR.",
                       "action_items": [], "nothing_important": False}
        _ok, checks = verdict(c["id"], out_summary)
        check(f"invented figure in summary caught on {c['id']}",
              "check_grounded" in checks, f"checks={checks}")
        out_items = {"summary": "A call took place.",
                    "action_items": [f"Rep to send the {needle} EUR discount"],
                    "nothing_important": False}
        _ok2, checks2 = verdict(c["id"], out_items)
        check(f"invented figure in action_items caught on {c['id']}",
              "check_grounded" in checks2, f"checks={checks2}")


# ---------------------------------------------------------------- 4. ledger-017 vacuous-green guard

def test_11_committed_inputs_resolve():
    resolved = 0
    for c in CASES:
        try:
            P._exp(c["input"])
            resolved += 1
        except Exception as exc:  # noqa: BLE001
            check(f"committed case {c['id']} resolves", False, repr(exc))
    check(f"all {len(CASES)} committed cases resolve their expectations",
          resolved == len(CASES), f"{resolved}/{len(CASES)}")


def test_12_uncommitted_input_fails_loudly_not_vacuously():
    """THE ATTACK, built by hand: take a real committed case and append a
    constraint to its input, exactly how a plausible new case gets authored by
    mistake (E26's first design, per recap's own docstring)."""
    base = CASES[0]["input"]
    mutated = base + "\n\nExtra constraint: keep the summary under 200 characters."
    raised = False
    try:
        P._exp(mutated)
    except KeyError:
        raised = True
    except Exception as exc:  # noqa: BLE001
        check("mutated input raises KeyError specifically", False,
              f"raised {type(exc).__name__}")
    check("appending a constraint to a committed input raises rather than "
          "returning {}", raised)

    good_enough = {"summary": "x", "action_items": [], "nothing_important": False}
    ok, failures, failed = R.run_properties(PROPS, mutated, good_enough)
    check("run_properties REJECTS an uncommitted input (was: silent full pass)",
          ok is False, f"ok={ok} failed={[f['check'] for f in failed]}")
    check("the rejection names the cause rather than failing opaquely",
          any("does not match any committed case" in f for f in failures),
          f"failures={failures}")

    truncated = base[: len(base) // 2]
    ok_t, _f_t, _fc_t = R.run_properties(PROPS, truncated, good_enough)
    check("run_properties REJECTS a truncated committed input", ok_t is False,
          f"ok={ok_t}")

    ok_e, _f_e, _fc_e = R.run_properties(PROPS, "", good_enough)
    check("run_properties REJECTS an empty input", ok_e is False, f"ok={ok_e}")

    prefix = base[:-1]
    ok_p, _f_p, _fc_p = R.run_properties(PROPS, prefix, good_enough)
    check("a one-character-short prefix of a committed input is REJECTED",
          ok_p is False, f"ok={ok_p}")


def main() -> int:
    print(f"transcript-en checks — {len(CASES)} cases "
          f"({sum(1 for c in CASES if c['split']=='train')} train, "
          f"{sum(1 for c in CASES if c['split']=='heldout')} heldout), "
          f"{len(LONG)} in the long band (>= {LONG_MIN} chars)")
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)), key=lambda f: f.__name__):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all green'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
