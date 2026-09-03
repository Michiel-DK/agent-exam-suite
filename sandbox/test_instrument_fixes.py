#!/usr/bin/env python3
"""Deterministic tests for the PR1a measuring-instrument fixes — no model, no server.

    python3 sandbox/test_instrument_fixes.py

Every fix is tested in BOTH directions (brief non-negotiable 4): the true positive
it must still catch AND the false positive it must stop producing.

  C1  abstention vocabulary: the three loophole strings that passed a substring
      test for "no" now FAIL; the champion's three real refusals still PASS.
      Tested against the SHIPPED evals/crm-followup/cases.json, not a copy.
  C2  answer_contains_any is ANY-of; answer_contains stays ALL-of.
  C4  numeric needles match on a number-token boundary ('6500' vs '16500');
      text needles keep substring behaviour.
  C3  properties.py strips thousands separators ONLY — the four-row truth table
      from the brief, plus the _norm_digits trap ('65.00' must stay invented).
  J3  judge model == model under test REFUSES (SystemExit), via load_judge.
      judges.py is generic infra reused by any future rubric'd exam — F3''
      (2026-07-24) removed reply-draft's own rubric.md/judge config, so this
      collision test now exercises load_judge against a throwaway synthetic
      exam/rubric instead of a real agent (no shipped exam carries a judge
      right now; the machinery still needs its own coverage).

Plain asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judges import load_judge  # noqa: E402
from runner import ROOT, _load_module, score_trajectory  # noqa: E402

props_mod = _load_module(ROOT / "evals" / "reply-draft" / "properties.py",
                         "props_reply_draft_test")

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def _trace(tool_calls=None, tool_results=None, steps=None):
    calls = tool_calls or []
    return {"tools_called": [c["tool"] for c in calls],
            "tool_calls": calls,
            "tool_results": tool_results if tool_results is not None else [],
            "steps": steps if steps is not None else len(calls) + 1}


def _abstention_cases() -> dict:
    """The three shipped abstention cases, by id — tests run against the real
    vocabulary in cases.json so a future vocabulary edit is re-verified here."""
    exam = json.loads((ROOT / "evals" / "crm-followup" / "cases.json").read_text())
    wanted = {"unknown-company", "unknown-deal-value", "no-deals-known-company"}
    return {c["id"]: c for c in exam["cases"] if c["id"] in wanted}


# ---------------------------------------------------------------- C1 abstention

LOOPHOLES = ["I know the deal is worth 6500 EUR.",
             "Nothing to report.",
             "Our Norway office handled it."]

# The champion's real answers (regression check only — the vocabulary is derived
# from what abstention MEANS; if it broke these, the vocabulary would be wrong).
REAL_REFUSALS = {
    "unknown-company": ("No CRM record found for Maes Bikes.",
                        [{"tool": "crm_lookup", "args": {"company": "Maes Bikes"}}],
                        [{"error": "no CRM record for 'Maes Bikes'"}]),
    "unknown-deal-value": ("There are no open deals for Aerts Consulting.",
                           [{"tool": "deals_list",
                             "args": {"company": "Aerts Consulting"}}],
                           [[]]),
    "no-deals-known-company": ("There are no open deals for Vitrine Restaurant.",
                               [{"tool": "deals_list",
                                 "args": {"company": "Vitrine Restaurant"}}],
                               [[]]),
}


def test_c1_loophole_strings_fail_every_abstention_case():
    """'I know...', 'Nothing to report.', 'Norway' all passed answer_contains ['no']
    by substring. Against the shipped vocabulary each must now fail — the specific
    answer_contains_any failure must be present, whatever else also fires."""
    for case_id, case in _abstention_cases().items():
        assert "answer_contains_any" in case["expected"], \
            f"{case_id} lost its answer_contains_any key"
        for loophole in LOOPHOLES:
            _ok, failures = score_trajectory(
                {"answer": loophole}, _trace(), case["expected"], case["input"])
            check(f"C1 {case_id}: {loophole!r} fails the vocabulary",
                  any("answer_contains_any" in f for f in failures),
                  "; ".join(failures) or "no failures at all")


def test_c1_real_refusals_still_pass():
    """The champion's genuine refusals pass the whole trajectory check, vocabulary
    included, with a realistic trace for each shipped case."""
    cases = _abstention_cases()
    for case_id, (answer, calls, results) in REAL_REFUSALS.items():
        ok, failures = score_trajectory(
            {"answer": answer}, _trace(tool_calls=calls, tool_results=results),
            cases[case_id]["expected"], cases[case_id]["input"])
        check(f"C1 {case_id}: real refusal {answer!r} passes", ok,
              "; ".join(failures))


# ---------------------------------------------------------------- C2 any-of

def test_c2_any_of_passes_on_one_needle():
    ok, failures = score_trajectory(
        {"answer": "b"}, _trace(), {"answer_contains_any": ["a", "b"]}, "in")
    check("C2 answer_contains_any ['a','b'] passes on answer 'b'", ok,
          "; ".join(failures))


def test_c2_all_of_still_fails_on_one_needle():
    ok, failures = score_trajectory(
        {"answer": "b"}, _trace(), {"answer_contains": ["a", "b"]}, "in")
    check("C2 answer_contains ['a','b'] still fails on answer 'b'",
          not ok and any("missing 'a'" in f for f in failures),
          "; ".join(failures))


def test_c2_any_of_fails_when_no_needle_matches():
    ok, failures = score_trajectory(
        {"answer": "c"}, _trace(), {"answer_contains_any": ["a", "b"]}, "in")
    check("C2 answer_contains_any fails when nothing matches",
          not ok and any("answer_contains_any" in f for f in failures),
          "; ".join(failures))


def test_c2_both_keys_coexist():
    """Both keys on one case, checked independently: all-of satisfied, any-of not."""
    ok, failures = score_trajectory(
        {"answer": "alpha beta"}, _trace(),
        {"answer_contains": ["alpha", "beta"], "answer_contains_any": ["gamma"]}, "in")
    check("C2 coexisting keys: any-of failure still fires",
          not ok and any("answer_contains_any" in f for f in failures)
          and not any("missing 'alpha'" in f for f in failures),
          "; ".join(failures))


# ---------------------------------------------------------------- C4 number boundary

def _needle_6500(answer: str, grounded: int):
    """Score needle '6500' against an answer whose number IS grounded in a tool
    result, so the needle check — not the grounding check — decides."""
    trace = _trace(tool_calls=[{"tool": "deals_list", "args": {"company": "J"}}],
                   tool_results=[[{"amount_eur": grounded}]])
    return score_trajectory({"answer": answer}, trace,
                            {"answer_contains": ["6500"]},
                            "What is the deal worth?")


def test_c4_substring_supersets_fail():
    for answer, grounded in [("The Janssens deal is worth 16500 EUR.", 16500),
                             ("The deal is worth 65000 EUR.", 65000)]:
        ok, failures = _needle_6500(answer, grounded)
        check(f"C4 expected 6500 fails against {answer.split()[-2]}",
              not ok and any("missing '6500'" in f for f in failures),
              "; ".join(failures))


def test_c4_formatting_variants_pass():
    for answer in ["The deal is worth 6500 EUR.",
                   "The deal is worth 6,500 EUR.",
                   "The deal is worth €6500."]:
        ok, failures = _needle_6500(answer, 6500)
        check(f"C4 expected 6500 passes against {answer!r}", ok, "; ".join(failures))


def test_c4_text_needles_keep_substring():
    """Text needles must NOT become word-boundary-exact — a name inside a sentence
    is a legitimate partial match (brief C4)."""
    ok, failures = score_trajectory(
        {"answer": "Your contact is Sofie Janssens; the deal is in discovery."},
        _trace(tool_calls=[{"tool": "crm_lookup", "args": {"company": "J"}}],
               tool_results=[{"contact": "Sofie Janssens", "stage": "discovery"}]),
        {"answer_contains": ["Sofie", "discovery"]}, "Who is my contact?")
    check("C4 text needle inside a sentence still passes", ok, "; ".join(failures))


def test_c4_date_needle_still_passes():
    ok, failures = score_trajectory(
        {"answer": "Last contact was 2026-07-02, about the chatbot."},
        _trace(tool_calls=[{"tool": "crm_lookup", "args": {"company": "J"}}],
               tool_results=[{"last_interaction": "2026-07-02", "notes": "chatbot"}]),
        {"answer_contains": ["2026-07-02", "chatbot"]}, "When did we last talk?")
    check("C4 date needle '2026-07-02' still passes", ok, "; ".join(failures))


# ---------------------------------------------------------------- C3 thousands only

def _invented(input_text: str, reply: str):
    return props_mod.check_no_invented_numbers(input_text, {"reply": reply})


def test_c3_truth_table():
    """The brief's four rows — input contains 6500."""
    inp = "The Janssens deal is worth 6500 EUR."
    for reply, want_ok, label in [
            ("The deal is worth 6,500 EUR.", True, "6,500 passes (not invented)"),
            ("De deal is 6.500 EUR waard.", True, "NL 6.500 passes (not invented)"),
            ("The deal is worth 65.00 EUR.", False, "65.00 FAILS as invented"),
            ("The deal is worth 9900 EUR.", False, "9900 FAILS as invented")]:
        ok, msg = _invented(inp, reply)
        check(f"C3 {label}", ok == want_ok, msg)


