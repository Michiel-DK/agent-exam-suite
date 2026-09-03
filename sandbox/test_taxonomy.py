#!/usr/bin/env python3
"""Tests for the E9 failure taxonomy (sandbox/taxonomy.py).

Run: python3 sandbox/test_taxonomy.py

What these pin, in the order the lane's bar states it:

1. NO SILENT BUCKETS. An unmatched failure string surfaces as `unclassified` with
   its raw text and its (model, agent, case) — `test_unclassified_*`. There is no
   catch-all category to hide in, and the count prints at zero — `test_report_*`.
2. EVERY RULE IS LOAD-BEARING (both directions). `test_every_rule_is_load_bearing`
   asserts each real failure string classifies as expected AND that deleting *that*
   rule drops it to `unclassified`. That is the "fails before, passes after" bar
   without needing 20 stashed checkouts: the ablation is the before-state.
3. BOTH RESULTS SHAPES, each failure counted ONCE — `test_shape_*`, `test_double_*`.
4. FAIL LOUD on a file that cannot be read — `test_*_raises`. Never skipped.
5. DETERMINISTIC AND OFFLINE — `test_byte_identical`, `test_offline_no_sockets`.
6. NOT A GATE — `test_not_wired_into_check_all`.

Every failure string in the RULES table below was COPIED from a real results file in
this repo's corpus (or, where the corpus has never produced one, from the literal
emission site in the source — those are marked `ZERO_OBSERVED` and the PR body says
so). No invented failure prose.
"""
from __future__ import annotations

import json
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402
import taxonomy  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


# (raw failure string, expected category, observed-in-corpus?) — one row per rule.
#
# PROVENANCE (fixed 2026-07-27 after the test-honesty refuter on PR #23): every
# ZERO_OBSERVED row must be the LITERAL text its emission site produces, because for
# those rows no real data exists and the emission string IS the evidence. Three rows
# were paraphrases of messages the code never emits — functionally inert (the
# classifier prefix-matches the leading phrase, which was correct) but they pinned a
# fiction: had the real message drifted, the category would have stopped firing and
# this test would still have passed. Each ZERO_OBSERVED row now carries its
# file:line. Re-derive before editing; do not paraphrase.
OBSERVED, ZERO_OBSERVED = "observed", "zero-observed"
RULES: tuple[tuple[str, str, str], ...] = (
    ("never called tool 'deals_list'", "tool-selection", OBSERVED),
    ("called forbidden tool 'crm_lookup'", "tool-selection", ZERO_OBSERVED),
    # VERBATIM from sandbox/runner.py:514-515
    #   f"called disallowed tool {tool!r}: not in " f"tools_allowed {allowed}"
    ("called disallowed tool 'invoice_lookup': not in tools_allowed "
     "['crm_lookup', 'deals_list']",
     "tool-selection", ZERO_OBSERVED),
    ("redundant tool call: crm_lookup called again with identical args {}",
     "tool-efficiency", ZERO_OBSERVED),
    ("took 7 steps (max 4)", "step-budget", ZERO_OBSERVED),
    ("ungrounded number '10,000': appears in the answer but in no tool result and "
     "not in the input", "fabrication", OBSERVED),
    ("ungrounded date/decimal '2022-02-15': no tool result or input contains it in "
     "any recognized format", "fabrication", OBSERVED),
    ("check_no_invented_numbers: numbers not present in input: ['500']",
     "fabrication", OBSERVED),
    # VERBATIM: evals/reply-draft/properties.py:318 emits
    #   f"weekday/date not present in input: {deduped}"
    # and sandbox/runner.py:162 prefixes it as f"{fn_name}: {msg}".
    ("check_no_invented_dates: weekday/date not present in input: ['tuesday']",
     "fabrication", ZERO_OBSERVED),
    ("error_recovery: ungrounded name 'Karen' in the answer — no tool result or "
     "input supplies it", "fabrication-on-tool-error", OBSERVED),
    # VERBATIM from sandbox/runner.py:427-429
    ("error_recovery: designed outage never occurred — 'crm_lookup' returned no "
     "error in this trace, so the rung was not exercised",
     "error-recovery", ZERO_OBSERVED),
    ("answer missing '6500'", "answer-content", OBSERVED),
    ("answer missing all of answer_contains_any: ['no record', 'not found']",
     "answer-content", OBSERVED),
    ("no final answer emitted", "no-answer", OBSERVED),
    ("check_has_reply: empty or missing 'reply' field", "no-answer", ZERO_OBSERVED),
    ("check_signoff: reply does not sign off with Michiel", "house-style", OBSERVED),
    ("check_word_limit: reply is 173 words (limit 120, +10 grace)",
     "house-style", ZERO_OBSERVED),
    ("check_language_match: input looks 'en' but reply looks 'nl'",
     "language-drift", OBSERVED),
    ("judge:Tone is professional: The reply uses informal language",
     "judge-verdict", OBSERVED),
)

