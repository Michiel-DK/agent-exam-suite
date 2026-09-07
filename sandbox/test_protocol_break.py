#!/usr/bin/env python3
"""Effect tests for the R7 gap fix — no model, no server.

    python3 sandbox/test_protocol_break.py

THE GAP (R7, named in docs/probes/multiturn-ladder-2026-09-03/RESULTS.md). A model
that answers in prose instead of JSON makes `retry.extract_json` raise ValueError after
its re-ask; that exception escaped `_run_tool_loop`, `_run_turns` and `score_case`, and
landed at run_exam's case-level `except (ValueError, TypeError)` — which records
`got = {"error": ...}`, a lone `quality/error` check, and an EMPTY `detail`. Every
tool call, tool result, token count and (for a `turns` case) every OTHER turn's
verdict was wiped. Measured on the committed results before this lane: 3 of the 2B
champion's crm-followup records and 12 of the 4B's were wiped this way
(results/crm-followup__ollama__gemma4_e2b-it-qat.json, `check == "error"`), so the
ladder's "0/4" rows partly meant "the instrument cannot see inside the case".

THE FIX. The parse failure is handled at the SAME call boundary as a D2 death: the
loop stops, `parsed` is `{}` (so `answer_present` co-fires, exactly as it does for a
death), and the trace carries a `protocol_break` record — cause "unparseable", the
step it happened on, how many re-asks were spent, and the head of the raw text — while
everything gathered before it survives. `_score_one_turn` forces the verdict FALSE and
inserts ONE `format/unparseable` entry first. For a `turns` case the marker sits on
the turn that broke and the remaining turns still run and score. Verdicts are
unchanged by construction: a parse failure failed the case before and fails it now.

WHAT THIS FILE PINS. The first four groups were seen RED on master before the fix
(gotcha 2; 16 of 38 assertions — a raw ValueError out of live, `detail.turns` None,
a cycling tool loop instead of a stop, no `.raw` on the exception). The last two are
INVARIANT GUARDS, green on master by design — they exist so a later change cannot
widen the marker or move the plain-mode boundary, not as witnesses of the fix.

  SINGLE-TURN. One good tool call, then prose twice: the case FAILS, `detail` keeps
      the tool evidence, `detail.protocol_break.cause == "unparseable"`, the failed
      call's usage is METERED (no longer an unmetered case), failed_checks opens with
      `format/unparseable` and still carries `answer_present` (declared co-firing).
  MULTI-TURN. Turn 0 prose, turn 1 a clean JSON answer: `detail.turns` has BOTH
      entries, turn 0 carries the marker and turn 1 PASSES; every failed_checks entry
      names turn 0. Before the fix `detail == {}`.
  LIVE. A tier-0 that answers in prose now ESCALATES to tier 1 (it used to propagate
      a raw ValueError and forfeit the fallback — declared in the pre-lane docstring);
      a prose answer on the LAST tier is flagged and `cmd_live` exits 2.
  RETRY. `call_with_retry` still spends exactly its parse re-asks (2 calls) and the
      raised exception carries the raw text and the last call's meta.
  -- invariant guards, green before and after --
  ISOLATION (gotcha 3). The marker fires ONLY on a parse failure: a JSON object that
      is neither tool nor answer (the pre-existing protocol-violation branch) and a
      D2 death both carry NO `protocol_break` key; a healthy trace keeps its literal
      key set. `format/unparseable` is never the SOLE entry: `answer_present`
      co-fires whenever parsed is {}, the same declared co-firing D2 has in
      trajectory mode (sandbox/test_termination.py:796) — the isolation claim is
      "exactly one NEW entry, and only on this input", asserted in the boundary test.
  UNCHANGED. Plain mode (no tool loop) still records `quality/error` — that boundary
      is not this lane's; `extract_json`'s message is unchanged.

Plain asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402
from retry import ParseFailure, call_with_retry, extract_json  # noqa: E402
from router import TerminationError  # noqa: E402
from runner import (ROOT, _load_module, load_exam, run_exam,  # noqa: E402
                    run_trajectory_case)

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


class _ScriptedAdapter:
    """Same shape as sandbox/test_termination.py's: replays outputs, raises Exception
    entries, cycles when exhausted (a loop bug is caught by call count, not IndexError)."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.seen: list = []

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        out = self.outputs[len(self.seen) % len(self.outputs)]
        self.seen.append([dict(m) for m in messages])
        if isinstance(out, Exception):
            raise out
        return out, {"prompt_tokens": 10, "completion_tokens": 40,
                     "total_tokens": 50, "content_chars": len(out),
                     "reasoning_chars": 0, "finish_reason": "stop"}


