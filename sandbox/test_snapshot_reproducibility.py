#!/usr/bin/env python3
"""Deterministic tests for SNAPSHOT-REPRODUCIBILITY — no model, no server.

    python3 sandbox/test_snapshot_reproducibility.py

The premise (docs/probes/determinism-2026-09-06/RESULTS.md): local temp-0 output is
deterministic WITHIN one Ollama model load and NOT across loads, so a snapshot taken
on one load and checked against a fresh load can disagree per case while the heldout
AGGREGATE stays unchanged by cancellation — and master's `check` only ever compares
that aggregate. This file pins the fix in both directions (CLAUDE.md gotcha 2: a
green guard proves nothing until seen RED):

  * `aggregate_loads` — the pure N-loads -> one-result reducer (majority `passed`,
    `stable` iff unanimous, scores recomputed over ALL cases from majority verdicts).
  * `compare_to_snapshot` — the pure per-case-drift-OR-aggregate-regression verdict
    `cmd_check`/`cmd_check_all` share.
  * `snapshot_preflight` — the three pre-inference refusals (no runtime; ollama-only
    version mismatch; case-id mismatch), provider-gated per criterion v3 halt 2.
  * `_validate_loads` — odd, >= 3, refused with SystemExit before any inference.
  * `ollama_version`/`ollama_unload` — native-API helpers, stdlib urllib, mocked here.
  * The CLI wiring (`cmd_run --snapshot --loads`, `cmd_check`, `cmd_run_all
    --snapshot`, `cmd_check_all`, `cmd_list`) driven through the real entry points
    with `run_exam`/network calls monkeypatched at the boundary — same pattern
    test_dedupe_tools.py and test_termination.py already use in this repo.

THE FLAGSHIP TEST (test_red_demonstration_...) is the repo-invariant-mandated one:
"seen RED on the defect it exists to catch, through the real entry point (runner.py),
with the injection target named." It loads MASTER's actual, unmodified `cmd_check`
(via its pinned pre-fix blob, exec'd under a distinct module name) and
runs it against a hand-built two-case fixture where one case flips PASS->FAIL and the
other flips FAIL->PASS (aggregate heldout score unchanged) — master's real code prints
`ok`. The SAME fixture through this PR's real `cmd_check` prints a DRIFT table and
exits 1. Both are asserted, so a revert to master's aggregate-only logic on this exact
fixture turns this test RED.

Plain asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402
from runner import (  # noqa: E402
    ROOT, _load_module, _snapshot_case, _validate_loads, aggregate_loads,
    cmd_check, cmd_list, cmd_run, cmd_run_all, compare_to_snapshot, ollama_unload,
    ollama_version, snapshot_payload, snapshot_preflight, take_snapshot_loads,
)

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


# ------------------------------------------------------------- fixture helpers

def _load_result(agent="fixture-agent", provider="ollama", model="m", mode="labels",
                 cases=None) -> dict:
    """A `run_exam`-shaped result. `cases` entries need only id/split/passed plus
    whatever the caller wants to assert on (failed_checks, detail, ...)."""
    cases = cases or []
    def _agg(split):
        subset = [c for c in cases if c["split"] == split]
        passed = sum(1 for c in subset if c["passed"])
        total = len(subset)
        return {"passed": passed, "total": total,
                "score": round(passed / total, 4) if total else None}
    return {"agent": agent, "provider": provider, "model": model, "mode": mode,
            "train": _agg("train"), "heldout": _agg("heldout"), "cases": cases}


def _case(cid, split, passed, **extra) -> dict:
    return {"id": cid, "split": split, "passed": passed,
            "expected": {}, "got": {}, **extra}


# --------------------------------------------------------------- aggregate_loads

def test_aggregate_loads_one_case_flips_stable_false_majority_from_two():
    """3 loads, ONE case flips on load 2: passed = majority (2 of 3), stable=False,
    failed_checks from the FIRST load that agreed with the majority (load 1, not the
    dissenting load 2)."""
    loads = [
        _load_result(cases=[_case("x", "heldout", True),
                            _case("y", "heldout", True,
                                 failed_checks=[{"bucket": "quality", "check": "labels"}])]),
        _load_result(cases=[_case("x", "heldout", False,
                                  failed_checks=[{"bucket": "quality", "check": "labels"}]),
                            _case("y", "heldout", True)]),
        _load_result(cases=[_case("x", "heldout", True),
                            _case("y", "heldout", True)]),
    ]
    agg = aggregate_loads(loads)
    by_id = {c["id"]: c for c in agg["cases"]}
    check("x: majority PASS (2 of 3), UNSTABLE",
          by_id["x"]["passed"] is True and by_id["x"]["stable"] is False,
          str(by_id["x"]))
    check("x: failed_checks came from load 1 (the majority-agreeing load), not load 2",
          by_id["x"].get("failed_checks", []) == [], str(by_id["x"]))
    check("y: unanimous PASS, STABLE",
          by_id["y"]["passed"] is True and by_id["y"]["stable"] is True, str(by_id["y"]))
    check("heldout score recomputed from majority verdicts over ALL cases (2/2 = 1.0)",
          agg["heldout"] == {"passed": 2, "total": 2, "score": 1.0}, str(agg["heldout"]))
    check("metrics_totals from load 1 is DROPPED, not silently presented as the total",
          "metrics_totals" not in agg, str(agg.get("metrics_totals")))


def test_aggregate_loads_two_loads_disagree_documented_no_majority():
    """2 loads that disagree: no majority exists. Documented behavior (brief's
    Tests section): passed = False, and the case is UNSTABLE (not all loads agree).
    This is aggregate_loads's OWN semantics, independent of the CLI's odd->=3
    restriction (which is enforced by _validate_loads, not this pure function)."""
    loads = [_load_result(cases=[_case("z", "train", True)]),
             _load_result(cases=[_case("z", "train", False)])]
    agg = aggregate_loads(loads)
    z = agg["cases"][0]
    check("2-way tie: passed=False (documented), stable=False",
          z["passed"] is False and z["stable"] is False, str(z))


def test_aggregate_loads_raises_below_two_loads():
    try:
        aggregate_loads([_load_result(cases=[_case("a", "train", True)])])
        check("N=1 raises", False, "did not raise")
    except ValueError as exc:
        check("N=1 raises", "aggregate_loads" in str(exc), str(exc))


def test_aggregate_loads_raises_on_case_id_mismatch():
    a = _load_result(cases=[_case("a", "train", True), _case("b", "train", True)])
    b = _load_result(cases=[_case("a", "train", True), _case("c", "train", True)])
    try:
        aggregate_loads([a, b])
        check("case-id mismatch between loads raises", False, "did not raise")
    except ValueError as exc:
        check("case-id mismatch between loads raises", "mismatch" in str(exc), str(exc))


def test_aggregate_loads_three_stable_agreeing_loads_all_stable():
    loads = [_load_result(cases=[_case("a", "heldout", True), _case("b", "heldout", False)])
             for _ in range(3)]
    agg = aggregate_loads(loads)
    check("3 identical loads: every case stable", all(c["stable"] for c in agg["cases"]),
          str(agg["cases"]))
    check("3 identical loads: verdicts unchanged",
          [(c["id"], c["passed"]) for c in agg["cases"]] == [("a", True), ("b", False)])


# ------------------------------------------------------- _snapshot_case / payload

def test_snapshot_case_carries_stable_only_when_input_has_it():
    """SNAPSHOT-REPRODUCIBILITY's ONE addition to _snapshot_case, same conditional
    pattern as turn_metrics — a case dict with no 'stable' key (every pre-lane
    caller, incl. test_observability.py's fixtures) gets byte-identical output."""
    with_stable = _snapshot_case({"id": "x", "split": "train", "passed": True,
                                 "stable": False})
    check("stable=False survives into the snapshot entry",
          with_stable.get("stable") is False, str(with_stable))
    check("key order: id, split, passed, stable",
          list(with_stable) == ["id", "split", "passed", "stable"], str(list(with_stable)))
    without_stable = _snapshot_case({"id": "y", "split": "train", "passed": True})
    check("no 'stable' key on the input -> none on the output (legacy shape preserved)",
          "stable" not in without_stable, str(without_stable))
    failing_stable = _snapshot_case({"id": "z", "split": "train", "passed": False,
                                     "stable": True, "failed_checks": [
                                         {"bucket": "quality", "check": "labels"}]})
    check("stable + failures key order: id, split, passed, stable, failures",
          list(failing_stable) == ["id", "split", "passed", "stable", "failures"],
          str(list(failing_stable)))


def test_snapshot_payload_omits_loads_and_runtime_when_not_passed():
    """The exact call shape test_observability.py uses (positional-only, no
    loads/runtime kwargs) must produce the EXACT old key set — that file asserts
    `set(snap) == {...}` and is out of this lane's declared file set."""
    agent = {"name": "reply-draft", "temperature": 0.0, "max_tokens": 2048}
    exam = json.loads((ROOT / "evals" / "reply-draft" / "cases.json").read_text())
    result = _load_result(agent="reply-draft", cases=[_case("a", "train", True)])
    snap = snapshot_payload(agent, exam, "ollama", "m", result)
    check("no loads/runtime passed -> neither key appears",
          "loads" not in snap and "runtime" not in snap, str(sorted(snap)))


def test_snapshot_payload_includes_loads_and_runtime_when_passed():
    agent = {"name": "reply-draft", "temperature": 0.0, "max_tokens": 2048}
    exam = json.loads((ROOT / "evals" / "reply-draft" / "cases.json").read_text())
    result = _load_result(agent="reply-draft", cases=[_case("a", "train", True)])
    snap = snapshot_payload(agent, exam, "ollama", "m", result, loads=5,
                            runtime={"name": "ollama", "version": "0.33.2"})
    check("loads: 5 written", snap.get("loads") == 5, str(snap.get("loads")))
    check("runtime written verbatim",
          snap.get("runtime") == {"name": "ollama", "version": "0.33.2"},
          str(snap.get("runtime")))


# --------------------------------------------------------------- compare_to_snapshot

def _snap(heldout_score, cases, provider="ollama", version="0.33.2") -> dict:
    return {"provider": provider, "model": "m", "heldout_score": heldout_score,
            "train_score": None, "runtime": {"name": provider, "version": version},
            "loads": 3, "cases": cases}


def test_compare_two_flip_fixture_drift_length_two_regression_pin():
    """Regression pin for the DEFECT this whole lane exists to fix (the 6 Sep
    shape): two STABLE heldout cases, one PASS->FAIL and one FAIL->PASS. The
    aggregate is UNCHANGED (0.5 -> 0.5) — a build reverted to master's
    aggregate-only comparison (sandbox/runner.py's pre-lane `cmd_check`: `drift =
    snap['heldout_score'] - result['heldout']['score']`) says ok on this fixture.
    `compare_to_snapshot` must not: drift length 2, ok False, regression False (the
    aggregate itself never moved — this is (a) firing without (b))."""
    snap = _snap(0.5, [_case("case-a", "heldout", True, stable=True),
                       _case("case-b", "heldout", False, stable=True)])
    result = _load_result(cases=[_case("case-a", "heldout", False),
                                 _case("case-b", "heldout", True)])
    verdict = compare_to_snapshot(snap, result)
    check("two-flip fixture: drift has both cases",
          {d[0] for d in verdict["drift"]} == {"case-a", "case-b"}, str(verdict["drift"]))
    check("two-flip fixture: aggregate did NOT regress (0.5 == 0.5) — (a) fires alone",
          verdict["regression"] is False, str(verdict))
    check("two-flip fixture: ok is False (a build gating on regression alone would say ok)",
          verdict["ok"] is False)
    # REVERT TARGET named per clause (4): a check() reduced to
    #   `regression = (snap['heldout_score'] - result['heldout']['score']) > tolerance`
    # with no per-case comparison at all — exactly master's pre-lane cmd_check body —
    # computes "ok" on this fixture. See test_red_demonstration_... below for the
    # SAME claim proven through master's actual unmodified code.
    master_logic_ok = not ((snap["heldout_score"] - (result["heldout"]["score"] or 0.0)) > 0.0)
    check("...and naming that revert target: master's aggregate-only formula says ok here",
          master_logic_ok is True)


def test_compare_stable_fail_to_pass_alone_is_drift_wrong_build_direction_only():
    """WRONG-BUILD TWIN (regression pin, clause 4): a stable FAIL->PASS ALONE (no
    accompanying PASS->FAIL) must still land in drift. Target: a build that only
    appends to drift when `scase['passed'] and not rcase['passed']`
    (PASS->FAIL-only, i.e. treats an improvement as never worth flagging) would
    produce an EMPTY drift list here — this asserts drift has exactly one entry."""
    snap = _snap(0.0, [_case("only", "heldout", False, stable=True)])
    result = _load_result(cases=[_case("only", "heldout", True)])
    verdict = compare_to_snapshot(snap, result)
    check("stable FAIL->PASS alone appears in drift (length 1)",
          len(verdict["drift"]) == 1 and verdict["drift"][0][:3] == ("only", False, True),
          str(verdict["drift"]))
    # The named wrong build, computed for real (not simulated): a comparison
    # that only fires on PASS->FAIL (an improvement is never worth flagging).
    wrong_build_drift = [(cid, was, now, fc) for cid, was, now, fc in verdict["drift"]
                         if was is True and now is False]
    check("WRONG-BUILD TARGET: PASS->FAIL-only direction would miss this FAIL->PASS",
          wrong_build_drift == [], str(wrong_build_drift))


def test_compare_unstable_flip_is_exempt_drift_empty_ok_true():
    snap = _snap(0.5, [_case("stable1", "heldout", True, stable=True),
                       _case("wobbly", "heldout", True, stable=False)])
    result = _load_result(cases=[_case("stable1", "heldout", True),
                                 _case("wobbly", "heldout", False)])
    verdict = compare_to_snapshot(snap, result)
    check("unstable case flip -> exempt, not drift",
          verdict["drift"] == [] and verdict["exempt"] == [("wobbly", False)],
          str(verdict))
    check("aggregate unchanged (0.5 -> 0.5) -> ok True",
          verdict["ok"] is True, str(verdict))
    check("n_stable/n_unstable computed from the snapshot's per-case field",
          verdict["n_stable"] == 1 and verdict["n_unstable"] == 1, str(verdict))


def test_compare_unstable_flip_past_tolerance_zero_stable_drift_exits_via_b():
    """HALT-1 TARGET (criterion v2's own defect): an UNSTABLE case flips FAIL->PASS
    in the snapshot's favor... no — flips such that the AGGREGATE regresses past
    tolerance while every STABLE case agrees (zero stable drift). `ok` must be
    False via (b) alone. WRONG-BUILD TARGET (named, clause 4): 'exit wired to
    drift only' — a build that returns `1 if verdict['drift'] else 0` (ignoring
    `regression` entirely) would return 0 here, which is exactly criterion v2's
    halt: a stable-cases-only gate silently let an unstable-driven aggregate
    regression through."""
    snap = _snap(1.0, [_case("stable1", "heldout", True, stable=True),
                       _case("stable2", "heldout", True, stable=True),
                       _case("stable3", "heldout", True, stable=True),
                       _case("stable4", "heldout", True, stable=True),
                       _case("wobbly", "heldout", True, stable=False)])
    result = _load_result(cases=[_case("stable1", "heldout", True),
                                 _case("stable2", "heldout", True),
                                 _case("stable3", "heldout", True),
                                 _case("stable4", "heldout", True),
                                 _case("wobbly", "heldout", False)])
    verdict = compare_to_snapshot(snap, result, tolerance=0.0)
    check("zero stable drift", verdict["drift"] == [], str(verdict["drift"]))
    check("aggregate regressed (snapshot 1.0 -> now 0.8, driven ONLY by the "
          "unstable case) regression fires",
          verdict["regression"] is True, str(verdict))
    check("ok is False purely via (b)", verdict["ok"] is False)
    wrong_build_exit = 1 if verdict["drift"] else 0   # named target: drift-only wiring
    check("WRONG-BUILD TARGET: exit-on-drift-only would wrongly return 0 (ok) here",
          wrong_build_exit == 0, f"got {wrong_build_exit}")
    check("the real rule (drift OR regression) correctly returns 1",
          (1 if not verdict["ok"] else 0) == 1)


def test_compare_raises_on_case_id_mismatch():
    snap = _snap(1.0, [_case("a", "train", True, stable=True)])
    result = _load_result(cases=[_case("b", "train", True)])
    try:
        compare_to_snapshot(snap, result)
        check("case-id mismatch raises", False, "did not raise")
    except ValueError as exc:
        check("case-id mismatch raises", "mismatch" in str(exc), str(exc))


# --------------------------------------------------------------- snapshot_preflight

def test_preflight_refuses_missing_runtime():
    snap = {"provider": "ollama", "cases": []}
    cause = snapshot_preflight(snap, {"cases": []})
    check("missing runtime -> RUNTIME: cause",
          cause is not None and cause.startswith("RUNTIME:"), str(cause))


def test_preflight_refuses_ollama_version_mismatch():
    snap = _snap(1.0, [_case("a", "train", True, stable=True)], version="0.30.0")
    cause = snapshot_preflight(snap, {"cases": [{"id": "a"}]},
                               version_fn=lambda: "0.33.2")
    check("ollama version mismatch -> VERSION: cause",
          cause is not None and cause.startswith("VERSION:"), str(cause))


def test_preflight_nonollama_never_calls_version_fn():
    """MISSING-FENCES advisory, directly falsified: a non-ollama snapshot's
    runtime.version is None per criterion v3 — comparing it unconditionally
    would refuse it FOREVER. version_fn must not even be called."""
    def _boom():
        raise AssertionError("version_fn called for a non-ollama snapshot")
    snap = _snap(1.0, [_case("a", "train", True, stable=True)],
                provider="scaleway", version=None)
    cause = snapshot_preflight(snap, {"cases": [{"id": "a"}]}, version_fn=_boom)
    check("non-ollama snapshot: no refusal, version_fn never invoked",
          cause is None, str(cause))


def test_preflight_refuses_case_id_mismatch():
    snap = _snap(1.0, [_case("a", "train", True, stable=True)])
    cause = snapshot_preflight(snap, {"cases": [{"id": "b"}]},
                               version_fn=lambda: "0.33.2")
    check("case-id mismatch -> CASES: cause",
          cause is not None and cause.startswith("CASES:"), str(cause))


def test_preflight_passes_clean_snapshot():
    snap = _snap(1.0, [_case("a", "train", True, stable=True)])
    cause = snapshot_preflight(snap, {"cases": [{"id": "a"}]},
                               version_fn=lambda: "0.33.2")
    check("clean snapshot: no refusal", cause is None, str(cause))


# --------------------------------------------------------- cmd_check refusals (real entry point)

class _StopAtRunExam(Exception):
    pass


def _run_cmd_check_expecting_no_run_exam(snap: dict, exam: dict,
                                        version_fn_result="0.33.2"):
    """Drives the REAL `cmd_check` with `_load_snapshot`, `load_agent`,
    `load_exam` and `ollama_version` monkeypatched, and `run_exam` a trap that
    raises if reached — proving the refusal fires BEFORE any inference."""
    real = (runner._load_snapshot, runner.load_agent, runner.load_exam,
           runner.run_exam, runner.ollama_version, runner.ollama_unload)
    exited = None
    try:
        runner._load_snapshot = lambda name: snap
        runner.load_agent = lambda name: {"name": name}
        runner.load_exam = lambda name: exam

        def _trap(*a, **k):
            raise AssertionError("run_exam was called — the refusal did not fire "
                                 "before inference")
        runner.run_exam = _trap
        runner.ollama_version = lambda: version_fn_result
        runner.ollama_unload = lambda model: (_ for _ in ()).throw(
            AssertionError("ollama_unload called before a refusal should have fired"))
        args = argparse.Namespace(agent="fixture-agent", dedupe_tools=False,
                                  tolerance=0.0)
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                cmd_check(args)
                exited = None
            except SystemExit as exc:
                exited = exc
    finally:
        (runner._load_snapshot, runner.load_agent, runner.load_exam, runner.run_exam,
         runner.ollama_version, runner.ollama_unload) = real
    return exited


def test_cmd_check_exits_before_run_exam_on_missing_runtime():
    snap = {"provider": "ollama", "cases": []}
    exam = {"cases": []}
    exited = _run_cmd_check_expecting_no_run_exam(snap, exam)
    check("cmd_check: missing runtime exits via SystemExit before run_exam",
          exited is not None and "RUNTIME" in str(exited.code), str(exited))


def test_cmd_check_exits_before_run_exam_on_version_mismatch():
    snap = _snap(1.0, [_case("a", "train", True, stable=True)], version="0.1.0")
    exam = {"cases": [{"id": "a"}]}
    exited = _run_cmd_check_expecting_no_run_exam(snap, exam, version_fn_result="0.33.2")
    check("cmd_check: ollama version mismatch exits via SystemExit before run_exam",
          exited is not None and "VERSION" in str(exited.code), str(exited))


def test_cmd_check_exits_before_run_exam_on_case_id_mismatch():
    snap = _snap(1.0, [_case("a", "train", True, stable=True)])
    exam = {"cases": [{"id": "different"}]}
    exited = _run_cmd_check_expecting_no_run_exam(snap, exam)
    check("cmd_check: case-id mismatch exits via SystemExit before run_exam",
          exited is not None and "CASES" in str(exited.code), str(exited))


# ---------------------------------------------------------- --loads validation

def test_validate_loads_refuses_1_2_4_accepts_3_5():
    for n in (1, 2, 4):
        try:
            _validate_loads(n)
            check(f"--loads {n} refused", False, "did not raise")
        except SystemExit as exc:
            check(f"--loads {n} refused", "odd" in str(exc), str(exc))
    for n in (3, 5, 7):
        try:
            _validate_loads(n)
            check(f"--loads {n} accepted", True)
        except SystemExit as exc:
            check(f"--loads {n} accepted", False, str(exc))


def _run_cmd_run_snapshot_expecting_no_inference(loads: int):
    """cmd_run --snapshot --loads N (N in {1,2,4}) must refuse BEFORE calling
    take_snapshot_loads, run_exam, or any native-API helper at all."""
    real = (runner.load_agent, runner.load_exam, runner.run_exam,
           runner.take_snapshot_loads, runner.ollama_unload, runner.ollama_version)

    def _boom(*a, **k):
        raise AssertionError("reached inference/native call after a bad --loads "
                             "should have refused first")
    exited = None
    try:
        runner.load_agent = lambda name: {"name": name, "provider": "ollama",
                                          "model": "m"}
        runner.load_exam = lambda name: {"mode": "labels", "cases": []}
        runner.run_exam = _boom
        runner.take_snapshot_loads = _boom
        runner.ollama_unload = _boom
        runner.ollama_version = _boom
        args = argparse.Namespace(agent="fixture-agent", provider=None, model=None,
                                  timeout=None, dedupe_tools=False, assembly="full",
                                  snapshot=True, loads=loads)
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                cmd_run(args)
            except SystemExit as exc:
                exited = exc
    finally:
        (runner.load_agent, runner.load_exam, runner.run_exam,
         runner.take_snapshot_loads, runner.ollama_unload,
         runner.ollama_version) = real
    return exited


def test_cmd_run_snapshot_loads_1_2_4_refused_before_inference():
    for n in (1, 2, 4):
        exited = _run_cmd_run_snapshot_expecting_no_inference(n)
        check(f"cmd_run --snapshot --loads {n}: SystemExit, no inference reached",
              exited is not None and "odd" in str(exited.code), str(exited))


def test_cmd_run_snapshot_loads_3_reaches_take_snapshot_loads():
    """The positive control for the refusal tests above: a VALID --loads must
    actually reach take_snapshot_loads (proves the trap tests above are real
    negative results, not a permanently-broken wire)."""
    real = (runner.load_agent, runner.load_exam, runner.take_snapshot_loads,
           runner.snapshot_payload)
    seen = {}
    try:
        runner.load_agent = lambda name: {"name": name, "provider": "ollama",
                                          "model": "m"}
        runner.load_exam = lambda name: {"mode": "labels", "cases": []}

        def _spy(agent, exam, provider, model, loads, **kw):
            seen["loads"] = loads
            return (_load_result(cases=[]), {"name": "ollama", "version": "0.33.2"})
        runner.take_snapshot_loads = _spy
        runner.snapshot_payload = lambda *a, **k: {"provider": "ollama"}
        args = argparse.Namespace(agent="fixture-agent", provider=None, model=None,
                                  timeout=None, dedupe_tools=False, assembly="full",
                                  snapshot=True, loads=3)
        with tempfile.TemporaryDirectory() as tmp:
            snap_dir = Path(tmp) / "evals" / "fixture-agent"
            snap_dir.mkdir(parents=True)
            real_root = runner.ROOT
            runner.ROOT = Path(tmp)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = cmd_run(args)
            finally:
                runner.ROOT = real_root
    finally:
        (runner.load_agent, runner.load_exam, runner.take_snapshot_loads,
         runner.snapshot_payload) = real
    check("--loads 3 (default): take_snapshot_loads reached with loads=3",
          seen.get("loads") == 3, str(seen))
    check("cmd_run --snapshot returns 0 on success", rc == 0, str(rc))


# --------------------------------------------------------------- take_snapshot_loads

def test_take_snapshot_loads_ollama_unloads_every_load():
    calls = {"unload": [], "version": 0, "run_exam": 0}
    real = (runner.ollama_unload, runner.ollama_version, runner.run_exam)
    try:
        runner.ollama_unload = lambda model: calls["unload"].append(model)

        def _ver():
            calls["version"] += 1
            return "0.33.2"
        runner.ollama_version = _ver

        def _run(agent, exam, provider, model, **kw):
            calls["run_exam"] += 1
            return _load_result(provider=provider, model=model,
                                cases=[_case("a", "heldout", True)])
        runner.run_exam = _run
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = runner.RESULTS_DIR
            runner.RESULTS_DIR = Path(tmp)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    aggregate, runtime = take_snapshot_loads(
                        {"name": "fixture-agent"}, {"cases": [{"id": "a"}]},
                        "ollama", "m", 3)
            finally:
                runner.RESULTS_DIR = real_dir
    finally:
        runner.ollama_unload, runner.ollama_version, runner.run_exam = real
    check("ollama: unload called once PER load (3)",
          calls["unload"] == ["m", "m", "m"], str(calls))
    check("ollama: run_exam called 3 times", calls["run_exam"] == 3, str(calls))
    check("runtime.version from ollama_version()", runtime == {"name": "ollama",
                                                               "version": "0.33.2"})
    check("aggregate has 1 case, stable, passed",
          len(aggregate["cases"]) == 1 and aggregate["cases"][0]["stable"] is True
          and aggregate["cases"][0]["passed"] is True, str(aggregate["cases"]))


def test_take_snapshot_loads_nonollama_never_unloads():
    real = (runner.ollama_unload, runner.run_exam)
    try:
        runner.ollama_unload = lambda model: (_ for _ in ()).throw(
            AssertionError("ollama_unload called for a non-ollama provider"))

        def _run(agent, exam, provider, model, **kw):
            return _load_result(provider=provider, model=model,
                                cases=[_case("a", "heldout", True)])
        runner.run_exam = _run
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = runner.RESULTS_DIR
            runner.RESULTS_DIR = Path(tmp)
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    aggregate, runtime = take_snapshot_loads(
                        {"name": "fixture-agent"}, {"cases": [{"id": "a"}]},
                        "scaleway", "m", 3)
            finally:
                runner.RESULTS_DIR = real_dir
    finally:
        runner.ollama_unload, runner.run_exam = real
    check("non-ollama: runtime.version is None (no shell-out, no fabricated value)",
          runtime == {"name": "scaleway", "version": None}, str(runtime))
    check("non-ollama: console says these are samples, not loads",
          "sample" in buf.getvalue(), buf.getvalue()[:200])


def test_take_snapshot_loads_saves_each_load_under_snapshot_loads_subdir():
    real = (runner.ollama_unload, runner.run_exam, runner.ollama_version)
    try:
        runner.ollama_unload = lambda model: None
        runner.ollama_version = lambda: "0.33.2"

        def _run(agent, exam, provider, model, **kw):
            return _load_result(agent="fixture-agent", provider=provider, model=model,
                                cases=[_case("a", "heldout", True)])
        runner.run_exam = _run
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = runner.RESULTS_DIR
            runner.RESULTS_DIR = Path(tmp)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    take_snapshot_loads({"name": "fixture-agent"},
                                        {"cases": [{"id": "a"}]}, "ollama", "m", 3)
            finally:
                runner.RESULTS_DIR = real_dir
                sub = Path(tmp) / "snapshot_loads"
                files = sorted(p.name for p in sub.glob("*.json")) if sub.exists() else []
                top_level = sorted(p.name for p in Path(tmp).glob("*.json"))
    finally:
        runner.ollama_unload, runner.run_exam, runner.ollama_version = real
    check("3 per-load files under results/snapshot_loads/, __load1..3 suffixed",
          files == ["fixture-agent__ollama__m__load1.json",
                    "fixture-agent__ollama__m__load2.json",
                    "fixture-agent__ollama__m__load3.json"], str(files))
    check("the aggregate is ALSO saved unsuffixed at the top level (taxonomy/route "
          "still glob results/*.json and see the current, majority-voted result)",
          top_level == ["fixture-agent__ollama__m.json"], str(top_level))


# ------------------------------------------------------------- ollama_* helpers

class _FakeHTTPResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_unload_raises_when_still_listed_in_ps():
    """The one native-API contract test the brief names explicitly: POST succeeds,
    but /api/ps still lists the model -> raise."""
    calls = []

    def fake_urlopen(req_or_url, timeout=10):
        url = req_or_url if isinstance(req_or_url, str) else req_or_url.full_url
        calls.append(url)
        if url.endswith("/api/generate"):
            return _FakeHTTPResponse(b'{"done": true, "done_reason": "unload"}')
        if url.endswith("/api/ps"):
            return _FakeHTTPResponse(
                json.dumps({"models": [{"model": "stuck-model"}]}).encode())
        raise AssertionError(f"unexpected URL {url}")

    real_urlopen = runner.urllib.request.urlopen
    try:
        runner.urllib.request.urlopen = fake_urlopen
        try:
            ollama_unload("stuck-model")
            check("ollama_unload raises when /api/ps still lists the model",
                  False, "did not raise")
        except RuntimeError as exc:
            check("ollama_unload raises when /api/ps still lists the model",
                  "stuck-model" in str(exc), str(exc))
    finally:
        runner.urllib.request.urlopen = real_urlopen
    check("both native endpoints were hit (generate then ps)",
          calls == [calls[0], calls[1]] and calls[0].endswith("/api/generate")
          and calls[1].endswith("/api/ps"), str(calls))


def test_ollama_unload_succeeds_when_ps_is_clean():
    def fake_urlopen(req_or_url, timeout=10):
        url = req_or_url if isinstance(req_or_url, str) else req_or_url.full_url
        if url.endswith("/api/generate"):
            return _FakeHTTPResponse(b'{"done": true}')
        return _FakeHTTPResponse(b'{"models": []}')
    real_urlopen = runner.urllib.request.urlopen
    try:
        runner.urllib.request.urlopen = fake_urlopen
        try:
            ollama_unload("gone-model")
            check("ollama_unload succeeds when /api/ps is clean", True)
        except Exception as exc:  # noqa: BLE001
            check("ollama_unload succeeds when /api/ps is clean", False, str(exc))
    finally:
        runner.urllib.request.urlopen = real_urlopen


def test_ollama_unload_tolerates_404_unknown_model_then_checks_ps():
    """Regression pin for a real collision this build hit: test_termination.py's
    outage test drives the real CLI with --model canned (never pulled) against a
    LIVE Ollama server. Ollama's /api/generate 404s on an unknown model
    ({"error": "model 'x' not found"}, verified against a live 0.33.2 server) —
    that model cannot possibly be resident, so /api/ps (the actual invariant)
    still gets checked and unload succeeds rather than crashing on an HTTPError
    that was never the failure mode the criterion cares about."""
    import urllib.error
    calls = []

    def fake_urlopen(req_or_url, timeout=10):
        url = req_or_url if isinstance(req_or_url, str) else req_or_url.full_url
        calls.append(url)
        if url.endswith("/api/generate"):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return _FakeHTTPResponse(b'{"models": []}')
    real_urlopen = runner.urllib.request.urlopen
    try:
        runner.urllib.request.urlopen = fake_urlopen
        try:
            ollama_unload("canned")
            check("404 unknown-model on /api/generate does not crash the unload",
                  True)
        except Exception as exc:  # noqa: BLE001
            check("404 unknown-model on /api/generate does not crash the unload",
                  False, str(exc))
    finally:
        runner.urllib.request.urlopen = real_urlopen
    check("/api/ps was still checked after the 404",
          any(u.endswith("/api/ps") for u in calls), str(calls))


def test_ollama_unload_reraises_non_404_http_errors():
    import urllib.error

    def fake_urlopen(req_or_url, timeout=10):
        url = req_or_url if isinstance(req_or_url, str) else req_or_url.full_url
        if url.endswith("/api/generate"):
            raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)
        raise AssertionError("should never reach /api/ps after a non-404 failure")
    real_urlopen = runner.urllib.request.urlopen
    try:
        runner.urllib.request.urlopen = fake_urlopen
        try:
            ollama_unload("m")
            check("a real 500 from /api/generate still raises", False, "did not raise")
        except urllib.error.HTTPError as exc:
            check("a real 500 from /api/generate still raises", exc.code == 500, str(exc))
    finally:
        runner.urllib.request.urlopen = real_urlopen


