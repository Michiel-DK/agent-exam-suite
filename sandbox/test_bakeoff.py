#!/usr/bin/env python3
"""E21 bake-off — the invariants that make the comparison mean anything.

THE ONE THAT MATTERS. `evals/recap/properties.py` resolves a case's expectations by
EXACT INPUT TEXT. Every E21 strategy changes the text the model sees. Score a strategy
against its own transformed text and the lookup misses, `_exp()` returns {}, and
`must_mention` / `max_ratio` / `nothing_important` ALL pass vacuously — so every strategy
posts a perfect score while measuring nothing, and the bake-off crowns a winner at random.

That failure would be SILENT and it is this repo's most-repeated shape (ledgers 006-008,
014, 015). test_1 and test_2 make it loud: test_2 constructs the mistake deliberately and
asserts it produces the tell-tale vacuous pass, so the invariant in test_1 has teeth.

No inference anywhere in this file.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import runner as R  # noqa: E402
import strategies as S  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


CASES = json.loads((ROOT / "evals" / "recap" / "cases.json").read_text())["cases"]
PROPS = R.load_properties("recap")
BY_ID = {c["id"]: c for c in CASES}
LONG = [c for c in CASES if len(c["input"]) >= 4200]

# A recap that names nothing and invents nothing: it must FAIL a long case on substance.
EMPTY_ISH = {"recap": "Some messages arrived today.", "nothing_important": False}


def test_1_scoring_uses_the_ORIGINAL_input_so_checks_stay_armed():
    """The invariant. Scored against the committed input, a content-free recap must fail
    every long case — exactly as test_recap_adversarial asserts."""
    for c in LONG:
        ok, checks = R._bakeoff_score(PROPS, c, EMPTY_ISH)
        check(f"{c['id']} still armed under bake-off scoring", not ok,
              f"passed with checks={checks} — expectations did not resolve")


def test_2_scoring_a_TRANSFORMED_input_now_FAILS_LOUDLY():
    """This test used to assert the OPPOSITE, and it did its job.

    It was written as a canary: "build the mistake on purpose — if this ever stops passing
    vacuously, the coupling between properties.py and exact input text has changed."
    That is exactly what happened. `_exp` now raises on an input that is not a committed
    case, and run_properties converts the raise into a failed check, so scoring transformed
    text fails loudly instead of scoring 4/4 on nothing. See evals/test_recap_vacuous_green.py
    and ledger 017.

    test_1's protection did NOT become unnecessary. It became load-bearing in a different
    way: the bake-off must still score against the ORIGINAL input, because a strategy that
    transforms its input would now fail every long case *for the wrong reason* — an
    unscoreable bake-off rather than a silently-wrong one. Failure mode changed from
    silent-pass to loud-fail; the requirement to score the original is unchanged.
    """
    c = next(x for x in LONG if (x.get("expected") or {}).get("must_mention"))
    filtered = S.join_items(S.split_items(c["input"])[:3])
    ok_wrong, failures_wrong, _fc = R.run_properties(PROPS, filtered, EMPTY_ISH)
    ok_right, _ = R._bakeoff_score(PROPS, c, EMPTY_ISH)
    check("scoring transformed text FAILS loudly (the vacuous green is closed)",
          not ok_wrong, f"passed vacuously — the guard in _exp is not armed")
    check("and the failure names the cause rather than failing opaquely",
          any("does not match any committed case" in f for f in failures_wrong),
          f"failures={failures_wrong}")
    check("scoring the original text still fails (the trap is avoided)", not ok_right)


def test_3_item_split_round_trips_on_every_committed_case():
    for c in CASES:
        items = S.split_items(c["input"])
        check(f"{c['id']} splits into >=1 item", len(items) >= 1, f"got {len(items)}")
        check(f"{c['id']} round-trips", S.join_items(items).strip() == c["input"].strip(),
              f"{len(S.join_items(items))} vs {len(c['input'])} chars")


def test_4_every_strategy_is_registered_and_callable():
    expected = {"single-shot", "filter-then-recap", "chunk-and-reduce",
                "extract-then-write"}
    check("all four strategies registered", set(S.STRATEGIES) == expected,
          f"got {sorted(S.STRATEGIES)}")
    for name, fn in S.STRATEGIES.items():
        check(f"{name} is callable", callable(fn))


class _FakeCtx:
    """Records what each stage was ASKED to summarise — no model, no server."""

    def __init__(self, ignore_all=False):
        self.recap_inputs, self.triage_inputs = [], []
        self.ignore_all = ignore_all

    def call_recap(self, day):
        self.recap_inputs.append(day)
        return ({"recap": "r", "nothing_important": False},
                {"total_tokens": 1, "reasoning_chars": 0, "content_chars": 1})

    def call_triage(self, item):
        self.triage_inputs.append(item)
        label = "ignore" if self.ignore_all else "reply_now"
        return label, {"total_tokens": 1, "reasoning_chars": 0, "content_chars": 1}


def test_5_filter_shrinks_what_the_model_sees():
    c = BY_ID["long-quiet-day"]          # 21 items, all noise by construction
    ctx = _FakeCtx()
    ctx.ignore_all = False
    _out, metrics = S.filter_then_recap(ctx, c)
    check("one triage call per item", len(ctx.triage_inputs) == len(S.split_items(c["input"])),
          f"{len(ctx.triage_inputs)} calls for {len(S.split_items(c['input']))} items")
    check("cost is items+1 calls", len(metrics) == len(ctx.triage_inputs) + 1,
          f"got {len(metrics)}")


def test_6_filter_dropping_everything_falls_back_to_the_full_day():
    """An empty day would score as a trivially-abstaining pass on quiet cases and tell us
    nothing, so the strategy passes the day through instead."""
    c = BY_ID["long-quiet-day"]
    ctx = _FakeCtx(ignore_all=True)
    S.filter_then_recap(ctx, c)
    check("recap stage saw the full day, not an empty one",
          ctx.recap_inputs[-1].strip() == c["input"].strip(),
          f"saw {len(ctx.recap_inputs[-1])} chars")


def test_7_chunk_degenerates_to_single_shot_on_a_short_day():
    short = min(CASES, key=lambda c: len(S.split_items(c["input"])))
    ctx = _FakeCtx()
    S.chunk_and_reduce(ctx, short, chunk_size=99)
    check(f"{short['id']} makes exactly one recap call", len(ctx.recap_inputs) == 1,
          f"{len(ctx.recap_inputs)} calls")


def test_8_extract_hands_over_figures_rather_than_prose():
    c = BY_ID["amounts-at-length"]
    ctx = _FakeCtx()
    S.extract_then_write(ctx, c)
    seen = ctx.recap_inputs[0]
    check("fact list is much shorter than the day", len(seen) < len(c["input"]) / 2,
          f"{len(seen)} vs {len(c['input'])}")
    for anchor in ("1249.50", "612.40"):
        check(f"figure {anchor} survives extraction", anchor in seen)


def main() -> int:
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)), key=lambda f: f.__name__):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all green'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
