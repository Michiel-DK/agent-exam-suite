#!/usr/bin/env python3
"""Effect tests for MULTITURN-EXAM (pass 1) — no live model, scripted adapters only.

    python3 evals/test_multiturn.py

PLAIN-ASSERT SCRIPT, DELIBERATELY (unlike the check()-collect-and-continue
pattern this repo's other test files use): every assertion below is a bare
`assert`, so the script HALTS at the first AssertionError and the traceback
names exactly which assertion fired — there is no runner-style failed_checks
list in this file. That is the format the criterion this file satisfies asks
for; a RED demonstration here means "run this file, read which assert line the
traceback names, confirm it is the intended one."

WHAT THIS LANE ADDED. A trajectory-mode case may now carry a `turns` list (user
messages) plus a parallel `turns_expected` list (each entry `{"turn": <text>,
"expected": {...}}`, matched to `turns` by POSITION AND literal text). Each turn
runs its OWN independent tool loop (fresh step counter, fresh dedupe cache — a
fresh call to the extracted `_run_tool_loop` every turn) against FULL-HISTORY
context (system prompt + every prior turn's user message, assistant answer, and
tool exchange, in order — no filtering, no summarising; E27's scoped-assembly arm
is out of this lane). `score_case` is now the SOLE producer of a trajectory-mode
verdict (criterion 9): attempt()'s old outer `score_trajectory(...)` call and the
D2 termination-override block (master runner.py:920-935) are both deleted from
attempt() and relocated, behavior preserved, into `_score_one_turn` — the ONE
call site of `score_trajectory(` left in sandbox/runner.py (grep count pasted in
the PR body).

WHAT EACH TEST PINS, each RED-DEMONSTRATED against a named injection before this
file was committed (pastes live in the lane's PR body, not here — same
red/green convention as evals/test_crm_realism.py and
sandbox/test_dedupe_tools.py, applied through bare asserts instead of check()):

  (1)  DEFAULT-PATH BYTE-IDENTITY (criterion 1). A real committed no-`turns`
       crm-followup case, run through the REAL run_exam with a scripted adapter
       standing in for the model and the REAL tools_mock.py fixture, produces
       EXACTLY master's 5-key trace shape and verdict.
  (9a) TERMINATION-PATH WITNESS (criterion 9a). The golden case in (1) never
       terminates, so it cannot witness the D2 relocation; a SEPARATE no-`turns`
       case driven into the termination path must show master's ORIGINAL
       two-key {"bucket","check"} termination entry — no "turn" key leaking in
       for a case that has no turns. Criteria 1 and 9a TOGETHER are the witness.
  (2a) INDEPENDENT-PER-TURN-LOOP red. Two turns, identical question, dedupe_tools
       ON: turn 1 must show a REAL tool re-execution (its own fresh cache), not a
       suppressed repeat served from turn 0's cache. About loop MECHANICS only —
       context stays full-history throughout; this is not a scoped-assembly demo.
  (2b) RAISE-ON-UNKNOWN-TURN red. A turn whose input text does not match the
       committed `turns_expected` entry at that position RAISES rather than
       scoring vacuously (the recap `_exp` discipline, restated for multi-turn).
  (2c) NON-FINAL-TURN-FAILURE red, through the SAME code path that writes the
       committed snapshot (run_exam -> snapshot_payload -> _snapshot_case — not
       score_case/the turn loop invoked directly, in isolation). Turn 0 fails,
       turn 1 passes; the written record still shows passed:false with the
       failing check naming turn 0, not turn 1.
  ERROR-RECOVERY CROSS-TURN PAIRING (P1 fix, pass 3 — NOTE: the brief's own
       numbering calls this "criterion 2a", colliding with the pre-existing
       "(2a)" label above for loop mechanics; the two are unrelated, this one
       is named plainly here to avoid confusion). test_2a_i_...verdict_level_red
       and test_2a_ii_...reason_level_red: `_error_recovery_failures` clause 1
       is INDEX-PAIRED (zip(tool_calls, tool_results)) and must pair a turn's
       calls against THAT SAME TURN's own results, never a different turn's,
       even though the scoring trace's `tool_results` key is deliberately the
       ACCUMULATED cross-turn corpus the grounding/digit checks need. (i)
       verdict-level: a turn that genuinely hits the designed outage and
       acknowledges it must PASS. (ii) reason-level: a turn that hits the
       outage and ignores it must still FAIL, but the REPORTED failure must be
       the acknowledgement clause, not a false "outage never occurred" — the
       pre-fix bug reports the latter unconditionally, for either scenario.
  (3)  PER-TURN METRICS. prompt_tokens is the turn's FIRST model call only;
       completion_tokens/wall_ms are the TURN TOTAL across that turn's whole
       intra-turn tool loop. Verified in the live result AND in the
       snapshot-shaped record `_snapshot_case` actually produces.
  (grounding) Cross-turn scoring corpus accumulates tool_results/input_text
       across turns (so a later turn can cite an earlier turn's fetched fact),
       while tool_calls/tools_called/steps stay strictly per-turn (CLAUDE.md
       gotcha 4 — presence and absence checks must not share an over-eager
       normalization that erases a turn boundary that never happened).
  (history) Full-history assembly: turn 1's model call actually SEES turn 0's
       user message, tool exchange, and final answer in its `messages` — the
       deliberate baseline this lane measures (never scoped/filtered).
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
from runner import (ROOT as RUNNER_ROOT, TerminationError, _load_module,  # noqa: E402
                    load_exam, run_exam, score_case, snapshot_payload)


# ------------------------------------------------------------------ fixtures

class ScriptedAdapter:
    """Replays a fixed sequence of model outputs. CYCLES when the script runs
    out (sandbox/test_dedupe_tools.py's reasoning: a loop bug making MORE calls
    than the script has lines must be caught by a call-count assertion, not
    disguised as an IndexError from the fixture). An entry may be a 2-tuple
    (content, metrics_override) to control per-call token counts; a bare string
    uses the flat default metrics."""

    def __init__(self, outputs: list):
        self.outputs = list(outputs)
        self.seen_messages: list = []

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        out = self.outputs[len(self.seen_messages) % len(self.outputs)]
        self.seen_messages.append([dict(m) for m in messages])
        if isinstance(out, tuple):
            content, metrics = out
        else:
            content, metrics = out, {}
        meta = {"prompt_tokens": None, "completion_tokens": None,
               "total_tokens": None, "content_chars": len(content),
               "reasoning_chars": 0, "finish_reason": "stop", **metrics}
        return content, meta


def _traj_tools():
    return _load_module(RUNNER_ROOT / "evals" / "crm-followup" / "tools_mock.py",
                        "tools_mock_multiturn_test")


_AGENT = {"system_prompt": "test agent", "temperature": 0.0, "max_tokens": 512}


# --------------------------------------------------------- (1) golden path

def test_1_default_path_byte_identical_to_master():
    """CRITERION 1. lookup-last-contact (train, real committed case, no `turns`)
    through the REAL run_exam, scripted model, real tools_mock.py fixture."""
    exam = load_exam("crm-followup")
    case = next(c for c in exam["cases"] if c["id"] == "lookup-last-contact")
    assert "turns" not in case, f"golden case must be a real single-turn case: {case}"
    script = ['{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
              '{"answer": "Janssens Bakery was last contacted on 2026-07-02 '
              'about a chatbot."}']
    agent = runner.load_agent("crm-followup")
    real_adapter_for = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: ScriptedAdapter(script)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(agent, {**exam, "cases": [case]}, "ollama", "scripted")
    finally:
        runner.adapter_for = real_adapter_for
    got = result["cases"][0]
    assert got["passed"] is True, f"golden case must pass: {got}"
    assert set(got["detail"].keys()) == {
        "tools_called", "tool_calls", "tool_results", "steps", "metrics"
    }, f"trace key set drifted from master's literal 5-key set: {sorted(got['detail'].keys())}"
    assert got["detail"]["tools_called"] == ["crm_lookup"], got["detail"]
    assert got["detail"]["steps"] == 2, got["detail"]
    assert "failed_checks" not in got, f"a passing case must carry no failed_checks: {got}"
    assert "turns" not in got["detail"], \
        f"no-turns path must never grow a 'turns' key: {got['detail']}"
    assert got["expected"] == case["expected"], \
        f"case.get('expected') fix must not touch the no-turns record shape: {got['expected']}"


def test_9a_termination_path_single_turn_matches_master_shape():
    """CRITERION 9a. A no-`turns` case driven into the D2 termination path must
    show master's ORIGINAL two-key {"bucket","check"} termination entry — the
    witness criterion 1's ordinarily-completing golden case cannot provide."""
    exam = load_exam("crm-followup")
    case = next(c for c in exam["cases"] if c["id"] == "lookup-last-contact")
    death = TerminationError(
        "model emitted no answer",
        {"finish_reason": "length", "completion_tokens": 128, "content_chars": 0,
         "reasoning_chars": 40})

    class _DeathAdapter:
        def generate(self, messages, model, temperature=0.0, max_tokens=512):
            raise death

    agent = runner.load_agent("crm-followup")
    real_adapter_for = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: _DeathAdapter()
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(agent, {**exam, "cases": [case]}, "ollama", "scripted")
    finally:
        runner.adapter_for = real_adapter_for
    got = result["cases"][0]
    assert got["passed"] is False, got
    assert got["failed_checks"][0] == {"bucket": "termination", "check": "termination"}, \
        f"no-turns termination entry must stay the ORIGINAL two-key shape: {got['failed_checks']}"
    assert {"bucket": "quality", "check": "answer_present"} in got["failed_checks"], \
        f"the declared D2 co-firing must be unchanged: {got['failed_checks']}"
    assert got["detail"]["termination"]["cause"] == "no_answer", got["detail"]


