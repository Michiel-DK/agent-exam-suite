#!/usr/bin/env python3
"""E12 tests: the cost-aware `diff` tiebreak, and the escalation-routing policy.

Run: python3 sandbox/test_policy.py     (stdlib only, offline, no model calls)

Two rules are pinned here and both are load-bearing:

1. **`diff`'s accuracy tie is broken on COST, never on argument order.** The
   motivating row is real (E8 corpus, `results/email-triage__ollama__*.json`,
   read 2026-07-27): gemma4:e2b-it-qat and llama3.1:latest score IDENTICALLY on
   both splits, while llama3.1 uses 2.8x fewer tokens and is 4.4x faster.
2. **A route is never recommended inside the noise band.** Heldout is single
   digits per exam, so a one-case accuracy difference is not a capability
   finding; it must come back `cannot-distinguish`, and only cost may then break
   it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import policy  # noqa: E402
from runner import diff_recommendation  # noqa: E402


# --------------------------------------------------------------- fixtures
# Numbers below are transcribed from the real corpus, not invented. Verified by
# reading the files on 2026-07-27:
#   email-triage__ollama__gemma4_e2b-it-qat.json  train 6/6 heldout 4/4
#       metrics_totals total_tokens=5581 wall_ms=60990.6 over 10 cases
#       -> 558.1 tok/case, 6099.1 ms/case
#   email-triage__ollama__llama3.1_latest.json    train 6/6 heldout 4/4
#       metrics_totals total_tokens=2004 wall_ms=13855.9 over 10 cases
#       -> 200.4 tok/case, 1385.6 ms/case

def _row(model: str, train=(6, 6), heldout=(4, 4), totals=None) -> dict:
    """A results-shaped row, the same shape `run_exam` returns."""
    cases = ([{"id": f"t{i}", "split": "train", "passed": i < train[0]}
              for i in range(train[1])]
             + [{"id": f"h{i}", "split": "heldout", "passed": i < heldout[0]}
                for i in range(heldout[1])])
    return {
        "agent": "email-triage", "provider": "ollama", "model": model,
        "train": {"passed": train[0], "total": train[1],
                  "score": round(train[0] / train[1], 4) if train[1] else None},
        "heldout": {"passed": heldout[0], "total": heldout[1],
                    "score": round(heldout[0] / heldout[1], 4) if heldout[1] else None},
        "cases": cases, "metrics_totals": totals,
    }


GEMMA_TOTALS = {"prompt_tokens": 2041, "completion_tokens": 3540,
                "total_tokens": 5581, "wall_ms": 60990.6, "retries": 0}
LLAMA_TOTALS = {"prompt_tokens": 1924, "completion_tokens": 80,
                "total_tokens": 2004, "wall_ms": 13855.9, "retries": 0}


class TestDiffCostTiebreak(unittest.TestCase):
    """DELIVERABLE 1 — cost-aware recommendation on an accuracy tie."""

    def test_the_motivating_row_flips_to_the_cheaper_model(self):
        """THE pinned case. Champion first on the command line (the usual call),
        identical accuracy, challenger 2.8x cheaper -> recommend the challenger.

        Pre-change this asserts False: `max` returns the first maximal row, so the
        incumbent wins the tie by position and the output is "keep gemma4"."""
        rows = [_row("gemma4:e2b-it-qat", totals=GEMMA_TOTALS),
                _row("llama3.1:latest", totals=LLAMA_TOTALS)]
        out = "\n".join(diff_recommendation(rows, "gemma4:e2b-it-qat"))
        self.assertIn("swap gemma4:e2b-it-qat -> llama3.1:latest", out)
        self.assertIn("tie", out.lower())
        self.assertIn("558", out)   # the incumbent's tok/case, cited
        self.assertIn("200", out)   # the challenger's tok/case, cited

    def test_tiebreak_is_not_sensitive_to_argument_order(self):
        """Same two rows, reversed on the command line -> same verdict. Today's
        order-dependent `max` gives the opposite answer for this ordering."""
        rows = [_row("llama3.1:latest", totals=LLAMA_TOTALS),
                _row("gemma4:e2b-it-qat", totals=GEMMA_TOTALS)]
        out = "\n".join(diff_recommendation(rows, "gemma4:e2b-it-qat"))
        self.assertIn("swap gemma4:e2b-it-qat -> llama3.1:latest", out)

    def test_cost_never_overrides_accuracy(self):
        """A cheaper model that is WORSE on heldout must not be recommended —
        the tiebreak fires only on an exact accuracy tie."""
        rows = [_row("gemma4:e2b-it-qat", totals=GEMMA_TOTALS),
                _row("llama3.1:latest", heldout=(3, 4), totals=LLAMA_TOTALS)]
        out = "\n".join(diff_recommendation(rows, "gemma4:e2b-it-qat"))
        self.assertIn("keep gemma4:e2b-it-qat", out)

    def test_unknown_cost_blocks_the_tiebreak_and_says_so(self):
        """An accuracy tie where one row has NO metrics block: refuse to break the
        tie, name the model, and never treat a missing total as 0."""
        rows = [_row("gemma4:e2b-it-qat", totals=GEMMA_TOTALS),
                _row("llama3.1:latest", totals=None)]
        out = "\n".join(diff_recommendation(rows, "gemma4:e2b-it-qat"))
        self.assertIn("keep gemma4:e2b-it-qat", out)
        self.assertIn("cost-unknown", out)
        self.assertIn("llama3.1:latest", out)

    def test_incomplete_metrics_are_cost_unknown_not_a_smaller_number(self):
        """`complete: False` means metered calls were burned that the total cannot
        see. Comparing that floor against a complete total is a fabricated
        comparison — it must read cost-unknown, not "cheaper"."""
        partial = dict(LLAMA_TOTALS, complete=False, unmetered_cases=2)
        rows = [_row("gemma4:e2b-it-qat", totals=GEMMA_TOTALS),
                _row("llama3.1:latest", totals=partial)]
        out = "\n".join(diff_recommendation(rows, "gemma4:e2b-it-qat"))
        self.assertIn("keep gemma4:e2b-it-qat", out)
        self.assertIn("cost-unknown", out)

    def test_tie_cites_the_heldout_denominator(self):
        """A tie on 4 heldout cases is a tie on 4 cases; the verdict must say so,
        because a cost call on a thin tie is still a call on thin data."""
        rows = [_row("gemma4:e2b-it-qat", totals=GEMMA_TOTALS),
                _row("llama3.1:latest", totals=LLAMA_TOTALS)]
        out = "\n".join(diff_recommendation(rows, "gemma4:e2b-it-qat"))
        self.assertIn("4 heldout", out)

    def test_champion_not_run_snapshot_tie_is_cost_unknown(self):
        """Snapshots carry no metrics block at all, so a challenger that merely
        TIES a snapshot cannot be shown to be cheaper. Keep, and say why."""
        rows = [_row("llama3.1:latest", totals=LLAMA_TOTALS)]
        snap = {"train_score": 1.0, "heldout_score": 1.0, "model": "gemma4:e2b-it-qat"}
        out = "\n".join(diff_recommendation(rows, "gemma4:e2b-it-qat", snap))
        self.assertIn("keep gemma4:e2b-it-qat", out)
        self.assertIn("cost-unknown", out)

    # --------------------------- DEFECT 2: order-dependence off the champion path
    # Every fixture above is the 2-model, champion-IS-tied shape. That is the blind
    # spot the test-honesty refuter and python-reviewer found independently: with the
    # champion outside the tied set and cost unable to decide, the verdict fell back
    # to `tied[0]` — command-line order presented as a recommendation.

    def test_tie_with_the_champion_outside_it_is_order_independent(self):
        """3 models: the champion is measurably worse, and the two tied leaders are
        BOTH cost-unknown so cost cannot decide. Pre-change this returned
        "swap champ -> aaa" for one ordering and "swap champ -> zzz" for the other."""
        champ = _row("champ", train=(6, 6), heldout=(2, 4), totals=LLAMA_TOTALS)
        aaa = _row("aaa-tied", totals=None)
        zzz = _row("zzz-tied", totals=None)
        one = "\n".join(diff_recommendation([champ, aaa, zzz], "champ"))
        two = "\n".join(diff_recommendation([champ, zzz, aaa], "champ"))
        self.assertEqual(one, two)
        self.assertIn(policy.CANNOT_DISTINGUISH, one)
        self.assertNotIn("swap champ -> aaa-tied", one)
        self.assertNotIn("swap champ -> zzz-tied", one)
        # the decidable half is still stated
        self.assertIn("MOVE OFF champ", one)
        self.assertIn("aaa-tied, zzz-tied", one)

    def test_tie_with_the_champion_outside_it_still_decides_on_cost_when_it_can(self):
        """The mirror: same shape, but both tied rows ARE priced. Cost decides, and
        the answer is the same in either order — a refusal is only correct when the
        data genuinely cannot choose."""
        champ = _row("champ", train=(6, 6), heldout=(2, 4), totals=LLAMA_TOTALS)
        aaa = _row("aaa-tied", totals=GEMMA_TOTALS)      # 558 tok/case
        zzz = _row("zzz-tied", totals=LLAMA_TOTALS)      # 200 tok/case
        one = "\n".join(diff_recommendation([champ, aaa, zzz], "champ"))
        two = "\n".join(diff_recommendation([champ, zzz, aaa], "champ"))
        self.assertEqual(one, two)
        self.assertIn("swap champ -> zzz-tied", one)
        self.assertNotIn(policy.CANNOT_DISTINGUISH, one)

    def test_snapshot_champion_outside_an_undecidable_tie_is_order_independent(self):
        """Same defect on the snapshot path: `best` was still `tied[0]`."""
        snap = {"train_score": 0.5, "heldout_score": 0.5, "model": "champ"}
        aaa, zzz = _row("aaa-tied", totals=None), _row("zzz-tied", totals=None)
        one = "\n".join(diff_recommendation([aaa, zzz], "champ", snap))
        two = "\n".join(diff_recommendation([zzz, aaa], "champ", snap))
        self.assertEqual(one, two)
        self.assertIn(policy.CANNOT_DISTINGUISH, one)
        self.assertIn("MOVE OFF champ is decided", one)
        self.assertNotIn("swap champ -> aaa-tied", one)

    def test_a_tie_below_the_snapshot_is_still_a_decided_keep(self):
        """Refusing here would be over-correction: which challenger is best is
        undecidable, but "none of them beats the snapshot" is decided."""
        snap = {"train_score": 1.0, "heldout_score": 1.0, "model": "champ"}
        aaa, zzz = _row("aaa-tied", totals=None), _row("zzz-tied", totals=None)
        out = "\n".join(diff_recommendation([aaa, zzz], "champ", snap))
        self.assertIn("keep champ", out)
        self.assertNotIn(policy.CANNOT_DISTINGUISH, out)

    def test_tiebreak_sentence_labels_a_slower_cheapest_model(self):
        """`_cost_tiebreak` ranks tokens first, so the winner can be the SLOWER
        model — and the wall ratio then drops below 1. Both directions asserted."""
        cheap_slow = _row("cheap-slow", totals={"total_tokens": 2000, "wall_ms": 60000})
        dear_fast = _row("dear-fast", totals={"total_tokens": 4000, "wall_ms": 20000})
        out = "\n".join(diff_recommendation([cheap_slow, dear_fast], "cheap-slow"))
        self.assertIn("2.00x tokens (MORE) and 0.33x wall (FASTER)", out)
        self.assertIn("winner is cheap-slow", out)

        cheap_fast = _row("cheap-fast", totals={"total_tokens": 2000, "wall_ms": 20000})
        dear_slow = _row("dear-slow", totals={"total_tokens": 4000, "wall_ms": 60000})
        out2 = "\n".join(diff_recommendation([cheap_fast, dear_slow], "cheap-fast"))
        self.assertIn("2.00x tokens (MORE) and 3.00x wall (SLOWER)", out2)

    def test_unchanged_verdicts_still_hold(self):
        """Regression guard on the paths the tiebreak must NOT touch."""
        better = [_row("gemma4:e2b-it-qat", heldout=(2, 4), totals=GEMMA_TOTALS),
                  _row("llama3.1:latest", totals=LLAMA_TOTALS)]
        self.assertIn("swap gemma4:e2b-it-qat -> llama3.1:latest",
                      "\n".join(diff_recommendation(better, "gemma4:e2b-it-qat")))
        snap = {"train_score": 0.5, "heldout_score": 0.5, "model": "gemma4:e2b-it-qat"}
        self.assertIn("swap", "\n".join(diff_recommendation(
            [_row("llama3.1:latest", totals=LLAMA_TOTALS)],
            "gemma4:e2b-it-qat", snap)))
        self.assertIn("none — champion", "\n".join(diff_recommendation(
            [_row("llama3.1:latest", totals=LLAMA_TOTALS)], "gemma4:e2b-it-qat", None)))


# ------------------------------------------------------ DELIVERABLE 2: the policy

def _corpus(*specs) -> list:
    """[(cohort key, Run)] from (model, train, heldout, failed_heldout, totals)."""
    out = []
    for model, train, heldout, failed, totals in specs:
        data = _row(model, train, heldout, totals)
        for i, case in enumerate(data["cases"]):
            if case["split"] == "heldout":
                case["passed"] = case["id"] not in failed
        data["heldout"]["passed"] = heldout[1] - len(failed)
        data["heldout"]["score"] = round(data["heldout"]["passed"] / heldout[1], 4)
        run = policy.to_run(data, f"email-triage__ollama__{model}.json")
        out.append((policy.cohort_key(data), run))
    return out


class TestNoiseBand(unittest.TestCase):
    """THE primary bar: never recommend inside the noise band."""

    def test_one_case_apart_is_cannot_distinguish(self):
        corpus = _corpus(
            ("cheap", (6, 6), (4, 4), ("h3",), LLAMA_TOTALS),   # 3/4 heldout
            ("dear", (6, 6), (4, 4), (), GEMMA_TOTALS),         # 4/4 heldout
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.accuracy_verdict, policy.CANNOT_DISTINGUISH)
        self.assertIn("one case is 25%", v.accuracy_evidence)

    def test_the_noise_guard_is_what_produces_that_verdict(self):
        """A/B on the injected band, mirroring taxonomy's injectable-tables pattern:
        the SAME corpus with the band set to 0 yields a pick. That isolates this
        guard — nothing else in the function changed — and is the both-direction
        evidence for new leaf code that has no pre-change behaviour to fail."""
        corpus = _corpus(
            ("cheap", (6, 6), (4, 4), ("h3",), LLAMA_TOTALS),
            ("dear", (6, 6), (4, 4), (), GEMMA_TOTALS),
        )
        banded = policy.route_agent("email-triage", corpus, None, noise_cases=1)
        unbanded = policy.route_agent("email-triage", corpus, None, noise_cases=0)
        self.assertEqual(banded.accuracy_verdict, policy.CANNOT_DISTINGUISH)
        self.assertEqual(banded.start, "cheap")          # cost decided it
        self.assertEqual(banded.start_basis, "cost")
        self.assertEqual(unbanded.accuracy_verdict, "pick")
        self.assertEqual(unbanded.start, "dear")         # accuracy decided it
        self.assertEqual(unbanded.start_basis, "accuracy")

    def test_two_cases_apart_is_a_real_pick(self):
        corpus = _corpus(
            ("cheap", (6, 6), (4, 4), ("h2", "h3"), LLAMA_TOTALS),
            ("dear", (6, 6), (4, 4), (), GEMMA_TOTALS),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.accuracy_verdict, "pick")
        self.assertEqual(v.start, "dear")
        self.assertIn("2 heldout case(s) BEHIND", v.accuracy_evidence)
        self.assertIn("the band is cleared on heldout", v.accuracy_evidence)

    def test_cost_decides_when_accuracy_cannot(self):
        """Equal accuracy + cheaper -> a recommendation, on COST, citing both."""
        corpus = _corpus(
            ("cheap", (6, 6), (4, 4), (), LLAMA_TOTALS),
            ("dear", (6, 6), (4, 4), (), GEMMA_TOTALS),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.accuracy_verdict, policy.CANNOT_DISTINGUISH)
        self.assertEqual(v.start, "cheap")
        self.assertEqual(v.start_basis, "cost")
        # Nothing outscores the cost pick here, so there is no escalation destination
        # — and the verdict must price the alternative rather than just assert it.
        # This is the ratio>1 HALF of the pair; the mirror lives in
        # TestComparativeDirection.test_no_escalation_target_cheaper_peer_is_a_de_escalation.
        self.assertEqual(v.escalation, "no-escalation-target")
        self.assertIn("2.78x tokens (MORE)", v.escalation_evidence)
        self.assertIn("would pay MORE", v.escalation_evidence)

    def test_escalation_prices_the_target_when_the_start_is_not_the_leader(self):
        """Start chosen on cost, a peer 1 case ahead: never-escalate, +1 of 4 inside
        the band, with the token/wall multiple the escalation would cost."""
        corpus = _corpus(
            ("aaa-cheap", (6, 6), (4, 4), ("h3",), LLAMA_TOTALS),
            ("bbb-dear", (6, 6), (4, 4), (), GEMMA_TOTALS),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.start, "aaa-cheap")
        self.assertEqual(v.escalation, "never-escalate")
        self.assertIn("buys +1 heldout case(s) of 4 (25%)", v.escalation_evidence)
        self.assertIn("the move costs MORE", v.escalation_evidence)
        self.assertIn("2.78x tokens (MORE)", v.escalation_evidence)

    def test_train_split_can_also_disqualify_a_contender(self):
        """A model that ties on a saturated heldout but is 2 train cases worse is
        NOT indistinguishable — otherwise cost would promote a measurably worse
        model on the strength of a saturated split alone."""
        corpus = _corpus(
            ("cheap", (4, 6), (4, 4), (), LLAMA_TOTALS),
            ("dear", (6, 6), (4, 4), (), GEMMA_TOTALS),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.accuracy_verdict, "pick")
        self.assertEqual(v.start, "dear")
        self.assertNotIn("cheap", v.contenders)


class TestCostHonesty(unittest.TestCase):
    """Partial/missing cost data must never be averaged or zero-filled."""

    def test_missing_metrics_block_is_cost_unknown(self):
        c = policy.cost_per_case(_row("m", totals=None))
        self.assertFalse(c.known)
        self.assertIsNone(c.tokens)
        self.assertIn("no metrics_totals", c.reason)

    def test_incomplete_metrics_block_is_cost_unknown_with_its_reason(self):
        partial = dict(LLAMA_TOTALS, complete=False, unmetered_cases=2)
        c = policy.cost_per_case(_row("m", totals=partial))
        self.assertFalse(c.known)
        self.assertIsNone(c.tokens)
        self.assertIn("FLOOR", c.reason)
        self.assertIn("2 of 10", c.reason)

    def test_complete_metrics_are_per_case_not_per_run(self):
        c = policy.cost_per_case(_row("m", totals=LLAMA_TOTALS))
        self.assertTrue(c.known)
        self.assertAlmostEqual(c.tokens, 2004 / 10)
        self.assertAlmostEqual(c.wall_ms, 13855.9 / 10)

    def test_cost_unknown_contender_is_named_and_never_ranked(self):
        corpus = _corpus(
            ("cheap", (6, 6), (4, 4), (), LLAMA_TOTALS),
            ("dear", (6, 6), (4, 4), (), GEMMA_TOTALS),
            ("unmetered", (6, 6), (4, 4), (), None),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertIn("unmetered", v.cost_unknown_models)
        self.assertEqual(v.start, "cheap")
        self.assertIn("cost-unknown", v.start_evidence)

    def test_all_contenders_cost_unknown_yields_no_pick(self):
        corpus = _corpus(
            ("a", (6, 6), (4, 4), (), None),
            ("b", (6, 6), (4, 4), (), None),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.accuracy_verdict, policy.CANNOT_DISTINGUISH)
        self.assertEqual(v.start, "")
        self.assertEqual(v.start_basis, policy.COST_UNKNOWN)


class TestCostFloor(unittest.TestCase):
    """A tiny token saving bought with a big latency regression is not a finding.

    Numbers are the real expense-categorization row (E8-era corpus, read
    2026-07-27): gemma4:e4b-it-qat 434 tok/case at 7286 ms/case vs gemma4:e2b-it-qat
    469 tok/case at 4396 ms/case — 1.08x cheaper on tokens, 1.66x SLOWER.
    """
    SLOW_CHEAP = {"prompt_tokens": 0, "completion_tokens": 0,
                  "total_tokens": 4340, "wall_ms": 72860, "retries": 0}
    FAST_DEAR = {"prompt_tokens": 0, "completion_tokens": 0,
                 "total_tokens": 4690, "wall_ms": 43960, "retries": 0}

    def test_small_saving_plus_latency_regression_decides_nothing(self):
        corpus = _corpus(
            ("slow-cheap", (6, 6), (4, 4), (), self.SLOW_CHEAP),
            ("fast-dear", (6, 6), (4, 4), (), self.FAST_DEAR),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.accuracy_verdict, policy.CANNOT_DISTINGUISH)
        self.assertEqual(v.start, "")
        self.assertEqual(v.start_basis, policy.CANNOT_DISTINGUISH)
        self.assertIn("under the declared 1.25x floor", v.start_evidence)
        self.assertEqual(v.escalation, policy.CANNOT_DISTINGUISH)

    def test_the_floor_is_what_blocks_it(self):
        """A/B isolating the floor: the SAME shape with the token saving raised past
        1.25x yields a pick, tradeoff explicitly accepted."""
        big_saving = dict(self.FAST_DEAR, total_tokens=9000)  # 900 vs 434 = 2.07x
        corpus = _corpus(
            ("slow-cheap", (6, 6), (4, 4), (), self.SLOW_CHEAP),
            ("fast-dear", (6, 6), (4, 4), (), big_saving),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.start, "slow-cheap")
        self.assertEqual(v.start_basis, "cost")
        self.assertIn("clears the declared 1.25x floor", v.start_evidence)

    def test_the_floor_never_applies_when_cheapest_is_also_fastest(self):
        corpus = _corpus(
            ("cheap-fast", (6, 6), (4, 4), (), {"total_tokens": 4340, "wall_ms": 4000}),
            ("dear-slow", (6, 6), (4, 4), (), {"total_tokens": 4690, "wall_ms": 5000}),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.start, "cheap-fast")   # 1.08x, but dominant on both axes
        self.assertEqual(v.start_basis, "cost")


class TestCohortsAndFailLoud(unittest.TestCase):

    def test_current_exam_status_is_its_own_field(self):
        """A route over a RETIRED case set must not read as `routed` full stop — a
        --json consumer has to be able to see that the current exam is unrouted."""
        corpus = _corpus(("a", (6, 6), (4, 4), (), LLAMA_TOTALS),
                         ("b", (6, 6), (4, 4), (), GEMMA_TOTALS))
        grown = corpus[0][0] + (("h9", "heldout"),)
        v = policy.route_agent("email-triage", corpus, grown)
        self.assertEqual(v.status, "routed")
        self.assertEqual(v.current_exam_status, policy.INSUFFICIENT_DATA)
        self.assertEqual(v.current_cohort, ())
        text = "\n".join(policy.report_lines([v], Path("results")))
        self.assertIn("insufficient-data to route the exam AS IT STANDS TODAY", text)
        same = policy.route_agent("email-triage", corpus, corpus[0][0])
        self.assertEqual(same.current_exam_status, "routable")

    def test_a_beaten_incumbent_is_called_out_even_with_no_pick(self):
        """The real current-exam email-triage shape: two contenders one case apart
        (undecidable), and the CHAMPION two cases behind both (decidable). The report
        must not read "stay put" when staying put is itself a measured loss."""
        corpus = _corpus(
            ("champ", (7, 8), (11, 11), ("h8", "h9", "h10"), LLAMA_TOTALS),  # 8/11
            ("lead", (7, 8), (11, 11), ("h10",), LLAMA_TOTALS),              # 10/11
            ("near", (7, 8), (11, 11), ("h9", "h10"), GEMMA_TOTALS),         # 9/11
        )
        v = policy.route_agent("email-triage", corpus, None, champion="champ")
        self.assertEqual(v.accuracy_verdict, policy.CANNOT_DISTINGUISH)
        self.assertNotIn("champ", v.contenders)
        self.assertIn("MEASURED LOSS", v.champion_note)
        self.assertIn("2 heldout case(s) BEHIND", v.champion_note)
        self.assertIn("MOVE OFF the incumbent", v.champion_note)
        # The "every contender is ahead of it" claim is DERIVED, not asserted — see
        # TestComparativeDirection.test_measured_loss_on_a_train_only_exclusion.
        self.assertIn("2 of 2 contender(s) are ahead of it on heldout", v.champion_note)

    def test_champion_framing_says_swap_or_confirm(self):
        corpus = _corpus(("cheap", (6, 6), (4, 4), (), LLAMA_TOTALS),
                         ("dear", (6, 6), (4, 4), (), GEMMA_TOTALS))
        swap = policy.route_agent("email-triage", corpus, None, champion="dear")
        self.assertIn("SWAP away from the incumbent",
                      "\n".join(policy.report_lines([swap], Path("results"))))
        keep = policy.route_agent("email-triage", corpus, None, champion="cheap")
        self.assertIn("CONFIRMS the incumbent",
                      "\n".join(policy.report_lines([keep], Path("results"))))

    def test_different_case_sets_are_never_pooled(self):
        """Two models scored on different case sets are not comparable; the smaller
        cohort must be reported as excluded, not merged in."""
        big = _corpus(("dear", (6, 6), (4, 4), (), GEMMA_TOTALS))
        small = []
        data = _row("cheap", (3, 3), (2, 2), LLAMA_TOTALS)
        small.append((policy.cohort_key(data),
                      policy.to_run(data, "email-triage__ollama__cheap.json")))
        v = policy.route_agent("email-triage", big + small, None)
        self.assertEqual(v.status, policy.INSUFFICIENT_DATA)
        self.assertIn("nothing to compare against", v.reason)
        self.assertIn("incompatible case sets", v.reason)

    def test_single_model_corpus_is_insufficient_data(self):
        corpus = _corpus(("only", (6, 6), (4, 4), (), LLAMA_TOTALS))
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.status, policy.INSUFFICIENT_DATA)
        self.assertEqual(v.start, "")

    def test_no_results_for_an_agent_is_insufficient_data(self):
        v = policy.route_agent("crm-followup", _corpus(
            ("only", (6, 6), (4, 4), (), LLAMA_TOTALS)), None)
        self.assertEqual(v.status, policy.INSUFFICIENT_DATA)
        self.assertIn("no results files", v.reason)

    def test_disagreeing_reruns_of_one_model_are_a_conflict_not_an_average(self):
        """The real corpus carries two email-triage llama3.1 files that disagree
        (train 5/6 vs 6/6). If both are metered, neither may be silently chosen."""
        a = _row("llama3.1:latest", train=(5, 6), totals=LLAMA_TOTALS)
        b = _row("llama3.1:latest", train=(6, 6), totals=GEMMA_TOTALS)
        runs = [policy.to_run(a, "a.json"), policy.to_run(b, "b.json")]
        kept, notes, conflicts = policy.resolve_duplicates(runs)
        self.assertEqual(kept, [])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0][0], "llama3.1:latest")

    def test_the_metered_file_wins_when_only_one_is_metered(self):
        a = _row("llama3.1:latest", train=(5, 6), totals=None)
        b = _row("llama3.1:latest", train=(6, 6), totals=LLAMA_TOTALS)
        runs = [policy.to_run(a, "a.json"), policy.to_run(b, "b.json")]
        kept, notes, conflicts = policy.resolve_duplicates(runs)
        self.assertEqual([r.file for r in kept], ["b.json"])
        self.assertEqual(conflicts, [])
        self.assertIn("kept b.json (metered)", notes[0])

    def test_missing_results_dir_raises(self):
        with self.assertRaises(ValueError):
            policy.load_corpus(Path("/nonexistent/results/dir"))

    def test_empty_results_dir_raises(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as cm:
                policy.load_corpus(Path(d))
        self.assertIn("empty results corpus", str(cm.exception))

    def test_staleness_is_labelled_against_the_current_exam(self):
        corpus = _corpus(("a", (6, 6), (4, 4), (), LLAMA_TOTALS),
                         ("b", (6, 6), (4, 4), (), GEMMA_TOTALS))
        current = corpus[0][0]
        self.assertEqual(policy.route_agent("email-triage", corpus, current)
                         .stale_label, "CURRENT")
        grown = current + (("h9", "heldout"),)
        v = policy.route_agent("email-triage", corpus, grown)
        self.assertEqual(v.stale_label, "STALE")
        self.assertIn("the exam now has 11", v.stale_detail)


class TestComparativeDirection(unittest.TestCase):
    """THE primary bar of the re-spin: **every generated comparative sentence is
    tested in BOTH directions.**

    PR #24 had 35 green tests and still printed, on the real crm-followup cohort,

        "...costs 0.6x tokens, 0.2x wall — escalating would pay more for no measured
         gain"

    while the merge gate's own read of the files said gemma4:e4b-it-qat = 886.1
    tok/case / 14551.8 ms/case and llama3.1:latest = 574.8 / 2820.4 — i.e. the
    alternative was CHEAPER and 5x FASTER. The clause was a fixed string appended
    without inspecting the ratio, and the one fixture on that branch (`dear` 2.8x
    pricier) happened to make it true.

    So: for every sentence asserting a DIRECTION there is a ratio>1 case AND a
    ratio<1 case here, named as a pair. `_directed`/`cost_move`/`gap_phrase` are
    pinned directly too, so the invariant is not only observable six call sites away.
    """

    # Mirror of the real crm-followup row: the peer is CHEAPER and much faster while
    # being materially worse. Ratios chosen to reproduce 0.65x / 0.19x exactly.
    LEADER_COST = {"total_tokens": 8861, "wall_ms": 145518, "retries": 0}   # 886.1/14551.8
    PEER_CHEAPER = {"total_tokens": 5748, "wall_ms": 28204, "retries": 0}   # 574.8/2820.4

    # ------------------------------------------------ the helper's own invariant
    def test_direction_word_and_printed_figure_can_never_disagree(self):
        """The root-cause pin. Sweep ratios across >1, <1 and ==1-after-rounding and
        assert the word always matches the number that is printed next to it."""
        for ratio in (0.01, 0.19, 0.649, 0.65, 0.994, 0.999, 1.0, 1.001, 1.004,
                      1.006, 1.25, 2.78, 100.0):
            sign, text = policy._directed(ratio, "MORE", "LESS", "SAME")
            shown = float(text.split("x")[0])
            with self.subTest(ratio=ratio):
                self.assertEqual(shown, round(ratio, policy.RATIO_DP))
                if shown > 1:
                    self.assertEqual((sign, text.endswith("MORE")), (1, True))
                elif shown < 1:
                    self.assertEqual((sign, text.endswith("LESS")), (-1, True))
                else:
                    self.assertEqual((sign, text.endswith("SAME")), (0, True))

    def test_cost_move_classifies_both_directions_and_the_mixed_case(self):
        dear = policy.Cost(True, 886.1, 14551.8, "")
        cheap = policy.Cost(True, 574.8, 2820.4, "")
        self.assertEqual(policy.cost_move(dear, cheap).direction, "cheaper")
        self.assertEqual(policy.cost_move(cheap, dear).direction, "pricier")
        self.assertIn("0.65x tokens (FEWER)", policy.cost_move(dear, cheap).text)
        self.assertIn("1.54x tokens (MORE)", policy.cost_move(cheap, dear).text)
        # tokens down, wall up -> neither word may be claimed
        slow_cheap = policy.Cost(True, 400.0, 20000.0, "")
        self.assertEqual(policy.cost_move(dear, slow_cheap).direction, "mixed")
        self.assertEqual(policy.cost_move(dear, dear).direction, "same")
        self.assertEqual(
            policy.cost_move(dear, policy.Cost(False, None, None, "no block")).direction,
            policy.COST_UNKNOWN)

    def test_savings_names_only_the_axes_below_one(self):
        """The derived phrase, pinned directly rather than only six call sites away.
        A ratio that ROUNDS to 1.00 is not a saving on that axis."""
        dear = policy.Cost(True, 886.1, 14551.8, "")
        both = policy.cost_move(dear, policy.Cost(True, 574.8, 2820.4, ""))
        self.assertEqual(both.savings,
                         ["a 35% token saving", "an 81% wall-clock saving"])
        wall_only = policy.cost_move(dear, policy.Cost(True, 886.1, 2820.4, ""))
        self.assertEqual(wall_only.savings, ["an 81% wall-clock saving"])
        # a 0.4% token drop rounds to 1.00x and must not be sold as a saving
        rounds_to_one = policy.cost_move(dear, policy.Cost(True, 882.6, 2820.4, ""))
        self.assertEqual(rounds_to_one.savings, ["an 81% wall-clock saving"])
        self.assertEqual(policy.cost_move(dear, dear).savings, [])
        self.assertEqual(
            policy.cost_move(dear, policy.Cost(False, None, None, "x")).savings, [])

    def test_gap_phrase_in_both_directions_and_at_zero(self):
        self.assertEqual(policy.gap_phrase(9, 6, "heldout"), "3 heldout case(s) BEHIND")
        self.assertEqual(policy.gap_phrase(6, 9, "heldout"), "3 heldout case(s) AHEAD")
        self.assertEqual(policy.gap_phrase(9, 9, "heldout"), "LEVEL on heldout")

    # ---------------------------- SENTENCE 1: the no-escalation-target price clause
    # ratio>1 half: TestNoiseBand.test_cost_decides_when_accuracy_cannot
    def test_no_escalation_target_cheaper_peer_is_a_de_escalation(self):
        """THE defect. Leader is also the DEARER model; the only alternative is
        cheaper and worse. Pre-fix this printed "escalating would pay more for no
        measured gain" — the exact inversion the merge gate caught on crm-followup."""
        corpus = _corpus(
            ("leader-dear", (6, 6), (9, 9), (), self.LEADER_COST),
            ("peer-cheap", (5, 6), (9, 9), ("h6", "h7", "h8"), self.PEER_CHEAPER),
        )
        # (`_corpus` labels every row email-triage; the SHAPE is crm-followup's.)
        v = policy.route_agent("email-triage", corpus, None, champion="peer-cheap")
        self.assertEqual(v.escalation, "no-escalation-target")
        ev = v.escalation_evidence
        # the number and the word agree, and the word is the RIGHT one
        self.assertIn("0.65x tokens (FEWER)", ev)
        self.assertIn("0.19x wall (FASTER)", ev)
        self.assertIn("DE-ESCALATION trade", ev)
        self.assertIn("35% token saving", ev)
        self.assertIn("3 heldout case(s) (33%)", ev)
        # the inverted clause must be GONE, not merely outweighed
        self.assertNotIn("pay MORE", ev)
        self.assertNotIn("pay more", ev)

    def test_de_escalation_credits_only_the_axis_that_actually_improved(self):
        """`cheaper` needs only ONE axis to improve. With tokens flat to 2dp and the
        clock 5x faster — the real email-triage 217/217 shape — crediting "a 0% token
        saving" would name an axis with no benefit on it. Both halves asserted: the
        flat-tokens case names the wall saving only, the both-axes case names both."""
        flat_tokens = _corpus(
            ("leader", (6, 6), (4, 4), (), {"total_tokens": 2170, "wall_ms": 100000}),
            ("peer", (6, 6), (4, 4), ("h1", "h2", "h3"),
             {"total_tokens": 2170, "wall_ms": 19000}),
        )
        ev = policy.route_agent("email-triage", flat_tokens, None).escalation_evidence
        self.assertIn("1.00x tokens (the same, to 2dp)", ev)
        self.assertIn("it buys an 81% wall-clock saving at the price of", ev)
        self.assertNotIn("0% token saving", ev)

        both_axes = _corpus(
            ("leader", (6, 6), (4, 4), (), {"total_tokens": 4000, "wall_ms": 100000}),
            ("peer", (6, 6), (4, 4), ("h1", "h2", "h3"),
             {"total_tokens": 2000, "wall_ms": 50000}),
        )
        ev2 = policy.route_agent("email-triage", both_axes, None).escalation_evidence
        self.assertIn("it buys a 50% token saving and a 50% wall-clock saving", ev2)

    def test_de_escalation_priced_against_a_train_only_regression(self):
        """The cheaper branch's OTHER tail: the peer is level on heldout and loses on
        train, so the price of the saving is a train regression, not heldout cases.
        (Its mirror — a level peer that is PRICIER — is
        test_no_escalation_target_level_peer_says_level_not_zero_behind.)"""
        corpus = _corpus(
            ("aaa-leader", (6, 6), (4, 4), (), GEMMA_TOTALS),   # 558 tok/case
            ("bbb-peer", (3, 6), (4, 4), (), LLAMA_TOTALS),     # 200 tok/case, cheaper
        )
        ev = policy.route_agent("email-triage", corpus, None).escalation_evidence
        self.assertIn("LEVEL on heldout", ev)
        self.assertIn("0.36x tokens (FEWER)", ev)
        self.assertIn("DE-ESCALATION trade", ev)
        self.assertIn("at the price of a train-split regression (3/6 vs 6/6)", ev)
        self.assertNotIn("heldout case(s) (0%)", ev)

    def test_no_escalation_target_mixed_and_unknown_directions(self):
        """The other two classifications on the same branch: axes disagreeing, and
        one side unpriced. Neither may borrow a direction word from the other."""
        mixed = _corpus(
            ("leader", (6, 6), (4, 4), (), {"total_tokens": 4000, "wall_ms": 40000}),
            ("peer", (6, 6), (4, 4), ("h2", "h3"),
             {"total_tokens": 3000, "wall_ms": 80000}),   # fewer tokens, 2x slower
        )
        ev = policy.route_agent("email-triage", mixed, None).escalation_evidence
        self.assertIn("MIXED trade", ev)
        self.assertIn("0.75x tokens (FEWER)", ev)
        self.assertIn("2.00x wall (SLOWER)", ev)
        self.assertNotIn("DE-ESCALATION", ev)

        unpriced = _corpus(
            ("leader", (6, 6), (4, 4), (), LLAMA_TOTALS),
            ("peer", (6, 6), (4, 4), ("h2", "h3"), None),
        )
        ev2 = policy.route_agent("email-triage", unpriced, None).escalation_evidence
        self.assertIn(policy.COST_UNKNOWN, ev2)
        self.assertNotIn("DE-ESCALATION", ev2)
        self.assertNotIn("pay MORE", ev2)

    def test_no_escalation_target_level_peer_says_level_not_zero_behind(self):
        """`0 case(s) BEHIND` is a comparative with no comparison in it. A peer that
        ties the leader on heldout and loses on train must be described as such."""
        corpus = _corpus(
            ("aaa-leader", (6, 6), (4, 4), (), LLAMA_TOTALS),
            ("bbb-peer", (3, 6), (4, 4), (), GEMMA_TOTALS),
        )
        ev = policy.route_agent("email-triage", corpus, None).escalation_evidence
        self.assertIn("LEVEL on heldout", ev)
        self.assertIn("3 train case(s) BEHIND", ev)
        self.assertNotIn("0 heldout case(s)", ev)

    def test_best_peer_choice_does_not_depend_on_corpus_order(self):
        """`max` alone resolves a (heldout, train) tie by list position. Two peers
        with identical scores must yield the same named alternative either way."""
        spec_a = ("aaa-peer", (6, 6), (4, 4), ("h2", "h3"), LLAMA_TOTALS)
        spec_b = ("bbb-peer", (6, 6), (4, 4), ("h2", "h3"), LLAMA_TOTALS)
        lead = ("leader", (6, 6), (4, 4), (), GEMMA_TOTALS)
        one = policy.route_agent("email-triage", _corpus(lead, spec_a, spec_b), None)
        two = policy.route_agent("email-triage", _corpus(lead, spec_b, spec_a), None)
        self.assertEqual(one.escalation_evidence, two.escalation_evidence)
        self.assertIn("aaa-peer", one.escalation_evidence)

    # ------------------------------- SENTENCE 2: the never-escalate price clause
    # ratio>1 half: TestNoiseBand.test_escalation_prices_the_start_is_not_the_leader
    def test_never_escalate_when_the_leader_is_faster_says_so(self):
        """Start is token-cheapest, leader costs more tokens but is FASTER. "costs
        2.0x tokens and 0.5x wall" would sell a speed-up as a cost."""
        corpus = _corpus(
            ("cheap-slow", (6, 6), (4, 4), ("h3",),
             {"total_tokens": 2000, "wall_ms": 80000}),
            ("dear-fast", (6, 6), (4, 4), (), {"total_tokens": 4000, "wall_ms": 40000}),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.start, "cheap-slow")
        self.assertEqual(v.escalation, "never-escalate")
        self.assertIn("MIXED trade", v.escalation_evidence)
        self.assertIn("2.00x tokens (MORE)", v.escalation_evidence)
        self.assertIn("0.50x wall (FASTER)", v.escalation_evidence)
        self.assertNotIn("costs MORE", v.escalation_evidence)

    def test_never_escalate_with_an_unpriced_leader_claims_no_direction(self):
        corpus = _corpus(
            ("cheap", (6, 6), (4, 4), ("h3",), LLAMA_TOTALS),
            ("unpriced-leader", (6, 6), (4, 4), (), None),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.escalation, "never-escalate")
        self.assertIn(policy.COST_UNKNOWN, v.escalation_evidence)
        self.assertNotIn("costs MORE", v.escalation_evidence)
        self.assertNotIn("is CHEAPER", v.escalation_evidence)

    # ------------------------------------- SENTENCE 3: the accuracy pick evidence
    def test_pick_evidence_never_prints_a_negative_lead(self):
        """Leader is 2 heldout cases ahead but 3 TRAIN cases behind. Pre-fix:
        "leads by 2 heldout / -3 train cases"."""
        corpus = _corpus(
            ("hi-heldout", (3, 6), (4, 4), (), LLAMA_TOTALS),
            ("hi-train", (6, 6), (4, 4), ("h2", "h3"), GEMMA_TOTALS),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.accuracy_verdict, "pick")
        self.assertEqual(v.leader, "hi-heldout")
        self.assertIn("2 heldout case(s) BEHIND", v.accuracy_evidence)
        self.assertIn("3 train case(s) AHEAD", v.accuracy_evidence)
        self.assertNotIn("-3", v.accuracy_evidence)

    def test_pick_evidence_names_train_when_train_is_what_separated_them(self):
        """Heldout gap is ZERO and train did the deciding. Pre-fix: "leads by 0
        heldout / 2 train cases — wider than the 1-case noise band"."""
        corpus = _corpus(
            ("weak-train", (4, 6), (4, 4), (), LLAMA_TOTALS),
            ("strong", (6, 6), (4, 4), (), GEMMA_TOTALS),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.accuracy_verdict, "pick")
        self.assertIn("LEVEL on heldout", v.accuracy_evidence)
        self.assertIn("the band is cleared on train", v.accuracy_evidence)
        self.assertNotIn("0 heldout case(s)", v.accuracy_evidence)

    # ----------------------------------------- SENTENCE 4: the cost spread clause
    def test_cost_spread_labels_a_sub_one_wall_ratio(self):
        """The real expense-categorization shape: the token-dearest model is FASTER,
        so the spread carried a bare `0.60x wall` inside a "the call is made on COST"
        frame. Both directions of the pair are asserted here."""
        pricier_and_slower = _corpus(
            ("cheap-fast", (6, 6), (4, 4), (), {"total_tokens": 2000, "wall_ms": 20000}),
            ("dear-slow", (6, 6), (4, 4), (), {"total_tokens": 4000, "wall_ms": 60000}),
        )
        ev = policy.route_agent("email-triage", pricier_and_slower, None).start_evidence
        self.assertIn("2.00x tokens (MORE) and 3.00x wall (SLOWER)", ev)

        cheaper_but_slower = _corpus(
            ("cheap-slow", (6, 6), (4, 4), (), {"total_tokens": 2000, "wall_ms": 60000}),
            ("dear-fast", (6, 6), (4, 4), (), {"total_tokens": 4000, "wall_ms": 20000}),
        )
        ev2 = policy.route_agent("email-triage", cheaper_but_slower, None).start_evidence
        self.assertIn("2.00x tokens (MORE) and 0.33x wall (FASTER)", ev2)

    def test_identical_cost_is_never_a_pick(self):
        """Equal accuracy AND equal cost on both axes: naming a "cheapest" would be a
        coin flip, and the sentence would carry a comparative next to a 1.00x figure.
        Mirrors `diff`'s existing identical-cost refusal."""
        same = {"total_tokens": 2000, "wall_ms": 20000}
        corpus = _corpus(("aaa", (6, 6), (4, 4), (), same),
                         ("bbb", (6, 6), (4, 4), (), dict(same)))
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.start, "")
        self.assertEqual(v.start_basis, policy.CANNOT_DISTINGUISH)
        self.assertIn("cost the SAME", v.start_evidence)

    # ------------------------------------------- SENTENCE 5: MEASURED LOSS framing
    def test_measured_loss_on_a_train_only_exclusion(self):
        """The champion ties the leader on HELDOUT and is excluded by the train arm.
        Pre-fix: "is 0 heldout cases behind the leader (4/4 vs 4/4, 0%) — OUTSIDE the
        1-case noise band" plus a flat "Every contender is ahead of it"."""
        corpus = _corpus(
            ("champ", (3, 6), (4, 4), (), LLAMA_TOTALS),
            ("lead", (6, 6), (4, 4), (), GEMMA_TOTALS),
        )
        v = policy.route_agent("email-triage", corpus, None, champion="champ")
        note = v.champion_note
        self.assertIn("MEASURED LOSS", note)
        self.assertIn("LEVEL on heldout", note)
        self.assertIn("3 train case(s) BEHIND", note)
        self.assertIn("noise band on train", note)     # the axis is named, not assumed
        self.assertIn("MOVE OFF the incumbent", note)
        self.assertNotIn("0 heldout case(s)", note)
        # and the contender claim is derived: `lead` is LEVEL on heldout, not ahead
        self.assertIn("1 are level with it on heldout", note)
        self.assertNotIn("ahead of it on heldout", note)

    def test_measured_loss_contender_buckets_are_counted_not_asserted(self):
        """A contender can be BELOW the champion on heldout and still be in the band
        (the leader is what defines the band). "Every contender is ahead of it" is
        then simply false."""
        corpus = _corpus(
            ("champ", (2, 6), (4, 4), ("h3",), LLAMA_TOTALS),     # 3/4 heldout, 2/6 train
            ("lead", (6, 6), (4, 4), (), GEMMA_TOTALS),           # 4/4
            ("below", (6, 6), (4, 4), ("h2", "h3"), GEMMA_TOTALS),  # 2/4, in band? no
        )
        v = policy.route_agent("email-triage", corpus, None, champion="champ")
        self.assertIn("MEASURED LOSS", v.champion_note)
        # whatever the buckets are, they must sum to the contender count and never
        # over-claim
        self.assertNotIn("Every contender", v.champion_note)


class TestReportIsStable(unittest.TestCase):

    def test_report_is_byte_identical_across_runs(self):
        corpus = _corpus(("a", (6, 6), (4, 4), (), LLAMA_TOTALS),
                         ("b", (6, 6), (4, 4), (), GEMMA_TOTALS))
        v = [policy.route_agent("email-triage", corpus, None)]
        self.assertEqual(policy.report_lines(v, Path("results")),
                         policy.report_lines(v, Path("results")))

    def test_escalation_trigger_is_reported_with_its_n(self):
        corpus = _corpus(
            ("cheap", (6, 6), (4, 4), ("h3",), LLAMA_TOTALS),
            ("dear", (6, 6), (4, 4), (), GEMMA_TOTALS),
        )
        v = policy.route_agent("email-triage", corpus, None)
        self.assertEqual(v.triggers, (("h3", ("dear",)),))
        text = "\n".join(policy.report_lines([v], Path("results")))
        self.assertIn("n=1, single run", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