# Categories reachable only through a failed_checks dict — these checks emit no
# failure string at all, so they cannot appear in RULES.
DICT_ONLY_RULES: tuple[tuple[str, str], ...] = (
    ("labels", "label-mismatch"),
    ("fields", "label-mismatch"),
    ("error", "harness-error"),
)


def _result(cases: list, agent: str = "crm-followup", model: str = "m1") -> dict:
    return {"agent": agent, "provider": "ollama", "model": model,
            "train": {"passed": 0, "total": 0}, "heldout": {"passed": 0, "total": 0},
            "cases": cases}


def _write(tmp: Path, name: str, payload) -> Path:
    path = tmp / name
    path.write_text(payload if isinstance(payload, str)
                    else json.dumps(payload, indent=2))
    return path


# ---------------------------------------------------------------- rules

def test_every_rule_is_load_bearing() -> None:
    """Both directions, ONE rule at a time.

    Forward: the real failure string classifies as expected. Backward: with exactly
    that rule removed — its single entry in CATEGORY_BY_CHECK, or its single
    refinement, or the "judge:" prefix that triggers it — the same string no longer
    reaches the category. Ablating a whole *category* would be too weak: it would
    still pass if two rules overlapped and neither was individually needed.
    """
    print("\n[rules] every classification rule is load-bearing (per-rule ablation)")
    for raw, expected, seen in RULES:
        check_id = taxonomy.check_id_for(raw)
        got = taxonomy.category_for(check_id, raw)
        check(f"{expected:<26} <- {raw[:46]!r} [{seen}]", got == expected,
              f"got {got!r} via check id {check_id!r}")

        # Remove ONLY this rule.
        one_less = {k: v for k, v in taxonomy.CATEGORY_BY_CHECK.items()
                    if k != check_id}
        refinement = next((r for r in taxonomy.STRING_REFINEMENTS
                           if r[0] == check_id and raw.startswith(r[1])), None)
        if refinement is not None:
            # A refinement sits on TOP of a check id: dropping it must fall back to
            # the coarse category (proving the refinement, not the table, is what
            # produced the fine one), and dropping both must reach unclassified.
            without_ref = tuple(r for r in taxonomy.STRING_REFINEMENTS
                                if r != refinement)
            coarse = taxonomy.category_for(check_id, raw, None, without_ref)
            check(f"  ablate refinement -> coarse category ({expected})",
                  coarse == taxonomy.CATEGORY_BY_CHECK[check_id],
                  f"got {coarse!r}")
            both = taxonomy.category_for(check_id, raw, one_less, without_ref)
            check(f"  ablate refinement + check id -> unclassified ({expected})",
                  both == taxonomy.UNCLASSIFIED, f"got {both!r}")
        elif check_id and check_id.startswith("judge:"):
            # The rule here IS the "judge:" prefix; strip it and the string must
            # stop classifying.
            stripped = raw.split(":", 1)[1]
            ablated = taxonomy.category_for(taxonomy.check_id_for(stripped), stripped)
            check(f"  without the 'judge:' prefix -> unclassified ({expected})",
                  ablated == taxonomy.UNCLASSIFIED, f"got {ablated!r}")
        else:
            ablated = taxonomy.category_for(check_id, raw, one_less)
            check(f"  ablate this check id -> unclassified ({expected})",
                  ablated == taxonomy.UNCLASSIFIED, f"got {ablated!r}")


def test_dict_only_rules() -> None:
    print("\n[rules] checks that emit no failure string (dict-only)")
    for check_id, expected in DICT_ONLY_RULES:
        got = taxonomy.category_for(check_id)
        check(f"{expected:<26} <- failed_checks {check_id!r}", got == expected,
              f"got {got!r}")
        ablated = taxonomy.category_for(
            check_id, None,
            {k: v for k, v in taxonomy.CATEGORY_BY_CHECK.items() if k != check_id})
        check(f"  ablated -> unclassified ({check_id})",
              ablated == taxonomy.UNCLASSIFIED, f"got {ablated!r}")


def test_reuses_runner_table_without_forking() -> None:
    """Every prefix in runner._TRAJECTORY_FAILURE_CHECKS must resolve to the same
    check id here as in runner._trajectory_check_id. A forked copy that drifts is
    the bug this repo has shipped twice."""
    print("\n[reuse] check ids agree with runner's table")
    for prefix, check_id in runner._TRAJECTORY_FAILURE_CHECKS:
        sample = prefix + "x"
        check(f"{check_id:<22} <- {prefix!r}",
              taxonomy.check_id_for(sample) == runner._trajectory_check_id(sample))


