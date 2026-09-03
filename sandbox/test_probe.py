#!/usr/bin/env python3
"""Deterministic tests for probe.py (S-E7B) — no live model calls.

    python3 sandbox/test_probe.py

The four structural gate-separation bars each get their own test group:

  BAR (a)  probe results are never writable to any snapshot.json, and
           check / check-all / cmd_diff's ranking never read probe output.
  BAR (b)  probe records are distinguishable from gate result files by
           SHAPE (kind discriminator, no train/heldout keys) AND FILENAME
           (probe__ prefix, results/probe/ directory).
  BAR (c)  cmd_check_all contains no reference to probe.
  BAR (d)  cases.json is never written — the samples/temperature override
           lands on an in-memory copy of the exam dict only.

Plus: fail-loud on a missing pass_rate (never defaults), k>=2 enforcement,
temperature parsing (one or more values), estimate math, deterministic flag.

Plain asserts + exit code, same bar as sibling sandbox/test_e8_sweep.py.
"""
from __future__ import annotations

import argparse
import inspect
import io
import json
import shutil
import sys
import tempfile
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe  # noqa: E402
import runner  # noqa: E402
import taxonomy  # noqa: E402

FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def _code_text(module) -> str:
    """Module source with comments and standalone string statements (docstrings)
    stripped — the static bars must scan CODE, not documentation prose (the
    module doc legitimately EXPLAINS that it never touches snapshot files)."""
    src = inspect.getsource(module)
    kept = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING:
            stripped = tok.line.lstrip()
            if (tok.start[1] == len(tok.line) - len(stripped)
                    and stripped[:1] in "\"'rRfF"):
                continue  # string statement at line start: docstring-shaped
        kept.append(tok.string)
    return " ".join(kept)


def _canned_result(pass_rates, model="m-test", agent="crm-followup") -> dict:
    return {
        "agent": agent, "provider": "ollama", "model": model, "mode": "labels",
        "train": {"passed": 0, "total": len(pass_rates)},
        "heldout": {"passed": 0, "total": 0},
        "cases": [{"id": f"case-{i}", "split": "train", "passed": pr == 1.0,
                   "detail": {"pass_rate": pr, "samples": 5}}
                  for i, pr in enumerate(pass_rates)],
    }


def _fakes(seen_exams: list, original_exam: dict, pass_rates=(0.0, 0.5, 1.0)):
    def fake_load_agent(name):
        return {"name": name, "provider": "ollama", "model": "champion-model"}

    def fake_load_exam(name):
        return original_exam

    def fake_run_exam(agent, exam, provider, model):
        seen_exams.append(exam)
        return _canned_result(list(pass_rates), model=model, agent=agent["name"])

    return fake_load_agent, fake_load_exam, fake_run_exam


def _patched(fake_load_agent, fake_load_exam, fake_run_exam):
    """Patch the runner module attrs probe imports AT CALL TIME."""
    orig = (runner.load_agent, runner.load_exam, runner.run_exam)
    runner.load_agent = fake_load_agent
    runner.load_exam = fake_load_exam
    runner.run_exam = fake_run_exam
    return orig


def _unpatch(orig):
    runner.load_agent, runner.load_exam, runner.run_exam = orig


# ---------------------------------------------------------------- BAR (a)

def test_bar_a_probe_never_touches_snapshots_and_gates_never_read_probe():
    # Static half: no CODE in the probe module (comments/docstrings stripped)
    # names snapshot files, so there is no code path that could write one.
    check("bar(a): probe.py code never references 'snapshot'",
          "snapshot" not in _code_text(probe))
    # The gate commands and diff's ranking never reference probe.
    for fn in (runner.cmd_check, runner.cmd_check_all, runner.cmd_diff,
               runner.diff_recommendation, runner._acc_key, runner.cmd_run):
        check(f"bar(a): runner.{fn.__name__} source never references 'probe'",
              "probe" not in inspect.getsource(fn))

    # Functional half: a full probe.run() pass writes files ONLY under
    # results/probe/, and no file named snapshot.json appears anywhere.
    tmp = Path(tempfile.mkdtemp(prefix="probe_test_"))
    seen, original_exam = [], {"cases": [{"id": "x"}], "mode": "labels"}
    orig = _patched(*_fakes(seen, original_exam))
    orig_dirs = (probe.ROOT, probe.RESULTS_DIR, probe.PROBE_DIR)
    probe.ROOT, probe.RESULTS_DIR = tmp, tmp / "results"
    probe.PROBE_DIR = tmp / "results" / "probe"
    try:
        args = argparse.Namespace(agent="crm-followup", models="m1,m2",
                                  temperature="0,0.7", k=5, provider=None)
        rc = probe.run(args)
    finally:
        _unpatch(orig)
        probe.ROOT, probe.RESULTS_DIR, probe.PROBE_DIR = orig_dirs
    written = sorted(p for p in tmp.rglob("*") if p.is_file())
    check("bar(a): probe.run returned 0", rc == 0)
    check("bar(a): no snapshot.json written anywhere",
          not any(p.name == "snapshot.json" for p in written))
    check("bar(a): every written file lives under results/probe/",
          written and all(p.parent == tmp / "results" / "probe" for p in written),
          str(written))
    check("bar(a): one record per (model, temperature) cell",
          len(written) == 4, str([p.name for p in written]))
    # The shared corpus reader (taxonomy / route) globs top-level results/*.json
    # only — a probe file in the subdirectory is invisible to it.
    gate_file = tmp / "results" / "crm-followup__ollama__m1.json"
    gate_file.write_text(json.dumps(_canned_result([1.0])))
    found = taxonomy.find_result_files(tmp / "results")
    check("bar(a): taxonomy.find_result_files sees the gate file, not probe files",
          found == [gate_file], str(found))
    shutil.rmtree(tmp)