def test_c3_decimal_not_stripped():
    """The _norm_digits trap: '1.5' must not normalize to '15'."""
    ok, msg = _invented("We shipped 15 units.", "About 1.5 days of work.")
    check("C3 invented '1.5' not conflated with input's '15'", not ok, msg)


def test_c3_input_side_normalized_too():
    """Reverse formatting: input writes '6,500', reply writes bare '6500'."""
    ok, msg = _invented("Budget is 6,500 EUR.", "Confirming the 6500 EUR budget.")
    check("C3 input '6,500' grounds reply '6500'", ok, msg)


def test_c3_trailing_punctuation_is_not_data():
    ok, msg = _invented("The deal is worth 6500 EUR",
                        "I confirm the deal is worth 6500.")
    check("C3 sentence-final '6500.' is the input's 6500", ok, msg)


def test_c3_ambiguous_token_fails_closed():
    """'1,23' fits neither grouping nor a clean decimal-after-thousands shape —
    it stays unnormalized and is flagged against an input containing '123'."""
    ok, msg = _invented("Ref 123.", "See ref 1,23.")
    check("C3 ambiguous '1,23' stays unnormalized (fail closed)", not ok, msg)


def test_c3_grouped_with_decimal():
    ok, msg = _invented("Total invoice 1,234,567.89 EUR.",
                        "Confirming the 1.234.567,89 EUR total is unchanged.")
    # NL '1.234.567,89' vs EN '1,234,567.89': both strip to '1234567,89'/'1234567.89'
    # — decimal separators differ, so this stays flagged (fail closed, harder).
    check("C3 cross-locale decimal stays flagged (fail closed)", not ok, msg)
    ok2, msg2 = _invented("Total invoice 1,234,567.89 EUR.",
                          "Confirming 1,234,567.89 EUR.")
    check("C3 same-locale grouped decimal passes", ok2, msg2)


