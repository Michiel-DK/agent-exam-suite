"""`runner.py run <agent> --split {all,train,heldout}` — run one split only (2026-09-23).

Why: the pages report held-out scores only and 47 of 114 committed cases are train; a hosted pass on a
frontier model spends ~40% of its budget on cases nobody reports. The filter must (1) leave the default
byte-identical to today (every case runs when the flag is absent or `all`), (2) run exactly the named
split, (3) be REFUSED on `--snapshot`: the committed snapshot is the whole case set and `check` refuses
on a changed set, so a scoped snapshot would silently redefine the gate. Driven through the real CLI
surface (argparse -> main -> cmd_run -> run_exam) with the model faked at the adapter boundary and the
results write captured, the same shape as sandbox/test_dedupe_tools.py::_cli_run.
Seen RED before the change: on master `--split` is an unknown argument, argparse exits 2, every check fails.
"""
from __future__ import annotations
import contextlib, io, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402
from runner import ROOT  # noqa: E402
from router import StubAdapter  # noqa: E402

FAILED = []
AGENT = "email-triage"

def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond: FAILED.append(name)

class _CountingStub(StubAdapter):
    """StubAdapter that counts generate() calls, so "refused before any inference" is an assertion, not a hope."""
    calls = 0
    def generate(self, *a, **k):
        _CountingStub.calls += 1
        return super().generate(*a, **k)

def _cli_run(argv: list[str]):
    """Returns (rc, captured_result_or_None, stderr_text). SystemExit is caught so a refusal is a datum."""
    captured: dict = {}; err = io.StringIO()
    real_adapter_for, real_save, real_argv = runner.adapter_for, runner.save_result, sys.argv
    _CountingStub.calls = 0
    try:
        runner.adapter_for = lambda *a, **k: _CountingStub()
        runner.save_result = lambda result, **kw: (captured.update(result), ROOT / "results" / "suppressed.json")[1]
        sys.argv = argv
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try: rc = runner.main()
            except SystemExit as e: rc = e.code if isinstance(e.code, int) else 1; err.write(str(e.code))
    finally:
        runner.adapter_for, runner.save_result, sys.argv = real_adapter_for, real_save, real_argv
    return rc, (captured or None), err.getvalue()

def _committed_split_counts() -> dict:
    exam = runner.load_exam(AGENT)
    out = {"train": 0, "heldout": 0}
    for c in exam["cases"]: out[c.get("split", "train")] += 1
    return out

def test_default_runs_every_case():
    n = _committed_split_counts()
    rc, res, _ = _cli_run(["runner.py", "run", AGENT, "--provider", "stub"])
    check("no flag: rc 0", rc == 0, str(rc))
    check("no flag: every committed case ran", res is not None and len(res["cases"]) == n["train"] + n["heldout"],
          f"{len(res['cases']) if res else None} vs {n}")
    rc2, res2, _ = _cli_run(["runner.py", "run", AGENT, "--provider", "stub", "--split", "all"])
    check("--split all: identical case list to no flag", res2 is not None and res is not None and
          [c["id"] for c in res2["cases"]] == [c["id"] for c in res["cases"]])

def test_heldout_only():
    n = _committed_split_counts()
    rc, res, _ = _cli_run(["runner.py", "run", AGENT, "--provider", "stub", "--split", "heldout"])
    check("--split heldout: rc 0", rc == 0, str(rc))
    check("--split heldout: only heldout cases ran", res is not None and res["cases"] and
          all(c["split"] == "heldout" for c in res["cases"]) and len(res["cases"]) == n["heldout"],
          f"{[c['split'] for c in res['cases']] if res else None}")
    check("--split heldout: train total is 0", res is not None and res["train"]["total"] == 0, str(res and res["train"]))

def test_train_only():
    n = _committed_split_counts()
    rc, res, _ = _cli_run(["runner.py", "run", AGENT, "--provider", "stub", "--split", "train"])
    check("--split train: only train cases ran", rc == 0 and res is not None and
          all(c["split"] == "train" for c in res["cases"]) and len(res["cases"]) == n["train"])

def test_snapshot_refuses_a_split():
    snap = ROOT / "evals" / AGENT / "snapshot.json"; before = snap.read_bytes()
    rc, res, err = _cli_run(["runner.py", "run", AGENT, "--provider", "stub", "--split", "heldout", "--snapshot"])
    check("--snapshot --split heldout: committed snapshot byte-identical after the call", snap.read_bytes() == before)
    check("--snapshot --split heldout: refused (rc != 0)", rc != 0, str(rc))
    check("--snapshot --split heldout: nothing written", res is None)
    # Must match the GUARD's message, not argparse's: on master `--split` is unknown, argparse also exits
    # non-zero and also mentions "split", so a looser check was green on master (seen 23 Sep, fixed here).
    check("--snapshot --split heldout: refused by the guard, not by argparse",
          "requires --split all" in err, err[:120])
    check("--snapshot --split heldout: the model was never called", _CountingStub.calls == 0, str(_CountingStub.calls))