# ---------------------------------------------------------------- BAR (b)

def test_bar_b_record_shape_and_filename_distinct_from_gate_results():
    record = probe.extract_reliability(_canned_result([0.0, 0.5, 1.0]),
                                       k=5, temperature=0.0)
    check("bar(b): record carries the kind discriminator",
          record["kind"] == "reliability-probe")
    check("bar(b): record carries an explicit not_a_gate notice",
          "not_a_gate" in record)
    check("bar(b): record has NO train key (gate vocabulary)",
          "train" not in record)
    check("bar(b): record has NO heldout key (gate vocabulary)",
          "heldout" not in record)
    check("bar(b): no per-case 'passed' verdicts (gate vocabulary)",
          all("passed" not in c for c in record["cases"]))
    name = probe.probe_filename(record)
    check("bar(b): filename starts with probe__", name.startswith("probe__"))
    check("bar(b): filename encodes temperature and k",
          "__t0__k5.json" in name, name)
    # A gate result filename (runner.save_result) is <agent>__<provider>__<model>
    # with no probe__ prefix; no agent directory named 'probe' exists to collide.
    check("bar(b): no agent named 'probe' can blur the filename prefix",
          not (probe.ROOT / "agents" / "probe").exists())
    # save_probe refuses to write anything that is not a probe record.
    try:
        probe.save_probe({"kind": "gate-result-lookalike"})
        refused = False
    except ValueError:
        refused = True
    check("bar(b): save_probe refuses a non-probe record", refused)


# ---------------------------------------------------------------- BAR (c)

def test_bar_c_check_all_contains_no_reference_to_probe():
    check("bar(c): cmd_check_all source never references 'probe'",
          "probe" not in inspect.getsource(runner.cmd_check_all))
    check("bar(c): cmd_run_all source never references 'probe'",
          "probe" not in inspect.getsource(runner.cmd_run_all))


# ---------------------------------------------------------------- BAR (d)

def test_bar_d_cases_json_never_written_override_is_in_memory():
    check("bar(d): probe.py code never references cases.json",
          "cases.json" not in _code_text(probe))
    seen, original_exam = [], {"cases": [{"id": "x"}], "samples": 1,
                               "mode": "labels"}
    orig = _patched(*_fakes(seen, original_exam))
    try:
        # Non-default k/temperature on purpose (see test_e8_sweep): defaults
        # would let an implementation that drops the args pass anyway.
        probe.run_probe_cell("crm-followup", "m1", temperature=0.35, k=3)
    finally:
        _unpatch(orig)
    check("bar(d): samples override reached run_exam",
          seen and seen[0]["samples"] == 3, str(seen))
    check("bar(d): sample_temperature override reached run_exam",
          seen and seen[0]["sample_temperature"] == 0.35)
    check("bar(d): the dict load_exam returned is byte-identical after the run",
          original_exam == {"cases": [{"id": "x"}], "samples": 1,
                            "mode": "labels"}, str(original_exam))


# ---------------------------------------------------------------- fail loud

def test_fail_loud_missing_pass_rate_raises_never_defaults():
    result = _canned_result([1.0, 1.0])
    del result["cases"][1]["detail"]["pass_rate"]  # a case that never sampled
    try:
        probe.extract_reliability(result, k=5, temperature=0.7)
        raised = False
    except ValueError:
        raised = True
    check("fail-loud: missing pass_rate raises ValueError", raised)

    result2 = _canned_result([1.0])
    result2["cases"][0].pop("detail")
    try:
        probe.extract_reliability(result2, k=5, temperature=0.7)
        raised2 = False
    except ValueError:
        raised2 = True
    check("fail-loud: missing detail block raises ValueError", raised2)