def test_c3_small_number_exemption_survives():
    ok, msg = _invented("Can we meet about the project?",
                        "Yes — I need 2 days to prepare.")
    check("C3 bare small number (<10) still allowed", ok, msg)
    ok2, msg2 = _invented("Can we meet?", "It will cost 4500 EUR.")
    check("C3 large ungrounded number still invented", not ok2, msg2)


# ------------------------------------------- F1 comma-decimal (PR1a follow-up)

def _needle_6500_both_grounded(answer: str):
    """Needle '6500' with BOTH 6500 and 16500 present in tool results, so for the
    fail rows only the needle check decides (F1's isolation setup, exam-audit §A0)."""
    trace = _trace(tool_calls=[{"tool": "deals_list", "args": {"company": "J"}}],
                   tool_results=[[{"amount_eur": 6500}, {"amount_eur": 16500}]])
    return score_trajectory({"answer": answer}, trace,
                            {"answer_contains": ["6500"]},
                            "What is the deal worth?")


def test_f1_needle_truth_table():
    """The full F1 table: comma/point decimals for sixty-five FAIL, every honest
    formatting of six-and-a-half thousand PASSES, wrong grounded rows FAIL."""
    for answer, want_ok in [
            ("The deal is worth 65,00 EUR.", False),   # EU decimal = sixty-five
            ("The deal is worth 65.00 EUR.", False),   # EN decimal = sixty-five
            ("The deal is worth 6500 EUR.", True),
            ("The deal is worth 6,500 EUR.", True),
            ("De deal is 6.500 EUR waard.", True),     # NL thousands grouping
            ("The deal is worth €6500.", True),
            ("The deal is worth 16500 EUR.", False),   # wrong grounded row (C4)
            ("The deal is worth 65000 EUR.", False)]:
        ok, failures = _needle_6500_both_grounded(answer)
        if want_ok:
            check(f"F1 needle 6500 passes {answer!r}", ok, "; ".join(failures))
        else:
            check(f"F1 needle 6500 FAILS {answer!r}",
                  not ok and any("missing '6500'" in f for f in failures),
                  "; ".join(failures) or "no failures at all")