def test_every_emitted_check_has_a_category() -> None:
    """Source-level coverage: every check id the suite can emit today maps to a
    category. A new check added without a category shows up here, not as a mystery
    `unclassified` row six weeks later."""
    print("\n[coverage] every check id the suite can emit has a category")
    ids = {cid for _, cid in runner._TRAJECTORY_FAILURE_CHECKS}
    ids |= {"labels", "fields", "error"}
    for agent_dir in sorted((runner.ROOT / "evals").iterdir()):
        if (agent_dir / "properties.py").exists():
            ids |= {name for name, _ in runner.load_properties(agent_dir.name)}
    for check_id in sorted(ids):
        check(f"{check_id} has a category",
              taxonomy.category_for(check_id) != taxonomy.UNCLASSIFIED)


# ---------------------------------------------------------------- no silent buckets

def test_unclassified_surfaces_with_raw_string() -> None:
    print("\n[no silent buckets] an unmatched failure surfaces, never dropped")
    novel = "wibble check: something nobody wrote a rule for"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "a.json", _result([
            {"id": "c1", "split": "train", "passed": False, "failures": [novel]}]))
        findings, stats = taxonomy.collect(tmp)
        check("one record, category unclassified",
              [f.category for f in findings] == [taxonomy.UNCLASSIFIED],
              str([f.category for f in findings]))
        check("raw string preserved", findings[0].raw == novel)
        check("model and case carried",
              (findings[0].model, findings[0].case_id) == ("m1", "c1"))
        check("record was counted, not dropped", stats["records"] == 1)
        text = "\n".join(taxonomy.report_lines(findings, stats, tmp))
        check("report shows the raw string", novel in text)
        check("report shows the count", "UNCLASSIFIED FAILURES: 1" in text)
        check("no 'other' catch-all category exists",
              "other" not in taxonomy.ALL_CATEGORIES)


def test_report_prints_zero_unclassified_prominently() -> None:
    print("\n[no silent buckets] the zero case still prints")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "a.json", _result([
            {"id": "c1", "split": "train", "passed": False,
             "failures": ["never called tool 'deals_list'"]}]))
        findings, stats = taxonomy.collect(tmp)
        text = "\n".join(taxonomy.report_lines(findings, stats, tmp))
        check("count printed at zero", "UNCLASSIFIED FAILURES: 0" in text)
        check("zero-observed categories declared, not hidden",
              "ZERO-OBSERVED in this corpus" in text)


def test_failing_case_with_no_evidence() -> None:
    print("\n[no invented reasons] a failing case with no failure record")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "a.json", _result([
            {"id": "c1", "split": "heldout", "passed": False,
             "expected": {"label": "x"}, "got": {"label": "y"}}]))
        findings, stats = taxonomy.collect(tmp)
        check("category is no-recorded-reason",
              [f.category for f in findings] == [taxonomy.NO_RECORDED_REASON])
        check("not guessed from expected/got", findings[0].check is None)
        text = "\n".join(taxonomy.report_lines(findings, stats, tmp))
        check("counted prominently",
              "FAILING CASES WITH NO RECORDED REASON: 1" in text)
        check("listed with model and case", "m1 | crm-followup | c1" in text)


def test_passing_cases_are_not_counted() -> None:
    print("\n[accounting] a passing case produces no finding")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "a.json", _result([
            {"id": "ok", "split": "train", "passed": True},
            {"id": "bad", "split": "train", "passed": False,
             "failures": ["answer missing '1'"]}]))
        findings, stats = taxonomy.collect(tmp)
        check("one finding from two cases", len(findings) == 1)
        check("stats count both cases", stats["cases"] == 2)
        check("stats count one failing case", stats["failing_cases"] == 1)


# ---------------------------------------------------------------- both shapes

def test_shape_old_strings_only() -> None:
    print("\n[shapes] old results: failures as strings")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "old.json", _result([
            {"id": "c1", "split": "train", "passed": False,
             "failures": ["never called tool 'crm_lookup'", "answer missing 'no'"]}]))
        findings, _ = taxonomy.collect(tmp)
        check("both strings classified",
              sorted(f.category for f in findings)
              == ["answer-content", "tool-selection"],
              str(sorted(f.category for f in findings)))


