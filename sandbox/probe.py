#!/usr/bin/env python3
"""E7 bullet 2: reliability as a first-class RECORDED number — `runner.py probe`.

    python3 sandbox/runner.py probe <agent> [--models m1,m2] [--temperature 0,0.7]
                                            [-k 5] [--provider ollama]
    python3 sandbox/probe.py       <agent> [same flags]

Every score this repo reports is a point estimate with no error bar, while local
models are known to flake ~1-in-2/3 when sampled (verified 2026-07-18). This
command runs each case k times per (model, temperature) cell and RECORDS the
per-case pass_rate, so "10/11" can be told apart from "right on 7 and lucky on 3".

Contract (each line is a constraint the tests in test_probe.py pin):

* **NOT a gate, structurally.** pass@k is barred from gates (CLAUDE.md golden
  principles). Probe output can never be mistaken for, or promoted into, a gate
  score:
    - it never writes any `snapshot.json` (this module does not even name that
      file), and `check` / `check-all` / `diff` never read probe output;
    - probe records are written ONLY under `results/probe/`, with a `probe__`
      filename prefix and a `"kind": "reliability-probe"` shape discriminator,
      and deliberately carry NO train/heldout score keys — a gate-results reader
      pointed at one fails loud instead of misreading it;
    - `taxonomy` / `route` glob only top-level `results/*.json`
      (taxonomy.find_result_files), so the corpus readers never see probe files.
* **cases.json is never written.** The samples/temperature override is applied to
  an IN-MEMORY copy of the exam dict only — the same mechanism e8_sweep.run_step0
  uses (`{**load_exam(name), "samples": k, "sample_temperature": t}`).
* **Temperature is a MEASURED VARIABLE, not a constant.** `--temperature` takes
  one or more values, so the same cases can be probed across a range and the
  degradation curve recorded. The default 0.7 is a convention, not a measurement.
* **Fail loud.** A probe run that cannot compute a pass_rate raises — it never
  defaults to 1.0 (or anything else). k < 2 is refused (k=1 records no
  pass_rate, so it would be a gate run wearing a probe's name).
* **results/ is disposable and box-local** (CLAUDE.md) — probe records feed no
  committed state. The report header says so.

What the number MEANS (printed with every run, because a reader will otherwise
assume the more flattering claim):

* At temperature 0 with k > 1 this is a DETERMINISM CONTROL: the gate assumes
  temp-0/samples=1 reproduces; any fractional pass_rate here falsifies that.
* At temperature > 0 it measures how ROBUSTLY a capability is held (right for a
  reason vs narrowly right). It is NOT deployment variance — the gate and live
  runs execute at temp 0.
* A high pass_rate means CONSISTENT, not CORRECT. k-sampling catches
  disagreement-with-yourself (variance), never agreement-on-the-wrong-thing
  (bias) — sampling does not fix hallucination (CLAUDE.md).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
PROBE_DIR = RESULTS_DIR / "probe"

DEFAULT_K = 5
DEFAULT_TEMPERATURES = "0.7"  # a convention, not a measurement — see module doc
# Rough per-case-run wall-clock for the up-front estimate. One case-run is one
# scored pass over one case (a trajectory case makes several model calls inside
# it, so those exams run 3-5x slower than this constant suggests). The printed
# estimate says it is rough; the CALL COUNT next to it is exact.
EST_SEC_PER_CASE_RUN = 8.0

KIND = "reliability-probe"


# ------------------------------------------------------------ pure helpers

def parse_temperatures(csv: str) -> list[float]:
    """CSV of temperatures -> list of floats. Fails loud on empty, non-numeric,
    negative, or duplicate values (a silent duplicate would double the compute
    and overwrite its own record)."""
    parts = [p.strip() for p in csv.split(",")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"--temperature must be a non-empty CSV of numbers, "
                         f"got {csv!r}")
    try:
        temps = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError(f"--temperature has a non-numeric entry: {csv!r}") from exc
    if any(t < 0 for t in temps):
        raise ValueError(f"--temperature values must be >= 0, got {csv!r}")
    if len(set(temps)) != len(temps):
        raise ValueError(f"--temperature has duplicate values: {csv!r}")
    return temps


def validate_k(k: int) -> int:
    """k must be >= 2: at k=1 run_exam records no pass_rate at all, so the
    'probe' would silently be an ordinary gate-shaped run."""
    if k < 2:
        raise ValueError(f"-k must be >= 2 for a reliability probe (k=1 records "
                         f"no pass_rate), got {k}")
    return k


def estimate_case_runs(n_cases: int, k: int, n_temps: int, n_models: int) -> int:
    """Exact number of scored case-runs the requested grid will execute."""
    return n_cases * k * n_temps * n_models


def estimate_lines(n_cases: int, k: int, n_temps: int, n_models: int) -> list[str]:
    runs = estimate_case_runs(n_cases, k, n_temps, n_models)
    minutes = runs * EST_SEC_PER_CASE_RUN / 60
    return [
        f"runtime estimate: {n_cases} cases x k={k} x {n_temps} temperature(s) "
        f"x {n_models} model(s) = {runs} case-runs (exact)",
        f"  at ~{EST_SEC_PER_CASE_RUN:.0f}s per case-run ~= {minutes:.0f} min "
        f"(rough; trajectory exams make several model calls per case-run and "
        f"can take 3-5x longer)",
    ]


def extract_reliability(result: dict, k: int, temperature: float) -> dict:
    """Reduce one run_exam result (samples=k) to a probe record.

    Fails loud: a case with no recorded pass_rate raises — it is never
    defaulted. (run_exam omits pass_rate when a case raised before sampling
    completed, and at samples=1; both mean this run measured nothing for that
    case and the record must not pretend otherwise.)

    The record deliberately carries NO train/heldout score block and no
    per-case passed verdicts — those are gate vocabulary, and their absence is
    what makes a probe file structurally unreadable as a gate result.
    """
    cases = []
    for c in result["cases"]:
        pr = (c.get("detail") or {}).get("pass_rate")
        if pr is None:
            raise ValueError(
                f"probe could not compute pass_rate for case {c['id']!r} "
                f"(model {result['model']}): the case never completed k samples "
                f"({(c.get('got') or {}).get('error', 'no error recorded')}). "
                f"Refusing to record a default.")
        cases.append({"id": c["id"], "split": c["split"], "pass_rate": pr,
                      "flaky": 0 < pr < 1})
    flaky = [c["id"] for c in cases if c["flaky"]]
    record = {
        "kind": KIND,
        "not_a_gate": ("pass@k reliability probe — never comparable to a "
                       "committed score, never a check/check-all input"),
        "agent": result["agent"],
        "provider": result["provider"],
        "model": result["model"],
        "temperature": temperature,
        "k": k,
        "date": datetime.now().isoformat(timespec="seconds"),
        "n_cases": len(cases),
        "flaky_count": len(flaky),
        "flaky_ids": flaky,
        # TEMPERATURE-NEUTRAL by name, deliberately. This says only "every
        # pass_rate is 0.0 or 1.0" — which at temp>0 means the model was
        # CONSISTENT, and says nothing about the gate. Naming it `deterministic`
        # (as the first draft did) mislabels a temp-0.7 record that happens to
        # come out binary: a later consumer reading the JSON would take it as
        # the gate's temp-0 assumption holding, which temp>0 never tests.
        # Caught by the correctness refuter on PR #26.
        "all_pass_rates_binary": all(c["pass_rate"] in (0.0, 1.0) for c in cases),
        "cases": cases,
    }
    # The gate claim is emitted ONLY where it is meaningful — at temperature 0.
    # Absent at temp>0 rather than False, so its absence cannot be misread as a
    # failed control.
    if temperature == 0:
        record["gate_assumption_held"] = record["all_pass_rates_binary"]
    return record


def probe_filename(record: dict) -> str:
    """probe__<agent>__<provider>__<model>__t<temp>__k<k>.json — the probe__
    prefix and the results/probe/ directory are BOTH load-bearing: no gate
    result file has either."""
    safe_model = record["model"].replace("/", "_").replace(":", "_")
    safe_provider = record["provider"].replace("/", "_").replace(":", "_")
    return (f"probe__{record['agent']}__{safe_provider}__{safe_model}"
            f"__t{record['temperature']:g}__k{record['k']}.json")


def save_probe(record: dict) -> Path:
    if record.get("kind") != KIND:
        raise ValueError(f"refusing to save a non-probe record (kind="
                         f"{record.get('kind')!r}) into {PROBE_DIR}")
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    path = PROBE_DIR / probe_filename(record)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return path


# ------------------------------------------------------------ execution

def run_probe_cell(agent_name: str, model: str, temperature: float, k: int,
                   provider: str | None = None) -> dict:
    """One (model, temperature) cell: run the whole exam at samples=k with the
    override applied to an IN-MEMORY copy of the exam dict only (e8_sweep's
    mechanism — cases.json is never written), then reduce to a probe record.

    Imports from runner are deferred to call time: runner imports this module
    at load time to hang the `probe` subcommand off its CLI (same cycle-breaking
    pattern as taxonomy.trajectory_prefixes)."""
    from runner import load_agent, load_exam, run_exam
    agent = load_agent(agent_name)
    exam = {**load_exam(agent_name), "samples": k, "sample_temperature": temperature}
    provider = provider or agent["provider"]
    result = run_exam(agent, exam, provider, model)
    return extract_reliability(result, k, temperature)


def _cell_lines(record: dict) -> list[str]:
    out = [f"\n--- probe {record['agent']} | {record['model']} | "
           f"temp={record['temperature']:g} | k={record['k']} ---"]
    for c in record["cases"]:
        mark = "  <-- FLAKY" if c["flaky"] else ""
        out.append(f"  {c['id']:34} {c['split']:8} pass_rate={c['pass_rate']}{mark}")
    out.append(f"  => {record['flaky_count']} flaky case(s) of {record['n_cases']}")
    if record["temperature"] == 0:
        if record["gate_assumption_held"]:
            out.append(
                "  temp-0 control: every pass_rate is exactly 0.0 or 1.0 — the "
                "gate's temp-0 reproducibility assumption HELD for this "
                "exam/model at k={k}.".format(k=record["k"]))
        else:
            frac = [c for c in record["cases"] if c["flaky"]]
            out.append(
                f"  *** MAJOR FINDING: FRACTIONAL pass_rate AT TEMPERATURE 0 on "
                f"{[c['id'] for c in frac]} — temp 0 did NOT reproduce. The "
                f"deterministic gate's foundational assumption is FALSIFIED for "
                f"this exam/model: its green results have been partly luck. "
                f"Do not retry until it looks clean — report this.")
    return out


HONESTY_LINES = [
    "what this number means:",
    "  * temp 0 (k>1): a DETERMINISM CONTROL — the gate assumes temp-0/samples=1",
    "    reproduces; any fractional pass_rate here falsifies that assumption.",
    "  * temp > 0: how ROBUSTLY the capability is held (right for a reason vs",
    "    narrowly right). NOT deployment variance — the gate and live runs use temp 0.",
    "  * a high pass_rate means CONSISTENT, not CORRECT: k-sampling catches",
    "    disagreement-with-yourself (variance), never agreement-on-the-wrong-thing",
    "    (bias). Sampling does not fix hallucination.",
]


def run(args) -> int:
    temps = parse_temperatures(args.temperature)
    k = validate_k(args.k)
    from runner import load_agent, load_exam
    agent = load_agent(args.agent)
    models = ([m.strip() for m in args.models.split(",") if m.strip()]
              if args.models else [agent["model"]])
    if not models:
        raise ValueError(f"--models parsed to an empty list: {args.models!r}")
    # Mirrors parse_temperatures: a silent duplicate doubles the compute and
    # then overwrites its own record, so the second run is invisible.
    if len(set(models)) != len(models):
        raise ValueError(f"--models has duplicate entries: {args.models!r}")
    n_cases = len(load_exam(args.agent)["cases"])

    print("RELIABILITY PROBE (E7) — pass@k per case, per (model, temperature). "
          "NOT a gate:")
    print("barred from check/check-all, never promoted into a committed score. "
          "Records go to results/probe/")
    print("which is box-local and disposable (results/ is gitignored).")
    print(f"exam: {args.agent}  models: {', '.join(models)}  "
          f"temps: {', '.join(f'{t:g}' for t in temps)}  k={k}")
    for line in estimate_lines(n_cases, k, len(temps), len(models)):
        print(line)
    for line in HONESTY_LINES:
        print(line)

    t0 = time.time()
    for model in models:
        for temp in temps:
            record = run_probe_cell(args.agent, model, temp, k,
                                    provider=args.provider)
            path = save_probe(record)
            print("\n".join(_cell_lines(record)), flush=True)
            print(f"  -> {path.relative_to(ROOT)}", flush=True)
    print(f"\nprobe wall-clock: {(time.time() - t0) / 60:.1f} min", flush=True)
    return 0


def add_arguments(sp) -> None:
    sp.add_argument("agent")
    sp.add_argument("--models",
                    help="CSV of models to probe (default: the agent's champion)")
    sp.add_argument("--temperature", default=DEFAULT_TEMPERATURES,
                    help="CSV of one or more temperatures (default "
                         f"{DEFAULT_TEMPERATURES} — a convention, not a "
                         "measurement; 0 is the gate-determinism control)")
    sp.add_argument("-k", type=int, default=DEFAULT_K,
                    help=f"samples per case (default {DEFAULT_K}; must be >= 2)")
    sp.add_argument("--provider",
                    help="provider override (default: the agent's champion provider)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(p)
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
