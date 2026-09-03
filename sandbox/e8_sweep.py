#!/usr/bin/env python3
"""E8 sweep driver: Step 0 noise band + untested-model sweep.

The committed `runner.py` CLI has no --samples flag (samples is read from a
cases.json's own "samples" field), so it cannot do either thing E8 needs:

  STEP 0 (noise band)  Run each exam's CURRENT CHAMPION at --samples (default
      5, sample_temperature 0.7) for ONE pass and print each case's pass_rate.
      A case with pass_rate strictly between 0 and 1 is FLAKY — that is the
      exam's own noise, not a model difference. The samples/temperature
      override is applied to an IN-MEMORY COPY of the exam dict only
      (`{**load_exam(name), "samples": N, ...}`) — cases.json is never
      written. This is a read-only characterization pass; nothing here is a
      gate and nothing here is committed.

  SWEEP  Run a list of challenger models across a list of exams at samples=1
      (the committed default) and save each result via runner.save_result.
      results/ is disposable (CLAUDE.md) — this is the never-before-measured
      data E8 exists to capture, not a scored comparison against a champion.

Purely additive plumbing over run_exam: no scoring/gate/snapshot semantics
are touched, and nothing in the repo imports this module (it is a standalone
CLI, not part of the check-all gate path).

Usage:
    python3 sandbox/e8_sweep.py --smoke
        # 1 exam (crm-followup), samples=2, 1 model already pulled locally —
        # quick end-to-end sanity check, no downloads triggered.

    python3 sandbox/e8_sweep.py
        # full run: Step 0 (samples=5) then sweep (the 6-model challenger
        # set) across all 4 exams. Pipe through `tee` for a log:
        #   python3 sandbox/e8_sweep.py 2>&1 | tee e8_$(date +%Y%m%d_%H%M).log

    python3 sandbox/e8_sweep.py --step0-only --exams crm-followup
    python3 sandbox/e8_sweep.py --sweep-only --models phi4-mini,qwen3:4b

OUT OF SCOPE (follow-up, not built here): capturing the resource profile
(on-disk size, tokens/sec, RAM) E8 also wants per model — a later addition,
and promoting any challenger into evals/*/known_models.json is a separate,
reviewed decision (this tool never touches that file).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Mirrors the bootstrap runner.py and judges.py already use to import each
# other from within sandbox/ regardless of the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runner import load_agent, load_exam, run_exam, save_result  # noqa: E402

# ROOT is relative to this file, not hardcoded — sandbox/e8_sweep.py is two
# levels below the repo root, same computation runner.py uses for its ROOT.
ROOT = Path(__file__).resolve().parent.parent

ALL_EXAMS = ["crm-followup", "email-triage", "expense-categorization", "reply-draft"]
DEFAULT_MODELS = [
    "deepseek-r1:8b",     # already downloaded, never run against these exams
    "llama3:8b",          # already downloaded, never run against these exams
    "gemma4:e4b-it-qat",  # e4b sibling of the e2b-it-qat champion, same quant
    "qwen3:4b",           # 256K ctx, 100+ langs, agentic
    "qwen3:8b",           # same family, size-up control
    "phi4-mini",          # 3.8B, function-calling + reasoning
]
# --smoke keeps the sweep phase to one model that is already pulled locally,
# so a sanity run never triggers a multi-GB download or a missing-model
# HTTP error — it proves the driver logic end-to-end, not full model coverage.
SMOKE_MODELS = ["deepseek-r1:8b"]
SMOKE_EXAM = "crm-followup"
SMOKE_SAMPLES = 2

DEFAULT_SAMPLES = 5
DEFAULT_SAMPLE_TEMPERATURE = 0.7


def _hdr(s: str) -> None:
    print(f"\n{'=' * 72}\n{s}\n{'=' * 72}", flush=True)


def is_flaky(case: dict) -> bool:
    """A case is flaky iff its multi-sample pass_rate is strictly between 0
    and 1 — it neither always passed nor always failed at this temperature.
    None (samples=1, no pass_rate recorded) is not flaky; it is unmeasured."""
    pr = (case.get("detail") or {}).get("pass_rate")
    return pr is not None and 0 < pr < 1


def run_step0(exam_name: str, samples: int,
              sample_temperature: float = DEFAULT_SAMPLE_TEMPERATURE) -> dict:
    """Champion @ --samples, ONE pass. Returns the run_exam result dict plus
    the list of flaky case ids. Applies the samples override to an in-memory
    copy of the exam dict ONLY — never writes cases.json."""
    agent = load_agent(exam_name)
    exam = {**load_exam(exam_name), "samples": samples,
            "sample_temperature": sample_temperature}
    provider, model = agent["provider"], agent["model"]
    result = run_exam(agent, exam, provider, model)
    flaky_ids = [c["id"] for c in result["cases"] if is_flaky(c)]
    return {"result": result, "flaky_ids": flaky_ids}


def print_step0(exam_name: str, samples: int,
                 sample_temperature: float = DEFAULT_SAMPLE_TEMPERATURE) -> dict:
    agent = load_agent(exam_name)
    _hdr(f"STEP 0 noise band | {exam_name} | champion={agent['model']} | "
         f"samples={samples}")
    t0 = time.time()
    out = run_step0(exam_name, samples, sample_temperature)
    dt = time.time() - t0
    result = out["result"]
    for c in result["cases"]:
        pr = (c.get("detail") or {}).get("pass_rate")
        mark = "  <-- FLAKY (noise)" if c["id"] in out["flaky_ids"] else ""
        print(f"  {c['id']:30} {c['split']:8} pass_rate={pr}{mark}", flush=True)
    print(f"  => heldout {result['heldout']['passed']}/{result['heldout']['total']}  "
          f"train {result['train']['passed']}/{result['train']['total']}  "
          f"| {len(out['flaky_ids'])} flaky case(s)  | {dt:.0f}s", flush=True)
    return out


def run_sweep(exam_name: str, models: list[str]) -> dict:
    """Run each model in `models` against exam_name at samples=1 (the
    committed default from cases.json — no override here) and save every
    result via runner.save_result. Returns {model: result_dict}."""
    agent = load_agent(exam_name)
    exam = load_exam(exam_name)
    provider = agent["provider"]
    results = {}
    for m in models:
        results[m] = run_exam(agent, exam, provider, m)
        save_result(results[m])
    return results


def print_sweep(exam_name: str, models: list[str]) -> dict:
    """Printing wrapper around run_sweep (the unit-tested primitive) — per
    model, so a slow/hanging model in a long list is visible in the log as
    it happens rather than only in the final summary."""
    agent = load_agent(exam_name)
    _hdr(f"SWEEP challenger models | {exam_name} | champion={agent['model']}")
    results = {}
    for m in models:
        t0 = time.time()
        results.update(run_sweep(exam_name, [m]))
        dt = time.time() - t0
        res = results[m]
        print(f"  {m:22} heldout {res['heldout']['passed']}/{res['heldout']['total']}  "
              f"train {res['train']['passed']}/{res['train']['total']}  ({dt:.0f}s)",
              flush=True)
    return results


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="E8 sweep driver: noise-band Step 0 + untested-model sweep "
                    "(read-only over run_exam; never touches committed config).")
    p.add_argument("--smoke", action="store_true",
                    help="1 exam (crm-followup), samples=2, 1 already-pulled model — "
                        "quick sanity, no downloads triggered.")
    p.add_argument("--samples", type=int, default=None,
                    help=f"Step 0 sample count (default {DEFAULT_SAMPLES}, "
                        f"or {SMOKE_SAMPLES} under --smoke).")
    p.add_argument("--models", type=str, default=None,
                    help="CSV of challenger models for the sweep "
                        f"(default: {','.join(DEFAULT_MODELS)}).")
    p.add_argument("--exams", type=str, default=None,
                    help=f"CSV of exam names (default: {','.join(ALL_EXAMS)}).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--step0-only", action="store_true", help="Run only Step 0.")
    mode.add_argument("--sweep-only", action="store_true", help="Run only the sweep.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    exams = (args.exams.split(",") if args.exams
             else [SMOKE_EXAM] if args.smoke
             else ALL_EXAMS)
    models = (args.models.split(",") if args.models
              else SMOKE_MODELS if args.smoke
              else DEFAULT_MODELS)
    samples = (args.samples if args.samples is not None
               else SMOKE_SAMPLES if args.smoke
               else DEFAULT_SAMPLES)

    run_step0_phase = not args.sweep_only
    run_sweep_phase = not args.step0_only

    t0 = time.time()
    if run_step0_phase:
        for exam_name in exams:
            print_step0(exam_name, samples)
    if run_sweep_phase:
        for exam_name in exams:
            print_sweep(exam_name, models)
    print(f"\nTOTAL wall-clock: {(time.time() - t0) / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
