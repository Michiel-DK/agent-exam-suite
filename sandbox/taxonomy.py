#!/usr/bin/env python3
"""E9 failure taxonomy: roll `results/` failures up into model x category counts.

    python3 sandbox/runner.py taxonomy [--agent X] [--by-agent] [--json]
    python3 sandbox/taxonomy.py        [--agent X] [--by-agent] [--json]

The question this answers, which no other command can: "this model fails 80% on
tool-selection and 0% on output format" — i.e. *why* a model fails, not just *that*
it does. That is E12's routing input.

Contract (each line is a constraint the tests pin):

* **Read-only and offline.** Loads `results/*.json`, calls no model, writes nothing.
  Two runs over the same directory print byte-identical output. It is a REPORT, not
  a gate — deliberately absent from `check-all`, and it moves no score.
* **No silent buckets.** A recorded failure that matches no rule is surfaced under
  `unclassified` with its raw string and its (model, agent, case) — never dropped,
  and never folded into a catch-all `other`. The count prints even when zero.
* **No invented reasons.** A failing case that recorded *no* failure evidence at all
  (old labels/fields results predate `failed_checks`) is reported as
  `no-recorded-reason`. It is not guessed at from `expected`/`got`.
* **Fail loud.** An unreadable or shape-violating results file raises; it is never
  skipped, because a silently skipped file understates every count in the report.
* **Both results shapes.** Old files carry `cases[].failures` (strings); newer ones
  also carry `cases[].failed_checks` ({bucket, check} dicts, C5(a)/D6). Where a case
  carries both, each failure is counted ONCE (see `case_findings`).

Categories are keyed on the stable check id, not on prose: the string -> check-id
table lives in `runner._TRAJECTORY_FAILURE_CHECKS` and is imported, never forked
(a second copy of a normalization table has drifted here before — CLAUDE.md).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"


def trajectory_prefixes() -> tuple:
    """The string -> check-id table, imported from runner at CALL time.

    Deferred on purpose: runner.py imports this module at top level (to hang the
    `taxonomy` subcommand off it), so a top-level import back would be a cycle. The
    table is imported rather than copied — a second copy of a matching table has
    drifted and shipped a bug here twice (CLAUDE.md, `_norm_digits`).
    """
    from runner import _TRAJECTORY_FAILURE_CHECKS
    return _TRAJECTORY_FAILURE_CHECKS


UNCLASSIFIED = "unclassified"
NO_RECORDED_REASON = "no-recorded-reason"

# A property check's failure string is "<fn_name>: <msg>" (runner.run_properties).
_PROPERTY_RE = re.compile(r"^(check_[A-Za-z0-9_]+): ")
# A judge failure is "judge:<criterion>: <reason>"; runner._judge_check_id keeps the
# head as the check id, so the same id appears in both shapes. Judges were dropped
# from the suite (PR #18) — old results still carry them, so the rule stays.
_JUDGE_PREFIX = "judge:"

# check id -> category. Every check id the current code can emit appears here; a new
# check that lands in `unclassified` is telling you this table needs a line, which is
# the loud failure mode we want (never a silent `other`).
CATEGORY_BY_CHECK: dict[str, str] = {
    # --- tool use
    "tools_called": "tool-selection",
    "tools_not_called": "tool-selection",
    "tools_allowed": "tool-selection",
    "redundancy": "tool-efficiency",
    "max_steps": "step-budget",
    # --- grounding / honesty
    "grounded_answer": "fabrication",
    "check_no_invented_numbers": "fabrication",
    "check_no_invented_dates": "fabrication",
    "error_recovery": "error-recovery",
    # --- answer substance
    "answer_contains": "answer-content",
    "answer_contains_any": "answer-content",
    # a forbidden string present = a decoy's detail attributed to the right entity;
    # the capability that failed is grounding, not content coverage
    "answer_not_contains": "fabrication",
    "labels": "label-mismatch",
    "fields": "label-mismatch",
    "answer_present": "no-answer",
    "check_has_reply": "no-answer",
    # --- style / language
    "check_signoff": "house-style",
    "check_word_limit": "house-style",
    "check_language_match": "language-drift",
    # --- summarisation (E13 recap). Deliberately mapped onto EXISTING categories where
    # the failure is the same capability wearing a new costume, so E12's routing input
    # does not fragment into per-exam buckets:
    #   check_grounded    invents a number  -> the same failure as check_no_invented_*
    #   check_coverage    omits a required item -> answer-content, like answer_contains
    #   check_output_shape malformed JSON   -> no-answer; nothing gradable came back
    # Two are genuinely NEW capabilities with no existing home:
    #   compression  — "a summary the length of its source has not summarised" is not a
    #                  house-style miss; it is a failure to perform the task at all.
    #   over-significance — reporting a quiet day as needing attention. The INVERSE of
    #                  fabrication-of-content: nothing is invented factually, yet the
    #                  recap asserts an importance the source does not support. This is
    #                  E19's core diary failure (inventing significance = inventing a
    #                  memory), so it gets its own row rather than hiding inside
    #                  "fabrication".
    "check_grounded": "fabrication",
    "check_coverage": "answer-content",
    "check_output_shape": "no-answer",
    "check_compression": "compression",
    "check_abstention": "over-significance",
    # --- dispatch (A4 task-intake, 2026-09-04). The label half is `labels` above; the
    # hand-over half maps onto existing capabilities: a paraphrased / invented / fixed-up
    # hand-over is fabrication (the material was not the request's), a roster miss is
    # a label mismatch, and 'none' with material attached (or a specialist with none)
    # is the dispatcher not performing the task — filed with compression's "did not
    # perform" reading rather than a new row.
    "check_agent_in_roster": "label-mismatch",
    "check_input_is_verbatim_span": "fabrication",
    "check_none_hands_over_nothing": "compression",
    # check_action_items (transcript-en, S-TRANSCRIPT-EN-EXAM): a PRESENCE check on
    # required content, exactly like check_coverage above — it is the same failure
    # (a required item is missing) wearing a new costume, just scoped to the
    # `action_items` field instead of `summary` (evals/transcript-en/properties.py's
    # own directionality-rule comment states the two are deliberately parallel).
    # Not a new capability, so it gets no new row of its own — folded into the
    # existing "answer-content" category rather than fragmenting E12's routing
    # input per-exam (same reasoning the recap block above states for
    # check_coverage/check_grounded).
    "check_action_items": "answer-content",
    # check_action_owner / check_withdrawn_excluded (transcript-en lane 1,
    # 2026-09-06, the long-call band): check_action_owner mis-attributes a
    # commitment to the wrong side (rep vs customer) — a label mismatch on the
    # action item's owner, the same failure shape as `labels`/`fields` above,
    # so it gets no new row. check_withdrawn_excluded is an ABSENCE check
    # (a withdrawn proposal resurfacing as a commitment) — the same failure as
    # `answer_not_contains` above: material attributed to the call that the
    # call itself retracted, filed as fabrication rather than a new category.
    "check_action_owner": "label-mismatch",
    "check_withdrawn_excluded": "fabrication",
    # --- infrastructure, not capability
    "error": "harness-error",
}

# Refinements split ONE check id by the literal prefix of its failure string, and
# only apply when the raw string was recorded. `error_recovery` emits four distinct
# messages (outage-never-occurred, spiral, no-acknowledgement, ungrounded name); only
# the last is fabrication, and fabrication-under-tool-failure is the signature E12
# routes on (docs/model-notes.md, llama3.1 "Karen Brown"). A dict-only record keeps
# the coarse category — trajectory results always record strings too, so in practice
# this costs nothing; the report says which source each finding came from.
STRING_REFINEMENTS: tuple[tuple[str, str, str], ...] = (
    ("error_recovery", "error_recovery: ungrounded name ", "fabrication-on-tool-error"),
)

# Declared so the coverage table can print a ZERO-OBSERVED row for a category the
# corpus never exercised — a category asserted in code but never seen in data is the
# failure mode that round-tripped E10 twice (CLAUDE.md).
CAPABILITY_CATEGORIES: tuple[str, ...] = tuple(sorted(
    set(CATEGORY_BY_CHECK.values()) | {c for _, _, c in STRING_REFINEMENTS}
    | {"judge-verdict"}
))
# The two meta categories are not capability findings: they record what the corpus
# could NOT tell us. They are reported separately and prominently, never merged into
# a capability bucket.
ALL_CATEGORIES: tuple[str, ...] = tuple(sorted(
    CAPABILITY_CATEGORIES + (UNCLASSIFIED, NO_RECORDED_REASON)))


class Finding(NamedTuple):
    """One recorded failure, classified. `raw` is None when the only record was a
    `failed_checks` dict (labels/fields/error cases emit no failure string).

    `file` is carried because (agent, model, case) is NOT unique across the corpus:
    results predating the provider-in-filename fix sit alongside their reruns, and
    two identical-looking rows in the unclassified list would be untraceable.
    """
    agent: str
    provider: str
    model: str
    case_id: str
    split: str
    category: str
    check: str | None
    raw: str | None
    source: str  # "failures" | "failed_checks" | "none"
    file: str


# ---------------------------------------------------------------- classification

def check_id_for(failure: str, prefixes: tuple | None = None) -> str | None:
    """Failure string -> stable check id, or None if no rule matches.

    Unlike runner._trajectory_check_id (which raises, because a mis-binned check
    would corrupt a committed snapshot) this returns None: a reporting tool must
    show the unknown string, not abort the whole report over one line.

    NOTE this is a PRESENCE matcher over raw strings and does no normalization at
    all. Do not reuse it for any absence check (CLAUDE.md: normalization is
    directional; a shared helper has shipped that bug here twice).
    """
    prefixes = trajectory_prefixes() if prefixes is None else prefixes
    for prefix, check_id in prefixes:
        if failure.startswith(prefix):
            return check_id
    if failure.startswith(_JUDGE_PREFIX):
        return failure.split(": ", 1)[0]
    m = _PROPERTY_RE.match(failure)
    return m.group(1) if m else None


def category_for(check_id: str | None, raw: str | None = None,
                 categories: dict | None = None,
                 refinements: tuple | None = None) -> str:
    """check id (+ optional raw string) -> category, or UNCLASSIFIED.

    The tables are injectable so a test can delete one rule and prove that rule —
    not something else — is what produces the classification.
    """
    categories = CATEGORY_BY_CHECK if categories is None else categories
    refinements = STRING_REFINEMENTS if refinements is None else refinements
    if check_id is None:
        return UNCLASSIFIED
    if raw is not None:
        for ref_check, prefix, category in refinements:
            if check_id == ref_check and raw.startswith(prefix):
                return category
    if check_id in categories:
        return categories[check_id]
    if check_id.startswith(_JUDGE_PREFIX):
        return "judge-verdict"
    return UNCLASSIFIED


# ---------------------------------------------------------------- loading

def load_result_file(path: Path) -> dict:
    """Parse one results file, or raise. Never returns a partial/empty stand-in:
    a skipped file would silently understate every count in the report."""
    try:
        data = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable results file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"malformed results file {path}: top level is "
                         f"{type(data).__name__}, expected object")
    missing = [k for k in ("agent", "model", "cases") if k not in data]
    if missing:
        raise ValueError(f"malformed results file {path}: missing {missing}")
    if not isinstance(data["cases"], list):
        raise ValueError(f"malformed results file {path}: 'cases' is not a list")
    return data


def find_result_files(results_dir: Path) -> list[Path]:
    """Top-level *.json only, sorted. `results/live/` holds shadow-run JSONL traces
    (a different schema, no pass/fail verdicts) and is deliberately out of scope."""
    if not results_dir.exists():
        raise ValueError(f"no results directory at {results_dir} — run "
                         f"`python3 sandbox/runner.py run <agent>` first")
    return sorted(results_dir.glob("*.json"))


def case_findings(data: dict, case: dict, file: str = "?") -> list[Finding]:
    """Classify one case's recorded failures, counting each failure exactly once.

    A newer results file records the SAME failure twice — once as a string in
    `failures`, once as a dict in `failed_checks`. Strings win (they carry the
    detail a refinement needs); a dict is only emitted as its own finding when the
    strings did not already account for that check id, which is exactly the
    labels/fields/error cases that produce no string at all.
    """
    meta = (data["agent"], data.get("provider", "?"), data["model"],
            str(case.get("id", "?")), str(case.get("split", "?")))
    out: list[Finding] = []
    seen: Counter = Counter()
    for raw in case.get("failures") or []:
        if not isinstance(raw, str):
            raise ValueError(f"malformed 'failures' entry in case "
                             f"{case.get('id')!r}: {raw!r} is not a string")
        check = check_id_for(raw)
        seen[check] += 1
        out.append(Finding(*meta, category_for(check, raw), check, raw,
                           "failures", file))
    for entry in case.get("failed_checks") or []:
        if not isinstance(entry, dict) or "check" not in entry:
            raise ValueError(f"malformed 'failed_checks' entry in case "
                             f"{case.get('id')!r}: {entry!r}")
        check = entry["check"]
        if seen[check]:  # already counted from its failure string
            seen[check] -= 1
            continue
        out.append(Finding(*meta, category_for(check), check, None,
                           "failed_checks", file))
    if not out:
        out.append(Finding(*meta, NO_RECORDED_REASON, None, None, "none", file))
    return out


def collect(results_dir: Path, agent: str | None = None) -> tuple[list[Finding], dict]:
    """(findings, stats) over every results file. Fails loud on any unreadable file."""
    findings: list[Finding] = []
    files, models, agents, failing_cases, total_cases = [], set(), set(), 0, 0
    for path in find_result_files(results_dir):
        data = load_result_file(path)
        if agent and data["agent"] != agent:
            continue
        files.append(path.name)
        models.add(data["model"])
        agents.add(data["agent"])
        for case in data["cases"]:
            total_cases += 1
            if case.get("passed"):
                continue
            failing_cases += 1
            findings.extend(case_findings(data, case, path.name))
    stats = {"files": len(files), "agents": len(agents), "models": len(models),
             "cases": total_cases, "failing_cases": failing_cases,
             "records": len(findings)}
    return findings, stats


# ---------------------------------------------------------------- aggregation

def aggregate(findings: list[Finding], by_agent: bool = False) -> dict:
    """{group key -> {category -> count}}. Group is the model, or (agent, model)."""
    out: dict = {}
    for f in findings:
        key = f"{f.agent} / {f.model}" if by_agent else f.model
        out.setdefault(key, Counter())[f.category] += 1
    return out


def coverage(findings: list[Finding]) -> list[dict]:
    """One row per category in ALL_CATEGORIES: how many records, how many models,
    and a deterministic example. Categories with zero records are KEPT, marked
    zero-observed — that is the "demonstrated or declared zero" bar."""
    rows = []
    for category in ALL_CATEGORIES:
        hits = _sorted(findings, category)
        rows.append({
            "category": category,
            "records": len(hits),
            "models": len({f.model for f in hits}),
            "example": None if not hits else {
                "model": hits[0].model, "agent": hits[0].agent,
                "case": hits[0].case_id, "check": hits[0].check,
                "failure": hits[0].raw, "source": hits[0].source,
                "file": hits[0].file,
            },
        })
    return rows


_NO_STRING = {
    "failed_checks": "(no failure string recorded — this check emits none; "
                     "read from failed_checks)",
    "none": "(NO failure evidence recorded at all — results file predates "
            "failed_checks)",
}


def _sort_key(f: Finding) -> tuple:
    """Total order over Findings whose `check`/`raw` may be None. Sorting the tuples
    directly would raise TypeError the first time a None met a str at the same
    position — a crash with no reason attached, in a tool whose contract is to fail
    loud WITH one."""
    return tuple("" if v is None else v for v in f)


def _sorted(findings: list[Finding], category: str) -> list[Finding]:
    return sorted((f for f in findings if f.category == category), key=_sort_key)


def _elide(text: str | None, source: str = "failed_checks", width: int = 88) -> str:
    """One display line for a failure. Never invents a reason for a missing string —
    it says which record was absent and why."""
    if text is None:
        return _NO_STRING[source]
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[:width - 1] + "…"


def report_lines(findings: list[Finding], stats: dict, results_dir: Path,
                 by_agent: bool = False) -> list[str]:
    """The whole report, as lines. Pure function of (findings, stats) — no clock,
    no environment, every loop over a sorted sequence, so it is byte-stable."""
    try:
        where = results_dir.resolve().relative_to(ROOT)
    except ValueError:
        where = results_dir.resolve()
    out = [
        "FAILURE TAXONOMY (E9) — read-only report over recorded results. NOT a gate:",
        "it scores nothing and is not part of check-all.",
        f"source: {where}/*.json  ({stats['files']} files, {stats['agents']} exams, "
        f"{stats['models']} models)",
        f"cases: {stats['cases']} scored, {stats['failing_cases']} failing  ->  "
        f"{stats['records']} classified failure records",
        "",
    ]
    n_unclassified = sum(1 for f in findings if f.category == UNCLASSIFIED)
    n_noreason = sum(1 for f in findings if f.category == NO_RECORDED_REASON)
    out += [f"UNCLASSIFIED FAILURES: {n_unclassified}",
            f"FAILING CASES WITH NO RECORDED REASON: {n_noreason}", ""]

    out += ["== failures per model x category "
            f"({'exam / model' if by_agent else 'model'}) ==",
            "shares are of ALL records for that model, including the two meta rows "
            "(unclassified,",
            "no-recorded-reason). A model with unattributable records therefore reads "
            "LOWER on every",
            "capability category — the uncertainty is shown, not divided away."]
    groups = aggregate(findings, by_agent)
    for key in sorted(groups):
        counts = groups[key]
        total = sum(counts.values())
        cases = len({(f.agent, f.case_id) for f in findings
                     if (f"{f.agent} / {f.model}" if by_agent else f.model) == key})
        out.append(f"\n{key}  —  {total} records over {cases} failing cases")
        for category, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            bar = "#" * round(20 * n / total)
            out.append(f"    {category:<26} {n:>4}  {n / total:>5.0%}  {bar}")
        zero = [c for c in CAPABILITY_CATEGORIES if not counts.get(c)]
        zero_txt = ", ".join(zero) if zero else "(nothing — it failed everywhere)"
        out.append(f"    0% on: {zero_txt}")

    out += ["", "== category coverage (real example, or ZERO-OBSERVED) ==",
            f"{'category':<26} {'recs':>4} {'models':>6}  "
            f"example: model | exam | case | check"]
    for row in coverage(findings):
        head = f"{row['category']:<26} {row['records']:>4} {row['models']:>6}  "
        if not row["records"]:
            out.append(head + "ZERO-OBSERVED in this corpus")
            continue
        ex = row["example"]
        out.append(head + f"{ex['model']} | {ex['agent']} | {ex['case']} | "
                          f"{ex['check']}")
        out.append(f"{'':<40}{_elide(ex['failure'], ex['source'])}")

    out += ["", f"== unclassified ({n_unclassified}) =="]
    unclassified = _sorted(findings, UNCLASSIFIED)
    if not unclassified:
        out.append("    none — every recorded failure matched a classification rule")
    for f in unclassified:
        out.append(f"    {f.model} | {f.agent} | {f.case_id} | {f.file}")
        out.append(f"        {_elide(f.raw, f.source)}")

    out += ["", f"== no recorded reason ({n_noreason}) ==",
            "    a FAILING case whose results file recorded no failure evidence at "
            "all. Not guessed at:",
            "    rerun the exam to get a failed_checks record."]
    noreason = _sorted(findings, NO_RECORDED_REASON)
    if not noreason:
        out.append("    none — every failing case recorded why it failed")
    for f in noreason:
        out.append(f"    {f.model} | {f.agent} | {f.case_id} | {f.file}")
    return out


def report_json(findings: list[Finding], stats: dict, by_agent: bool = False) -> dict:
    return {
        "stats": stats,
        "unclassified": [f._asdict() for f in _sorted(findings, UNCLASSIFIED)],
        "no_recorded_reason": [f._asdict() for f
                               in _sorted(findings, NO_RECORDED_REASON)],
        "coverage": coverage(findings),
        "groups": {k: dict(sorted(v.items())) for k, v
                   in sorted(aggregate(findings, by_agent).items())},
    }


# ---------------------------------------------------------------- entry point

def run(args) -> int:
    results_dir = Path(args.results) if getattr(args, "results", None) else RESULTS_DIR
    findings, stats = collect(results_dir, getattr(args, "agent", None))
    if args.json:
        print(json.dumps(report_json(findings, stats, args.by_agent),
                         indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print("\n".join(report_lines(findings, stats, results_dir, args.by_agent)))
    return 0


def add_arguments(sp) -> None:
    sp.add_argument("--agent", help="only this exam's results")
    sp.add_argument("--results", help="results directory (default: ./results)")
    sp.add_argument("--by-agent", action="store_true",
                    help="group by exam x model instead of model")
    sp.add_argument("--json", action="store_true")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(p)
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
