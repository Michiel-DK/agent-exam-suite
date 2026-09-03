"""E21 — long-input STRATEGY bake-off. The first experiment here whose subject is OUR
OWN architecture rather than a vendor's model.

THE FINDING THAT CREATED IT. recap's champion fails EVERY long case the same way:
4292 / 5520 / 6550 / 7597 chars all fail `check_compression`. The intuitive fix — a
bigger context window — was MEASURED and does not work: at num_ctx=8192 the longest case
returns complete JSON and still fails compression alone. The model can SEE the whole day;
it will not COMPRESS one. So the lever is not context size, it is what we feed the model.

THE ONE INVARIANT THIS FILE EXISTS TO PROTECT
---------------------------------------------
A strategy changes what the MODEL SEES. It never changes what the SCORER sees.

`evals/recap/properties.py` resolves a case's expectations by EXACT INPUT TEXT. Score a
filtered or chunked day and the lookup misses, `_exp()` returns {}, and `must_mention`,
`max_ratio` and `nothing_important` ALL pass vacuously — every strategy would post a
perfect score while measuring nothing. That is this repo's most-repeated failure shape
(ledger 006-008, 014, 015) and it would be silent here.

So every strategy returns only an OUTPUT; `cmd_bakeoff` always scores it against the
ORIGINAL committed `case["input"]`. `test_bakeoff.py` pins this by name.

Scoring against the original is also the only FAIR comparison: `check_compression`'s limit
is `max_ratio x len(input)`, so scoring a filter-then-recap run against its own shortened
input would hand it a TIGHTER budget than single-shot faced, not an easier one.
"""
import re

ITEM_RE = re.compile(r"^--- item \d+ ---\s*$", re.MULTILINE)


def split_items(day: str) -> list[str]:
    """A day -> its items, each 'From: ...\\nSubject: ...\\nbody', headers dropped.

    Round-trips with join_items for a committed recap case; a day with no item markers
    comes back as one item, which is the honest degenerate reading rather than a crash.
    """
    parts = [p.strip() for p in ITEM_RE.split(day)]
    return [p for p in parts if p]


def join_items(items: list[str]) -> str:
    """Items -> a day in the exact shape the recap prompt was written against."""
    return "\n\n".join(f"--- item {i} ---\n{t}" for i, t in enumerate(items, 1))


# --------------------------------------------------------------------- strategies
# Each takes (ctx, case) and returns (parsed_output, metrics_list). `ctx` carries the
# call machinery so this module never imports runner (which imports this one).


def single_shot(ctx, case):
    """BASELINE — the whole day in one prompt. What ships today."""
    parsed, metrics = ctx.call_recap(case["input"])
    return parsed, [metrics]


def filter_then_recap(ctx, case):
    """Run email-triage over each item, DROP everything it labels `ignore`, recap the rest.

    Composes two agents we already own and already measure — the whole point: the failing
    long cases are ~2/3 noise, and email-triage's entire job is naming noise.

    Cost is 1 call per item + 1, which is the expensive strategy by construction. That is
    a finding, not a defect: it is what the architecture costs.

    If the filter drops EVERYTHING, the day is passed through unfiltered rather than
    handing the model an empty prompt — an empty day would score as a trivially-abstaining
    pass on quiet cases and tell us nothing.
    """
    items = split_items(case["input"])
    metrics = []
    kept = []
    dropped = 0
    for item in items:
        label, m = ctx.call_triage(item)
        metrics.append(m)
        if label == "ignore":
            dropped += 1
        else:
            kept.append(item)
    day = join_items(kept) if kept else case["input"]
    parsed, m = ctx.call_recap(day)
    metrics.append(m)
    parsed["_strategy_note"] = f"dropped {dropped}/{len(items)} items as ignore"
    return parsed, metrics


def chunk_and_reduce(ctx, case, chunk_size=6):
    """Recap items in batches, then recap the batch recaps.

    The risk this strategy carries is detail loss at the reduce step, and the cases that
    should expose it are the ones with multi-item coverage floors (Lane A2). A day short
    enough to fit one chunk degenerates to single-shot, which is correct, not a bug.
    """
    items = split_items(case["input"])
    metrics = []
    if len(items) <= chunk_size:
        return single_shot(ctx, case)
    partials = []
    for i in range(0, len(items), chunk_size):
        parsed, m = ctx.call_recap(join_items(items[i:i + chunk_size]))
        metrics.append(m)
        text = (parsed or {}).get("recap") or ""
        if text.strip():
            partials.append(text.strip())
    reduced_day = join_items([f"From: partial-recap\nSubject: batch {i}\n{p}"
                              for i, p in enumerate(partials, 1)])
    parsed, m = ctx.call_recap(reduced_day)
    metrics.append(m)
    parsed["_strategy_note"] = f"{len(partials)} partials over {len(items)} items"
    return parsed, metrics


_NUM_RE = re.compile(r"\d[\d.,]*\d|\d")
_FROM_RE = re.compile(r"^From:\s*(\S+)", re.MULTILINE)
_SUBJ_RE = re.compile(r"^Subject:\s*(.+)$", re.MULTILINE)


def extract_then_write(ctx, case):
    """Pull sender, subject and figures DETERMINISTICALLY; hand the model a fact list.

    The hypothesis: grounding should IMPROVE because the figures are handed over rather
    than recalled, and compression should improve because the model never sees the prose
    it keeps wanting to restate.

    The extractor is deliberately dumb (regex, no model) — if a smart extractor were
    needed, that would be a different strategy with a different cost.
    """
    facts = []
    for item in split_items(case["input"]):
        sender = (_FROM_RE.search(item) or [None, "?"])[1] if _FROM_RE.search(item) else "?"
        subj = (_SUBJ_RE.search(item).group(1).strip() if _SUBJ_RE.search(item) else "?")
        nums = sorted(set(_NUM_RE.findall(item)))
        line = f"- {sender} | {subj}"
        if nums:
            line += f" | figures: {', '.join(nums)}"
        facts.append(line)
    compact = ("Below is a DECODED fact list for one day — one line per message, already "
               "extracted. Write the recap from these facts.\n\n" + "\n".join(facts))
    parsed, m = ctx.call_recap(compact)
    parsed["_strategy_note"] = f"{len(facts)} facts extracted"
    return parsed, [m]


STRATEGIES = {
    "single-shot": single_shot,
    "filter-then-recap": filter_then_recap,
    "chunk-and-reduce": chunk_and_reduce,
    "extract-then-write": extract_then_write,
}
