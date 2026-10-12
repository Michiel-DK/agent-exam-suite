#!/usr/bin/env python3
"""Deterministic tests for AS-6, the `moves first` annotation in `check` output.

    python3 sandbox/test_moves_first.py

Report-only metadata: a case tagged `moves_first` in cases.json prints a suffix on its
DRIFT row and one summary line. It never changes the verdict (CLAUDE.md gotcha 2: each
group below names the injection that turns it red). No model, no network.
check()-style (gotcha 17): failures are appended to FAILED, rc comes from main().
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FAILED: list = []
MODEL = "m-champ"
TAG = "moves first"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  -- {detail}"))
    if not cond:
        FAILED.append(name)


def mf(model=MODEL, n=3):
    return {"observed_on": model, "evidence": [f"docs/e{i}.md" for i in range(n)]}


def exam(tags: dict):
    """tags: id -> moves_first value (or absent). Cases: A, B, U (U is unstable)."""
    cases = []
    for cid in ("A", "B", "U"):
        c = {"id": cid, "split": "heldout", "input": "x"}
        if cid in tags:
            c["moves_first"] = tags[cid]
        cases.append(c)
    return {"agent": "fixture-agent", "cases": cases}


def snapshot(model=MODEL):
    return {"agent": "fixture-agent", "provider": "mlx", "model": model, "heldout_score": 1.0,
            "cases": [{"id": "A", "passed": True, "stable": True},
                      {"id": "B", "passed": True, "stable": True},
                      {"id": "U", "passed": True, "stable": False}]}


def result(flipped=()):
    return {"cases": [{"id": i, "passed": i not in flipped, "failed_checks": [{"check": "c1"}]}
                      for i in ("A", "B", "U")],
            "heldout": {"score": 1.0}}


def verdict_of(flipped, tags, model=MODEL):
    snap = snapshot(model)
    v = runner.compare_to_snapshot(snap, result(flipped))
    return snap, v, runner.moves_first_ids(exam(tags), snap["model"])


def printed(v, mfi, model=MODEL):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rv = runner._print_verdict(v, moves_first=mfi, model=model)
    return rv, out.getvalue()


def test_a_appears():
    # red injection: remove the suffix/summary printing
    snap, v, mfi = verdict_of(["A"], {"A": mf()})
    rv, out = printed(v, mfi)
    row = [ln for ln in out.splitlines() if "DRIFT  A" in ln]
    check("(a) tagged drifting A: DRIFT row carries `moves first` and the evidence count",
          len(row) == 1 and TAG in row[0] and "3 recorded" in row[0], out)
    check("(a) summary line states `1 of 1`", "moves-first: 1 of 1" in out, out)


def test_b_untagged_only():
    # red injection: tag every DRIFT row unconditionally
    snap, v, mfi = verdict_of(["B"], {"A": mf()})
    rv, out = printed(v, mfi)
    check("(b) only untagged B drifts: no `moves first` anywhere (tagged A holds)",
          TAG not in out and "DRIFT  B" in out, out)


SAMPLE = ""


def test_c_mixed():
    global SAMPLE
    snap, v, mfi = verdict_of(["A", "B"], {"A": mf()})
    rv, out = printed(v, mfi)
    SAMPLE = out
    rows = {ln.split()[1].rstrip(":"): ln for ln in out.splitlines() if ln.startswith("  DRIFT")}
    check("(c) A's row tagged, B's row not",
          TAG in rows.get("A", "") and TAG not in rows.get("B", TAG), out)
    summ = [ln for ln in out.splitlines() if ln.startswith("  moves-first:")]
    check("(c) summary reads `1 of 2` and names B as not known",
          len(summ) == 1 and "1 of 2" in summ[0] and "1 are not (B)" in summ[0], out)


def test_d_model_scope():
    # red injection: ignore observed_on
    snap, v, mfi = verdict_of(["A"], {"A": mf(model="other-model")})
    rv, out = printed(v, mfi)
    check("(d) observed_on != snapshot model: helper omits A", mfi == {}, str(mfi))
    check("(d) ...and no `moves first` in output", TAG not in out and "DRIFT  A" in out, out)


def test_e_clean():
    snap, v, mfi = verdict_of([], {"A": mf()})
    rv, out = printed(v, mfi)
    check("(e) nothing drifts: no `moves first`, `ok:` printed, True",
          TAG not in out and "ok:" in out and rv is True, out)


def test_iv_unstable_tagged_exempt():
    # red injection: tag exempt rows too
    snap, v, mfi = verdict_of(["U"], {"U": mf()})
    rv, out = printed(v, mfi)
    check("(3iv) tagged but UNSTABLE case flips: exempt row, no `moves first`, verdict ok",
          TAG not in out and "exempt U" in out and rv is True and v["drift"] == [], out)


# --- real entry points -----------------------------------------------------------------
class patched:
    def __init__(self, mod, **kw):
        self.mod, self.kw, self.old = mod, kw, {}

    def __enter__(self):
        for k, val in self.kw.items():
            self.old[k] = getattr(self.mod, k)
            setattr(self.mod, k, val)

    def __exit__(self, *a):
        for k, val in self.old.items():
            setattr(self.mod, k, val)


def run_check(tags, flipped, calls):
    snap, ex = snapshot(), exam(tags)

    def fake_run(agent, exam_, provider, model, **kw):
        calls.append(1)
        return result(flipped)
    exited, rc = None, None
    out = io.StringIO()
    with patched(runner, _load_snapshot=lambda n: snap, load_agent=lambda n: {"name": n},
                 load_exam=lambda n: ex, run_exam=fake_run,
                 snapshot_preflight=lambda *a, **k: None, ollama_unload=lambda m: None):
        with contextlib.redirect_stdout(out):
            try:
                rc = runner.cmd_check(argparse.Namespace(agent="fixture-agent",
                                                         dedupe_tools=False, tolerance=0.0))
            except SystemExit as e:
                exited = e
    return exited, rc, out.getvalue()


def run_check_all(tags, flipped, calls):
    ex = exam(tags)

    def fake_run(agent, exam_, provider, model, **kw):
        calls.append(1)
        return result(flipped)
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "evals" / "fixture-agent"
        d.mkdir(parents=True)
        (d / "snapshot.json").write_text(json.dumps(snapshot()))
        out = io.StringIO()
        with patched(runner, ROOT=Path(td), _all_agents=lambda: ["fixture-agent"],
                     load_agent=lambda n: {"name": n}, load_exam=lambda n: ex,
                     run_exam=fake_run, snapshot_preflight=lambda *a, **k: None,
                     ollama_unload=lambda m: None):
            with contextlib.redirect_stdout(out):
                rc = runner.cmd_check_all(argparse.Namespace(tolerance=0.0))
    return rc, out.getvalue()


def test_f_report_only():
    # red injections: move tagged cases to exempt / return True when every drift is tagged.
    # NOTE: the verdict halves (drift/exempt, False, FAILED: DRIFT, rc 1) are a REGRESSION
    # PIN that also passes on origin/master by design; only the tag assertions discriminate
    # old from new code.
    tagged = {"A": mf()}
    plain_v = runner.compare_to_snapshot(snapshot(), result(["A"]))
    snap, v, mfi = verdict_of(["A"], tagged)
    check("(f) compare_to_snapshot return identical with and without the field",
          plain_v == v, f"{plain_v} != {v}")
    check("(f) tagged A is in drift and NOT in exempt",
          [d[0] for d in v["drift"]] == ["A"] and "A" not in [e[0] for e in v["exempt"]], str(v))
    rv, out = printed(v, mfi)
    check("(f) _print_verdict returns False and prints FAILED: DRIFT",
          rv is False and "FAILED: DRIFT" in out and v["ok"] is False, out)
    calls: list = []
    exited, rc, cout = run_check(tagged, ["A"], calls)
    check("(f) real cmd_check returns 1 and prints the tag",
          exited is None and rc == 1 and TAG in cout and calls == [1], f"{exited} {rc} {cout}")
    calls2: list = []
    rc2, aout = run_check_all(tagged, ["A"], calls2)
    check("(f) real cmd_check_all returns 1 and prints the tag (sibling call site)",
          rc2 == 1 and TAG in aout and "1 of 1" in aout, f"{rc2} {aout}")
    calls3: list = []
    rc3, bout = run_check_all(tagged, ["B"], calls3)
    check("(f) cmd_check_all: untagged-only drift prints no tag, still 1",
          rc3 == 1 and TAG not in bout, bout)


MALFORMED = {
    "not a dict": "oops",
    "list instead of dict": ["gemma"],
    "observed_on missing": {"evidence": ["a.md"]},
    "observed_on empty": {"observed_on": "", "evidence": ["a.md"]},
    "observed_on not str": {"observed_on": 5, "evidence": ["a.md"]},
    "evidence missing": {"observed_on": MODEL},
    "evidence not a list": {"observed_on": MODEL, "evidence": "a.md"},
    "evidence empty list": {"observed_on": MODEL, "evidence": []},
    "evidence holds non-str": {"observed_on": MODEL, "evidence": ["a.md", 3]},
    "evidence holds empty str": {"observed_on": MODEL, "evidence": ["a.md", ""]},
}


def test_g_malformed():
    # red injection: validation removed
    for label, bad in MALFORMED.items():
        try:
            runner.moves_first_ids(exam({"A": bad}), MODEL)
            raised = False
        except ValueError:
            raised = True
        except Exception:       # a crash is not the loud, named refusal
            raised = False
        check(f"(g) helper raises ValueError: {label}", raised)
    calls: list = []
    exited, rc, out = run_check({"A": MALFORMED["evidence empty list"]}, ["A"], calls)
    check("(g) real cmd_check: malformed tag exits with the message, run_exam never called",
          exited is not None and "moves_first" in str(exited.code) and calls == [] and rc is None,
          f"{exited} {calls}")
    calls2: list = []
    rc2, aout = run_check_all({"A": MALFORMED["not a dict"]}, ["A"], calls2)
    check("(g) real cmd_check_all: malformed tag is REFUSED for that agent, run_exam never called",
          rc2 == 1 and "REFUSED" in aout and calls2 == [], f"{rc2} {aout}")


def test_h_committed_files():
    cases_doc = json.loads((REPO / "evals/crm-followup/cases.json").read_text())
    snap = json.loads((REPO / "evals/crm-followup/snapshot.json").read_text())
    # If a champion change re-snapshots with a new model, this goes red on purpose:
    # the tags are stale until re-evaluated against the new champion.
    tagged = {c["id"]: c for c in cases_doc["cases"] if "moves_first" in c}
    want = {"crm-outage-mid-sweep", "peeters-hedge-suppresses-lookup"}
    check("(h) exactly the two expected ids carry moves_first", set(tagged) == want, str(set(tagged)))
    for cid, c in tagged.items():
        m = c["moves_first"]
        check(f"(h) {cid}: heldout", c.get("split") == "heldout", str(c.get("split")))
        check(f"(h) {cid}: observed_on == committed snapshot model",
              m.get("observed_on") == snap["model"], f"{m.get('observed_on')} vs {snap['model']}")
        ev = m.get("evidence", [])
        check(f"(h) {cid}: >= 2 evidence entries", len(ev) >= 2, str(ev))
        for p in ev:
            f = REPO / p
            check(f"(h) {cid}: evidence {p} exists and names the case id",
                  f.is_file() and cid in f.read_text(), p)
    others = []
    for f in (REPO / "evals").rglob("cases.json"):
        if ".claude" in f.relative_to(REPO).parts or f.parent.name == "crm-followup":
            continue
        doc = json.loads(f.read_text())
        cs = doc["cases"] if isinstance(doc, dict) else doc
        others += [str(f) for c in cs if isinstance(c, dict) and "moves_first" in c]
    check("(h) no other exam's cases.json carries the key", others == [], str(others))
    src = (REPO / "sandbox/runner.py").read_text()
    check("(h) no case id is a literal in runner.py", not any(i in src for i in want))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        print(f"\n{t.__name__}")
        t()
    if SAMPLE:
        print("\n--- sample output (test c) ---\n" + SAMPLE)
    print(f"\n{len(tests)} test groups; {len(FAILED)} failed check(s)"
          + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