def test_f1_grounding_comma_decimal_fails():
    """Second site, same root cause: '65,00' used to skip the date path (split had
    no ',') and then false-pass number grounding via _norm_digits('65,00')=='6500'.
    No needle here — only the grounding check decides."""
    trace = _trace(tool_calls=[{"tool": "deals_list", "args": {"company": "J"}}],
                   tool_results=[[{"amount_eur": 6500}]])
    ok, failures = score_trajectory(
        {"answer": "The deal is worth 65,00 EUR."}, trace, {},
        "What is the deal worth?")
    check("F1 grounding: '65,00' vs grounded 6500 fails",
          not ok and any("ungrounded" in f and "65,00" in f for f in failures),
          "; ".join(failures) or "no failures at all")
    ok2, failures2 = score_trajectory(
        {"answer": "The deal is worth 65.00 EUR."}, trace, {},
        "What is the deal worth?")
    check("F1 grounding: '65.00' vs grounded 6500 fails",
          not ok2 and any("ungrounded" in f for f in failures2),
          "; ".join(failures2) or "no failures at all")


def test_f1_grounding_thousands_grouping_grounds():
    """The unambiguous grouped shapes are the SAME fact as a grounded 6500 and must
    pass grounding — '6.500' previously fell into the date path and failed."""
    trace = _trace(tool_calls=[{"tool": "deals_list", "args": {"company": "J"}}],
                   tool_results=[[{"amount_eur": 6500}]])
    for answer in ["The deal is worth 6,500 EUR.",
                   "De deal is 6.500 EUR waard."]:
        ok, failures = score_trajectory({"answer": answer}, trace, {},
                                        "What is the deal worth?")
        check(f"F1 grounding: {answer!r} grounds against 6500", ok,
              "; ".join(failures))


def test_f1_grounding_comma_decimal_echoed_from_input_still_grounds():
    """Echoing the input's own comma-decimal back is not fabrication."""
    ok, failures = score_trajectory(
        {"answer": "Confirmed: the fee is 65,00 EUR."}, _trace(), {},
        "The fee is 65,00 EUR, correct?")
    check("F1 grounding: input's own '65,00' still grounds", ok,
          "; ".join(failures))


