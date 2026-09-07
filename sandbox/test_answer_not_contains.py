#!/usr/bin/env python3
"""Effect tests for `answer_not_contains` — the absence needle. No model, no server.

    python3 sandbox/test_answer_not_contains.py

WHY IT EXISTS (2026-09-04). Probing the six drafted multi-turn train cases on the crm
champion (gemma4-e2b-ctx16k, 3 same-day runs, docs/probes/train-cases-probe-2026-09-04/),
`decoy-owner-after-deals-devos` PASSED every run with this answer:

    "The contact for Devos Garage is Jan De Vos. His details are: Phone: +32 3 771 26 58,
     Email: tom.verhaeghe@example.com."

Right name (answer_contains 'De Vos' ✓), right tool (crm_lookup ✓), every number
grounded (the phone is Devos's own fixture value ✓) — and OUR REP's email, lifted from
the deals_list envelope one turn earlier, attributed to the client. The decoy fires at
the DETAIL level and no existing check can see it: `answer_contains` is presence-only,
`grounded_answer` reads digits, `tools_not_called` reads tools. The exam's failure
shape 1 (decoy-in-history) was passing "by accident" in exactly the sense the draft's
protocol warned about.

WHAT THIS FILE PINS:
  ISOLATION (CLAUDE.md gotcha 3). The champion's REAL recorded answer + trace from the
      probe file, scored against the case's expected block WITH the new key: failures
      has EXACTLY ONE entry and it is the new check. Without the key: passes (the
      pre-lane verdict, unchanged). Seen RED on master: the key is silently ignored.
  DIRECTIONAL (gotcha 4). Absence never shares presence's normalizer: a forbidden
      '6,500' does NOT fire on an answer saying '6500', and vice versa — the needle is
      exactly the text it forbids. Case-insensitive, substring.
  REAL ENTRY POINT (gotcha 5). Through run_exam with a scripted adapter replaying the
      recorded trajectory: failed_checks == [{"bucket": "quality",
      "check": "answer_not_contains"}] — one entry — and taxonomy files it, not
      UNCLASSIFIED.
  NO KEY, NO EFFECT. Every committed case without the key scores byte-identically:
      the check is a no-op on an absent/empty list.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402
import taxonomy  # noqa: E402
from runner import (ROOT, _load_module, _trajectory_check_id, load_exam,  # noqa: E402
                    run_exam, score_trajectory)

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


PROBE = ROOT / "docs" / "probes" / "train-cases-probe-2026-09-04" / "probe1.json"
CASE_ID = "decoy-owner-after-deals-devos"
LEAK = "tom.verhaeghe@example.com"


def _recorded():
    """The champion's real turn-1 answer + per-turn trace, straight off the probe file."""
    rec = next(c for c in json.loads(PROBE.read_text())["cases"] if c["id"] == CASE_ID)
    turn1 = rec["detail"]["turns"][1]
    # The probe record keeps tool_calls, not tool_results; re-execute the SAME calls
    # against the committed mock (deterministic) so the grounding corpus is what the
    # champion actually saw — the phone number in the answer is Devos's fixture value.
    tools = _tools()
    results = [getattr(tools, tc["tool"])(**tc["args"]) for tc in turn1["tool_calls"]]
    trace = {"tools_called": turn1["tools_called"], "tool_calls": turn1["tool_calls"],
             "tool_results": results, "steps": turn1["steps"]}
    return rec["got"], trace


def _committed_expected():
    exam = load_exam("crm-followup")
    case = next(c for c in exam["cases"] if c["id"] == CASE_ID)
    return case, case["turns_expected"][1]["expected"]


def _tools():
    return _load_module(ROOT / "evals" / "crm-followup" / "tools_mock.py",
                        "tools_mock_anc_test")


def test_the_recorded_leak_is_real_and_was_passing():
    got, _trace = _recorded()
    check("probe: the champion's recorded answer carries our rep's email",
          LEAK in got.get("answer", ""), str(got))
    check("probe: and the right client name", "De Vos" in got.get("answer", ""), str(got))
    rec = next(c for c in json.loads(PROBE.read_text())["cases"] if c["id"] == CASE_ID)
    check("probe: the case PASSED on the pre-lane grader (the blind spot)",
          rec["passed"] is True, str(rec.get("failed_checks")))


def test_isolation_exactly_one_failure_and_it_is_the_new_check():
    got, trace = _recorded()
    case, expected = _committed_expected()
    check("committed case forbids the rep's surname",
          any("verhaeghe" in str(n).lower() for n in expected.get("answer_not_contains", [])),
          str(expected))
    ok, failures = score_trajectory(got, trace, expected, "\n".join(case["turns"][:2]))
    check("isolation: FAILS", not ok)
    check("isolation: EXACTLY ONE failure", len(failures) == 1, "; ".join(failures))
    check("isolation: and it is answer_not_contains",
          failures and _trajectory_check_id(failures[0]) == "answer_not_contains",
          "; ".join(failures))
    # the same answer, same trace, key removed -> the pre-lane verdict
    without = {k: v for k, v in expected.items() if k != "answer_not_contains"}
    ok2, failures2 = score_trajectory(got, trace, without, "\n".join(case["turns"][:2]))
    check("control: without the key the case PASSES (unchanged pre-lane verdict)",
          ok2 and failures2 == [], "; ".join(failures2))


