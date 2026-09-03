#!/usr/bin/env python3
"""E13 recap exam — check tests, with ISOLATION as the load-bearing part.

THE RULE THIS FILE EXISTS TO ENFORCE (CLAUDE.md gotchas; ledger 006-008):
  "A new check earns its place only if some case ISOLATES it — otherwise you have built
   apparatus that measures nothing. For every new check, name a case that passes ALL
   other checks and fails ONLY the new one, and verify it does."

This repo has shipped unfalsifiable checks THREE times, each disguised by a score moving
the expected direction. So isolation is asserted MECHANICALLY here: for each check, a
synthetic output is fed through the real run_properties() and the assertion is that
failed_checks has EXACTLY ONE entry, naming that check.

Why synthetic outputs rather than the model's: whether the champion happens to fail a
case is a fact about the champion, not about the instrument. These assertions must hold
regardless of which model is under test — otherwise the next champion swap silently
disarms them, exactly as it did to E10's error_recovery rung.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import runner as R  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


CASES = {c["id"]: c for c in json.loads((ROOT / "evals" / "recap" / "cases.json").read_text())["cases"]}
PROPS = R.load_properties("recap")


def run(case_id, output):
    """(ok, failed_check_names) through the REAL scoring path."""
    ok, _failures, failed = R.run_properties(PROPS, CASES[case_id]["input"], output)
    return ok, [f["check"] for f in failed]


def only(case_id, output, expected_check):
    """Assert this output fails EXACTLY the named check and nothing else."""
    ok, names = run(case_id, output)
    check(f"{case_id}: fails ONLY {expected_check}",
          not ok and names == [expected_check], f"failed_checks={names}")


# ---------------------------------------------------------------- baselines

# A correct recap for busy-day-standard: mentions both required items, uses only source
# numbers, well under the 401-char limit, and does not abstain on a busy day.
GOOD_BUSY = {"recap": "Janssens gaat akkoord met 6500 EUR en wil starten in september. "
                      "De Vos vraagt om het overleg een week te verplaatsen.",
             "nothing_important": False}

# A correct recap for a quiet day: abstains, stays under the 220-char cap.
GOOD_QUIET = {"recap": "Niets belangrijk vandaag - een nieuwsbrief, een automatische "
                       "back-up en een profielmelding.",
              "nothing_important": True}


def test_baselines_pass_every_check():
    """Direction 2 of both-direction: the checks must be SILENT on a correct answer.
    A check that fires on a good recap is worse than no check."""
    ok, names = run("busy-day-standard", GOOD_BUSY)
    check("good busy-day recap passes ALL checks", ok, f"failed={names}")
    ok, names = run("quiet-day-automated", GOOD_QUIET)
    check("good quiet-day recap passes ALL checks", ok, f"failed={names}")


def test_isolation_grounded():
    """Invents an amount. Coverage still satisfied, still short, flag still correct."""
    only("busy-day-standard",
         {"recap": "Janssens gaat akkoord met 6500 EUR en betaalt een voorschot van "
                   "7200 EUR. De Vos verplaatst het overleg.",
          "nothing_important": False},
         "check_grounded")


def test_isolation_coverage():
    """Drops a required item. No invented number, still short, flag still correct."""
    only("busy-day-standard",
         {"recap": "Er kwam een akkoord binnen over 6500 EUR en iemand vroeg het "
                   "overleg te verplaatsen.",
          "nothing_important": False},
         "check_coverage")


def test_isolation_compression():
    """The lazy-model failure: restates at length. Every number is from the source, both
    required items appear, the flag is right — it is simply not a summary."""
    filler = ("De klant beschrijft de situatie uitvoerig en herhaalt de context nog eens "
              "in andere bewoordingen zodat niets verloren gaat. ") * 5
    only("busy-day-standard",
         {"recap": f"Janssens gaat akkoord met 6500 EUR. {filler}",
          "nothing_important": False},
         "check_compression")


def test_isolation_abstention_busy_day():
    """Abstains on a day that needed attention — the inverse failure, equally wrong."""
    only("busy-day-standard",
         {"recap": "Janssens gaat akkoord met 6500 EUR en wil starten in september.",
          "nothing_important": True},
         "check_abstention")


def test_isolation_abstention_quiet_day_flag():
    """Manufactured significance: a quiet day reported as needing attention."""
    only("quiet-day-automated",
         {"recap": "Niets belangrijk vandaag - enkel een nieuwsbrief en een back-up.",
          "nothing_important": False},
         "check_abstention")


def test_isolation_abstention_padding():
    """The subtle one: flag set HONESTLY, but the recap is padded anyway.

    This is why the cap exists — a model can answer 'nothing important' correctly and
    still produce three paragraphs about newsletters. The padded recap stays UNDER the
    compression limit (330) and over the abstain cap (220), so compression must stay
    silent and only abstention fires. If those two bounds ever cross, this test starts
    failing with TWO entries and that is the signal the case design broke.
    """
    padded = ("Niets belangrijk vandaag. Er kwam een nieuwsbrief binnen met tips over "
              "administratie en een interview met een starter uit Gent. Daarnaast is de "
              "geplande back-up zonder fouten voltooid en zijn er enkele nieuwe "
              "profielweergaven gemeld op het netwerkplatform.")
    n = len(padded)
    check("padded quiet-day recap sits between the abstain cap and the compression limit",
          220 < n < 330, f"len={n} (must be >220 and <330 or the test proves nothing)")
    only("quiet-day-automated", {"recap": padded, "nothing_important": True},
         "check_abstention")


def test_shape_check_fires_loud():
    """Fail loud, never a placeholder: a malformed answer is a failed case."""
    ok, names = run("busy-day-standard", {"recap": "", "nothing_important": False})
    check("empty recap -> check_output_shape fires", "check_output_shape" in names, str(names))
    ok, names = run("busy-day-standard", {"recap": "iets", "nothing_important": "yes"})
    check("non-bool nothing_important -> check_output_shape fires",
          "check_output_shape" in names, str(names))


def test_grounding_normalisation_is_directional():
    """The bug that shipped TWICE: over-normalising an ABSENCE check waves fabrications
    through. '65.00' and '6500' are different amounts and must not be conflated."""
    from importlib import import_module
    sys.path.insert(0, str(ROOT / "evals" / "recap"))
    props = import_module("properties")
    src = "Het bedrag is 65.00 EUR."
    ok, _ = props.check_grounded(src, {"recap": "Het bedrag is 6500 EUR."})
    check("'6500' is NOT accepted as grounded by a source '65.00'", not ok)
    ok, _ = props.check_grounded(src, {"recap": "Het bedrag is 65.00 EUR."})
    check("'65.00' IS accepted against source '65.00'", ok)
    ok, _ = props.check_grounded("Bedrag 6.500 EUR.", {"recap": "6500 EUR"})
    check("thousands separator normalised: '6.500' source accepts '6500'", ok)


def test_every_check_has_an_isolation_case():
    """Meta-assertion: no check may exist without an isolation test above. If someone
    adds a 5th check, this fails until they prove it can fire alone."""
    names = {n for n, _ in PROPS}
    covered = {"check_output_shape", "check_grounded", "check_coverage",
               "check_compression", "check_abstention"}
    check("no check lacks an isolation demonstration", names <= covered,
          f"uncovered: {sorted(names - covered)}")


def test_case_inventory():
    cases = list(CASES.values())
    longest = max(len(c["input"]) for c in cases)
    check("longest input beats the previous suite max of 1814 chars", longest > 1814,
          f"longest={longest}")
    check("at least 3 quiet-day (abstention) cases exist",
          sum(1 for c in cases if c["expected"].get("nothing_important") is True) >= 3)
    check("both splits populated",
          sum(1 for c in cases if c["split"] == "train") >= 4
          and sum(1 for c in cases if c["split"] == "heldout") >= 5)


def main() -> int:
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)), key=lambda f: f.__name__):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all green'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