def test_f1_date_path_intact():
    """The ',' split must not damage date grounding: a grounded date still passes,
    a wrong day still fails (the Stage-3 guarantee)."""
    trace = _trace(tool_calls=[{"tool": "crm_lookup", "args": {"company": "J"}}],
                   tool_results=[{"last_interaction": "2026-07-02"}])
    ok, failures = score_trajectory(
        {"answer": "Last contact was 2026-07-02."}, trace, {},
        "When did we last talk?")
    check("F1 date grounding: real 2026-07-02 still passes", ok, "; ".join(failures))
    ok2, failures2 = score_trajectory(
        {"answer": "Last contact was 2026-07-05."}, trace, {},
        "When did we last talk?")
    check("F1 date grounding: wrong day 2026-07-05 still fails",
          not ok2 and any("ungrounded" in f for f in failures2),
          "; ".join(failures2) or "no failures at all")


def test_f1_one_shared_implementation():
    """runner.py and properties.py must use the SAME strip_thousands object — the
    F1 root cause was two sites drifting apart."""
    from numnorm import strip_thousands
    from runner import strip_thousands as runner_strip
    check("F1 runner imports the shared strip_thousands",
          runner_strip is strip_thousands)
    check("F1 properties.py imports the shared strip_thousands",
          props_mod._strip_thousands is strip_thousands)


# ---------------------------------------------------------------- J3 self-judging

def _synthetic_judged_exam(tmp_root: Path, agent_name: str,
                           judge_model: str = "llama3.1:latest") -> dict:
    """A throwaway evals/<agent_name>/rubric.md + judge config under a scratch
    root — decoupled from any real, shipped agent (no exam ships a judge
    anymore post-F3''), so this still proves load_judge's own collision logic
    without depending on reply-draft carrying a rubric it no longer has."""
    rubric_dir = tmp_root / "evals" / agent_name
    rubric_dir.mkdir(parents=True)
    (rubric_dir / "rubric.md").write_text("- The reply is polite\n")
    return {"judge": {"provider": "ollama", "model": judge_model}}


def test_j3_load_judge_refuses_collision():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        exam = _synthetic_judged_exam(tmp_root, "fake-agent")
        judge_model = exam["judge"]["model"]
        try:
            load_judge("fake-agent", exam, judge_model, tmp_root)
            check("J3 load_judge refuses judge == model under test", False,
                  "did not exit")
        except SystemExit as exc:
            msg = str(exc)
            check("J3 load_judge refuses judge == model under test",
                  "fake-agent" in msg and judge_model in msg and "cases.json" in msg,
                  f"exit message lacks exam/collision/resolution: {msg}")


def test_j3_load_judge_allows_distinct_model():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        exam = _synthetic_judged_exam(tmp_root, "fake-agent")
        judge = load_judge("fake-agent", exam, "gemma4:e2b-it-qat", tmp_root)
        check("J3 load_judge returns a judge for a distinct model under test",
              callable(judge))


def test_j3_reply_draft_has_no_judge():
    """F3'' regression gate: reply-draft's rubric.md/judge config are GONE —
    load_judge must return None for it (no rubric.md => no judge, by
    construction), and cases.json must carry no "judge" key."""
    exam = json.loads((ROOT / "evals" / "reply-draft" / "cases.json").read_text())
    check("J3 reply-draft cases.json has no 'judge' key", "judge" not in exam,
          str(exam.get("judge")))
    check("J3 reply-draft rubric.md does not exist",
          not (ROOT / "evals" / "reply-draft" / "rubric.md").exists())
    judge = load_judge("reply-draft", exam, "gemma4:e2b-it-qat", ROOT)
    check("J3 load_judge('reply-draft', ...) returns None", judge is None,
          repr(judge))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)} test groups; {len(FAILED)} failed assertion(s)"
          + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