# --------------------------------------------------- (R7) early termination

def test_r7_turn_terminates_before_first_model_call_no_fabricated_metrics():
    """R7 (pass-2 fix list, folded into criterion 3). A turn that raises
    (TerminationError, here — D2's own vocabulary) before completing its FIRST
    model call has NO real prompt_tokens/completion_tokens/wall_ms to report:
    step_metrics for that turn is empty. That turn's record must carry an
    explicit incomplete/terminated marker (this lane reuses the existing
    "termination" key already required by criterion 2 to name the turn — no new
    key invented) and must NEVER carry a fabricated 0 standing in for a
    measurement that never happened. Turn 0 completes normally with real
    (deliberately distinctive) metrics; turn 1's first — and only — call dies
    immediately, before _run_tool_loop's step_metrics.append() for that turn
    ever runs. Checked both on the live score_case() result and on the
    snapshot-shaped record `_snapshot_case` actually writes (never a
    standalone in-memory dict)."""
    q0 = "When did we last talk to Janssens Bakery?"
    q1 = "And Devos Garage?"
    case = {
        "id": "_probe_r7_turn_dies_before_first_call", "split": "train",
        "turns": [q0, q1],
        "turns_expected": [
            {"turn": q0, "expected": {"tools_called": ["crm_lookup"],
                                      "answer_contains": ["2026-07-02"],
                                      "max_steps": 4}},
            {"turn": q1, "expected": {"max_steps": 2}},
        ],
    }
    death = TerminationError(
        "model emitted no answer",
        {"finish_reason": "length", "completion_tokens": 0, "content_chars": 0,
         "reasoning_chars": 0})
    turn0_script = [
        '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
        '{"answer": "Janssens Bakery was last contacted on 2026-07-02."}',
    ]

    class _DiesOnTurn1Adapter:
        """Turn 0's two calls play out normally with distinctive per-call
        metrics; the THIRD call (turn 1's first, and only) raises before any
        metrics dict for it is ever produced."""

        def __init__(self):
            self.calls = 0

        def generate(self, messages, model, temperature=0.0, max_tokens=512):
            self.calls += 1
            if self.calls <= len(turn0_script):
                content = turn0_script[self.calls - 1]
                return content, {"prompt_tokens": 10 * self.calls, "completion_tokens": 5,
                                 "total_tokens": 10 * self.calls + 5,
                                 "content_chars": len(content), "reasoning_chars": 0,
                                 "finish_reason": "stop"}
            raise death

    parsed, trace, passed, failures, failed_checks = score_case(
        _AGENT, case, _DiesOnTurn1Adapter(), "scripted", _traj_tools())
    assert passed is False, "a case with a terminated turn must fail"
    t0, t1 = trace["turns"]
    assert t0["prompt_tokens"] == 10, \
        f"turn 0 completed normally and must report its real first-call value: {t0}"
    assert "termination" not in t0, f"turn 0 never died: {t0}"

    assert "termination" in t1, \
        f"turn 1 must carry an explicit incomplete/terminated marker: {t1}"
    assert t1["prompt_tokens"] is None, \
        f"turn 1 never completed a model call — prompt_tokens must be None, never a fabricated 0: {t1}"
    assert t1["completion_tokens"] is None, \
        f"turn 1 never completed a model call — completion_tokens must be None, never a fabricated 0: {t1}"
    assert t1["wall_ms"] is None, \
        f"turn 1 never completed a model call — wall_ms must be None, never a fabricated 0: {t1}"
    assert t1["passed"] is False, t1
    assert any(fc.get("turn") == 1 and fc.get("check") == "termination"
              for fc in failed_checks), \
        f"the case-level failed_checks must name turn 1 as the terminating turn: {failed_checks}"

    # Same code path that writes the committed snapshot (run_exam ->
    # snapshot_payload -> _snapshot_case), never the turn loop invoked in
    # isolation: input-growth-per-turn must stay computable from the committed
    # file alone by SKIPPING a marked-incomplete turn, never by reading a
    # fabricated number out of it.
    exam = load_exam("crm-followup")
    agent = runner.load_agent("crm-followup")
    modified_exam = {**exam, "cases": [case]}
    real_adapter_for = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: _DiesOnTurn1Adapter()
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(agent, modified_exam, "ollama", "scripted")
    finally:
        runner.adapter_for = real_adapter_for
    payload = snapshot_payload(agent, modified_exam, "ollama", "scripted", result)
    snap_entry = next(c for c in payload["cases"]
                      if c["id"] == "_probe_r7_turn_dies_before_first_call")
    tm0, tm1 = snap_entry["turn_metrics"]
    assert tm0["prompt_tokens"] == 10, tm0
    assert tm1["prompt_tokens"] is None, \
        f"committed snapshot must never carry a fabricated 0 for an unmeasured turn: {tm1}"
    assert tm1["completion_tokens"] is None, tm1
    assert tm1["wall_ms"] is None, tm1


