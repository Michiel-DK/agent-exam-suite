#!/usr/bin/env python3
"""Effect tests for the gate-0 --dedupe-tools intervention — no model, no server.

    python3 sandbox/test_dedupe_tools.py

The redundancy monitor GRADES a repeated tool call post-hoc. `--dedupe-tools` is the
runtime half: it suppresses the repeat live, so the gate-0 A/B has an on/off switch to
measure. What this file pins, in both directions (gotcha 2 — a green guard proves
nothing until seen RED):

  1. guard OFF: a duplicate-emitting script lands the duplicate in trace["tool_calls"]
     and score_trajectory fails with the redundancy string. The RED side, seen.
  2. guard ON, byte-identical script: no duplicate in tool_calls, exactly one entry in
     trace["deduped_calls"], the tool executed ONCE, the case passes.
  3. guard ON, different-args control: both calls execute, deduped_calls empty — the
     intervention must never eat a legitimate multi-lookup.
  4. the CLI default really is off — asserted by driving `runner.main()` with argv
     (argparse -> cmd_run -> run_exam -> run_trajectory_case, the whole plumbing),
     NOT by reading the argparse default (gotcha 1: presence is not effect).

Pass 2 (brief amendment 1, after the four-reviewer round-trip) adds the three
invariants that pass 1 got wrong or proved vacuously:

  5. A1 — a suppressed duplicate CHARGES its step: same scripted model => the SAME
     number of real generate() calls with the guard on and off.
  6. A2 — a RAISING execution is never cached, so an identical retry after an error
     re-executes and stays fully graded (redundancy AND error_recovery's spiralled
     clause); a returned error-shaped dict without a raise stays dedupe-eligible.
  7. A4 — with the flag off the trace carries master's exact 5-key set, asserted
     against a literal fixture rather than against the new code.
  8. A5 — the CLI wiring is asserted by the VALUE that reaches run_exam on run,
     check and diff, not by `--help` text (unwiring two of them failed no assertion).

Everything runs through the REAL loop entry point (`run_trajectory_case`) against the
REAL evals/crm-followup/tools_mock.py fixture; only the model is scripted. Plain
asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402
from runner import (ROOT, _load_module, run_trajectory_case,  # noqa: E402
                    score_trajectory)

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


class ScriptedAdapter:
    """Replays a fixed sequence of model outputs — deterministic tool-loop driver.

    CYCLES rather than raising when the script runs out, because a real model never
    runs out of things to say. A loop bug that makes MORE calls than the script has
    lines must be caught by the call-count assertion that is looking for it, not
    disguised as an IndexError from the test's own fixture. (Verified: with the
    pass-1 step refund reintroduced, this is the difference between the A1 assertion
    reporting off=5 on=7 and the suite dying in the adapter.)

    len(seen_messages) is the number of real generate() calls."""

    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.seen_messages: list[list[dict]] = []

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        out = self.outputs[len(self.seen_messages) % len(self.outputs)]
        self.seen_messages.append([dict(m) for m in messages])
        return out, {"prompt_tokens": None, "completion_tokens": None,
                     "total_tokens": None}


class CountingTools:
    """The crm-followup fixture, wrapped to count how many times each tool actually
    RAN. The dedupe guard's core promise is 'do not re-execute' — a trace without the
    duplicate proves the bookkeeping, this proves the tool was really not called."""

    def __init__(self):
        self._mod = _load_module(ROOT / "evals" / "crm-followup" / "tools_mock.py",
                                 "tools_mock_dedupe_test")
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        fn = getattr(self._mod, name)

        def wrapped(**kwargs):
            self.calls.append((name, tuple(sorted(kwargs.items()))))
            return fn(**kwargs)
        return wrapped


# AMENDMENT 4: the trace key set master emits, written out as a LITERAL fixture —
# transcribed from the pre-intervention `return parsed, {...}` in run_trajectory_case,
# deliberately NOT derived from the new code (a set built from the runner would agree
# with the runner no matter what the runner did). Flag-off byte-identity means this
# exact set, with no `deduped_calls` in it. Pass 1 emitted 6 keys where master has 5.
_MASTER_TRACE_KEYS = {"tools_called", "tool_calls", "tool_results", "steps", "metrics"}

_DUP_SCRIPT = [
    '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
    '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
    '{"answer": "Janssens Bakery was last contacted on 2026-07-02."}',
]
_CASE = {"input": "When did we last talk to Janssens Bakery?",
         "expected": {"tools_called": ["crm_lookup"],
                      "answer_contains": ["2026-07-02"], "max_steps": 4}}


def _run(script, dedupe, case=None):
    case = case or _CASE
    tools = CountingTools()
    agent = {"system_prompt": "test", "temperature": 0.0, "max_tokens": 512}
    parsed, trace = run_trajectory_case(agent, case, ScriptedAdapter(script),
                                        "scripted", tools, dedupe_tools=dedupe)
    return parsed, trace, tools


# ------------------------------------------------------------------ 1: RED side

def test_guard_off_duplicate_is_red():
    """Without the flag the duplicate survives into the trace and the monitor fires.
    This is the failure the four committed exposure cases reproduce with a real
    model; here it is pinned deterministically."""
    parsed, trace, tools = _run(_DUP_SCRIPT, dedupe=False)
    check("guard off: both calls land in tool_calls", len(trace["tool_calls"]) == 2,
          str(trace["tool_calls"]))
    check("guard off: the tool really executed twice", len(tools.calls) == 2,
          str(tools.calls))
    check("guard off: no deduped_calls key exists at all",
          "deduped_calls" not in trace, str(sorted(trace)))
    ok, failures = score_trajectory(parsed, trace, _CASE["expected"], _CASE["input"])
    check("guard off: case FAILS", not ok)
    check("guard off: redundancy is the SOLE failure",
          len(failures) == 1 and failures[0].startswith("redundant tool call: "),
          "; ".join(failures))


# ----------------------------------------------------------------- 2: GREEN side

def test_guard_on_same_script_is_green():
    """Same script, flag on: the repeat is served from cache, never re-executed,
    kept out of tool_calls (so the monitor cannot fire) and recorded in
    deduped_calls so the A/B can count exposure."""
    parsed, trace, tools = _run(_DUP_SCRIPT, dedupe=True)
    check("guard on: tool_calls holds ONE call", len(trace["tool_calls"]) == 1,
          str(trace["tool_calls"]))
    check("guard on: the tool executed once", len(tools.calls) == 1, str(tools.calls))
    check("guard on: deduped_calls has exactly one entry",
          trace["deduped_calls"] == [{"tool": "crm_lookup",
                                      "args": {"company": "Janssens Bakery"}}],
          str(trace["deduped_calls"]))
    check("guard on: steps counts the suppressed turn too, so it stays comparable "
          "with the guard-off run of the same script (steps == 3)",
          trace["steps"] == 3, str(trace["steps"]))
    check("guard on: the model still answered", "answer" in parsed, str(parsed))
    ok, failures = score_trajectory(parsed, trace, _CASE["expected"], _CASE["input"])
    check("guard on: case PASSES on the input that was RED", ok, "; ".join(failures))


def test_cached_result_is_fed_back_to_the_model():
    """The suppressed call must still produce a tool_result turn, carrying the FIRST
    execution's value — a model that gets silence instead of its retry's answer would
    derail, and the intervention would be measuring derailment rather than dedupe.

    The tool is made stateful (each execution stamps its own sequence number) so the
    assertion can tell 'served from cache' apart from 'ran again and happened to
    return the same thing' — with the deterministic fixture those are indistinguishable,
    which would make this check unfalsifiable."""
    class SeqTools(CountingTools):
        def crm_lookup(self, **kwargs):  # noqa: D401 — mirrors the fixture signature
            self.calls.append(("crm_lookup", tuple(sorted(kwargs.items()))))
            return {**self._mod.crm_lookup(**kwargs), "call_seq": len(self.calls)}

    agent = {"system_prompt": "test", "temperature": 0.0, "max_tokens": 512}
    for dedupe, expect_seq in ((True, 1), (False, 2)):
        tools = SeqTools()
        adapter = ScriptedAdapter(_DUP_SCRIPT)
        run_trajectory_case(agent, _CASE, adapter, "scripted", tools,
                            dedupe_tools=dedupe)
        third = adapter.seen_messages[2]  # what the model saw before answering
        label = "on" if dedupe else "off"
        check(f"guard {label}: model sees a tool_result after the repeat",
              len(third) == 6 and "Sofie Janssens" in third[-1]["content"],
              str(third[-1])[:160])
        check(f"guard {label}: that result is call_seq {expect_seq}"
              + (" (the CACHED first execution)" if dedupe else " (a re-execution)"),
              f'"call_seq": {expect_seq}' in third[-1]["content"],
              str(third[-1])[:200])


# --------------------------------------------------------------- 3: NOT-too-eager

def test_guard_on_different_args_both_execute():
    """A legitimate multi-lookup (two companies) must be untouched by the guard."""
    case = {"input": "Compare Janssens Bakery and Devos Garage.",
            "expected": {"tools_called": ["crm_lookup"], "max_steps": 4}}
    _parsed, trace, tools = _run([
        '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
        '{"tool": "crm_lookup", "args": {"company": "Devos Garage"}}',
        '{"answer": "Sofie Janssens and Jan De Vos."}',
    ], dedupe=True, case=case)
    check("guard on: different args -> both calls in tool_calls",
          len(trace["tool_calls"]) == 2, str(trace["tool_calls"]))
    check("guard on: different args -> both tools executed", len(tools.calls) == 2,
          str(tools.calls))
    check("guard on: different args -> deduped_calls empty",
          trace["deduped_calls"] == [], str(trace["deduped_calls"]))


def test_declared_gap_case_variant_slips_past_both_sides():
    """DECLARED GAP, pinned so it cannot be closed by accident on one side only.

    The dedupe key is raw args — 'Janssens Bakery' and 'janssens bakery' are two
    different calls to both the monitor and the guard, even though tools_mock._norm
    lowercases them into the same lookup. Unfixed by decision (gate-0 lane brief,
    2026-08-26, out of scope). The point of asserting it: monitor and guard must
    agree about what a duplicate IS, or the A/B's two sides measure different things.
    If someone normalizes one of them, this test goes red and forces the other."""
    script = [
        '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
        '{"tool": "crm_lookup", "args": {"company": "janssens bakery"}}',
        '{"answer": "Janssens Bakery was last contacted on 2026-07-02."}',
    ]
    parsed, trace, tools = _run(script, dedupe=True)
    check("declared gap: case-variant repeat is NOT suppressed by the guard",
          trace["deduped_calls"] == [] and len(trace["tool_calls"]) == 2
          and len(tools.calls) == 2, str(trace["deduped_calls"]))
    _p, off_trace, _t = _run(script, dedupe=False)
    ok, failures = score_trajectory(parsed, off_trace, _CASE["expected"],
                                    _CASE["input"])
    check("declared gap: the monitor does not grade it either (same key, so the "
          "A/B's two sides agree)", ok, "; ".join(failures))


def test_same_model_calls_guard_on_and_off():
    """AMENDMENT 1's invariant. A suppressed duplicate is still a real model turn and
    must charge its step: for the SAME scripted model, guard ON and guard OFF make the
    same number of generate() calls. Pass 1 refunded the step, which let a guard-ON run
    make more real calls than its advertised ceiling (measured: 7 against a ceiling of
    5 under alternating keys) — the A/B's two sides then were not running on the same
    budget, which is the comparison gate 0 exists to make.

    Three scripts, including the alternating-key interleaving that exposed it, and one
    that never answers (the worst case for a budget bug).

    Note on what each assertion can catch. Equality alone compares two values produced
    by the same code path, so a budget bug that shifts BOTH sides moves right past it
    (mutation M16: `range(max_steps - 1)` survived the entire suite). The never-answers
    script therefore also pins an ABSOLUTE expected count, and the same run's trace and
    execution count are asserted — that repeats-forever run is the only place where
    'the cache keeps serving' and 'the tool never runs again' are distinguishable from
    a single-repeat script (mutations: a cache served with .pop(), and a guard that
    suppresses only the FIRST repeat, both survived without it)."""
    dup = '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}'
    other = '{"tool": "crm_lookup", "args": {"company": "Devos Garage"}}'
    answer = '{"answer": "Sofie Janssens, 2026-07-02."}'
    scripts = {
        # label: (script, max_steps, exact expected generate() calls)
        "duplicate-then-answer": ([dup, dup, answer], 4, 3),
        "alternating-keys": ([dup, other, dup, other, dup, other, answer], 5, 5),
        "never-answers": ([dup] * 12, 4, 4),
    }
    seen: dict = {}
    for label, (script, max_steps, exact) in scripts.items():
        case = {"input": "x", "expected": {"max_steps": max_steps}}
        counts, traces, execs = {}, {}, {}
        for dedupe in (False, True):
            adapter = ScriptedAdapter(list(script))
            agent = {"system_prompt": "test", "temperature": 0.0, "max_tokens": 512}
            tools = CountingTools()
            _parsed, trace = run_trajectory_case(agent, case, adapter, "scripted",
                                                 tools, dedupe_tools=dedupe)
            counts[dedupe] = len(adapter.seen_messages)  # one entry per generate()
            traces[dedupe], execs[dedupe] = trace, len(tools.calls)
        check(f"equal model calls ON vs OFF ({label})", counts[False] == counts[True],
              f"off={counts[False]} on={counts[True]}")
        # ABSOLUTE count, not just equality: a budget bug that moves both sides
        # together is invisible to an equality check between two same-path values.
        check(f"exact model-call count ({label}): {exact}",
              counts[True] == exact and counts[False] == exact,
              f"off={counts[False]} on={counts[True]} expected={exact}")
        # steps must be comparable across the A/B: a suppressed turn still counts.
        check(f"steps identical ON vs OFF ({label})",
              traces[False]["steps"] == traces[True]["steps"],
              f'off={traces[False]["steps"]} on={traces[True]["steps"]}')
        seen[label] = (traces[True], execs[True])

    # The repeats-forever run under the guard: the cache must keep serving every
    # repeat (not just the first, and not be consumed by the first), and the tool must
    # never run a second time.
    trace, executions = seen["never-answers"]
    check("never-answers guard ON: the tool executed exactly ONCE", executions == 1,
          f"{executions} executions")
    check("never-answers guard ON: tool_calls holds exactly one entry",
          len(trace["tool_calls"]) == 1, str(trace["tool_calls"]))
    check("never-answers guard ON: all 3 later repeats were suppressed",
          len(trace["deduped_calls"]) == 3, str(trace["deduped_calls"]))


def test_a_raising_execution_is_never_deduped():
    """AMENDMENT 2, direction (a). The cache may only serve results of executions that
    did NOT raise. crm_lookup RAISES for Peeters Logistics (tools_mock _BACKEND_DOWN),
    and five committed error_recovery cases sit on that fixture. With the error cached,
    an identical retry after a failure was suppressed — which made error_recovery's
    'spiralled' clause dead code under guard ON and retry-then-recover structurally
    impossible. An intervention may not make an existing check unfireable.

    Guard ON on a raise-then-identical-retry must be indistinguishable from guard OFF:
    two executions, and BOTH the redundancy failure and the spiralled failure present."""
    case = {"input": "Who is our contact at Peeters Logistics?",
            "expected": {"tools_called": ["crm_lookup"], "max_steps": 4,
                         "error_recovery": {"tool": "crm_lookup",
                                            "fact": ["contact", "name", "crm",
                                                     "record"]}}}
    script = [
        '{"tool": "crm_lookup", "args": {"company": "Peeters Logistics"}}',
        '{"tool": "crm_lookup", "args": {"company": "Peeters Logistics"}}',
        '{"answer": "The CRM record could not be retrieved, so I do not have the '
        'contact name."}',
    ]
    for dedupe in (True, False):
        label = "on" if dedupe else "off"
        parsed, trace, tools = _run(script, dedupe=dedupe, case=case)
        check(f"guard {label}: the raising tool executed BOTH times",
              len(tools.calls) == 2, str(tools.calls))
        check(f"guard {label}: nothing was suppressed",
              trace.get("deduped_calls", []) == [],
              str(trace.get("deduped_calls")))
        check(f"guard {label}: the retry is still in tool_calls for grading",
              len(trace["tool_calls"]) == 2, str(trace["tool_calls"]))
        _ok, failures = score_trajectory(parsed, trace, case["expected"],
                                         case["input"])
        check(f"guard {label}: redundancy still fires",
              any(f.startswith("redundant tool call: ") for f in failures),
              "; ".join(failures))
        check(f"guard {label}: error_recovery 'spiralled' still fires",
              any("spiralled" in f for f in failures), "; ".join(failures))


def test_repeated_unknown_tool_is_identical_on_and_off():
    """An unknown tool is NOT an execution, so it is never cached and the guard must
    leave a repeated unknown-tool call completely alone — identical executions,
    identical failure strings, nothing suppressed, on both sides.

    The runner's comment said so; nothing tested it, and a mutation that made the
    unknown-tool branch cacheable survived the whole suite. It matters because the
    synthesized {"error": "unknown tool ..."} is a runner artifact, not a tool return:
    caching it would let the guard hide a repeated bad tool pick from the monitor."""
    case = {"input": "x", "expected": {"max_steps": 4}}
    script = [
        '{"tool": "no_such_tool", "args": {"company": "Janssens Bakery"}}',
        '{"tool": "no_such_tool", "args": {"company": "Janssens Bakery"}}',
        '{"answer": "I could not look that up."}',
    ]
    outcomes = {}
    for dedupe in (True, False):
        label = "on" if dedupe else "off"
        parsed, trace, tools = _run(script, dedupe=dedupe, case=case)
        _ok, failures = score_trajectory(parsed, trace, case["expected"],
                                         case["input"])
        check(f"unknown tool, guard {label}: no real tool executed",
              len(tools.calls) == 0, str(tools.calls))
        check(f"unknown tool, guard {label}: both attempts stay in tool_calls",
              len(trace["tool_calls"]) == 2, str(trace["tool_calls"]))
        check(f"unknown tool, guard {label}: nothing was suppressed or cached",
              trace.get("deduped_calls", []) == [], str(trace.get("deduped_calls")))
        check(f"unknown tool, guard {label}: the repeat is still graded redundant",
              any(f.startswith("redundant tool call: ") for f in failures),
              "; ".join(failures))
        outcomes[dedupe] = (len(trace["tool_calls"]), sorted(failures),
                            trace["steps"])
    check("unknown tool: guard ON and OFF are indistinguishable",
          outcomes[True] == outcomes[False], f"{outcomes[True]} vs {outcomes[False]}")


def test_a_returned_error_dict_is_still_dedupe_eligible():
    """AMENDMENT 2, direction (b). The rule is about RAISING, not about the shape of
    the result: crm_lookup RETURNS {"error": "no CRM record..."} for an unknown company
    without raising, which is a normal result and stays dedupe-eligible. Without this
    side the A2 rule could be satisfied by never caching anything error-shaped, which
    would quietly disable the guard on every abstention case."""
    case = {"input": "What do we know about Maes Bikes?",
            "expected": {"tools_called": ["crm_lookup"], "max_steps": 4}}
    script = [
        '{"tool": "crm_lookup", "args": {"company": "Maes Bikes"}}',
        '{"tool": "crm_lookup", "args": {"company": "Maes Bikes"}}',
        '{"answer": "No CRM record for Maes Bikes."}',
    ]
    _parsed, trace, tools = _run(script, dedupe=True, case=case)
    check("no-record error dict (no raise): the repeat WAS suppressed",
          len(trace["deduped_calls"]) == 1 and len(trace["tool_calls"]) == 1,
          f"{trace['tool_calls']} / {trace['deduped_calls']}")
    check("no-record error dict (no raise): tool executed once", len(tools.calls) == 1,
          str(tools.calls))


def test_guard_off_is_inert_on_every_shape():
    """Regression fence for the committed gate: with the flag off, the loop's
    observable output is what it was before the intervention existed — same
    tool_calls, same tool_results, same steps, and master's exact trace key set (no
    deduped_calls key at all) — for a duplicate script, a different-args script, and a
    straight-to-answer script."""
    shapes = {
        "duplicate": (_DUP_SCRIPT, 2, 2),
        "different-args": ([
            '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
            '{"tool": "crm_lookup", "args": {"company": "Devos Garage"}}',
            '{"answer": "Sofie Janssens and Jan De Vos."}'], 2, 2),
        "no-tools": (['{"answer": "2026-07-02"}'], 0, 0),
    }
    for label, (script, n_calls, n_exec) in shapes.items():
        _parsed, trace, tools = _run(script, dedupe=False)
        check(f"guard off inert ({label}): tool_calls unchanged",
              len(trace["tool_calls"]) == n_calls, str(trace["tool_calls"]))
        check(f"guard off inert ({label}): executions unchanged",
              len(tools.calls) == n_exec, str(tools.calls))
        check(f"guard off inert ({label}): steps == len(tools_called) + 1",
              trace["steps"] == len(trace["tools_called"]) + 1, str(trace["steps"]))
        check(f"guard off inert ({label}): trace keys are master's exact set",
              set(trace) == _MASTER_TRACE_KEYS, str(sorted(trace)))


# ---------------------------------------------------- 4: the CLI default, for real

class _DupEverywhereAdapter:
    """Emits the same duplicate pattern for EVERY case of a whole exam run: two
    identical crm_lookup calls, then an answer. Position is derived from the message
    history, so one instance serves every case."""

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        step = (len(messages) - 2) // 2
        out = ('{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}'
               if step < 2 else
               '{"answer": "Janssens Bakery was last contacted on 2026-07-02."}')
        return out, {"prompt_tokens": None, "completion_tokens": None,
                     "total_tokens": None}


def _cli_run(argv: list[str]) -> dict:
    """Drive the CLI surface — sys.argv -> runner.main() -> cmd_run -> run_exam —
    with the MODEL faked at the adapter boundary and the results write suppressed.
    Everything between argparse and the tool loop is the real code path, which is the
    only way to prove what the default does (gotcha 1)."""
    captured: dict = {}
    real_adapter_for, real_save, real_argv = (runner.adapter_for, runner.save_result,
                                              sys.argv)
    try:
        runner.adapter_for = lambda *a, **k: _DupEverywhereAdapter()
        runner.save_result = lambda result: (captured.update(result),
                                             ROOT / "results" / "suppressed.json")[1]
        sys.argv = argv
        with contextlib.redirect_stdout(io.StringIO()):
            rc = runner.main()
    finally:
        runner.adapter_for, runner.save_result, sys.argv = (real_adapter_for,
                                                            real_save, real_argv)
    if rc != 0 or not captured:
        raise AssertionError(f"CLI run {argv} returned rc={rc}, captured={bool(captured)}")
    return captured


def _redundancy_cases(result: dict) -> list:
    """MULTITURN-EXAM R2 fix (pass 3, correcting pass 2's ACCURATE cause but
    FORBIDDEN fix): a turns-aware case's failed_checks entries carry a THIRD
    key, "turn" (criterion 2 — every failed_checks entry on the turns-aware
    path names its turn), so the pre-lane exact 2-key dict equality this helper
    used (`{"bucket": "quality", "check": "redundancy"} in
    c.get("failed_checks", [])`) never matches a turns-case's entry even when
    the redundancy check fired exactly as it always has — pass 2's own
    diagnosis of the ORIGINAL bug proved this by running this file with the 4
    new multi-turn cases removed from evals/crm-followup/cases.json (13 test
    groups; 0 failed assertions with them out, 1 with them in, same scripted
    model both times); that specific experiment predates this pass's
    exact-shape fix and was not rerun here (the predicate it was diagnosing
    no longer exists to reproduce against). The redundancy BEHAVIOR is
    unchanged; only this helper's shape assumption was stale.

    Pass 2's fix (subset-match on bucket+check alone, ignoring any other key)
    was flagged by the pass-3 adversarial round as a FORBIDDEN predicate
    loosening: it would also match a hypothetical malformed entry carrying
    EXTRA unexpected keys the runner never emits, which an exact-shape
    assertion is supposed to catch. The fix here keeps EXACT-SHAPE dict
    equality — no subset match — but is now AWARE of the two shapes that are
    both legitimate: the pre-existing 2-key {"bucket", "check"} shape for a
    non-turns case's entry (criterion 1/(9a) pin this shape byte-identical),
    and the 3-key {"bucket", "check", "turn"} shape criterion 2 mandates for a
    turns-case's entry. An entry matching NEITHER exact shape (any other key
    set at all) is a runner bug and must NOT be waved through as a match."""
    ids = []
    for c in result["cases"]:
        for f in c.get("failed_checks", []):
            is_redundancy = f.get("bucket") == "quality" and f.get("check") == "redundancy"
            shape_ok = set(f.keys()) in ({"bucket", "check"},
                                         {"bucket", "check", "turn"})
            if is_redundancy and shape_ok:
                ids.append(c["id"])
                break
    return ids


def _deduped_cases(result: dict) -> list:
    return [c["id"] for c in result["cases"]
            if c.get("detail", {}).get("deduped_calls")]


def test_cli_default_is_off():
    """No flag on the command line => the duplicate-emitting model stays RED. If the
    default ever flips, every committed snapshot silently changes meaning."""
    result = _cli_run(["runner.py", "run", "crm-followup"])
    red = _redundancy_cases(result)
    check("CLI without the flag: redundancy fires on every case",
          len(red) == len(result["cases"]), f"{len(red)}/{len(result['cases'])}: {red}")
    check("CLI without the flag: nothing was deduped", _deduped_cases(result) == [],
          str(_deduped_cases(result)))


def test_cli_flag_on_suppresses():
    """Same command plus --dedupe-tools => the same scripted model produces zero
    redundancy failures and a countable exposure figure in the results detail."""
    result = _cli_run(["runner.py", "run", "crm-followup", "--dedupe-tools"])
    red = _redundancy_cases(result)
    check("CLI with --dedupe-tools: no redundancy failure anywhere", red == [], str(red))
    check("CLI with --dedupe-tools: exposure counted on every case",
          len(_deduped_cases(result)) == len(result["cases"]),
          f"{len(_deduped_cases(result))}/{len(result['cases'])}")


class _StopAtRunExam(Exception):
    """Sentinel: the spy has recorded what it needed; unwind before any model call."""


def _dedupe_kwarg_seen_by_run_exam(argv: list[str]):
    """What `run_exam` was ACTUALLY passed for dedupe_tools when the CLI was invoked
    with these args. Spies at the run_exam boundary and aborts there, so no command
    needs a well-formed fake result and all three can be probed the same way."""
    seen: dict = {}
    real_run_exam, real_argv = runner.run_exam, sys.argv
    # SNAPSHOT-REPRODUCIBILITY: `check` now runs a pre-inference preflight (a live
    # /api/version call) and a native-API UNLOAD of the champion before run_exam.
    # Neither belongs in the deterministic gate: the version call makes this file red
    # whenever Ollama is down or bumped, and the unload would evict a model out from
    # under a snapshot run in flight in another shell (breaking its "one load"). Both
    # are stubbed here; their own behaviour is tested in test_snapshot_reproducibility.
    real_preflight, real_unload = runner.snapshot_preflight, runner.ollama_unload

    def spy(*_a, **kwargs):
        seen["dedupe_tools"] = kwargs.get("dedupe_tools", "<never passed>")
        raise _StopAtRunExam

    try:
        runner.run_exam = spy
        runner.snapshot_preflight = lambda *_a, **_k: None
        runner.ollama_unload = lambda *_a, **_k: None
        sys.argv = argv
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                runner.main()
            except _StopAtRunExam:
                pass
    finally:
        runner.run_exam, sys.argv = real_run_exam, real_argv
        runner.snapshot_preflight, runner.ollama_unload = real_preflight, real_unload
    return seen.get("dedupe_tools", "<run_exam never reached>")


def test_flag_reaches_run_exam_on_run_check_and_diff():
    """AMENDMENT 5: effect, not presence. Pass 1 proved `check` and `diff` wiring with
    `--help` text only — mutation testing unwired both with ZERO assertions failing,
    which is exactly the vacuous-green shape this repo keeps paying for. This asserts
    the VALUE that reaches run_exam, so an unwired command reports '<never passed>'
    and fails.

    `check` is included on purpose: the gate-0 A/B is 'run the committed gate both
    ways and diff', so it has to accept the flag."""
    for cmd in ("run", "check", "diff"):
        tail = ["--models", "gemma4:e4b-it-qat"] if cmd == "diff" else []
        off = _dedupe_kwarg_seen_by_run_exam(
            ["runner.py", cmd, "crm-followup"] + tail)
        on = _dedupe_kwarg_seen_by_run_exam(
            ["runner.py", cmd, "crm-followup", "--dedupe-tools"] + tail)
        check(f"`{cmd}` without the flag passes dedupe_tools=False", off is False,
              f"got {off!r}")
        check(f"`{cmd}` with --dedupe-tools passes dedupe_tools=True", on is True,
              f"got {on!r}")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        print(f"\n{t.__name__}")
        t()
    print(f"\n{len(tests)} test groups; {len(FAILED)} failed assertion(s)"
          + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
