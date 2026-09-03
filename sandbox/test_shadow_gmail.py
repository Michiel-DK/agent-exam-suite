#!/usr/bin/env python3
"""Deterministic tests for the read-only Gmail shadow logger — no live IMAP.

    python3 sandbox/test_shadow_gmail.py

Covers, all offline against canned email.message_from_bytes fixtures:
  * parsing: plain, multipart(alternative), HTML-only, weird charset, RFC 2047
    encoded headers — From/Subject/body extracted, never crashes;
  * the constructed input matches the email-triage exam format exactly;
  * READ-ONLY source-level assertions: readonly=True + BODY.PEEK present, and NO
    mailbox-mutating verb (store/expunge/\\Seen/copy/append/delete) reachable;
  * ONE end-to-end run through the real email-triage model on a HARDCODED sample
    (NOT Gmail) — skipped with a printed reason if Ollama isn't reachable.

Plain asserts + exit code, zero pip dependencies — same bar as runner.py itself.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402  (for RESULTS_DIR monkeypatching in dedup tests)
import shadow_gmail as sg  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


# ------------------------------------------------------------------ fixtures

def _plain() -> bytes:
    m = EmailMessage()
    m["From"] = "sofie@janssens-bakery.com"
    m["Subject"] = "quote for AI chatbot"
    m["Message-ID"] = "<plain-1@janssens-bakery.com>"
    m.set_content("Hi, could you call us this week about a chatbot? Thanks, Sofie")
    return m.as_bytes()


def _multipart() -> bytes:
    m = EmailMessage()
    m["From"] = "accounting@hostpro.eu"
    m["Subject"] = "Payment reminder"
    m["Message-ID"] = "<mp-1@hostpro.eu>"
    m.set_content("Invoice 4482 is overdue. Please settle within 7 days.")
    m.add_alternative("<html><body><p>Invoice 4482 is overdue.</p></body></html>",
                      subtype="html")
    return m.as_bytes()


def _html_only() -> bytes:
    m = EmailMessage()
    m["From"] = "growth@rankboosters.net"
    m["Subject"] = "Your website is losing traffic"
    m["Message-ID"] = "<html-1@rankboosters.net>"
    m.set_content(
        "<html><head><style>p{color:red}</style></head><body>"
        "<p>We found 47 SEO issues.</p><script>evil()</script>"
        "<p>Fix them for $299/month.</p></body></html>",
        subtype="html")
    return m.as_bytes()


def _weird_charset() -> bytes:
    """A latin-1 body + an RFC 2047 encoded UTF-8 Subject — the 'weird charset' case."""
    body = "Beste, de prijs is 65 euros. Groeten, André".encode("latin-1")
    raw = (
        b"From: andre@voorbeeld.be\r\n"
        b"Subject: =?UTF-8?B?" +
        __import__("base64").b64encode("Vraag over prijs — André".encode()) +
        b"?=\r\n"
        b"Message-ID: <weird-1@voorbeeld.be>\r\n"
        b"Content-Type: text/plain; charset=iso-8859-1\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\n" + body
    )
    return raw


def _empty_body() -> bytes:
    """Headers only, no body — an attachment-only mail / calendar invite / read
    receipt. extract_body() returns "" for this."""
    return (b"From: calendar@corp.com\r\n"
            b"Subject: Invitation: Standup\r\n"
            b"Message-ID: <empty-1@corp.com>\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n")


def _plain2() -> bytes:
    """A second distinct plain message (different message_id) for batch tests."""
    m = EmailMessage()
    m["From"] = "lars@acme.io"
    m["Subject"] = "renewal question"
    m["Message-ID"] = "<plain-2@acme.io>"
    m.set_content("Can you confirm our renewal date? Thanks, Lars")
    return m.as_bytes()


def _ok_record() -> tuple[dict, dict]:
    """A stand-in for a successful live_run_and_log return: (entry, record)."""
    record = {"output": {"label": "reply_later"}, "metrics": {}}
    return {"logged": True}, record


# ------------------------------------------------------------------ parsing tests

def test_plain_parse_and_input_format() -> None:
    p = sg.parse_message(_plain(), max_body_chars=4000)
    check("plain: from extracted", p["from"] == "sofie@janssens-bakery.com", p["from"])
    check("plain: subject extracted", p["subject"] == "quote for AI chatbot", p["subject"])
    check("plain: body extracted", "chatbot" in p["body"], p["body"])
    check("plain: message_id extracted",
          p["message_id"] == "<plain-1@janssens-bakery.com>", p["message_id"])
    # Exact exam format: 'From: X\nSubject: Y\n\n<body>'
    expected = ("From: sofie@janssens-bakery.com\n"
                "Subject: quote for AI chatbot\n\n"
                "Hi, could you call us this week about a chatbot? Thanks, Sofie")
    check("plain: input matches exam format exactly", p["input"] == expected,
          repr(p["input"]))


def test_input_shape_matches_shipped_cases() -> None:
    """The constructed input must be the SAME shape the shipped exam uses:
    starts 'From: ', has a 'Subject: ' line, then a blank line before the body."""
    p = sg.parse_message(_plain(), max_body_chars=4000)
    m = re.match(r"^From: .+\nSubject: .+\n\n", p["input"])
    check("input has From/Subject/blank-line header block", m is not None)
    # Cross-check against a real shipped case if the exam is present.
    cases_path = sg.Path(__file__).resolve().parent.parent / "evals" / "email-triage" / "cases.json"
    if cases_path.exists():
        sample = json.loads(cases_path.read_text())["cases"][0]["input"]
        check("shipped case also matches the header-block regex",
              re.match(r"^From: .+\nSubject: .+\n\n", sample) is not None)


def test_multipart_prefers_plain() -> None:
    p = sg.parse_message(_multipart(), max_body_chars=4000)
    check("multipart: from extracted", p["from"] == "accounting@hostpro.eu")
    check("multipart: prefers text/plain body",
          "overdue" in p["body"] and "<p>" not in p["body"], p["body"])


def test_html_only_stripped() -> None:
    p = sg.parse_message(_html_only(), max_body_chars=4000)
    check("html-only: tags stripped", "<p>" not in p["body"] and "<html" not in p["body"],
          p["body"])
    check("html-only: script/style content removed",
          "evil()" not in p["body"] and "color:red" not in p["body"], p["body"])
    check("html-only: visible text kept",
          "47 SEO issues" in p["body"] and "$299" in p["body"], p["body"])


def test_weird_charset_and_encoded_header() -> None:
    p = sg.parse_message(_weird_charset(), max_body_chars=4000)
    check("weird: latin-1 body decoded without crash", "André" in p["body"], p["body"])
    check("weird: euros amount preserved", "65 euros" in p["body"], p["body"])
    check("weird: RFC2047 encoded subject decoded",
          p["subject"] == "Vraag over prijs — André", repr(p["subject"]))


def test_body_truncation() -> None:
    m = EmailMessage()
    m["From"] = "x@y.com"
    m["Subject"] = "long"
    m.set_content("A" * 10000)
    p = sg.parse_message(m.as_bytes(), max_body_chars=100)
    # Truncation applies to the model-facing `input` (the prompt), not the raw parsed
    # body field. Header block (~30 chars) + 100 body chars + marker < 200.
    check("truncation: input bounded", len(p["input"]) < 200, str(len(p["input"])))
    check("truncation: marker appended", "[...truncated]" in p["input"])


def test_malformed_message_does_not_crash_parse() -> None:
    # Garbage bytes: message_from_bytes is lenient; parse must still return a dict.
    p = sg.parse_message(b"\xff\xfe not really an email at all", max_body_chars=4000)
    check("malformed: returns a dict with an input string",
          isinstance(p, dict) and isinstance(p["input"], str))


# ------------------------------------------------------------------ read-only guard

_SRC = (Path(__file__).resolve().parent / "shadow_gmail.py").read_text()


def _code_lines() -> list[str]:
    """Source lines with full-line comments and docstring-ish prose removed, so the
    read-only-verb assertions test EXECUTABLE code, not the invariant comment that
    names the forbidden verbs on purpose."""
    out = []
    for ln in _SRC.splitlines():
        stripped = ln.strip()
        if stripped.startswith("#"):
            continue
        out.append(ln)
    return out


def test_readonly_select_and_peek_present() -> None:
    check("uses select(..., readonly=True)", "readonly=True" in _SRC)
    check("uses BODY.PEEK (does not set \\Seen)", "BODY.PEEK[]" in _SRC)


def test_no_mutating_verbs_in_executable_code() -> None:
    # Strip ALL triple-quoted blocks (module + every function docstring — where the
    # read-only banner legitimately NAMES the forbidden verbs) AND full-line comments,
    # then assert no mailbox-mutating IMAP verb is invoked anywhere in real code.
    # Single-quote string literals (e.g. the "(BODY.PEEK[])" fetch spec) are kept, so
    # a real \\Seen flag or BODY[] fetch inside a string would still be caught.
    code = re.sub(r'(?s)""".*?"""', " ", _SRC)
    code = re.sub(r"(?s)'''.*?'''", " ", code)
    code = "\n".join(l for l in code.splitlines()
                     if not l.strip().startswith("#"))
    # Scope to calls on the IMAP connection object `conn` — a mailbox mutation is a
    # method call on the live connection (conn.store / conn.expunge / conn.copy /
    # conn.append / conn.uid). Scoping to `conn.` avoids false-matching Python's
    # list.append(...). BODY.PEEK[] legitimately contains no verb.
    for verb in ("store", "expunge", "copy", "append", "uid", "delete"):
        check(f"no conn.{verb}( mailbox-mutation call",
              not re.search(rf"conn\s*\.\s*{verb}\s*\(", code), verb)
    check("no BODY[] (unpeeked fetch that would set \\Seen)",
          "BODY[]" not in code)
    check("no explicit \\Seen flag set", "\\Seen" not in code)
    # Belt-and-suspenders: the ONLY connection methods this tool ever invokes are the
    # read-only session verbs. Any conn.<method>( must be in this allowlist.
    used = set(re.findall(r"conn\s*\.\s*(\w+)\s*\(", code))
    allowed = {"login", "select", "search", "fetch", "close", "logout"}
    check("every conn.<method>( is a read-only session verb",
          used <= allowed, f"unexpected: {used - allowed}")


def test_dry_run_never_imports_imaplib_or_calls_model(monkeypatched=None) -> None:
    """--dry-run must fetch+parse+print with NO model call and NO log write. We prove
    it by monkeypatching both the fetch and the run+log path to explode if reached,
    then feeding canned messages through the dry-run branch directly."""
    calls = {"model": 0}

    def _boom_live(*a, **k):
        calls["model"] += 1
        raise AssertionError("live_run_and_log must NOT be called during --dry-run")

    orig_fetch = sg.fetch_recent_raw
    orig_live = sg.live_run_and_log
    sg.fetch_recent_raw = lambda count, mailbox: [_plain(), _html_only()]
    sg.live_run_and_log = _boom_live
    try:
        rc = sg.run(count=2, mailbox="INBOX", dry_run=True, max_body_chars=4000)
    finally:
        sg.fetch_recent_raw = orig_fetch
        sg.live_run_and_log = orig_live
    check("dry-run returns 0", rc == 0)
    check("dry-run made no model/log call", calls["model"] == 0)


def test_missing_credentials_fail_loud(monkeypatch=None) -> None:
    import os
    saved = {k: os.environ.pop(k, None)
             for k in ("IMAP_USER", "IMAP_APP_PASSWORD")}
    try:
        sg._require_credentials()
        raised = False
    except SystemExit as exc:
        raised = True
        msg = str(exc)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    check("unset credentials -> SystemExit", raised)
    if raised:
        check("error message names the missing vars + App Password",
              "IMAP_USER" in msg and "App Password" in msg, msg)


# ------------------------------------------------------------------ review-fix tests

def _run_process_with_stub(raws, live_stub, dry_run=False, results_dir=None):
    """Call sg._process with live_run_and_log and runner.RESULTS_DIR temporarily
    swapped, restoring both afterwards. Returns the counts dict."""
    orig_live = sg.live_run_and_log
    orig_results = runner.RESULTS_DIR
    sg.live_run_and_log = live_stub
    if results_dir is not None:
        runner.RESULTS_DIR = Path(results_dir)
    try:
        return sg._process(list(raws), dry_run=dry_run, max_body_chars=4000)
    finally:
        sg.live_run_and_log = orig_live
        runner.RESULTS_DIR = orig_results


def test_empty_body_skipped_not_logged() -> None:
    """FIX 1: an empty-body message must be skipped + counted separately, never run
    through the model nor counted as a clean logged result."""
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("model must NOT run on an empty-body message")

    with tempfile.TemporaryDirectory() as td:
        c = _run_process_with_stub([_empty_body()], _boom, results_dir=td)
    check("empty-body: model never called", calls["n"] == 0)
    check("empty-body: counted as skipped_empty", c["skipped_empty"] == 1, str(c))
    check("empty-body: NOT counted as logged", c["logged"] == 0, str(c))


def test_mailbox_crlf_rejected_before_network() -> None:
    """FIX 2: a mailbox carrying CR/LF (IMAP command injection) is rejected fail-loud
    inside fetch_recent_raw BEFORE any credential/network use."""
    raised = False
    try:
        sg.fetch_recent_raw(count=5, mailbox="INBOX\r\nA001 DELETE evil")
    except SystemExit:
        raised = True
    check("mailbox with CRLF -> SystemExit (no network reached)", raised)
    # Direct validator: CRLF and out-of-allowlist chars rejected, INBOX accepted.
    for bad in ("INBOX\r\nX", "INBOX\nX", "IN;BOX", "IN\tBOX", "IN*BOX"):
        rej = False
        try:
            sg._validate_mailbox(bad)
        except SystemExit:
            rej = True
        check(f"validator rejects {bad!r}", rej)
    ok = True
    try:
        sg._validate_mailbox("INBOX")
        sg._validate_mailbox("Archive/2024")
    except SystemExit:
        ok = False
    check("validator accepts INBOX and Archive/2024", ok)


def test_mailbox_gmail_system_folders_reachable() -> None:
    """Every Gmail system folder is namespaced "[Gmail]/…" and localized per account,
    so a bracket-less allowlist made --mailbox unable to reach Sent / All Mail / Drafts
    on ANY Gmail account. Brackets are now allowed; CR/LF stays the injection barrier.

    Both directions: the widened class ACCEPTS the real folder names, and still REJECTS
    a bracketed name carrying CR/LF (the combination widening could have opened up)."""
    # Direction 1 — real Gmail system folders, incl. the localized ones observed on a
    # live Spanish-locale account (2026-07-28: "[Gmail]/Enviados" holds the sent mail).
    for good in ("[Gmail]/Enviados", "[Gmail]/Sent Mail", "[Gmail]/All Mail",
                 "[Gmail]/Todos", "[Gmail]/Borradores", "[Gmail]"):
        ok = True
        try:
            sg._validate_mailbox(good)
        except SystemExit:
            ok = False
        check(f"validator accepts Gmail system folder {good!r}", ok)

    # Direction 2 — brackets must NOT become a hole: CR/LF still rejected when the
    # payload is wrapped in the newly-allowed characters.
    for bad in ("[Gmail]/Enviados\r\nA001 DELETE evil",
                "[Gmail]\nA001 EXPUNGE",
                "[Gmail]/Sent;DROP"):
        rej = False
        try:
            sg._validate_mailbox(bad)
        except SystemExit:
            rej = True
        check(f"validator still rejects {bad!r}", rej)

    # And the pre-network guard still fires for a bracketed injection attempt.
    raised = False
    try:
        sg.fetch_recent_raw(count=5, mailbox="[Gmail]/Enviados\r\nA001 DELETE evil")
    except SystemExit:
        raised = True
    check("bracketed CRLF mailbox -> SystemExit before any network", raised)


def test_mailbox_with_space_is_quoted_on_the_wire() -> None:
    """Passing validation is NOT the same as being reachable. imaplib.select()
    interpolates the mailbox into the protocol line UNQUOTED, so a name containing a
    space arrives as two arguments and the server answers BAD Could not parse command.

    Observed live 2026-07-28: --mailbox "Proposal Sent" crashed with
    `imaplib.IMAP4.error: EXAMINE command error: BAD [b'Could not parse command']`.
    PRE-EXISTING (space was already in the old allowlist), but it makes the localized
    English Gmail sent folder — "[Gmail]/Sent Mail" — unreachable, which is the single
    most common account. select() must receive the name QUOTED."""
    sent: list[str] = []

    class _FakeConn:
        def login(self, u, p): pass
        def select(self, mailbox, readonly=False):
            sent.append(mailbox)
            return "OK", [b""]
        def search(self, *a): return "OK", [b""]
        def fetch(self, *a): return "NO", None
        def close(self): pass
        def logout(self): pass

    import imaplib
    real_ssl, real_creds = imaplib.IMAP4_SSL, sg._require_credentials
    imaplib.IMAP4_SSL = lambda *a, **k: _FakeConn()
    sg._require_credentials = lambda: ("h", "u", "p")
    try:
        for box in ("[Gmail]/Sent Mail", "Proposal Sent", "INBOX"):
            sent.clear()
            sg.fetch_recent_raw(count=1, mailbox=box)
            check(f"select() received {box!r} QUOTED (was unquoted -> BAD)",
                  sent == [f'"{box}"'], f"got {sent!r}")
    finally:
        imaplib.IMAP4_SSL, sg._require_credentials = real_ssl, real_creds


def test_count_zero_and_negative_rejected() -> None:
    """FIX 4: --count must be > 0 (0 would falsily fetch ALL; negatives nonsensical)."""
    for tp in ("0", "-3"):
        raised = False
        try:
            sg.main(["--count", tp])
        except SystemExit as exc:
            raised = exc.code != 0  # argparse exits 2 on a bad argument
        check(f"--count {tp} rejected at argparse", raised)
    check("_positive_int('5') == 5", sg._positive_int("5") == 5)
    for bad in ("0", "-1", "abc"):
        import argparse as _ap
        rej = False
        try:
            sg._positive_int(bad)
        except _ap.ArgumentTypeError:
            rej = True
        check(f"_positive_int({bad!r}) raises", rej)


def test_model_failure_mid_batch_continues() -> None:
    """FIX 3: an exception from the model call on one message is caught, counted as
    failed, and the batch continues to the next message."""
    seq = {"i": 0}

    def _flaky(agent, text, extra=None):
        seq["i"] += 1
        if seq["i"] == 1:
            raise RuntimeError("simulated model/backend blowup")
        return _ok_record()

    with tempfile.TemporaryDirectory() as td:
        c = _run_process_with_stub([_plain(), _plain2()], _flaky, results_dir=td)
    check("mid-batch failure: model called for BOTH messages", seq["i"] == 2, str(seq))
    check("mid-batch failure: one counted failed", c["failed"] == 1, str(c))
    check("mid-batch failure: the other still logged", c["logged"] == 1, str(c))


def test_dedup_skips_already_logged() -> None:
    """FIX 5: a message whose message_id is already in the live log is skipped as a
    duplicate and never re-run through the model."""
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("dup message must NOT be re-run through the model")

    with tempfile.TemporaryDirectory() as td:
        live = Path(td) / "live"
        live.mkdir(parents=True)
        # _plain()'s Message-ID is <plain-1@janssens-bakery.com>.
        (live / "email-triage.jsonl").write_text(
            json.dumps({"message_id": "<plain-1@janssens-bakery.com>",
                        "input": "x", "output": {"label": "ignore"}}) + "\n"
            + "not-json-partial-line-should-be-ignored\n")
        c = _run_process_with_stub([_plain()], _boom, results_dir=td)
    check("dedup: model never called for the already-logged id", calls["n"] == 0)
    check("dedup: counted as skipped_dup", c["skipped_dup"] == 1, str(c))
    check("dedup: NOT counted as logged", c["logged"] == 0, str(c))


def test_missing_or_blank_label_still_logs_with_warning() -> None:
    """FIX 7: a model output with an absent OR falsy (empty-string) label must still
    count as logged (the raw output is in the jsonl) — the console just warns."""
    def _no_label(agent, text, extra=None):
        return {"logged": True}, {"output": {}, "metrics": {}}

    def _blank_label(agent, text, extra=None):
        return {"logged": True}, {"output": {"label": ""}, "metrics": {}}

    for name, stub in (("absent label", _no_label), ("blank label", _blank_label)):
        with tempfile.TemporaryDirectory() as td:
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                c = _run_process_with_stub([_plain()], stub, results_dir=td)
        check(f"{name}: still counted logged", c["logged"] == 1, str(c))
        check(f"{name}: a visible warning was printed",
              "no label" in buf.getvalue().lower(), buf.getvalue())


def test_summary_line_format() -> None:
    """The end-of-run summary reports the full breakdown so a low-capture run is
    visibly not 'all healthy'."""
    with tempfile.TemporaryDirectory() as td:
        orig_fetch = sg.fetch_recent_raw
        orig_live = sg.live_run_and_log
        orig_results = runner.RESULTS_DIR
        sg.fetch_recent_raw = lambda count, mailbox: [_plain()]
        sg.live_run_and_log = lambda agent, text, extra=None: _ok_record()
        runner.RESULTS_DIR = Path(td)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = sg.run(count=1, mailbox="INBOX", dry_run=False,
                            max_body_chars=4000)
        finally:
            sg.fetch_recent_raw = orig_fetch
            sg.live_run_and_log = orig_live
            runner.RESULTS_DIR = orig_results
    out = buf.getvalue()
    check("summary run returns 0", rc == 0)
    check("summary has the full breakdown format",
          "fetched 1 | logged 1 | skipped_empty 0 | skipped_dup 0 | "
          "parse_skip 0 | failed 0" in out, out)


# ------------------------------------------------------------------ e2e (optional)

def _ollama_up() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def test_end_to_end_through_real_model() -> None:
    """ONE real run: hardcoded sample email -> email-triage -> valid label + logged
    line. Uses a temp results dir so the test never pollutes the real live log.
    Skipped (not failed) if Ollama is unreachable."""
    if not _ollama_up():
        print("  [SKIP] end-to-end: Ollama not reachable at localhost:11434")
        return
    from runner import live_run_and_log
    import runner
    sample = sg.parse_message(_plain(), max_body_chars=4000)
    with tempfile.TemporaryDirectory() as td:
        orig_results = runner.RESULTS_DIR
        runner.RESULTS_DIR = Path(td)
        try:
            extra = {"from": sample["from"], "subject": sample["subject"],
                     "message_id": sample["message_id"], "source": "shadow_gmail"}
            entry, record = live_run_and_log("email-triage", sample["input"],
                                             extra=extra)
        finally:
            runner.RESULTS_DIR = orig_results
        label = (record.get("output") or {}).get("label")
        check("e2e: produced a valid triage label",
              label in ("reply_now", "reply_later", "ignore"), repr(label))
        # Schema: reused path wrote the SAME keys as runner.live + our extra fields.
        for key in ("ts", "model", "provider", "input", "output", "metrics"):
            check(f"e2e: logged entry has '{key}'", key in entry)
        for key in ("from", "subject", "message_id", "source"):
            check(f"e2e: logged entry carries provenance '{key}'", key in entry)
        log_file = Path(td) / "live" / "email-triage.jsonl"
        check("e2e: appended exactly one JSONL line to the temp live log",
              log_file.exists() and len(log_file.read_text().splitlines()) == 1)


# ------------------------------------------------------------------ runner

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
