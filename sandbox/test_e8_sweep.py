#!/usr/bin/env python3
"""Deterministic tests for e8_sweep.py — no live model calls.

    python3 sandbox/test_e8_sweep.py

e8_sweep is a read-only driver over runner.run_exam; these tests monkeypatch
load_agent / load_exam / run_exam / save_result with canned fakes and assert
the driver logic only:

  is_flaky        pass_rate strictly between 0 and 1 is flaky; 0.0, 1.0, and
                   None (unmeasured, samples=1) are not.
  run_step0       applies the samples override to an IN-MEMORY exam copy
                   (never mutates what load_exam returned) and surfaces
                   flaky case ids from a canned multi-case result.
  run_sweep       calls run_exam exactly once per model in the given list,
                   in order, and saves every result (never touches
                   cases.json/snapshot.json — save_result is the only writer
                   called, and it is monkeypatched to a no-op recorder here).

Plain asserts + exit code, same bar as the runner itself and the sibling
sandbox/test_observability.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e8_sweep  # noqa: E402

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def _case(case_id: str, pass_rate) -> dict:
    detail = {} if pass_rate is None else {"pass_rate": pass_rate}
    return {"id": case_id, "split": "train", "passed": pass_rate != 0.0,
            "detail": detail}


def test_is_flaky():
    check("is_flaky: pass_rate 0.5 -> flaky", e8_sweep.is_flaky(_case("a", 0.5)))
    check("is_flaky: pass_rate 0.2 -> flaky", e8_sweep.is_flaky(_case("b", 0.2)))
    check("is_flaky: pass_rate 0.0 -> not flaky", not e8_sweep.is_flaky(_case("c", 0.0)))
    check("is_flaky: pass_rate 1.0 -> not flaky", not e8_sweep.is_flaky(_case("d", 1.0)))
    check("is_flaky: no pass_rate (samples=1) -> not flaky",
          not e8_sweep.is_flaky(_case("e", None)))


def test_run_step0_flags_flaky_cases_and_never_touches_cases_json():
    """Canned exam has 3 cases at pass_rate 0.0 / 0.5 / 1.0 — only the middle
    one is flaky. The samples override must land on an in-memory COPY of
    load_exam's return value: mutating the exam passed into run_exam must
    never be visible on the object load_exam handed back."""
    original_exam = {"cases": [{"id": "x"}], "samples": 1, "mode": "labels"}
    seen_exam_args = []

    def fake_load_agent(name):
        return {"name": name, "provider": "ollama", "model": "champion-model"}

    def fake_load_exam(name):
        return original_exam

    def fake_run_exam(agent, exam, provider, model):
        seen_exam_args.append(exam)
        return {
            "agent": agent["name"], "provider": provider, "model": model,
            "mode": "labels",
            "train": {"passed": 2, "total": 3}, "heldout": {"passed": 0, "total": 0},
            "cases": [_case("case-fail", 0.0), _case("case-flaky", 0.5),
                      _case("case-pass", 1.0)],
        }

    orig = (e8_sweep.load_agent, e8_sweep.load_exam, e8_sweep.run_exam)
    e8_sweep.load_agent, e8_sweep.load_exam, e8_sweep.run_exam = (
        fake_load_agent, fake_load_exam, fake_run_exam)
    try:
        # Non-default inputs on purpose: DEFAULT_SAMPLES=5 / DEFAULT_SAMPLE_TEMPERATURE=0.7,
        # so passing 5/0.7 would let an impl that silently drops the args and falls back to
        # the module defaults pass anyway (a tautology). 3/0.55 differ from the defaults, so
        # the override assertions below fail unless run_step0 actually forwards its args.
        out = e8_sweep.run_step0("crm-followup", samples=3, sample_temperature=0.55)
    finally:
        e8_sweep.load_agent, e8_sweep.load_exam, e8_sweep.run_exam = orig

    check("run_step0: exactly the flaky case is flagged",
          out["flaky_ids"] == ["case-flaky"], str(out["flaky_ids"]))
    check("run_step0: samples override reached run_exam (not the module default)",
          seen_exam_args and seen_exam_args[0]["samples"] == 3)
    check("run_step0: sample_temperature override reached run_exam (not the module default)",
          seen_exam_args and seen_exam_args[0]["sample_temperature"] == 0.55)
    check("run_step0: original exam dict from load_exam is untouched",
          original_exam == {"cases": [{"id": "x"}], "samples": 1, "mode": "labels"},
          str(original_exam))


def test_run_sweep_calls_run_exam_once_per_model_and_saves_every_result():
    models = ["model-a", "model-b", "model-c"]
    calls = []
    saved = []

    def fake_load_agent(name):
        return {"name": name, "provider": "ollama", "model": "champion-model"}

    def fake_load_exam(name):
        return {"cases": [], "mode": "labels"}

    def fake_run_exam(agent, exam, provider, model):
        calls.append(model)
        return {"agent": agent["name"], "provider": provider, "model": model,
                "train": {"passed": 1, "total": 1}, "heldout": {"passed": 1, "total": 1},
                "cases": []}

    def fake_save_result(result):
        saved.append(result["model"])
        return Path("/dev/null")

    orig = (e8_sweep.load_agent, e8_sweep.load_exam, e8_sweep.run_exam,
            e8_sweep.save_result)
    e8_sweep.load_agent, e8_sweep.load_exam, e8_sweep.run_exam, e8_sweep.save_result = (
        fake_load_agent, fake_load_exam, fake_run_exam, fake_save_result)
    try:
        results = e8_sweep.run_sweep("crm-followup", models)
    finally:
        (e8_sweep.load_agent, e8_sweep.load_exam, e8_sweep.run_exam,
         e8_sweep.save_result) = orig

    check("run_sweep: run_exam called once per model, in order",
          calls == models, str(calls))
    check("run_sweep: every model's result was saved",
          saved == models, str(saved))
    check("run_sweep: returns a result keyed by every model",
          set(results.keys()) == set(models), str(results.keys()))


def test_root_is_relative_to_file_not_hardcoded():
    """(5) ROOT must be derived from __file__, matching runner.py's own
    computation — not a hardcoded absolute path baked in for one machine."""
    check("ROOT == two levels up from e8_sweep.py (matches runner.py's ROOT)",
          e8_sweep.ROOT == Path(e8_sweep.__file__).resolve().parent.parent)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)} test groups; {len(FAILED)} failed assertion(s)"
          + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