# ------------------------------------------------------ (2a) loop mechanics

def test_2a_independent_per_turn_dedupe_cache_and_step_counter():
    """CRITERION 2(a) — INDEPENDENT-PER-TURN-LOOP red. Two turns ask the
    IDENTICAL question, dedupe_tools=True. If the dedupe cache (or step counter)
    leaked across turns instead of _run_tool_loop starting fresh every turn,
    turn 1's identical call would be served from turn 0's cache and recorded as
    a suppressed "deduped_calls" entry instead of a real tool_calls entry. This
    is about loop MECHANICS, not context isolation — full-history context is
    unaffected either way and stays forbidden from being scoped."""
    q = "When did we last talk to Janssens Bakery?"
    case = {
        "id": "_probe_loop_mechanics", "split": "train",
        "turns": [q, q],
        "turns_expected": [
            {"turn": q, "expected": {"tools_called": ["crm_lookup"],
                                     "answer_contains": ["2026-07-02"],
                                     # exactly the steps each turn needs: a
                                     # leaked step-counter offset from turn 0
                                     # leaves turn 1 zero budget and fails loud
                                     # (a slack budget hid the leak — refuted
                                     # 2026-09-02, pass-3 test-honesty lens)
                                     "max_steps": 2}},
            {"turn": q, "expected": {"tools_called": ["crm_lookup"],
                                     "answer_contains": ["2026-07-02"],
                                     # exactly the steps each turn needs: a
                                     # leaked step-counter offset from turn 0
                                     # leaves turn 1 zero budget and fails loud
                                     # (a slack budget hid the leak — refuted
                                     # 2026-09-02, pass-3 test-honesty lens)
                                     "max_steps": 2}},
        ],
    }
    script = ['{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
              '{"answer": "Janssens Bakery was last contacted on 2026-07-02."}']
    parsed, trace, passed, failures, failed_checks = score_case(
        _AGENT, case, ScriptedAdapter(script), "scripted", _traj_tools(),
        dedupe_tools=True)
    assert passed, failed_checks
    assert trace["turns"][0]["tools_called"] == ["crm_lookup"], trace["turns"][0]
    assert trace["turns"][1]["tools_called"] == ["crm_lookup"], \
        f"turn 1 must ALSO really call the tool — a fresh cache, not turn 0's: {trace['turns'][1]}"
    assert trace["turns"][1].get("deduped_calls") == [], \
        f"a leaked cache would populate turn 1's deduped_calls entry: {trace['turns'][1]}"
    assert trace["turns"][1]["steps"] == trace["turns"][0]["steps"] == 2, \
        f"turn 1's step counter must also reset: {trace}"


