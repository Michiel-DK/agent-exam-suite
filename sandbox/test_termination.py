#!/usr/bin/env python3
"""Effect tests for TERMINATION-DETECT — no model, no server.

    python3 sandbox/test_termination.py

WHAT THE LANE CHANGED. `router.py` used to substitute the model's `reasoning` text
whenever `content` came back empty, and `retry.extract_json` then returned the LAST
JSON object in that thinking prose — so a reasoning model that drafted its answer
object mid-thought and was cut off before ever answering was scored as if it had
answered. One committed HELDOUT case scored GREEN that way (reply-draft /
budget-figure-demand x qwen3:4b, 2026-08-27: finish_reason 'length', 2048 completion
tokens, 0 content chars, 8110 reasoning chars, run_properties ok=True with zero
failed_checks). Now the adapter raises TerminationError and the case fails loud with
one named record.

WHAT THIS FILE PINS, each mode seen RED and GREEN (gotcha 2 — a green guard proves
nothing until seen red):

  (b) ZERO CONTENT. The defect is first reproduced GREEN as a fixture of the OLD
      semantics — the recorded reply object, extracted from thinking prose exactly the
      way the deleted fallback + extract_json did, run through the REAL committed
      reply-draft property checks, ok=True with zero failed_checks. That construction
      is deliberately independent of the new code: a "before" derived from the fixed
      runner would agree with the fixed runner no matter what it did. Then the same
      response through the real `run_exam` fails with a SOLE `termination` entry.
  (c) PARTIAL CONTENT (D3, the soft tier). A truncated response whose content holds a
      complete object followed by cut-off junk is still ACCEPTED, with
      truncated_calls == 1 and unanswered_calls == 0 — a tripwire documenting today's
      behaviour, not an endorsement of it. Broken partial JSON still fails as `error`.
  (a) TIMEOUT (D4). A `requests.Timeout` surviving retry.py used to escape run_exam and
      kill the WHOLE run. Now the case fails with cause "timeout" and the run continues.
  CONTROLS. A clean 'stop' with content is untouched; a backend that omits
      finish_reason is untouched (the fix never invents a death); both fields empty
      raises TerminationError, not the old ValueError.
  TRAJECTORY. One good tool call then zero content: failed_checks carries BOTH
      `termination` and `answer_present` (the declared co-firing), and `detail` still
      carries the tool evidence gathered before the death.
  ISOLATION (gotcha 3). test_isolation_plain_mode_termination_is_the_sole_entry names
      the case whose failed_checks has exactly ONE entry and it is `termination`.
  BUCKET. `termination` is runner-emitted only: a properties.py check declaring it is
      refused at load time exactly like a check with no bucket.
  LIVE. `live_run_and_log` reaches the same call path. Trajectory mode would otherwise
      have written a JSONL line with an empty output and returned SUCCESS — a silent
      pass. Both modes log the record and then raise.

HOW THE MODEL IS FAKED. Plain-mode tests drive the REAL `ChatCompletionsAdapter`
against canned HTTP bodies (`requests.post` is the only thing replaced), so
router.generate -> call_with_retry -> call_model -> run_plain_case -> run_exam is all
real code — an adapter-shaped stand-in that raised TerminationError itself would prove
nothing about the adapter that actually raises it (gotcha 5). Trajectory tests use a
scripted adapter against the REAL evals/crm-followup/tools_mock.py fixture, the same
shape as sandbox/test_dedupe_tools.py.

Plain asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import router  # noqa: E402
import runner  # noqa: E402
from retry import _iter_top_level_objects, extract_json  # noqa: E402
from router import ChatCompletionsAdapter, TerminationError  # noqa: E402
from runner import (ROOT, _load_module, combine_metrics, load_exam,  # noqa: E402
                    load_properties, run_exam, run_properties,
                    run_trajectory_case, score_trajectory)

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


# ------------------------------------------------------------------ the fixtures

# The reply object qwen3:4b drafted INSIDE its thinking on reply-draft /
# budget-figure-demand and never emitted, transcribed verbatim from
# results/reply-draft__ollama__qwen3_4b.json (the run that scored it GREEN).
_DRAFTED_REPLY = {
    "reply": "Hi Kris,\n\nThanks for the prompt request. I'll get back to you with "
             "the exact budget figure and go-live date by the end of the day.\n\n"
             "Michiel"
}

# A REJECTED first draft, so the fixture holds TWO top-level objects and the "LAST
# object wins" rule the mechanism actually depends on is exercised rather than merely
# described. Pass 1's fixture had exactly ONE object, which made every "extract_json
# took the LAST object out of the thinking" claim vacuously true — first == last.
# This one is deliberately schema-INVALID for reply-draft (`draft`, not `reply`), so
# if extraction ever took the FIRST object instead, run_properties would fail
# check_has_reply and the pre-fix "scored ok=True" assertion would go red.
_REJECTED_DRAFT = {"draft": "Hi Kris, the budget is 45000 EUR and we go live 3 March."}

# Thinking prose with a rejected draft, then the answer object drafted mid-stream, then
# the generation cut off — the shape the real death had (8110 reasoning chars, 0
# content chars).
_THINKING_WITH_DRAFT = (
    "Okay, Kris wants a total budget figure and an exact go-live date, and says the "
    "board meets tomorrow. First attempt:\n"
    + json.dumps(_REJECTED_DRAFT, ensure_ascii=False)
    + "\nNo — I do not have either number in front of me, so I must not invent them. "
      "Let me draft something that promises the numbers without stating any. Maybe:\n"
    + json.dumps(_DRAFTED_REPLY, ensure_ascii=False)
    + "\nHmm, is that too short? Let me reconsider whether the sign-off is right and "
      "whether I should mention the board meeting explicitly, because Kris said the"
)

_CASE_ZERO_CONTENT = "budget-figure-demand"   # heldout
_CASE_CONTROL = "quote-request"               # train


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _body(content, reasoning=None, finish_reason="stop", completion_tokens=2048):
    """A chat-completions response body. `content=None` omits the key entirely (some
    backends do); `reasoning=None` omits the reasoning key."""
    msg = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if reasoning is not None:
        msg["reasoning"] = reasoning
    return {"choices": [{"message": msg, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 218, "completion_tokens": completion_tokens,
                      "total_tokens": 218 + completion_tokens}}


class _CannedPost:
    """Replaces requests.post at the HTTP boundary and NOTHING above it.

    `reply_for(user_text, nth_call)` returns a response body, or an Exception instance
    to raise (that is how the D4 timeout is injected — retry.py's api-retry loop sees
    exactly what a real socket timeout looks like)."""

    def __init__(self, reply_for):
        self.reply_for = reply_for
        self.seen: list[str] = []

    def __call__(self, url, headers=None, data=None, timeout=None):
        sent = json.loads(data)
        user = sent["messages"][-1]["content"]
        self.seen.append(user)
        out = self.reply_for(user, len(self.seen) - 1)
        if isinstance(out, Exception):
            raise out
        return _FakeResp(out)


def _run_reply_draft(reply_for, case_ids):
    """Drive the REAL run_exam over selected committed reply-draft cases with the HTTP
    boundary canned. Returns (result, post).

    Exactly ONE thing is replaced: `router.requests.post`, the network.
    `runner.adapter_for` returns a REAL ChatCompletionsAdapter, so the raise under test
    is the production one.

    ⚠️ The two exception tests below really sleep through retry.py's backoff (2 s + 4 s
    per api-retried case, ~12 s for this file). An earlier version of this helper
    patched `retry.time.sleep` to skip it — and that patch was INERT, because
    call_with_retry's `sleep=time.sleep` default is bound at DEF time to the real
    function, so rebinding the module attribute afterwards changes nothing (verified,
    2026-08-27). Rather than reach further into the code under test to save ten
    seconds, the sleep is left real. Presence is not effect (gotcha 1) — including in
    a test file's own scaffolding.
    """
    exam = load_exam("reply-draft")
    exam = {**exam, "cases": [c for c in exam["cases"] if c["id"] in case_ids]}
    if len(exam["cases"]) != len(case_ids):
        raise AssertionError(f"case ids missing from evals/reply-draft/cases.json: "
                             f"{case_ids} -> {[c['id'] for c in exam['cases']]}")
    agent = runner.load_agent("reply-draft")
    post = _CannedPost(reply_for)
    real_post, real_adapter_for = router.requests.post, runner.adapter_for
    try:
        router.requests.post = post
        runner.adapter_for = lambda *a, **k: ChatCompletionsAdapter(
            "http://canned/v1", timeout=7)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(agent, exam, "ollama", "canned-model")
    finally:
        router.requests.post = real_post
        runner.adapter_for = real_adapter_for
    return result, post


def _case(result, case_id):
    for c in result["cases"]:
        if c["id"] == case_id:
            return c
    raise AssertionError(f"case {case_id!r} not in result")


def _names(case):
    return [f["check"] for f in case.get("failed_checks", [])]


# ------------------------------------- (b) RED side: the defect, reproduced GREEN

def test_b_red_the_old_semantics_scored_the_thinking_as_an_answer():
    """The defect seen GREEN, built as a fixture of the OLD code, not from the new.

    The deleted fallback was literally `content = raw_reasoning`, after which
    extract_json ran on that text. Both steps are reproduced here by hand against the
    REAL committed case input and the REAL committed reply-draft property checks. If
    this ever stops being green, the historical claim this lane rests on — a heldout
    case passed off a run that emitted zero answer characters — was wrong.
    """
    exam = load_exam("reply-draft")
    case = next(c for c in exam["cases"] if c["id"] == _CASE_ZERO_CONTENT)
    check("the zero-content case is HELDOUT (that is why it mattered)",
          case.get("split") == "heldout", str(case.get("split")))

    # Step 1, the deleted fallback: content was empty, so `reasoning` became content.
    substituted = _THINKING_WITH_DRAFT
    # Step 2, retry.extract_json: the LAST complete object in the thinking wins. The
    # fixture holds TWO objects on purpose so this is a real discrimination and not a
    # tautology — asserted against the REAL extract_json.
    objs = [o for o in _iter_top_level_objects(substituted) if isinstance(o, dict)]
    check("the fixture really holds two top-level objects, so LAST != FIRST",
          len(objs) == 2 and objs[0] != objs[-1], str(objs))
    parsed = extract_json(substituted)
    check("the old path recovered the drafted object out of the thinking",
          parsed == _DRAFTED_REPLY, str(parsed))
    check("...and it is the LAST object, not the first (the rejected draft)",
          parsed != _REJECTED_DRAFT and parsed == objs[-1], str(parsed))

    props = load_properties("reply-draft")
    check("reply-draft really ships property checks (else this proves nothing)",
          len(props) >= 5, str(len(props)))
    ok, failures, failed = run_properties(props, case["input"], parsed)
    check("PRE-FIX: a run that emitted ZERO answer characters scored ok=True", ok,
          "; ".join(failures))
    check("PRE-FIX: with zero failed_checks", failed == [], str(failed))


# ----------------------------------- (b) GREEN side: the same response, fixed path

def test_b_green_zero_content_now_fails_with_a_named_record():
    """Same response through the REAL run_exam: passed=False, one `termination`
    entry, and detail["termination"] naming the four measured facts."""
    def reply_for(user, _n):
        return _body(content="", reasoning=_THINKING_WITH_DRAFT,
                     finish_reason="length")

    result, post = _run_reply_draft(reply_for, [_CASE_ZERO_CONTENT])
    case = _case(result, _CASE_ZERO_CONTENT)
    check("POST-FIX: the zero-content case FAILS", case["passed"] is False,
          str(case["passed"]))
    check("POST-FIX: failed_checks is exactly one `termination` entry",
          case.get("failed_checks") == [{"bucket": "termination",
                                         "check": "termination"}],
          str(case.get("failed_checks")))
    rec = (case.get("detail") or {}).get("termination")
    check("POST-FIX: detail carries the termination record", isinstance(rec, dict),
          str(case.get("detail")))
    check("POST-FIX: cause is no_answer", (rec or {}).get("cause") == "no_answer",
          str(rec))
    check("POST-FIX: content_chars is the measured 0",
          (rec or {}).get("content_chars") == 0, str(rec))
    check("POST-FIX: finish_reason is attributed as 'length'",
          (rec or {}).get("finish_reason") == "length", str(rec))
    check("POST-FIX: reasoning_chars records where the budget went",
          (rec or {}).get("reasoning_chars") == len(_THINKING_WITH_DRAFT), str(rec))
    check("POST-FIX: completion_tokens carried through from usage",
          (rec or {}).get("completion_tokens") == 2048, str(rec))
    check("POST-FIX: the model's thinking text is NOT in the answer",
          case["got"] == {}, str(case["got"]))
    check("POST-FIX: no parse-retry was spent on it — exactly ONE real call",
          len(post.seen) == 1, f"{len(post.seen)} calls")
    check("POST-FIX: heldout score reflects the failure",
          result["heldout"]["passed"] == 0 and result["heldout"]["total"] == 1,
          str(result["heldout"]))


def test_console_line_names_the_cause_and_stores_nothing_extra():
    """A terminated case emits no failure STRING — the record is structured — so the
    printed line used to be a bare FAIL, indistinguishable on a `check` run from a
    generic `error`. That distinction IS the lane, so the console says the cause.

    Asserted against the real captured stdout of run_exam, and asserted NOT to have
    leaked into the stored record: `failures` must stay absent, or taxonomy.py would
    count the same failure twice (once from the string, once from the dict)."""
    def reply_for(user, _n):
        return _body(content="", reasoning=_THINKING_WITH_DRAFT,
                     finish_reason="length")

    exam = load_exam("reply-draft")
    exam = {**exam, "cases": [c for c in exam["cases"]
                              if c["id"] == _CASE_ZERO_CONTENT]}
    post = _CannedPost(reply_for)
    real_post, real_adapter_for = router.requests.post, runner.adapter_for
    buf = io.StringIO()
    try:
        router.requests.post = post
        runner.adapter_for = lambda *a, **k: ChatCompletionsAdapter("http://c/v1")
        with contextlib.redirect_stdout(buf):
            result = run_exam(runner.load_agent("reply-draft"), exam, "ollama", "m")
    finally:
        router.requests.post = real_post
        runner.adapter_for = real_adapter_for
    out = buf.getvalue()
    check("the console line names the cause, not just FAIL",
          "termination: no_answer" in out, repr(out))
    check("...and attributes it", "finish_reason=length" in out
          and "content_chars=0" in out, repr(out))
    check("...while the STORED record grows no failure string (no double counting "
          "in taxonomy.py, which reads both `failures` and `failed_checks`)",
          "failures" not in _case(result, _CASE_ZERO_CONTENT),
          str(_case(result, _CASE_ZERO_CONTENT).get("failures")))


def test_isolation_plain_mode_termination_is_the_sole_entry():
    """GOTCHA 3, named explicitly: reply-draft / budget-figure-demand under a
    zero-content response is the case that passes every other check and fails only
    the new one. reply-draft is a `properties` exam, so a passing run's
    failed_checks is empty; the raise happens before run_properties is reached, so
    nothing can co-fire. No existing check co-fires in plain mode."""
    def reply_for(user, _n):
        return _body(content="", reasoning=_THINKING_WITH_DRAFT,
                     finish_reason="length")

    result, _post = _run_reply_draft(reply_for, [_CASE_ZERO_CONTENT])
    names = _names(_case(result, _CASE_ZERO_CONTENT))
    check("failed_checks has EXACTLY ONE entry", len(names) == 1, str(names))
    check("and it is `termination`", names == ["termination"], str(names))


def test_b_whitespace_only_content_is_also_no_answer():
    """The predicate is the fallback's OWN test (`not content.strip()`), not
    len == 0. A response of three spaces has no answer in it either, and gating on
    length would leave it falling through to a substitution that no longer exists.
    content_chars in the record is the MEASURED length (3), not a restatement of the
    trigger — so nothing here may hardcode 0 as an invariant of the trigger."""
    def reply_for(user, _n):
        return _body(content="   \n ", reasoning=_THINKING_WITH_DRAFT,
                     finish_reason="length")

    result, _post = _run_reply_draft(reply_for, [_CASE_ZERO_CONTENT])
    case = _case(result, _CASE_ZERO_CONTENT)
    check("whitespace-only content FAILS as termination",
          _names(case) == ["termination"], str(_names(case)))
    check("and the record reports the MEASURED length, not 0",
          (case["detail"]["termination"]).get("content_chars") == 5,
          str(case["detail"]["termination"]))


# --------------------------------------------------- (c) D3: the soft tier

_COMPLETE_THEN_JUNK = (
    json.dumps({"reply": "Hi Sofie,\n\nThanks for your email! I'll come back with a "
                         "quote and a timeline shortly.\n\nMichiel"},
               ensure_ascii=False)
    + '\n\nWait, let me reconsider. Maybe {"reply": "Dag Sof'
)


def test_c_truncated_but_complete_object_is_ACCEPTED_and_counted():
    """DECLARED GAP, pinned so a silent change goes RED. A truncated response whose
    content holds a complete object followed by cut-off text still parses to a real
    answer, and failing it would discard correct work. It is RECORDED (truncated_calls
    == 1) and scored exactly as today. This is a tripwire, not an endorsement."""
    def reply_for(user, _n):
        return _body(content=_COMPLETE_THEN_JUNK, finish_reason="length")

    result, _post = _run_reply_draft(reply_for, [_CASE_CONTROL])
    case = _case(result, _CASE_CONTROL)
    check("D3: the truncated-but-complete answer is ACCEPTED", case["passed"] is True,
          str(case.get("failures")))
    m = case["detail"]["metrics"]
    check("D3: truncated_calls == 1", m.get("truncated_calls") == 1, str(m))
    check("D3: unanswered_calls == 0", m.get("unanswered_calls") == 0, str(m))
    check("D3: finish_reason is carried on the per-call metrics",
          m.get("finish_reason") == "length", str(m))
    check("D3: no termination record on an accepted case",
          "termination" not in case.get("detail", {}), str(case.get("detail")))


def test_c_broken_partial_json_still_fails_as_error_not_termination():
    """The other half of the partial-content mode, unchanged by this lane: content cut
    mid-string never parses, extract_json raises after its parse-retries, and the case
    scores a generic `error`. Reclassifying it would be a scope creep that moves
    committed records."""
    def reply_for(user, _n):
        return _body(content='{"reply": "Hi Sofie,\\n\\nThanks for your email! '
                             "I'll get ba",
                     finish_reason="length")

    result, post = _run_reply_draft(reply_for, [_CASE_CONTROL])
    case = _case(result, _CASE_CONTROL)
    check("broken partial JSON still FAILS", case["passed"] is False)
    check("and still as `error`, NOT termination", _names(case) == ["error"],
          str(_names(case)))
    check("extract_json's parse-retry still ran (2 calls, unchanged)",
          len(post.seen) == 2, f"{len(post.seen)} calls")


def test_unanswered_calls_counter_is_reachable_and_falsifiable():
    """DECLARED: with the real ChatCompletionsAdapter this counter can never exceed 0
    in a returned metrics dict, because D2 raises before call_model returns. It is a
    tripwire on D2's completeness, not an observable of model behaviour.

    That does not make it untestable. A scripted adapter — a legitimate second adapter
    implementation, not a stand-in for the one under test — returns content with a
    zero content_chars meta, and the REAL call_model/combine_metrics path counts it.
    Seen at 1 and at 0."""
    class _ZeroCharsAdapter:
        def __init__(self, content_chars):
            self.content_chars = content_chars

        def generate(self, messages, model, temperature=0.0, max_tokens=512):
            return '{"answer": "x"}', {"prompt_tokens": 1, "completion_tokens": 2,
                                       "total_tokens": 3, "content_chars":
                                       self.content_chars, "reasoning_chars": 0,
                                       "finish_reason": "stop"}

    agent = {"system_prompt": "t", "temperature": 0.0, "max_tokens": 16}
    _p, _r, hot = runner.call_model(agent, _ZeroCharsAdapter(0), "m", [])
    _p, _r, cold = runner.call_model(agent, _ZeroCharsAdapter(17), "m", [])
    check("unanswered_calls is 1 when a call returned zero answer chars",
          hot["unanswered_calls"] == 1, str(hot))
    check("unanswered_calls is 0 when it did not", cold["unanswered_calls"] == 0,
          str(cold))
    check("the counters aggregate as counts across calls",
          combine_metrics([hot, cold])["unanswered_calls"] == 1,
          str(combine_metrics([hot, cold])))
    check("truncated_calls is 0 on a clean stop", hot["truncated_calls"] == 0,
          str(hot))


def test_counters_report_unknown_as_None_never_as_zero():
    """A backend that omits finish_reason knows nothing about truncation, and a
    metrics dict written before this lane knows nothing either. Both report None:
    unknown and zero are different facts (_empty_usage's standing rule), and a 0 here
    would read as "measured, no truncation"."""
    legacy = [{"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3,
               "wall_ms": 1.0, "retries": 0}]
    agg = combine_metrics(legacy)
    check("a pre-lane metrics dict aggregates truncated_calls to None, not 0",
          agg["truncated_calls"] is None, repr(agg["truncated_calls"]))
    check("...and unanswered_calls to None, not 0",
          agg["unanswered_calls"] is None, repr(agg["unanswered_calls"]))

    class _NoReasonAdapter:
        def generate(self, messages, model, temperature=0.0, max_tokens=512):
            return '{"answer": "x"}', {"prompt_tokens": None,
                                       "completion_tokens": None,
                                       "total_tokens": None}

    agent = {"system_prompt": "t", "temperature": 0.0, "max_tokens": 16}
    _p, _r, m = runner.call_model(agent, _NoReasonAdapter(), "m", [])
    check("a backend omitting finish_reason reports truncated_calls None",
          m["truncated_calls"] is None, str(m))
    check("the StubAdapter reports finish_reason None, never 'stop'",
          router.StubAdapter().generate([], "m")[1]["finish_reason"] is None,
          str(router.StubAdapter().generate([], "m")[1]))


# ----------------------------------------------------- (a) D4: the timeout escape

def test_a_timeout_fails_the_case_and_the_run_CONTINUES():
    """RED before this lane: a requests.Timeout surviving retry.py's api_attempts
    escaped run_exam and killed the whole run — every later case lost its verdict.
    Now the case fails with cause "timeout" and the next case still runs.

    The timeout is raised from inside requests.post, which is where a real socket
    timeout comes from, so retry.py's api-retry loop is exercised for real."""
    def reply_for(user, _n):
        if "vandamme-logistics" in user:            # budget-figure-demand
            return requests.Timeout("timed out after 7s")
        return _body(content=json.dumps(_DRAFTED_REPLY, ensure_ascii=False))

    result, post = _run_reply_draft(reply_for,
                                    [_CASE_CONTROL, _CASE_ZERO_CONTENT])
    check("D4: run_exam RETURNED — the timeout no longer kills the run",
          isinstance(result, dict) and len(result["cases"]) == 2,
          str(len(result.get("cases", []))))
    dead = _case(result, _CASE_ZERO_CONTENT)
    check("D4: the timing-out case FAILS", dead["passed"] is False)
    check("D4: with a sole `termination` entry", _names(dead) == ["termination"],
          str(_names(dead)))
    rec = dead["detail"]["termination"]
    check("D4: cause is `timeout`, distinct from `no_answer`",
          rec.get("cause") == "timeout", str(rec))
    check("D4: the exception type is named", rec.get("exception") == "Timeout",
          str(rec))
    check("D4: the timeout in force is recorded", rec.get("timeout_s") == 7, str(rec))
    survivor = _case(result, _CASE_CONTROL)
    check("D4: THE POINT — the following case still ran and was scored",
          survivor["passed"] is True, str(survivor.get("failures")))
    check("D4: retry.py's three api attempts were really spent on the dead case",
          sum(1 for s in post.seen if "vandamme-logistics" in s) == 3,
          str(len(post.seen)))


def test_a_http_error_is_declared_as_STILL_escaping():
    """Declared gap, pinned so it cannot silently change. requests.HTTPError is a
    backend fault (4xx/5xx), not a statement about this model's termination, and it
    still aborts the run — deliberately out of D4's scope."""
    def reply_for(user, _n):
        return requests.HTTPError("500 Server Error")

    try:
        _run_reply_draft(reply_for, [_CASE_CONTROL])
    except requests.HTTPError:
        check("HTTPError still escapes run_exam (declared, not fixed here)", True)
    else:
        check("HTTPError still escapes run_exam (declared, not fixed here)", False,
              "it was caught — D4's surface widened without the brief")


# --------------------------------------------------------------- controls

def test_control_a_clean_stop_with_content_is_untouched():
    """The fix must never invent a death. A normal response scores exactly as before,
    carries no termination record, and reports truncated/unanswered as measured 0s."""
    def reply_for(user, _n):
        return _body(content=json.dumps(_DRAFTED_REPLY, ensure_ascii=False),
                     finish_reason="stop", completion_tokens=120)

    result, _post = _run_reply_draft(reply_for, [_CASE_ZERO_CONTENT, _CASE_CONTROL])
    for cid in (_CASE_ZERO_CONTENT, _CASE_CONTROL):
        case = _case(result, cid)
        check(f"control ({cid}): passes", case["passed"] is True,
              str(case.get("failures")))
        check(f"control ({cid}): no failed_checks at all",
              "failed_checks" not in case, str(case.get("failed_checks")))
        check(f"control ({cid}): no termination record",
              "termination" not in case["detail"], str(case["detail"]))
        m = case["detail"]["metrics"]
        check(f"control ({cid}): truncated_calls 0, unanswered_calls 0",
              m["truncated_calls"] == 0 and m["unanswered_calls"] == 0, str(m))


def test_control_missing_finish_reason_does_not_invent_a_death():
    """A backend that omits finish_reason entirely (the field is optional on the
    compat wire) must still score its content normally — `None` is not `length`."""
    payload = {"choices": [{"message": {"role": "assistant",
                                        "content": json.dumps(_DRAFTED_REPLY)}}],
               "usage": {"prompt_tokens": 1, "completion_tokens": 2,
                         "total_tokens": 3}}

    def reply_for(user, _n):
        return payload

    result, _post = _run_reply_draft(reply_for, [_CASE_ZERO_CONTENT])
    case = _case(result, _CASE_ZERO_CONTENT)
    check("no finish_reason: the case still scores normally", case["passed"] is True,
          str(case.get("failures")))
    check("no finish_reason: recorded as None, never defaulted to 'stop'",
          case["detail"]["metrics"]["finish_reason"] is None,
          str(case["detail"]["metrics"]))
    check("no finish_reason: truncated_calls is None (unknown), not 0",
          case["detail"]["metrics"]["truncated_calls"] is None,
          str(case["detail"]["metrics"]))


def test_control_both_fields_empty_raises_TerminationError_not_ValueError():
    """The old `ValueError("returned empty content")` path folds into the same
    exception — one exit for "there is no answer here", two recorded causes.

    It must NOT stay a ValueError, but not for the reason it is tempting to give:
    call_with_retry's `except (TypeError, ValueError)` wraps only `parse_fn(raw)`,
    never `call_fn()`, so the class makes NO difference to how many generate() calls
    happen (verified 2026-08-27 — a ValueError-raising call_fn produces exactly one).
    The reason is ISOLATION at the CASE boundaries: `run_exam` and `judges.py` both
    catch (ValueError, TypeError) as "unparseable output", so a ValueError subclass
    would be classified correctly only while the narrower `except TerminationError`
    clause happens to be listed first."""
    real_post = router.requests.post
    try:
        router.requests.post = lambda *a, **k: _FakeResp(
            _body(content="", reasoning=None, finish_reason="stop"))
        ad = ChatCompletionsAdapter("http://canned/v1")
        try:
            ad.generate([{"role": "user", "content": "hi"}], "m")
        except TerminationError as exc:
            check("both fields empty raises TerminationError", True)
            check("...and is NOT a ValueError/TypeError, so no case-level "
                  "`except (ValueError, TypeError)` can reclassify it as `error`",
                  not isinstance(exc, (ValueError, TypeError)), type(exc).__name__)
            check("...and is NOT a requests exception (no api-retry)",
                  not isinstance(exc, requests.RequestException), type(exc).__name__)
            check("...carrying reasoning_chars 0 — the second recorded cause",
                  exc.details["reasoning_chars"] == 0 and
                  exc.details["content_chars"] == 0, str(exc.details))
        else:
            check("both fields empty raises TerminationError", False, "it returned")
    finally:
        router.requests.post = real_post


# ------------------------------------------------------------- trajectory mode

class _ScriptedAdapter:
    """Replays a fixed sequence of model outputs; an entry may be an Exception to
    raise instead (that is how the mid-loop death is injected). CYCLES when the script
    runs out, for the reason sandbox/test_dedupe_tools.py states: a loop bug making
    more calls than the script has lines must be caught by a call-count assertion, not
    disguised as an IndexError from the test's own fixture."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.seen: list = []

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        out = self.outputs[len(self.seen) % len(self.outputs)]
        self.seen.append(messages)
        if isinstance(out, Exception):
            raise out
        return out, {"prompt_tokens": 10, "completion_tokens": 400,
                     "total_tokens": 410, "content_chars": len(out),
                     "reasoning_chars": 0, "finish_reason": "stop"}


_TRAJ_CASE = {"id": "traj-death", "split": "train",
              "input": "When did we last talk to Janssens Bakery?",
              "expected": {"tools_called": ["crm_lookup"],
                           "answer_contains": ["2026-07-02"], "max_steps": 4}}

_DEATH = TerminationError(
    "model emitted no answer",
    {"finish_reason": "length", "completion_tokens": 2048, "content_chars": 0,
     "reasoning_chars": 8110})


def _traj_tools():
    return _load_module(ROOT / "evals" / "crm-followup" / "tools_mock.py",
                        "tools_mock_termination_test")


def test_trajectory_death_preserves_the_tool_evidence():
    """One good tool call, then a call that emits nothing. The loop stops, and
    everything gathered BEFORE the death survives on the trace — an aborting exception
    would leave a reader unable to tell a mid-loop death from a model that never
    called a tool at all."""
    agent = {"system_prompt": "test", "temperature": 0.0, "max_tokens": 512}
    script = ['{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
              _DEATH]
    parsed, trace = run_trajectory_case(agent, _TRAJ_CASE, _ScriptedAdapter(script),
                                        "scripted", _traj_tools())
    check("trajectory: parsed is empty — no answer was emitted", parsed == {},
          str(parsed))
    check("trajectory: the trace carries a termination record",
          trace.get("termination", {}).get("cause") == "no_answer",
          str(trace.get("termination")))
    check("trajectory: finish_reason attributed",
          trace["termination"]["finish_reason"] == "length",
          str(trace["termination"]))
    check("trajectory: the tool call made BEFORE the death survives",
          trace["tools_called"] == ["crm_lookup"], str(trace["tools_called"]))
    check("trajectory: so does the tool RESULT (the grounding corpus)",
          len(trace["tool_results"]) == 1, str(trace["tool_results"]))
    check("trajectory: and the tool_calls feed the monitor reads",
          trace["tool_calls"] == [{"tool": "crm_lookup",
                                   "args": {"company": "Janssens Bakery"}}],
          str(trace["tool_calls"]))
    ok, failures = score_trajectory(parsed, trace, _TRAJ_CASE["expected"],
                                    _TRAJ_CASE["input"])
    check("trajectory: score_trajectory fails it", not ok)
    check("trajectory: answer_present is among the failures",
          "no final answer emitted" in failures, "; ".join(failures))


def test_trajectory_death_comes_from_the_REAL_ADAPTER_not_a_hand_built_exception():
    """The trajectory tests around this one inject `_DEATH`, a TerminationError built
    by hand — which pins run_trajectory_case's HANDLING but assumes the adapter would
    ever have raised it. This one closes that loop: the model's last turn returns
    genuinely empty `content` over the wire, through the REAL ChatCompletionsAdapter,
    so the death under test is produced by the shipped predicate.

    Micro-scale — the death signature reproduces on a canned body in milliseconds; no
    live model is needed to prove which line raises.
    """
    turns = [json.dumps({"tool": "crm_lookup",
                         "args": {"company": "Janssens Bakery"}}),
             None]  # None => a real empty-content response on the wire

    def reply_for(_user, n):
        out = turns[min(n, len(turns) - 1)]
        if out is None:
            return _body(content="", reasoning=_THINKING_WITH_DRAFT,
                         finish_reason="length")
        return _body(content=out, finish_reason="stop", completion_tokens=40)

    post = _CannedPost(reply_for)
    agent = {"system_prompt": "test", "temperature": 0.0, "max_tokens": 512}
    real_post = router.requests.post
    try:
        router.requests.post = post
        parsed, trace = run_trajectory_case(
            agent, _TRAJ_CASE, ChatCompletionsAdapter("http://canned/v1"),
            "scripted", _traj_tools())
    finally:
        router.requests.post = real_post

    check("real adapter: two real HTTP round-trips happened", len(post.seen) == 2,
          str(len(post.seen)))
    check("real adapter: the loop stopped with no answer", parsed == {}, str(parsed))
    check("real adapter: the death record came from the shipped raise",
          trace.get("termination", {}).get("cause") == "no_answer",
          str(trace.get("termination")))
    check("real adapter: finish_reason attributed off the wire",
          trace["termination"]["finish_reason"] == "length", str(trace["termination"]))
    check("real adapter: content_chars is the MEASURED 0",
          trace["termination"]["content_chars"] == 0, str(trace["termination"]))
    check("real adapter: reasoning_chars measured off the wire body",
          trace["termination"]["reasoning_chars"] == len(_THINKING_WITH_DRAFT),
          str(trace["termination"]))
    check("real adapter: the tool evidence from before the death survives",
          trace["tools_called"] == ["crm_lookup"]
          and len(trace["tool_results"]) == 1, str(trace))
    ok, failures = score_trajectory(parsed, trace, _TRAJ_CASE["expected"],
                                    _TRAJ_CASE["input"])
    check("real adapter: answer_present co-fires", not ok
          and "no final answer emitted" in failures, "; ".join(failures))


def test_trajectory_death_on_the_FIRST_call_declared_gap_zeroed_metrics():
    """DECLARED GAP (e), pinned so a silent change goes RED.

    When the death happens on the FIRST model call no step metrics were ever collected,
    and combine_metrics([]) returns measured-looking ZEROS — `completion_tokens: 0` for
    a call that really burned its whole budget. That contradicts the unknown-is-not-zero
    rule this file lives by, and it is reachable only through this lane's new path (a
    first-call raise used to escape run_trajectory_case entirely).

    It is NOT fixed here: the honest value is None, and a None `wall_ms` would crash the
    exam-level roll-up, which sums that field without null handling — a change to a
    score-defining aggregate well outside this lane's stated surface. Instead the case
    is counted as UNMETERED at the exam level, so metrics_totals reports
    complete=False rather than presenting a short number as complete. Both halves are
    asserted below."""
    agent = {"system_prompt": "test", "temperature": 0.0, "max_tokens": 512}
    parsed, trace = run_trajectory_case(agent, _TRAJ_CASE,
                                        _ScriptedAdapter([_DEATH]), "scripted",
                                        _traj_tools())
    check("first-call death: still recorded as a termination",
          trace["termination"]["cause"] == "no_answer", str(trace.get("termination")))
    check("first-call death: no tool evidence exists to preserve",
          trace["tools_called"] == [] and trace["tool_results"] == [],
          str(trace))
    check("GAP (e): combine_metrics([]) fabricates zeros, NOT None — today's behaviour",
          trace["metrics"]["completion_tokens"] == 0
          and trace["metrics"]["unanswered_calls"] == 0, str(trace["metrics"]))

    # ...and the exam level says the totals are incomplete because of it.
    exam = load_exam("crm-followup")
    exam = {**exam, "cases": exam["cases"][:1]}
    real_adapter_for = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: _ScriptedAdapter([_DEATH])
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(runner.load_agent("crm-followup"), exam, "ollama", "s")
    finally:
        runner.adapter_for = real_adapter_for
    totals = result["metrics_totals"]
    check("a died case is counted UNMETERED, so the totals say complete=False",
          totals.get("complete") is False and totals.get("unmetered_cases") == 1,
          str(totals))


def test_trajectory_healthy_run_carries_NO_termination_key():
    """The trace's key set on a healthy run must be literally what it was before this
    lane — that is what keeps test_dedupe_tools.py's `set(trace) == _MASTER_TRACE_KEYS`
    assertion green UNCHANGED. Asserted here against a literal fixture too, so a
    regression fails in both files."""
    agent = {"system_prompt": "test", "temperature": 0.0, "max_tokens": 512}
    script = ['{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
              '{"answer": "Janssens Bakery was last contacted on 2026-07-02."}']
    _parsed, trace = run_trajectory_case(agent, _TRAJ_CASE, _ScriptedAdapter(script),
                                         "scripted", _traj_tools())
    check("healthy trajectory: no termination key at all",
          set(trace) == {"tools_called", "tool_calls", "tool_results", "steps",
                         "metrics"}, str(sorted(trace)))


def test_trajectory_case_boundary_records_BOTH_termination_and_answer_present():
    """THE DECLARED CO-FIRING (D2). Attribution is this lane's product: `termination`
    says the model was cut off mid-generation, `answer_present` says the case has no
    answer. Dropping either would make a trajectory death indistinguishable from a
    model that finished its loop and chose not to answer.

    Driven through the REAL run_exam on the REAL committed crm-followup exam (one case
    selected), so the boundary under test is production code."""
    exam = load_exam("crm-followup")
    check("crm-followup really is a trajectory exam (else this proves nothing)",
          exam.get("mode") == "trajectory", str(exam.get("mode")))
    exam = {**exam, "cases": exam["cases"][:1]}
    agent = runner.load_agent("crm-followup")
    script = ['{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
              _DEATH]
    real_adapter_for = runner.adapter_for
    try:
        runner.adapter_for = lambda *a, **k: _ScriptedAdapter(script)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(agent, exam, "ollama", "scripted")
    finally:
        runner.adapter_for = real_adapter_for
    case = result["cases"][0]
    names = _names(case)
    check("trajectory case FAILS", case["passed"] is False)
    check("failed_checks carries BOTH entries, termination first",
          names[0] == "termination" and "answer_present" in names, str(names))
    check("the termination entry carries the termination bucket",
          {"bucket": "termination", "check": "termination"}
          in case["failed_checks"], str(case["failed_checks"]))
    check("the answer_present entry keeps its quality bucket",
          {"bucket": "quality", "check": "answer_present"} in case["failed_checks"],
          str(case["failed_checks"]))
    check("detail STILL carries the tool evidence beside the record",
          case["detail"]["tools_called"] == ["crm_lookup"]
          and len(case["detail"]["tool_results"]) == 1, str(case["detail"]))
    check("detail carries the termination record itself",
          case["detail"]["termination"]["cause"] == "no_answer",
          str(case["detail"].get("termination")))


# ------------------------------------------------------------------- the bucket

def test_termination_bucket_is_runner_emitted_only():
    """`termination` is a real bucket in a committed record and an INVALID declaration
    on a property check: a check has an output to inspect, and a case that terminated
    has none, so a check can never be in a position to declare it. load_checks must
    refuse it exactly like a missing bucket."""
    check("termination is in the record vocabulary",
          "termination" in runner.BUCKETS, str(runner.BUCKETS))
    check("but NOT in the set a properties.py check may declare",
          "termination" not in runner.DECLARABLE_BUCKETS,
          str(runner.DECLARABLE_BUCKETS))
    tmp = ROOT / "evals" / "reply-draft" / "_termination_bucket_probe.py"
    tmp.write_text('def check_bogus(input_text, output):\n'
                   '    return True, ""\n'
                   'check_bogus.bucket = "termination"\n')
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            runner.load_checks(tmp, "props_termination_probe")
    except SystemExit as exc:
        check("a check declaring bucket='termination' is REFUSED at load time",
              "check_bogus" in str(exc), str(exc))
    else:
        check("a check declaring bucket='termination' is REFUSED at load time",
              False, "load_checks accepted it")
    finally:
        tmp.unlink(missing_ok=True)


# --------------------------------------------------------------- the live path

def test_live_run_logs_the_record_then_raises_in_BOTH_modes():
    """`live_run_and_log` reaches the same call path, and the two modes failed
    DIFFERENTLY before this lane: plain mode propagated and logged nothing, while
    trajectory mode caught internally and returned — writing a JSONL line with an
    empty output and reporting SUCCESS. That second one is a silent pass on a run that
    emitted no answer. Both now log the record and raise."""
    import tempfile
    for agent_name, adapter in (
            ("reply-draft", _ScriptedAdapter([_DEATH])),
            ("crm-followup", _ScriptedAdapter(
                ['{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
                 _DEATH]))):
        with tempfile.TemporaryDirectory() as td:
            real_adapter_for, real_results = runner.adapter_for, runner.RESULTS_DIR
            try:
                runner.adapter_for = lambda *a, **k: adapter
                runner.RESULTS_DIR = Path(td)
                raised = None
                try:
                    runner.live_run_and_log(agent_name, "When did we last talk to "
                                                        "Janssens Bakery?")
                except TerminationError as exc:
                    raised = exc
            finally:
                runner.adapter_for = real_adapter_for
                runner.RESULTS_DIR = real_results
            check(f"live ({agent_name}): raises instead of returning a silent pass",
                  raised is not None, "it returned normally")
            logged = Path(td) / "live" / f"{agent_name}.jsonl"
            check(f"live ({agent_name}): the line was written BEFORE the raise",
                  logged.exists(), str(logged))
            if logged.exists():
                entry = json.loads(logged.read_text().splitlines()[-1])
                check(f"live ({agent_name}): the logged line carries the record",
                      entry.get("termination", {}).get("cause") == "no_answer",
                      str(entry)[:300])


# ------------------------------------------- pass 2: the snapshot-outage hazard

def test_snapshot_is_REFUSED_when_cases_died_of_timeouts():
    """D4 created this hazard and closes it in the same lane.

    Before D4 a timeout CRASHED the run, so `--snapshot` could never be reached during
    an outage. Now the run survives — which means a timeout storm would write a
    snapshot recording ~0.0, and `check` gates on heldout dropping BELOW the snapshot,
    so every later run would clear it trivially. A green gate that asserts nothing.

    Driven through the REAL CLI: sys.argv -> runner.main() -> cmd_run -> --snapshot.
    The committed snapshot's bytes are compared before/after, which is the assertion
    that actually matters — an exit code says the process stopped, not that the file
    survived.

    ⚠️ TWO pieces of scaffolding here, both deliberate and both learned the hard way
    when the mutation sweep for this very test ran against pass 2:

    1. `load_exam` is stubbed to ONE case. It is exam DATA, not the code under test
       (`cmd_run` -> `run_exam` -> `refuse_snapshot_on_outage` is all real). Without it
       the test drives all 17 committed cases and each one really sleeps through
       retry.py's 2 s + 4 s backoff — 100 s per invocation, times every mutation.
    2. The snapshot file is restored in a `finally` from bytes read up front, and the
       post-run bytes are captured INSIDE the try so the assertion still sees the
       damage. When the guard is mutated away this test genuinely overwrites the
       committed snapshot with a `train 0.0 / heldout 0.0 / model "canned"` file — i.e.
       the exact artifact the guard exists to prevent, produced for real. A test that
       proves a guard works by breaking the repo when the guard is gone must clean up
       after itself.
    """
    snap_path = ROOT / "evals" / "reply-draft" / "snapshot.json"
    before = snap_path.read_bytes()

    def reply_for(_user, _n):
        return requests.Timeout("timed out")

    post = _CannedPost(reply_for)
    full = load_exam("reply-draft")
    one_case = {**full, "cases": full["cases"][:1]}
    real_post, real_adapter_for = router.requests.post, runner.adapter_for
    real_load_exam, real_argv = runner.load_exam, sys.argv
    rc, exited, after = None, None, None
    try:
        router.requests.post = post
        runner.adapter_for = lambda *a, **k: ChatCompletionsAdapter("http://c/v1",
                                                                    timeout=3)
        runner.load_exam = lambda _name: one_case
        sys.argv = ["runner.py", "run", "reply-draft", "--model", "canned",
                    "--snapshot"]
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                rc = runner.main()
            except SystemExit as exc:
                exited = exc
        after = snap_path.read_bytes()          # captured BEFORE the restore below
    finally:
        router.requests.post = real_post
        runner.adapter_for = real_adapter_for
        runner.load_exam = real_load_exam
        sys.argv = real_argv
        if snap_path.read_bytes() != before:    # only writes when the guard failed
            snap_path.write_bytes(before)

    check("a timeout storm REFUSES the snapshot (SystemExit, not rc=0)",
          exited is not None, f"returned rc={rc}")
    msg = str(exited.code) if exited is not None else ""
    check("...loudly, naming the cause and the count",
          "refusing --snapshot" in msg and "timeout" in msg, msg[:200])
    check("...and THE POINT: the committed snapshot is byte-identical",
          after == before,
          "the snapshot was overwritten during a simulated outage")


def test_snapshot_is_ALLOWED_when_cases_died_of_no_answer():
    """The other half, and the one that keeps the guard honest. `no_answer` is a real
    measurement OF THE MODEL and belongs in a snapshot — a guard that refused those
    would make a model that cannot terminate unsnapshottable, which is the opposite of
    this lane's point. Only `timeout` (an infrastructure fact) blocks.

    Asserted on the payload, never by writing over the committed file."""
    result = {"cases": [
        {"id": "a", "detail": {"termination": {"cause": "no_answer"}}},
        {"id": "b", "detail": {"metrics": {}}},
    ]}
    try:
        runner.refuse_snapshot_on_outage(result)
        check("a run full of no_answer deaths is still snapshottable", True)
    except SystemExit as exc:
        check("a run full of no_answer deaths is still snapshottable", False, str(exc))
    mixed = {"cases": [{"id": "a", "detail": {"termination": {"cause": "no_answer"}}},
                       {"id": "b", "detail": {"termination": {"cause": "timeout"}}}]}
    try:
        runner.refuse_snapshot_on_outage(mixed)
        check("ONE timeout among no_answers still refuses", False, "it allowed it")
    except SystemExit as exc:
        check("ONE timeout among no_answers still refuses", "1 of 2" in str(exc),
              str(exc)[:160])


# ------------------------------------------------- pass 2: the judge boundary

def test_a_judge_that_emits_no_answer_is_a_JUDGE_failure():
    """The two-place gap. judges.py catches (ValueError, TypeError); a judge model
    emitting empty content now raises TerminationError, which would escape into
    run_exam's case boundary and be recorded as the CANDIDATE's `no_answer` — with
    detail["termination"] overwriting the candidate's real detail. A fabricated
    measurement of the wrong model.

    ⚠️ Unreachable today, VERIFIED not assumed: no evals/*/rubric.md exists, so
    load_judge returns None for every agent. Asserted below so the claim is checked
    rather than repeated."""
    rubrics = sorted((ROOT / "evals").glob("*/rubric.md"))
    check("no rubric.md exists, so the judge path is dormant today",
          rubrics == [], str(rubrics))

    # Driven through the REAL load_judge, which takes `root` — so a temp tree with a
    # rubric.md builds the production closure without touching the repo.
    import tempfile

    import judges
    real_get_adapter = judges.get_adapter

    class _EmptyJudgeAdapter:
        """A judge backend that emits no answer. Raises the same typed exception the
        real ChatCompletionsAdapter raises on empty content."""

        def generate(self, messages, model, temperature=0.0, max_tokens=512):
            raise TerminationError("judge emitted no answer",
                                   {"finish_reason": "length",
                                    "completion_tokens": 2048,
                                    "content_chars": 0, "reasoning_chars": 4000})

    with tempfile.TemporaryDirectory() as td:
        rubric = Path(td) / "evals" / "reply-draft" / "rubric.md"
        rubric.parent.mkdir(parents=True)
        rubric.write_text("- Tone: the reply is polite\n")
        try:
            judges.get_adapter = lambda *a, **k: _EmptyJudgeAdapter()
            judge = judges.load_judge(
                "reply-draft",
                {"judge": {"provider": "ollama", "model": "judge-model"}},
                "candidate-model", Path(td))
            check("load_judge built a real judge from the temp rubric",
                  judge is not None)
            ok, failures = judge("some input", {"reply": "hi"})
        finally:
            judges.get_adapter = real_get_adapter

    check("a judge that emitted nothing FAILS the case", ok is False, str(ok))
    check("...as a JUDGE failure, not as the candidate's termination",
          len(failures) == 1 and failures[0].startswith("judge unparseable"),
          str(failures))
    check("...so _judge_check_id still bins it under the judge",
          runner._judge_check_id(failures[0]) == "judge unparseable",
          runner._judge_check_id(failures[0]))


