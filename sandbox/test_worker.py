#!/usr/bin/env python3
"""Deterministic tests for the shadow-mode inbox digest (`sandbox/worker.py`) —
lane 0, `docs/worker-brief-2026-09-06.md`. No network, no model, no live IMAP.

    python3 sandbox/test_worker.py

Same bar as every other test file here: plain `check()` assertions + exit code,
zero pip dependencies. Each test's docstring names the exact injection target — the
line(s) that, reverted to the wrong build named, make that specific test (and only
that test, where noted) fail.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402  (RESULTS_DIR monkeypatching; TerminationError)
import worker  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


# ------------------------------------------------------------------ fixtures

def _email(frm: str, subject: str, mid: str, body: str = "please get back to me soon") -> bytes:
    m = EmailMessage()
    m["From"] = frm
    m["Subject"] = subject
    m["Message-ID"] = mid
    m.set_content(body)
    return m.as_bytes()


def _rec(ts: str, mid: str, label: str, source: str = "worker",
        checks_failed: list | None = None, subject: str = "s",
        frm: str = "f@x.com") -> dict:
    r = {"ts": ts, "message_id": mid, "from": frm, "subject": subject,
         "output": {"label": label}, "source": source, "model": "m", "provider": "p",
         "input": "x"}
    if checks_failed:
        r["checks_failed"] = checks_failed
    return r


# sha256(message_id) % 100 values, computed offline and pinned (never builtin hash()):
#   "<msg-19@example.com>" -> 7   (sampled at rate 0.10, since 7 < 10)
#   "<msg-2@example.com>"  -> 23  (NOT sampled at rate 0.10, since 23 >= 10)
SAMPLED_MID = "<msg-19@example.com>"
NOT_SAMPLED_MID = "<msg-2@example.com>"


# ------------------------------------------------------------------ 1. bucketing

def test_1_five_fixture_records_land_in_exactly_one_state_each() -> None:
    """Five fixture records, one per queue state (reply_now / flagged-by-check /
    flagged-off-vocab / sampled / silent) -> render() puts each in exactly one
    bucket.

    Injection target: worker.render's `needs_you_lines` construction (the union of
    reply_now lines and `_is_flagged` lines). A build that computes it from
    `label == "reply_now"` alone (ignoring `_is_flagged`) sends the flagged-by-check
    and flagged-off-vocab records to `remaining` instead of needs-you — this test's
    per-`from` presence assertions for those two records then fail.
    """
    date = "2026-09-06"
    recs = [
        (1, _rec(f"{date}T09:00:00", "<r1@x.com>", "reply_now", frm="reply-now@x.com")),
        (2, _rec(f"{date}T09:01:00", "<r2@x.com>", "reply_later", frm="flag-check@x.com",
                checks_failed=["grounded_answer"])),
        (3, _rec(f"{date}T09:02:00", "<r3@x.com>", "URGENT", frm="flag-vocab@x.com")),
        (4, _rec(f"{date}T09:03:00", SAMPLED_MID, "ignore", frm="sampled@x.com")),
        (5, _rec(f"{date}T09:04:00", NOT_SAMPLED_MID, "ignore", frm="silent@x.com")),
    ]
    text = worker.render(recs, date, snapshot={}, rate=0.10)
    check("reply_now record is in needs-you", "reply-now@x.com" in text, text)
    check("flagged-by-check record is in needs-you", "flag-check@x.com" in text, text)
    check("flagged-off-vocab record is in needs-you", "flag-vocab@x.com" in text, text)
    check("sampled record is in needs-you", "sampled@x.com" in text, text)
    check("silent record is NOT in needs-you table",
          "silent@x.com" not in text, text)
    check("silent count is 1", "1 message(s) needed no review" in text, text)
    check("flagged count is 2 (checks_failed + off-vocab; reply_now excluded)",
          "flagged (2026-09-06): 2" in text, text)


# ------------------------------------------------------------------ 2. off-vocab regression pin

def test_2_offvocab_label_is_flagged_not_silent() -> None:
    """A label outside {reply_now, reply_later, ignore} (e.g. "URGENT") must be
    flagged, because `live_output_checks` is structural-only for `labels` mode and
    a live {"label": "URGENT"} exits 0 clean (declared gap in runner.py) — this
    digest is the only place that catches it.

    Injection target: worker._is_flagged. WRONG BUILD: bucket on
    `label == "reply_now"` only (dropping the `label not in VALID_LABELS` arm) ->
    "URGENT" has no checks_failed and is not "reply_now", so it falls through to
    `remaining` and, absent a sampling hit, lands in silent instead of flagged.
    """
    date = "2026-09-06"
    recs = [(1, _rec(f"{date}T09:00:00", NOT_SAMPLED_MID, "URGENT", frm="urgent@x.com"))]
    text = worker.render(recs, date, snapshot={}, rate=0.10)
    check("off-vocab record appears in needs-you", "urgent@x.com" in text, text)
    check("reason names it off-vocab", "off-vocab" in text, text)
    check("flagged count is 1", "flagged (2026-09-06): 1" in text, text)
    check("silent count is 0 (not silently dropped)",
          "0 message(s) needed no review" in text, text)


# ------------------------------------------------------------------ 3. sample determinism

def test_3_sample_determinism_pinned_members() -> None:
    """Same message_ids -> the same sampled/not-sampled verdict, twice, and a
    pre-computed member set at rate 0.10 matches (the sha256 digest is pinned, not
    just the resulting set size — a build that samples on `hash(message_id)` or on
    `random` would not reproduce this exact split across two calls or two processes).

    Injection target: worker._sampled. WRONG BUILD: `hash(message_id) % 100 < ...`
    (builtin `hash()`, process-salted for str since PYTHONHASHSEED randomization) ->
    the two calls in this test would disagree across a fresh interpreter, and this
    test's cross-process assertion (spawning a second interpreter) would fail.
    """
    check("SAMPLED_MID (score 7) is sampled at rate 0.10",
          worker._sampled(SAMPLED_MID, 0.10) is True)
    check("NOT_SAMPLED_MID (score 23) is NOT sampled at rate 0.10",
          worker._sampled(NOT_SAMPLED_MID, 0.10) is False)
    check("no message_id -> never sampled", worker._sampled(None, 0.10) is False)
    check("no message_id (empty string) -> never sampled", worker._sampled("", 1.0) is False)
    # Same id, two direct calls in-process:
    check("repeated call is deterministic (in-process)",
          worker._sampled(SAMPLED_MID, 0.10) == worker._sampled(SAMPLED_MID, 0.10))
    # A FRESH interpreter (PYTHONHASHSEED would differ across processes for
    # builtin hash() on str; sha256 is immune) must agree with this one.
    code = (f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); "
           f"import worker; print(worker._sampled({SAMPLED_MID!r}, 0.10))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    check("cross-process determinism (fresh interpreter agrees)",
          out.stdout.strip() == "True", out.stdout + out.stderr)


# ------------------------------------------------------------------ 4. --dry-run

def test_4_dry_run_writes_nothing_and_calls_no_model() -> None:
    """--dry-run fetches+parses+prints only: no model call, no log write.

    Injection target: worker._process's `if dry_run:` branch. WRONG BUILD: falling
    through to the `runner.live_run_and_log(...)` call regardless of `dry_run` ->
    the monkeypatched stub below raises AssertionError, which this test would then
    report as an uncaught exception (a hard fail, not a silent pass).
    """
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("live_run_and_log must NOT be called during --dry-run")

    orig_fetch = worker.sg.fetch_recent_raw
    orig_live = runner.live_run_and_log
    orig_results = runner.RESULTS_DIR
    worker.sg.fetch_recent_raw = lambda count, mailbox: [
        _email("a@x.com", "s1", "<dr-1@x.com>"), _email("b@x.com", "s2", "<dr-2@x.com>")]
    runner.live_run_and_log = _boom
    with tempfile.TemporaryDirectory() as td:
        runner.RESULTS_DIR = Path(td)
        try:
            rc = worker.run(count=2, mailbox="INBOX", dry_run=True, max_body_chars=4000)
        finally:
            worker.sg.fetch_recent_raw = orig_fetch
            runner.live_run_and_log = orig_live
            runner.RESULTS_DIR = orig_results
        check("dry-run returns 0", rc == 0)
        check("dry-run made no model/log call", calls["n"] == 0)
        check("dry-run wrote no results/live file",
              not (Path(td) / "live" / "email-triage.jsonl").exists())


# ------------------------------------------------------------------ 5. logged extra + dedup

def test_5_logged_extra_carries_message_id_and_source_and_rerun_dedups() -> None:
    """The logged `extra` carries message_id + source: "worker", and a rerun
    dedups through `shadow_gmail._load_logged_message_ids` (unmodified, reused) on
    a temp RESULTS_DIR.

    Injection target: worker._process's `extra = {...}` dict literal. WRONG BUILD:
    omitting "source": "worker" (or key-renaming it) -> `worker digest`'s
    `_in_scope` check (`rec.get("source") in IN_SCOPE_SOURCES`) would then exclude
    every worker-logged line from every header figure and the needs-you table,
    which this test's direct read of the written line would catch.
    """
    written: list[dict] = []

    def _fake_live_run_and_log(agent, text, extra=None, **kw):
        entry = {"ts": "2026-09-06T10:00:00", "model": "m", "provider": "p",
                "input": text, **(extra or {}), "output": {"label": "reply_later"}}
        live_dir = runner.RESULTS_DIR / "live"
        live_dir.mkdir(parents=True, exist_ok=True)
        with (live_dir / f"{agent}.jsonl").open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        written.append(entry)
        return entry, {"output": entry["output"], "metrics": {}}

    orig_live = runner.live_run_and_log
    orig_results = runner.RESULTS_DIR
    runner.live_run_and_log = _fake_live_run_and_log
    with tempfile.TemporaryDirectory() as td:
        runner.RESULTS_DIR = Path(td)
        try:
            raw = _email("dedup@x.com", "renewal", "<dedup-1@x.com>")
            c1 = worker._process([raw], dry_run=False, max_body_chars=4000)
            c2 = worker._process([raw], dry_run=False, max_body_chars=4000)
        finally:
            runner.live_run_and_log = orig_live
            runner.RESULTS_DIR = orig_results
    check("first pass logs the message", c1["logged"] == 1, str(c1))
    check("model was called exactly once across both passes", len(written) == 1)
    check("second pass dedups instead of re-running", c2["skipped_dup"] == 1, str(c2))
    check("second pass logs nothing new", c2["logged"] == 0, str(c2))
    entry = written[0]
    check("logged entry carries message_id", entry.get("message_id") == "<dedup-1@x.com>")
    check("logged entry carries source: worker", entry.get("source") == "worker")


# ------------------------------------------------------------------ 6. render() big fixture

def test_6_render_two_date_fixture_with_corrupt_and_sourceless_lines() -> None:
    """render() on a raw file with TWO dates, one corrupt line, and one source-less
    manual `runner.py live` record (no `extra`, so no `source` key) on the target
    date: only in-scope (date == D, source in {worker, shadow_gmail}) records
    appear anywhere in the digest; the source-less one appears nowhere; every
    surviving row's line number is the ABSOLUTE raw-file line; the promote command
    appears exactly once; the corrupt line is listed (under flagged) at ITS
    absolute line; the header carries heldout/counts/flagged/days-running; the
    silent count is present.

    Injection target: worker.render's row-building loops (`rows.append((ln, r, ...))`).
    WRONG BUILD: enumerating the FILTERED list (`for ln, (_, r) in enumerate(scoped, 1)`)
    instead of keeping the file's own `ln` -> every row's printed line number would be
    its position among in-scope records (1, 2, 3, ...) instead of the real file line —
    this test's exact-line-number assertions (2, 3, 5) would then fail.
    """
    d1, d2 = "2026-09-01", "2026-09-02"
    lines = [
        json.dumps(_rec(f"{d2}T08:00:00", "<d2-1@x.com>", "ignore", source="worker")),
        json.dumps(_rec(f"{d1}T08:00:00", SAMPLED_MID, "ignore", source="worker",
                        frm="sampled@x.com")),
        "{not valid json at all",
        json.dumps({"ts": f"{d1}T08:05:00", "message_id": "<manual@x.com>",
                   "from": "manual@x.com", "subject": "s", "output": {"label": "ignore"},
                   "input": "x", "model": "m", "provider": "p"}),  # no "source" key
        json.dumps(_rec(f"{d1}T09:00:00", "<r1@x.com>", "reply_now", source="worker",
                        frm="reply-now@x.com")),
        json.dumps(_rec(f"{d2}T09:00:00", "<d2-2@x.com>", "ignore", source="shadow_gmail")),
        json.dumps(_rec(f"{d1}T09:05:00", NOT_SAMPLED_MID, "ignore", source="shadow_gmail",
                        frm="silent@x.com")),
    ]
    with tempfile.TemporaryDirectory() as td:
        live_path = Path(td) / "live.jsonl"
        live_path.write_text("\n".join(lines) + "\n")
        records = worker._read_live_lines(live_path)
    check("7 raw lines read back with absolute line numbers",
          [ln for ln, _ in records] == [1, 2, 3, 4, 5, 6, 7], records)
    check("corrupt line 3 surfaced as _parse_error",
          "_parse_error" in dict(records)[3])

    snapshot = {"heldout_score": 0.75,
               "cases": [{"split": "heldout", "passed": p} for p in (True, True, True, False)]}
    text = worker.render(records, d1, snapshot, rate=0.10)

    check("heldout figure in header", "3/4 (75.0%)" in text, text)
    check("counts by label for D: ignore 2, reply_now 1",
          "counts by label (2026-09-01): ignore 2, reply_now 1" in text, text)
    check("flagged count for D is 1 (the corrupt line only — no in-scope-D "
         "checks_failed/off-vocab record)", "flagged (2026-09-01): 1" in text, text)
    check("days running is 2 (D and D2 both have in-scope-source records)",
          "days running: 2" in text, text)
    check("silent count is 1", "1 message(s) needed no review" in text, text)

    check("other-date worker record (line 1) appears nowhere", "d2-1@x.com" not in text)
    check("other-date shadow_gmail record (line 6) appears nowhere", "d2-2@x.com" not in text)
    check("source-less manual record (line 4) appears nowhere", "manual@x.com" not in text)
    check("silent in-scope record (line 7) is not in the needs-you table",
          "silent@x.com" not in text)

    # Row identity and line number are asserted on the SAME table row. Two separate
    # substring checks ("sampled@x.com" in text and "| 2 |" in text) were the wrong
    # build here (PR #77 review): under the filtered-list renumbering injection some
    # OTHER row still contained "| 2 |", so 2 of the 3 assertions stayed green.
    def _row_with(needle: str) -> str:
        rows = [ln for ln in text.splitlines() if ln.startswith("|") and needle in ln]
        return rows[0] if len(rows) == 1 else f"<{len(rows)} rows match {needle!r}>"

    check("sampled row (line 2) carries its ABSOLUTE line number 2 on ITS row",
          re.search(r"\|\s*2\s*\|", _row_with("sampled@x.com")) is not None,
          _row_with("sampled@x.com"))
    check("reply_now row (line 5) carries its ABSOLUTE line number 5 on ITS row",
          re.search(r"\|\s*5\s*\|", _row_with("reply-now@x.com")) is not None,
          _row_with("reply-now@x.com"))
    check("corrupt line's row carries its ABSOLUTE line number 3 on ITS row",
          re.search(r"\|\s*3\s*\|", _row_with("parse_error")) is not None,
          _row_with("parse_error"))
    check("promote command appears exactly once",
          text.count("promote email-triage <line>") == 1, text)


# ------------------------------------------------------------------ 7. reachable through runner.py

def test_7_worker_help_and_digest_reachable_through_runner() -> None:
    """`runner.py worker --help` exits 0 (presence), and `runner.py worker digest
    --date ...` actually DISPATCHES to worker.main and writes the file (effect) —
    driven through the REAL `runner.main()` with `sys.argv` set and
    `runner.RESULTS_DIR` monkeypatched, not by calling `worker.main` directly. That
    proves the subcommand is reachable end to end, not merely registered
    (CLAUDE.md gotcha 1: presence is not effect).

    Injection target: runner.py's `sub.add_parser("worker", ...)` registration.
    WRONG BUILD: forgetting `sp.set_defaults(fn=cmd_worker)` (or wiring `fn` to a
    no-op) -> `runner.main()` either raises (no `fn` attribute) or never calls
    worker.main, and this test's file-was-actually-written assertion fails even
    though `--help` still exits 0.
    """
    help_proc = subprocess.run(
        [sys.executable, "sandbox/runner.py", "worker", "--help"],
        cwd=ROOT, capture_output=True, text=True)
    check("`runner.py worker --help` exits 0", help_proc.returncode == 0,
          f"rc={help_proc.returncode} stderr={help_proc.stderr}")

    orig_results = runner.RESULTS_DIR
    orig_argv = sys.argv
    with tempfile.TemporaryDirectory() as td:
        runner.RESULTS_DIR = Path(td)
        out_path = Path(td) / "digest.md"
        sys.argv = ["runner.py", "worker", "digest", "--date", "2026-01-01",
                   "--out", str(out_path)]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = runner.main()
            check("runner.main() dispatching `worker digest` returns 0", rc == 0)
            check("the digest file was actually written (effect, not just presence)",
                  out_path.exists() and "# Inbox digest — 2026-01-01" in out_path.read_text())
        finally:
            runner.RESULTS_DIR = orig_results
            sys.argv = orig_argv


# ------------------------------------------------------------------ 8. TerminationError -> logged

def test_8_termination_error_counts_as_logged() -> None:
    """A message whose triage raises TerminationError is counted `logged`, not
    `failed`: `runner.live_run_and_log` writes the JSONL line BEFORE it raises, so
    the evidence is already on disk when the exception propagates.

    Injection target: worker._process's `except runner.TerminationError:` arm.
    WRONG BUILD: a single broad `except Exception:` before this specific arm (so
    TerminationError is swallowed by the generic handler and counted `failed`) ->
    this test's `counts["logged"] == 1` assertion fails and `counts["failed"] == 1`
    instead.
    """
    def _dies(agent, text, extra=None, **kw):
        raise runner.TerminationError("emitted no answer", {"cause": "empty"})

    orig_live = runner.live_run_and_log
    runner.live_run_and_log = _dies
    with tempfile.TemporaryDirectory() as td:
        orig_results = runner.RESULTS_DIR
        runner.RESULTS_DIR = Path(td)
        try:
            raw = _email("dies@x.com", "s", "<dies-1@x.com>")
            c = worker._process([raw], dry_run=False, max_body_chars=4000)
        finally:
            runner.live_run_and_log = orig_live
            runner.RESULTS_DIR = orig_results
    check("TerminationError counted as logged", c["logged"] == 1, str(c))
    check("TerminationError NOT counted as failed", c["failed"] == 0, str(c))


# ------------------------------------------------------------------ runner

# ------------------------------------------------------------------ 9. the REAL run() print path

def test_9_non_dry_run_prints_logged_tally_and_invariant() -> None:
    """`worker.run(dry_run=False)` — the path the live witness exercises — prints the
    six-counter tally with the word `logged` (never `would-log`) and the results path,
    and the counters satisfy logged+skipped_dup+skipped_empty+parse_skip+failed ==
    fetched. Added after PR #77's test-honesty refutation: this print path had zero
    automated coverage and its only evidence was a hand-edited transcript.

    Injection target: worker.run's `label = "would-log" if dry_run else "logged"`
    line. WRONG BUILD: `label = "would-log"` unconditionally (or `if not dry_run`) ->
    the real run's tally reads `would-log`, and this test's `logged 2 |` assertion fails.
    """
    written: list[dict] = []

    def _fake_live_run_and_log(agent, text, extra=None, **kw):
        entry = {"ts": "2026-09-06T10:00:00", **(extra or {}), "output": {"label": "ignore"}}
        written.append(entry)
        return entry, {"output": entry["output"], "metrics": {}}

    orig_fetch = worker.sg.fetch_recent_raw
    orig_live = runner.live_run_and_log
    orig_results = runner.RESULTS_DIR
    worker.sg.fetch_recent_raw = lambda count, mailbox: [
        _email("a@x.com", "s1", "<nd-1@x.com>"), _email("b@x.com", "s2", "<nd-2@x.com>"),
        _email("c@x.com", "s3", "<nd-3@x.com>", body="   ")]  # third: empty body
    runner.live_run_and_log = _fake_live_run_and_log
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        runner.RESULTS_DIR = Path(td)
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                rc = worker.run(count=3, mailbox="INBOX", dry_run=False, max_body_chars=4000)
        finally:
            worker.sg.fetch_recent_raw = orig_fetch
            runner.live_run_and_log = orig_live
            runner.RESULTS_DIR = orig_results
    out = buf.getvalue()
    tally = [ln for ln in out.splitlines() if ln.startswith("fetched 3 |")]
    check("real run returns 0", rc == 0)
    check("exactly one tally line", len(tally) == 1, out)
    line = tally[0] if tally else ""
    check("tally says `logged 2` (not would-log) on the real path",
          "| logged 2 |" in line and "would-log" not in line, line)
    check("tally names the results path", "-> results/live/email-triage.jsonl" in line, line)
    m = re.search(r"fetched (\d+) \| logged (\d+) \| skipped_dup (\d+) \| skipped_empty (\d+) "
                  r"\| parse_skip (\d+) \| failed (\d+)", line)
    check("six counters parse and satisfy the invariant",
          m is not None and int(m.group(1)) == sum(int(g) for g in m.groups()[1:]), line)
    check("skipped_empty is 1 (the blank-body message)", m is not None and m.group(4) == "1", line)
    check("model called exactly twice", len(written) == 2)


def main() -> int:
    for fn in sorted(
        (v for k, v in globals().items() if k.startswith("test_") and callable(v)),
        key=lambda f: f.__name__,
    ):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all green'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