# ------------------------------------------------------ (2b) raise on drift

def test_2b_raise_on_unknown_turn():
    """CRITERION 2(b) — raise-on-unknown-turn red. turns[1]'s text does not match
    turns_expected[1]["turn"]: RAISES rather than scoring vacuously."""
    case = {
        "id": "_probe_turn_drift", "split": "train",
        "turns": ["turn one text", "turn two text — EDITED AT RUNTIME"],
        "turns_expected": [
            {"turn": "turn one text", "expected": {"max_steps": 2}},
            {"turn": "turn two text — the COMMITTED text, does not match",
             "expected": {"max_steps": 2}},
        ],
    }
    script = ['{"answer": "ok"}', '{"answer": "ok"}']
    raised = None
    try:
        score_case(_AGENT, case, ScriptedAdapter(script), "scripted", _traj_tools())
    except ValueError as exc:
        raised = exc
    assert raised is not None, "a mismatched turn must RAISE ValueError, not score vacuously"
    assert "turn 1" in str(raised) and "turn two text — EDITED AT RUNTIME" in str(raised), \
        f"the raise must name the turn and the mismatched committed text: {raised}"


def test_2b_raise_on_missing_turns_expected_entry():
    """Companion to 2b: more turns than committed turns_expected entries also
    raises (an under-committed case must not silently score its extra turn
    against nothing)."""
    case = {"id": "_probe_turn_overrun", "split": "train",
           "turns": ["only turn"], "turns_expected": []}
    raised = None
    try:
        score_case(_AGENT, case, ScriptedAdapter(['{"answer": "ok"}']),
                  "scripted", _traj_tools())
    except ValueError as exc:
        raised = exc
    assert raised is not None, "zero committed turns_expected entries must RAISE"


