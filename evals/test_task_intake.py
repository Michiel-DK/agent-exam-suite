#!/usr/bin/env python3
"""Effect tests for the task-intake exam (A4 dispatcher, 2026-09-04). No model.

    python3 evals/test_task_intake.py

WHAT IS PINNED, each property seen RED by construction (gotcha 2):
  ROSTER.   The exam's expected agents are exactly the six committed agents + "none";
            the prompt names every one of them (a specialist the prompt never mentions
            cannot be chosen — presence is not effect).
  SPAN.     check_input_is_verbatim_span fails a paraphrase, an invented line, a
            digit-"fixed" line, and a cherry-picked fragment below the floor; passes the
            verbatim payload and the whole request. Directional: it uses no digit
            normalization.
  NONE.     'none' with material attached fails; a specialist with an empty hand-over
            fails; 'none' with "" passes.
  MIXED.    Through the REAL run_exam (scripted adapter): labels + properties BOTH grade
            one case. Right agent + verbatim span → PASS. Wrong agent → FAIL with ONLY
            the labels entry. Right agent + fabricated input → FAIL with EXACTLY ONE
            failed_check, check_input_is_verbatim_span (gotcha 3 isolation).
  SPLIT.    Ids unique; every heldout case's agent also has ≥ 1 train case (a shape no
            train case teaches cannot be iterated on); the 3 'none' baits stay split
            across both halves.
Plain asserts + exit code, zero dependencies.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import runner  # noqa: E402
from runner import _load_module, load_exam, load_properties, run_exam  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


props = _load_module(ROOT / "evals" / "task-intake" / "properties.py", "props_intake_test")
EXAM = load_exam("task-intake")
PROMPT = (ROOT / "agents" / "task-intake" / "prompt.md").read_text()
AGENTS = sorted(p.name for p in (ROOT / "agents").iterdir()
                if (p / "agent.yaml").exists() and p.name != "task-intake")


def test_roster_matches_committed_agents_and_the_prompt():
    expected = sorted({c["expected"]["agent"] for c in EXAM["cases"]} - {"none"})
    check("exam roster == the six committed agents", expected == AGENTS, f"{expected} vs {AGENTS}")
    check("properties ROSTER == the six committed agents", sorted(props.ROSTER) == AGENTS,
          str(sorted(props.ROSTER)))
    missing = [a for a in AGENTS + ["none"] if f'"{a}"' not in PROMPT]
    check("prompt.md names every specialist and 'none'", not missing, str(missing))


REQ = "Book this: 2026-08-14 ANTHROPIC API 42.10 EUR"


def test_span_property_red_and_green():
    fn = props.check_input_is_verbatim_span
    ok, _ = fn(REQ, {"agent": "expense-categorization", "input": "2026-08-14 ANTHROPIC API 42.10 EUR"})
    check("span: the verbatim payload passes", ok)
    ok, _ = fn(REQ, {"agent": "expense-categorization", "input": REQ})
    check("span: the whole request passes (instruction-stripping is a declared gap)", ok)
    ok, msg = fn(REQ, {"agent": "expense-categorization", "input": "Anthropic API charge of 42.10 euro"})
    check("span: a paraphrase FAILS", not ok and "not a verbatim span" in msg, msg)
    ok, msg = fn(REQ, {"agent": "expense-categorization", "input": "2026-08-14 ANTHROPIC API 42,10 EUR"})
    check("span: a digit-'fixed' line FAILS (no digit normalization, gotcha 4)", not ok, msg)
    ok, msg = fn(REQ, {"agent": "expense-categorization", "input": "42.10 EUR"})
    check("span: a fragment below the floor FAILS", not ok and "covers only" in msg, msg)
    ok, _ = fn(REQ, {"agent": "none", "input": ""})
    check("span: quiet for 'none' (the NONE property owns that)", ok)
    ok, _ = fn("  Book this:\n2026-08-14  ANTHROPIC API 42.10 EUR ", {"agent": "expense-categorization",
                                                                       "input": "2026-08-14 anthropic api 42.10 eur"})
    check("span: whitespace and case are collapsed, nothing else", ok)


def test_multi_payload_case_grades_by_its_committed_handover():
    """Refuters 2026-09-05 (two, independently): with only the 50% floor, the POLICY-
    CORRECT hand-over on `heavy-question-inside-email-crm` (the crm question, 26% of a
    request that also embeds an email) could not pass, and echoing the decoy could.
    Now the case commits `handover` and is graded by containment (recap _exp discipline):
    the ideal span PASSES, the decoy-only span FAILS, the whole request still passes
    (declared gap), and a case WITHOUT a golden keeps the floor."""
    fn = props.check_input_is_verbatim_span
    case = next(c for c in EXAM["cases"] if c["id"] == "heavy-question-inside-email-crm")
    golden, req = case["handover"], case["input"]
    check("golden: is a verbatim span of its request", golden in req)
    check("golden: the ideal hand-over PASSES (was RED under the floor alone: 26% < 50%)",
          fn(req, {"agent": "crm-followup", "input": golden})[0])
    decoy = req.split("\n\n", 1)[1]
    ok, msg = fn(req, {"agent": "crm-followup", "input": decoy})
    check("golden: the decoy email alone FAILS", not ok and "committed hand-over" in msg, msg)
    check("golden: the whole request passes (instruction-stripping stays a declared gap)",
          fn(req, {"agent": "crm-followup", "input": req})[0])
    carriers = sorted(c["id"] for c in EXAM["cases"] if c.get("handover"))
    check("golden: exactly the two multi-payload heavy cases carry a handover",
          carriers == ["heavy-question-inside-email-crm", "heavy-two-payloads-reply-wins"], str(carriers))
    check("golden: every committed handover is a verbatim span of its own input",
          all(c["handover"] in c["input"] for c in EXAM["cases"] if c.get("handover")))
    check("no golden: the floor still applies (live requests match no case)",
          not fn("Book this: 2026-08-14 ANTHROPIC API 42.10 EUR",
                 {"agent": "expense-categorization", "input": "42.10 EUR"})[0])


def test_none_property_red_and_green():
    fn = props.check_none_hands_over_nothing
    check("none: '' passes", fn("x", {"agent": "none", "input": ""})[0])
    check("none: absent input passes", fn("x", {"agent": "none"})[0])
    check("none: material attached FAILS", not fn("x", {"agent": "none", "input": "book a train"})[0])
    check("none: specialist with empty hand-over FAILS",
          not fn("x", {"agent": "recap", "input": "  "})[0])
    check("roster: an unknown agent FAILS the format check",
          not props.check_agent_in_roster("x", {"agent": "invoice-writer", "input": "y"})[0])


class _Scripted:
    def __init__(self, out):
        self.out = out

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        return self.out, {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10,
                          "content_chars": len(self.out), "reasoning_chars": 0, "finish_reason": "stop"}


def _run(case_id, output: dict):
    case = next(c for c in EXAM["cases"] if c["id"] == case_id)
    exam = {**EXAM, "cases": [case]}
    saved = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: _Scripted(json.dumps(output, ensure_ascii=False))
        with contextlib.redirect_stdout(io.StringIO()):
            res = run_exam(runner.load_agent("task-intake"), exam, "ollama", "s")
    finally:
        runner.adapter_for = saved
    return res["cases"][0]


def test_mixed_labels_plus_properties_through_run_exam():
    payload = "2026-08-14 ANTHROPIC API 42.10 EUR"
    rec = _run("expense-book-anthropic", {"agent": "expense-categorization", "input": payload})
    check("mixed: right agent + verbatim span PASSES", rec["passed"] is True, str(rec.get("failed_checks")))
    rec = _run("expense-book-anthropic", {"agent": "crm-followup", "input": payload})
    check("mixed: wrong agent FAILS with only the labels entry",
          rec["passed"] is False and rec.get("failed_checks") == [{"bucket": "quality", "check": "labels"}],
          str(rec.get("failed_checks")))
    rec = _run("expense-book-anthropic", {"agent": "expense-categorization", "input": "Anthropic 42.10"})
    check("mixed: right agent + fabricated input FAILS with EXACTLY ONE check, the span property (isolation)",
          rec["passed"] is False and rec.get("failed_checks") == [{"bucket": "quality",
                                                                    "check": "check_input_is_verbatim_span"}],
          str(rec.get("failed_checks")))
    rec = _run("none-book-train", {"agent": "none", "input": ""})
    check("mixed: a correct abstention PASSES", rec["passed"] is True, str(rec.get("failed_checks")))
    rec = _run("none-book-train", {"agent": "none", "input": "Book me a train to Paris next Tuesday morning."})
    check("mixed: abstention with material FAILS on the format check only",
          rec["passed"] is False and rec.get("failed_checks") == [{"bucket": "format",
                                                                    "check": "check_none_hands_over_nothing"}],
          str(rec.get("failed_checks")))
    check("properties really load for a labels-mode exam (presence is not effect)",
          len(load_properties("task-intake")) == 3, str(len(load_properties("task-intake"))))


def test_split_shape():
    ids = [c["id"] for c in EXAM["cases"]]
    check("ids unique", len(ids) == len(set(ids)))
    by = {}
    for c in EXAM["cases"]:
        by.setdefault(c["expected"]["agent"], set()).add(c["split"])
    check("every agent (and none) has both a train and a heldout case",
          all(v == {"train", "heldout"} for v in by.values()), str(by))
    baits = [c for c in EXAM["cases"] if c["id"].endswith("-bait")]
    check("the 'none' baits sit in both splits",
          {c["split"] for c in baits} == {"train", "heldout"} and len(baits) >= 3,
          str([(c["id"], c["split"]) for c in baits]))


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
        print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
        sys.exit(1)
    print("all task-intake tests passed")