def test_ollama_version_reads_native_endpoint_no_shell_out():
    def fake_urlopen(req_or_url, timeout=10):
        url = req_or_url if isinstance(req_or_url, str) else req_or_url.full_url
        check("ollama_version hits /api/version", url.endswith("/api/version"), url)
        return _FakeHTTPResponse(b'{"version": "0.33.2"}')
    real_urlopen = runner.urllib.request.urlopen
    real_run = runner.subprocess.run
    try:
        runner.urllib.request.urlopen = fake_urlopen

        def _boom(*a, **k):
            raise AssertionError("ollama_version shelled out via subprocess.run")
        runner.subprocess.run = _boom
        check("ollama_version() returns the live version string",
              ollama_version() == "0.33.2")
    finally:
        runner.urllib.request.urlopen = real_urlopen
        runner.subprocess.run = real_run


# ---------------------------------------------------------- cmd_run_all / cmd_list

def test_cmd_run_all_snapshot_goes_through_take_snapshot_loads():
    """Criterion v3's closing sentence on clause 2: run-all --snapshot writes
    every snapshot through the SAME function cmd_run does."""
    real = (runner._all_agents, runner.load_agent, runner.load_exam,
           runner.take_snapshot_loads)
    seen = []
    try:
        runner._all_agents = lambda: ["fixture-agent"]
        runner.load_agent = lambda name: {"name": name, "provider": "ollama",
                                          "model": "m"}
        runner.load_exam = lambda name: {"mode": "labels", "cases": []}

        def _spy(agent, exam, provider, model, loads, **kw):
            seen.append((agent["name"], loads))
            return (_load_result(agent=agent["name"], cases=[]),
                   {"name": "ollama", "version": "0.33.2"})
        runner.take_snapshot_loads = _spy
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "evals" / "fixture-agent").mkdir(parents=True)
            real_root = runner.ROOT
            runner.ROOT = Path(tmp)
            try:
                args = argparse.Namespace(snapshot=True, loads=3)
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = cmd_run_all(args)
                written = json.loads(
                    (Path(tmp) / "evals" / "fixture-agent" / "snapshot.json")
                    .read_text())
            finally:
                runner.ROOT = real_root
    finally:
        (runner._all_agents, runner.load_agent, runner.load_exam,
         runner.take_snapshot_loads) = real
    check("cmd_run_all --snapshot calls take_snapshot_loads once per agent",
          seen == [("fixture-agent", 3)], str(seen))
    check("cmd_run_all --snapshot writes runtime/loads via the same snapshot_payload",
          written.get("loads") == 3 and written.get("runtime", {}).get("name") == "ollama",
          str(written))
    check("cmd_run_all returns 0", rc == 0)