# ---------------------------------------------- (2c) non-final-turn failure

def test_2c_non_final_turn_failure_reaches_the_written_snapshot_record():
    """CRITERION 2(c) — NON-FINAL-TURN-FAILURE red, through the SAME code path
    that produces the committed snapshot.json: run_exam -> snapshot_payload ->
    _snapshot_case (never score_case/the turn loop invoked directly, in
    isolation, by this test). Turn 0 fails (its answer is missing the required
    needle), turn 1 passes; the case-level verdict AND the written snapshot
    record must both still show passed:false, with the failing check naming
    turn 0 — not turn 1, the passing one."""
    exam = load_exam("crm-followup")
    stub_case = {
        "id": "_probe_non_final_turn_failure", "split": "train",
        "turns": ["When did we last talk to Janssens Bakery?",
                  "And Devos Garage?"],
        "turns_expected": [
            {"turn": "When did we last talk to Janssens Bakery?",
             "expected": {"tools_called": ["crm_lookup"],
                          "answer_contains": ["THIS-NEEDLE-NEVER-APPEARS"],
                          "max_steps": 4}},
            {"turn": "And Devos Garage?",
             "expected": {"tools_called": ["crm_lookup"],
                          "answer_contains": ["2026-06-19"], "max_steps": 4}},
        ],
    }
    modified_exam = {**exam, "cases": [stub_case]}
    script = [
        '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
        '{"answer": "Janssens Bakery was last contacted on 2026-07-02."}',
        '{"tool": "crm_lookup", "args": {"company": "Devos Garage"}}',
        '{"answer": "Devos Garage was last contacted on 2026-06-19."}',
    ]
    agent = runner.load_agent("crm-followup")
    real_adapter_for = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: ScriptedAdapter(script)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(agent, modified_exam, "ollama", "scripted")
    finally:
        runner.adapter_for = real_adapter_for
    got = result["cases"][0]
    assert got["passed"] is False, \
        f"case-level verdict must be FALSE despite turn 1 passing: {got}"
    assert got["detail"]["turns"][0]["passed"] is False, got["detail"]["turns"][0]
    assert got["detail"]["turns"][1]["passed"] is True, got["detail"]["turns"][1]

    payload = snapshot_payload(agent, modified_exam, "ollama", "scripted", result)
    snap_entry = next(c for c in payload["cases"]
                      if c["id"] == "_probe_non_final_turn_failure")
    assert snap_entry["passed"] is False, \
        f"the WRITTEN snapshot record must also show passed:false: {snap_entry}"
    named_turns = [f.get("turn") for f in snap_entry.get("failures", [])]
    assert 0 in named_turns, \
        f"the written record must name turn 0 as a failing turn: {snap_entry.get('failures')}"
    assert 1 not in named_turns, \
        f"the written record must NOT blame turn 1, the passing one: {snap_entry.get('failures')}"
    assert [tm["turn"] for tm in snap_entry.get("turn_metrics", [])] == [0, 1], \
        snap_entry.get("turn_metrics")


# ------------------------------------ (2a) error_recovery cross-turn pairing

def _outage_case():
    """Shape of the committed case peeters-contact-followup-outage: turn 0 a
    HEALTHY deals_list call on Peeters Logistics, turn 1 a crm_lookup call on
    the same company, which tools_mock.py's real _BACKEND_DOWN forces to raise
    deterministically. Uses the REAL tools_mock.py fixture (via _traj_tools()),
    not a fake tool, so the designed outage is the genuine article, not a
    stand-in for it."""
    q0, q1 = "What's the deal amount for Peeters Logistics?", "Can you also get their contact details?"
    return {
        "id": "_probe_error_recovery_cross_turn_pairing", "split": "train",
        "turns": [q0, q1],
        "turns_expected": [
            {"turn": q0, "expected": {"tools_called": ["deals_list"],
                                      "answer_contains": ["4200"], "max_steps": 3}},
            {"turn": q1, "expected": {
                "tools_called": ["crm_lookup"],
                "error_recovery": {"tool": "crm_lookup",
                                   "fact": ["contact", "name", "crm", "record"]},
                "max_steps": 3}},
        ],
    }