AGENT = {"system_prompt": "test", "temperature": 0.0, "max_tokens": 512}
TOOL = '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}'
ANSWER = '{"answer": "Janssens Bakery was last contacted on 2026-07-02."}'
PROSE = ("Janssens Bakery has one open deal:\n*   **Deal:** Webshop chatbot\n"
         "*   **Amount:** EUR 6,500")   # the 2B's real failure shape, no `{` anywhere

SINGLE = {"id": "single-prose", "split": "train",
          "input": "When did we last talk to Janssens Bakery?",
          "expected": {"tools_called": ["crm_lookup"],
                       "answer_contains": ["2026-07-02"], "max_steps": 4}}


def _tools():
    return _load_module(ROOT / "evals" / "crm-followup" / "tools_mock.py",
                        "tools_mock_protocol_break_test")


def _names(case):
    return [f["check"] for f in case.get("failed_checks", [])]


def _run(exam_cases, script):
    """The REAL run_exam on the REAL crm-followup agent with a scripted adapter."""
    exam = {**load_exam("crm-followup"), "cases": exam_cases}
    ad = _ScriptedAdapter(script)
    saved = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: ad
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(runner.load_agent("crm-followup"), exam, "ollama", "s")
    finally:
        runner.adapter_for = saved
    return result, ad


# ------------------------------------------------------------ retry.py contract

def test_retry_raises_ParseFailure_carrying_raw_and_meta_after_its_reasks():
    calls = []

    def call_fn():
        calls.append(1)
        return PROSE, {"completion_tokens": 40, "finish_reason": "stop"}

    try:
        call_with_retry(call_fn, extract_json, sleep=lambda _s: None)
    except ParseFailure as exc:
        check("retry: ParseFailure is a ValueError (every existing `except ValueError` "
              "still catches it)", isinstance(exc, ValueError))
        check("retry: carries the raw text", exc.raw == PROSE, repr(exc.raw)[:80])
        check("retry: carries the last call's meta",
              exc.meta == {"completion_tokens": 40, "finish_reason": "stop"},
              str(exc.meta))
        check("retry: attempts = the 2 parse re-asks, unchanged",
              exc.attempts == 2 and len(calls) == 2, f"{exc.attempts}/{len(calls)}")
    else:
        check("retry: a prose reply still raises after the re-asks", False)


def test_extract_json_still_raises_a_plain_ValueError_shape():
    try:
        extract_json(PROSE)
    except ValueError as exc:
        check("extract_json: message unchanged", "no JSON object found" in str(exc),
              str(exc))
    else:
        check("extract_json raises on prose", False)


# ----------------------------------------------------------- single-turn loop

