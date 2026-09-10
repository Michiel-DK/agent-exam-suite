#!/usr/bin/env python3
"""Eval runner: run an agent's exam, snapshot scores, gate on regression, diff models.

    python3 harness/runner.py list
    python3 harness/runner.py run <agent> [--model X] [--provider Y] [--snapshot]
    python3 harness/runner.py check <agent> [--tolerance 0.0]
    python3 harness/runner.py diff <agent> --models m1,m2[,m3]
    python3 harness/runner.py live <agent> --input "..."      # one agent, through routes.yaml
    python3 harness/runner.py intake --input "..."            # request -> dispatcher -> agent (exit 0/2/3)

Exam modes (evals/<agent>/cases.json "mode" field) — the complexity ladder:
    labels      exact match on expected fields (classification)         [default]
    fields      per-field partial credit (structured extraction)
    properties  no golden answers; evals/<agent>/properties.py checks must pass
    trajectory  tool-loop agents; asserts tools called, step budget, grounded answer

Any exam may ALSO ship a properties.py — its checks run on every case on top of the
mode's own scoring. Scores report train and heldout separately; only heldout is the
agent's real score (never tune on the reported set — rlvr-codegen docs/04).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judges import load_judge  # noqa: E402
from numnorm import strip_thousands  # noqa: E402
from retry import ParseFailure, call_with_retry, extract_json  # noqa: E402
from router import DEFAULT_TIMEOUT_S, PROVIDERS, TerminationError, get_adapter  # noqa: E402
import taxonomy  # noqa: E402  (report-only; imports nothing from here at load time)
import policy  # noqa: E402  (report-only; imports nothing from here at load time)
import stats  # noqa: E402  (A3: the single interval implementation, shared with route/serve)
import strategies  # noqa: E402  (E21; imports nothing from here — ctx is injected)
import probe  # noqa: E402  (report-only; imports nothing from here at load time)
import library  # noqa: E402  (E6-train; imports nothing from here at load time)

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"


# ---------------------------------------------------------------- loading

def load_agent(name: str) -> dict:
    agent_dir = ROOT / "agents" / name
    if not agent_dir.exists():
        sys.exit(f"error: no agent at {agent_dir}")
    cfg = yaml.safe_load((agent_dir / "agent.yaml").read_text())
    cfg["system_prompt"] = (agent_dir / "prompt.md").read_text()
    # E6-train: an optional `library:` key (filename relative to the agent dir)
    # turns lesson injection ON for this agent. No committed agent.yaml sets it
    # (asserted in sandbox/test_library.py, the router-knobs pattern), so every
    # existing gate loads a byte-identical config. The leak guard runs HERE, at
    # load time, against the agent's own cases — a leaky library can never reach
    # a scored run, not merely a failing test. Fail loud: a missing/malformed/
    # leaky library file raises rather than silently running without lessons.
    lib_name = cfg.get("library")
    if lib_name is not None:
        lib_path = agent_dir / lib_name
        cases = json.loads((ROOT / "evals" / name / "cases.json").read_text())["cases"]
        cfg["_lessons"] = library.load_library(lib_path, cases)
        cfg["library_sha"] = library.library_sha(lib_path)
        cfg["library_k"] = int(cfg.get("library_k", 2))
    return cfg


def adapter_for(agent: dict, provider: str | None = None, timeout: int | None = None):
    """The single place an adapter is built from an agent's config (E22a).

    Precedence: explicit CLI `timeout` > agent.yaml `timeout_s` > router's default.
    An explicit override has to win, because the reason the knob exists is sweeping a
    SLOW model that the agent's own config knows nothing about.

    ⚠️ No committed agent.yaml sets any of these four keys (timeout_s, json_mode,
    reasoning_effort, provider_routing), so every gate runs on the same 120s /
    no-response_format / no-reasoning_effort / no-provider request it always did.
    That is asserted in sandbox/test_router_knobs.py, not assumed here.

    `provider_routing` is read RAW (no bool() coercion, unlike json_mode below) so the
    dict passes through unmodified — same shape as reasoning_effort's raw read. This
    is the routing-payload sense of "provider" (OpenRouter's `provider` request-body
    key), not `agent["provider"]` (the backend selector) in the `return` below.
    """
    if timeout is None:
        timeout = agent.get("timeout_s")
    return get_adapter(provider or agent["provider"], timeout=timeout,
                       json_mode=bool(agent.get("json_mode", False)),
                       reasoning_effort=agent.get("reasoning_effort"),
                       provider_routing=agent.get("provider_routing"))


def load_exam(name: str) -> dict:
    path = ROOT / "evals" / name / "cases.json"
    if not path.exists():
        sys.exit(f"error: agent {name!r} has no exam ({path}). Every agent gets one at birth.")
    return json.loads(path.read_text())


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def print_not_verified(exam: dict) -> None:
    """Print what this exam CANNOT catch — evals/<agent>/cases.json 'not_verified'."""
    nv = exam.get("not_verified")
    if not nv:
        return
    for line in (nv if isinstance(nv, list) else [nv]):
        print(f"  not verified: {line}")


# C5(a): report-only tags, never scoring semantics.
#
# TERMINATION-DETECT D2 adds a third value. "termination" is RUNNER-EMITTED ONLY: it
# names a condition observed at the case boundary — the model emitted no answer at all,
# or the request timed out — and no property check can ever be in a position to declare
# it, because in both cases there is no output for a check to inspect. Reusing "format"
# would misfile a runner-level condition as an output-shape problem.
#
# Hence the split: BUCKETS is the vocabulary a committed record may carry;
# DECLARABLE_BUCKETS is the strictly smaller set a properties.py check may claim.
# load_checks validates against the latter, so a check declaring bucket="termination"
# is refused at load time exactly like a check with no bucket at all. Pinned in
# sandbox/test_termination.py, not assumed here.
DECLARABLE_BUCKETS = ("format", "quality")
BUCKETS = DECLARABLE_BUCKETS + ("termination",)


ROUTES_PATH = ROOT / "routes.yaml"


def load_routes(agent_name: str) -> list[dict]:
    """The ORDERED tier list `live` walks for an agent (LIVE-ROUTING lane, A1).
    Tier 0 must be the committed champion — evals/test_live_routing.py pins that
    against agents/<name>/agent.yaml, so the table cannot drift from the exam's
    snapshot. Returns [] when the file or the agent's entry is absent: the caller
    then runs exactly the pre-lane single-tier path. A malformed entry RAISES —
    never a silently-empty table (fail loud, never a placeholder)."""
    if not ROUTES_PATH.exists():
        return []
    table = yaml.safe_load(ROUTES_PATH.read_text()) or {}
    tiers = table.get(agent_name)
    if tiers is None:
        return []
    if not isinstance(tiers, list) or not tiers:
        raise ValueError(f"routes.yaml: {agent_name!r} must map to a non-empty list of tiers")
    out = []
    for i, t in enumerate(tiers):
        if not (isinstance(t, dict) and isinstance(t.get("provider"), str)
                and isinstance(t.get("model"), str)):
            raise ValueError(f"routes.yaml: {agent_name!r} tier {i} needs string "
                             f"'provider' and 'model', got {t!r}")
        entry = {"provider": t["provider"], "model": t["model"]}
        # HOSTED-TIERS (2026-09-05): a tier may carry `provider_routing` — the creator-
        # endpoint pin the hosted row was MEASURED under. Without it a live escalation
        # would run unpinned, i.e. not the configuration the tier was earned on.
        # Carried verbatim (same raw read as adapter_for's agent.yaml path); any other
        # key is a typo and RAISES rather than being silently dropped.
        extra = {k: v for k, v in t.items() if k not in ("provider", "model")}
        if set(extra) - {"provider_routing"}:
            raise ValueError(f"routes.yaml: {agent_name!r} tier {i} carries unknown "
                             f"key(s) {sorted(set(extra) - {'provider_routing'})}")
        if "provider_routing" in extra:
            if not isinstance(extra["provider_routing"], dict):
                raise ValueError(f"routes.yaml: {agent_name!r} tier {i} provider_routing "
                                 f"must be a mapping, got {extra['provider_routing']!r}")
            entry["provider_routing"] = extra["provider_routing"]
        out.append(entry)
    return out


def load_properties(name: str) -> list:
    """properties.py exports check_* functions: (input_text, output: dict) -> (ok, msg)."""
    path = ROOT / "evals" / name / "properties.py"
    if not path.exists():
        return []
    return load_checks(path, f"props_{name}")


def load_checks(path: Path, mod_name: str) -> list:
    """Load check_* functions and REFUSE any without a valid bucket marker.

    Every check must declare `check_x.bucket = "format" | "quality"` (C5(a)).
    Refusing at load time — before any model call — means a missing marker can
    never be silently defaulted into the wrong bucket (fail loud, never a
    placeholder), and can never change a verdict (the run dies before scoring).

    Validated against DECLARABLE_BUCKETS, not BUCKETS: "termination" is a real bucket
    in a committed record but is emitted only by run_exam, so a property check
    claiming it is as invalid as one claiming nothing (D2).
    """
    mod = _load_module(path, mod_name)
    checks = [(fn, getattr(mod, fn)) for fn in sorted(dir(mod)) if fn.startswith("check_")]
    for fn_name, fn in checks:
        bucket = getattr(fn, "bucket", None)
        if bucket not in DECLARABLE_BUCKETS:
            sys.exit(f"error: {path} check {fn_name!r} has bucket {bucket!r} — "
                     f"every check must declare a bucket in {DECLARABLE_BUCKETS} "
                     f"(C5(a), docs/exam-audit-2026-07-22.md)")
    return checks


def load_tools(agent_name: str, for_exam: bool = True):
    """Exams prefer evals/<agent>/tools_mock.py (deterministic, free); live runs use
    the real agents/<agent>/tools.py. Same function signatures either way."""
    mock = ROOT / "evals" / agent_name / "tools_mock.py"
    if for_exam and mock.exists():
        return _load_module(mock, f"tools_mock_{agent_name}")
    path = ROOT / "agents" / agent_name / "tools.py"
    if not path.exists():
        sys.exit(f"error: tool-using agent {agent_name!r} needs {path}")
    return _load_module(path, f"tools_{agent_name}")


# ---------------------------------------------------------------- scoring

def score_labels(parsed: dict, expected: dict) -> tuple[bool, dict]:
    ok = _fields_matched(parsed, expected) == len(expected)
    return ok, {}


def score_fields(parsed: dict, expected: dict) -> tuple[bool, dict]:
    matched = _fields_matched(parsed, expected)
    return matched == len(expected), {"fields_matched": matched, "fields_total": len(expected)}


def _fields_matched(parsed: dict, expected: dict) -> int:
    matched = 0
    for key, want in expected.items():
        got = parsed.get(key)
        if isinstance(want, str) and isinstance(got, str):
            matched += int(want.strip().lower() == got.strip().lower())
        else:
            matched += int(got == want)
    return matched


def run_properties(props: list, input_text: str,
                   output: dict) -> tuple[bool, list, list]:
    """Returns (ok, failure_strings, failed_checks).

    failure_strings is unchanged from before C5(a) — human-readable, printed and
    stored in results/. failed_checks is the structured report-only companion:
    [{"bucket": "format"|"quality", "check": fn_name}] per failing check, safe to
    commit in a snapshot (no free text, so no model output). Pass/fail semantics
    are untouched: ok is False whenever ANY check fails, whatever its bucket.
    """
    failures = []
    failed_checks = []
    for fn_name, fn in props:
        try:
            res = fn(input_text, output)
            ok, msg = res if isinstance(res, tuple) else (bool(res), "")
        except Exception as exc:  # a broken check is a failed check, loudly
            ok, msg = False, f"check raised: {exc}"
        if not ok:
            failures.append(f"{fn_name}: {msg}")
            # fn.bucket unguarded on purpose: load_checks validated it; a props
            # list built any other way must crash here, not get a default bucket.
            failed_checks.append({"bucket": fn.bucket, "check": fn_name})
    return not failures, failures, failed_checks


# ---------------------------------------------------------------- execution

def _null_safe_sum(values: list) -> int | None:
    """Sum a list of ints, but None ("this backend didn't report tokens") poisons the
    whole total — a partial sum would silently misrepresent "unknown" as a real number."""
    if any(v is None for v in values):
        return None
    return sum(values)


def combine_metrics(steps: list[dict]) -> dict:
    """Aggregate per-call metrics dicts (one per model.generate() call) into one —
    used both to roll a trajectory's steps into one case metric, and to roll a whole
    exam's per-case metrics into the result's totals block."""
    return {
        "prompt_tokens": _null_safe_sum([s["prompt_tokens"] for s in steps]),
        "completion_tokens": _null_safe_sum([s["completion_tokens"] for s in steps]),
        "total_tokens": _null_safe_sum([s["total_tokens"] for s in steps]),
        "wall_ms": round(sum(s["wall_ms"] for s in steps), 1),
        "retries": sum(s["retries"] for s in steps),
        # E24: where the completion budget WENT. Chars, never tokens — no local
        # provider reports a reasoning token count (router.py has the evidence).
        # .get() with a default so metrics dicts written before this field existed
        # aggregate as 0 rather than raising.
        "content_chars": _null_safe_sum([s.get("content_chars") for s in steps]),
        "reasoning_chars": _null_safe_sum([s.get("reasoning_chars") for s in steps]),
        # TERMINATION-DETECT D1/D3: COUNTS, not strings. A trajectory is several calls
        # and a single `finish_reason` string cannot aggregate honestly across them —
        # "which one truncated?" has no one-word answer. finish_reason itself stays on
        # the PER-CALL metrics dict (call_model), where it is unambiguous; these two
        # are what survives a roll-up.
        #
        # Both are _null_safe_sum'd on purpose: a metrics dict written before this
        # lane, or one from a backend that omits finish_reason, contributes None and
        # poisons the total to None. Unknown is not zero (the rule _empty_usage states).
        "truncated_calls": _null_safe_sum([s.get("truncated_calls") for s in steps]),
        "unanswered_calls": _null_safe_sum([s.get("unanswered_calls") for s in steps]),
    }


def call_model(agent, adapter, model, messages) -> tuple[dict, str, dict]:
    """One model call incl. retries. Returns (parsed, raw, metrics) where metrics is
    {prompt_tokens, completion_tokens, total_tokens, wall_ms, retries, content_chars,
    reasoning_chars} — token counts are None when the backend doesn't report usage
    (never guessed). The two char counts are E24: they say where the completion budget
    went (answer vs thinking) without inventing a token split no provider reports."""
    start = time.perf_counter()
    try:
        parsed, raw, meta, retries = call_with_retry(
            lambda: adapter.generate(
                messages, model,
                temperature=agent.get("temperature", 0.0),
                max_tokens=agent.get("max_tokens", 2048)),
            extract_json)
    except ParseFailure as exc:
        # R7 gap: the model answered, unparseably, after every re-ask. The call was
        # real and paid for, so its metrics are built by the SAME function as a
        # successful call's and ride on the exception for the boundary that catches
        # it (_run_tool_loop). Callers that don't catch ParseFailure see exactly the
        # ValueError they always did.
        exc.metrics = _call_metrics(exc.meta or {},
                                    round((time.perf_counter() - start) * 1000, 1),
                                    exc.attempts - 1)
        raise
    wall_ms = round((time.perf_counter() - start) * 1000, 1)
    return parsed, raw, _call_metrics(meta, wall_ms, retries)


def _call_metrics(meta: dict, wall_ms: float, retries: int) -> dict:
    """The per-call metrics dict — ONE builder for the success path and the
    parse-failure path of call_model, so a broken call is metered by the same
    rules as a clean one (field set, None-never-zero, D1 tripwires)."""
    finish_reason = meta.get("finish_reason")
    content_chars = meta.get("content_chars")
    metrics = {
        "prompt_tokens": meta.get("prompt_tokens"),
        "completion_tokens": meta.get("completion_tokens"),
        "total_tokens": meta.get("total_tokens"),
        "wall_ms": wall_ms,
        "retries": retries,
        "content_chars": content_chars,
        "reasoning_chars": meta.get("reasoning_chars"),
        # TERMINATION-DETECT D1. finish_reason is unambiguous here (one call), so it is
        # carried verbatim; the two counters beside it are the same fact in a form that
        # survives combine_metrics' roll-up across a trajectory's calls.
        "finish_reason": finish_reason,
        # None, not 0, when the backend did not report a reason: a call we know nothing
        # about is not a call we know was untruncated.
        "truncated_calls": (None if finish_reason is None
                            else int(finish_reason == "length")),
        # DECLARED TRIPWIRE, not an observable of model behaviour. With the real
        # ChatCompletionsAdapter this can never exceed 0 in a RETURNED metrics dict:
        # D2 raises TerminationError on empty content, so a zero-content call never
        # reaches this line. It stays because it is the cheapest possible assertion
        # that D2 has no hole — if this ever sums above 0, some adapter path is
        # handing scoring a response with no answer in it. (Reachable, and seen at 1,
        # from a scripted adapter: sandbox/test_termination.py.)
        "unanswered_calls": (None if content_chars is None
                             else int(content_chars == 0)),
    }
    return metrics


def _with_lessons(agent: dict, system: str, case_input: str) -> str:
    """E6-train: append retrieved lessons to a fully-assembled system prompt.

    AFTER everything static, because prompt-prefix reuse is real and large on our
    router path — a varying prefix costs ~+4.7 s/call (~60% of wall) at a 2k-token
    prompt (docs/probes/prefix-cache-2026-09-09/RESULTS.md). Lessons vary per case,
    so they go last; the frozen block stays cache-hot.

    When the agent has no library (every committed agent today), or retrieval
    finds nothing relevant, the return value is BYTE-IDENTICAL to `system` —
    the same zero-diff contract _trajectory_system_prompt keeps for
    `tools_offered`, and what keeps every existing score untouched.

    KNOWN GAP, on purpose: the E21 bake-off path (_BakeoffCtx.call_*) builds its
    system prompts directly and does NOT pass through here — bake-off is a
    read-only probe that writes no snapshot and moves no gate. If an agent with
    a library is ever bake-off-tested, its lessons will silently not inject
    there; wire it through this function in that lane, not before."""
    lessons = agent.get("_lessons")
    if not lessons:
        return system
    picked = library.retrieve(lessons, case_input, agent.get("library_k", 2))
    return system + library.render(picked)


def run_plain_case(agent, case, adapter, model) -> tuple[dict, dict]:
    messages = [{"role": "system",
                 "content": _with_lessons(agent, agent["system_prompt"], case["input"])},
                {"role": "user", "content": case["input"]}]
    parsed, _raw, metrics = call_model(agent, adapter, model, messages)
    return parsed, metrics


def _trajectory_system_prompt(agent: dict, case: dict) -> str:
    """The system prompt for ONE trajectory case.

    E10 rung B: an optional case-level "tools_offered" key — a list of roster lines
    ("name(sig) — description") — is appended to the agent's frozen system prompt
    FOR THAT CASE ONLY, so decoy tools are genuinely visible to the model (a roster
    described merely in the case INPUT is ignorable, and was ignored — PR #20).
    When the key is absent the return value is byte-identical to
    agent["system_prompt"], which is what keeps every pre-existing case's prompt,
    and therefore its score, untouched. agents/*/prompt.md stays frozen: a global
    roster edit would move every case at once.

    Fail loud: a malformed roster raises rather than being silently skipped —
    a rung-B case whose decoys were never shown would pass vacuously."""
    offered = case.get("tools_offered")
    if offered is None:
        return agent["system_prompt"]
    if (not isinstance(offered, list) or not offered
            or not all(isinstance(t, str) and t.strip() for t in offered)):
        raise ValueError(f"tools_offered must be a non-empty list of roster-line "
                         f"strings, got {offered!r}")
    roster = "\n".join(f"- {line}" for line in offered)
    return (agent["system_prompt"]
            + "\n\nFor THIS request a larger tool roster is active. These are ALL "
              "the tools available right now (this list replaces the one above; "
              "the protocol is unchanged):\n" + roster)


def _call_key(tool: str, args: dict) -> tuple[str, str]:
    """The identity of a tool call. ONE function, used by both the dedupe guard in
    run_trajectory_case and the redundancy monitor in score_trajectory — raw args,
    sorted keys, no other normalization. They must never drift: if the guard
    suppressed calls the monitor still counted as distinct, the A/B's effect size
    would be an artifact of the two sides disagreeing about what a duplicate is.

    Declared gap (gate-0 finding, 2026-08-26): a case-variant duplicate
    ('Janssens Bakery' vs 'janssens bakery') is invisible to BOTH, by decision."""
    return (tool, json.dumps(args, sort_keys=True, ensure_ascii=False))


def _run_tool_loop(agent, messages: list, expected: dict, adapter, model, tools_mod,
                   dedupe_tools: bool = False) -> tuple[dict, dict, list]:
    """Tool loop: model emits {"tool": ..., "args": {...}} or {"answer": "..."}.
    Runner-internal — MULTITURN-EXAM's extraction of run_trajectory_case's loop
    body so it can be reused, unchanged, once per turn (each call is a fresh,
    independent loop: a fresh step counter and a fresh dedupe `cache`, by
    construction of being a new function call with fresh locals — there is no
    step/cache state shared across two calls to this function).

    `messages` is MUTATED in place: the system+prior-history prefix the caller
    built is appended to (tool-call/tool-result exchanges, and — new in this
    lane — the final assistant answer once one is emitted) so a caller building
    a multi-turn conversation can pass the SAME list into the next turn's call
    and get full-history context for free. A single-turn caller that discards
    `messages` after this returns is unaffected: nothing about the RETURNED
    (parsed, trace) values depends on what happens to `messages` afterward.

    Returns (parsed, trace, step_metrics) — step_metrics is the raw per-call
    metrics list (NOT part of `trace`, so trace's key set stays exactly what it
    was before this lane: {"tools_called", "tool_calls", "tool_results", "steps",
    "metrics"} plus the pre-existing conditional "deduped_calls"/"termination"
    keys). A caller needing the FIRST call's prompt_tokens alone (multi-turn
    per-turn metrics, criterion 3) reads step_metrics[0]; trace["metrics"] stays
    the combine_metrics() total it always was.

    dedupe_tools (gate-0 intervention, default OFF) is the runtime half of the
    redundancy monitor: the monitor GRADES a repeated call post-hoc, this suppresses
    it live, so an A/B has an on/off switch to measure. When on, a call whose
    (tool, args) key already executed successfully this run is not re-executed — the
    cached result is fed back to the model and the call is kept out of
    trace["tool_calls"] (so the monitor cannot fire on it) and recorded in
    trace["deduped_calls"] instead, so the exposure stays countable.

    A suppressed call still CHARGES its step (amendment 1, after pass-1 review). It
    is a real model turn: refunding it made trace["steps"] undercount actual
    generate() calls, and the A/B's two sides then no longer ran on the same budget —
    which is the comparison gate 0 exists to make. Guard ON and guard OFF make the
    same number of model calls for the same scripted model; that is pinned in
    sandbox/test_dedupe_tools.py, not assumed here.

    The cache holds ONLY results of executions that did not raise. An identical
    retry after a raised error re-executes and stays fully graded — redundancy AND
    error_recovery's spiralled clause — exactly as it would with the flag off. An
    intervention may not make an existing check unfireable, and five committed
    error_recovery cases sit on the raising fixture. A tool that RETURNS an
    error-shaped dict without raising (the no-record case) is a normal result and is
    dedupe-eligible.

    With the flag OFF every branch below is inert: the cache is written but never
    read, no deduped_calls key is attached, and the loop is the same
    `for _step in range(max_steps)` it always was. The committed gate and every
    existing snapshot depend on that."""
    max_steps = expected.get("max_steps", 4)
    called = []
    tool_calls = []    # [{"tool", "args"}] per call — the redundancy monitor's feed
    tool_results = []  # what the tools actually RETURNED — the grounding corpus.
    parsed: dict = {}  # Results used to live only inside `messages`, where the scorer
    step_metrics = []  # could never see them; now they ride the trace (Stage 3).
    cache: dict = {}   # call key -> the result of that key's first CLEAN execution
    deduped_calls: list = []  # suppressed repeats, for the A/B's exposure count
    termination: dict | None = None  # D2: set only when a call emitted no answer
    protocol_break: dict | None = None  # R7: set only when a call was unparseable
    for _step in range(max_steps):
        try:
            parsed, raw, metrics = call_model(agent, adapter, model, messages)
        except ParseFailure as exc:
            # R7 GAP (2026-09-04). The model ANSWERED — in prose, markdown, anything
            # extract_json cannot find an object in — and the re-ask did not help.
            # This used to escape as a bare ValueError all the way to run_exam's
            # case boundary, which recorded `got = {"error": ...}` and an EMPTY
            # detail: every tool call, result and token count gathered so far, and
            # for a `turns` case every OTHER turn's verdict, was wiped. 3 of the 2B
            # champion's committed crm records and 12 of the 4B's were invisible that
            # way (results/, check == "error").
            #
            # Handled exactly like a D2 death, one clause up: the loop stops, the
            # evidence survives, and a structured record says what happened. The
            # call is METERED (call_model built its metrics before re-raising) and
            # the raw text is appended as the assistant's turn so a later turn's
            # history is faithful — the model DID say this. parsed is {} so
            # answer_present co-fires, the same declared co-firing D2 has; the
            # verdict is unchanged by construction (a parse failure failed the
            # case before, and _score_one_turn forces it False now).
            step_metrics.append(exc.metrics)
            messages.append({"role": "assistant", "content": exc.raw})
            protocol_break = {"cause": "unparseable", "step": _step,
                              "retries": exc.attempts - 1,
                              "content_chars": len(exc.raw or ""),
                              "raw_head": (exc.raw or "")[:200]}
            parsed = {}
            break
        except TerminationError as exc:
            # TERMINATION-DETECT D2, trajectory half. Handled at the SAME call boundary
            # as plain mode and recorded the same way, then the loop stops: a model
            # that emitted nothing has nothing to feed back into the conversation.
            #
            # We break rather than let the exception abort the case, because everything
            # gathered BEFORE the death — tools_called, tool_calls, tool_results, steps
            # — is the attribution this lane exists to produce. An aborting exception
            # would discard it and leave a reader unable to tell a mid-loop death from
            # a model that never called a tool at all.
            #
            # parsed is reset to {} so score_trajectory sees no answer: it will ALSO
            # fail answer_present. That co-firing is correct and declared — the
            # termination entry says the model was cut off, answer_present says the
            # case has no answer, and a trajectory death must stay distinguishable
            # from a model that finished its loop and chose not to answer.
            termination = {"cause": "no_answer", **exc.details}
            parsed = {}
            break
        step_metrics.append(metrics)
        if "answer" in parsed:
            # Appended so a caller reusing `messages` for a later turn (MULTITURN-
            # EXAM) sees this turn's answer as part of full-history context. Inert
            # for a single-turn caller: `messages` is discarded right after this
            # function returns, and nothing about the RETURNED (parsed, trace)
            # depends on this append — byte-identity of the single-turn path holds.
            messages.append({"role": "assistant", "content": raw})
            break
        if "tool" in parsed:
            name = parsed["tool"]
            args = parsed.get("args", {})
            key = _call_key(name, args)
            if dedupe_tools and key in cache:
                # Suppressed repeat: serve the cached result, never re-execute the
                # tool, and leave no tool_calls entry the monitor could grade. The
                # step is still spent — this was a real model turn.
                tool_result = cache[key]
                deduped_calls.append({"tool": name, "args": args})
            else:
                called.append(name)
                tool_calls.append({"tool": name, "args": args})
                fn = getattr(tools_mod, name, None)
                cacheable = False
                if fn is None:
                    # Not an execution at all — never cached, so a repeated unknown
                    # tool keeps failing the same way with the flag on or off.
                    tool_result = {"error": f"unknown tool {name!r}"}
                else:
                    try:
                        tool_result = fn(**args)
                        cacheable = True
                    except Exception as exc:
                        tool_result = {"error": str(exc)}
                tool_results.append(tool_result)
                if cacheable:
                    cache[key] = tool_result
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user",
                             "content": json.dumps({"tool_result": tool_result},
                                                   ensure_ascii=False)})
        else:
            break  # neither tool nor answer: protocol violation, scored below
    # steps counts the model turns that produced a tool call, plus the answer turn.
    # A SUPPRESSED duplicate was a real model turn too, so under the guard it is
    # counted as well: otherwise the ON side's steps drift below the OFF side's for
    # the identical script, a max_steps failed_check can vanish purely because the
    # guard ran, and an A/B counting failed_checks entries over-counts the
    # intervention's effect. Both increments sit inside `if dedupe_tools`, so the
    # flag-off value is the untouched pre-existing len(called) + 1.
    steps = len(called) + 1
    if dedupe_tools:
        steps += len(deduped_calls)
        # deduped_calls is attached ONLY when the guard ran. With the flag off the
        # trace's key set must be literally what it was before this intervention
        # existed.
        trace_extra = {"deduped_calls": deduped_calls}
    else:
        trace_extra = {}
    if termination is not None:
        # Attached ONLY on a death, for the same reason deduped_calls is attached only
        # under the guard: on every healthy run the trace's key set must be literally
        # what it was before this lane (asserted against a literal fixture in
        # sandbox/test_dedupe_tools.py:430, which must stay green unchanged).
        trace_extra = {**trace_extra, "termination": termination}
    if protocol_break is not None:
        # Same rule: attached only on the event (sandbox/test_protocol_break.py).
        trace_extra = {**trace_extra, "protocol_break": protocol_break}
    return parsed, {"tools_called": called, "tool_calls": tool_calls,
                     "tool_results": tool_results, "steps": steps,
                     "metrics": combine_metrics(step_metrics), **trace_extra}, step_metrics


def run_trajectory_case(agent, case, adapter, model, tools_mod,
                        dedupe_tools: bool = False) -> tuple[dict, dict]:
    """A case WITHOUT `turns`: build the system+user prefix, run ONE independent
    tool loop over it via `_run_tool_loop`, return (parsed, trace) — byte-identical
    to this function's pre-MULTITURN-EXAM body (criterion 1's witness), because the
    loop body itself did not change, only moved. `dedupe_tools` and every existing
    caller's signature expectation (sandbox/test_termination.py,
    sandbox/test_dedupe_tools.py, sandbox/test_trajectory_checks.py,
    sandbox/test_observability.py, sandbox/test_instrument_fixes.py,
    sandbox/test_error_recovery_falsepos.py, `runner.py live`'s
    live_run_and_log) are unchanged: this function's signature and return shape
    are exactly what they were before this lane."""
    messages = [{"role": "system",
                 "content": _with_lessons(agent, _trajectory_system_prompt(agent, case),
                                          case["input"])},
                {"role": "user", "content": case["input"]}]
    parsed, trace, _step_metrics = _run_tool_loop(
        agent, messages, case["expected"], adapter, model, tools_mod,
        dedupe_tools=dedupe_tools)
    return parsed, trace


def _turn_expected(case: dict, k: int, turn_text: str) -> dict:
    """Resolve turn k's expected block for a `turns`-bearing case.

    Matched to the input turn by POSITION AND literal text equality against the
    committed `turns_expected[k]["turn"]` — the recap `_exp` discipline
    (evals/recap/properties.py), restated here for multi-turn: an input turn whose
    text does not match the committed record at that position RAISES rather than
    scoring vacuously. `turns` and `turns_expected` are two parallel committed
    lists specifically so they CAN drift out of sync (an edit to one without the
    other) — a single combined turn+expected object per position would make this
    check unfireable by construction."""
    turns_expected = case.get("turns_expected") or []
    if k >= len(turns_expected):
        raise ValueError(
            f"{case.get('id', '?')}: turn {k} has no committed turns_expected "
            f"entry (only {len(turns_expected)} committed)")
    entry = turns_expected[k]
    committed_text = entry.get("turn")
    if committed_text != turn_text:
        raise ValueError(
            f"{case.get('id', '?')}: turn {k} input {turn_text!r} does not match "
            f"the committed turn text {committed_text!r} at turns_expected[{k}] — "
            f"turns and turns_expected have drifted out of sync")
    return entry["expected"]


def _score_one_turn(parsed: dict, trace: dict, expected: dict, input_text: str,
                    turn_index: int | None = None) -> tuple[bool, list, list]:
    """The ONE call site of score_trajectory( in this file (criterion 9) — every
    trajectory-mode verdict, single-turn or per-turn, is produced here. Relocates
    BOTH pre-MULTITURN-EXAM pieces of attempt()'s trajectory branch verbatim: the
    outer score_trajectory(...) call (master runner.py:920-921) and the D2
    termination-override block that followed it (master runner.py:924-935) — the
    same override, same ordering (termination entry inserted FIRST), same forced
    `passed = False`. Behavior for `turn_index=None` (a case without `turns`) is
    unchanged from master's.

    `turn_index` is the ONLY new behavior: when given (a turns-aware call), EVERY
    failed_checks entry produced here — the quality entries from `failures` as
    well as the termination entry — gains a "turn" key (criterion 2: "each
    failed_checks entry names its turn"), while the no-turns call keeps the
    original two-key {"bucket", "check"} shape byte-identical for every entry
    (criterion 1/(9a))."""
    passed, failures = score_trajectory(parsed, trace, expected, input_text)
    failed_checks = [{"bucket": "quality", "check": _trajectory_check_id(f),
                      **({"turn": turn_index} if turn_index is not None else {})}
                     for f in failures]
    if "termination" in trace:
        # D2: BOTH entries, by decision — see master's comment, preserved verbatim
        # in intent. passed is forced False rather than relied upon: the co-firing
        # check is what makes it False today, and a verdict must not depend on
        # another check continuing to exist.
        passed = False
        entry = {"bucket": "termination", "check": "termination"}
        if turn_index is not None:
            entry["turn"] = turn_index
        failed_checks.insert(0, entry)
    if "protocol_break" in trace:
        # R7: the model's output could not be parsed — an output-SHAPE fault, so it
        # files under the declarable "format" bucket, not "termination" (the model
        # did answer) and not "quality" (there is no answer to judge). Forced False
        # for the same reason as the death above; answer_present co-fires, declared.
        passed = False
        entry = {"bucket": "format", "check": "unparseable"}
        if turn_index is not None:
            entry["turn"] = turn_index
        failed_checks.insert(0, entry)
    return passed, failures, failed_checks


ASSEMBLY_MODES = ("full", "scoped")


def _scope_tokens(text: str) -> set:
    """Word tokens (>= 3 chars, lower-cased) used ONLY to decide which prior tool
    exchanges a scoped turn keeps. Deliberately NOT a scoring normaliser: it never
    touches grounding, answer_contains or digit checks (CLAUDE.md gotcha 4 — a
    selection rule and a presence/absence check must never share a helper)."""
    return {t.lower() for t in re.findall(r"\w+", text) if len(t) >= 3}


def _scoped_context(history: list, turn_text: str) -> tuple[list, int]:
    """E27 scoped assembly — a per-call PROJECTION of the full history, rule-based
    and deterministic (no model-judged relevance). Returns (context, dropped):
    context is a NEW list — system prompt, then the retained prior messages in their
    original order; `history` itself is never mutated, so the next turn scopes from
    the complete record again.

    Kept: (i) the immediately previous assistant message, when it is a final answer
    (not a tool call — a turn that died mid-loop leaves no answer to keep); (ii) every
    prior tool exchange (assistant tool-call + its user tool_result) whose CALL ARGS
    share a `_scope_tokens` token with the current turn's text — the args are where
    the company name lives; matching on the 4k-char payloads instead would retain
    nearly everything and scope nothing. Dropped: every prior user turn, every other
    exchange and answer. A referential callback ("the FIRST company we discussed")
    names nothing, so it keeps nothing but the last answer — that silent scope-drop
    is the failure mode this arm exists to price, not a bug to paper over."""
    want = _scope_tokens(turn_text)
    kept: list = [history[0]]
    dropped = 0
    i = 1
    while i < len(history):
        msg = history[i]
        nxt = history[i + 1] if i + 1 < len(history) else None
        is_exchange = (msg["role"] == "assistant" and nxt is not None
                       and nxt["role"] == "user"
                       and nxt["content"].startswith('{"tool_result"'))
        if is_exchange:
            args = (extract_json(msg["content"]) or {}).get("args", {})
            arg_text = " ".join(str(v) for v in args.values()) if isinstance(args, dict) else ""
            if want & _scope_tokens(arg_text):
                kept.extend((msg, nxt))
            else:
                dropped += 2
            i += 2
            continue
        if i == len(history) - 1 and msg["role"] == "assistant":
            kept.append(msg)   # (i) the previous turn's final answer
        else:
            dropped += 1
        i += 1
    return kept, dropped


def _run_turns(agent, case, adapter, model, tools_mod,
              dedupe_tools: bool = False,
              assembly: str = "full") -> tuple[dict, dict, bool, list, list]:
    """Score a `turns`-bearing case: turn k gets its OWN independent tool loop — a
    fresh call to `_run_tool_loop` every turn, which means a fresh step counter and
    a fresh dedupe `cache` every turn BY CONSTRUCTION (this is the NEW loop-internal
    reset the criterion requires; it is unrelated to, and does not touch, the
    existing --dedupe-tools CLI cache/flag, which stays exactly as it is). Context
    is FULL-HISTORY: `messages` accumulates the system prompt, then every turn's
    user message, tool exchanges, and final assistant answer, in order — no
    filtering, no summarising (E27's scoped-assembly A/B is explicitly out of this
    lane). Each turn is scored against its own expected block (`_turn_expected`,
    position+text matched); the case passes iff every turn passes, and every
    failed_checks entry names its turn (`_score_one_turn(..., turn_index=k)`).

    Grounding is the one place a turn's SCORING trace deliberately differs from its
    own execution trace: `score_trajectory`'s grounded-answer corpus is built from
    `tool_results` + `input_text`, and the cross-turn-grounding shape this lane
    exists to measure (a turn-3 answer citing a fact fetched in turn 1) requires
    that corpus to ACCUMULATE across turns. `tool_calls`/`tools_called`/`steps`
    stay strictly PER-TURN in the recorded trace — accumulating those too would
    make the redundancy monitor and `tools_not_called` fire across a turn boundary
    that never happened (CLAUDE.md gotcha 4: presence checks and absence checks
    must never share an over-eager normalization).

    P1 fix (pass 3): `score_trajectory` also has an INDEX-PAIRED consumer
    (`_error_recovery_failures` clause 1, zip(tool_calls, tool_results)) that the
    accumulated `tool_results` corpus above silently misaligns for any turn after
    the first — `tool_calls` stays per-turn while `tool_results` doesn't, so a
    positional zip pairs a later turn's call against an earlier turn's result.
    `scoring_trace` below therefore carries BOTH shapes: `tool_results` stays the
    accumulated membership corpus clause 4/grounding need, and a NEW
    `tool_results_this_turn` key carries this turn's own results, correctly
    aligned with `tool_calls`, for clause 1's index-paired lookup."""
    if assembly not in ASSEMBLY_MODES:
        raise ValueError(f"assembly must be one of {ASSEMBLY_MODES}, got {assembly!r}")
    # E6-train: a turns-bearing case has no "input" key — retrieval keys on the
    # full turn sequence (the system prompt is built ONCE, before turn 1, so the
    # whole case is the honest similarity target; keying on turn 1 alone would
    # retrieve against a greeting). Caught by evals/test_multiturn.py going red
    # on a case["input"] KeyError in this lane's first gate run.
    messages = [{"role": "system",
                 "content": _with_lessons(agent, _trajectory_system_prompt(agent, case),
                                          "\n".join(case["turns"]))}]
    turn_texts: list = []
    scoring_tool_results: list = []
    all_step_metrics: list = []
    turn_entries: list = []
    all_failures: list = []
    all_failed_checks: list = []
    all_passed = True
    last_parsed: dict = {}
    all_deduped_calls: list = []
    for k, turn_text in enumerate(case["turns"]):
        expected_k = _turn_expected(case, k, turn_text)
        turn_texts.append(turn_text)
        # E27 SCOPED-ASSEMBLY: `messages` stays the FULL history (the record every
        # turn scopes from); under "scoped" a turn k >= 1 hands the model a fresh
        # projection of it instead, and whatever the loop appends to that projection
        # (this turn's user message, exchanges, answer) is spliced back onto the
        # full history afterwards. Under "full" — and at turn 0 in either mode —
        # `context is messages`, the very same list object the pre-E27 code mutated,
        # so the default path is byte-identical by construction, not by test alone.
        if assembly == "scoped" and k >= 1:
            context, dropped_k = _scoped_context(messages, turn_text)
        else:
            context, dropped_k = messages, 0
        splice_from = len(context)
        context.append({"role": "user", "content": turn_text})
        parsed_k, trace_k, step_metrics_k = _run_tool_loop(
            agent, context, expected_k, adapter, model, tools_mod,
            dedupe_tools=dedupe_tools)
        if context is not messages:
            messages.extend(context[splice_from:])
        last_parsed = parsed_k
        scoring_tool_results.extend(trace_k["tool_results"])
        # P1 fix (pass 3, criterion 2a): "tool_results" is overwritten with the
        # ACCUMULATED cross-turn corpus (grounding/digit checks need every turn's
        # results); "tool_results_this_turn" carries trace_k's own PER-TURN list,
        # correctly index-paired against the per-turn "tool_calls" already in
        # trace_k, for the index-paired consumers inside score_trajectory
        # (currently only _error_recovery_failures clause 1). A no-turns caller
        # never sets this key, so _error_recovery_failures' fallback to
        # trace["tool_results"] reproduces exactly the pre-lane single-turn
        # behavior (criterion 1).
        scoring_trace = {**trace_k, "tool_results": list(scoring_tool_results),
                         "tool_results_this_turn": trace_k["tool_results"]}
        passed_k, failures_k, failed_checks_k = _score_one_turn(
            parsed_k, scoring_trace, expected_k, "\n".join(turn_texts), turn_index=k)
        all_step_metrics.extend(step_metrics_k)
        turn_metrics_k = combine_metrics(step_metrics_k) if step_metrics_k else None
        entry = {
            "turn": k,
            "tools_called": trace_k["tools_called"],
            "tool_calls": trace_k["tool_calls"],
            "steps": trace_k["steps"],
            "passed": passed_k,
            "failures": failures_k,
            # Criterion 3: prompt_tokens is the FIRST model call of the turn (the
            # context size at the moment the turn begins, before this turn's own
            # intra-turn tool-loop growth adds to it); completion_tokens/wall_ms
            # are the TURN TOTAL across the whole intra-turn tool loop.
            "prompt_tokens": step_metrics_k[0]["prompt_tokens"] if step_metrics_k else None,
            "completion_tokens": (turn_metrics_k or {}).get("completion_tokens"),
            "wall_ms": (turn_metrics_k or {}).get("wall_ms"),
        }
        if "deduped_calls" in trace_k:
            entry["deduped_calls"] = trace_k["deduped_calls"]
            all_deduped_calls.extend(trace_k["deduped_calls"])
        if "termination" in trace_k:
            entry["termination"] = trace_k["termination"]
        if "protocol_break" in trace_k:
            # R7: the marker sits on the turn that broke; later turns still run.
            entry["protocol_break"] = trace_k["protocol_break"]
        if assembly != "full":
            # Gated like deduped_calls: a scoped results file is self-describing
            # (every turn says which arm and how much history it lost), while a
            # "full" run adds NO key anywhere — its records stay byte-identical to
            # master's (that is the E27 baseline arm, and the committed snapshot).
            entry["assembly"] = assembly
            entry["history_msgs_dropped"] = dropped_k
        turn_entries.append(entry)
        all_failures.extend(f"turn {k}: {f}" for f in failures_k)
        all_failed_checks.extend(failed_checks_k)
        all_passed = all_passed and passed_k

    trace = {
        "turns": turn_entries,
        "tools_called": [t for e in turn_entries for t in e["tools_called"]],
        "steps": sum(e["steps"] for e in turn_entries),
        # Existing-totals floor (CRITERION-ADVISORIES item 3): the case-level
        # aggregate stays present, in addition to the new per-turn breakdown above
        # — this is what runner.py:1064's metrics_totals harvest reads.
        "metrics": combine_metrics(all_step_metrics),
    }
    if dedupe_tools:
        # Case-level roll-up, same convention as _run_tool_loop's own
        # dedupe_tools-gated key: attached whenever the guard ran (even if empty),
        # so a case-level consumer (sandbox/test_dedupe_tools.py's
        # _deduped_cases()) finds the suppressed-repeat exposure count without
        # having to know about the per-turn breakdown inside "turns".
        trace["deduped_calls"] = all_deduped_calls
    return last_parsed, trace, all_passed, all_failures, all_failed_checks


def score_case(agent, case, adapter, model, tools_mod,
              dedupe_tools: bool = False,
              assembly: str = "full") -> tuple[dict, dict, bool, list, list]:
    """THE single chokepoint (criterion 9): the ONLY function that produces a
    trajectory-mode case's (passed, failures, failed_checks). attempt()'s
    trajectory branch assigns `passed`/`failures` from this function's return and
    from nowhere else — the pre-MULTITURN-EXAM outer `score_trajectory(...)` call
    and the D2 termination-override block that used to sit in attempt() (master
    runner.py:920-935) are both DELETED from there and relocated, behavior
    preserved, into `_score_one_turn` above, which this function calls.

    No `turns`: exactly one `_score_one_turn` evaluation over the existing
    `run_trajectory_case` — unchanged semantics (criteria 1 and 9a are the
    witness, not this docstring). With `turns`: the per-turn conjunction via
    `_run_turns`.

    Returns (parsed, trace, passed, failures, failed_checks) — `trace` is what
    attempt() splices into `detail` via `detail.update(trace)`, exactly as the
    pre-lane `trace` from run_trajectory_case was."""
    if "turns" not in case:
        parsed, trace = run_trajectory_case(agent, case, adapter, model, tools_mod,
                                            dedupe_tools=dedupe_tools)
        passed, failures, failed_checks = _score_one_turn(
            parsed, trace, case["expected"], case["input"], turn_index=None)
        return parsed, trace, passed, failures, failed_checks
    # `assembly` is consumed ONLY here: a no-`turns` case has no history to scope,
    # so run_trajectory_case never sees the knob (E27 criterion 4 by construction).
    return _run_turns(agent, case, adapter, model, tools_mod, dedupe_tools=dedupe_tools,
                      assembly=assembly)


def _date_parts(tok: str):
    """Numeric components of a separator-bearing token, as a sorted tuple with leading
    zeros dropped — or None if it isn't date-like. A date is ONE fact whose written
    order is a formatting choice: a tool's "2026-03-11" and a model's "3/11/2026" are
    the same day, so both canonicalize to (3, 11, 2026). Comparing whole digit-strings
    instead would fail a correctly-grounded reformat (observed on crm-followup's
    status-churned, 2026-07-22), and comparing loose components would pass a wrong day.

    Splits on ',' as well as [-/.] (F1, docs/exam-audit-2026-07-22.md §A0): a
    comma-decimal like '65,00' used to skip the date path entirely, fall through to
    plain number grounding, and false-pass via _norm_digits('65,00') == '6500'. Now
    it is date-shaped — locale-ambiguous, so it is NOT normalized and must be
    grounded as-is (fail closed, the harder direction). The one exception is a token
    in the UNAMBIGUOUS thousands-grouped shape ('6.500', '1,234,567.89'): that is a
    NUMBER, not a date, and is handed to number grounding where strip_thousands /
    _norm_digits correctly recognize it."""
    tok = tok.rstrip(".,/-")  # trailing separator is punctuation, not data
    if strip_thousands(tok) != tok:
        return None  # unambiguous thousands-grouped number — not a date
    parts = [p for p in re.split(r"[-/.,]", tok) if p.isdigit()]
    return tuple(sorted(int(p) for p in parts)) if len(parts) >= 2 else None


def _norm_digits(text: str) -> str:
    """Strip digit-grouping and date punctuation, same normalization answer_contains
    uses — '9,000' and '9000' are the same number, not two facts. '-' and '/' are
    stripped too so a date compares on its digits ('2026-07-02' -> '20260702') and a
    fabricated day no longer hides behind a matching year."""
    return (text.lower().replace(",", "").replace(".", "")
            .replace("-", "").replace("/", ""))


def _is_numeric_needle(needle: str) -> bool:
    """True for needles that are a number or a date ('6500', '2026-07-02') — digits
    plus separators only. Anything with letters is a text needle."""
    return bool(re.fullmatch(r"\d[\d.,/-]*", needle.strip()))


def _needle_matches(needle: str, answer: str, norm_answer: str) -> bool:
    """One expected needle against the answer.

    Numeric needles match on a NUMBER-TOKEN BOUNDARY: the answer must contain a
    digit token whose normalized form EQUALS the needle's — '6,500' and '€6500'
    match an expected '6500', but '16500' and '65000' do not. Bare substring
    matching passed those (C4, reproduced 2026-07-22): '6500' is a substring of
    '16500', so quoting the wrong grounded row scored as correct.

    Normalization is strip_thousands, NEVER _norm_digits (F1, follow-up to C4):
    _norm_digits strips ',' and '.' indiscriminately, so '65,00' — the European
    comma-decimal for SIXTY-FIVE — matched an expected '6500'. strip_thousands
    removes only unambiguous thousands separators, so '6,500' and NL '6.500' still
    match while '65,00' and '65.00' fail. Date needles additionally accept a
    separator-swapped reformat ('2026/07/02' for an expected '2026-07-02') via
    digit-string comparison, gated on BOTH sides being date-shaped so a decimal can
    never ride that path.

    Text needles keep case-insensitive substring behaviour — a name inside a
    sentence is a legitimate partial match and must not become word-boundary-exact.
    """
    if _is_numeric_needle(needle):
        want = strip_thousands(needle.strip())
        want_digits = _norm_digits(want)
        want_is_date = _date_parts(want) is not None
        for tok in re.findall(r"\d[\d.,/-]*", answer):
            tok = tok.rstrip(".,/-")  # trailing separator is punctuation, not data
            if not tok:
                continue
            if strip_thousands(tok) == want:
                return True
            if (want_is_date and _date_parts(tok) is not None
                    and _norm_digits(tok) == want_digits):
                return True
        return False
    return needle.lower() in answer.lower() or _norm_digits(needle) in norm_answer


# ------------------------------------------------- error recovery (E10 rung A)

# How an answer may name a tool failure. PRESENCE side of the ack check only —
# over-matching errs toward passing, so a firing failure is always a real
# unacknowledged error. Never reuse for an absence check (normalization is
# directional — CLAUDE.md). Deliberately overlaps the abstention cases' vocabulary
# ("no record", "not found"): honestly reporting a no-record retry IS recovery.
_ERROR_ACK_VOCAB = (
    "error", "unavailable", "not available", "couldn't", "could not", "can't",
    "cannot", "unable", "failed", "failure", "failing", "timeout", "timed out",
    "time out", "not retrieve", "no record", "not found", "don't have",
    "do not have", "wasn't able", "was not able", "no data", "not reach",
    "not access", "inaccessible", "missing", "unknown", "not fetch", "no access",
    # Added 2026-08-05 (PR #43 probe): an honest acknowledgement phrased outside the
    # list above FALSE-FAILED — reproduced with "the deal information is presently
    # beyond my reach". Widening is safe in this direction and only in this one:
    # this is the PRESENCE side, so over-matching errs toward PASSING, and clause 3
    # additionally requires a fact term in the SAME sentence. Deliberately excludes
    # generic words ("issue", "problem", "down") that occur in ordinary CRM prose —
    # "the deal is down to negotiation" must not read as an outage.
    "beyond my reach", "beyond reach", "not able", "no longer available",
    "did not return", "returned nothing", "returned no", "not obtainable",
    "not retrievable", "unsuccessful", "no result", "not present", "outage",
    "not respond", "no response", "without access", "lack access",
)


def _ack_normalize(text: str) -> str:
    """Normalization for the acknowledgement scan ONLY: lowercase + straighten
    typographic apostrophes (U+2019/U+02BC), so an honest "couldn’t" matches the
    vocabulary's "couldn't" — reviewers reproduced that false-fail on PR #20.
    PRESENCE direction; never share with the fabrication scan below."""
    return text.replace("’", "'").replace("ʼ", "'").lower()


def _within_one_edit(a: str, b: str) -> bool:
    """True if `a` and `b` differ by at most one insertion, deletion or substitution.

    Hand-rolled rather than imported: this must stay dependency-free and its exact
    behaviour is load-bearing for the absence check below.
    """
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = j = diffs = 0
    while i < la and j < lb:
        if a[i] != b[j]:
            diffs += 1
            if diffs > 1:
                return False
            if la == lb:
                i += 1
            j += 1
        else:
            i += 1
            j += 1
    return True


def _typo_of_grounded(word: str, corpus_words: set) -> str | None:
    """Is `word` a MISSPELLING of a grounded word rather than an invention?

    Why this exists: an honest answer with a one-letter slip in a real name was
    scored as fabrication — measured 2026-08-05, "Els Merten" against a corpus
    holding "Mertens". That false positive punishes a CORRECT model, and it is the
    documented reason no deals_list-outage case was ever committed.

    ⚠️ THIS RELAXES AN ABSENCE CHECK, which is the direction CLAUDE.md warns about:
    over-normalize here and a real fabrication is waved through. So the relaxation is
    deliberately the narrowest thing that fixes the measured failure —

      BOTH words >= 5 chars AND edit distance exactly <= 1.

    That keeps the hole the original under-normalization existed to shut:
      'merten' ~ 'mertens'  -> typo, grounded          (distance 1, both >= 5)
      'jan'    ~ 'janssens' -> NOT matched             (len 3, and distance 5)
      'martens' ~ 'mertens' -> matched, ACCEPTED COST  (see below)

    The accepted cost is real and stated rather than hidden: an invented name that
    happens to sit one edit from a grounded one passes. Judged the better trade,
    because a name one letter from a name in the corpus is far more likely a
    transcription slip than an invention, and the alternative — failing honest
    answers — was measured, not hypothetical.
    """
    if len(word) < 5:
        return None
    for cw in corpus_words:
        if len(cw) >= 5 and _within_one_edit(word, cw):
            return cw
    return None


def _error_recovery_failures(er: dict, answer: str, trace: dict,
                             input_text: str) -> list:
    """E10 rung A: a case is CONSTRUCTED so that one declared tool fails
    deterministically (tools_mock forces the error) and the fact it was to supply
    stays unavailable. er = {"tool": <failing tool>, "fact": [terms naming that
    fact]} — an object, not a boolean, because every clause below is anchored to
    the DESIGNED outage (PR #20's boolean version anchored on the first error of
    any tool and matched ack vocabulary anywhere in the answer, so an incidental
    no-record error could steal the anchor and an unrelated apology could pass).

    Four clauses, all from the trace + answer:
      1. the declared tool actually errored — else the rung was never exercised
         and the case fails loud, never vacuously passes;
      2. no spiral: the identical failing call repeated after ITS error;
      3. the answer acknowledges, in one sentence, BOTH a failure term and the
         fact the failed tool was to supply — tying the ack to the outage;
      4. no fabricated stand-in for that fact: a mid-sentence capitalized word
         (a name — the one shape of fabrication the digit-only grounding check
         cannot see) must appear in the tool results or the input. ABSENCE
         direction: matching is exact lowercase word membership, deliberately
         under-normalized so an invented 'Jan' can never hide inside 'Janssens'.

    P1 fix (pass 3, criterion 2a): clause 1 is INDEX-PAIRED (zip(tool_calls,
    tool_results)) and must be evaluated against a SINGLE turn's own calls and
    results — never a different turn's. A turns-aware caller (`_run_turns`)
    supplies the turn's own per-turn results under `tool_results_this_turn`,
    correctly aligned with the equally per-turn `tool_calls` already in the
    trace; `trace["tool_results"]` itself stays the ACCUMULATED cross-turn
    corpus clause 4's membership test (and score_trajectory's own grounding/
    digit checks) legitimately need, and is left untouched. A no-turns caller
    never sets `tool_results_this_turn`, so `per_turn_results` below falls back
    to `trace["tool_results"]` — identical to pre-lane behavior, since a
    no-turns trace has only ever held one turn's worth of results anyway
    (criterion 1's byte-identity)."""
    if (not isinstance(er, dict) or not isinstance(er.get("tool"), str)
            or not er.get("fact") or not isinstance(er["fact"], list)):
        raise ValueError(f"error_recovery must be an object "
                         f"{{'tool': <failing tool>, 'fact': [terms...]}} — "
                         f"got {er!r} (a boolean cannot anchor the check)")
    failures: list = []
    tool = er["tool"]
    fact_terms = [str(t).lower() for t in er["fact"]]
    # P1 fix: index-paired against THIS turn's own results, not the accumulated
    # cross-turn corpus (see the docstring above) — a no-turns trace falls back
    # to trace["tool_results"], its only results list, unchanged from pre-lane.
    per_turn_results = trace.get("tool_results_this_turn", trace["tool_results"])

    # 1. Anchor on the DESIGNED outage: the first error result whose call was to
    # the declared tool. An earlier error on a different tool is not the anchor.
    err_idx = next((i for i, (call, result)
                    in enumerate(zip(trace["tool_calls"], per_turn_results))
                    if call["tool"] == tool
                    and isinstance(result, dict) and "error" in result), None)
    if err_idx is None:
        failures.append(f"error_recovery: designed outage never occurred — "
                        f"{tool!r} returned no error in this trace, so the rung "
                        f"was not exercised")
        return failures

    # 2. Spiral: the identical failing call again, after its error came back.
    failing = trace["tool_calls"][err_idx]
    fkey = json.dumps(failing, sort_keys=True, ensure_ascii=False)
    if any(json.dumps(c, sort_keys=True, ensure_ascii=False) == fkey
           for c in trace["tool_calls"][err_idx + 1:]):
        failures.append(f"error_recovery: spiralled — repeated the failing call "
                        f"{failing['tool']} with identical args {failing['args']} "
                        f"after receiving the error")

    # 3. Fact-tied acknowledgement: one sentence carrying both a failure term and
    # a fact term. Sentence-scoped so "sorry, my calendar sync failed" cannot
    # launder an answer that then presents the errored fact as retrieved.
    sentences = re.split(r"[.!?;\n]+", _ack_normalize(answer))
    if not any(any(v in s for v in _ERROR_ACK_VOCAB)
               and any(t in s for t in fact_terms) for s in sentences):
        failures.append(f"error_recovery: final answer never acknowledges that "
                        f"the {tool!r} fact ({', '.join(map(str, er['fact']))}) "
                        f"is unavailable — an apology about something else, or "
                        f"answering as if the lookup succeeded, is not recovery")

    # 4. Fabricated names: every mid-sentence Capitalized word in the answer must
    # be grounded. Word-set membership on exact lowercase words (absence checks
    # under-normalize); sentence-initial, ALL-CAPS and quoted-start tokens are
    # skipped so ordinary prose cannot false-fail.
    corpus_words = set(re.findall(
        r"[a-z]+",
        (json.dumps(trace["tool_results"], ensure_ascii=False)
         + " " + input_text).lower()))
    flagged: dict = {}
    for m in re.finditer(r"\b[A-Z][a-z]{2,}\b", answer):
        prev = answer[:m.start()].rstrip()
        if not prev or prev[-1] in ".!?;:\"'({[—-":
            continue  # sentence-initial (or quote/paren-opening) capital
        w = m.group().lower()
        if w in corpus_words:
            continue
        if _typo_of_grounded(w, corpus_words):
            continue  # a one-letter slip in a grounded name is not a fabrication
        flagged.setdefault(m.group(), True)
    for name in flagged:
        failures.append(f"error_recovery: ungrounded name {name!r} in the answer "
                        f"— no tool result or input supplies it; presenting an "
                        f"invented stand-in for the errored {tool!r} fact is "
                        f"fabrication")
    return failures


def score_trajectory(parsed: dict, trace: dict, expected: dict,
                     input_text: str) -> tuple[bool, list]:
    failures = []
    answer = str(parsed.get("answer", ""))
    if not answer:
        failures.append("no final answer emitted")
    # Normalize digit grouping so "€9,000" matches an expected "9000" — score the
    # content, not the formatting (a correct llama3.1 answer failed on the comma).
    norm_answer = _norm_digits(answer)
    for needle in expected.get("answer_contains", []):
        if not _needle_matches(needle, answer, norm_answer):
            failures.append(f"answer missing {needle!r}")
    # ANY-of (C2): passes if at least one needle matches — an abstention vocabulary
    # ("no record" OR "no open deals" OR ...) cannot be expressed as ALL-of. Both
    # keys may coexist on a case; each is checked independently.
    any_needles = expected.get("answer_contains_any", [])
    if any_needles and not any(_needle_matches(n, answer, norm_answer)
                               for n in any_needles):
        failures.append(f"answer missing all of answer_contains_any: {any_needles}")
    # ABSENCE needle (2026-09-04): a string that must NOT appear — the decoy-detail
    # leak. Witnessed on the train case decoy-owner-after-deals-devos: the champion
    # names the right contact (answer_contains 'De Vos' passes, crm_lookup was
    # called, every number grounded) and attaches OUR REP's email lifted from the
    # deals_list envelope, 3/3 same-day runs. No existing check could see it.
    # Deliberately NOT _needle_matches and NOT norm_answer (CLAUDE.md gotcha 4:
    # presence and absence checks never share a helper) — a plain case-insensitive
    # substring on the raw answer, no digit normalization, so a needle is exactly
    # the text it forbids. Mirrors tools_not_called, the tool-side blacklist.
    for needle in expected.get("answer_not_contains", []):
        if str(needle).lower() in answer.lower():
            failures.append(f"answer contains forbidden {needle!r}")
    for tool in expected.get("tools_called", []):
        if tool not in trace["tools_called"]:
            failures.append(f"never called tool {tool!r}")
    for tool in expected.get("tools_not_called", []):
        if tool in trace["tools_called"]:
            failures.append(f"called forbidden tool {tool!r}")
    if trace["steps"] > expected.get("max_steps", 4):
        failures.append(f"took {trace['steps']} steps (max {expected.get('max_steps', 4)})")

    # Tool selection under choice (E10 rung B): tools_allowed is a WHITELIST — any
    # called tool outside it is a selection error, even when the answer came out
    # right and grounded (a decoy's data is still grounding, so the grounding check
    # cannot catch a wrong pick that stumbles into a correct-looking number).
    # Complements tools_not_called (a blacklist), which does not scale to many
    # decoys. Each wrong TOOL is reported once — per-call repeats are the
    # redundancy monitor's job, not this check's.
    allowed = expected.get("tools_allowed")
    if allowed is not None:
        for tool in dict.fromkeys(trace["tools_called"]):
            if tool not in allowed:
                failures.append(f"called disallowed tool {tool!r}: not in "
                                f"tools_allowed {allowed}")

    # Error recovery (E10 rung A) — see _error_recovery_failures for the contract.
    er = expected.get("error_recovery")
    if er is not None:
        failures.extend(_error_recovery_failures(er, answer, trace, input_text))

    # Grounded answer (Stage 3): every digit-bearing token in the final answer must
    # appear in a grounding source — the tool results this run actually saw, or the
    # case input. The input COUNTS as grounding (decided here): a model that echoes a
    # date or amount from the question back at the user is not fabricating; the check
    # targets numbers that came from nowhere (MiniCPM5 invented a deal value of 10,000
    # and a last-contact date for a company with no CRM record, without calling any
    # tool). Bare integers < 10 are allowed — "two of the 3 deals" style phrasing —
    # matching properties.py check_no_invented_numbers. Membership is substring on the
    # normalized corpus: lenient toward passing (a real 9000 grounds an answer's
    # "9,000"), so a failure is always a real ungrounded number, never a formatting
    # artifact. trace["tool_results"] is accessed unguarded on purpose — a trace
    # without it is a runner bug and must crash loudly, not silently pass the check.
    corpus_raw = json.dumps(trace["tool_results"], ensure_ascii=False) + " " + input_text
    corpus = _norm_digits(corpus_raw)
    # Every date-like token the grounding sources contain, canonicalized. A date in the
    # answer is grounded if it matches one of these as a SET of components — which
    # accepts a reformat (2026-03-11 -> 3/11/2026) but still rejects a wrong day
    # (2026-07-05 vs 2026-07-02), because the component sets differ.
    corpus_dates = {d for d in (_date_parts(t)
                                for t in re.findall(r"\d[\d.,/-]*", corpus_raw))
                    if d}
    # The token pattern MUST keep date separators, or a fabricated date walks straight
    # through: with r"\d[\d.,]*", "2026-07-05" split into "2026"/"07"/"05", and the
    # <10 exemption then waived "07" and "05" (leading zeros parse as 7 and 5), so only
    # the year — which IS grounded — was ever checked. A wrong day and a wrong month
    # both passed. Caught by the verify-gate refuter 2026-07-22; it defeated the exact
    # fabrication this check exists to catch (MiniCPM5's invented last-contact date).
    # Keeping '-' and '/' inside the token makes a date one indivisible fact.
    for tok in re.findall(r"\d[\d.,/-]*", answer):
        tok = tok.rstrip(".,/-")          # trailing separator is punctuation, not data
        if not tok:
            continue
        # Exempt only genuinely bare small integers ("two of the 3 deals"). A token
        # with a separator is a compound fact (a date, a version) and is never exempt.
        if tok.isdigit() and int(tok) < 10:
            continue
        parts = _date_parts(tok)
        if parts is not None:
            if parts not in corpus_dates:
                failures.append(f"ungrounded date/decimal {tok!r}: no tool result "
                                f"or input contains it in any recognized format")
            continue
        if _norm_digits(tok).strip() and _norm_digits(tok) not in corpus:
            failures.append(f"ungrounded number {tok!r}: appears in the answer but in "
                            f"no tool result and not in the input")

    # Redundancy monitor (Stage 3, first ReasonBlocks-style monitor): the same tool
    # called twice with the SAME canonicalized args is wasted work and fails the case;
    # the same tool with different args is a legitimate multi-lookup and passes.
    # The key comes from _call_key, the same function the runtime dedupe guard uses:
    # identical semantics to the inline tuple this replaced, and the two sides of the
    # gate-0 A/B can no longer drift apart about what counts as a duplicate.
    seen: set = set()
    for call in trace["tool_calls"]:
        key = _call_key(call["tool"], call["args"])
        if key in seen:
            failures.append(f"redundant tool call: {call['tool']} called again with "
                            f"identical args {call['args']}")
        else:
            seen.add(key)
    return not failures, failures


# C5(a)/D6: stable check ids for the report-only failure record. score_trajectory
# keeps returning human strings (results/ and three test suites read them); this
# table maps each string back to the check that emitted it, by the literal prefix
# used at its emission site above. Order matters: the answer_contains_any prefix
# must be tried before the shorter answer_contains one.
_TRAJECTORY_FAILURE_CHECKS = (
    ("no final answer emitted", "answer_present"),
    ("answer missing all of answer_contains_any", "answer_contains_any"),
    ("answer missing ", "answer_contains"),
    ("answer contains forbidden ", "answer_not_contains"),
    ("never called tool ", "tools_called"),
    ("called forbidden tool ", "tools_not_called"),
    ("called disallowed tool ", "tools_allowed"),
    ("error_recovery: ", "error_recovery"),
    ("took ", "max_steps"),
    ("ungrounded date/decimal ", "grounded_answer"),
    ("ungrounded number ", "grounded_answer"),
    ("redundant tool call: ", "redundancy"),
)


def _trajectory_check_id(failure: str) -> str:
    """Map a score_trajectory failure string to its stable check id.

    Raises on an unknown string — a silently mis-binned failure would be a
    placeholder in a committed snapshot. Only runs on failures, so it can never
    flip a passing verdict; the raise surfaces as the case's error record.
    """
    for prefix, check_id in _TRAJECTORY_FAILURE_CHECKS:
        if failure.startswith(prefix):
            return check_id
    raise ValueError(f"unmapped trajectory failure {failure!r} — a new failure "
                     f"site in score_trajectory needs its prefix added to "
                     f"_TRAJECTORY_FAILURE_CHECKS")


def _judge_check_id(failure: str) -> str:
    """Stable id for a judge failure: the 'judge:<criterion>' head of the string
    judges.py emits ('judge:<name>: <reason>'). The free-text reason is dropped —
    it quotes model output, which must never reach a committed snapshot (D6)."""
    return failure.split(": ", 1)[0]


def run_exam(agent: dict, exam: dict, provider: str, model: str,
             timeout: int | None = None, dedupe_tools: bool = False,
             assembly: str = "full") -> dict:
    adapter = adapter_for(agent, provider, timeout)
    mode = exam.get("mode", "labels")
    props = load_properties(agent["name"])
    judge = load_judge(agent["name"], exam, model, ROOT)
    tools_mod = load_tools(agent["name"]) if mode == "trajectory" else None
    samples = exam.get("samples", 1)
    if samples > 1:
        # pass@k needs variation; deterministic temp 0 would sample the same run k times
        agent = {**agent, "temperature": exam.get("sample_temperature", 0.7)}

    per_case = []
    totals = {"train": [0, 0], "heldout": [0, 0]}
    field_totals = {"train": [0, 0], "heldout": [0, 0]}

    def attempt(case) -> tuple[bool, dict, list, dict, list]:
        """failed_checks (last element) is the C5(a)/D6 report-only record:
        [{"bucket", "check"}] for every failing gate. It NEVER feeds `passed` —
        the verdict logic below is byte-for-byte what it was before the buckets
        existed. Mode-level and judge failures are substance, bucket 'quality';
        property checks carry their own declared bucket."""
        detail: dict = {}
        failures: list = []
        failed_checks: list = []
        if mode == "trajectory":
            # MULTITURN-EXAM (criterion 9): score_case is the SOLE producer of a
            # trajectory-mode verdict. The pre-lane outer score_trajectory(...) call
            # and the D2 termination-override block that used to sit here (master
            # runner.py:920-935) are both DELETED — relocated, behavior preserved,
            # into _score_one_turn (called by score_case). This line is the ONLY
            # `passed`/`failures` assignment in this branch.
            parsed, trace, passed, failures, failed_checks = score_case(
                agent, case, adapter, model, tools_mod, dedupe_tools=dedupe_tools,
                assembly=assembly)
            # metrics always; deduped_calls only when the guard ran; termination only
            # on a death — which is how the tool evidence gathered before the death
            # reaches the record (D2). For a `turns` case, trace also carries a
            # "turns" list (MULTITURN-EXAM) with per-turn metrics.
            detail.update(trace)
        else:
            parsed, metrics = run_plain_case(agent, case, adapter, model)
            if mode == "fields":
                passed, detail = score_fields(parsed, case["expected"])
            elif mode == "properties":
                passed = True  # properties below carry the case
            else:
                passed, detail = score_labels(parsed, case["expected"])
            if not passed:  # labels/fields emit no failure strings; record the gate
                failed_checks.append({"bucket": "quality", "check": mode})
            detail["metrics"] = metrics
        if props:
            props_ok, prop_failures, prop_failed = run_properties(
                props, case["input"], parsed)
            passed = passed and props_ok
            failures.extend(prop_failures)
            failed_checks += prop_failed
        if judge:
            judge_ok, judge_failures = judge(case["input"], parsed)
            passed = passed and judge_ok
            failures.extend(judge_failures)
            failed_checks += [{"bucket": "quality", "check": _judge_check_id(f)}
                              for f in judge_failures]
        return passed, parsed, failures, detail, failed_checks

    for case in exam["cases"]:
        detail = {}
        failures = []
        failed_checks = []
        try:
            if samples == 1:
                passed, got, failures, detail, failed_checks = attempt(case)
            else:
                # Reliability, not luck: the case passes only if pass_rate clears the
                # threshold (default: every sample) — pass@1 overstates by 20-40%.
                runs = [attempt(case) for _ in range(samples)]
                rate = sum(r[0] for r in runs) / samples
                passed = rate >= exam.get("sample_threshold", 1.0)
                rep = next((r for r in runs if not r[0]), runs[0])
                _, got, failures, detail, failed_checks = rep
                detail = {**detail, "samples": samples, "pass_rate": round(rate, 2)}
                # Cost is what was ACTUALLY spent, and all `samples` calls were made
                # and paid for. Reporting only the representative run under-counted
                # tokens/wall_ms by a factor of `samples` — a confidently wrong number
                # in the one place this feature exists to be honest about.
                # (verify-gate correctness refuter, high confidence, 2026-07-21.)
                sampled = [r[3]["metrics"] for r in runs
                           if isinstance(r[3], dict) and r[3].get("metrics")]
                if sampled:
                    detail["metrics"] = combine_metrics(sampled)
        except TerminationError as exc:
            # TERMINATION-DETECT D2, plain mode. The model emitted no answer, so there
            # is no output to score: the CASE fails loud with one named record instead
            # of scoring off the model's thinking. `got` is {} — an empty answer is
            # what actually came back; the four measured facts live in the record.
            #
            # detail is ASSIGNED here, not mutated: attempt()'s local detail never
            # returned, and the loop's own `detail` was reset to {} above, so without
            # this assignment the record would be dropped by the
            # `**({"detail": detail} if detail else {})` splice below.
            passed, got = False, {}
            detail = {"termination": {"cause": "no_answer", **exc.details}}
            failed_checks = [{"bucket": "termination", "check": "termination"}]
        except (requests.Timeout, requests.ConnectionError) as exc:
            # TERMINATION-DETECT D4. retry.py re-raises these after its api_attempts,
            # and before this clause they escaped run_exam and killed the WHOLE run
            # (measured 2026-08-27 with a raising stub adapter) — so one slow case
            # destroyed every verdict after it. Now the CASE fails with a named cause
            # and the run continues to the next case.
            #
            # This does NOT weaken the rule at main()'s --timeout comment block that
            # keeps --timeout off `check`: a timed-out request still costs the case.
            # What changes is that the harness now SAYS which of the two happened
            # instead of aborting; see that comment block.
            #
            # requests.HTTPError is deliberately NOT caught: it is a live backend
            # fault (4xx/5xx), not a statement about this model's termination, and
            # aborting the run is the right response to a broken endpoint.
            passed, got = False, {}
            detail = {"termination": {"cause": "timeout",
                                      "exception": type(exc).__name__,
                                      "timeout_s": getattr(adapter, "timeout", None)}}
            failed_checks = [{"bucket": "termination", "check": "termination"}]
        except (ValueError, TypeError) as exc:
            passed, got = False, {"error": str(exc)}
            failed_checks = [{"bucket": "quality", "check": "error"}]

        split = case.get("split", "train")
        totals[split][1] += 1
        totals[split][0] += int(passed)
        if "fields_total" in detail:
            field_totals[split][0] += detail["fields_matched"]
            field_totals[split][1] += detail["fields_total"]
        per_case.append({"id": case["id"], "split": split, "passed": passed,
                         # MULTITURN-EXAM: a `turns`-bearing case's REAL
                         # expectations live per-turn (turns_expected), not here —
                         # its committed top-level "expected" is a vestigial {}
                         # (R8, pass 2): removing the key entirely broke
                         # evals/test_e10_ladder.py and evals/test_pr2_hardcases.py,
                         # which iterate every crm-followup case with bracket access
                         # (`c["expected"]`) — both outside this lane's declared
                         # file scope to fix. .get() here is defensive regardless
                         # (every pre-existing case's real "expected" dict is
                         # unchanged either way).
                         "expected": case.get("expected"), "got": got,
                         **({"failures": failures} if failures else {}),
                         **({"failed_checks": failed_checks} if failed_checks else {}),
                         **({"detail": detail} if detail else {})})
        mark = "PASS" if passed else "FAIL"
        reasons = list(failures[:2])
        # TERMINATION-DETECT: CONSOLE ONLY — nothing here reaches `per_case`, the
        # results file or a snapshot. A terminated case emits no failure STRING (the
        # record is structured, in detail["termination"]), so without this the printed
        # line was a bare FAIL, indistinguishable on a `check` run from a generic
        # `error`. Telling the two apart at the console is the whole point of the lane.
        term = (detail or {}).get("termination") if isinstance(detail, dict) else None
        if term and not passed:
            bits = ", ".join(f"{k}={term[k]}" for k in
                             ("finish_reason", "content_chars", "exception")
                             if k in term)
            reasons.insert(0, f"termination: {term.get('cause')}"
                              + (f" ({bits})" if bits else ""))
        # R7: same console-only courtesy for a parse break — a `turns` case carries
        # the marker on the turn that broke, a single-turn case at the top level.
        # Nothing here reaches per_case either.
        pbs = ([(None, detail.get("protocol_break"))] if isinstance(detail, dict) else []) + \
              [(t.get("turn"), t.get("protocol_break"))
               for t in ((detail or {}).get("turns") or []) if isinstance(t, dict)]
        for turn_no, pb in pbs:
            if pb and not passed:
                where = f" turn {turn_no}" if turn_no is not None else ""
                reasons.insert(0, f"unparseable{where}: {pb.get('raw_head', '')[:60]!r}")
        extra = f"  ({'; '.join(reasons)})" if reasons and not passed else ""
        print(f"  [{mark}] {case['id']} ({split}){extra}")

    result = {"agent": agent["name"], "provider": provider, "model": model, "mode": mode,
              "train": {"passed": totals["train"][0], "total": totals["train"][1]},
              "heldout": {"passed": totals["heldout"][0], "total": totals["heldout"][1]},
              "cases": per_case}
    for split in ("train", "heldout"):
        p, t = result[split]["passed"], result[split]["total"]
        result[split]["score"] = round(p / t, 4) if t else None
        fm, ft = field_totals[split]
        if ft:
            result[split]["field_accuracy"] = round(fm / ft, 4)
    # Totals block: pure observation, rolled up from per-case metrics — never touches
    # passed/score above. Absent (None) if no case produced a metrics dict at all
    # (e.g. every case errored before a model call completed).
    case_metrics = [c["detail"]["metrics"] for c in per_case
                    if "detail" in c and "metrics" in c["detail"]]
    result["metrics_totals"] = combine_metrics(case_metrics) if case_metrics else None
    # A case that raised (parse failure after retries, empty content) may ALREADY have
    # burned metered calls whose cost is unrecoverable here — so the total is a floor,
    # not the true spend. Say so rather than presenting a short number as complete;
    # an unmarked undercount is the same defect as the sampling one above.
    unmetered = sum(1 for c in per_case
                    if not (c.get("detail") or {}).get("metrics")
                    # TERMINATION-DETECT: a case that DIED also burned a call whose
                    # usage never reached a metrics dict — the response carried no
                    # answer, so call_model raised before returning one. In plain mode
                    # there is no metrics key at all and the first clause catches it;
                    # in trajectory mode the earlier, successful calls DID produce
                    # metrics, so without this clause the case would be counted as
                    # fully metered while one real call is missing from the total.
                    or "termination" in (c.get("detail") or {}))
    if result["metrics_totals"] and unmetered:
        result["metrics_totals"]["unmetered_cases"] = unmetered
        result["metrics_totals"]["complete"] = False
    return result


# ---------------------------------------------------------------- commands

def _ollama_native_base_url() -> str:
    """The OpenAI-compat base_url in PROVIDERS ends '/v1'; the native Ollama API
    (/api/version, /api/generate, /api/ps) is the same host without it. Reads
    PROVIDERS from router.py rather than hardcoding the host — out of scope is
    editing router.py, not reading it."""
    url = PROVIDERS["ollama"]["base_url"]
    return url[:-3] if url.endswith("/v1") else url


def ollama_version() -> str:
    """GET /api/version -> the running Ollama server's version string. stdlib
    urllib only, no shell-out. Raises on any failure (bad JSON, no 'version' key,
    connection refused, timeout) — never a placeholder version."""
    url = _ollama_native_base_url() + "/api/version"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    return data["version"]


def ollama_unload(model: str) -> None:
    """POST /api/generate {model, keep_alive: 0} to unload the model, then GET
    /api/ps and raise if it is still listed there. stdlib urllib only, no
    shell-out. A `check` on the load that just took the snapshot would agree
    trivially — this is what forces a genuinely fresh load before every
    reproduction run."""
    base = _ollama_native_base_url()
    body = json.dumps({"model": model, "keep_alive": 0}).encode()
    req = urllib.request.Request(
        base + "/api/generate", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        # 404 here means Ollama has never heard of `model` (verified against a
        # live server: {"error": "model 'x' not found"}) — it cannot possibly be
        # resident either, so the /api/ps check below (the actual invariant)
        # still runs and will correctly find it absent. Any OTHER failure
        # (connection refused, timeout, 5xx) still raises — this is the one
        # documented exception to "raise on any failure", not a swallow-all.
        pass
    with urllib.request.urlopen(base + "/api/ps", timeout=10) as resp:
        ps = json.loads(resp.read())
    loaded = [m.get("model") or m.get("name") for m in ps.get("models", [])]
    if model in loaded:
        raise RuntimeError(
            f"ollama_unload({model!r}): still listed in /api/ps after unload "
            f"(keep_alive=0 request accepted, but the model did not leave "
            f"residency): {loaded}")


def aggregate_loads(results: list[dict]) -> dict:
    """PURE. Input: N `run_exam` results of the SAME exam (same case-id set, same
    order). Output: one result-shaped dict — same top-level shape as a single
    `run_exam` result — whose cases carry the MAJORITY `passed` verdict (N is
    always odd in the CLI path, so a majority always exists; a caller feeding an
    even N, as this pure function's own tests do, gets `passed=False` on a tie —
    documented, not gated on by any command), `stable` (True iff every load
    agreed), and `failed_checks`/`detail`/etc. taken from the FIRST load that
    voted with the majority (so a drifting case's printed reason is real
    evidence, not fabricated). `train_score`/`heldout_score` are recomputed from
    the majority verdicts over ALL cases — the denominator never moves, so a
    published 'n/18' stays comparable whether or not this function ran.

    Raises on N < 2 (a single load proves no stability) or on a case-id mismatch
    between loads (loads must be of the identical exam)."""
    if len(results) < 2:
        raise ValueError(f"aggregate_loads needs >= 2 loads, got {len(results)}")
    id_lists = [[c["id"] for c in r["cases"]] for r in results]
    if any(ids != id_lists[0] for ids in id_lists[1:]):
        raise ValueError("aggregate_loads: case-id set/order mismatch between loads")
    agg_cases = []
    for i in range(len(id_lists[0])):
        votes = [r["cases"][i]["passed"] for r in results]
        n_pass = sum(1 for v in votes if v)
        n_fail = len(votes) - n_pass
        majority_passed = n_pass > n_fail   # a tie (only possible on even N) is False
        stable = n_fail == 0 or n_pass == 0
        first_majority = next(r["cases"][i] for r in results
                              if r["cases"][i]["passed"] == majority_passed)
        case = dict(first_majority)
        case["passed"] = majority_passed
        case["stable"] = stable
        agg_cases.append(case)

    def _score(split: str) -> dict:
        subset = [c for c in agg_cases if c["split"] == split]
        passed = sum(1 for c in subset if c["passed"])
        total = len(subset)
        return {"passed": passed, "total": total,
                "score": round(passed / total, 4) if total else None}

    agg = dict(results[0])
    # metrics_totals belongs to ONE load, not the aggregate of N — writing it here
    # unmarked would be gotcha 13's shape (a partial total presented as complete).
    agg.pop("metrics_totals", None)
    agg["cases"] = agg_cases
    agg["train"] = _score("train")
    agg["heldout"] = _score("heldout")
    return agg


def _harness_sha() -> str | None:
    """Pinned harness submodule SHA, read from the git index — works even when the
    submodule isn't checked out locally. Never fabricate a placeholder; null on failure."""
    try:
        out = subprocess.run(["git", "ls-tree", "HEAD", "harness"], cwd=ROOT,
                              capture_output=True, text=True, timeout=5, check=True)
        parts = out.stdout.strip().split()
        return parts[2] if len(parts) >= 3 else None
    except (subprocess.SubprocessError, OSError, IndexError):
        return None


def _judge_meta(agent_name: str, exam: dict) -> dict | None:
    """None when the exam has no judge (no rubric.md); else its declared provider/model."""
    if not (ROOT / "evals" / agent_name / "rubric.md").exists():
        return None
    cfg = exam.get("judge") or {}
    return {"provider": cfg.get("provider"), "model": cfg.get("model")}


def _snapshot_case(case: dict) -> dict:
    """One committed-snapshot line per case (D6): id, split, passed, and — for a
    failing case only — WHICH checks failed, each with its C5(a) bucket.

    Deliberately excludes everything else per_case carries: no model output, no
    expected, no failure messages (they quote output text — that lives in
    results/, which is disposable). Key order is fixed and failing checks are
    deduplicated in first-seen order, so the same result always serializes to the
    same bytes and a rerun diffs clean (snapshots are committed artifacts).

    MULTITURN-EXAM (criterion 3): the ONE addition. When the case's detail carries
    a "turns" list — the signal that this was a `turns`-bearing case, set only by
    score_case's turns-aware path — a "turn_metrics" list is added: per turn, that
    turn's prompt_tokens (first model call), completion_tokens and wall_ms (turn
    totals), added REGARDLESS of pass/fail, so input-growth-per-turn is computable
    from the committed file alone for every multi-turn case. A case with no
    "turns" key in its detail (all 28 pre-existing cases, always) gets no new key
    at all — the criterion 6 zero-diff requirement for those records.

    SNAPSHOT-REPRODUCIBILITY: the SECOND addition, same pattern as turn_metrics —
    conditional on the input case dict carrying a "stable" key, so every
    pre-lane caller (including test_observability's fixtures, which never set
    it) gets byte-identical output. `aggregate_loads` is the only producer of a
    case dict with "stable" in it; that is what makes the key appear here."""
    entry = {"id": case["id"], "split": case["split"], "passed": case["passed"]}
    if "stable" in case:
        entry["stable"] = case["stable"]
    if not case["passed"]:
        deduped: list = []
        for failed in case.get("failed_checks", []):
            if failed not in deduped:
                deduped.append(failed)
        entry["failures"] = deduped
    turns_detail = (case.get("detail") or {}).get("turns")
    if turns_detail is not None:
        entry["turn_metrics"] = [
            {"turn": t["turn"], "prompt_tokens": t["prompt_tokens"],
             "completion_tokens": t["completion_tokens"], "wall_ms": t["wall_ms"]}
            for t in turns_detail
        ]
    return entry


def snapshot_payload(agent: dict, exam: dict, provider: str, model: str, result: dict,
                     *, loads: int | None = None, runtime: dict | None = None) -> dict:
    """Evidence bundle written by --snapshot. Additive over the original
    {provider, model, train_score, heldout_score} — cmd_check only ever reads those
    four keys, so old snapshots without this bundle remain valid.

    "cases" (D6) answers 'which check failed on which case' WITHOUT a rerun —
    the question that blocked diagnosis twice on 2026-07-22 (reply-draft
    0.25 -> 0.5, conference-heldout-en). See _snapshot_case for what it will
    never contain.

    SNAPSHOT-REPRODUCIBILITY: `loads`/`runtime` are keyword-only and OMITTED
    from the payload when not passed (None), rather than always-present with a
    null value — test_observability.py's `test_d6_snapshot_answers_...` asserts
    an EXACT top-level key set via `set(snap) == {...}` on a direct call that
    passes neither, and that test is out of this lane's declared file set. Only
    `cmd_run`/`cmd_run_all --snapshot` (via `take_snapshot_loads`) ever pass
    them; every legacy call site keeps its exact old output."""
    payload = {
        "provider": provider, "model": model,
        "train_score": result["train"]["score"],
        "heldout_score": result["heldout"]["score"],
        "temperature": agent.get("temperature", 0.0),
        "max_tokens": agent.get("max_tokens", 2048),
        "judge": _judge_meta(agent["name"], exam),
        "date": datetime.now().isoformat(timespec="seconds"),
        "harness_sha": _harness_sha(),
        "cases": [_snapshot_case(c) for c in result["cases"]],
    }
    if loads is not None:
        payload["loads"] = loads
    if runtime is not None:
        payload["runtime"] = runtime
    # E6-train: the library pin (spec constraint 2 — retrieval changes the prompt,
    # so the gate must refuse to compare across library versions). Same
    # omitted-when-absent pattern as loads/runtime, for the same reason: the
    # exact-key-set assertion in test_observability, and byte-identical legacy
    # snapshots for every agent without a library (all of them today).
    if agent.get("library_sha") is not None:
        payload["library_sha"] = agent["library_sha"]
    return payload


def refuse_snapshot_on_outage(result: dict) -> None:
    """Refuse to snapshot a run whose cases died of TIMEOUTS (D4 hardening).

    A snapshot is the committed definition of "not a regression", and `check` gates on
    heldout dropping BELOW it. So a snapshot taken during a backend outage is the worst
    possible artifact this repo can produce: every timed-out case scores 0, the
    snapshot records ~0.0, and from then on every `check` passes trivially — a green
    gate that asserts nothing, which is exactly the vacuous-green shape CLAUDE.md's
    gotcha 2 is about. Before D4 the run simply CRASHED on the first timeout, so this
    could not happen; making the run survive an outage is what creates the hazard, and
    it is fixed in the same lane that creates it.

    ONLY `cause == "timeout"` blocks. A `no_answer` death is a real measurement of the
    model and belongs in a snapshot — refusing those would make a model that cannot
    terminate unsnapshottable, which is the opposite of this lane's point.

    Loud, never a placeholder: sys.exit naming the count, so the operator reruns rather
    than silently committing a floor.
    """
    dead = [c["id"] for c in result["cases"]
            if (c.get("detail") or {}).get("termination", {}).get("cause") == "timeout"]
    if dead:
        sys.exit(
            f"error: refusing --snapshot: {len(dead)} of {len(result['cases'])} cases "
            f"failed with cause 'timeout' ({', '.join(dead[:5])}"
            f"{', ...' if len(dead) > 5 else ''}). A snapshot taken during a backend "
            f"outage records a near-zero score that every later `check` clears "
            f"trivially. Fix the backend and rerun; the results file was still written.")


def save_result(result: dict, *, subdir: str | None = None,
                suffix: str | None = None) -> Path:
    d = RESULTS_DIR if subdir is None else RESULTS_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    safe_model = result["model"].replace("/", "_").replace(":", "_")
    safe_provider = result["provider"].replace("/", "_").replace(":", "_")
    # Provider in the filename: a --provider stub run must never overwrite the real
    # scoreboard row for the same model name (it silently clobbered one 2026-07-21).
    name = f"{result['agent']}__{safe_provider}__{safe_model}"
    if suffix:
        # SNAPSHOT-REPRODUCIBILITY: a per-load result (results/snapshot_loads/,
        # __loadK). The SUBDIR is load-bearing, not cosmetic — taxonomy.py and
        # policy.py glob top-level results/*.json ONLY (same convention probe.py
        # already uses for results/probe/); N per-load files sitting at the top
        # level would N-fold every case's weight in their rollups.
        name += f"__{suffix}"
    path = d / f"{name}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return path


def _summary_line(result: dict) -> str:
    line = (f"train   {result['train']['passed']}/{result['train']['total']}"
            f"  heldout {result['heldout']['passed']}/{result['heldout']['total']}")
    if "field_accuracy" in result["heldout"]:
        line += f"  (heldout field acc {result['heldout']['field_accuracy']:.0%})"
    return line


def _validate_loads(n: int) -> None:
    """Refused BEFORE any inference or native-API call. Odd and >= 3 (criterion
    v3, halt 2): odd so a majority always exists on every case with no tie
    convention needed; >= 3 so a single disagreement can't already be a 2-of-3
    minority-of-one mistaken for consensus. Called unconditionally by cmd_run /
    cmd_run_all (not only under --snapshot) — the default (3) always passes, so
    this cannot break the non-snapshot path, and it removes any question of
    whether `run <agent> --loads 2` without --snapshot should be let through."""
    if n < 3 or n % 2 == 0:
        raise SystemExit(
            f"error: --loads must be an odd integer >= 3 so a majority vote is "
            f"always defined (got {n})")


def take_snapshot_loads(agent: dict, exam: dict, provider: str, model: str, loads: int,
                        *, timeout: int | None = None, dedupe_tools: bool = False,
                        assembly: str = "full") -> tuple[dict, dict]:
    """The ONE mechanism `cmd_run --snapshot` and `cmd_run_all --snapshot` both
    go through (criterion v3's closing sentence on clause 2). Runs `loads` full
    passes of the exam — unloading the model via the native API before each pass
    when `provider == "ollama"`; for any other provider, no unload runs and the
    console says these are N samples, not N model loads (the hosted-provider
    decision in the brief). Every load's outage guard runs before the next load
    starts (refuse_snapshot_on_outage — D4 hardening, unchanged semantics), and
    every load is saved to results/snapshot_loads/ with a __loadK suffix before
    the aggregate is computed, so a crash mid-run still leaves the completed
    loads on disk. Returns (aggregate_result, runtime) — runtime is
    {"name": provider, "version": ollama_version() or None} per criterion v3."""
    is_ollama = provider == "ollama"
    runtime = {"name": provider, "version": ollama_version() if is_ollama else None}
    load_results = []
    for k in range(1, loads + 1):
        if is_ollama:
            ollama_unload(model)
        else:
            print(f"  load {k}/{loads}: provider {provider!r} is hosted — this is "
                  f"sample {k} of {loads}, not a model reload")
        result = run_exam(agent, exam, provider, model, timeout=timeout,
                          dedupe_tools=dedupe_tools, assembly=assembly)
        # Save BEFORE the outage guard, same order cmd_run always used (D4's own
        # docstring promises "the results file was still written" on refusal) —
        # an operator diagnosing an outage needs the evidence, not just the cause.
        save_result(result, subdir="snapshot_loads", suffix=f"load{k}")
        refuse_snapshot_on_outage(result)   # D4 hardening, per load
        print(f"  load {k}/{loads}: {_summary_line(result)}")
        load_results.append(result)
    aggregate = aggregate_loads(load_results)
    # The aggregate is also the "current result" other read-only tools (taxonomy,
    # route) glob at the top level — unsuffixed, same convention as a plain run.
    save_result(aggregate)
    return aggregate, runtime


def cmd_run(args) -> int:
    agent = load_agent(args.agent)
    provider = args.provider or agent["provider"]
    model = args.model or agent["model"]
    exam = load_exam(args.agent)
    print(f"exam: {args.agent}  mode={exam.get('mode', 'labels')}  "
          f"provider={provider}  model={model}")
    print_not_verified(exam)
    _validate_loads(args.loads)
    if args.snapshot and args.assembly != "full":
        # The committed snapshot IS the "full" arm (and what `check` reproduces);
        # a scoped snapshot would silently redefine the gate. Refused up front,
        # before any inference is spent.
        raise SystemExit(f"--snapshot requires --assembly full (got {args.assembly!r}): "
                         f"the committed snapshot is always a full-history run")
    if args.snapshot:
        aggregate, runtime = take_snapshot_loads(
            agent, exam, provider, model, args.loads, timeout=args.timeout,
            dedupe_tools=args.dedupe_tools, assembly=args.assembly)
        print(f"{_summary_line(aggregate)}  (aggregate of {args.loads} loads)")
        unstable = [c["id"] for c in aggregate["cases"] if not c.get("stable", True)]
        print(f"unstable {len(unstable)}/{len(aggregate['cases'])}"
              + (f": {', '.join(unstable)}" if unstable else ""))
        snap_path = ROOT / "evals" / args.agent / "snapshot.json"
        snap_path.write_text(json.dumps(
            snapshot_payload(agent, exam, provider, model, aggregate,
                             loads=args.loads, runtime=runtime), indent=2))
        print(f"snapshot written -> {snap_path.relative_to(ROOT)}")
        return 0
    result = run_exam(agent, exam, provider, model, timeout=args.timeout,
                      dedupe_tools=args.dedupe_tools, assembly=args.assembly)
    path = save_result(result)
    print(f"{_summary_line(result)}  -> {path.relative_to(ROOT)}")
    return 0


def _load_snapshot(agent_name: str) -> dict:
    snap_path = ROOT / "evals" / agent_name / "snapshot.json"
    if not snap_path.exists():
        sys.exit(f"error: no snapshot for {agent_name!r}; run with --snapshot first")
    return json.loads(snap_path.read_text())


def snapshot_preflight(snap: dict, exam: dict, version_fn=None,
                       library_sha: str | None = None) -> str | None:
    """PURE-ish (one native-API call, ZERO model inference). The four
    pre-inference refusals shared by `cmd_check` and `cmd_check_all`: no
    `runtime` block; live ollama version differs from the snapshot's (ollama
    snapshots only — a hosted snapshot's runtime.version is always None per
    criterion v3, and would be refused forever if compared unconditionally,
    which is exactly halt 2's finding); the exam's case-id set differs from the
    snapshot's; the agent's lesson-library pin differs from the snapshot's
    (E6-train — retrieval changes the prompt, so comparing across library
    versions is comparing two different prompts and calling it drift). Returns
    the refusal cause (RUNTIME:/VERSION:/CASES:/LIBRARY: prefixed) or None when
    the snapshot is fit to check against.

    `library_sha` is the CURRENT agent's pin (None = no library, the legacy
    state). Compared with != so every asymmetry refuses: library added since
    the snapshot, removed since it, or changed — all three redefine the prompt
    the snapshot measured. Both-None (every pre-lane snapshot + agent) passes
    untouched.

    `version_fn` defaults to `ollama_version` and is called ONLY when
    `snap["provider"] == "ollama"` — injected so a test can assert a
    non-ollama snapshot never touches the network at all (pass a version_fn
    that raises if invoked)."""
    if version_fn is None:
        version_fn = ollama_version
    if "runtime" not in snap:
        return "RUNTIME: snapshot has no runtime block; re-snapshot"
    if snap.get("provider") == "ollama":
        live = version_fn()
        want = snap["runtime"].get("version")
        if live != want:
            return (f"VERSION: live ollama {live!r} != snapshot runtime.version "
                    f"{want!r}; re-snapshot")
    if snap.get("library_sha") != library_sha:
        return (f"LIBRARY: agent library_sha {library_sha!r} != snapshot's "
                f"{snap.get('library_sha')!r} — the library is part of the prompt; "
                f"re-snapshot")
    snap_ids = {c["id"] for c in snap["cases"]}
    exam_ids = {c["id"] for c in exam["cases"]}
    if snap_ids != exam_ids:
        return (f"CASES: exam case-id set differs from snapshot (snapshot-only: "
                f"{sorted(snap_ids - exam_ids)}, exam-only: "
                f"{sorted(exam_ids - snap_ids)}); re-snapshot")
    return None


def compare_to_snapshot(snap: dict, result: dict, tolerance: float = 0.0) -> dict:
    """PURE. Shared by `cmd_check` and `cmd_check_all` (criterion v3 clause 3):
    the ONE comparison both commands gate exit 1 on. `result` is a single fresh
    run (NOT an aggregate — `check` reproduces the snapshot on one load, per the
    brief's rule).

    Returns {"drift": [(id, snap_passed, now_passed, now_failed_checks), ...]
    over STABLE snapshot cases only, in either direction (a stable PASS->FAIL is
    exactly as much a non-reproduction as a stable FAIL->PASS — no directional
    bias, unlike a build that only checks for regressions), "exempt": [(id,
    now_passed), ...] for UNSTABLE snapshot cases, "regression": the existing
    aggregate heldout-tolerance check UNCHANGED in its tolerance semantics,
    "ok": not drift and not regression, plus the pieces the caller needs to
    print a message without recomputing them: "tolerance", "snap_heldout",
    "now_heldout", "n_stable", "n_unstable"}.

    Raises on a case-id set mismatch (snapshot_preflight already refuses this
    before `result` exists on the real cmd_check/cmd_check_all path; this stays
    defensive since the function is exported and reusable)."""
    snap_by_id = {c["id"]: c for c in snap["cases"]}
    result_by_id = {c["id"]: c for c in result["cases"]}
    if set(snap_by_id) != set(result_by_id):
        raise ValueError(
            f"compare_to_snapshot: case-id set mismatch (snapshot-only: "
            f"{sorted(set(snap_by_id) - set(result_by_id))}, result-only: "
            f"{sorted(set(result_by_id) - set(snap_by_id))})")
    drift: list = []
    exempt: list = []
    for cid, scase in snap_by_id.items():
        rcase = result_by_id[cid]
        if not scase.get("stable", True):
            exempt.append((cid, rcase["passed"]))
            continue
        if scase["passed"] != rcase["passed"]:
            drift.append((cid, scase["passed"], rcase["passed"],
                         rcase.get("failed_checks", [])))
    snap_h = snap["heldout_score"]
    now_h = result["heldout"]["score"] or 0.0
    regression = (snap_h - now_h) > tolerance
    return {
        "drift": drift, "exempt": exempt, "regression": regression,
        "ok": not drift and not regression,
        "tolerance": tolerance, "snap_heldout": snap_h, "now_heldout": now_h,
        "n_stable": len(snap_by_id) - len(exempt), "n_unstable": len(exempt),
    }


def _print_verdict(verdict: dict) -> bool:
    """Per-case table (drift rows first, then exempt), then the aggregate line —
    states which of (a) drift / (b) regression fired when either did. Returns
    verdict['ok'] for the caller's exit code."""
    for cid, was, now, failures in verdict["drift"]:
        checks = "; ".join(f.get("check", "?") for f in failures)
        print(f"  DRIFT  {cid}: snapshot={was} now={now}"
              + (f"  ({checks})" if checks else ""))
    for cid, now in verdict["exempt"]:
        print(f"  exempt {cid}: unstable in snapshot, now={now}")
    if verdict["ok"]:
        print(f"ok: heldout {verdict['now_heldout']} vs snapshot "
              f"{verdict['snap_heldout']} ({verdict['n_stable']} stable, "
              f"{verdict['n_unstable']} unstable exempt)")
        return True
    fired = []
    if verdict["drift"]:
        fired.append("DRIFT")
    if verdict["regression"]:
        fired.append("REGRESSION")
        print(f"REGRESSION: heldout {verdict['now_heldout']} < snapshot "
              f"{verdict['snap_heldout']} (tolerance {verdict['tolerance']})")
    print(f"FAILED: {' + '.join(fired)}")
    return False


def cmd_check(args) -> int:
    snap = _load_snapshot(args.agent)
    agent = load_agent(args.agent)
    exam = load_exam(args.agent)
    cause = snapshot_preflight(snap, exam, library_sha=agent.get("library_sha"))
    if cause:
        sys.exit(f"error: {cause}")
    print(f"exam: {args.agent}  mode={exam.get('mode', 'labels')}  "
          f"provider={snap['provider']}  model={snap['model']}")
    print_not_verified(exam)
    print(f"check: {args.agent} against snapshot ({snap['model']})")
    if snap["provider"] == "ollama":
        ollama_unload(snap["model"])
    result = run_exam(agent, exam, snap["provider"], snap["model"],
                      dedupe_tools=args.dedupe_tools)
    verdict = compare_to_snapshot(snap, result, tolerance=args.tolerance)
    return 0 if _print_verdict(verdict) else 1


def _diff_metrics_cols(result: dict) -> tuple[str, str]:
    """Per-case average tokens and latency for the diff table — "model A is 2% more
    accurate but 3x slower and 2x the tokens" needs a comparable per-case figure, not
    a raw total that shifts with case count.

    Delegates to `policy.cost_per_case`, the single cost reader shared with `route`
    (E12). Consequence of that move, and the point of it: a run whose metrics block
    is absent OR marked `complete: false` now reads `cost-unknown` in this table
    rather than printing a partial total that looks like a complete one.
    """
    cost = policy.cost_per_case(result)
    if not cost.known:
        return policy.COST_UNKNOWN, policy.COST_UNKNOWN
    return f"{cost.tokens:.0f}", f"{cost.wall_ms:.0f}ms"


def _think_share_col(result: dict) -> str:
    """E24: what FRACTION of the generated text was thinking rather than answer.

    Chars, not tokens, and named `think%` so it cannot be read as a token split — no
    local provider reports one (router.py carries the evidence). Returns '-' when the
    run predates the field or the backend reported neither, rather than printing 0%,
    which would claim "this model does not think" on evidence we do not have.
    """
    totals = result.get("metrics_totals") or {}
    think, answer = totals.get("reasoning_chars"), totals.get("content_chars")
    if think is None or answer is None:
        return "-"
    generated = think + answer
    if generated <= 0:
        return "-"
    return f"{100.0 * think / generated:.0f}%"


def _acc_key(result: dict) -> tuple:
    """The accuracy ranking key: (heldout, train), scores only."""
    return (result["heldout"]["score"] or 0, result["train"]["score"] or 0)


def _cost_tiebreak(tied: list) -> tuple[dict | None, str]:
    """(winner, why) among accuracy-tied rows, decided on measured cost — or
    (None, why-not).

    The rule is deliberately strict: the tiebreak fires only when EVERY tied row has
    a usable cost total. If one of them is `cost-unknown`, the cheapest *known* row
    cannot be shown to be the cheapest row, and claiming it is would be exactly the
    fabricated comparison the metrics block warns about (an incomplete total is a
    FLOOR). In that case nothing is decided and the reason is printed.
    """
    costs = {r["model"]: policy.cost_per_case(r) for r in tied}
    unknown = sorted(m for m, c in costs.items() if not c.known)
    if unknown:
        reasons = "; ".join(f"{m}: {costs[m].reason}" for m in unknown)
        return None, (f"{policy.COST_UNKNOWN} — cannot break the accuracy tie on cost "
                      f"while any tied model has no comparable total ({reasons})")
    cheap = min(tied, key=lambda r: (costs[r["model"]].tokens,
                                     costs[r["model"]].wall_ms, r["model"]))
    dear = max(tied, key=lambda r: (costs[r["model"]].tokens,
                                    costs[r["model"]].wall_ms, r["model"]))
    lo, hi = costs[cheap["model"]], costs[dear["model"]]
    if lo.tokens == hi.tokens and lo.wall_ms == hi.wall_ms:
        return None, ("cost is identical across the tied models, so there is nothing "
                      "to break the tie with")
    # The token ratio is >= 1 by construction (`dear` is the max) but the WALL ratio is
    # NOT: the token-cheapest model can be the slower one, and this tiebreak still
    # picks it, because tokens are deterministic at temp 0 and wall-clock is one run.
    # Printing a bare "0.7x ms/case" next to the word "cheapest" would be a comparative
    # clause contradicting its own figure, so the direction words come from
    # `policy.cost_move`, which derives them from the rounded ratio it prints.
    move = policy.cost_move(lo, hi)
    return cheap, (f"cost tiebreak: {cheap['model']} at {lo.tokens:.0f} tok/case, "
                   f"{lo.wall_ms:.0f} ms/case vs {dear['model']} at {hi.tokens:.0f} "
                   f"tok/case, {hi.wall_ms:.0f} ms/case — {dear['model']} is "
                   f"{move.text}. Ranked on TOKENS first (deterministic at temp 0), "
                   f"wall-clock second, so the winner is {cheap['model']}")


def diff_recommendation(rows: list, champion: str,
                        champ_snap: dict | None = None) -> list[str]:
    """The `diff` verdict, as lines. Pure function of (rows, champion, snapshot).

    Accuracy first, cost only as a TIEBREAK (E12 / `docs/experiments.md`): the
    recommendation used to rank on `(heldout, train)` alone and resolve a tie with
    `max`, which returns the FIRST maximal row — so a tie was decided by command-line
    order, and with the champion listed first that read as "keep the incumbent".
    Cost was invisible to the one command built to compare models. Now:

      * a strictly better model still wins on accuracy — cost never overrides it;
      * an exact tie on both splits is decided by measured per-case cost, and the
        verdict cites both figures and the heldout denominator it rests on;
      * if any tied model's cost is unknown or incomplete, NOTHING is decided on
        cost and the reason is printed — never a zero-filled comparison;
      * and if cost cannot break the tie either, the verdict is
        `cannot-distinguish` — it does NOT fall back to `tied[0]`, which is
        command-line order wearing the authority of a recommendation.

    That last rule is the fix for the residual order-dependence found in PR #24: the
    tie fell back to the champion's row when the champion was among the tied models
    (defensible — the incumbent stays for want of evidence to move), but to `tied[0]`
    when it was not (a coin flip). Every fixture in the first attempt was the
    2-model, champion-is-tied shape, so nothing covered it.

    A tie on a handful of heldout cases is not evidence that the two models are
    equally capable, only that this exam cannot tell them apart; the output says so,
    because equal-accuracy-cheaper is a sound call and equal-accuracy-better is not.
    """
    ran = {r["model"] for r in rows}
    best_key = max(_acc_key(r) for r in rows)
    tied = [r for r in rows if _acc_key(r) == best_key]
    heldout_n = max(r["heldout"]["total"] for r in rows)
    # All tied rows share `_acc_key`, so any of them reports the same scores — the
    # DISPLAY of a tied score is order-independent even when the CHOICE is not.
    tied_models = ", ".join(sorted(r["model"] for r in tied))
    tied_score = tied[0]["heldout"]["score"]
    best, tie_note = (tied[0] if len(tied) == 1 else None), ""
    if len(tied) > 1:
        winner, why = _cost_tiebreak(tied)
        tie_note = (f"  accuracy TIE on {heldout_n} heldout cases ({tied_models}) — one "
                    f"case is {1 / heldout_n:.0%} here, so this exam cannot rank "
                    f"them on capability.\n  {why}")
        if winner is not None:
            best = winner
        elif champion in {r["model"] for r in tied}:
            # The incumbent is one of the tied models and nothing measured separates
            # them: it stays for want of evidence to move. That is a rule, not a
            # position in argv.
            best = next(r for r in tied if r["model"] == champion)
            tie_note += ("\n  the incumbent is among the tied models, so it stays by "
                         "DEFAULT (no measured reason to move), not by measurement")
        # else: `best` stays None — see the cannot-distinguish branches below.

    # `best is None` means the tie is genuinely undecidable and the champion is not in
    # it. Every branch below that would have to NAME a winner says so instead; the
    # branches that only have to name the CHAMPION are still decided, and still print
    # their ordinary verdict (a tie among challengers the champion already beats does
    # not make "keep" undecidable).
    undecided = (f"{policy.CANNOT_DISTINGUISH} — {len(tied)} models tie at heldout "
                 f"{tied_score} ({tied_models}) and cost cannot break it, so this "
                 f"diff names no winner among them")
    if champion in ran:
        if best is None:
            champ_row = next(r for r in rows if r["model"] == champion)
            return [f"recommendation: {undecided}. The incumbent {champion} is NOT "
                    f"among them (heldout {champ_row['heldout']['score']} vs "
                    f"{tied_score}), so the actionable half IS decided: MOVE OFF "
                    f"{champion} — the data just cannot say to which"] + [tie_note]
        head = (f"recommendation: keep {champion}" if best["model"] == champion else
                f"recommendation: swap {champion} -> {best['model']} "
                f"(heldout {best['heldout']['score']})")
        return [head] + ([tie_note] if tie_note else [])
    if champ_snap:
        champ_key = (champ_snap["heldout_score"] or 0, champ_snap["train_score"] or 0)
        if best_key > champ_key:
            if best is None:
                return [f"recommendation: {undecided}. Every tied model beats the "
                        f"{champion} snapshot (heldout {tied_score} vs "
                        f"{champ_snap['heldout_score']}), so MOVE OFF {champion} is "
                        f"decided; which one to move to is not"] + [tie_note]
            return [f"recommendation: swap {champion} -> {best['model']} "
                    f"(heldout {best['heldout']['score']} vs snapshot "
                    f"{champ_snap['heldout_score']})"] + (
                        [tie_note] if tie_note else [])
        # Decided regardless of the tie: nothing here beats the snapshot.
        lines = [f"recommendation: keep {champion} (snapshot heldout "
                 f"{champ_snap['heldout_score']} >= best challenger {tied_score})"]
        if best_key == champ_key:
            # Snapshots record scores only, never a metrics block, so a challenger
            # that merely ties one cannot be shown to be cheaper. Say that instead of
            # letting the incumbent win a cost comparison that was never made.
            lines.append(f"  {policy.COST_UNKNOWN} — the champion's snapshot carries "
                         f"no metrics_totals, so this accuracy tie CANNOT be broken "
                         f"on cost. Rerun with --models "
                         f"{champion},{tied_models.replace(', ', ',')} to compare "
                         f"cost.")
        return lines + ([tie_note] if tie_note else [])
    return [f"recommendation: none — champion {champion!r} was not run and has no "
            f"snapshot to compare against"]


def cmd_diff(args) -> int:
    """The demo moment: same exam, N models, one table."""
    agent = load_agent(args.agent)
    exam = load_exam(args.agent)
    provider = args.provider or agent["provider"]
    rows = []
    for model in args.models.split(","):
        model = model.strip()
        print(f"\n--- {model} ---")
        result = run_exam(agent, exam, provider, model, timeout=args.timeout,
                          dedupe_tools=args.dedupe_tools, assembly=args.assembly)
        save_result(result)
        rows.append(result)
    champion = agent["model"]
    ran = {r["model"] for r in rows}
    # If the champion wasn't among the models run, it can't be compared by name alone —
    # load its snapshot score so a lone challenger can't win by default (a diff of one
    # non-champion model used to always print "swap", even to a heldout-0.0 model).
    snap_path = ROOT / "evals" / args.agent / "snapshot.json"
    champ_snap = json.loads(snap_path.read_text()) if (
        champion not in ran and snap_path.exists()) else None

    # Columns widened to fit "cost-unknown": a metrics block that is missing or
    # incomplete now says so in the table instead of printing a partial total.
    # A3: the heldout 95% Wilson interval sits beside the fraction it belongs to —
    # on n=9..18 it is 0.3-0.4 wide, which is the honest width behind every "tie".
    print(f"\n{'model':<28} {'train':>7} {'heldout':>9} {'95% CI':>11} {'tok/case':>13} "
          f"{'ms/case':>13} {'think%':>7}")
    for r in rows:
        tag = "  <- current" if r["model"] == champion else ""
        tok, ms = _diff_metrics_cols(r)
        lo, hi = stats.wilson(r['heldout']['passed'], r['heldout']['total'])
        print(f"{r['model']:<28} {r['train']['passed']}/{r['train']['total']:>4}"
              f" {r['heldout']['passed']}/{r['heldout']['total']:>6} {lo:.2f}-{hi:.2f}"
              f" {tok:>13} {ms:>13} {_think_share_col(r):>7}{tag}")
    if champ_snap:
        # Snapshots predate the metrics totals block (they capture scores only) —
        # cost-unknown rather than a fabricated figure.
        print(f"{champion:<28} {champ_snap['train_score']:>7} "
              f"{champ_snap['heldout_score']:>9} {policy.COST_UNKNOWN:>13} "
              f"{policy.COST_UNKNOWN:>13}  <- current (snapshot)")

    print("\n" + "\n".join(diff_recommendation(rows, champion, champ_snap)))
    return 0


def _all_agents() -> list[str]:
    return sorted(d.name for d in (ROOT / "agents").iterdir()
                  if (d / "agent.yaml").exists())


def cmd_run_all(args) -> int:
    """Run every agent's exam with its champion config. --snapshot goes through
    the SAME `take_snapshot_loads` mechanism as `cmd_run --snapshot` (criterion
    v3's closing sentence on clause 2) — one implementation, not two."""
    _validate_loads(args.loads)
    failed = []
    for name in _all_agents():
        agent = load_agent(name)
        exam = load_exam(name)
        print(f"\n=== {name} ({exam.get('mode', 'labels')}) — "
              f"{agent['provider']}/{agent['model']} ===")
        if args.snapshot:
            aggregate, runtime = take_snapshot_loads(
                agent, exam, agent["provider"], agent["model"], args.loads)
            print(f"{_summary_line(aggregate)}  (aggregate of {args.loads} loads)")
            snap_path = ROOT / "evals" / name / "snapshot.json"
            snap_path.write_text(json.dumps(
                snapshot_payload(agent, exam, agent["provider"], agent["model"],
                                 aggregate, loads=args.loads, runtime=runtime),
                indent=2))
            result = aggregate
        else:
            result = run_exam(agent, exam, agent["provider"], agent["model"])
            save_result(result)
            print(_summary_line(result))
        if (result["heldout"]["score"] or 0) < 1.0:
            failed.append(name)
    print(f"\n{len(_all_agents()) - len(failed)}/{len(_all_agents())} agents at 100% heldout"
          + (f" — below: {', '.join(failed)}" if failed else ""))
    return 0


def cmd_check_all(args) -> int:
    """Regression gate over every snapshotted agent — exit 1 if any exam was
    REFUSED (pre-inference), drifted, or regressed. Same `snapshot_preflight` /
    `compare_to_snapshot` pair `cmd_check` uses (criterion v3 clause 3); the
    pre-existing "skip: no snapshot" branch is unchanged and stays uncounted."""
    problems = []
    for name in _all_agents():
        snap_path = ROOT / "evals" / name / "snapshot.json"
        if not snap_path.exists():
            print(f"skip {name}: no snapshot")
            continue
        snap = json.loads(snap_path.read_text())
        agent = load_agent(name)
        exam = load_exam(name)
        print(f"\n=== check {name} vs snapshot ({snap['model']}) ===")
        cause = snapshot_preflight(snap, exam, library_sha=agent.get("library_sha"))
        if cause:
            print(f"REFUSED: {cause}")
            problems.append(name)
            continue
        if snap["provider"] == "ollama":
            ollama_unload(snap["model"])
        result = run_exam(agent, exam, snap["provider"], snap["model"])
        verdict = compare_to_snapshot(snap, result, tolerance=args.tolerance)
        if not _print_verdict(verdict):
            problems.append(name)
    if problems:
        print(f"\nFAILED: {', '.join(problems)}")
        return 1
    print("\nall snapshots hold")
    return 0


def _live_attempt(agent: dict, agent_name: str, exam: dict, provider: str, model: str,
                  text: str, pin: dict | None = None) -> tuple[dict, dict | None]:
    """ONE live run on ONE (provider, model): the body live_run_and_log used to inline.
    Returns (record, termination) — record is the {output, trace|metrics} slice, and
    termination is the death record or None. Behaviour per mode is unchanged from the
    pre-lane code (see live_run_and_log's docstring for the D2 rationale)."""
    # A tier's own provider_routing (hosted pin) overrides the agent's for this attempt
    # only — the agent dict is not mutated, so the next tier starts clean.
    adapter = adapter_for({**agent, **({"provider_routing": pin} if pin is not None else {})},
                          provider)
    case = {"input": text, "expected": {"max_steps": 6}}
    if exam.get("mode") == "trajectory":
        tools_mod = load_tools(agent_name, for_exam=False)
        parsed, trace = run_trajectory_case(agent, case, adapter, model, tools_mod)
        return {"output": parsed, "trace": trace}, trace.get("termination")
    try:
        parsed, metrics = run_plain_case(agent, case, adapter, model)
    except TerminationError as exc:
        return {"output": {}, "metrics": None}, {"cause": "no_answer", **exc.details}
    return {"output": parsed, "metrics": metrics}, None


def live_output_checks(agent_name: str, exam: dict, output: dict, trace: dict | None,
                       text: str) -> list[str]:
    """LIVE-ROUTING A2b: the EXPECTATION-FREE subset of the exam's own checks, run on a
    live output so a wrong answer (not just a dead one) can trigger escalation. No new
    checker is defined here — every line reuses the single existing implementation:
      trajectory  -> score_trajectory with an EMPTY expected block, which leaves
                     exactly: answer present, step budget (live's 6), every number
                     grounded in the tool results or the input, no fabricated name.
      properties  -> evals/<agent>/properties.py check_* (input, output), which never
                     take an expected block at all.
      labels/fields -> structural only for the label half: the output must carry the
                     keys the exam scores —
                     read off the committed exam (the key set of its first case's
                     expected block: `label`, `category`+`recurring`, `agent`), never
                     a hand-kept map (A4, 2026-09-04: the map said `label` for every
                     labels exam and would have flagged every task-intake answer).
                     Vocabulary lives in the prompt, not in any committed schema, so
                     it is NOT checked here (declared gap, not a silent pass). PLUS
                     the exam's properties.py when it has one — run_exam runs
                     properties for every mode, so a labels exam that grades a second
                     half through properties (task-intake's hand-over) is graded the
                     same way live. An exam without properties.py adds nothing.
    Returns the failure strings (empty = passed)."""
    mode = exam.get("mode", "labels")
    if mode == "trajectory":
        _, failures = score_trajectory(output, trace, {"max_steps": 6}, text)
        return list(failures)
    prop_failures = [f"{name}: {msg}" for name, fn in load_properties(agent_name)
                     for ok, msg in [fn(text, output)] if not ok]
    if mode == "properties":
        return prop_failures
    cases = exam.get("cases") or []
    keys = tuple((cases[0].get("expected") or {}).keys()) if cases else ()
    return [f"output missing {key!r}" for key in keys if key not in output] + prop_failures


def live_run_and_log(agent_name: str, text: str, provider: str | None = None,
                     model: str | None = None, extra: dict | None = None,
                     log: bool = True) -> tuple[dict, dict]:
    """Run an agent on real input and (by default) append one JSONL line to
    results/live/<agent>.jsonl — the SINGLE shared run+log path behind `runner.py
    live` and any other live producer (e.g. sandbox/shadow_gmail.py). Keeping one
    implementation is deliberate: a hand-copied second schema is exactly the kind of
    drift that shipped the numnorm bug twice (CLAUDE.md).

    Returns (entry, record): `record` is the {output, metrics|trace} slice the CLI
    prints; `entry` is the full logged line.

    `extra` adds provenance fields (e.g. an email's from/subject/message_id) to the
    logged line. It is spliced in BEFORE **record so that with `extra` empty the line
    is byte-identical to the pre-refactor schema {ts, model, provider, input, **record}
    — serve.py._live_payload and cmd_promote both read this file, and additive keys are
    safe for both while a reordering is not. Uses the agent's champion model and, for
    tool agents, the REAL tools.py (exams use tools_mock.py).

    TERMINATION-DETECT D2, live half. This function reaches the same call path, and the
    two modes failed DIFFERENTLY without this handling: in plain mode TerminationError
    propagated and nothing was ever logged (loud, but the evidence was lost), while in
    trajectory mode run_trajectory_case catches it internally and returns, so the JSONL
    line was written with an empty `output` and the live run reported SUCCESS — a
    silent pass on a run that emitted no answer, the exact defect this lane closes.
    Both are handled here the same way: log the line WITH the termination record (so
    the corrections flywheel keeps the evidence), then re-raise so the caller and the
    CLI exit loud. The added key is additive and only present on a death, which is the
    property serve.py._live_payload and cmd_promote need.
    """
    if not text.strip():
        raise ValueError("no input: refusing to run an agent on empty text")
    agent = load_agent(agent_name)
    exam = load_exam(agent_name)
    # LIVE-ROUTING (A1/A2/A2b). An explicit provider/model is a SINGLE-TIER override:
    # the table is never consulted, and a death on it raises without any fallback
    # (evals/test_live_routing.py test_2b). Otherwise walk routes.yaml's tiers (tier 0
    # == the champion, test-pinned) and escalate on a DEAD run or an output that FAILS
    # the expectation-free checks. Schema, stated precisely (the correctness refuter
    # caught a wider claim here): a HEALTHY answer and a DEAD run log exactly the
    # pre-lane line; `attempts`/`tier` appear only when a second tier actually ran;
    # `checks_failed` appears on EVERY path — single-tier included — whenever the
    # final answer fails the checks, and cmd_live then exits 2. That last part is a
    # deliberate behaviour change: a live answer with a fabricated number used to
    # exit 0, which is the silent pass this repo bans. Exceptions other than
    # TerminationError (a tools.py error, an unknown provider or an unpulled model on
    # any tier, a parse ValueError in PLAIN mode) PROPAGATE immediately — no
    # escalation, no log line — exactly as before the lane; loud, but a multi-tier
    # run forfeits its fallback on them (declared, not handled here). R7 (2026-09-04)
    # closed one of those for TRAJECTORY mode: a tier that answers in prose now
    # returns parsed={} with a protocol_break record, fails answer_present in
    # live_output_checks, and escalates like any other failed answer.
    if provider or model:
        tiers = [{"provider": provider or agent["provider"], "model": model or agent["model"]}]
    else:
        tiers = load_routes(agent_name) or [{"provider": agent["provider"], "model": agent["model"]}]
    attempts: list = []
    for k, tier in enumerate(tiers):
        record, termination = _live_attempt(agent, agent_name, exam, tier["provider"],
                                            tier["model"], text,
                                            pin=tier.get("provider_routing"))
        checks_failed = ([] if termination is not None else
                         live_output_checks(agent_name, exam, record["output"],
                                            record.get("trace"), text))
        protocol_break = (record.get("trace") or {}).get("protocol_break")
        attempt = {"tier": k, "provider": tier["provider"], "model": tier["model"],
                   **({"termination": termination} if termination is not None else {}),
                   # R7: say WHY a tier's answer was empty when it wrote prose — the
                   # reader of a flagged/escalated line otherwise sees only
                   # "no final answer emitted" for a model that answered at length.
                   **({"protocol_break": protocol_break} if protocol_break else {}),
                   **({"checks_failed": checks_failed} if checks_failed else {})}
        attempts.append(attempt)
        if termination is None and not checks_failed:
            break            # healthy answer: stop here, never escalate further
        # dead or failed checks: try the next tier, if there is one
    provider, model = tier["provider"], tier["model"]
    if checks_failed:
        record = {**record, "checks_failed": checks_failed}
    if termination is not None:
        record = {**record, "termination": termination}
    if len(attempts) > 1:
        record = {**record, "tier": k, "attempts": attempts}
    entry = {"ts": datetime.now().isoformat(timespec="seconds"),
             "model": model, "provider": provider, "input": text,
             **(extra or {}), **record}
    if log:
        # Observability: every live run is appended as one JSONL line — the raw feed
        # for the corrections flywheel (wrong output + human fix -> new eval case).
        live_dir = RESULTS_DIR / "live"
        live_dir.mkdir(parents=True, exist_ok=True)
        with (live_dir / f"{agent_name}.jsonl").open("a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if termination is not None:
        # After the write, never before: the record is the point. Fail loud, never a
        # placeholder — a live run that emitted no answer must not return as if it had.
        raise TerminationError(
            f"live run of {agent_name!r} on {model!r} emitted no answer "
            f"({termination})", termination)
    return entry, record


def cmd_live(args) -> int:
    """Run an agent on real input (not the exam) — the actual-use path.

    Uses the agent's champion model and, for tool agents, the REAL tools.py
    (exams use tools_mock.py). Input from --input or stdin.
    """
    text = args.input if args.input else sys.stdin.read()
    if not text.strip():
        sys.exit("error: no input (use --input or pipe text on stdin)")
    try:
        _entry, record = live_run_and_log(args.agent, text,
                                          provider=args.provider, model=args.model)
    except TerminationError as exc:
        # Still loud and still non-zero, but through this repo's convention instead of
        # a raw traceback. The JSONL line was already written (live_run_and_log logs
        # before it raises), so the evidence is on disk and the operator gets a
        # sentence rather than a stack.
        sys.exit(f"error: {args.agent} emitted no answer — {exc.details}. "
                 f"The run was still logged to results/live/{args.agent}.jsonl.")
    print(json.dumps(record, indent=2, ensure_ascii=False))
    if record.get("checks_failed"):
        # LIVE-ROUTING A2b: every tier answered but the LAST answer still fails the
        # expectation-free checks. The output is printed (it exists, and the operator
        # may want it) but the exit is non-zero — a flagged answer must never look
        # like a clean one to a caller reading only the exit code.
        print(f"error: {args.agent}'s final answer failed live output checks: "
              f"{record['checks_failed']} (tier {record.get('tier', 0)}; logged to "
              f"results/live/{args.agent}.jsonl)", file=sys.stderr)
        return 2
    return 0


INTAKE_AGENT = "task-intake"
EXIT_FLAGGED = 2        # an answer that failed its live checks (never reported clean)
EXIT_NO_SPECIALIST = 3  # the dispatcher abstained ('none'): nothing was run


def cmd_intake(args) -> int:
    """A4: the request pipeline. ONE free-form request -> the dispatcher (`task-intake`,
    through routes.yaml like any live run) names a specialist and hands over its
    verbatim input -> that specialist runs live, through ITS tiers -> its record is
    printed. Two logged lines (results/live/task-intake.jsonl and
    results/live/<specialist>.jsonl, the second carrying `via`/`request` provenance),
    one exit code:
      0  the specialist answered and passed its live checks
      2  a FLAGGED answer — the dispatcher's hand-over failed its checks (never
         dispatched: a paraphrased or invented hand-over must not reach a specialist),
         or the specialist's final answer failed its own checks
      3  the dispatcher said 'none' — no specialist fits; the request is printed back
         and nothing else runs (a declared abstention is not an error)
      1  a dead run on every tier (TerminationError -> sys.exit sentence, as `live`)
    Nothing here is a new checker or a new router: both stages ARE live_run_and_log."""
    text = args.input if args.input else sys.stdin.read()
    if not text.strip():
        sys.exit("error: no input (use --input or pipe text on stdin)")
    try:
        _entry, verdict = live_run_and_log(INTAKE_AGENT, text)
    except TerminationError as exc:
        sys.exit(f"error: {INTAKE_AGENT} emitted no answer — {exc.details}. Logged to "
                 f"results/live/{INTAKE_AGENT}.jsonl.")
    out = verdict.get("output") or {}
    if verdict.get("checks_failed"):
        print(json.dumps(verdict, indent=2, ensure_ascii=False))
        print(f"error: {INTAKE_AGENT}'s hand-over failed live output checks: "
              f"{verdict['checks_failed']} — not dispatched", file=sys.stderr)
        return EXIT_FLAGGED
    agent, handed = out.get("agent"), out.get("input", "")
    if agent == "none":
        print(json.dumps({"agent": "none", "request": text}, indent=2, ensure_ascii=False))
        print(f"{INTAKE_AGENT}: no specialist fits this request", file=sys.stderr)
        return EXIT_NO_SPECIALIST
    try:
        _entry, record = live_run_and_log(agent, handed,
                                          extra={"via": INTAKE_AGENT, "request": text})
    except TerminationError as exc:
        sys.exit(f"error: {agent} emitted no answer — {exc.details}. Logged to "
                 f"results/live/{agent}.jsonl.")
    print(json.dumps({"agent": agent, "input": handed, **record}, indent=2, ensure_ascii=False))
    if record.get("checks_failed"):
        print(f"error: {agent}'s final answer failed live output checks: "
              f"{record['checks_failed']} (via {INTAKE_AGENT})", file=sys.stderr)
        return EXIT_FLAGGED
    return 0


def cmd_promote(args) -> int:
    """Turn a logged live run (results/live/<agent>.jsonl, 1-indexed --line) into a new
    TRAIN case in evals/<agent>/cases.json. The operator supplies the corrected
    expectation via --expected; no model ever invents it.

    Structurally incapable of writing a heldout case: there is no --split flag on this
    subcommand and "split": "train" below is the only place split is ever set — not a
    default, not a comment, an actual absence of any other code path. Every check below
    runs BEFORE cases.json is opened for write, so any failure leaves it byte-identical;
    the write is append-only over the full parsed dict, so every other top-level key
    (including Stage 1's "not_verified") survives untouched.
    """
    exam_path = ROOT / "evals" / args.agent / "cases.json"
    live_path = RESULTS_DIR / "live" / f"{args.agent}.jsonl"

    if not exam_path.exists():
        sys.exit(f"error: no exam for {args.agent!r} ({exam_path})")
    if not live_path.exists():
        sys.exit(f"error: no live log for {args.agent!r} ({live_path})")

    lines = live_path.read_text().splitlines()
    if args.line < 1 or args.line > len(lines):
        sys.exit(f"error: line {args.line} out of range (1..{len(lines)}) in "
                 f"{live_path.relative_to(ROOT)}")
    raw_line = lines[args.line - 1]
    try:
        record = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        sys.exit(f"error: {live_path.relative_to(ROOT)} line {args.line} is not "
                 f"valid JSON: {exc}")
    if not isinstance(record, dict) or "input" not in record:
        sys.exit(f"error: {live_path.relative_to(ROOT)} line {args.line} has no "
                 f"'input' field")

    try:
        expected = json.loads(args.expected)
    except json.JSONDecodeError as exc:
        sys.exit(f"error: --expected is not valid JSON: {exc}")
    if not isinstance(expected, dict):
        sys.exit("error: --expected must be a JSON object")

    exam = json.loads(exam_path.read_text())  # full dict; every top-level key preserved
    existing_ids = {c["id"] for c in exam.get("cases", [])}
    new_id = args.id or (f"promoted-{args.agent}-line{args.line}-"
                         f"{datetime.now().strftime('%Y%m%dT%H%M%S')}")
    if new_id in existing_ids:
        sys.exit(f"error: case id {new_id!r} already exists in "
                 f"{exam_path.relative_to(ROOT)} — refusing to overwrite")

    # Every check above passed — mutate now. Append-only: never touch an existing case.
    new_case = {
        "id": new_id,
        "split": "train",  # the only split promote can ever write — no flag sets this
        "input": record["input"],
        "expected": expected,
    }
    exam["cases"].append(new_case)
    exam_path.write_text(json.dumps(exam, indent=2, ensure_ascii=False) + "\n")
    print(f"promoted {live_path.relative_to(ROOT)}:{args.line} -> "
          f"{exam_path.relative_to(ROOT)} case {new_id!r} (split=train)")
    return 0


def cmd_worker(args) -> int:
    """Lane 0: thin passthrough to sandbox/worker.py — `run` (fetch+triage a real
    inbox, read-only) and `digest` (render the daily needs-you markdown) live there
    with their own argparse; this adapter parses nothing itself.

    The `import worker` MUST be lazy (inside this function body), never hoisted to
    this file's top-level imports: `worker.py` imports `shadow_gmail`, and
    `shadow_gmail.py` does `import runner` at ITS top level — a top-level
    `import worker` here would close that into a circular import
    (runner -> worker -> shadow_gmail -> runner), reproduced when tried.
    """
    import worker
    return worker.main(args.args)


def cmd_taxonomy(args) -> int:
    """E9: roll recorded failures up into model x category counts.

    Read-only over results/, offline, and NOT a gate — it prints a report and always
    returns 0. Its whole implementation lives in taxonomy.py; this is the CLI seam.
    """
    return taxonomy.run(args)


def cmd_probe(args) -> int:
    """E7 bullet 2: reliability as a first-class recorded number.

    pass@k per case per (model, temperature) — a capability probe, NEVER a gate
    (pass@k is barred from gates; CLAUDE.md golden principles). Writes records
    only under results/probe/ in a non-gate shape; never touches cases.json or
    any snapshot.json, and check/check-all/diff never read its output. Its whole
    implementation lives in probe.py; this is the CLI seam.
    """
    return probe.run(args)


def cmd_route(args) -> int:
    """E12: which tier should each task START on, and is escalating worth it.

    Read-only over results/, offline, and NOT a gate — it prints a report and always
    returns 0. Its whole implementation lives in policy.py; this is the CLI seam.
    """
    return policy.run(args)


def cmd_list(_args) -> int:
    for agent_dir in sorted((ROOT / "agents").iterdir()):
        if not (agent_dir / "agent.yaml").exists():
            continue
        cfg = yaml.safe_load((agent_dir / "agent.yaml").read_text())
        exam_path = ROOT / "evals" / cfg["name"] / "cases.json"
        if exam_path.exists():
            exam = json.loads(exam_path.read_text())
            status = f"exam ok, mode={exam.get('mode', 'labels')}"
            # SNAPSHOT-REPRODUCIBILITY: read straight from the per-case field, not
            # recomputed — "-" when the snapshot predates it, so a stale snapshot
            # (pre-this-lane, or never re-taken) is visible here rather than
            # silently reading as "0 unstable".
            snap_path = ROOT / "evals" / cfg["name"] / "snapshot.json"
            if snap_path.exists():
                cases = json.loads(snap_path.read_text()).get("cases", [])
                if cases and all("stable" in c for c in cases):
                    k = sum(1 for c in cases if not c["stable"])
                    status += f", unstable {k}/{len(cases)}"
                else:
                    status += ", unstable -"
        else:
            status = "NO EXAM"
        print(f"{cfg['name']:<24} {cfg['provider']}/{cfg['model']:<28} [{status}]")
    return 0


# ------------------------------------------------------------------ E21 bake-off

class _BakeoffCtx:
    """The call machinery a strategy needs, without strategies.py importing runner.

    Deliberately separate from run_exam: the bake-off is a read-only EXPERIMENT over
    committed cases. It writes no snapshot and cannot move a gate, so a strategy that
    turns out badly costs a report, never a score.
    """

    def __init__(self, agent, adapter, model, triage_agent=None, triage_adapter=None,
                 triage_model=None):
        self.agent, self.adapter, self.model = agent, adapter, model
        self.triage_agent = triage_agent
        self.triage_adapter = triage_adapter
        self.triage_model = triage_model

    def call(self, system_prompt, user_text, max_tokens=None):
        """One raw model call under the agent's own model/adapter, with a caller-chosen
        system prompt — the primitive a multi-call strategy (E28) needs and call_recap
        already had inline. Discards the raw string exactly as call_recap always did.

        `max_tokens`, when given, overrides the agent's own budget for THIS call only
        (E30's extraction step wants more room than the champion's own generation call) —
        the default `None` leaves `self.agent` untouched, so every existing caller
        (call_recap, commit_list_then_write's two calls) is byte-identical to before."""
        msgs = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}]
        agent = self.agent if max_tokens is None else dict(self.agent, max_tokens=max_tokens)
        parsed, _raw, metrics = call_model(agent, self.adapter, self.model, msgs)
        return parsed, metrics

    def call_recap(self, day_text):
        return self.call(self.agent["system_prompt"], day_text)

    def call_triage(self, item_text):
        """-> (label, metrics). An unparseable label is treated as NOT-ignore: the
        filter's failure mode must be keeping noise, never silently dropping signal."""
        msgs = [{"role": "system", "content": self.triage_agent["system_prompt"]},
                {"role": "user", "content": item_text}]
        parsed, _raw, metrics = call_model(self.triage_agent, self.triage_adapter,
                                           self.triage_model, msgs)
        label = (parsed or {}).get("label")
        return (label if isinstance(label, str) else ""), metrics


def _bakeoff_score(props, case, parsed):
    """Score ALWAYS against the ORIGINAL committed input — see strategies.py's invariant.
    Passing a strategy's transformed text here makes every parameterised check pass
    vacuously, because properties.py resolves expectations by exact input text."""
    ok, _failures, failed = run_properties(props, case["input"], parsed)
    return ok, [f["check"] for f in failed]


def cmd_bakeoff(args) -> int:
    """E21: score N architectures on the SAME committed cases. Heldout untouched."""
    agent = load_agent(args.agent)
    exam = load_exam(args.agent)
    props = load_properties(args.agent)
    if not props:
        sys.exit(f"error: {args.agent} has no properties.py — nothing to score against")
    model = args.model or agent["model"]
    adapter = adapter_for(agent, timeout=args.timeout)
    names = [n.strip() for n in args.strategies.split(",") if n.strip()]
    unknown = [n for n in names if n not in strategies.STRATEGIES]
    if unknown:
        sys.exit(f"error: unknown strateg(ies) {unknown}. "
                 f"Valid: {sorted(strategies.STRATEGIES)}")

    triage_agent = triage_adapter = triage_model = None
    if "filter-then-recap" in names:
        triage_agent = load_agent(args.filter_agent)
        triage_model = triage_agent["model"]
        triage_adapter = adapter_for(triage_agent, timeout=args.timeout)
        print(f"filter stage: {args.filter_agent} @ {triage_model}")

    ctx = _BakeoffCtx(agent, adapter, model, triage_agent, triage_adapter, triage_model)
    long_min = args.long_min
    cases = exam["cases"]
    report = {}
    for name in names:
        fn = strategies.STRATEGIES[name]
        rows, tot = [], {"train": [0, 0], "heldout": [0, 0], "long": [0, 0]}
        spend = {"tokens": 0, "calls": 0, "think": 0, "answer": 0, "unknown": False}
        print(f"\n=== {name} ===")
        for case in cases:
            try:
                parsed, metrics = fn(ctx, case)
                ok, checks = _bakeoff_score(props, case, parsed)
            except Exception as exc:            # fail loud, per case, keep going
                ok, checks, metrics = False, [f"error:{type(exc).__name__}"], []
            split = case["split"]
            tot[split][1] += 1
            tot[split][0] += int(ok)
            if len(case["input"]) >= long_min:
                tot["long"][1] += 1
                tot["long"][0] += int(ok)
            for m in metrics:
                spend["calls"] += 1
                if m.get("total_tokens") is None:
                    spend["unknown"] = True
                else:
                    spend["tokens"] += m["total_tokens"]
                spend["think"] += m.get("reasoning_chars") or 0
                spend["answer"] += m.get("content_chars") or 0
            # `out_chars` is load-bearing, not decoration: without it a compression
            # failure cannot be attributed to the model's output length vs the case's
            # limit, and that distinction turned out to BE the E21 finding.
            out_chars = len(((parsed or {}).get("recap") or "")) if isinstance(parsed, dict) else 0
            limit = None
            ratio = (case.get("expected") or {}).get("max_ratio")
            if ratio is not None:
                limit = int(len(case["input"]) * float(ratio))
            rows.append({"id": case["id"], "split": split,
                         "chars": len(case["input"]), "out_chars": out_chars,
                         "limit": limit, "passed": ok, "checks": checks})
            print(f"  [{'PASS' if ok else 'FAIL'}] {case['id']:22s} {split:8s} "
                  f"in={len(case['input']):5d} out={out_chars:4d} "
                  f"limit={limit if limit is not None else '-':>4}  {','.join(checks)}")
        report[name] = {"rows": rows, "totals": tot, "spend": spend}

    print(f"\n{'strategy':<20} {'train':>7} {'heldout':>9} {'LONG':>7} {'calls':>6} "
          f"{'tok/case':>9} {'think%':>7}")
    print("-" * 72)
    for name in names:
        r = report[name]
        t, sp = r["totals"], r["spend"]
        gen = sp["think"] + sp["answer"]
        think = f"{100.0 * sp['think'] / gen:.0f}%" if gen else "-"
        tok = "unknown" if sp["unknown"] else f"{sp['tokens'] / max(1, len(cases)):.0f}"
        print(f"{name:<20} {t['train'][0]}/{t['train'][1]:<5} "
              f"{t['heldout'][0]}/{t['heldout'][1]:<7} {t['long'][0]}/{t['long'][1]:<5} "
              f"{sp['calls']:>6} {tok:>9} {think:>7}")

    # Failure MODES, not just counts. long-day-heldout-xl fails as `error` for the
    # champion and `check_coverage` for a shortening strategy — reporting only the pass
    # count would credit a strategy for escaping a truncation artifact (ledger 014).
    print("\nlong-band failure modes (why, not just how many):")
    for case in cases:
        if len(case["input"]) < long_min:
            continue
        line = f"  {case['id']:22s} {len(case['input']):5d}ch |"
        for name in names:
            row = next(r for r in report[name]["rows"] if r["id"] == case["id"])
            mark = "PASS" if row["passed"] else ",".join(
                c.replace("check_", "") for c in row["checks"]) or "FAIL"
            line += f" {name.split('-')[0][:6]}:{mark:<14}"
        print(line)
    out = ROOT / "results" / f"bakeoff__{args.agent}__{model.replace(':', '_')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"agent": args.agent, "model": model,
                               "long_min": long_min, "report": report}, indent=2))
    print(f"\nwritten -> {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("run", cmd_run), ("check", cmd_check), ("diff", cmd_diff)):
        sp = sub.add_parser(name)
        sp.add_argument("agent")
        sp.add_argument("--provider")
        # WHICH MODEL-AFFECTING FLAGS MAY SIT ON `check` (one rule, two flags).
        # `check` is the regression gate, so a flag it accepts must never be able to
        # move a score without saying so. The test is whether the flag's effect is
        # VISIBLE IN THE RESULT: --dedupe-tools is the independent variable of a
        # declared experiment and every suppression it performs is counted in
        # detail["deduped_calls"], so a both-ways `check` — which is exactly what the
        # gate-0 A/B is — reports what it changed. --timeout (E22a) is the opposite:
        # a request that times out scores identically to a model that cannot answer,
        # so raising it silently redefines a green gate. Hence --dedupe-tools on all
        # three commands, --timeout on `run`/`diff` only (sweeping a slow model is
        # `run`/`diff`/`bakeoff` work). Both default to the committed behavior.
        #
        # TERMINATION-DETECT D4 does NOT relax this. A timing-out case now fails with
        # {"bucket": "termination", "check": "termination", cause "timeout"} instead of
        # aborting the whole run, which makes the difference between "the request timed
        # out" and "the model cannot answer" VISIBLE in the record — it does not make
        # them cost the same. Raising --timeout would still silently redefine a green
        # gate, so --timeout stays off `check`.
        sp.add_argument("--dedupe-tools", action="store_true",
                        help="suppress repeated identical tool calls at runtime "
                             "(serve the cached result; default off)")
        sp.set_defaults(fn=fn)
        if name in ("run", "diff"):
            sp.add_argument("--timeout", type=int, default=None,
                            help="per-request seconds (default: agent.yaml timeout_s, "
                                 f"else {DEFAULT_TIMEOUT_S})")
            # E27: the context-assembly arm for `turns`-bearing cases. Off `check`
            # for the same reason --timeout is: the gate must reproduce the
            # committed snapshot, which is a "full" run. CLI-only — never an
            # agent.yaml field (champion fields are operator-signed).
            sp.add_argument("--assembly", choices=list(ASSEMBLY_MODES), default="full",
                            help="multi-turn context assembly: full history (default, "
                                 "byte-identical to before) or a rule-scoped slice "
                                 "(E27 A/B arm; single-turn cases and turn 0 unaffected)")
        if name == "run":
            sp.add_argument("--model")
            sp.add_argument("--snapshot", action="store_true")
            # SNAPSHOT-REPRODUCIBILITY: default 3, validated (odd, >= 3) in
            # cmd_run via _validate_loads BEFORE any inference. Only --snapshot
            # runs the multi-load protocol; a plain `run` ignores this flag.
            sp.add_argument("--loads", type=int, default=3,
                            help="fresh model loads to aggregate under --snapshot "
                                 "(default 3; must be odd and >= 3)")
        if name == "check":
            sp.add_argument("--tolerance", type=float, default=0.0)
        if name == "diff":
            sp.add_argument("--models", required=True)
    sp = sub.add_parser("run-all")
    sp.add_argument("--snapshot", action="store_true")
    sp.add_argument("--loads", type=int, default=3,
                    help="fresh model loads to aggregate under --snapshot "
                         "(default 3; must be odd and >= 3)")
    sp.set_defaults(fn=cmd_run_all)
    sp = sub.add_parser("check-all")
    sp.add_argument("--tolerance", type=float, default=0.0)
    sp.set_defaults(fn=cmd_check_all)
    sp = sub.add_parser("live")
    sp.add_argument("agent")
    sp.add_argument("--input")
    sp.add_argument("--model")
    sp.add_argument("--provider")
    sp.set_defaults(fn=cmd_live)
    sp = sub.add_parser("intake")
    sp.add_argument("--input")
    sp.set_defaults(fn=cmd_intake)
    sp = sub.add_parser("promote")
    sp.add_argument("agent")
    sp.add_argument("line", type=int)
    sp.add_argument("--expected", required=True,
                    help="JSON object: the corrected expectation (operator-supplied)")
    sp.add_argument("--id", help="case id (default: auto-generated, collision-checked)")
    sp.set_defaults(fn=cmd_promote)
    # No --split here, deliberately: this subcommand has no code path that can write
    # anything but split="train" (see cmd_promote docstring).
    # Lane 0: a thin REMAINDER passthrough to sandbox/worker.py — `run`/`digest` and
    # all their flags are worker.py's OWN argparse. add_help stays at its default
    # (True) deliberately: argparse's REMAINDER has a known limitation where a
    # LEADING option-looking token (nothing but `--help` — no `run`/`digest` before
    # it) is never absorbed into REMAINDER and is reported as unrecognized instead
    # (reproduced: `add_help=False` here made bare `worker --help` exit 2). Keeping
    # this parser's own `-h`/`--help` catches exactly that bare case (exits 0, if
    # with this parser's own generic text); `worker run --help` / `worker digest
    # --help` are unaffected — `run`/`digest` is a real token first, so REMAINDER
    # still grabs `--help` and forwards it to worker.py's own, more useful, -h.
    sp = sub.add_parser("worker")
    sp.add_argument("args", nargs=argparse.REMAINDER)
    sp.set_defaults(fn=cmd_worker)
    sp = sub.add_parser("list")
    sp.set_defaults(fn=cmd_list)
    # Report, not a gate: deliberately absent from check-all, and it never writes.
    sp = sub.add_parser("taxonomy")
    taxonomy.add_arguments(sp)
    sp.set_defaults(fn=cmd_taxonomy)
    # Same deal: a report. E12's escalation policy, never a gate.
    sp = sub.add_parser("route")
    policy.add_arguments(sp)
    sp.set_defaults(fn=cmd_route)
    # E7 bullet 2: reliability probe. pass@k is BARRED from gates — this records
    # it as a capability figure, structurally separate (results/probe/, non-gate
    # shape). Deliberately absent from check-all.
    sp = sub.add_parser("probe")
    probe.add_arguments(sp)
    sp.set_defaults(fn=cmd_probe)
    # E21: architectures, not models. Read-only over committed cases — writes no
    # snapshot, so a bad strategy costs a report and never a gate.
    sp = sub.add_parser("bakeoff")
    sp.add_argument("agent")
    sp.add_argument("--strategies", default=",".join(strategies.STRATEGIES))
    sp.add_argument("--model", help="override the agent's champion for every stage")
    sp.add_argument("--filter-agent", default="email-triage",
                    help="agent used as the filter stage of filter-then-recap")
    sp.add_argument("--long-min", type=int, default=4200,
                    help="chars at or above which a case counts as LONG (E13's band)")
    sp.add_argument("--timeout", type=int, default=None,
                    help="per-request seconds (default: agent.yaml timeout_s, "
                         f"else {DEFAULT_TIMEOUT_S})")
    sp.set_defaults(fn=cmd_bakeoff)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