def _outage_script(turn1_answer: str) -> list:
    return [
        '{"tool": "deals_list", "args": {"company": "Peeters Logistics"}}',
        '{"answer": "Their deal amount is 4200."}',
        '{"tool": "crm_lookup", "args": {"company": "Peeters Logistics"}}',
        json.dumps({"answer": turn1_answer}),
    ]


def test_2a_i_error_recovery_cross_turn_pairing_verdict_level_red():
    """CRITERION 2a(i) — VERDICT-LEVEL RED. Turn 1 hits the DESIGNED outage
    (crm_lookup on Peeters Logistics genuinely raises via tools_mock.py's real
    _BACKEND_DOWN) and the model answers turn 1 correctly despite it: calls the
    tool, receives the error, and acknowledges it in one sentence naming both a
    failure term and a fact term. The case's overall verdict must be PASS.

    PRE-FIX (P1 bug, reproduced): _error_recovery_failures' clause 1 zips
    trace["tool_calls"] (per-turn: 1 entry, turn 1's crm_lookup call) against
    trace["tool_results"] (ACCUMULATED: 2 entries, turn 0's healthy deals_list
    result THEN turn 1's error) — zip stops at the shorter length, pairing
    turn 1's call against turn 0's healthy result. No error is found at that
    pairing, so clause 1 fires 'designed outage never occurred' UNCONDITIONALLY
    (a blanket false-FAIL, regardless of the model's actual answer) and the
    function returns immediately, before clauses 2-4 ever run. Verified by
    hand pre-fix (git stash the fix, rerun this exact scenario): `passed=False`,
    the ONLY failure is
    "error_recovery: designed outage never occurred — 'crm_lookup' returned no
    error in this trace, so the rung was not exercised" — the assertion below
    (`passed is True`) is what fires RED against that.

    POST-FIX: the per-turn `tool_results_this_turn` view correctly pairs turn
    1's call against turn 1's OWN error result, clause 1 finds it, and the
    acknowledging answer clears clauses 2-4 too — passed becomes True."""
    case = _outage_case()
    script = _outage_script("I wasn't able to retrieve their contact record "
                            "right now.")
    parsed, trace, passed, failures, failed_checks = score_case(
        _AGENT, case, ScriptedAdapter(script), "scripted", _traj_tools())
    assert passed is True, \
        (f"turn 1 genuinely hit the designed outage and acknowledged it — the "
         f"case must PASS. If this fired, the P1 index-misalignment regressed: "
         f"failures={failures}, failed_checks={failed_checks}")
    assert failures == [], failures


def test_2a_ii_error_recovery_cross_turn_pairing_reason_level_red():
    """CRITERION 2a(ii) — REASON-LEVEL RED. Same designed outage, but turn 1's
    model answer IGNORES it and answers as if nothing changed (no acknowledgement
    vocabulary at all). The verdict is FAIL both before AND after the fix — the
    pre-fix bug is a blanket false-FAIL that fires regardless of the model's
    answer, so a verdict-only assertion here is satisfied even pre-fix and
    cannot serve as a red witness (documented, not a miss).

    What the fix changes, and what this test asserts instead, is WHICH failure
    is reported for turn 1:
      PRE-FIX: the misaligned pairing never finds the real error, so clause 1
        fires 'designed outage never occurred' (the DETECTION clause) — even
        though the tool genuinely errored. Verified by hand pre-fix: the ONLY
        failure string is exactly this one.
      POST-FIX: pairing is corrected, clause 1 correctly finds the outage (no
        'never occurred' failure), and clause 3 fires instead because THIS
        model never acknowledges it — 'never acknowledges that the ... fact
        ... is unavailable' (the ACKNOWLEDGEMENT clause).

    This guards against a fix that simply stops checking outages after turn 0
    (which would silently drop ALL error_recovery-derived failures for later
    turns, passing this scenario for the wrong reason — verdict would flip to
    True, which the assertion below would catch) rather than pairing
    correctly."""
    case = _outage_case()
    script = _outage_script("Their contact information is available in our "
                            "records and everything is up to date.")
    parsed, trace, passed, failures, failed_checks = score_case(
        _AGENT, case, ScriptedAdapter(script), "scripted", _traj_tools())
    assert passed is False, \
        f"turn 1 never acknowledged the outage — the case must still FAIL: {failures}"
    assert len(failures) == 1, \
        f"exactly one error_recovery failure expected for this scenario: {failures}"
    assert "never occurred" not in failures[0], \
        (f"POST-FIX the pairing must correctly find the real error — a "
         f"'designed outage never occurred' failure here means the P1 "
         f"index-misalignment regressed: {failures}")
    assert "never acknowledges" in failures[0], \
        (f"POST-FIX the reported failure must be the ACKNOWLEDGEMENT clause, "
         f"not the detection clause: {failures}")
    assert failed_checks == [{"bucket": "quality", "check": "error_recovery", "turn": 1}], \
        failed_checks


