# pass^3 column — consistency as a reported score — DESIGN 2026-09-28, NOT FIRED (no inference needed)

**Why.** pass^k (τ-bench, arXiv 2406.12045) is the standard reliability metric in 2026; our rule-A "stable across 3 loads"
already IS pass^3 for local models, and the pin probe holds 6 runs for GLM/Kimi. Post 1 must call it pass^k, not "our
consistency score". Saying it in the results table makes the flip finding a column instead of a blog anecdote.

## Shape (CPU, from files on disk)

- Local: from every `evals/*/snapshot.json` (3 loads): pass^3 = share of held-out cases passed on all 3 loads; plus the
  count of unstable cases. Expect pass^3 = heldout score (0 unstable measured 7 Sep) — that identity is the point.
- Hosted: from `docs/probes/provider-pin-day1-2026-09-01/results/D` (6 runs): pass^3 over pinned reps and pass^6 over all,
  per exam, GLM and Kimi. From the 27 Sep matrix: not computable (one pass) → the column reads "1 run" until the three
  same-day repeats (queue item, ≈$20).
- Output: `build_tables.py` gains a `pass^k` column (k stated per row) and an `unstable` count; `docs/tiers-and-results-table.md`
  gets the rule: a tier letter needs pass^3.

**Registered prediction:** GLM pass^6 on transcript-en ≤ 0.60 of the single-run score; local pass^3 = single-run score exactly.
**Kill:** none — a table build; `build_tables.py` is score-consuming (cline-safe), the tier rule is a doc edit.
