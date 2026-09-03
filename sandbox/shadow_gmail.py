#!/usr/bin/env python3
"""Read-only Gmail shadow logger — flywheel data collection, never a mutation.

    python3 sandbox/shadow_gmail.py [--count N] [--mailbox INBOX] [--dry-run]

Reads the most recent messages from a Gmail mailbox over IMAP, runs the existing
`email-triage` agent on each, and appends the result to results/live/email-triage.jsonl
via the SAME run+log path as `runner.py live` (runner.live_run_and_log). This is
"shadow mode": it builds training/flywheel data by observing a real inbox without ever
touching it.

============================  READ-ONLY INVARIANT  ============================
This tool NEVER sends, replies, deletes, marks-read, moves, or modifies the mailbox
in ANY way. Enforced mechanically, not by convention:
  * the mailbox is opened with select(mailbox, readonly=True) — the server rejects
    any state change on a read-only selection;
  * messages are fetched with BODY.PEEK[] (NOT BODY[], which would set the \\Seen
    flag), so reading a message does not even mark it read;
  * this module never calls store / \\Seen / expunge / copy / append / delete /
    mark — grep the source: those verbs appear only in this comment and in the
    test that asserts their absence.
Credentials are used for a single READ-ONLY IMAP session and nothing else.
==============================================================================

Config via environment (fails loud if user/password unset):
    IMAP_HOST          default imap.gmail.com
    IMAP_USER          the Gmail address
    IMAP_APP_PASSWORD  a Google App Password (NOT the account password)

Real email bodies are PII: results/ is gitignored, so the log never reaches git.
Stdlib only — imaplib, email, ssl, argparse. No pip dependencies.
"""
from __future__ import annotations

import argparse
import email
import json
import os
import re
import ssl
import sys
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402  (referenced dynamically so RESULTS_DIR monkeypatch takes)
from runner import live_run_and_log  # noqa: E402  (the shared run+log path)

AGENT = "email-triage"

# Mailbox names are interpolated into an IMAP protocol line by imaplib. An embedded
# CR/LF would split it into extra commands (injection); anything outside this
# conservative allowlist is rejected fail-loud. Default INBOX passes; an unusual
# folder failing loud is acceptable.
# Square brackets are allowed because EVERY Gmail system folder is namespaced
# "[Gmail]/…" — and localized per account ("[Gmail]/Enviados", "[Gmail]/Sent Mail").
# Without them --mailbox could reach only user-created labels, never Sent / All Mail /
# Drafts, on any Gmail account in any locale. Brackets are inert in IMAP: splitting one
# protocol line into two still requires CR/LF, which stays rejected above and is the
# load-bearing guard. This allowlist is defence-in-depth, not the injection barrier.
_MAILBOX_RE = re.compile(r"^[A-Za-z0-9_./ \[\]-]+$")


# ------------------------------------------------------------------ parsing

def decode_mime_header(raw: str | None) -> str:
    """Decode a possibly-encoded MIME header ('=?UTF-8?B?...?=') to plain text.

    Real Gmail headers arrive RFC 2047-encoded; the exam-format input string needs
    the human-readable value, not the raw encoded-word. Never raises on a malformed
    header — falls back to the raw string so one weird header can't crash a fetch.
    """
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except (ValueError, LookupError, UnicodeDecodeError):
        return raw


