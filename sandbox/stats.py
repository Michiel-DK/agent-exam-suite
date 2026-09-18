"""Interval and paired-comparison statistics for exam scores — the SINGLE implementation
(A3, LIVE-ROUTING follow-up). `route`, `diff` and the scoreboard all import from here;
nothing recomputes an interval in JavaScript or by hand (the numnorm lesson: two copies
of one statistic drift).

What these numbers can and cannot do, stated once:
  * `wilson` gives the 95% score interval for k passes of n. With this suite's heldout
    sizes (9–18) an interval is 0.3–0.4 wide — it FORMALISES "cannot-distinguish", it
    does not create ranking power. Growing n does.
  * `paired` compares two models on the SAME cases (the exam is paired by construction:
    every model sees identical inputs at temp 0). Only DISCORDANT cases carry
    information — cases both pass or both fail say nothing about which is better. The
    exact two-sided sign test on the discordant counts is the honest p-value; the
    1-case noise band in policy.py stays THE decision rule, this annotates it.
Pure functions, deterministic, no dependencies beyond math.
"""
from __future__ import annotations

import math

Z95 = 1.959964  # two-sided 95%


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes of n. Returns (lo, hi) in [0, 1].
    n == 0 -> (0.0, 1.0): no information, the widest honest answer, never a crash."""
    if n <= 0:
        return (0.0, 1.0)
    if not 0 <= k <= n:
        raise ValueError(f"wilson: k={k} must be within 0..n={n}")
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def fmt_ci(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"95% CI {lo:.2f}–{hi:.2f}"


def paired(fail_a: set, fail_b: set) -> dict:
    """Paired comparison of model A vs model B from their FAILED heldout case-id sets.
    a_only = cases only A fails (B's wins), b_only = cases only B fails (A's wins).
    p = exact two-sided sign test on the discordant cases (H0: each discordant case is
    a coin flip). With zero discordant cases there is nothing to test: p = 1.0 and
    the verdict is 'identical on every case'."""
    a_only = sorted(set(fail_a) - set(fail_b))
    b_only = sorted(set(fail_b) - set(fail_a))
    n_d = len(a_only) + len(b_only)
    if n_d == 0:
        p = 1.0
    else:
        x = min(len(a_only), len(b_only))
        tail = sum(math.comb(n_d, i) for i in range(0, x + 1)) / 2 ** n_d
        p = min(1.0, 2 * tail)
    return {"a_only_fails": a_only, "b_only_fails": b_only, "discordant": n_d, "p": p}


def fmt_paired(name_a: str, name_b: str, fail_a: set, fail_b: set) -> str:
    r = paired(fail_a, fail_b)
    if r["discordant"] == 0:
        return f"{name_a} vs {name_b}: identical verdict on every heldout case (0 discordant)"
    return (f"{name_a} vs {name_b}: {len(r['b_only_fails'])} case(s) only {name_b} fails, "
            f"{len(r['a_only_fails'])} only {name_a} fails — {r['discordant']} discordant, "
            f"sign-test p={r['p']:.3f}"
            + (" (not distinguishable at 0.05)" if r["p"] > 0.05 else " (distinguishable at 0.05)"))


# ------------------------------------------------- selection denominator (S-2026-09-11)
# A champion is the argmax of a model x exam matrix, and until 2026-09-15 no report said
# how many candidates that argmax ran over. The best of N noisy estimates is biased
# upward, and N-1 paired tests against one leader inflate the family-wise error — the
# same selection mechanism that inflates a backtest (Bailey/Borwein/Lopez de Prado;
# docs/2026-09-11-routing-competitive-scan-and-selection-bias.md section 3). These two
# functions make the count a printed number next to every pick. They ANNOTATE: the
# noise band stays the decision rule in policy.py and the accuracy key stays the rule
# in runner.diff_recommendation — a pick is never flipped here, only its width shown.

ALPHA = 0.05


def bonferroni(n_comparisons: int, alpha: float = ALPHA) -> float:
    """Family-wise threshold for n paired comparisons against one leader: alpha / n."""
    if n_comparisons < 1:
        raise ValueError(f"bonferroni: n_comparisons={n_comparisons} must be >= 1")
    return alpha / n_comparisons


def fmt_comparisons(n_candidates: int, p: float | None = None) -> str:
    """One line: how many candidates the leader was chosen FROM (itself included), the
    corrected threshold that follows, and — when the deciding paired sign-test p is
    given — whether that p still clears it. p is the leader-vs-runner-up test; pass
    None when no single test decided the pick (a tie broken on cost, or a
    cannot-distinguish verdict)."""
    if n_candidates < 1:
        raise ValueError(f"fmt_comparisons: n_candidates={n_candidates} must be >= 1")
    if n_candidates == 1:
        return ("compared: 1 candidate — no comparison was made, so nothing here is a "
                "pick and no selection bias applies")
    n_cmp = n_candidates - 1
    # The WORD is decided from the same rounded figures that are printed (the repo's
    # cost_move rule): p and the threshold both at 4 dp, compared after rounding, so
    # the digits beside the word can never disagree with it. Correctness refuter,
    # 2026-09-15: p=0.0034 printed as "0.003" next to "0.0033 ... NOT distinguishable".
    # "pick" is deliberately absent — this line also prints under cannot-distinguish.
    thr = round(bonferroni(n_cmp), 4)
    head = (f"compared: {n_candidates} candidates — the top-ranked score is the maximum "
            f"of {n_candidates} noisy estimates (biased upward); {n_cmp} paired "
            f"comparison(s) against it, Bonferroni threshold {ALPHA}/{n_cmp} = {thr:.4f}")
    if p is None:
        return head
    p = round(p, 4)
    word = "distinguishable" if p <= thr else "NOT distinguishable"
    return head + f"; the deciding sign-test p={p:.4f} is {word} after correction"