def test_single_turn_prose_keeps_the_evidence_and_meters_the_call():
    parsed, trace = run_trajectory_case(AGENT, SINGLE, _ScriptedAdapter([TOOL, PROSE, PROSE]),
                                        "s", _tools())
    check("single: parsed is {} — nothing scorable came back", parsed == {}, str(parsed))
    pb = trace.get("protocol_break")
    check("single: trace carries protocol_break cause=unparseable",
          (pb or {}).get("cause") == "unparseable", str(pb))
    check("single: the marker names the step and the re-asks spent",
          pb and pb["step"] == 1 and pb["retries"] == 1, str(pb))
    check("single: the marker carries the head of the raw text, bounded",
          pb and pb["raw_head"] == PROSE[:200] and len(pb["raw_head"]) <= 200, str(pb))
    check("single: the tool call made BEFORE the break survives",
          trace["tools_called"] == ["crm_lookup"] and len(trace["tool_results"]) == 1,
          str(trace))
    check("single: steps counts the broken turn as a real model turn",
          trace["steps"] == 2, str(trace["steps"]))
    check("single: the failed call is METERED — completion_tokens sums both calls",
          trace["metrics"]["completion_tokens"] == 80, str(trace["metrics"]))
    check("single: retries folded into metrics like a successful re-ask would be",
          trace["metrics"]["retries"] == 1, str(trace["metrics"]))


def test_console_line_names_the_break_and_stores_nothing_extra():
    """Console only (mirrors test_termination's console test): the operator reading a
    `check` run sees WHY the case failed; the record itself gains no extra key."""
    exam = {**load_exam("crm-followup"), "cases": [SINGLE, MULTI]}
    ad = _ScriptedAdapter([TOOL, PROSE, PROSE, TOOL, PROSE, PROSE, CONTACT])
    saved = runner.adapter_for
    out = io.StringIO()
    try:
        runner.adapter_for = lambda *a, **k: ad
        with contextlib.redirect_stdout(out):
            result = run_exam(runner.load_agent("crm-followup"), exam, "ollama", "s")
    finally:
        runner.adapter_for = saved
    lines = [l for l in out.getvalue().splitlines() if "[FAIL]" in l]
    check("console: single-turn line says unparseable + the raw head",
          any("single-prose" in l and "unparseable: 'Janssens Bakery has one" in l
              for l in lines), "\n".join(lines))
    check("console: multi-turn line names the turn",
          any("multi-prose" in l and "unparseable turn 0:" in l for l in lines),
          "\n".join(lines))
    keys = set(result["cases"][0])
    check("console: the record carries no console-only key",
          keys <= {"id", "split", "passed", "expected", "got", "failures",
                   "failed_checks", "detail"}, str(sorted(keys)))


def test_single_turn_case_boundary_records_format_unparseable_first():
    result, ad = _run([SINGLE], [TOOL, PROSE, PROSE])
    case = result["cases"][0]
    names = _names(case)
    check("boundary: case FAILS", case["passed"] is False)
    check("boundary: NOT the wiped `error` record any more", names != ["error"], str(names))
    check("boundary: format/unparseable is FIRST, answer_present co-fires (declared)",
          names[0] == "unparseable" and "answer_present" in names, str(names))
    check("boundary: the entry carries the format bucket",
          {"bucket": "format", "check": "unparseable"} in case["failed_checks"],
          str(case["failed_checks"]))
    check("boundary: got is {} — no placeholder, no error string masquerading as output",
          case["got"] == {}, str(case["got"]))
    check("boundary: detail keeps tools_called + the marker",
          case["detail"].get("tools_called") == ["crm_lookup"]
          and case["detail"].get("protocol_break", {}).get("cause") == "unparseable",
          str(case.get("detail")))
    totals = result["metrics_totals"]
    check("boundary: the case is metered — totals stay complete",
          totals.get("complete") is not False and not totals.get("unmetered_cases"),
          str(totals))
    check("boundary: 3 model calls — tool, prose, one re-ask", len(ad.seen) == 3,
          str(len(ad.seen)))


# --------------------------------------------------------------- multi-turn

