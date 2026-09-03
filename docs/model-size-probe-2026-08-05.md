# Model size is not the lever — three models, two families, 3.4× range, same score

**Date:** 2026-08-05 · **Cost:** one 9.3 GB download, ~40 min local inference, €0 · **Lane:** none, main-loop probe

## The question this closes

E25 located a ceiling on `recap` but could not attribute it, and said so:

> ⛔ I first wrote "a capability ceiling of a 4B local model" and that is **NOT shown** — we measured
> `gemma4:e4b-it-qat`, one model. **Whether it is a MODEL-SIZE limit or a property of the task and OUR
> TARGET is untested, and the two imply opposite next moves** (upgrade the model vs. fix the exam).

It also recorded why it couldn't be settled: the biggest model on the box was `qwen3:8b` (8.2B) and the
champion was already 7.5B. That constraint was real but incomplete — `qwen3:14b` is 9.3 GB at Q4_K_M and
fits 16 GB. Nobody had tried.

## Result

| model | family | params | train | **heldout** |
|---|---|---|---|---|
| `gemma4:e4b-it-qat` (champion) | gemma4 | ~4B | 3/7 | **7/10** |
| `qwen3:8b` | qwen3 | 8.2B | 3/7 | **7/10** |
| `qwen3:14b` | qwen3 | 14B | 3/7 | **7/10** |

**Three models. Two families. A 3.4× parameter range. Identical scores, train and heldout.**

`qwen3:8b` vs `qwen3:14b` is the controlled pair — same family, same tokenizer, same prompt, 1.7× size.
It also ties. So the tie is not an artifact of comparing gemma4 to qwen3.

## The mechanism, now visible ACROSS models instead of within one

E25's finding was that one model could be brief or complete, **not both**. Counting which check decided
each failure shows the same trade-off distributed across model sizes:

| model | compression failures | coverage failures |
|---|---|---|
| `qwen3:8b` | **1** | **6** |
| `qwen3:14b` | **5** | **5** |

The 8B writes short: it clears the length bar and **drops items**. The 14B writes longer: it covers more
items and **blows the length bar**. Same family, same exam, opposite failure modes, same score.

Extra capacity was spent on *length*, and length is precisely what the exam penalises. That is why the
score does not move: the models are not at different heights on one axis, they are at different points on
the same trade-off curve.

**One thing the 14B did buy, and it is not nothing:** on `long-day-heldout-xl` the champion **errors out
on truncation**, while the 14B returns a complete 667-char answer and fails honestly on compression +
coverage. Better completion, identical score. If a future exam grades *whether an answer arrived*
separately from *whether it was good*, that difference would show up.

## What follows

1. **Do not buy hardware to raise this score.** A GPU, a VM, or Qwen3.8-27B would have bought the same
   7/10. The earlier "do not rent a VM" call stands, and now for a second, independent reason — that one
   was about sweep cost, this one is about there being nothing to gain.
2. **The lever is the TARGET.** E25 said compression stops being binding and coverage becomes it. This
   confirms it from the other side: make the model longer and you just trade one failure for the other.
   Any real gain has to come from changing what the exam asks for, or from a model that compresses
   better rather than one that is bigger.
3. **E25's open question is answered** in the direction that costs nothing: property of the task and our
   target, not a model-size limit.

## Scope — what is NOT claimed

- **N=1 exam.** This says size does not move `recap`. It says nothing about the coding band, where
  `qwen3:8b` fails by **never terminating** — a failure mode where more capacity plausibly *does* help,
  and which this probe does not test.
- **Three models is not a curve.** It is three points that happen to coincide. A 32B or a frontier model
  could break the pattern; neither fits 16 GB, so neither was tried.
- **Quantisation is uncontrolled.** All three are Q4-class local builds. A full-precision 14B was not tested.

## Reproduce

```sh
ollama pull qwen3:14b
python3 -u sandbox/runner.py run recap --model qwen3:14b --timeout 900
python3 -u sandbox/runner.py run recap --model qwen3:8b  --timeout 900
```

⛔ **`--timeout 900` is load-bearing.** The router default is 120 s. The first attempt at this probe ran
without it and produced zero completed cases — a 14B on a 16 GB M1 Pro exceeds 120 s on a 7,597-char
input, so the run would have reported timeouts as capability failures. **One number would have merged two
opposite causes**, which is ledger 018's lesson repeating. Killed and rerun rather than interpreted.
