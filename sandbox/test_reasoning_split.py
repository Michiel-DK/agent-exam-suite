#!/usr/bin/env python3
"""E24 — the reasoning/answer split: where the completion budget actually went.

WHAT THIS MEASURES, AND WHAT IT DELIBERATELY DOES NOT
-----------------------------------------------------
Neither Ollama endpoint reports a reasoning TOKEN count (verified 2026-07-29: the
compat `usage` block has only prompt/completion/total and no `completion_tokens_details`;
the native API has only `eval_count`). Both DO return the reasoning TEXT separately.

So we record CHARS. A char-derived token figure would be a guess, and router.py's
long-standing rule is that an unreported token count is None, never guessed. Everything
here asserts that the split is measured honestly, not that it is a token split.

Thinking is already billed inside `completion_tokens` — so these fields explain WHERE a
measured cost went; they never add to it. That is why no assertion below touches
`cost_per_case` or the tiebreak.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import policy  # noqa: E402
import runner as R  # noqa: E402
from router import ChatCompletionsAdapter, TerminationError  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _generate_against(payload, monkey):
    """Drive the REAL adapter against a canned body — no server, no inference."""
    ad = ChatCompletionsAdapter("http://x/v1")
    import router as _router
    orig = _router.requests.post
    _router.requests.post = lambda *a, **k: _FakeResp(payload)
    try:
        return ad.generate([{"role": "user", "content": "hi"}], "m")
    finally:
        _router.requests.post = orig


def _body(content, reasoning, usage=None):
    msg = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if reasoning is not None:
        msg["reasoning"] = reasoning
    return {"choices": [{"message": msg}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 20,
                               "total_tokens": 30}}


def test_1_split_is_captured_from_a_thinking_response():
    _c, meta = _generate_against(_body('{"a":1}', "x" * 500), None)
    check("content_chars measured", meta.get("content_chars") == 7, f"got {meta.get('content_chars')}")
    check("reasoning_chars measured", meta.get("reasoning_chars") == 500,
          f"got {meta.get('reasoning_chars')}")


def test_2_truncated_answer_does_NOT_double_count():
    """THE regression this test exists for, updated by TERMINATION-DETECT (2026-08-27).

    router.py USED TO fall back to `reasoning` when `content` was empty, so a truncated
    answer would report the SAME text as both content and reasoning if the lengths were
    read after the fallback — and it would do so precisely on the long cases the split
    exists to explain. E24 fixed the double-count by measuring before the fallback;
    D2 removed the fallback entirely, because substituting the thinking text scored a
    run that emitted no answer as if it had answered.

    The assertion is therefore now: the same input RAISES, and the exception carries
    the same honestly-split lengths E24 asserted (content 0, reasoning 800). The
    original property — the reasoning text is never counted as content — is what is
    still being checked; only the exit path changed."""
    try:
        _generate_against(_body("", "y" * 800), None)
    except TerminationError as exc:
        d = exc.details
        check("empty content raises TerminationError instead of scoring the thinking",
              True)
        check("content_chars is 0 on a truncated answer", d.get("content_chars") == 0,
              f"got {d.get('content_chars')} — measured AFTER a fallback, double-counted")
        check("reasoning_chars still measured", d.get("reasoning_chars") == 800,
              f"got {d.get('reasoning_chars')}")
    else:
        check("empty content raises TerminationError instead of scoring the thinking",
              False, "generate() returned — either the reasoning fallback is back, or "
                     "the empty string is being handed on to extract_json, which "
                     "loses the attribution and scores a generic `error`")


def test_3_non_thinking_model_reports_zero_not_none():
    """A model that emits no reasoning must report a measured 0. None would mean
    'unknown' and would propagate through _null_safe_sum, poisoning the aggregate for
    every non-thinking model in the roster (3 of 5 today)."""
    _c, meta = _generate_against(_body('{"a":1}', None), None)
    check("reasoning_chars is 0, not None", meta.get("reasoning_chars") == 0,
          f"got {meta.get('reasoning_chars')!r}")


def test_4_aggregation_sums_and_tolerates_older_metrics_dicts():
    steps = [{"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3,
              "wall_ms": 1.0, "retries": 0, "content_chars": 10, "reasoning_chars": 90},
             {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3,
              "wall_ms": 1.0, "retries": 0, "content_chars": 5, "reasoning_chars": 45}]
    agg = R.combine_metrics(steps)
    check("content_chars aggregated", agg["content_chars"] == 15, f"got {agg['content_chars']}")
    check("reasoning_chars aggregated", agg["reasoning_chars"] == 135,
          f"got {agg['reasoning_chars']}")
    legacy = [{"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3,
               "wall_ms": 1.0, "retries": 0}]
    agg2 = R.combine_metrics(legacy)
    check("a pre-E24 metrics dict aggregates to None, not a crash",
          agg2["reasoning_chars"] is None, f"got {agg2['reasoning_chars']!r}")


def test_5_think_share_column_is_honest():
    mk = lambda t, c: {"metrics_totals": {"reasoning_chars": t, "content_chars": c}}
    check("90% thinking renders as 90%", R._think_share_col(mk(900, 100)) == "90%",
          R._think_share_col(mk(900, 100)))
    check("no thinking renders as 0%", R._think_share_col(mk(0, 500)) == "0%",
          R._think_share_col(mk(0, 500)))
    check("absent fields render '-' not 0%", R._think_share_col({"metrics_totals": {}}) == "-",
          R._think_share_col({"metrics_totals": {}}))
    check("pre-E24 run renders '-'", R._think_share_col({}) == "-", R._think_share_col({}))


def test_6_cost_reader_is_untouched_by_the_new_fields():
    """The split explains where a measured cost went; it must not change the cost, nor
    flip a complete run to cost-unknown. Thinking is already inside completion_tokens."""
    base = {"cases": [{"id": "a"}, {"id": "b"}],
            "metrics_totals": {"total_tokens": 200, "wall_ms": 100.0}}
    with_split = {"cases": [{"id": "a"}, {"id": "b"}],
                  "metrics_totals": {"total_tokens": 200, "wall_ms": 100.0,
                                     "content_chars": 50, "reasoning_chars": 950}}
    a, b = policy.cost_per_case(base), policy.cost_per_case(with_split)
    check("cost still known with the new fields", b.known, b.reason)
    check("tok/case unchanged", a.tokens == b.tokens, f"{a.tokens} vs {b.tokens}")
    check("ms/case unchanged", a.wall_ms == b.wall_ms, f"{a.wall_ms} vs {b.wall_ms}")


def test_7_no_token_named_reasoning_field_is_emitted_anywhere():
    """The rule this lane lives by: we did not measure reasoning TOKENS, so nothing may
    be named as though we did. A future edit adding `reasoning_tokens` fails here."""
    for rel in ("sandbox/router.py", "sandbox/runner.py"):
        text = (ROOT / rel).read_text()
        check(f"{rel} emits no 'reasoning_tokens' key",
              '"reasoning_tokens"' not in text and "'reasoning_tokens'" not in text,
              "a reasoning TOKEN count would be derived, not measured")


def main() -> int:
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)), key=lambda f: f.__name__):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all green'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