MULTI = {"id": "multi-prose", "split": "heldout", "input": "",
         "turns": ["When did we last talk to Janssens Bakery?",
                   "And who is our contact there?"],
         "turns_expected": [
             {"turn": "When did we last talk to Janssens Bakery?",
              "expected": {"tools_called": ["crm_lookup"],
                           "answer_contains": ["2026-07-02"], "max_steps": 4}},
             {"turn": "And who is our contact there?",
              "expected": {"answer_contains": ["Sofie"], "max_steps": 4}}],
         "expected": {}}
CONTACT = '{"answer": "Your contact at Janssens Bakery is Sofie Janssens."}'


def test_multi_turn_break_on_turn0_does_not_wipe_turn1():
    # turn 0: tool, prose, prose(re-ask) -> break; turn 1: answer (contact fetched in t0)
    result, ad = _run([MULTI], [TOOL, PROSE, PROSE, CONTACT])
    case = result["cases"][0]
    turns = (case.get("detail") or {}).get("turns")
    check("multi: detail.turns exists with BOTH turns (was {} — the wipe)",
          isinstance(turns, list) and len(turns) == 2, str(case.get("detail")))
    if not turns or len(turns) != 2:
        return
    check("multi: turn 0 carries the marker",
          turns[0].get("protocol_break", {}).get("cause") == "unparseable", str(turns[0]))
    check("multi: turn 0 failed, turn 1 PASSED — the later turn still ran and scored",
          turns[0]["passed"] is False and turns[1]["passed"] is True, str(turns))
    check("multi: turn 1 carries no marker", "protocol_break" not in turns[1],
          str(turns[1]))
    check("multi: the case still FAILS (per-turn conjunction)", case["passed"] is False)
    check("multi: every failed_checks entry names turn 0",
          case["failed_checks"] and all(f.get("turn") == 0 for f in case["failed_checks"]),
          str(case["failed_checks"]))
    check("multi: format/unparseable first, with its turn",
          case["failed_checks"][0] == {"bucket": "format", "check": "unparseable", "turn": 0},
          str(case["failed_checks"][0]))
    check("multi: 4 model calls — tool, prose, re-ask, then turn 1's answer",
          len(ad.seen) == 4, str(len(ad.seen)))
    hist = ad.seen[3]
    check("multi: turn 1 saw the prose as the assistant's turn-0 answer (faithful history)",
          any(m["role"] == "assistant" and m["content"] == PROSE for m in hist),
          str([m["role"] for m in hist]))
    # 3 metered calls (tool, the FINAL prose call, turn 1's answer): a re-ask
    # reports only its last call's usage, the same convention as a successful
    # re-ask; the spend shows up as retries, not as a second usage row.
    check("multi: case-level metrics include the broken turn's tokens",
          case["detail"]["metrics"]["completion_tokens"] == 120
          and case["detail"]["metrics"]["retries"] == 1,
          str(case["detail"]["metrics"]))


# --------------------------------------------------------------- isolation

def test_isolation_marker_fires_only_on_a_parse_failure():
    # (a) valid JSON that is neither tool nor answer: the pre-existing branch, no marker
    _p, trace = run_trajectory_case(AGENT, SINGLE, _ScriptedAdapter(['{"foo": 1}']),
                                    "s", _tools())
    check("isolation: neither-tool-nor-answer JSON carries NO protocol_break",
          "protocol_break" not in trace, str(sorted(trace)))
    # (b) a D2 death: termination, not protocol_break
    death = TerminationError("x", {"finish_reason": "length", "completion_tokens": 0,
                                   "content_chars": 0, "reasoning_chars": 0})
    _p, trace = run_trajectory_case(AGENT, SINGLE, _ScriptedAdapter([TOOL, death]),
                                    "s", _tools())
    check("isolation: a death carries termination and NO protocol_break",
          "termination" in trace and "protocol_break" not in trace, str(sorted(trace)))
    # (c) healthy: literal key set unchanged (the byte-identity invariant)
    _p, trace = run_trajectory_case(AGENT, SINGLE, _ScriptedAdapter([TOOL, ANSWER]),
                                    "s", _tools())
    check("isolation: healthy trace key set is literally the master set",
          set(trace) == {"tools_called", "tool_calls", "tool_results", "steps", "metrics"},
          str(sorted(trace)))


