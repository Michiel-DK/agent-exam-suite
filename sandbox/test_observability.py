#!/usr/bin/env python3
"""Deterministic tests for the PR1b observability changes — no model, no server.

    python3 sandbox/test_observability.py

PR1b is REPORT-ONLY: it must make failures visible without changing any verdict.
Every group therefore tests two things at once — the new visibility is present,
AND the pass/fail semantics are exactly what they were.

  C5(a)  every reply-draft check carries a format/quality bucket marker; an
         unmarked or mis-marked check REFUSES to load; a format-only failure
         (check_signoff) still FAILS the case, but the failure now records its
         bucket, so the quality checks' verdicts are no longer hidden behind it.
  D6     snapshot_payload gains a per-case block (id, split, passed, failing
         checks with bucket): additive over the original keys, deterministic
         ordering, deduplicated, and NEVER containing model output text.
         Trajectory/judge failures map to stable check ids; an unknown failure
         string raises rather than being silently binned.
  D8     _lang detects French and returns an explicit 'unknown'; a Dutch reply
         to a French email FAILS check_language_match (it passed before); the
         8 shipped reply-draft inputs keep their exact pre-change language
         (7x 'en', prijs-exact-nl 'nl') — tested against the SHIPPED cases.json.

Plain asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runner import (  # noqa: E402
    ROOT, _judge_check_id, _load_module, _snapshot_case, _trajectory_check_id,
    load_checks, load_properties, run_properties, score_trajectory,
    snapshot_payload,
)

props_mod = _load_module(ROOT / "evals" / "reply-draft" / "properties.py",
                         "props_reply_draft_obs_test")

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


# The exact split stated in the PR body — a drift here is a reviewed decision,
# not an accident.
EXPECTED_BUCKETS = {
    "check_has_reply": "quality",
    "check_language_match": "quality",
    "check_no_invented_numbers": "quality",
    "check_no_invented_dates": "quality",
    "check_signoff": "format",
    "check_word_limit": "format",
}

EN_INPUT = ("From: sofie@example.com\nSubject: chatbot quote\n\n"
            "Hi Michiel, could you send a quote for the chatbot project? "
            "We planned a budget of 6500 EUR. Thanks, Sofie")
GOOD_REPLY = ("Hi Sofie, thanks for reaching out about the chatbot project. "
              "I will prepare a quote within the 6500 EUR budget and follow up "
              "shortly. Best regards, Michiel")


# ---------------------------------------------------------------- C5(a) buckets

def test_c5_bucket_mapping_is_declared_on_every_check():
    props = load_properties("reply-draft")
    got = {fn_name: fn.bucket for fn_name, fn in props}
    check("C5 all five reply-draft checks carry the agreed bucket",
          got == EXPECTED_BUCKETS, str(got))


def test_c5_unmarked_check_refuses_to_load():
    """A check without a bucket must REFUSE at load time — a silently defaulted
    bucket would be a placeholder (CLAUDE.md: fail loud)."""
    for body, label in [
            ("def check_x(input_text, output):\n    return (True, '')\n",
             "no bucket at all"),
            ("def check_x(input_text, output):\n    return (True, '')\n"
             "check_x.bucket = 'style'\n",
             "invalid bucket value")]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "properties.py"
            path.write_text(body)
            try:
                load_checks(path, f"props_scratch_{label.replace(' ', '_')}")
                check(f"C5 load_checks refuses {label}", False, "did not exit")
            except SystemExit as exc:
                check(f"C5 load_checks refuses {label}",
                      "check_x" in str(exc) and "bucket" in str(exc), str(exc))


def test_c5_format_failure_still_fails_the_case_and_names_its_bucket():
    """The operator ruling: option (a), NOT the scoring split. A reply failing
    ONLY check_signoff must still fail overall — and the failure record must show
    it was the format bucket, with every quality check passing (the visibility
    this lane exists to add)."""
    props = load_properties("reply-draft")
    no_signoff = GOOD_REPLY.replace("Michiel", "the team")
    ok, failures, failed_checks = run_properties(
        props, EN_INPUT, {"reply": no_signoff})
    check("C5 signoff-only miss still FAILS the case", not ok,
          "; ".join(failures))
    check("C5 the only failing check is check_signoff, bucket format",
          failed_checks == [{"bucket": "format", "check": "check_signoff"}],
          str(failed_checks))
    check("C5 failure strings unchanged in shape (fn_name: msg)",
          failures == ["check_signoff: reply does not sign off with Michiel"],
          str(failures))


def test_c5_quality_failure_tagged_quality():
    props = load_properties("reply-draft")
    invented = ("Hi Sofie, thanks — the chatbot would cost 9900 EUR. "
                "Best regards, Michiel")
    ok, _failures, failed_checks = run_properties(
        props, EN_INPUT, {"reply": invented})
    check("C5 invented number fails as bucket quality",
          not ok and {"bucket": "quality",
                      "check": "check_no_invented_numbers"} in failed_checks,
          str(failed_checks))


def test_c5_clean_reply_passes_with_empty_failure_lists():
    props = load_properties("reply-draft")
    ok, failures, failed_checks = run_properties(
        props, EN_INPUT, {"reply": GOOD_REPLY})
    check("C5 clean reply passes with no failures recorded",
          ok and failures == [] and failed_checks == [],
          f"{failures} / {failed_checks}")


# ---------------------------------------------------------------- D6 check ids

def test_d6_trajectory_failures_map_to_stable_check_ids():
    """Every failure score_trajectory can emit maps to a stable id — produced via
    the real scoring function, not by mimicking its strings."""
    scenarios = [  # (parsed, trace, expected, input, wanted check ids)
        ({"answer": ""}, _trace(), {}, "in", {"answer_present"}),
        ({"answer": "hello"}, _trace(), {"answer_contains": ["zzz"]}, "in",
         {"answer_contains"}),
        ({"answer": "hello"}, _trace(), {"answer_contains_any": ["x", "y"]},
         "in", {"answer_contains_any"}),
        ({"answer": "hello"}, _trace(), {"tools_called": ["crm_lookup"]}, "in",
         {"tools_called"}),
        ({"answer": "hello"},
         _trace(tool_calls=[{"tool": "crm_lookup", "args": {}}],
                tool_results=[{}]),
         {"tools_not_called": ["crm_lookup"]}, "in", {"tools_not_called"}),
        ({"answer": "hello"}, _trace(steps=5), {"max_steps": 4}, "in",
         {"max_steps"}),
        ({"answer": "worth 9000"}, _trace(), {}, "in", {"grounded_answer"}),
        ({"answer": "on 2026-07-02"}, _trace(), {}, "in", {"grounded_answer"}),
        ({"answer": "hello"},
         _trace(tool_calls=[{"tool": "crm_lookup", "args": {"c": "X"}},
                            {"tool": "crm_lookup", "args": {"c": "X"}}],
                tool_results=[{}, {}], steps=3),
         {"max_steps": 4}, "in", {"redundancy"}),
    ]
    for parsed, trace, expected, input_text, wanted in scenarios:
        ok, failures = score_trajectory(parsed, trace, expected, input_text)
        ids = {_trajectory_check_id(f) for f in failures}
        check(f"D6 trajectory ids {sorted(wanted)} from {failures[:1]}",
              not ok and ids == wanted, f"got {sorted(ids)}: {failures}")


def test_d6_unmapped_trajectory_failure_raises():
    try:
        _trajectory_check_id("some future failure string")
        check("D6 unmapped failure string raises", False, "did not raise")
    except ValueError as exc:
        check("D6 unmapped failure string raises",
              "some future failure string" in str(exc), str(exc))


def test_d6_judge_check_id_drops_the_free_text_reason():
    """The criterion head is a stable id; the reason (which quotes model output)
    must never reach a committed snapshot."""
    fid = _judge_check_id("judge:Avoids exact timing or figures: The reply "
                          "promises 'exact pricing' by Friday.")
    check("D6 judge id keeps 'judge:<criterion>'",
          fid == "judge:Avoids exact timing or figures", fid)
    check("D6 judge id drops the output-quoting reason",
          "Friday" not in fid and "pricing" not in fid, fid)
    check("D6 unparseable-judge failure keeps its head",
          _judge_check_id("judge unparseable: Expecting value: line 1")
          == "judge unparseable")


# ---------------------------------------------------------------- D6 snapshot

def _fake_result():
    return {
        "agent": "reply-draft", "provider": "ollama", "model": "m",
        "mode": "properties",
        "train": {"passed": 1, "total": 2, "score": 0.5},
        "heldout": {"passed": 1, "total": 1, "score": 1.0},
        "cases": [
            {"id": "a", "split": "train", "passed": True, "expected": {},
             "got": {"reply": "SECRET-MODEL-OUTPUT-A"}},
            {"id": "b", "split": "train", "passed": False, "expected": {},
             "got": {"reply": "SECRET-MODEL-OUTPUT-B"},
             "failures": ["check_signoff: reply does not sign off with Michiel",
                          "judge:Tone: SECRET-MODEL-OUTPUT-B is too blunt"],
             "failed_checks": [
                 {"bucket": "format", "check": "check_signoff"},
                 {"bucket": "format", "check": "check_signoff"},  # dupe
                 {"bucket": "quality", "check": "judge:Tone"}]},
            {"id": "c", "split": "heldout", "passed": True, "expected": {},
             "got": {}},
        ],
    }


def test_d6_snapshot_answers_which_check_failed_on_which_case():
    agent = {"name": "reply-draft", "temperature": 0.0, "max_tokens": 2048}
    exam = json.loads((ROOT / "evals" / "reply-draft" / "cases.json").read_text())
    snap = snapshot_payload(agent, exam, "ollama", "m", _fake_result())
    check("D6 original snapshot keys all survive, 'cases' is the only addition",
          set(snap) == {"provider", "model", "train_score", "heldout_score",
                        "temperature", "max_tokens", "judge", "date",
                        "harness_sha", "cases"}, str(sorted(snap)))
    check("D6 scores unchanged by the schema addition",
          snap["train_score"] == 0.5 and snap["heldout_score"] == 1.0)
    check("D6 per-case: id, split, passed for every case",
          [(c["id"], c["split"], c["passed"]) for c in snap["cases"]]
          == [("a", "train", True), ("b", "train", False),
              ("c", "heldout", True)], str(snap["cases"]))
    check("D6 failing case lists its checks with bucket, deduplicated",
          snap["cases"][1]["failures"]
          == [{"bucket": "format", "check": "check_signoff"},
              {"bucket": "quality", "check": "judge:Tone"}],
          str(snap["cases"][1]))
    check("D6 passing cases carry no failures key",
          "failures" not in snap["cases"][0]
          and "failures" not in snap["cases"][2])
    check("D6 no model output text anywhere in the snapshot",
          "SECRET-MODEL-OUTPUT" not in json.dumps(snap), json.dumps(snap)[:200])


def test_d6_snapshot_ordering_is_deterministic():
    """Snapshots are committed artifacts: same result -> byte-identical 'cases'
    block (key order fixed, case order = exam order), so a rerun diffs clean."""
    agent = {"name": "reply-draft", "temperature": 0.0, "max_tokens": 2048}
    exam = json.loads((ROOT / "evals" / "reply-draft" / "cases.json").read_text())
    a = snapshot_payload(agent, exam, "ollama", "m", _fake_result())
    b = snapshot_payload(agent, exam, "ollama", "m", _fake_result())
    check("D6 identical results serialize to identical cases blocks",
          json.dumps(a["cases"]) == json.dumps(b["cases"]))
    check("D6 per-case key order is fixed",
          [list(c) for c in a["cases"]]
          == [["id", "split", "passed"], ["id", "split", "passed", "failures"],
              ["id", "split", "passed"]], str([list(c) for c in a["cases"]]))


def test_d6_errored_case_is_visible_not_empty():
    """A case that raised before scoring must still say WHY it failed."""
    entry = _snapshot_case({"id": "x", "split": "train", "passed": False,
                            "failed_checks": [{"bucket": "quality",
                                               "check": "error"}]})
    check("D6 errored case records check 'error'",
          entry["failures"] == [{"bucket": "quality", "check": "error"}],
          str(entry))
    bare = _snapshot_case({"id": "y", "split": "train", "passed": False})
    check("D6 failing case with no recorded checks still emits an empty list "
          "(visible absence, not a missing key)",
          bare["failures"] == [], str(bare))


# ---------------------------------------------------------------- D8 _lang

FR_EMAIL = ("De: claire@duval-traiteur.be\nObjet: devis chatbot\n\n"
            "Bonjour Michiel, je voudrais un devis pour un chatbot pour notre "
            "site. Quel serait le prix? Merci d'avance, cordialement, Claire")
NL_REPLY = ("Dag Claire, bedankt voor je bericht. Ik stuur je graag volgende "
            "week een offerte. Groeten, Michiel")
FR_REPLY = ("Bonjour Claire, merci pour votre message. Je vous envoie un devis "
            "la semaine prochaine avec le prix. Cordialement, Michiel")


def test_d8_french_is_detected_as_french():
    check("D8 French email detects 'fr' (was 'nl' before the fix)",
          props_mod._lang(FR_EMAIL) == "fr", props_mod._lang(FR_EMAIL))


def test_d8_dutch_reply_to_french_email_fails():
    """THE D8 bug: this exact combination PASSED before the fix ('je'/'de' put
    French into the Dutch bin, so nl == nl)."""
    ok, msg = props_mod.check_language_match(FR_EMAIL, {"reply": NL_REPLY})
    check("D8 Dutch reply to French email FAILS", not ok, msg)
    check("D8 failure names both detected languages",
          "'fr'" in msg and "'nl'" in msg, msg)


def test_d8_matching_replies_still_pass():
    ok_fr, msg_fr = props_mod.check_language_match(FR_EMAIL, {"reply": FR_REPLY})
    check("D8 French reply to French email passes", ok_fr, msg_fr)
    ok_nl, msg_nl = props_mod.check_language_match(
        "Dag Michiel, wat kost een chatbot? Graag een exact bedrag. Groeten",
        {"reply": NL_REPLY})
    check("D8 Dutch reply to Dutch email passes", ok_nl, msg_nl)


def test_d8_unknown_is_explicit_and_always_fails():
    check("D8 empty text is 'unknown'", props_mod._lang("") == "unknown")
    check("D8 digits-only text is 'unknown'",
          props_mod._lang("6500 EUR 2026-07-22") == "unknown")
    ok, msg = props_mod.check_language_match(FR_EMAIL, {"reply": ""})
    check("D8 unknown reply FAILS rather than defaulting",
          not ok and "unknown" in msg, msg)
    ok2, msg2 = props_mod.check_language_match("12345", {"reply": "67890"})
    check("D8 unknown == unknown still FAILS (two unknowns are not a match)",
          not ok2, msg2)


def test_d8_shipped_inputs_keep_their_language():
    """REGRESSION GATE from the brief: the 8 shipped reply-draft inputs must
    detect exactly as before the fix — 7x 'en', prijs-exact-nl 'nl'. A flip
    means the heuristic is wrong (tested against the SHIPPED cases.json)."""
    exam = json.loads((ROOT / "evals" / "reply-draft" / "cases.json").read_text())
    got = {c["id"]: props_mod._lang(c["input"]) for c in exam["cases"]}
    # SUBSET, not equality. This started as `got == want` over reply-draft's
    # original 8 cases and broke the moment PR2 (#19) added 9 more — an exact pin
    # over data later lanes legitimately change, the same defect class adversarial
    # review caught in evals/test_pr2_hardcases.py. The REGRESSION GUARD the
    # docstring describes is "these 8 must not flip", which a subset check states
    # exactly; new cases are covered by the no-'unknown' assertion below instead.
    want = {"quote-request": "en", "intro-call-en": "en", "scope-question": "en",
            "followup-en": "en", "price-push": "en",
            "conference-heldout-en": "en", "budget-figure-demand": "en",
            "prijs-exact-nl": "nl"}
    unknown = sorted(cid for cid, lang in got.items() if lang == "unknown")
    check("D8 no shipped input detects as 'unknown'", not unknown,
          f"unknown: {unknown}")
    check("D8 the original 8 inputs unchanged (7 en, 1 nl)",
          all(got.get(k) == v for k, v in want.items()),
          str(got))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)} test groups; {len(FAILED)} failed assertion(s)"
          + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