def test_cmd_list_reads_unstable_from_per_case_field():
    real_root = runner.ROOT
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agents" / "with-unstable").mkdir(parents=True)
            (root / "agents" / "with-unstable" / "agent.yaml").write_text(
                "name: with-unstable\nprovider: ollama\nmodel: m\n")
            (root / "evals" / "with-unstable").mkdir(parents=True)
            (root / "evals" / "with-unstable" / "cases.json").write_text(
                json.dumps({"mode": "labels", "cases": []}))
            (root / "evals" / "with-unstable" / "snapshot.json").write_text(json.dumps({
                "cases": [{"id": "a", "split": "heldout", "passed": True, "stable": True},
                         {"id": "b", "split": "heldout", "passed": True, "stable": False}]}))
            (root / "agents" / "stale-snap").mkdir(parents=True)
            (root / "agents" / "stale-snap" / "agent.yaml").write_text(
                "name: stale-snap\nprovider: ollama\nmodel: m\n")
            (root / "evals" / "stale-snap").mkdir(parents=True)
            (root / "evals" / "stale-snap" / "cases.json").write_text(
                json.dumps({"mode": "labels", "cases": []}))
            (root / "evals" / "stale-snap" / "snapshot.json").write_text(json.dumps({
                "cases": [{"id": "a", "split": "heldout", "passed": True}]}))
            runner.ROOT = root
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_list(argparse.Namespace())
            out = buf.getvalue()
    finally:
        runner.ROOT = real_root
    check("cmd_list prints 'unstable 1/2' for a snapshot with the per-case field",
          "unstable 1/2" in out, out)
    check("cmd_list prints 'unstable -' for a snapshot that predates the field",
          "unstable -" in out, out)


