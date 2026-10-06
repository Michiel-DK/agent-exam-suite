# Post-mortem 3 — A green gate that cannot go red (September 2026)

**What we believed.** "The tests pass." A build lane named `python3 -m pytest -q` as its gate; it reported "8 passed".

**What the probe showed.** Most test files in this repo record a failure by appending to a list and return the verdict as the
exit code of `main()`; no `assert` sits inside any test. pytest collects every `def test_*`, sees no exception, and prints
"N passed" **by construction**. Reproduced in one line: a file whose check says `1 == 2` is "1 passed" under pytest and exit
code 1 under `python3 <file>`. The lane had named a gate that cannot go red.

The same review found a second thing that was present and inert: a bake-off harness handed every strategy the full case
dictionary, **answer key included**. Nothing stopped a strategy from reading the expected commitments and topping up its own
output; the score would have moved the right way while measuring nothing. The only guard was a sentinel test per strategy
whose injection had been seen failing.

**What changed.** The gate is a shell script that runs every test file as its own process and captures the exit code at once;
pytest is only the public clone's CI, and its green carries the same blind spot, which the README now says. Three rules entered
the project file: *a green guard proves nothing until seen red* — build the attacker's input by hand and run it; *a new check
earns its place only if some case isolates it* — name one case that passes every other check and fails only the new one; and
*presence is not effect* — a `num_ctx` accepted and ignored, a judge module imported and dormant, a test-count floor counting
7 of 428 assertions because it grepped for the word `assert`, all green, all doing nothing.

**The transferable rule.** Before trusting a check, make it fail on purpose. Two adversarial tests here had looked green while
asserting nothing; a count floor only catches a net decrease, so deleting a real test and adding a stub keeps it green. The
cost of the habit is minutes; the cost of its absence was three shipped checks that could not fail.