# --------------------------------------------------------- (3) per-turn metrics

def test_3_per_turn_metrics_pinned_and_reach_the_snapshot():
    """CRITERION 3. prompt_tokens is the turn's FIRST model call only;
    completion_tokens/wall_ms are the TURN TOTAL across the whole intra-turn tool
    loop. Each turn here makes TWO model calls (a tool call then an answer) with
    DELIBERATELY DISTINCT per-call token counts, so first-call-only vs
    turn-total-sum are distinguishable. Asserted both on the live result detail
    (_run_turns) and on the snapshot-shaped record `_snapshot_case` actually
    produces — not a standalone in-memory dict."""
    q1 = "When did we last talk to Janssens Bakery?"
    q2 = "And Devos Garage?"
    case = {
        "id": "_probe_per_turn_metrics", "split": "train",
        "turns": [q1, q2],
        "turns_expected": [
            {"turn": q1, "expected": {"tools_called": ["crm_lookup"],
                                      "answer_contains": ["2026-07-02"],
                                      "max_steps": 4}},
            {"turn": q2, "expected": {"tools_called": ["crm_lookup"],
                                      "answer_contains": ["2026-06-19"],
                                      "max_steps": 4}},
        ],
    }
    script = [
        ('{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
         {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}),
        ('{"answer": "Janssens Bakery was last contacted on 2026-07-02."}',
         {"prompt_tokens": 80, "completion_tokens": 12, "total_tokens": 92}),
        ('{"tool": "crm_lookup", "args": {"company": "Devos Garage"}}',
         {"prompt_tokens": 200, "completion_tokens": 7, "total_tokens": 207}),
        ('{"answer": "Devos Garage was last contacted on 2026-06-19."}',
         {"prompt_tokens": 230, "completion_tokens": 9, "total_tokens": 239}),
    ]
    parsed, trace, passed, failures, failed_checks = score_case(
        _AGENT, case, ScriptedAdapter(script), "scripted", _traj_tools())
    assert passed, failed_checks
    t0, t1 = trace["turns"]
    assert t0["prompt_tokens"] == 50, \
        f"turn 0 prompt_tokens must be the FIRST call's value, not summed: {t0}"
    assert t0["completion_tokens"] == 17, f"turn 0 completion_tokens must be the TURN TOTAL: {t0}"
    assert t1["prompt_tokens"] == 200, \
        f"turn 1 prompt_tokens must be the FIRST call's value, not summed: {t1}"
    assert t1["completion_tokens"] == 16, f"turn 1 completion_tokens must be the TURN TOTAL: {t1}"
    assert isinstance(t0["wall_ms"], (int, float)) and t0["wall_ms"] >= 0, t0
    assert trace["metrics"]["completion_tokens"] == 5 + 12 + 7 + 9, \
        f"case-level 'metrics' totals (the existing-totals floor) must still exist: {trace['metrics']}"

    exam = load_exam("crm-followup")
    agent = runner.load_agent("crm-followup")
    modified_exam = {**exam, "cases": [case]}
    real_adapter_for = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: ScriptedAdapter(script)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(agent, modified_exam, "ollama", "scripted")
    finally:
        runner.adapter_for = real_adapter_for
    payload = snapshot_payload(agent, modified_exam, "ollama", "scripted", result)
    snap_entry = next(c for c in payload["cases"]
                      if c["id"] == "_probe_per_turn_metrics")
    assert "turn_metrics" in snap_entry, \
        f"turn_metrics must reach the committed snapshot even on a PASSING case: {snap_entry}"
    tm0, tm1 = snap_entry["turn_metrics"]
    assert tm0["prompt_tokens"] == 50, tm0
    assert tm0["completion_tokens"] == 17, tm0
    assert tm1["prompt_tokens"] == 200, \
        f"input-growth-per-turn (the number this criterion exists to expose): {tm1}"


