"""A3 — interval + paired-test witnesses (sandbox/stats.py and its three consumers).

Numbers are pinned to HAND-COMPUTED values, not to the function's own output:
  Wilson 14/18 at z=1.959964 -> (0.5479, 0.9100); 9/9 -> (0.7009, 1.0); 0/10 -> (0, 0.2775)
  sign test: 4 vs 1 discordant -> p = 2*(C(5,0)+C(5,1))/32 = 0.375; 6 vs 0 -> 2/64 = 0.03125
Every consumer test names the wrong build it catches. Plain unittest, no inference.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import policy  # noqa: E402
import stats  # noqa: E402


class TestWilson(unittest.TestCase):
    def test_hand_values(self):
        lo, hi = stats.wilson(14, 18)
        self.assertAlmostEqual(lo, 0.5479, places=4)
        self.assertAlmostEqual(hi, 0.9100, places=4)
        lo, hi = stats.wilson(9, 9)
        self.assertAlmostEqual(lo, 0.7009, places=4)
        self.assertEqual(hi, 1.0)
        lo, hi = stats.wilson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=4)

    def test_width_is_the_point(self):
        """The statistic's job here is to SHOW the width: on this suite's heldout sizes
        two models one case apart always overlap. WRONG BUILD: a normal-approximation
        interval that collapses to a point at 9/9 (p̂(1-p̂)=0)."""
        for n in (9, 10, 11, 13, 18):
            a = stats.wilson(n - 1, n)
            b = stats.wilson(n, n)
            self.assertLess(a[0], b[1])          # overlap
            self.assertGreater(b[1] - b[0], 0.15)  # never a point at n/n (18/18 is 0.18 wide)

    def test_edges(self):
        self.assertEqual(stats.wilson(0, 0), (0.0, 1.0))
        with self.assertRaises(ValueError):
            stats.wilson(5, 4)


class TestPaired(unittest.TestCase):
    def test_hand_values(self):
        r = stats.paired({"a", "b", "c", "d"}, {"x"})
        self.assertEqual((r["discordant"], r["p"]), (5, 0.375))
        r = stats.paired({"a", "b", "c", "d", "e", "f"}, set())
        self.assertEqual((r["discordant"], r["p"]), (6, 0.03125))
        self.assertEqual(r["a_only_fails"], ["a", "b", "c", "d", "e", "f"])

    def test_concordant_cases_carry_no_information(self):
        """WRONG BUILD: an unpaired test on the two fractions. Two models that fail
        the SAME 4 cases are identical (p=1, 0 discordant) even though a naive
        reading of 14/18 vs 14/18 says nothing about that."""
        same = {"c1", "c2", "c3", "c4"}
        r = stats.paired(same, set(same))
        self.assertEqual((r["discordant"], r["p"]), (0, 1.0))
        # and 14/18 vs 14/18 with DISJOINT failures is 8 discordant, 4-4 -> p = 1.0 too,
        # but for the opposite reason (balanced), which fmt_paired must say
        r = stats.paired({"c1", "c2", "c3", "c4"}, {"d1", "d2", "d3", "d4"})
        self.assertEqual(r["discordant"], 8)
        self.assertEqual(r["p"], 1.0)

    def test_symmetry(self):
        a, b = {"a", "b", "c"}, {"z"}
        self.assertEqual(stats.paired(a, b)["p"], stats.paired(b, a)["p"])

    def test_fmt_paired_names_direction(self):
        line = stats.fmt_paired("champ", "chall", {"m", "n"}, {"n"})
        self.assertIn("0 case(s) only chall fails, 1 only champ fails", line)   # champ fails m, chall does not
        self.assertIn("not distinguishable", line)
        self.assertIn("identical verdict", stats.fmt_paired("a", "b", {"x"}, {"x"}))


def _run(model, passed, total, failed, train=(6, 6)):
    return policy.Run(agent="t", model=model, provider="ollama", file=f"{model}.json",
                      train_passed=train[0], train_total=train[1],
                      heldout_passed=passed, heldout_total=total,
                      heldout_failed=tuple(sorted(failed)),
                      cost=policy.Cost(known=False, tokens=None, wall_ms=None, reason="test"))


class TestRouteCarriesTheStats(unittest.TestCase):
    """The route report must print an interval per band member and a paired line per
    contender, derived from Run.heldout_failed. WRONG BUILD: stats computed from the
    fractions only (no paired line), or the field present but never printed."""

    def _verdict(self, runs):
        key = tuple(f"c{i}" for i in range(18))
        rk = [(key, r) for r in runs]
        return policy.route_agent("t", rk, key)

    def test_cannot_distinguish_prints_interval_and_paired_lines(self):
        v = self._verdict([_run("A", 15, 18, {"c1", "c2", "c3"}),
                           _run("B", 14, 18, {"c1", "c2", "c3", "c4"})])
        self.assertEqual(v.accuracy_verdict, policy.CANNOT_DISTINGUISH)
        text = "\n".join(policy.report_lines([v], Path("results")))
        self.assertIn("A 15/18 heldout [95% CI 0.61–0.94]", text)
        self.assertIn("B 14/18 heldout [95% CI 0.55–0.91]", text)
        self.assertIn("A vs B: 1 case(s) only B fails, 0 only A fails — 1 discordant, sign-test p=1.000", text)

    def test_a_pick_still_shows_its_own_width(self):
        """A 3-case lead on n=18 is a 'pick' by the noise band — and p=0.25 by the
        sign test. Both must be visible; the band decides, the p annotates."""
        v = self._verdict([_run("A", 16, 18, {"c1", "c2"}),
                           _run("B", 13, 18, {"c1", "c2", "c3", "c4", "c5"})])
        self.assertEqual(v.accuracy_verdict, "pick")
        text = "\n".join(policy.report_lines([v], Path("results")))
        self.assertIn("B 13/18 heldout [95% CI", text)
        self.assertIn("3 discordant, sign-test p=0.250 (not distinguishable at 0.05)", text)

    def test_report_is_still_deterministic(self):
        v = self._verdict([_run("A", 15, 18, {"c1"}), _run("B", 15, 18, {"c2"})])
        self.assertEqual(policy.report_lines([v], Path("results")),
                         policy.report_lines([v], Path("results")))


class TestComparisons(unittest.TestCase):
    """The selection denominator (docs/2026-09-11 ... section 3). Hand values:
    7 discordant cases all one way -> p = 2*C(7,0)/2^7 = 0.015625; Bonferroni over 4
    comparisons = 0.05/4 = 0.0125, over 1 = 0.05."""

    def test_bonferroni_hand_values_and_fail_loud(self):
        self.assertEqual(stats.bonferroni(4), 0.0125)
        self.assertEqual(stats.bonferroni(1), 0.05)
        with self.assertRaises(ValueError):
            stats.bonferroni(0)
        with self.assertRaises(ValueError):
            stats.fmt_comparisons(0)

    def test_same_p_flips_only_on_the_candidate_count(self):
        """THE isolating case: identical deciding p, only N changes. WRONG BUILD: a
        line that prints the count but compares p against a fixed 0.05 (presence
        without effect)."""
        p = stats.paired(set(), {"h0", "h1", "h2", "h3", "h4", "h5", "h6"})["p"]
        self.assertAlmostEqual(p, 0.015625)
        five = stats.fmt_comparisons(5, p)
        two = stats.fmt_comparisons(2, p)
        self.assertIn("compared: 5 candidates", five)
        self.assertIn("Bonferroni threshold 0.05/4 = 0.0125", five)
        self.assertIn("p=0.0156 is NOT distinguishable after correction", five)
        self.assertIn("compared: 2 candidates", two)
        self.assertIn("Bonferroni threshold 0.05/1 = 0.0500", two)
        self.assertIn("p=0.0156 is distinguishable after correction", two)
        self.assertNotIn("NOT", two)

    def test_word_is_decided_from_the_printed_digits(self):
        """Correctness refuter 2026-09-15: at 3 dp, p=0.0034 printed as 0.003 beside a
        0.0033 threshold and the word "NOT distinguishable" — digits contradicting the
        word. Now both print at 4 dp and the word is derived from those rounded values.
        Hand values: 16 candidates -> 0.05/15 = 0.00333.. -> 0.0033; p = 0.003418."""
        line = stats.fmt_comparisons(16, 0.003418)
        self.assertIn("threshold 0.05/15 = 0.0033", line)
        self.assertIn("p=0.0034 is NOT distinguishable", line)
        # Rounded-equal reads as clearing the bar — the printed digits are the rule.
        self.assertIn("p=0.0033 is distinguishable", stats.fmt_comparisons(16, 0.00334))
        # The line never claims a pick: it also prints under cannot-distinguish.
        self.assertNotIn("pick", stats.fmt_comparisons(12))

    def test_no_p_means_no_claim_and_one_candidate_is_no_pick(self):
        line = stats.fmt_comparisons(3)
        self.assertIn("compared: 3 candidates", line)
        self.assertNotIn("sign-test", line)
        self.assertIn("no comparison was made", stats.fmt_comparisons(1))


class TestServePayload(unittest.TestCase):
    def test_results_endpoint_serves_ci95_from_the_single_implementation(self):
        """Functional and SELF-SUFFICIENT (the refuter caught a skipTest on a clean
        checkout — results/ is gitignored, so the guard never ran): a temp ROOT with
        its own results/*.json fixture, serve.Handler on an ephemeral port, GET
        /api/results. Every row carries ci95 == stats.wilson(passed, total); the
        fixture file on disk is untouched (view-only key). WRONG BUILD: interval
        recomputed in index.html (a second implementation) — index.html must only
        RENDER ci95."""
        import http.client
        import tempfile
        import threading
        from http.server import HTTPServer
        import serve
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "results").mkdir()
            fixture = root / "results" / "t__ollama__m.json"
            fixture.write_text(json.dumps({"agent": "t", "provider": "ollama", "model": "m",
                                           "train": {"passed": 6, "total": 6},
                                           "heldout": {"passed": 14, "total": 18, "score": 0.7778},
                                           "cases": []}))
            before = fixture.read_bytes()
            saved = serve.ROOT
            serve.ROOT = root
            srv = HTTPServer(("127.0.0.1", 0), serve.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
                conn.request("GET", "/api/results")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                rows = json.loads(resp.read())
            finally:
                srv.shutdown()
                serve.ROOT = saved
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["heldout"]["ci95"], list(stats.wilson(14, 18)))
            self.assertAlmostEqual(rows[0]["heldout"]["ci95"][0], 0.5479, places=4)
            self.assertEqual(fixture.read_bytes(), before, "results files must not be rewritten")
        html = (ROOT / "frontend" / "index.html").read_text()
        self.assertIn("ci95", html)
        self.assertNotIn("Math.sqrt", html, "index.html must render ci95, never compute an interval")


if __name__ == "__main__":
    unittest.main()