def test_shape_new_failed_checks_dicts() -> None:
    print("\n[shapes] newer results: failed_checks as dicts")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "new.json", _result([
            {"id": "c1", "split": "train", "passed": False,
             "failed_checks": [{"bucket": "quality", "check": "labels"},
                               {"bucket": "format", "check": "check_signoff"}]}]))
        findings, _ = taxonomy.collect(tmp)
        check("both dicts classified",
              sorted(f.category for f in findings)
              == ["house-style", "label-mismatch"],
              str(sorted(f.category for f in findings)))
        check("source recorded as failed_checks",
              {f.source for f in findings} == {"failed_checks"})


def test_double_recorded_failure_counted_once() -> None:
    """A real newer file records the same failure twice (string + dict). Counting
    both would double every trajectory/property failure in the report."""
    print("\n[shapes] a failure recorded in BOTH shapes counts once")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "both.json", _result([
            {"id": "c1", "split": "train", "passed": False,
             "failures": ["never called tool 'deals_list'", "answer missing '6500'"],
             "failed_checks": [{"bucket": "quality", "check": "tools_called"},
                               {"bucket": "quality", "check": "answer_contains"}]}]))
        findings, stats = taxonomy.collect(tmp)
        check("2 records, not 4", stats["records"] == 2, str(stats))
        check("string form kept (it carries the detail)",
              all(f.source == "failures" for f in findings))


def test_dict_only_check_alongside_strings() -> None:
    """Mixed case: the string-bearing checks dedupe, the string-less one survives."""
    print("\n[shapes] a dict-only check is not swallowed by the dedupe")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "mix.json", _result([
            {"id": "c1", "split": "train", "passed": False,
             "failures": ["check_signoff: reply does not sign off with Michiel"],
             "failed_checks": [{"bucket": "format", "check": "check_signoff"},
                               {"bucket": "quality", "check": "error"}]}]))
        findings, stats = taxonomy.collect(tmp)
        check("2 records", stats["records"] == 2, str(stats))
        check("harness-error kept",
              sorted(f.category for f in findings) == ["harness-error",
                                                       "house-style"],
              str(sorted(f.category for f in findings)))


def test_repeated_same_check_not_collapsed() -> None:
    """Two ungrounded names in one answer are two failures, not one."""
    print("\n[accounting] repeats of one check are counted separately")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _write(tmp, "rep.json", _result([
            {"id": "c1", "split": "train", "passed": False,
             "failures": ["error_recovery: ungrounded name 'Karen' in the answer",
                          "error_recovery: ungrounded name 'Brown' in the answer"],
             "failed_checks": [{"bucket": "quality", "check": "error_recovery"},
                               {"bucket": "quality", "check": "error_recovery"}]}]))
        findings, stats = taxonomy.collect(tmp)
        check("2 records", stats["records"] == 2, str(stats))
        check("both fabrication-on-tool-error",
              {f.category for f in findings} == {"fabrication-on-tool-error"})


# ---------------------------------------------------------------- fail loud

def test_unreadable_file_raises() -> None:
    print("\n[fail loud] a file that cannot be read is never skipped")
    cases = [
        ("invalid json", "{not json"),
        ("top level is a list", "[1, 2]"),
        ("missing 'cases'", json.dumps({"agent": "a", "model": "m"})),
        ("missing 'model'", json.dumps({"agent": "a", "cases": []})),
        ("'cases' not a list", json.dumps({"agent": "a", "model": "m",
                                           "cases": {}})),
    ]
    for label, payload in cases:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp, "bad.json", payload)
            try:
                taxonomy.collect(tmp)
                check(f"raises on {label}", False, "no exception")
            except ValueError as exc:
                check(f"raises on {label}", "bad.json" in str(exc), str(exc))


def test_malformed_failure_entries_raise() -> None:
    print("\n[fail loud] malformed failure records raise")
    bad = [
        ("failures entry not a string",
         {"id": "c", "split": "t", "passed": False, "failures": [{"a": 1}]}),
        ("failed_checks entry not a dict",
         {"id": "c", "split": "t", "passed": False, "failed_checks": ["labels"]}),
        ("failed_checks entry without 'check'",
         {"id": "c", "split": "t", "passed": False,
          "failed_checks": [{"bucket": "quality"}]}),
    ]
    for label, case in bad:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp, "bad.json", _result([case]))
            try:
                taxonomy.collect(tmp)
                check(f"raises on {label}", False, "no exception")
            except ValueError as exc:
                check(f"raises on {label}", True, str(exc)[:60])


def test_missing_results_dir_raises() -> None:
    print("\n[fail loud] a missing results dir raises rather than reporting zero")
    with tempfile.TemporaryDirectory() as td:
        try:
            taxonomy.collect(Path(td) / "nope")
            check("raises on missing dir", False, "no exception")
        except ValueError as exc:
            check("raises on missing dir", "nope" in str(exc), str(exc))