# ------------------------------------------------------ pass 2: the CLI boundary

def test_cmd_live_exits_with_a_sentence_not_a_traceback():
    """A TerminationError out of live_run_and_log used to reach the user as a raw
    stack. Loud is right; a traceback is not this repo's way of being loud."""
    import tempfile
    real_adapter_for, real_results, real_argv = (runner.adapter_for,
                                                 runner.RESULTS_DIR, sys.argv)
    with tempfile.TemporaryDirectory() as td:
        exited = None
        try:
            runner.adapter_for = lambda *a, **k: _ScriptedAdapter([_DEATH])
            runner.RESULTS_DIR = Path(td)
            sys.argv = ["runner.py", "live", "reply-draft", "--input", "hello there"]
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    runner.main()
                except SystemExit as exc:
                    exited = exc
        finally:
            runner.adapter_for, runner.RESULTS_DIR = real_adapter_for, real_results
            sys.argv = real_argv
        check("cmd_live exits non-zero", exited is not None
              and exited.code not in (0, None), repr(exited and exited.code))
        msg = str(exited.code) if exited is not None else ""
        check("...with the repo's 'error: ...' convention, naming the cause",
              msg.startswith("error:") and "emitted no answer" in msg, msg[:200])
        check("...and pointing at the line it already logged",
              "results/live/reply-draft.jsonl" in msg, msg[:200])


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