def test_directional_no_shared_normalizer():
    trace = {"tools_called": [], "tool_calls": [], "tool_results": [], "steps": 1}
    # input_text carries 6500 so grounded_answer stays quiet and only the absence
    # needle is under test.
    ok, f = score_trajectory({"answer": "The deal is 6500 EUR."}, trace,
                             {"answer_not_contains": ["6,500"]}, "deal 6500")
    check("directional: forbidden '6,500' does NOT fire on '6500' (no digit normalization)",
          ok and f == [], "; ".join(f))
    ok, f = score_trajectory({"answer": "The deal is 6,500 EUR."}, trace,
                             {"answer_not_contains": ["6500"]}, "deal 6500")
    check("directional: forbidden '6500' does NOT fire on '6,500' either", ok and f == [],
          "; ".join(f))
    ok, f = score_trajectory({"answer": "Email: Tom.Verhaeghe@Example.com"}, trace,
                             {"answer_not_contains": ["verhaeghe"]}, "")
    check("case-insensitive substring fires", not ok and len(f) == 1, "; ".join(f))
    ok, f = score_trajectory({"answer": "Jan De Vos"}, trace,
                             {"answer_not_contains": []}, "")
    check("empty list is a no-op", ok and f == [], "; ".join(f))
    ok, f = score_trajectory({"answer": "Jan De Vos"}, trace, {}, "")
    check("absent key is a no-op", ok and f == [], "; ".join(f))
    ok, f = score_trajectory({}, trace, {"answer_not_contains": ["x"]}, "")
    check("no answer: absence check stays quiet (answer_present carries that case)",
          "answer contains forbidden" not in " ".join(f), "; ".join(f))


class _Replay:
    """Replays the recorded trajectory's TOOL CALLS and turn 1's answer (`got`, the
    only answer text a results record keeps — per-turn entries carry tool_calls,
    steps and verdicts, not answer text). Turn 0's answer is therefore a synthetic
    stand-in chosen to satisfy turn 0's own committed expected block, exactly as the
    recorded turn 0 did (probe1.json: turn 0 passed, failures []); it is not derived
    from, and cannot affect, turn 1's scripted answer."""

    def __init__(self, got):
        self.out = ['{"tool": "deals_list", "args": {"company": "Devos Garage"}}',
                    '{"answer": "The Devos Garage deal is in the discovery stage."}',
                    '{"tool": "crm_lookup", "args": {"company": "Devos Garage"}}',
                    json.dumps(got, ensure_ascii=False)]
        self.n = 0

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        out = self.out[self.n]
        self.n += 1
        return out, {"prompt_tokens": 10, "completion_tokens": 30, "total_tokens": 40,
                     "content_chars": len(out), "reasoning_chars": 0, "finish_reason": "stop"}


def test_real_entry_point_one_failed_check_and_taxonomy_files_it():
    got, _ = _recorded()
    case, _ = _committed_expected()
    exam = {**load_exam("crm-followup"), "cases": [case]}
    saved = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: _Replay(got)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(runner.load_agent("crm-followup"), exam, "ollama", "s")
    finally:
        runner.adapter_for = saved
    rec = result["cases"][0]
    check("run_exam: the replayed case FAILS", rec["passed"] is False)
    check("run_exam: failed_checks is EXACTLY the one new entry, on turn 1",
          rec.get("failed_checks") == [{"bucket": "quality", "check": "answer_not_contains",
                                        "turn": 1}], str(rec.get("failed_checks")))
    check("taxonomy: the new id has a category (never UNCLASSIFIED)",
          taxonomy.CATEGORY_BY_CHECK.get("answer_not_contains") == "fabrication",
          str(taxonomy.CATEGORY_BY_CHECK.get("answer_not_contains")))


def test_no_committed_case_outside_the_new_ones_carries_the_key():
    """Scope pin: the key lands on the two decoy-owner train cases only, so every
    pre-existing verdict is untouched by construction."""
    exam = load_exam("crm-followup")
    carriers = sorted(c["id"] for c in exam["cases"]
                      if any("answer_not_contains" in te.get("expected", {})
                             for te in c.get("turns_expected", []))
                      or "answer_not_contains" in c.get("expected", {}))
    check("only the two decoy-owner train cases carry answer_not_contains",
          carriers == ["decoy-owner-after-deals-devos", "decoy-owner-after-deals-janssens"],
          str(carriers))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"\n{name}")
            try:
                fn()
            except Exception as exc:
                check(f"{name} raised {type(exc).__name__}", False, str(exc)[:160])
    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}):")
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("all answer_not_contains tests passed")
