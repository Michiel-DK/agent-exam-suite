#!/usr/bin/env python3
"""Effect tests for `runner.py intake` (A4b, 2026-09-04) — no model, no server.

    python3 sandbox/test_intake_pipeline.py

The pipeline is two live_run_and_log calls and an exit code. What is pinned, each
seen RED on master (master has no `intake` and live_output_checks flagged every
task-intake answer as "output missing 'label'"):

  KEYS.      live_output_checks reads the structural keys off the exam: task-intake
             → 'agent'; email-triage still 'label'; expense still category+recurring.
  PROPS.     a labels exam WITH properties.py is graded by them live (task-intake's
             hand-over check fires on a paraphrase); one without adds nothing.
  DISPATCH.  happy path: the specialist is called with EXACTLY the handed-over text,
             both JSONL lines are written, the second carries via/request, exit 0.
  NONE.      'none' → exit 3, no specialist call, nothing but the dispatcher logged.
  FLAGGED.   a hand-over that fails its checks on every tier → exit 2, NOT dispatched.
             a specialist whose final answer fails its checks → exit 2.
  DEAD.      a dispatcher dead on every tier → sys.exit sentence (exit 1), logged.
Plain asserts + exit code, zero dependencies.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402
from router import TerminationError  # noqa: E402
from runner import ROOT, live_output_checks, load_exam  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


class ByAgentAdapter:
    """Scripted outputs keyed by MODEL name (tiers are models). Records every call's
    last user message so 'called with exactly X' is asserted, not assumed."""

    def __init__(self, by_model):
        self.by_model = {m: list(v) for m, v in by_model.items()}
        self.calls = []

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        self.calls.append((model, messages[-1]["content"]))
        if model not in self.by_model or not self.by_model[model]:
            raise AssertionError(f"unexpected call to {model!r}")
        out = self.by_model[model].pop(0)
        if isinstance(out, Exception):
            raise out
        return out, {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
                     "content_chars": len(out), "reasoning_chars": 0, "finish_reason": "stop"}


SCRATCH = ROOT / "results" / "_test_intake_pipeline"


@contextlib.contextmanager
def _pipeline(table, adapter):
    """Scratch routes.yaml + scratch RESULTS_DIR (so the JSONL lines this test writes
    are its own evidence and never touch results/live/) + scripted adapter."""
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)
    (SCRATCH / "routes.yaml").write_text(yaml.safe_dump(table))
    saved = (runner.ROUTES_PATH, runner.adapter_for, runner.RESULTS_DIR)
    runner.ROUTES_PATH, runner.adapter_for, runner.RESULTS_DIR = (
        SCRATCH / "routes.yaml", (lambda *a, **k: adapter), SCRATCH)
    try:
        yield
    finally:
        runner.ROUTES_PATH, runner.adapter_for, runner.RESULTS_DIR = saved
        shutil.rmtree(SCRATCH, ignore_errors=True)


def _run_intake(text):
    out, err = io.StringIO(), io.StringIO()
    args = type("A", (), {"input": text})()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = runner.cmd_intake(args)
        except SystemExit as exc:
            rc = ("exit", str(exc))
    return rc, out.getvalue(), err.getvalue()


def _lines(agent):
    p = SCRATCH / "live" / f"{agent}.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


TABLE = {"task-intake": [{"provider": "ollama", "model": "d0"}, {"provider": "ollama", "model": "d1"}],
         "expense-categorization": [{"provider": "ollama", "model": "x0"}, {"provider": "ollama", "model": "x1"}]}
REQ = "Book this: 2026-08-14 ANTHROPIC API 42.10 EUR"
PAYLOAD = "2026-08-14 ANTHROPIC API 42.10 EUR"
GOOD = json.dumps({"agent": "expense-categorization", "input": PAYLOAD})
PARA = json.dumps({"agent": "expense-categorization", "input": "Anthropic API, 42.10 euro"})
NONE = json.dumps({"agent": "none", "input": ""})
EXP = json.dumps({"category": "software", "recurring": False})


def test_keys_are_read_off_the_exam():
    ti = load_exam("task-intake")
    check("task-intake: 'agent' is the structural key, not 'label'",
          live_output_checks("task-intake", ti, {"agent": "none", "input": ""}, None, "x") == []
          and "output missing 'agent'" in live_output_checks("task-intake", ti, {"label": "x"}, None, "x"),
          str(live_output_checks("task-intake", ti, {"label": "x"}, None, "x")))
    et = load_exam("email-triage")
    check("email-triage: still 'label'",
          live_output_checks("email-triage", et, {"lable": "reply_now"}, None, "x") == ["output missing 'label'"])
    ex = load_exam("expense-categorization")
    check("expense: still category + recurring",
          live_output_checks("expense-categorization", ex, {"category": "software"}, None, "x")
          == ["output missing 'recurring'"])


def test_properties_run_live_for_a_labels_exam_that_has_them():
    ti = load_exam("task-intake")
    bad = live_output_checks("task-intake", ti, json.loads(PARA), None, REQ)
    check("task-intake: a paraphrased hand-over is flagged live by the span property",
          any("check_input_is_verbatim_span" in f for f in bad), str(bad))
    check("task-intake: the verbatim hand-over passes live",
          live_output_checks("task-intake", ti, json.loads(GOOD), None, REQ) == [])
    check("email-triage (no properties.py): nothing added",
          live_output_checks("email-triage", load_exam("email-triage"), {"label": "ignore"}, None, "x") == [])


def test_dispatch_happy_path():
    ad = ByAgentAdapter({"d0": [GOOD], "x0": [EXP]})
    with _pipeline(TABLE, ad):
        rc, out, err = _run_intake(REQ)
        ti, ex = _lines("task-intake"), _lines("expense-categorization")
    check("happy: exit 0", rc == 0, str(rc))
    check("happy: dispatcher then specialist, one call each",
          [m for m, _ in ad.calls] == ["d0", "x0"], str(ad.calls))
    check("happy: the specialist was called with EXACTLY the handed-over text",
          ad.calls[1][1] == PAYLOAD, repr(ad.calls[1][1]))
    check("happy: printed record names the agent and carries the output",
          '"agent": "expense-categorization"' in out and '"category": "software"' in out, out[:300])
    check("happy: dispatcher line logged", len(ti) == 1 and ti[0]["output"]["agent"] == "expense-categorization", str(ti))
    check("happy: specialist line logged WITH provenance",
          len(ex) == 1 and ex[0]["via"] == "task-intake" and ex[0]["request"] == REQ and ex[0]["input"] == PAYLOAD,
          str(ex))


def test_none_exits_3_and_runs_nothing_else():
    ad = ByAgentAdapter({"d0": [NONE]})
    with _pipeline(TABLE, ad):
        rc, out, err = _run_intake("Book me a train to Paris next Tuesday morning.")
        ti, ex = _lines("task-intake"), _lines("expense-categorization")
    check("none: exit 3", rc == 3, str(rc))
    check("none: only the dispatcher was called", [m for m, _ in ad.calls] == ["d0"], str(ad.calls))
    check("none: request printed back, says no specialist", '"agent": "none"' in out and "no specialist" in err, err)
    check("none: dispatcher logged, nothing else", len(ti) == 1 and ex == [], f"{len(ti)}/{len(ex)}")


def test_flagged_handover_is_never_dispatched():
    ad = ByAgentAdapter({"d0": [PARA], "d1": [PARA], "x0": [EXP]})
    with _pipeline(TABLE, ad):
        rc, out, err = _run_intake(REQ)
        ti = _lines("task-intake")
    check("flagged hand-over: exit 2", rc == 2, str(rc))
    check("flagged hand-over: both dispatcher tiers tried, specialist NEVER called",
          [m for m, _ in ad.calls] == ["d0", "d1"], str(ad.calls))
    check("flagged hand-over: says not dispatched", "not dispatched" in err, err)
    check("flagged hand-over: the flagged line is logged with both attempts",
          len(ti) == 1 and len(ti[0].get("attempts", [])) == 2, str(ti)[:300])


def test_flagged_specialist_answer_exits_2():
    ad = ByAgentAdapter({"d0": [GOOD], "x0": [json.dumps({"category": "software"})],
                         "x1": [json.dumps({"category": "software"})]})
    with _pipeline(TABLE, ad):
        rc, out, err = _run_intake(REQ)
    check("flagged specialist: exit 2 after both specialist tiers", rc == 2 and
          [m for m, _ in ad.calls] == ["d0", "x0", "x1"], f"{rc} {ad.calls}")
    check("flagged specialist: names the agent and via", "expense-categorization's final answer" in err
          and "via task-intake" in err, err)


def test_dead_dispatcher_exits_with_a_sentence():
    dead = TerminationError("x", {"finish_reason": "length", "completion_tokens": 0, "content_chars": 0})
    ad = ByAgentAdapter({"d0": [dead], "d1": [dead]})
    with _pipeline(TABLE, ad):
        rc, out, err = _run_intake(REQ)
        ti = _lines("task-intake")
    check("dead: sys.exit with a sentence naming the dispatcher",
          isinstance(rc, tuple) and "task-intake emitted no answer" in rc[1], str(rc))
    check("dead: the death was logged before the exit", len(ti) == 1 and "termination" in ti[0], str(ti)[:200])


def test_empty_input_refused():
    rc, out, err = _run_intake("   ")
    check("empty input: refused with a sentence", isinstance(rc, tuple) and "no input" in rc[1], str(rc))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"\n{name}")
            try:
                fn()
            except Exception as exc:
                check(f"{name} raised {type(exc).__name__}", False, str(exc)[:200])
    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
        sys.exit(1)
    print("all intake-pipeline tests passed")
