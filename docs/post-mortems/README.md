# Post-mortems — three times the instrument was wrong, and what changed

> Picked from the private build ledger (one entry per merged change, written at merge time). Each one follows the same shape:
> what we believed, what the probe showed, what changed in the code or the rules. Scrubbed of nothing but internal references.

| # | title | the belief | the fix |
|---|---|---|---|
| 1 | [The window, not the weights](01-the-window-not-the-weights.md) | "the 4B can't handle long inputs" | measure the infrastructure before writing a capability verdict |
| 2 | [The gate said ok while five verdicts moved](02-the-gate-said-ok.md) | an aggregate regression check is a gate | per-case comparison, three loads, a runtime stamp |
| 3 | [A green gate that cannot go red](03-a-green-gate-that-cannot-go-red.md) | "the tests pass" | a check earns its place only after it has been seen failing |

The rule that all three share: **presence is not effect.** A thing can be present, wired and green, and do nothing. Test the effect through the real entry point, and build the input that makes the check fire before trusting the day it stays quiet.