# ---------------------------------------------------------------- determinism

def _corpus(tmp: Path) -> None:
    _write(tmp, "b.json", _result([
        {"id": "c2", "split": "heldout", "passed": False,
         "failures": ["check_signoff: reply does not sign off with Michiel"]},
        {"id": "c3", "split": "train", "passed": False}], agent="reply-draft",
        model="m2"))
    _write(tmp, "a.json", _result([
        {"id": "c1", "split": "train", "passed": False,
         "failures": ["never called tool 'deals_list'", "answer missing '6500'"],
         "failed_checks": [{"bucket": "quality", "check": "tools_called"},
                           {"bucket": "quality", "check": "answer_contains"}]},
        {"id": "c4", "split": "train", "passed": False,
         "failures": ["mystery failure with no rule"]}]))


def test_byte_identical_across_runs() -> None:
    print("\n[deterministic] two runs, identical bytes")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _corpus(tmp)
        first = "\n".join(taxonomy.report_lines(*taxonomy.collect(tmp), tmp))
        second = "\n".join(taxonomy.report_lines(*taxonomy.collect(tmp), tmp))
        check("plain report identical", first == second)
        fj = json.dumps(taxonomy.report_json(*taxonomy.collect(tmp)), sort_keys=True)
        sj = json.dumps(taxonomy.report_json(*taxonomy.collect(tmp)), sort_keys=True)
        check("json report identical", fj == sj)
        by_agent = "\n".join(taxonomy.report_lines(*taxonomy.collect(tmp), tmp,
                                                   by_agent=True))
        check("--by-agent groups differently", by_agent != first)
        check("--by-agent names the exam", "crm-followup / m1" in by_agent)


def test_offline_no_sockets() -> None:
    """No model call, no network — proven by making any socket fatal."""
    print("\n[offline] the whole report runs with sockets disabled")
    real = socket.socket

    def forbidden(*a, **k):
        raise AssertionError("taxonomy opened a socket")

    socket.socket = forbidden
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _corpus(tmp)
            text = "\n".join(taxonomy.report_lines(*taxonomy.collect(tmp), tmp))
        check("report produced with no socket", "FAILURE TAXONOMY" in text)
    except AssertionError as exc:
        check("report produced with no socket", False, str(exc))
    finally:
        socket.socket = real


def test_writes_nothing() -> None:
    print("\n[read-only] the corpus is untouched")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _corpus(tmp)
        before = {p.name: (p.stat().st_mtime_ns, p.read_bytes())
                  for p in sorted(tmp.iterdir())}
        taxonomy.report_lines(*taxonomy.collect(tmp), tmp)
        after = {p.name: (p.stat().st_mtime_ns, p.read_bytes())
                 for p in sorted(tmp.iterdir())}
        check("no file added, changed, or touched", before == after)


def test_not_wired_into_check_all() -> None:
    """A report that can fail the gate is a new way to break the build."""
    print("\n[not a gate] check-all does not call the taxonomy")
    import inspect
    src = inspect.getsource(runner.cmd_check_all)
    check("cmd_check_all never mentions taxonomy", "taxonomy" not in src)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _corpus(tmp)  # contains an unclassified failure

        class Args:
            results, agent, by_agent, json = str(tmp), None, False, False

        check("returns 0 even with unclassified failures",
              taxonomy.run(Args()) == 0)


def test_agent_filter() -> None:
    print("\n[filter] --agent narrows the corpus")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _corpus(tmp)
        _, stats = taxonomy.collect(tmp, agent="reply-draft")
        check("only the named exam", stats["agents"] == 1 and stats["files"] == 1,
              str(stats))


def main() -> int:
    for fn in (test_every_rule_is_load_bearing, test_dict_only_rules,
               test_reuses_runner_table_without_forking,
               test_every_emitted_check_has_a_category,
               test_unclassified_surfaces_with_raw_string,
               test_report_prints_zero_unclassified_prominently,
               test_failing_case_with_no_evidence,
               test_passing_cases_are_not_counted,
               test_shape_old_strings_only, test_shape_new_failed_checks_dicts,
               test_double_recorded_failure_counted_once,
               test_dict_only_check_alongside_strings,
               test_repeated_same_check_not_collapsed,
               test_unreadable_file_raises, test_malformed_failure_entries_raise,
               test_missing_results_dir_raises,
               test_byte_identical_across_runs, test_offline_no_sockets,
               test_writes_nothing, test_not_wired_into_check_all,
               test_agent_filter):
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