def _strip_html(html: str) -> str:
    """Minimal tag-strip for an HTML-only message: drop <script>/<style> bodies and
    all tags, unescape entities, collapse blank lines. Not a full renderer — enough
    to give the triage model readable text when there is no text/plain part."""
    import re
    from html import unescape
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</p\s*>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _decode_payload(part: Message) -> str:
    """Bytes payload of a single part, decoded with its declared charset (falling
    back to utf-8, then latin-1 which never raises). Returns "" if there is no
    payload, so a weird part degrades instead of crashing."""
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    for enc in (charset, "utf-8", "latin-1"):
        try:
            return payload.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def extract_body(msg: Message) -> str:
    """Plain-text body of an email. Prefers text/plain; if the message is HTML-only,
    strips the HTML. Walks multipart containers and skips attachments. Never raises."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            disp = str(part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain":
                plain_parts.append(_decode_payload(part))
            elif ctype == "text/html":
                html_parts.append(_decode_payload(part))
    else:
        ctype = msg.get_content_type()
        if ctype == "text/html":
            html_parts.append(_decode_payload(msg))
        else:
            plain_parts.append(_decode_payload(msg))

    if any(p.strip() for p in plain_parts):
        return "\n".join(p for p in plain_parts if p.strip()).strip()
    if any(p.strip() for p in html_parts):
        return _strip_html("\n".join(html_parts)).strip()
    return ""


def build_triage_input(sender: str, subject: str, body: str,
                       max_body_chars: int) -> str:
    """Construct the email-triage exam input string: 'From: ...\\nSubject: ...\\n\\n<body>'
    — byte-for-byte the shape of evals/email-triage/cases.json inputs. Long bodies are
    truncated to keep the prompt bounded."""
    body = body.strip()
    if len(body) > max_body_chars:
        body = body[:max_body_chars].rstrip() + "\n[...truncated]"
    return f"From: {sender}\nSubject: {subject}\n\n{body}"


def parse_message(raw_bytes: bytes, max_body_chars: int) -> dict:
    """Parse one raw RFC822 message into {from, subject, message_id, body, input}.

    Raises on a message that cannot be parsed at all; the caller skips+warns so one
    malformed message never aborts the whole run."""
    msg = email.message_from_bytes(raw_bytes)
    sender = decode_mime_header(msg.get("From"))
    subject = decode_mime_header(msg.get("Subject"))
    message_id = (msg.get("Message-ID") or "").strip()
    body = extract_body(msg)
    return {
        "from": sender,
        "subject": subject,
        "message_id": message_id,
        "body": body,
        "input": build_triage_input(sender, subject, body, max_body_chars),
    }


# ------------------------------------------------------------------ IMAP (read-only)

def _require_credentials() -> tuple[str, str, str]:
    host = os.environ.get("IMAP_HOST", "imap.gmail.com")
    user = os.environ.get("IMAP_USER")
    password = os.environ.get("IMAP_APP_PASSWORD")
    missing = [n for n, v in (("IMAP_USER", user),
                              ("IMAP_APP_PASSWORD", password)) if not v]
    if missing:
        sys.exit(
            f"error: missing required env var(s): {', '.join(missing)}.\n"
            f"  Set IMAP_USER to your Gmail address and IMAP_APP_PASSWORD to a Google\n"
            f"  App Password (https://myaccount.google.com/apppasswords), then retry.\n"
            f"  IMAP_HOST is optional (default imap.gmail.com). This tool is READ-ONLY\n"
            f"  and never modifies the mailbox.")
    return host, user, password


def _validate_mailbox(mailbox: str) -> None:
    """Reject a mailbox name that could inject extra IMAP protocol lines. Fails loud
    BEFORE any network call. The CR/LF check is the load-bearing security guard (an
    embedded newline becomes a second IMAP command via imaplib); the allowlist is
    defence-in-depth."""
    if "\r" in mailbox or "\n" in mailbox:
        sys.exit("error: --mailbox may not contain CR/LF "
                 "(would inject extra IMAP commands)")
    if not _MAILBOX_RE.match(mailbox):
        sys.exit(f"error: --mailbox {mailbox!r} has disallowed characters; allowed: "
                 f"letters, digits, and the set _ . / space -")


def _load_logged_message_ids() -> set[str]:
    """Set of message_ids already present in results/live/<agent>.jsonl, so a rerun
    (e.g. an unattended cron job) never re-triages the same email. Robust to a
    missing or partially-written file: an unreadable/corrupt line is skipped, not
    fatal. Reads runner.RESULTS_DIR dynamically so a monkeypatched dir is honoured."""
    path = runner.RESULTS_DIR / "live" / f"{AGENT}.jsonl"
    ids: set[str] = set()
    if not path.exists():
        return ids
    try:
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue  # partial/corrupt trailing line — stay robust
                mid = (obj.get("message_id") or "").strip()
                if mid:
                    ids.add(mid)
    except OSError as exc:
        print(f"  warning: could not read existing live log for dedup: {exc}",
              file=sys.stderr)
    return ids


def fetch_recent_raw(count: int, mailbox: str) -> list[bytes]:
    """Return the raw bytes of the `count` most-recent messages in `mailbox`.

    READ-ONLY: select(readonly=True) + BODY.PEEK[] (peek does not set \\Seen). imaplib
    is imported lazily so --dry-run and all unit tests never touch the network."""
    _validate_mailbox(mailbox)  # fail loud before opening any connection
    import imaplib
    host, user, password = _require_credentials()
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(host, ssl_context=ctx)
    try:
        conn.login(user, password)
        # readonly=True: the server refuses any state-changing command on this
        # selection — the primary read-only guard.
        # QUOTE the mailbox: imaplib.select() interpolates the name into the protocol
        # line WITHOUT quoting, so any name containing a space ("[Gmail]/Sent Mail",
        # "Proposal Sent") arrives as two arguments -> BAD Could not parse command.
        # Safe: _validate_mailbox has already rejected CR/LF, and neither " nor \ is in
        # the allowlist, so the name cannot terminate or escape out of this quoted string.
        typ, _ = conn.select(f'"{mailbox}"', readonly=True)
        if typ != "OK":
            sys.exit(f"error: could not select mailbox {mailbox!r} (read-only): {typ}")
        typ, data = conn.search(None, "ALL")
        if typ != "OK":
            sys.exit(f"error: IMAP search failed: {typ}")
        # search returns message ids as bytes (b"1 2 3"); decode to str so fetch gets
        # a plain ASCII id regardless of imaplib version tolerance.
        ids = [i.decode() if isinstance(i, bytes) else i for i in data[0].split()]
        recent = ids[-count:] if count and count < len(ids) else ids
        raws: list[bytes] = []
        for msg_id in reversed(recent):  # newest first
            # BODY.PEEK[] fetches the full message WITHOUT setting \\Seen. Using
            # BODY[] here would mark the message read — a mailbox mutation. Do not
            # change this to BODY[].
            typ, msg_data = conn.fetch(msg_id, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                print(f"  warning: could not fetch message id {msg_id!r}, skipping",
                      file=sys.stderr)
                continue
            raws.append(msg_data[0][1])
        return raws
    finally:
        # close() on a readonly selection performs no expunge; logout ends the session.
        try:
            conn.close()
        except Exception as exc:  # non-fatal, but surface it instead of swallowing
            print(f"  warning: IMAP close() failed (session still logged out): {exc}",
                  file=sys.stderr)
        conn.logout()


# ------------------------------------------------------------------ CLI

def _summary(parsed: dict) -> str:
    from_ = parsed["from"] or "(no sender)"
    subject = parsed["subject"] or "(no subject)"
    return f"    from={from_!r}  subject={subject!r}"


def _process(raws: list[bytes], dry_run: bool, max_body_chars: int) -> dict:
    """Triage each fetched message, returning a tally dict. One bad message never
    aborts the batch: a parse failure, an empty body, a duplicate, and a model-call
    failure are each caught, logged per-item, counted, and skipped. Only a message
    that runs the model and logs cleanly counts as `logged`.

    Kept separate from run() so the numeric tallies are directly unit-testable while
    run() keeps returning int 0 (its callers rely on that)."""
    counts = {"logged": 0, "previewed": 0, "skipped_empty": 0,
              "skipped_dup": 0, "parse_skip": 0, "failed": 0}
    seen_ids = _load_logged_message_ids()
    for i, raw in enumerate(raws, 1):
        try:
            parsed = parse_message(raw, max_body_chars)
        except Exception as exc:  # never let one bad MIME message abort the run
            print(f"  [{i}] warning: unparseable message skipped: {exc}",
                  file=sys.stderr)
            counts["parse_skip"] += 1
            continue
        # Empty-body guard: an attachment-only message, calendar invite, or read
        # receipt has no body to triage. Running the model on sender+subject alone
        # would log a spurious "clean" verdict, so skip it visibly and count it
        # separately — it is NOT an ok/logged result.
        if not parsed["body"].strip():
            print(f"  [{i}] warning: empty body — skipped (NOT triaged):"
                  f"{_summary(parsed)}", file=sys.stderr)
            counts["skipped_empty"] += 1
            continue
        # Dedup: never re-triage a message already in the live log (protects an
        # unattended rerun from double-logging). Guard against ids seen earlier in
        # THIS batch too.
        mid = parsed["message_id"]
        if mid and mid in seen_ids:
            print(f"  [{i}] already logged (message_id={mid!r}) — skipped")
            counts["skipped_dup"] += 1
            continue
        if dry_run:
            print(f"  [{i}]{_summary(parsed)}")
            print(f"        input: {parsed['input'][:200]!r}"
                  + (" ..." if len(parsed["input"]) > 200 else ""))
            counts["previewed"] += 1
            if mid:
                seen_ids.add(mid)
            continue
        extra = {"from": parsed["from"], "subject": parsed["subject"],
                 "message_id": parsed["message_id"], "source": "shadow_gmail"}
        try:
            _entry, record = live_run_and_log(AGENT, parsed["input"], extra=extra)
        except Exception as exc:  # one model/log failure must not abort the batch
            print(f"  [{i}] warning: triage run failed — skipped: {exc}",
                  file=sys.stderr)
            counts["failed"] += 1
            continue
        label = (record.get("output") or {}).get("label")
        if label:
            print(f"  [{i}]{_summary(parsed)}  ->  {label}")
        else:
            # Raw output is still in the jsonl; make the missing label visible.
            print(f"  [{i}]{_summary(parsed)}  ->  WARNING: model output had no "
                  f"label (raw output logged)", file=sys.stderr)
        counts["logged"] += 1
        if mid:
            seen_ids.add(mid)
    return counts


def run(count: int, mailbox: str, dry_run: bool, max_body_chars: int) -> int:
    if dry_run:
        print(f"[dry-run] fetching {count} message(s) from {mailbox!r} "
              f"(read-only) — NO model call, NO log write")
    raws = fetch_recent_raw(count, mailbox)
    fetched = len(raws)
    print(f"fetched {fetched} message(s) from {mailbox!r} (read-only)")
    c = _process(raws, dry_run, max_body_chars)
    if dry_run:
        print(f"[dry-run] fetched {fetched} | would-log {c['previewed']} | "
              f"skipped_empty {c['skipped_empty']} | skipped_dup {c['skipped_dup']} | "
              f"parse_skip {c['parse_skip']}  (nothing logged, no model called)")
    else:
        print(f"fetched {fetched} | logged {c['logged']} | "
              f"skipped_empty {c['skipped_empty']} | skipped_dup {c['skipped_dup']} | "
              f"parse_skip {c['parse_skip']} | failed {c['failed']} "
              f"-> results/live/{AGENT}.jsonl")
    return 0


def _positive_int(raw: str) -> int:
    """argparse type: a strictly-positive int. --count 0 would otherwise be falsy and
    silently fetch the ENTIRE mailbox; negatives are nonsensical."""
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {raw!r}")
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {value}")
    return value


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Read-only Gmail shadow logger for the email-triage agent. "
                    "Never modifies the mailbox.")
    p.add_argument("--count", type=_positive_int, default=20,
                   help="number of most-recent messages to read (default 20, must be > 0)")
    p.add_argument("--mailbox", default="INBOX",
                   help="mailbox to read (default INBOX)")
    p.add_argument("--dry-run", action="store_true",
                   help="fetch + parse + print only — no model call, no log write "
                        "(safe to run against a real inbox to preview)")
    p.add_argument("--max-body-chars", type=int, default=4000,
                   help="truncate email bodies longer than this (default 4000)")
    args = p.parse_args(argv)
    return run(args.count, args.mailbox, args.dry_run, args.max_body_chars)


if __name__ == "__main__":
    sys.exit(main())