def test_k_validation():
    try:
        probe.validate_k(1)
        raised = False
    except ValueError:
        raised = True
    check("k=1 is refused (records no pass_rate — a gate run in disguise)", raised)
    check("k=2 is accepted", probe.validate_k(2) == 2)


def test_temperature_parsing_one_or_more_values():
    check("single temperature parses", probe.parse_temperatures("0") == [0.0])
    check("multiple temperatures parse (the degradation-curve path)",
          probe.parse_temperatures("0,0.4,0.7,1.0") == [0.0, 0.4, 0.7, 1.0])
    for bad, why in (("", "empty"), ("0.7,", "trailing comma"),
                     ("abc", "non-numeric"), ("-0.5", "negative"),
                     ("0.7,0.7", "duplicate")):
        try:
            probe.parse_temperatures(bad)
            raised = False
        except ValueError:
            raised = True
        check(f"temperature CSV {bad!r} ({why}) is refused", raised)


def test_estimate_math_and_upfront_lines():
    check("estimate: 63 x 5 x 3 x 2 = 1890 case-runs",
          probe.estimate_case_runs(63, 5, 3, 2) == 1890)
    lines = probe.estimate_lines(63, 5, 3, 2)
    check("estimate lines carry the exact case-run count",
          any("1890" in line for line in lines), str(lines))
    check("estimate lines say the seconds figure is rough",
          any("rough" in line for line in lines))


def test_deterministic_flag_and_flaky_ids():
    det = probe.extract_reliability(_canned_result([0.0, 1.0, 1.0]),
                                    k=5, temperature=0.0)
    check("all pass_rates in {0,1} -> all_pass_rates_binary",
          det["all_pass_rates_binary"])
    check("temp 0 + all binary -> gate_assumption_held True",
          det["gate_assumption_held"])
    check("no flaky ids on a binary record", det["flaky_ids"] == [])
    frac = probe.extract_reliability(_canned_result([0.0, 0.4, 1.0]),
                                     k=5, temperature=0.0)
    check("a fractional pass_rate -> NOT all_pass_rates_binary",
          not frac["all_pass_rates_binary"])
    check("temp 0 + fractional -> gate_assumption_held False",
          frac["gate_assumption_held"] is False)
    check("flaky ids name exactly the fractional case",
          frac["flaky_ids"] == ["case-1"], str(frac["flaky_ids"]))
    warn = "\n".join(probe._cell_lines(frac))
    check("temp-0 fractional record prints the MAJOR FINDING warning",
          "MAJOR FINDING" in warn and "FALSIFIED" in warn)
    held = "\n".join(probe._cell_lines(det))
    check("temp-0 clean record states the assumption HELD", "HELD" in held)


def test_gate_claim_is_absent_above_temperature_zero():
    """The defect the correctness refuter caught on PR #26: the first draft
    emitted a `deterministic` key at ANY temperature, computed only from
    "were all pass_rates binary". A temp-0.7 run that happens to come out
    binary would then persist a record a later consumer reads as "the gate's
    temp-0 assumption held" — which temp>0 never tests. Both directions are
    pinned here, because a fix without a both-directions fixture is the exact
    blind spot that shipped PR #24's inverted cost sentence."""
    hot = probe.extract_reliability(_canned_result([0.0, 1.0, 1.0]),
                                    k=5, temperature=0.7)
    check("temp>0 still reports all_pass_rates_binary (a CONSISTENCY fact)",
          hot["all_pass_rates_binary"] is True)
    check("temp>0 must NOT carry the gate claim at all",
          "gate_assumption_held" not in hot,
          f"found gate_assumption_held={hot.get('gate_assumption_held')!r}")
    check("the mislabelled key name is gone entirely",
          "deterministic" not in hot and "deterministic" not in
          probe.extract_reliability(_canned_result([1.0]), k=5, temperature=0.0))
    cold = probe.extract_reliability(_canned_result([1.0, 1.0]),
                                     k=5, temperature=0.0)
    check("temp==0 DOES carry the gate claim", "gate_assumption_held" in cold)


def test_duplicate_models_are_refused():
    """Mirrors parse_temperatures' duplicate guard: a silent duplicate doubles
    the compute and then overwrites its own record, so the second run is
    invisible."""
    import argparse
    args = argparse.Namespace(agent="expense-categorization", models="m1,m1",
                              temperature="0", k=5, provider=None)
    try:
        probe.run(args)
        check("duplicate --models is refused", False, "no ValueError raised")
    except ValueError as exc:
        check("duplicate --models is refused", "duplicate" in str(exc).lower(),
              str(exc))
    except Exception as exc:  # pragma: no cover - unexpected failure mode
        check("duplicate --models is refused", False,
              f"{type(exc).__name__}: {exc}")


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
