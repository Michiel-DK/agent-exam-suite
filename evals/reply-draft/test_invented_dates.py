#!/usr/bin/env python3
"""Deterministic tests for check_no_invented_dates — no model, no server (F3'').

    python3 evals/reply-draft/test_invented_dates.py

reply-draft's judge used to grade "no NEW exact timing the incoming email didn't
mention" as a rubric bullet. A small judge could not enforce it (llama3:8b
mis-passed 3/3 invented-date replies; qwen3:8b mis-passed 1 and crashed on 2 —
exam-audit 2026-07-24), so F3' moved the criterion to a deterministic property
check — and F3'' (2026-07-24) then removed the judge ENTIRELY (rubric.md and
the "judge" key are gone from cases.json; reply-draft is now judge-free like
every other exam). This file carries the timing-adversarial coverage that used
to live in the judge-dependent test_rubric_j1.py (deleted with the judge).

F3-FIX (2026-07-24, this file): the harness review round-tripped F3'' with two
REAL defects, both fixed here. HONESTY NOTE, per the review that caught them —
44 green tests previously gave FALSE CONFIDENCE because every echo case used
an IDENTICAL date, hiding a day-granularity hole. Every echo case below now
either differs the day (must-fail) or is asserted as an exact, non-trivial
tuple echo (must-pass), so this file cannot go green the same blind way again.

  DEFECT A (over-matching, false-fail): slash/hyphen numeric-format date
      detection ('1/9', '3-5') is STRUCTURALLY IDENTICAL to fractions, ratios,
      and ranges business replies use constantly ('1/3 upfront', '3-5
      options'). No denylist of range-unit words can close that gap, so the
      slash/hyphen detector was REMOVED entirely (properties.py). Numeric-date
      coverage is now ISO ('2026-08-15') only. ACCEPTED GAP: a both-small-digit
      numeric date like '1/9' no longer false-fails, but is no longer CAUGHT
      either — documented in properties.py, not silently dropped.
  DEFECT B (under-matching, false-pass): the word-form date guard used to
      check only whether the MONTH WORD echoed the input, so a bare month
      mention licensed ANY invented day ("are we still on for September?" ->
      "confirmed for September 3rd" used to PASS). Fixed by validating the
      (DAY, MONTH) TUPLE, not the month word alone — word-order agnostic,
      ordinal==cardinal (EN 'st/nd/rd/th', NL 'de/e'), bilingual EN+NL.

What it proves:
  FAIL direction — a reply introducing a NEW full weekday name, full month name +
      day, or ISO date absent from the input FAILS: full names (EN/NL), the three
      brief-adversarial replies, ordinals ('September 3rd', 'the 15th of August'),
      ISO dates ('2026-08-15'), AND — the F3-fix defect B cases — an invented DAY
      inside an echoed or bare month ('are we still on for September?' ->
      'September 3rd'; '15th of August' -> '3rd of August'; 'the November slot' ->
      '3 November').
  DECLARED GAPS (defect C — pinned so they are KNOWN, not silent) — abbreviations
      ('Fri', 'Sept 3'), the ambiguous month words 'may'/'march', both-small-digit
      numeric dates ('1/9'), and NL weekday COMPOUNDS ('vrijdagmiddag') PASS
      uncaught. Each collides with ordinary business language (or, for the compound,
      breaks the word boundary); false-failing a good model is worse for a capability
      exam than missing a rare/ambiguous invention. Completeness is deferred to PR2's
      real date-bearing cases, not chased against imagined inputs here.
  PASS direction — a reply echoing a weekday/date/tuple THE INPUT CONTAINS
      passes (EN, NL, abbreviated, ISO, exact-echo with a non-trivial date);
      vague-timing whitelist phrases pass by construction; clean deferrals
      pass; a bare month word ("we may follow up") does not false-fail;
      common non-date numeric idioms ('24/7') do not false-fail — AND, the
      F3-fix defect A cases — fractions, ratios, and ranges in ordinary
      business language ('1/3 upfront', '3-5 options', '2-3 rounds of
      review', 'about 3/4 complete') never false-fail, in EN and NL.
  Division of labour — the digit half stays in check_no_invented_numbers
      (magnitude-shaped); this check owns the alphabetic month/weekday
      vocabulary PLUS the narrow ISO numeric-date exception.

Plain asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox"))
from runner import ROOT, _load_module  # noqa: E402

props_mod = _load_module(ROOT / "evals" / "reply-draft" / "properties.py",
                         "props_reply_draft_dates_test")

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def _dates(input_text: str, reply: str):
    return props_mod.check_no_invented_dates(input_text, {"reply": reply})


# A pushy client email that mentions NO weekday and NO calendar date, so any of
# those in a reply is by construction NEW (mirrors the old test_rubric_j1 EMAIL).
CLEAN_EN = ("Hi Michiel, before we can proceed I need your exact price for the "
            "chatbot project, and I need to know which day you can deliver. Best, Tom")
CLEAN_NL = ("Dag Michiel, wat kost zo'n chatbot nu precies? Graag een exact "
            "bedrag. Groeten, Pieter")


def test_fail_the_three_brief_adversarial_replies():
    """The three replies the brief names as MUST-FAIL — each invents a weekday
    and/or a month-adjacent-day date the clean input never mentioned."""
    ok1, msg1 = _dates(CLEAN_EN, "Hi Tom, we can go live on Friday 15 August. Best, Michiel")
    check("adversarial 'Friday 15 August' FAILS", not ok1, msg1)
    ok2, msg2 = _dates(CLEAN_EN, "Hi Tom, let's meet Tuesday 3 November at 14:30. Best, Michiel")
    check("adversarial 'Tuesday 3 November at 14:30' FAILS", not ok2, msg2)
    ok3, msg3 = _dates(
        CLEAN_EN,
        "Hi Tom, total budget is 87500 EUR and go-live is 1 September. Best, Michiel")
    check("adversarial '1 September' FAILS (month word the digit check waves through)",
          not ok3, msg3)


def test_clean_and_whitelisted_replies_pass():
    """Clean deferrals and the vague-timing whitelist never fail."""
    ok, msg = _dates(
        CLEAN_EN,
        "Hi Tom, I'll send pricing as soon as possible so you can decide this "
        "week. Best, Michiel")
    check("clean deferral 'as soon as possible / this week' PASSES", ok, msg)
    whitelist = ["today", "shortly", "asap", "I will follow up", "this week",
                 "binnenkort", "zo snel mogelijk", "I can give you a call"]
    for phrase in whitelist:
        ok, msg = _dates(CLEAN_EN, f"Hi Tom, I will get back to you {phrase}. Best, Michiel")
        check(f"whitelist phrase {phrase!r} PASSES", ok, msg)
    ok, msg = _dates(CLEAN_EN, "Hi Tom, we may follow up on the march to launch. Best, Michiel")
    check("bare month word ('may'/'march', no adjacent day) does NOT false-fail",
          ok, msg)


def test_echoed_timing_passes_but_invented_dutch_fails():
    """Echoing a weekday/date THE INPUT CONTAINS passes; inventing one fails —
    both EN and NL (NL is required: reply-draft has Dutch cases)."""
    inp_en = ("Dear Michiel, could you confirm the November slot? We need an "
              "answer by Friday. Regards, the program team")
    ok, msg = _dates(inp_en, "Hi, yes — I'll confirm the November slot by Friday. Best, Michiel")
    check("EN reply echoing input's 'November'/'Friday' PASSES", ok, msg)

    inp_nl = ("Dag Michiel, graag een exact bedrag, dan kan ik het budget vrijdag "
              "laten goedkeuren. Groeten, Pieter")
    ok, msg = _dates(inp_nl, "Dag Pieter, ik stuur je de prijs zodat je het vrijdag kunt regelen. Groeten, Michiel")
    check("NL reply echoing input's 'vrijdag' PASSES", ok, msg)

    ok, msg = _dates(inp_nl, "Dag Pieter, ik kom maandag bij je langs. Groeten, Michiel")
    check("NL reply inventing 'maandag' (not in input) FAILS", not ok, msg)
    ok, msg = _dates(CLEAN_NL, "Dag Pieter, we gaan live op 3 maart. Groeten, Michiel")
    check("NL reply inventing '3 maart' (not in input) FAILS", not ok, msg)


def test_division_of_labour_month_word_only():
    """This check owns the ALPHABETIC month word; the digit half is
    check_no_invented_numbers' job. '1 September' fails HERE on 'September'
    (the '1' is a whitelisted small number the digit check ignores)."""
    ok, msg = _dates(CLEAN_EN, "Hi Tom, go-live is 1 September. Best, Michiel")
    check("'1 September' fails on the month word alone", not ok and "september" in msg.lower(), msg)
    ok, _ = _dates(CLEAN_EN, "Hi Tom, we can start August 15. Best, Michiel")
    check("'August 15' (month-before-day order) FAILS", not ok)


# ---------------------------------------------------------- hole class (b): ordinals

def test_ordinals_fail_both_orders():
    ok, msg = _dates(CLEAN_EN, "Hi Tom, we can go live September 3rd. Best, Michiel")
    check("'September 3rd' (month then ordinal day) FAILS", not ok, msg)
    ok, msg = _dates(CLEAN_EN, "Hi Tom, we can go live the 15th of August. Best, Michiel")
    check("'the 15th of August' (ordinal 'of' month) FAILS", not ok, msg)
    ok, msg = _dates(CLEAN_EN, "Hi Tom, we can go live 3rd September. Best, Michiel")
    check("'3rd September' (ordinal day then month, no 'of') FAILS", not ok, msg)


def test_ordinal_echo_passes():
    inp = "Hi Michiel, does the 15th of August work for you? Best, Tom"
    ok, msg = _dates(inp, "Hi Tom, yes, the 15th of August works. Best, Michiel")
    check("echoed ordinal 'the 15th of August' PASSES", ok, msg)


# --------------------------------------------- ACCEPTED GAPS: abbreviations (defect C)
# Weekday AND month abbreviations were dropped from the matcher entirely (F3-fix
# defect C, 2026-07-24): they are ambiguous with ordinary words ('Sat'/'Wed' at a
# sentence start, 'Mar'/'May'/'March' as verbs) and were never in the criterion the
# deleted judge enforced (full-form dates). Catching them cost three round-trips of
# false-FAILS. They are now DOCUMENTED accepted gaps — the exam trades a rare missed
# abbreviated invention for never false-failing ordinary business language, which is
# the right call for a CAPABILITY exam (a false-fail penalizes a GOOD model).

def test_abbreviations_are_an_accepted_gap_and_do_not_false_fail():
    """Abbreviated forms now PASS (uncaught) — the accepted gap. The point of the
    change is that the reply on the RIGHT of each pair is ordinary language the
    check must never reject; whether it is 'really' a date is exactly the ambiguity
    we stopped trying to resolve."""
    for reply, label in [
        ("Hi Tom, let's talk Fri. Best, Michiel", "abbreviated weekday 'Fri'"),
        ("Hi Tom, let's talk Mon. Best, Michiel", "abbreviated weekday 'Mon'"),
        ("Hi Tom, we can go live Sept 3. Best, Michiel", "month abbreviation 'Sept 3'"),
        ("Hi Tom, we can go live Aug 15. Best, Michiel", "month abbreviation 'Aug 15'"),
    ]:
        ok, msg = _dates(CLEAN_EN, reply)
        check(f"{label} is an accepted gap (PASSES, not false-fail)", ok, msg)


def test_ambiguous_month_words_do_not_false_fail():
    """'may' (modal) and 'march' (verb) are common words even adjacent to a number
    ('3 may be enough', 'we march 5 people through onboarding'). They are excluded
    from the month set (_AMBIGUOUS_MONTHS) so ordinary language never false-fails —
    the fourth false-fail class found in review (defect C)."""
    for reply, label in [
        ("3 may be enough to cover it. Best, Michiel", "'3 may be' (modal verb)"),
        ("We may 3 options here. Best, Michiel", "'may 3' (modal verb)"),
        ("We march 5 people through onboarding. Best, Michiel", "'march 5' (verb)"),
        ("About 5 march-outs planned. Best, Michiel", "'5 march' (verb)"),
    ]:
        ok, msg = _dates(CLEAN_EN, reply)
        check(f"{label} does NOT false-fail", ok, msg)


def test_nl_weekday_compound_is_a_declared_gap():
    """NL weekday+daypart compounds ('vrijdagmiddag') PASS uncaught — the \\b
    boundary does not fire inside the compound. Pinned as a KNOWN gap (not a silent
    one): the bare 'vrijdag' IS caught; a PR2 case with an invented NL daypart is the
    right trigger to close this if real cases show it matters."""
    inp = "Beste, kunt u laten weten wanneer we kunnen bellen? Dank je wel."
    ok, msg = _dates(inp, "Beste, laten we vrijdagmiddag bellen. Met vriendelijke groet, Michiel")
    check("NL compound 'vrijdagmiddag' is a declared gap (PASSES uncaught)", ok, msg)
    # ...but the BARE NL weekday is still caught — the gap is only the compound.
    ok, msg = _dates(inp, "Beste, laten we vrijdag bellen. Met vriendelijke groet, Michiel")
    check("bare NL 'vrijdag' invention is still CAUGHT (FAILS)", not ok, msg)


def test_capitalized_ordinary_words_do_not_false_fail():
    """A weekday-word capitalized at a sentence start ('Sat through the demo') must
    not false-fail — the exact bug the case-sensitive abbreviation guard missed and
    that dropping the matcher fixes."""
    for reply, label in [
        ("Sat through the demo yesterday, all looked solid. Best, Michiel", "'Sat' (sentence-start verb)"),
        ("Sat with finance on this, we are aligned. Best, Michiel", "'Sat with finance'"),
        ("We sat down together and discussed pricing. Best, Michiel", "lowercase 'sat'"),
        ("The sun was out today when we spoke. Best, Michiel", "lowercase 'sun'"),
    ]:
        ok, msg = _dates(CLEAN_EN, reply)
        check(f"{label} does NOT false-fail", ok, msg)


# ----------------------------------------------------------- hole class (a): numeric
# F3-fix defect A removed slash/hyphen date detection entirely (properties.py):
# it was structurally identical to fractions/ratios/ranges and no denylist
# closed that gap. ISO is the only numeric format still recognized.

def test_numeric_dates_fail():
    ok, msg = _dates(CLEAN_EN, "Hi Tom, go-live is 2026-08-15. Best, Michiel")
    check("'2026-08-15' (ISO date) FAILS", not ok, msg)


def test_numeric_date_echo_passes():
    inp_iso = "Hi Michiel, target date is 2026-08-15, confirm? Best, Tom"
    ok, msg = _dates(inp_iso, "Hi Tom, confirmed for 2026-08-15. Best, Michiel")
    check("echoed ISO '2026-08-15' PASSES", ok, msg)
    ok, msg = _dates(inp_iso, "Hi Tom, confirmed for 2026-08-20 instead. Best, Michiel")
    check("a DIFFERENT ISO date (not echoed) FAILS", not ok, msg)


def test_numeric_idioms_do_not_false_fail():
    """'24/7' used to be date-shaped enough to need an explicit idiom
    exception; now that slash detection is gone entirely, it never becomes a
    candidate in the first place — still worth pinning as a non-regression."""
    ok, msg = _dates(CLEAN_EN, "Hi Tom, we are available 24/7. Best, Michiel")
    check("'24/7' idiom does NOT false-fail", ok, msg)


# --------------------------------------------- F3-fix defect A: fractions/ranges
# THE false-fail bug: '1/3 upfront', '3-5 options' etc. were flagged as
# invented slash/hyphen dates before the fix removed that detector. These are
# the exact repro cases from the operator's hand-verified report.

def test_fractions_ratios_ranges_do_not_false_fail():
    """Ordinary business language using slash/hyphen numeric shorthand for
    fractions, ratios, and ranges must never be mistaken for a date — this IS
    defect A, reproduced and fixed."""
    cases = [
        "we offer 1/3 upfront, 1/3 mid-project, 1/3 at go-live",
        "I can give you 3-5 options",
        "2-3 rounds of review",
        "about 3/4 complete",
        "a 1/3 deposit",
        "we're proposing an 80-20 split",
        "that will take 3-11 business days",
    ]
    for phrase in cases:
        ok, msg = _dates(CLEAN_EN, f"Hi Tom, {phrase}. Best, Michiel")
        check(f"business phrase {phrase!r} does NOT false-fail", ok, msg)


# ------------------------------------------------ F3-fix defect B: invented day
# THE false-pass bug: a bare or echoed month word used to license ANY day
# number in the reply. Fixed by validating the (day, month) TUPLE. These are
# the exact repro cases from the operator's hand-verified report.

def test_invented_day_inside_bare_or_echoed_month_fails():
    ok, msg = _dates("Hi Michiel, are we still on for September? Best, Tom",
                      "Hi Tom, confirmed for September 3rd. Best, Michiel")
    check("bare month input + invented day 'September 3rd' FAILS", not ok, msg)

    ok, msg = _dates("Hi Michiel, does the 15th of August work? Best, Tom",
                      "Hi Tom, the 3rd of August works better. Best, Michiel")
    check("different day, SAME month ('15th' -> '3rd of August') FAILS", not ok, msg)

    ok, msg = _dates(
        "Dear Michiel, could you confirm the November slot? Regards, Tom",
        "Hi Tom, confirmed for 3 November. Best, Michiel")
    check("bare month ('the November slot') + invented '3 November' FAILS", not ok, msg)


def test_exact_date_echo_still_passes():
    """The fix must not reintroduce false-fails: a reply that echoes the exact
    (day, month) the input mentions still passes, word-order agnostic and
    ordinal/cardinal agnostic. Uses a NON-TRIVIAL, non-identical-string echo
    (input says 'the 3rd of September', reply says 'September 3rd') so this
    cannot pass by string-matching alone — it must resolve the tuple."""
    ok, msg = _dates("Hi Michiel, does the 3rd of September work? Best, Tom",
                      "Hi Tom, yes, September 3rd works well. Best, Michiel")
    check("tuple echo across word order + ordinal form PASSES", ok, msg)

    ok, msg = _dates("Hi Michiel, can we confirm September 3rd? Best, Tom",
                      "Hi Tom, confirmed for September 3rd. Best, Michiel")
    check("identical-string exact-echo 'September 3rd' -> 'September 3rd' PASSES", ok, msg)


def test_nl_ordinal_day_and_tuple_echo():
    """NL day-ordinal forms ('3de'/'3e') must resolve to the same tuple as the
    cardinal, and an NL echo of a real input date must pass while an invented
    NL day inside the same month fails."""
    inp = "Dag Michiel, werkt 3 september voor jou? Groeten, Piet"
    ok, msg = _dates(inp, "Dag Piet, ja, 3de september werkt goed. Groeten, Michiel")
    check("NL ordinal '3de september' echoing input's '3 september' PASSES", ok, msg)
    ok, msg = _dates(inp, "Dag Piet, 5 september werkt beter. Groeten, Michiel")
    check("NL different day, same month ('5 september') FAILS", not ok, msg)


def main() -> int:
    test_fail_the_three_brief_adversarial_replies()
    test_clean_and_whitelisted_replies_pass()
    test_echoed_timing_passes_but_invented_dutch_fails()
    test_division_of_labour_month_word_only()
    test_ordinals_fail_both_orders()
    test_ordinal_echo_passes()
    test_abbreviations_are_an_accepted_gap_and_do_not_false_fail()
    test_ambiguous_month_words_do_not_false_fail()
    test_nl_weekday_compound_is_a_declared_gap()
    test_capitalized_ordinary_words_do_not_false_fail()
    test_numeric_dates_fail()
    test_numeric_date_echo_passes()
    test_numeric_idioms_do_not_false_fail()
    test_fractions_ratios_ranges_do_not_false_fail()
    test_invented_day_inside_bare_or_echoed_month_fails()
    test_exact_date_echo_still_passes()
    test_nl_ordinal_day_and_tuple_echo()
    print(f"\n{len(FAILED)} failed assertion(s)" + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
