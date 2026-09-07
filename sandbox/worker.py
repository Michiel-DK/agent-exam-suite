#!/usr/bin/env python3
"""Shadow-mode inbox digest — lane 0 (`docs/worker-brief-2026-09-06.md`).

    python3 sandbox/runner.py worker run --count N [--mailbox INBOX] [--dry-run]
    python3 sandbox/runner.py worker digest [--date YYYY-MM-DD] [--out PATH] [--sample-rate 0.10]

`run` fetches the newest N messages read-only (via `shadow_gmail.fetch_recent_raw` —
this module NEVER opens a mail connection of its own) and triages each directly through
`email-triage` (v1 deviation from the 5 Sep plan text: NOT through `task-intake`, which
emits `{agent, input}` only — no label, no `checks_failed` — and drops `message_id` from
the logged line, which breaks the rerun dedup guard; see the PR body). `digest` renders a
markdown "needs-you" queue from the accumulated `results/live/email-triage.jsonl` so a
human can review the model's decisions and `promote` the wrong ones into exam cases.

Read-only end to end: every mailbox read goes through `shadow_gmail.fetch_recent_raw`
(select(readonly=True) + BODY.PEEK[]). This module contains no `imaplib`/`smtplib`
import and makes no `conn.*` call of its own — grep it.

Reuses, unmodified: `shadow_gmail.fetch_recent_raw`, `shadow_gmail.parse_message`,
`shadow_gmail._load_logged_message_ids`, `shadow_gmail._positive_int`, and
`runner.live_run_and_log` (the single write path for `results/live/*.jsonl`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402  (the shared run+log path; RESULTS_DIR read dynamically)
import shadow_gmail as sg  # noqa: E402  (fetch_recent_raw, parse_message, dedup — reused as-is)

AGENT = "email-triage"
VALID_LABELS = {"reply_now", "reply_later", "ignore"}
IN_SCOPE_SOURCES = {"worker", "shadow_gmail"}


# ------------------------------------------------------------------ run

def _process(raws: list[bytes], dry_run: bool, max_body_chars: int) -> dict:
    """Triage each fetched message, returning the six-counter tally dict (fetched is
    len(raws), added by the caller). One bad message never aborts the batch.

    A message whose triage raises `runner.TerminationError` is counted as `logged`,
    not `failed`: `runner.live_run_and_log` writes the JSONL line BEFORE it raises
    (see its docstring, "After the write, never before"), so the line already exists —
    counting it `failed` would say a line was never written when one was. Only a
    non-Termination exception (no line written) counts as `failed`.
    """
    counts = {"logged": 0, "skipped_dup": 0, "skipped_empty": 0,
              "parse_skip": 0, "failed": 0}
    seen_ids = sg._load_logged_message_ids()
    for i, raw in enumerate(raws, 1):
        try:
            parsed = sg.parse_message(raw, max_body_chars)
        except Exception as exc:  # never let one bad MIME message abort the run
            print(f"  [{i}] warning: unparseable message skipped: {exc}",
                  file=sys.stderr)
            counts["parse_skip"] += 1
            continue
        if not parsed["body"].strip():
            print(f"  [{i}] warning: empty body — skipped (NOT triaged): "
                  f"from={parsed['from']!r} subject={parsed['subject']!r}",
                  file=sys.stderr)
            counts["skipped_empty"] += 1
            continue
        mid = parsed["message_id"]
        if mid and mid in seen_ids:
            print(f"  [{i}] already logged (message_id={mid!r}) — skipped")
            counts["skipped_dup"] += 1
            continue
        if dry_run:
            print(f"  [{i}] from={parsed['from']!r} subject={parsed['subject']!r}  "
                  f"(dry-run: would triage, no model call, no log write)")
            counts["logged"] += 1
            if mid:
                seen_ids.add(mid)
            continue
        extra = {"from": parsed["from"], "subject": parsed["subject"],
                 "message_id": mid, "source": "worker"}
        try:
            _entry, record = runner.live_run_and_log(AGENT, parsed["input"], extra=extra)
        except runner.TerminationError as exc:
            print(f"  [{i}] warning: {AGENT} emitted no answer, but the line was "
                  f"logged before the raise: {exc}", file=sys.stderr)
            counts["logged"] += 1
        except Exception as exc:  # one model/log failure must not abort the batch
            print(f"  [{i}] warning: triage run failed — skipped: {exc}",
                  file=sys.stderr)
            counts["failed"] += 1
            continue
        else:
            label = (record.get("output") or {}).get("label")
            print(f"  [{i}] from={parsed['from']!r} subject={parsed['subject']!r}  "
                  f"-> {label or '(no label)'}")
            counts["logged"] += 1
        if mid:
            seen_ids.add(mid)
    return counts


def run(count: int, mailbox: str, dry_run: bool, max_body_chars: int) -> int:
    if dry_run:
        print(f"[dry-run] fetching {count} message(s) from {mailbox!r} "
              f"(read-only) — NO model call, NO log write")
    raws = sg.fetch_recent_raw(count, mailbox)  # read-only: select(readonly=True) + PEEK
    fetched = len(raws)
    print(f"fetched {fetched} message(s) from {mailbox!r} (read-only)")
    c = _process(raws, dry_run, max_body_chars)
    # The `logged` counter's underlying meaning never changes (it is always "not
    # skipped/failed"; the six-counter tally invariant, logged+skipped_dup+
    # skipped_empty+parse_skip+failed == fetched, holds in both modes) — only the
    # PRINTED word changes, so a dry-run line never reads as self-contradictory
    # ("logged N ... nothing logged" was the wrong build here, caught in review).
    label = "would-log" if dry_run else "logged"
    tail = " (nothing logged, no model called)" if dry_run \
        else f" -> results/live/{AGENT}.jsonl"
    print(f"fetched {fetched} | {label} {c['logged']} | skipped_dup {c['skipped_dup']} | "
          f"skipped_empty {c['skipped_empty']} | parse_skip {c['parse_skip']} | "
          f"failed {c['failed']}{tail}")
    return 0


def cmd_run(args) -> int:
    return run(args.count, args.mailbox, args.dry_run, args.max_body_chars)


# ------------------------------------------------------------------ digest

def _read_live_lines(path: Path) -> list[tuple[int, dict]]:
    """[(absolute 1-indexed line number, parsed record)] over `path`. Mirrors
    serve.py's `_live_payload` exactly (same enumerate(...,1) numbering, same
    {"_parse_error": ..., "_line": ...} shape for a corrupt line) so a digest row's
    line number is the SAME number `cmd_promote` reads (`lines[line-1]` over the
    whole raw file) — never a position in a filtered list. Missing file -> []."""
    if not path.exists():
        return []
    out: list[tuple[int, dict]] = []
    for lineno, raw_line in enumerate(path.read_text().splitlines(), 1):
        raw_line = raw_line.strip()
        if not raw_line:  # a trailing newline splits into a blank final element
            continue
        try:
            out.append((lineno, json.loads(raw_line)))
        except ValueError as exc:
            out.append((lineno, {"_parse_error": str(exc), "_line": lineno}))
    return out


def _record_date(rec: dict) -> str | None:
    ts = rec.get("ts")
    if not isinstance(ts, str) or len(ts) < 10:
        return None
    return ts[:10]


def _label_of(rec: dict) -> str | None:
    return (rec.get("output") or {}).get("label")


def _in_scope(rec: dict, date: str) -> bool:
    """A record counts toward date D's figures iff it is a real (non-parse-error)
    record, its `ts` falls on D, AND its `source` is one of the two live producers.
    A manual `runner.py live email-triage` line passes no `extra`, so it has no
    `source` key at all, and is excluded here exactly like an unrecognised source."""
    return ("_parse_error" not in rec and _record_date(rec) == date
            and rec.get("source") in IN_SCOPE_SOURCES)


def _is_flagged(rec: dict) -> bool:
    """checks_failed non-empty OR an off-vocabulary label. `live_output_checks` is
    structural-only for a `labels`-mode agent (declared gap in runner.py), so a live
    {"label": "URGENT"} passes live and exits 0 — this is the only place it gets
    caught. `reply_now` is needs-you but deliberately NOT flagged (brief, halt 2)."""
    return bool(rec.get("checks_failed")) or _label_of(rec) not in VALID_LABELS


def _sampled(message_id: str | None, rate: float) -> bool:
    """Deterministic across reruns: sha256(message_id), never `random` or builtin
    `hash()` (CLAUDE.md gotcha — builtin hash() is process-salted, not reproducible).
    A record with no message_id is never sampled (nothing to key the digest on)."""
    if not message_id:
        return False
    digest = hashlib.sha256(message_id.encode()).hexdigest()
    return int(digest, 16) % 100 < rate * 100


def _heldout_figure(snapshot: dict) -> str:
    cases = snapshot.get("cases") or []
    heldout = [c for c in cases if c.get("split") == "heldout"]
    total = len(heldout)
    if not total:
        return "n/a (no snapshot)"
    passed = sum(1 for c in heldout if c.get("passed"))
    score = snapshot.get("heldout_score")
    pct = f"{score * 100:.1f}%" if isinstance(score, (int, float)) else \
        f"{100.0 * passed / total:.1f}%"
    return f"{passed}/{total} ({pct})"


def _md(text: str | None) -> str:
    """Escape a field for a markdown table cell: no pipes, no embedded newlines."""
    return (text or "").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _truncate(text: str, n: int = 60) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1].rstrip() + "\u2026"


PROMOTE_TEMPLATE = ('python3 sandbox/runner.py promote email-triage <line> '
                    '--expected \'{"label": "..."}\'')


def render(records_with_lineno: list[tuple[int, dict]], date: str,
          snapshot: dict, rate: float) -> str:
    """Pure function of the log: markdown text, given already-read (lineno, record)
    pairs, the target date, the loaded email-triage snapshot dict, and the sample
    rate. No I/O — the CLI layer (`cmd_digest`) does all the reading and writing.

    Sections, in order: (1) scoreboard header — exam heldout, counts by label for
    D, flagged count for D, days running (any date); (2) needs-you table — every
    in-scope reply_now / flagged record, every _parse_error line (any date/source),
    then a sha256-deterministic sample of what's left, each row carrying the
    ABSOLUTE 1-indexed raw-file line number; the promote command once below the
    table; (3) silent — a count only, same source/date scope as the header.
    """
    scoped = [(ln, r) for ln, r in records_with_lineno if _in_scope(r, date)]
    parse_errors = [(ln, r) for ln, r in records_with_lineno if "_parse_error" in r]

    label_counts = Counter(_label_of(r) or "(none)" for _, r in scoped)

    # Flagged count (header figure): checks_failed/off-vocab records in scope for D,
    # PLUS every _parse_error line in the whole file — undated, never date/source
    # filtered (brief, halt 2: listed under flagged in EVERY digest until repaired).
    flagged_in_scope = [(ln, r) for ln, r in scoped if _is_flagged(r)]
    flagged_count = len(flagged_in_scope) + len(parse_errors)

    dates_seen = {_record_date(r) for _, r in records_with_lineno
                 if "_parse_error" not in r and r.get("source") in IN_SCOPE_SOURCES
                 and _record_date(r)}
    days_running = len(dates_seen)

    needs_you_lines = {ln for ln, _ in flagged_in_scope} | \
        {ln for ln, r in scoped if _label_of(r) == "reply_now"}
    needs_you_scoped = [(ln, r) for ln, r in scoped if ln in needs_you_lines]
    remaining = [(ln, r) for ln, r in scoped if ln not in needs_you_lines]
    sampled = [(ln, r) for ln, r in remaining
              if _sampled(r.get("message_id"), rate)]
    silent_count = len(remaining) - len(sampled)

    def reason_for(r: dict) -> str:
        if _label_of(r) == "reply_now":
            return "reply_now"
        if r.get("checks_failed"):
            return f"flagged: checks_failed={r['checks_failed']}"
        return f"flagged: off-vocab label {_label_of(r)!r}"

    rows: list[tuple[int, dict, str]] = []
    for ln, r in sorted(needs_you_scoped, key=lambda x: x[0]):
        rows.append((ln, r, reason_for(r)))
    for ln, r in sorted(parse_errors, key=lambda x: x[0]):
        rows.append((ln, r, f"parse_error: {r.get('_parse_error', '')}"))
    for ln, r in sorted(sampled, key=lambda x: x[0]):
        rows.append((ln, r, "sample"))

    out: list[str] = []
    out.append(f"# Inbox digest — {date}")
    out.append("")
    out.append(f"- email-triage heldout: {_heldout_figure(snapshot)}")
    if label_counts:
        counts_str = ", ".join(f"{k} {v}" for k, v in sorted(label_counts.items()))
    else:
        counts_str = "(no messages)"
    out.append(f"- counts by label ({date}): {counts_str}")
    out.append(f"- flagged ({date}): {flagged_count}")
    out.append(f"- days running: {days_running}")
    out.append("")
    out.append("## needs you")
    out.append("")
    out.append("| ts | from | subject | label | reason | line |")
    out.append("|---|---|---|---|---|---|")
    for ln, r, reason in rows:
        if "_parse_error" in r:
            out.append(f"| | | | | {_md(reason)} | {ln} |")
        else:
            out.append(
                f"| {_md(r.get('ts'))} | {_md(r.get('from'))} | "
                f"{_md(_truncate(r.get('subject') or ''))} | "
                f"{_md(_label_of(r))} | {_md(reason)} | {ln} |")
    out.append("")
    out.append(PROMOTE_TEMPLATE)
    out.append("")
    out.append("## silent")
    out.append("")
    out.append(f"{silent_count} message(s) needed no review.")
    out.append("")
    return "\n".join(out)


def cmd_digest(args) -> int:
    date = args.date or datetime.now().strftime("%Y-%m-%d")
    live_path = runner.RESULTS_DIR / "live" / f"{AGENT}.jsonl"
    records = _read_live_lines(live_path)
    snapshot_path = runner.ROOT / "evals" / AGENT / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text()) if snapshot_path.exists() else {}
    text = render(records, date, snapshot, args.sample_rate)
    out_path = Path(args.out) if args.out else \
        (runner.RESULTS_DIR / "worker" / f"digest-{date}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text)
    print(text)
    print(f"written -> {out_path}", file=sys.stderr)
    return 0


# ------------------------------------------------------------------ CLI

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="worker",
        description="Shadow-mode inbox digest for email-triage: fetch+triage "
                    "read-only mail (run), then render the daily needs-you "
                    "digest (digest). Read-only end to end.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("run", help="fetch N newest messages (read-only) and "
                                    "triage each via email-triage")
    sp.add_argument("--count", type=sg._positive_int, default=20,
                    help="number of most-recent messages to read (default 20)")
    sp.add_argument("--mailbox", default="INBOX")
    sp.add_argument("--dry-run", action="store_true",
                    help="fetch + parse + print only — no model call, no log write")
    sp.add_argument("--max-body-chars", type=int, default=4000)
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("digest", help="render the daily needs-you digest from "
                                       "results/live/email-triage.jsonl")
    sp.add_argument("--date", default=None,
                    help="YYYY-MM-DD (default: today)")
    sp.add_argument("--out", default=None,
                    help="output path (default: results/worker/digest-<date>.md)")
    sp.add_argument("--sample-rate", type=float, default=0.10,
                    help="fraction of the non-flagged remainder to sample into "
                         "needs-you, deterministically by message_id (default 0.10)")
    sp.set_defaults(fn=cmd_digest)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