def test_plain_mode_parse_failure_is_UNCHANGED_still_error():
    exam = {**load_exam("reply-draft"), "cases": [load_exam("reply-draft")["cases"][0]]}
    ad = _ScriptedAdapter([PROSE])
    saved = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: ad
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(runner.load_agent("reply-draft"), exam, "ollama", "s")
    finally:
        runner.adapter_for = saved
    case = result["cases"][0]
    check("plain: still FAILS as quality/error (not this lane's boundary)",
          case["passed"] is False and _names(case) == ["error"], str(_names(case)))
    check("plain: got carries the error string, as before",
          "error" in case["got"], str(case["got"]))


# --------------------------------------------------------------------- live

class _TierAdapter:
    def __init__(self, by_model):
        self.by_model = {m: list(v) for m, v in by_model.items()}
        self.calls: list = []

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        self.calls.append(model)
        out = self.by_model[model].pop(0)
        return out, {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
                     "content_chars": len(out), "reasoning_chars": 0, "finish_reason": "stop"}


@contextlib.contextmanager
def _routes(table, adapter):
    scratch = ROOT / "results" / "_test_protocol_break"
    scratch.mkdir(parents=True, exist_ok=True)
    path = scratch / "routes.yaml"
    path.write_text(yaml.safe_dump(table))
    saved = (runner.ROUTES_PATH, runner.adapter_for)
    runner.ROUTES_PATH, runner.adapter_for = path, (lambda *a, **k: adapter)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        runner.ROUTES_PATH, runner.adapter_for = saved


def test_live_prose_on_tier0_escalates_and_prose_on_the_last_tier_exits_2():
    table = {"crm-followup": [{"provider": "ollama", "model": "t0"},
                              {"provider": "ollama", "model": "t1"}]}
    q = "When did we last talk to Janssens Bakery?"
    # tier 0 answers in prose (twice: the re-ask), tier 1 answers properly
    ad = _TierAdapter({"t0": [PROSE, PROSE], "t1": [TOOL, ANSWER]})
    with _routes(table, ad):
        entry, record = runner.live_run_and_log("crm-followup", q, log=False)
    check("live: tier 0 spent its re-ask then ESCALATED to tier 1 (was: raw ValueError)",
          ad.calls == ["t0", "t0", "t1", "t1"], str(ad.calls))
    check("live: the answer came from tier 1", entry["model"] == "t1", str(entry["model"]))
    a0 = record["attempts"][0]
    check("live: attempt 0 names answer_present among its failed checks",
          "answer_present" in json.dumps(a0.get("checks_failed", [])) or
          any("no final answer" in c for c in a0.get("checks_failed", [])), str(a0))
    check("live: attempt 0 carries the marker for the reader",
          a0.get("protocol_break", {}).get("cause") == "unparseable", str(a0))
    check("live: the final record is clean", "checks_failed" not in record, str(record))
    # every tier prose -> flagged, exit 2 through cmd_live
    ad2 = _TierAdapter({"t0": [PROSE, PROSE], "t1": [PROSE, PROSE]})
    with _routes(table, ad2):
        args = type("A", (), {"agent": "crm-followup", "input": q, "provider": None,
                              "model": None})()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = runner.cmd_live(args)
    check("live: prose on EVERY tier exits 2 (flagged, never clean)", rc == 2, str(rc))
    check("live: and says so on stderr", "failed live output checks" in err.getvalue(),
          err.getvalue()[:200])


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"\n{name}")
            try:
                fn()
            except Exception as exc:   # one crashing test must not hide the others
                check(f"{name} raised {type(exc).__name__}", False, str(exc)[:160])
    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}):")
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("all protocol-break tests passed")
