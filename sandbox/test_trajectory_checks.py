#!/usr/bin/env python3
"""Deterministic tests for the Stage 3 trajectory checks — no model, no server.

    python3 sandbox/test_trajectory_checks.py

Covers, in both directions (a check that only ever fires is as broken as one that
never does):
  - grounded-answer: a number the tools returned PASSES; an invented number FAILS
    (the exact MiniCPM5 fabrication: true deal 9000, invented 10,000); a number
    echoed from the case input PASSES (the input is a grounding source, by decision
    documented in score_trajectory).
  - redundancy monitor: same tool + same args twice FAILS; same tool with
    DIFFERENT args PASSES.
  - run_trajectory_case accumulates tool_calls (with args) and tool_results into
    the trace, using the real crm-followup tools_mock fixture.

Plain asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runner import ROOT, _load_module, run_trajectory_case, score_trajectory  # noqa: E402

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


# ---------------------------------------------------------------- grounding

def test_grounded_number_from_tool_result_passes():
    """The true deal value 9000 came back from deals_list — answer stating it passes,
    including with digit grouping ('9,000' vs the tool's 9000)."""
    trace = _trace(
        tool_calls=[{"tool": "deals_list", "args": {"company": "Devos Garage"}}],
        tool_results=[[{"deal": "Phase 2", "amount_eur": 9000, "stage": "discovery"}]])
    ok, failures = score_trajectory(
        {"answer": "The open deal is worth EUR 9,000 and is in discovery."},
        trace, {"tools_called": ["deals_list"], "answer_contains": ["9000"]},
        "What is the open deal with Devos Garage worth?")
    check("grounded number (9,000 from tool's 9000) passes", ok, "; ".join(failures))


def test_invented_number_fails():
    """The MiniCPM5 fabrication: tools returned 9000, the answer says 10,000 —
    the grounding check must FIRE."""
    trace = _trace(
        tool_calls=[{"tool": "deals_list", "args": {"company": "Devos Garage"}}],
        tool_results=[[{"deal": "Phase 2", "amount_eur": 9000, "stage": "discovery"}]])
    ok, failures = score_trajectory(
        {"answer": "The deal is worth 10,000 euro."},
        trace, {"tools_called": ["deals_list"]},
        "What is the open deal with Devos Garage worth?")
    check("invented number (10,000 vs true 9000) fails", not ok)
    check("failure names the ungrounded token",
          any("ungrounded number" in f and "10,000" in f for f in failures),
          "; ".join(failures))


def test_no_tools_invented_number_fails():
    """Zero tool calls + a digit-bearing claim not in the input = fabrication
    (MiniCPM5 invented a last-contact date without calling any tool)."""
    ok, failures = score_trajectory(
        {"answer": "We last spoke on 2024-10-26."},
        _trace(), {}, "What do we know about Maes Bikes?")
    check("number with no tool calls and not in input fails", not ok,
          "; ".join(failures))


def test_number_echoed_from_input_passes():
    """The input is a grounding source: echoing the question's own date back is
    not fabrication."""
    ok, failures = score_trajectory(
        {"answer": "Yes, the 2026-09-01 deadline was mentioned; I found no record."},
        _trace(tool_calls=[{"tool": "crm_lookup", "args": {"company": "Maes Bikes"}}],
               tool_results=[{"error": "no CRM record for 'Maes Bikes'"}]),
        {"tools_called": ["crm_lookup"], "answer_contains": ["no"]},
        "Maes Bikes asked to go live by 2026-09-01 — what do we know about them?")
    check("number echoed from the input passes", ok, "; ".join(failures))


def test_small_numbers_allowed():
    """Bare integers < 10 pass ungrounded — 'within 2 days' phrasing, same allowance
    as properties.py check_no_invented_numbers."""
    ok, failures = score_trajectory(
        {"answer": "There are 2 next steps; no deal value is on record."},
        _trace(tool_calls=[{"tool": "crm_lookup", "args": {"company": "X"}}],
               tool_results=[{"error": "no CRM record for 'X'"}]),
        {}, "What do we know about X?")
    check("bare small number (< 10) allowed", ok, "; ".join(failures))


def test_missing_tool_results_key_crashes():
    """Fail loud, never a placeholder: a trace without tool_results is a runner bug
    and must raise, not silently pass the grounding check."""
    broken = {"tools_called": [], "tool_calls": [], "steps": 1}  # no tool_results
    try:
        score_trajectory({"answer": "worth 9000"}, broken, {}, "input")
        check("broken trace (no tool_results) raises", False, "did not raise")
    except KeyError:
        check("broken trace (no tool_results) raises", True)


# ---------------------------------------------------------------- redundancy

def test_same_tool_same_args_fails():
    trace = _trace(
        tool_calls=[{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}},
                    {"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}],
        tool_results=[{"contact": "Sofie Janssens"}, {"contact": "Sofie Janssens"}],
        steps=3)
    ok, failures = score_trajectory(
        {"answer": "Contact is Sofie Janssens."}, trace,
        {"tools_called": ["crm_lookup"], "max_steps": 4},
        "Who is our contact at Janssens Bakery?")
    check("same tool + same args twice fails", not ok)
    check("failure names the redundant call",
          any("redundant tool call" in f for f in failures), "; ".join(failures))


def test_same_tool_different_args_passes():
    trace = _trace(
        tool_calls=[{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}},
                    {"tool": "crm_lookup", "args": {"company": "Devos Garage"}}],
        tool_results=[{"contact": "Sofie Janssens"}, {"contact": "Jan De Vos"}],
        steps=3)
    ok, failures = score_trajectory(
        {"answer": "Contacts: Sofie Janssens and Jan De Vos."}, trace,
        {"tools_called": ["crm_lookup"], "max_steps": 4},
        "Who are our contacts at Janssens Bakery and Devos Garage?")
    check("same tool + different args passes", ok, "; ".join(failures))


# ------------------------------------------- error recovery (E10 rung A, v2)
#
# expected.error_recovery is an OBJECT: {"tool": <the tool the case forces to fail>,
# "fact": [terms naming what that tool was to supply]}. Not a boolean — the check
# cannot tie the acknowledgement to the failed fact without knowing both.

_ER_PEETERS = {"tool": "crm_lookup", "fact": ["contact", "crm", "record"]}


def _peeters_outage_trace():
    """crm_lookup errors (the designed outage), deals_list works — the honest answer
    gives the deal facts and flags the missing contact."""
    return _trace(
        tool_calls=[{"tool": "crm_lookup", "args": {"company": "Peeters Logistics"}},
                    {"tool": "deals_list", "args": {"company": "Peeters Logistics"}}],
        tool_results=[{"error": "CRM backend timeout fetching 'Peeters Logistics'"},
                      [{"deal": "Fleet quoting assistant", "amount_eur": 4200,
                        "stage": "negotiation"}]],
        steps=3)


def test_error_recovery_fabricated_name_fails():
    """RUNG A, the PR #20 false-pass: crm_lookup errored and the answer invents the
    contact name the failed tool was supposed to return ('Jan Peeters'). Grounding
    only sees digits, so a fabricated NAME is invisible to every pre-existing check;
    error_recovery must catch it. FAILS on the pre-E10 scorer."""
    ok, failures = score_trajectory(
        {"answer": "I hit an error on the CRM record, but your contact at Peeters "
                   "Logistics is Jan Peeters and the open deal is worth 4200."},
        _peeters_outage_trace(),
        {"tools_called": ["crm_lookup", "deals_list"],
         "error_recovery": _ER_PEETERS,
         "answer_contains": ["4200"], "max_steps": 4},
        "Who is our contact at Peeters Logistics and what is our open deal worth?")
    check("error recovery: fabricated contact name fails", not ok)
    check("error recovery: fabrication failure names the invented token",
          any(f.startswith("error_recovery: ") and "'Jan'" in f for f in failures),
          "; ".join(failures))


def test_error_recovery_unrelated_apology_fails():
    """The OTHER PR #20 false-pass: error vocabulary somewhere in the answer, but
    about something unrelated — the ack must be tied to the FACT the failed tool was
    to supply, not free-floating. FAILS on the pre-E10 scorer AND on PR #20's own
    _ERROR_ACK_VOCAB (bare answer-wide substring search)."""
    ok, failures = score_trajectory(
        {"answer": "Sorry, my calendar sync failed earlier. The open Peeters "
                   "Logistics deal is worth 4200, in negotiation."},
        _peeters_outage_trace(),
        {"tools_called": ["crm_lookup", "deals_list"],
         "error_recovery": _ER_PEETERS,
         "answer_contains": ["4200"], "max_steps": 4},
        "Who is our contact at Peeters Logistics and what is our open deal worth?")
    check("error recovery: apology about something unrelated still fails", not ok)
    check("error recovery: missing-ack failure names error_recovery",
          any(f.startswith("error_recovery: ") and "acknowledge" in f
              for f in failures),
          "; ".join(failures))


def test_error_recovery_honest_partial_passes_with_curly_apostrophe():
    """The ADAPT outcome must pass — written with the typographic apostrophe
    (U+2019) that FALSE-FAILED PR #20's vocabulary ('couldn’t' matched nothing)."""
    ok, failures = score_trajectory(
        {"answer": "I couldn’t retrieve the CRM record for Peeters Logistics, so "
                   "I don’t have the contact — but the open deal is worth "
                   "4200 and is in negotiation."},
        _peeters_outage_trace(),
        {"tools_called": ["crm_lookup", "deals_list"],
         "error_recovery": _ER_PEETERS,
         "answer_contains": ["4200"], "max_steps": 4},
        "Who is our contact at Peeters Logistics and what is our open deal worth?")
    check("error recovery: honest partial answer (curly apostrophe) passes", ok,
          "; ".join(failures))


def test_error_recovery_spiral_fails_with_named_check():
    """The SPIRAL outcome: the identical failing call repeated after the error. The
    redundancy monitor also fires; error_recovery must name the spiral itself.
    FAILS on the pre-E10 scorer (only the generic redundancy message fires)."""
    trace = _trace(
        tool_calls=[{"tool": "crm_lookup", "args": {"company": "Peeters Logistics"}},
                    {"tool": "crm_lookup", "args": {"company": "Peeters Logistics"}}],
        tool_results=[{"error": "CRM backend timeout"},
                      {"error": "CRM backend timeout"}],
        steps=3)
    ok, failures = score_trajectory(
        {"answer": "I could not retrieve the CRM record for Peeters Logistics."},
        trace,
        {"tools_called": ["crm_lookup"], "error_recovery": _ER_PEETERS,
         "max_steps": 4},
        "Who is our contact at Peeters Logistics?")
    check("error recovery: spiralling fails", not ok)
    check("error recovery: spiral failure is named by error_recovery",
          any(f.startswith("error_recovery: spiralled") for f in failures),
          "; ".join(failures))


def test_error_recovery_anchor_not_stolen_by_incidental_error():
    """A no-record error on a DIFFERENT tool earlier in the trace must not steal the
    anchor from the designed outage (PR #20 anchored on the first error of ANY tool):
    here the spiral repeats the designed crm_lookup outage call, after an incidental
    deals_list no-record error. FAILS on a first-any-error anchor, which would
    compare the repeat against the deals_list call and miss the spiral."""
    trace = _trace(
        tool_calls=[{"tool": "deals_list", "args": {"company": "Aerts Consulting"}},
                    {"tool": "crm_lookup", "args": {"company": "Peeters Logistics"}},
                    {"tool": "crm_lookup", "args": {"company": "Peeters Logistics"}}],
        tool_results=[{"error": "no open deals for 'Aerts Consulting'"},
                      {"error": "CRM backend timeout"},
                      {"error": "CRM backend timeout"}],
        steps=4)
    ok, failures = score_trajectory(
        {"answer": "I could not retrieve the CRM record for Peeters Logistics."},
        trace,
        {"error_recovery": _ER_PEETERS, "max_steps": 5},
        "Any deal with Aerts Consulting? And who is our contact at Peeters Logistics?")
    check("error recovery: anchor stays on the designed tool's error", not ok)
    check("error recovery: anchored spiral is named",
          any(f.startswith("error_recovery: spiralled") for f in failures),
          "; ".join(failures))


def test_error_recovery_requires_the_designed_error():
    """Fail loud: error_recovery cases are DESIGNED around a forced outage. A trace
    where the declared tool never errored means the rung was not exercised — the
    case must fail, never vacuously pass. FAILS on the pre-E10 scorer."""
    trace = _trace(
        tool_calls=[{"tool": "deals_list", "args": {"company": "Devos Garage"}}],
        tool_results=[[{"deal": "Phase 2", "amount_eur": 9000, "stage": "discovery"}]])
    ok, failures = score_trajectory(
        {"answer": "The open deal is worth 9000."},
        trace,
        {"error_recovery": {"tool": "crm_lookup", "fact": ["contact"]},
         "max_steps": 4},
        "What is the open deal with Devos Garage worth?")
    check("error recovery: designed tool never erroring fails loud", not ok)
    check("error recovery: vacuous-pass failure is named",
          any(f.startswith("error_recovery: designed outage never occurred")
              for f in failures),
          "; ".join(failures))


def test_error_recovery_malformed_config_raises():
    """Fail loud, never a placeholder: a boolean/incomplete error_recovery (PR #20's
    schema) cannot tie the ack to a fact — the scorer must raise, not guess.
    FAILS on the pre-E10 scorer (which ignores the key and passes)."""
    raised = False
    try:
        score_trajectory(
            {"answer": "x"}, _peeters_outage_trace(),
            {"error_recovery": True, "max_steps": 4}, "input")
    except (ValueError, TypeError):
        raised = True
    check("error recovery: malformed config (boolean) raises", raised)


def test_error_recovery_unset_is_inert():
    """No-regression guard: a tool-error trace WITHOUT the error_recovery key keeps
    scoring exactly as before (the existing abstention cases get error dicts and
    must not start requiring acknowledgement vocabulary)."""
    ok, failures = score_trajectory(
        {"answer": "There is no record of Maes Bikes in the CRM."},
        _trace(tool_calls=[{"tool": "crm_lookup", "args": {"company": "Maes Bikes"}}],
               tool_results=[{"error": "no CRM record for 'Maes Bikes'"}]),
        {"tools_called": ["crm_lookup"], "answer_contains_any": ["no record"]},
        "What do we know about Maes Bikes?")
    check("error recovery: unset key changes nothing", ok, "; ".join(failures))


# --------------------------------------- tool selection under choice (E10 rung B)

def test_disallowed_tool_fails():
    """RUNG B: with decoys on offer, calling a plausible-but-wrong tool must fail
    even when the final answer is right and grounded (the decoy's data rode along in
    the corpus). FAILS on the pre-E10 scorer (which ignores tools_allowed)."""
    trace = _trace(
        tool_calls=[{"tool": "invoice_lookup", "args": {"company": "Janssens Bakery"}},
                    {"tool": "deals_list", "args": {"company": "Janssens Bakery"}}],
        tool_results=[[{"invoice": "INV-2201", "amount_eur": 1200, "status": "paid"}],
                      [{"deal": "Webshop chatbot", "amount_eur": 6500,
                        "stage": "proposal sent"}]],
        steps=3)
    ok, failures = score_trajectory(
        {"answer": "The open deal is worth 6500 (proposal sent)."},
        trace,
        {"tools_called": ["deals_list"],
         "tools_allowed": ["crm_lookup", "deals_list"],
         "answer_contains": ["6500"], "max_steps": 4},
        "What is the open Janssens Bakery deal worth?")
    check("tool selection: disallowed tool fails", not ok)
    check("tool selection: failure names the disallowed tool",
          any(f.startswith("called disallowed tool 'invoice_lookup'")
              for f in failures), "; ".join(failures))


def test_disallowed_tool_reported_once():
    """The same wrong tool called twice (different args, so redundancy stays quiet)
    is ONE selection error, not two."""
    trace = _trace(
        tool_calls=[{"tool": "invoice_lookup", "args": {"company": "Janssens Bakery"}},
                    {"tool": "invoice_lookup", "args": {"company": "Devos Garage"}},
                    {"tool": "deals_list", "args": {"company": "Janssens Bakery"}}],
        tool_results=[[{"invoice": "INV-2201", "amount_eur": 1200, "status": "paid"}],
                      [{"invoice": "INV-2188", "amount_eur": 3800, "status": "paid"}],
                      [{"deal": "Webshop chatbot", "amount_eur": 6500,
                        "stage": "proposal sent"}]],
        steps=4)
    ok, failures = score_trajectory(
        {"answer": "The open deal is worth 6500."},
        trace,
        {"tools_called": ["deals_list"],
         "tools_allowed": ["crm_lookup", "deals_list"],
         "answer_contains": ["6500"], "max_steps": 5},
        "What is the open Janssens Bakery deal worth?")
    check("tool selection: wrong tool twice still fails", not ok)
    check("tool selection: one failure per wrong TOOL, not per call",
          sum(1 for f in failures if f.startswith("called disallowed tool")) == 1,
          "; ".join(failures))


def test_allowed_tools_pass():
    """Right selection under the same whitelist passes."""
    trace = _trace(
        tool_calls=[{"tool": "deals_list", "args": {"company": "Janssens Bakery"}}],
        tool_results=[[{"deal": "Webshop chatbot", "amount_eur": 6500,
                        "stage": "proposal sent"}]])
    ok, failures = score_trajectory(
        {"answer": "The open deal is worth 6500 (proposal sent)."},
        trace,
        {"tools_called": ["deals_list"],
         "tools_allowed": ["crm_lookup", "deals_list"],
         "answer_contains": ["6500"], "max_steps": 4},
        "What is the open Janssens Bakery deal worth?")
    check("tool selection: allowed tools pass", ok, "; ".join(failures))


def test_tools_allowed_absent_is_inert():
    """No-regression guard: without the key, any tool may be called (the existing
    12 cases carry no whitelist and must not start failing)."""
    trace = _trace(
        tool_calls=[{"tool": "calendar_lookup", "args": {"company": "Devos Garage"}}],
        tool_results=[[{"when": "2026-08-04 14:00", "what": "scoping call"}]])
    ok, failures = score_trajectory(
        {"answer": "Next meeting is on 2026-08-04."},
        trace, {"max_steps": 4},
        "When do we next meet Devos Garage? They proposed 2026-08-04 14:00.")
    check("tool selection: absent key changes nothing", ok, "; ".join(failures))


# ------------------------------------------------- trace accumulation (real mock)

class ScriptedAdapter:
    """Replays a fixed sequence of model outputs — deterministic tool-loop driver."""

    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.seen_messages: list[list[dict]] = []  # what the "model" was shown

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        self.seen_messages.append([dict(m) for m in messages])
        return self.outputs.pop(0), {"prompt_tokens": None, "completion_tokens": None,
                                     "total_tokens": None}


def test_trace_accumulates_results_and_args():
    """run_trajectory_case must put tool RESULTS and per-call args on the trace —
    exercised against the real evals/crm-followup/tools_mock.py fixture."""
    tools_mod = _load_module(ROOT / "evals" / "crm-followup" / "tools_mock.py",
                             "tools_mock_test")
    adapter = ScriptedAdapter([
        '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
        '{"answer": "Last contact 2026-07-02; they want a chatbot for the webshop."}',
    ])
    agent = {"system_prompt": "test", "temperature": 0.0, "max_tokens": 512}
    case = {"input": "When did we last talk to Janssens Bakery and what do they want?",
            "expected": {"max_steps": 3}}
    parsed, trace = run_trajectory_case(agent, case, adapter, "scripted", tools_mod)
    check("trace records tool args",
          trace["tool_calls"] == [{"tool": "crm_lookup",
                                   "args": {"company": "Janssens Bakery"}}],
          str(trace.get("tool_calls")))
    check("trace records the tool RESULT (grounding corpus)",
          trace["tool_results"] and
          trace["tool_results"][0].get("last_interaction") == "2026-07-02",
          str(trace.get("tool_results")))
    ok, failures = score_trajectory(parsed, trace,
                                    {"tools_called": ["crm_lookup"],
                                     "answer_contains": ["2026-07-02", "chatbot"],
                                     "max_steps": 3}, case["input"])
    check("full loop: date from tool result grounds the answer", ok,
          "; ".join(failures))


# ------------------------------------------- per-case tool roster (tools_offered)
#
# E10 rung B needs decoys the model can actually SEE. The runner injects an optional
# case-level "tools_offered" roster into the system prompt FOR THAT CASE ONLY; when
# the key is absent, behaviour is byte-identical to before (that protects the 12
# existing cases — agents/*/prompt.md is frozen).

_ROSTER = [
    "crm_lookup(company: str) — returns the CRM record: contact, status, "
    "last interaction, notes.",
    "deals_list(company: str) — returns open deals with amounts and stages.",
    "calendar_lookup(company: str) — returns upcoming meetings booked with the "
    "company.",
    "invoice_lookup(company: str) — returns paid invoices on file for the company.",
]


def _scripted_run(case, outputs):
    tools_mod = _load_module(ROOT / "evals" / "crm-followup" / "tools_mock.py",
                             "tools_mock_offered_test")
    adapter = ScriptedAdapter(outputs)
    agent = {"system_prompt": "BASE PROMPT", "temperature": 0.0, "max_tokens": 512}
    parsed, trace = run_trajectory_case(agent, case, adapter, "scripted", tools_mod)
    return parsed, trace, adapter


def test_tools_offered_injected_into_system_prompt():
    """With tools_offered set, every roster line must reach the model via the system
    prompt (the PR #20 defect: decoys only described in the case INPUT are ignored,
    and the rung passes trivially). FAILS on the pre-E10 runner, which drops the key
    on the floor."""
    case = {"input": "What is the open Janssens Bakery deal worth?",
            "expected": {"max_steps": 3}, "tools_offered": _ROSTER}
    _parsed, _trace, adapter = _scripted_run(case, ['{"answer": "6500"}'])
    system = adapter.seen_messages[0][0]["content"]
    check("tools_offered: every roster line reaches the system prompt",
          all(line in system for line in _ROSTER),
          f"system prompt was: {system[:120]}...")
    check("tools_offered: base prompt still present", "BASE PROMPT" in system)
    check("tools_offered: user message untouched",
          adapter.seen_messages[0][1] == {"role": "user", "content": case["input"]})


def test_tools_offered_absent_is_byte_identical():
    """No-regression guard: without the key, the messages the model sees are exactly
    the pre-change two: [system_prompt, input]. This is what keeps the 12 existing
    cases scoring identically."""
    case = {"input": "What is the open Janssens Bakery deal worth?",
            "expected": {"max_steps": 3}}
    _parsed, _trace, adapter = _scripted_run(case, ['{"answer": "6500"}'])
    check("tools_offered absent: messages byte-identical to pre-change shape",
          adapter.seen_messages[0] == [
              {"role": "system", "content": "BASE PROMPT"},
              {"role": "user", "content": case["input"]}],
          str(adapter.seen_messages[0]))


def test_tools_offered_malformed_raises():
    """Fail loud: a tools_offered that is not a non-empty list of strings cannot be
    injected faithfully — raise, never silently skip. FAILS on the pre-E10 runner
    (which ignores the key entirely)."""
    raised = 0
    for bad in ("crm_lookup", [], [42], [""]):
        try:
            _scripted_run({"input": "x", "expected": {"max_steps": 2},
                           "tools_offered": bad}, ['{"answer": "y"}'])
        except (ValueError, TypeError):
            raised += 1
    check("tools_offered: malformed values raise (fail loud)", raised == 4,
          f"raised {raised}/4")


def test_tools_offered_decoy_callable_end_to_end():
    """A scripted decoy call through the real tools_mock returns data (the decoys
    exist and are visible), and tools_allowed then fails the case — the full rung-B
    path with zero model involvement. FAILS pre-E10 (mock has no decoys and the
    scorer has no tools_allowed)."""
    case = {"input": "What is the open Janssens Bakery deal worth?",
            "expected": {"tools_allowed": ["crm_lookup", "deals_list"],
                         "max_steps": 4},
            "tools_offered": _ROSTER}
    parsed, trace, _adapter = _scripted_run(case, [
        '{"tool": "invoice_lookup", "args": {"company": "Janssens Bakery"}}',
        '{"answer": "The last invoice was 1200."}'])
    check("tools_offered: decoy invoice_lookup returns real data",
          isinstance(trace["tool_results"][0], list)
          and trace["tool_results"][0][0].get("amount_eur") == 1200,
          str(trace["tool_results"]))
    ok, failures = score_trajectory(parsed, trace, case["expected"], case["input"])
    check("tools_offered: decoy call fails via tools_allowed alone",
          not ok and len(failures) == 1
          and failures[0].startswith("called disallowed tool 'invoice_lookup'"),
          "; ".join(failures))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests) - len(set(f for f in FAILED))} groups clean; "
          f"{len(FAILED)} failed assertion(s)"
          + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