# ------------------------------------------------- THE RED DEMONSTRATION (flagship)

# `git rev-parse c485bb4:sandbox/runner.py` — the last pre-fix runner.py (aggregate-only
# cmd_check). Content-addressed; see the comment inside the test for why not `master:`.
PRE_FIX_RUNNER_BLOB = "816a5ef778d48ab5029485288be9919fd2a15474"

def test_red_demonstration_master_ok_pr_drift_two_flip_fixture():
    """Repo invariant: 'seen RED on the defect it exists to catch, through the
    real entry point (runner.py), with the injection target named.'

    Loads the PRE-FIX `sandbox/runner.py` (the pinned blob below, exec'd
    under a distinct module name so it never collides with this PR's `runner`
    module already in sys.modules) and drives its REAL, UNMODIFIED `cmd_check`
    against a two-case fixture where case-a flips PASS->FAIL and case-b flips
    FAIL->PASS (aggregate heldout unchanged, 0.5 -> 0.5). Only `run_exam`,
    `load_agent`, `load_exam` and `ROOT` are monkeypatched (the exact same
    fixture-injection pattern this file uses everywhere else) — `cmd_check`
    itself is master's byte-for-byte code.

    REVERT TARGET (clause 4): master's `cmd_check` at the commit this branch was
    cut from (blob `PRE_FIX_RUNNER_BLOB`, around its own `cmd_check`
    definition) computes `drift = snap['heldout_score'] -
    result['heldout']['score']` and nothing else — it prints `ok` on this
    fixture. This PR's `cmd_check` prints a 2-row DRIFT table and exits 1 on the
    IDENTICAL fixture, proving the fix through the real entry point rather than
    a simulated replica of one.
    """
    # The PRE-FIX runner is pinned by CONTENT (the git blob of sandbox/runner.py at
    # c485bb4, the commit PR #79 was cut from), never by branch name: the first
    # version of this test said `git show master:...`, which was the pre-fix code
    # while the PR was open and became the FIX itself the moment it merged — the
    # test then compared the fix with the fix and went red on master (7 Sep). A
    # blob id is content-addressed, so it names the same bytes forever. If the
    # history is absent (a curated public cut ships files, not history), say so
    # loudly and skip the master half; the PR-side assertions below still bite.
    proc = subprocess.run(["git", "cat-file", "-p", PRE_FIX_RUNNER_BLOB], cwd=ROOT,
                          capture_output=True, text=True, timeout=15)
    have_pre_fix = proc.returncode == 0 and "def cmd_check" in proc.stdout
    if not have_pre_fix:
        print(f"  [SKIP] pre-fix runner blob {PRE_FIX_RUNNER_BLOB[:12]} not in this "
              f"clone's history — RED half of the demonstration not re-run here "
              f"(recorded at PR #79 time in docs/probes/snapshot-reproducibility-"
              f"2026-09-07/logs/test_output.txt); the PR-side half still runs")

    snap = {"provider": "ollama", "model": "m", "heldout_score": 0.5,
           "train_score": None,
           "runtime": {"name": "ollama", "version": "0.33.2"}, "loads": 3,
           "cases": [_case("case-a", "heldout", True, stable=True),
                    _case("case-b", "heldout", False, stable=True)]}
    exam = {"mode": "labels", "cases": [{"id": "case-a"}, {"id": "case-b"}]}
    fresh_run = _load_result(cases=[_case("case-a", "heldout", False),
                                    _case("case-b", "heldout", True)])

    master_rc, master_out = None, ""
    if have_pre_fix:
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "runner_master.py"
            scratch.write_text(proc.stdout)
            master_runner = _load_module(scratch, "master_runner_snapshot_repro_test")
            master_runner.ROOT = Path(tmp)   # only cmd_check's inline snap_path read needs this
            # the pre-fix cmd_check reads the snapshot straight off disk (no `_load_snapshot`
            # seam exists there — that helper is the fix's own refactor) — write it for real.
            snap_dir = Path(tmp) / "evals" / "fixture-agent"
            snap_dir.mkdir(parents=True)
            (snap_dir / "snapshot.json").write_text(json.dumps(snap))
            master_runner.load_agent = lambda name: {"name": name}
            master_runner.load_exam = lambda name: exam
            master_runner.run_exam = lambda *a, **k: fresh_run
            args = argparse.Namespace(agent="fixture-agent", dedupe_tools=False,
                                      tolerance=0.0)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                master_rc = master_runner.cmd_check(args)
            master_out = buf.getvalue()

    if have_pre_fix:
        check("MASTER's real cmd_check returns 0 (ok) on the two-flip fixture",
              master_rc == 0, f"rc={master_rc}\n{master_out}")
        check("MASTER's real cmd_check prints 'ok' (aggregate-only comparison)",
              "ok:" in master_out and "REGRESSION" not in master_out, master_out)

    real = (runner._load_snapshot, runner.load_agent, runner.load_exam,
           runner.run_exam, runner.ollama_version, runner.ollama_unload)
    try:
        runner._load_snapshot = lambda name: snap
        runner.load_agent = lambda name: {"name": name}
        runner.load_exam = lambda name: exam
        runner.run_exam = lambda *a, **k: fresh_run
        runner.ollama_version = lambda: "0.33.2"
        runner.ollama_unload = lambda model: None
        args = argparse.Namespace(agent="fixture-agent", dedupe_tools=False,
                                  tolerance=0.0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pr_rc = cmd_check(args)
        pr_out = buf.getvalue()
    finally:
        (runner._load_snapshot, runner.load_agent, runner.load_exam, runner.run_exam,
         runner.ollama_version, runner.ollama_unload) = real

    check("THIS PR's real cmd_check returns 1 (DRIFT) on the SAME fixture",
          pr_rc == 1, f"rc={pr_rc}\n{pr_out}")
    check("THIS PR's cmd_check prints DRIFT for both flipped cases",
          "DRIFT" in pr_out and "case-a" in pr_out and "case-b" in pr_out, pr_out)
    if have_pre_fix:
        check("THE POINT: master is RED-blind to this defect, the PR catches it — "
              "same fixture, same real entry point, opposite verdict",
              master_rc == 0 and pr_rc == 1)


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