def test_3_pre_existing_case_gains_no_new_snapshot_key():
    """The other half of criterion 3/6: a no-`turns` case's snapshot record gets
    NO new key at all — `_snapshot_case` only adds turn_metrics when detail
    carries a "turns" list."""
    exam = load_exam("crm-followup")
    case = next(c for c in exam["cases"] if c["id"] == "lookup-last-contact")
    script = ['{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
              '{"answer": "Janssens Bakery was last contacted on 2026-07-02 '
              'about a chatbot."}']
    agent = runner.load_agent("crm-followup")
    real_adapter_for = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: ScriptedAdapter(script)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(agent, {**exam, "cases": [case]}, "ollama", "scripted")
    finally:
        runner.adapter_for = real_adapter_for
    payload = snapshot_payload(agent, exam, "ollama", "scripted", result)
    entry = payload["cases"][0]
    assert set(entry.keys()) == {"id", "split", "passed"}, \
        f"a no-turns case's snapshot record must gain NO new key: {entry}"


# ------------------------------------------------- grounding accumulation

def test_cross_turn_grounding_accumulates_but_calls_stay_per_turn():
    """A turn-1 answer citing a fact fetched in turn 0 must GROUND (the
    cross-turn-grounding shape this lane exists to measure): turn 1 answers
    directly from context, with NO new tool call, inside a 1-step budget — that
    is only possible because the scoring corpus accumulates turn 0's tool
    results. Meanwhile turn 0's OWN tools_called never leaks into turn 1's
    tools_not_called/redundancy bookkeeping (CLAUDE.md gotcha 4)."""
    q1 = "When did we last talk to Devos Garage?"
    q2 = "Remind me — when was that again?"
    case = {
        "id": "_probe_cross_turn_grounding", "split": "train",
        "turns": [q1, q2],
        "turns_expected": [
            {"turn": q1, "expected": {"tools_called": ["crm_lookup"],
                                      "answer_contains": ["2026-06-19"],
                                      "max_steps": 4}},
            {"turn": q2, "expected": {"tools_called": [],
                                      "tools_not_called": ["crm_lookup"],
                                      "answer_contains": ["2026-06-19"],
                                      "max_steps": 1}},
        ],
    }
    script = ['{"tool": "crm_lookup", "args": {"company": "Devos Garage"}}',
              '{"answer": "Devos Garage was last contacted on 2026-06-19."}',
              '{"answer": "You last talked to them on 2026-06-19."}']
    parsed, trace, passed, failures, failed_checks = score_case(
        _AGENT, case, ScriptedAdapter(script), "scripted", _traj_tools())
    assert passed, \
        f"turn 1 must ground off turn 0's fetched fact with zero new tool calls: {failed_checks}"
    assert trace["turns"][1]["tools_called"] == [], trace["turns"][1]


# --------------------------------------------------------- full-history

def test_full_history_context_assembly_no_scoping():
    """The deliberate baseline (E27's future scoped-assembly arm is OUT of this
    lane): turn 1's model call must SEE turn 0's user message, tool exchange,
    and final answer verbatim in `messages` — never filtered, never
    summarised."""
    q1 = "When did we last talk to Janssens Bakery?"
    q2 = "And what did they want?"
    case = {
        "id": "_probe_full_history", "split": "train",
        "turns": [q1, q2],
        "turns_expected": [
            {"turn": q1, "expected": {"tools_called": ["crm_lookup"],
                                      "answer_contains": ["2026-07-02"],
                                      "max_steps": 4}},
            {"turn": q2, "expected": {"answer_contains": ["chatbot"],
                                      "max_steps": 1}},
        ],
    }
    script = ['{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
              '{"answer": "Janssens Bakery was last contacted on 2026-07-02."}',
              '{"answer": "They want a chatbot for the webshop."}']
    adapter = ScriptedAdapter(script)
    parsed, trace, passed, failures, failed_checks = score_case(
        _AGENT, case, adapter, "scripted", _traj_tools())
    assert passed, failed_checks
    turn1_messages = adapter.seen_messages[-1]
    joined = " | ".join(m["content"] for m in turn1_messages)
    assert q1 in joined, joined[:400]
    assert "2026-07-02" in joined, \
        f"turn 1's call must see turn 0's tool result: {joined[:400]}"
    assert any(m["role"] == "assistant" and "2026-07-02" in m["content"]
              for m in turn1_messages), \
        f"turn 1's call must see turn 0's final answer as an assistant turn: {joined[:400]}"
    assert q2 in joined, joined[:400]


def main() -> int:
    tests = [v for k, v in sorted(globals().items())
            if k.startswith("test_") and callable(v)]
    for t in tests:
        print(f"running {t.__name__}")
        t()
        print(f"  PASS")
    print(f"\n{len(tests)} test groups; all passed (plain-assert script — a "
         f"failure would have halted above with a traceback)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