def test_partial_run_cannot_pose_as_a_full_one():
    """Refuter finding (23 Sep): a partial run written to results/<agent>__<provider>__<model>.json would be adopted
    by taxonomy.py / policy.py (they glob results/*.json at the top level) as the canonical row. Through the REAL
    save_result, redirected to a temp results dir: a split run lands in a subdir with a suffix and a "split" key;
    the top-level file is never touched; the default run still writes the top-level file with no "split" key."""
    import json, shutil, uuid
    # A results dir UNDER the repo root (cmd_run prints path.relative_to(ROOT)); removed at the end.
    tmp = ROOT / "results" / f"_test_split_{uuid.uuid4().hex[:8]}"; real_dir, real_adapter_for, real_argv = runner.RESULTS_DIR, runner.adapter_for, sys.argv
    try:
        runner.RESULTS_DIR = tmp; runner.adapter_for = lambda *a, **k: StubAdapter()
        for argv in (["runner.py", "run", AGENT, "--provider", "stub", "--split", "heldout"], ["runner.py", "run", AGENT, "--provider", "stub"]):
            sys.argv = argv
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try: runner.main()
                except SystemExit: pass   # on master argparse rejects --split; the checks below then go red
        top = sorted(p.name for p in tmp.glob("*.json")); sub = sorted(p.name for p in (tmp / "split").glob("*.json"))
        part = json.loads((tmp / "split" / sub[0]).read_text()) if sub else {}; full = json.loads((tmp / top[0]).read_text()) if top else {}
    finally:
        runner.RESULTS_DIR, runner.adapter_for, sys.argv = real_dir, real_adapter_for, real_argv
        shutil.rmtree(tmp, ignore_errors=True)
    check("partial run: no file at the top level of results/ (taxonomy/policy glob there)", len(top) == 1 and "split" not in top[0], str(top))
    check("partial run: written under results/split/ with a split suffix", len(sub) == 1 and sub[0].endswith("__split-heldout.json"), str(sub))
    check("partial run: JSON carries split=heldout", part.get("split") == "heldout", str(part.get("split")))
    check("full run: JSON carries no split key (byte-shape unchanged)", "split" not in full)
    check("full run: every committed case present", len(full.get("cases", [])) == sum(_committed_split_counts().values()))

def test_empty_split_fails_loud():
    """Regression refuter (23 Sep): every committed exam has both splits, so this is latent — but an exam whose
    cases are all train would make `--split heldout` a 0/0 run with score None, written as if it were data. The
    repo's convention is fail loud, never a vacuous score. Fakes such an exam at load_exam and expects a refusal."""
    real_load, real_adapter_for, real_save, real_argv = runner.load_exam, runner.adapter_for, runner.save_result, sys.argv
    written = {}; err = io.StringIO()
    try:
        full = real_load(AGENT)
        runner.load_exam = lambda name: {**full, "cases": [c for c in full["cases"] if c.get("split", "train") == "train"]}
        runner.adapter_for = lambda *a, **k: StubAdapter()
        runner.save_result = lambda result, **kw: (written.update(result), ROOT / "results" / "suppressed.json")[1]
        sys.argv = ["runner.py", "run", AGENT, "--provider", "stub", "--split", "heldout"]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try: rc = runner.main()
            except SystemExit as e: rc = e.code if isinstance(e.code, int) else 1; err.write(str(e.code))
    finally:
        runner.load_exam, runner.adapter_for, runner.save_result, sys.argv = real_load, real_adapter_for, real_save, real_argv
    check("empty split: refused (rc != 0)", rc != 0, str(rc))
    check("empty split: nothing written", not written)
    msg = err.getvalue()
    check("empty split: the refusal names the empty split", "no cases" in msg.lower() and "heldout" in msg, msg[:120])

def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        print(f"\n{t.__name__}")
        try: t()
        except Exception as e:   # a crashing test must count as a failure, never hide the tests sorted after it
            FAILED.append(f"{t.__name__} crashed: {type(e).__name__}: {e}"); print(f"  [FAIL] {t.__name__} crashed: {e}")
    print(f"\n{len(tests)} test groups; {len(FAILED)} failed assertion(s)" + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0

if __name__ == "__main__":
    sys.exit(main())
