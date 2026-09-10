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


# --------------------------------------------------------------- E28 commit-list-then-write
#
# THE FINDING THIS TESTS. transcript-en's long-call band (>=12,000 chars) fails only by
# OMISSION — 1-2 of ~7 commitments dropped, never invented (ledger 043). The literature's
# fix for omission under long context is a two-step pipeline: list every commitment first,
# in a call whose ONLY job is finding them, then write the deliverable from that list in a
# second call (Kirstein 2025; docs/research/long-transcript-omission-2026-09-08.md).
#
# EXTRACT_SYSTEM_PROMPT is call 1's system prompt. It is a strategy-owned constant, not an
# agents/ file, because this strategy is an experiment over the champion's OWN prompt, not
# a second shipped agent.
EXTRACT_SYSTEM_PROMPT = """You read one business call transcript between a REP (our side) \
and a CUSTOMER (or PROSPECT), with speaker labels. Your only job is to find every \
commitment made on the call — do not summarise, do not write action items, do not judge \
importance.

Include EVERY promise, delivery, confirmation, or follow-up that EITHER side makes,
however small. If a proposal is later withdrawn or superseded during the same call, still
list it, but set "withdrawn": true for that entry.

For each commitment, copy its evidence line VERBATIM from the transcript — never
paraphrase, shorten, or reword it. The evidence line must be text that actually appears in
the transcript.

Reply with ONLY a JSON object, no other text:

{"commitments": [{"speaker": "rep" or "customer", "item": "<what was committed, in your \
own words>", "evidence": "<verbatim line from the transcript>", "withdrawn": true or \
false}]}

An empty list is correct only when the call truly produced no commitment from either
side."""

# Call 2's header, prepended to the surviving commitment list. "MUST appear ... unless
# withdrawn" is the instruction the whole strategy exists to test: whether handing the
# champion its own extracted list closes the omission gap that reading the transcript
# once did not.
_REQUIRED_HEADER = (
    "The following commitments were extracted from this call. Each one MUST appear as "
    "an action item with its owner first, unless it is marked withdrawn. Add nothing "
    "that is not in the transcript."
)


def _ws_norm(s: str) -> str:
    """casefold + collapse-whitespace, used ONLY for the grounding-filter PRESENCE check
    below (an extracted evidence line must be found in the transcript). Per CLAUDE.md
    gotcha 4 (normalization is directional), this helper is private to this strategy and
    is never reused for an ABSENCE check anywhere else in the suite."""
    return " ".join(s.split()).casefold()


def _ground_commitments(raw_commitments, transcript: str):
    """Deterministic filter, no model call. Drops any entry that is not a dict, or whose
    `evidence` or `item` is missing / not a string, or whose `evidence` does not survive
    as a substring of the transcript under whitespace/case normalization. Never raises —
    a malformed entry is dropped and counted, not fatal to the case.

    Returns (survivors, extracted_count, dropped_count) where survivors keep the
    `withdrawn` flag (defaulting False) and the verbatim `evidence` string (E30: the
    supersession rules below need it — `_is_cancellation` matches against evidence too,
    since the cancel wording sometimes lands there and not in `item`) for the
    required-block builder / E30 pipeline below.
    """
    if not isinstance(raw_commitments, list):
        return [], 0, 0
    extracted = len(raw_commitments)
    norm_transcript = _ws_norm(transcript)
    survivors = []
    for c in raw_commitments:
        if not isinstance(c, dict):
            continue
        item, evidence = c.get("item"), c.get("evidence")
        if not isinstance(item, str) or not item.strip():
            continue
        if not isinstance(evidence, str) or not evidence.strip():
            continue
        if _ws_norm(evidence) not in norm_transcript:
            continue
        # Never STAMP an owner the model didn't give — an invented "rep"/"customer"
        # label would itself be a fabrication, and "owner attribution unchanged" is
        # part of E28's pre-registered prediction, so a wrong owner tag would be a
        # self-inflicted confound in the evening read. An unrecognised/missing
        # speaker survives with speaker=None; _required_block below emits it with
        # no owner tag rather than guessing one.
        # Case-insensitive on purpose: the prompt prose says REP/CUSTOMER in caps and
        # the schema says "rep"/"customer" — a model echoing "REP" must not silently
        # lose the owner tag the evening run is measuring (refuter caveat, PR #85).
        raw_speaker = c.get("speaker")
        speaker = (raw_speaker.strip().casefold()
                   if isinstance(raw_speaker, str)
                   and raw_speaker.strip().casefold() in ("rep", "customer") else None)
        survivors.append({"speaker": speaker, "item": item, "evidence": evidence,
                          "withdrawn": bool(c.get("withdrawn"))})
    return survivors, extracted, extracted - len(survivors)


def _required_block(survivors) -> str:
    """Call 2's user-text suffix built ONLY from `survivors` (already grounded against
    the transcript in `_ground_commitments`) — never from case['expected']."""
    lines = [_REQUIRED_HEADER]
    for s in survivors:
        prefix = f"[{s['speaker']}] " if s["speaker"] else ""
        line = f"- {prefix}{s['item']}"
        if s["withdrawn"]:
            line += " — WITHDRAWN, do not list as an action item"
        lines.append(line)
    return "\n".join(lines)


def commit_list_then_write(ctx, case):
    """E28 — extract every commitment first, then write from the grounded list.

    Call 1 (EXTRACT_SYSTEM_PROMPT, case['input'] verbatim) asks only for a commitment
    list. A deterministic filter (no model, no case['expected'] — grounded ONLY against
    the transcript text) drops anything unparseable or not actually in the call. Call 2
    (the champion's own agent.system_prompt) gets the ORIGINAL transcript plus a required-
    commitments block built only from the surviving list, so the output schema
    (summary/action_items) is unchanged and the scorer sees the normal shape.

    Degrades, never fabricates: a non-dict or commitments-less call-1 reply is treated as
    zero commitments extracted (survivors=[]) — call 2 still runs, with the header alone
    (chosen over omitting the block entirely, so call 2's shape never depends on whether
    call 1 degraded). Nothing is raised for a malformed extraction; that is this probe's
    subject, not a defect to hide.

    Never calls split_items — transcript-en transcripts carry no `--- item N ---`
    markers; that is a recap-only convention.

    case['expected'] (must_commit / commit_owner / must_not_commit — the scorer's answer
    key) is NEVER read here. cmd_bakeoff hands every strategy the full committed case
    dict, but everything that reaches call 2 or the return value traces only to
    case['input'] and call 1's own reply. See test_bakeoff.py T-G.
    """
    transcript = case["input"]
    parsed1, metrics1 = ctx.call(EXTRACT_SYSTEM_PROMPT, transcript)
    raw_commitments = (parsed1 or {}).get("commitments") if isinstance(parsed1, dict) else None
    survivors, extracted, dropped = _ground_commitments(raw_commitments, transcript)
    withdrawn = sum(1 for s in survivors if s["withdrawn"])

    user_text = transcript + "\n\n" + _required_block(survivors)
    parsed2, metrics2 = ctx.call(ctx.agent["system_prompt"], user_text)
    if isinstance(parsed2, dict):
        parsed2["_strategy_note"] = f"extracted={extracted} dropped={dropped} withdrawn={withdrawn}"
    print(f"  [commit-list-then-write] {case['id']} extracted={extracted} "
          f"dropped={dropped} withdrawn={withdrawn}", flush=True)
    return parsed2, [metrics1, metrics2]


# --------------------------------------------------------------- E30 extract-then-assemble
#
# THE FINDING THIS TESTS. E28 (refuted): handing the champion its own extracted commitment
# list and asking it to WRITE the action items from that list still drops one — the model
# reads well and writes badly (docs/probes/e28-commit-list-2026-09-08/RESULTS.md). E28b
# probe 2 (docs/probes/e28b-extraction-recall-2026-09-09/): a supersession-aware EXTRACTION
# prompt gets recall 12/12 and leak 2/3 — the model still lists a cancelled commitment on
# one call of three. So this strategy stops asking the model to write the list at all: the
# model extracts (call 1), deterministic code applies the supersession/dedupe rules and
# ASSEMBLES the final action-item strings, and the model's own summary call (call 2, byte-
# identical to single-shot) never sees the list — its own `action_items` are discarded.
#
# STOPWORDS is ONE list, shared by every content-token computation in this block (CLAUDE.md
# gotcha 4: presence and absence checks must never diverge on normalization — here there is
# only one direction, "does this token carry meaning", so one shared set is correct, not a
# violation). It carries the round-3 criterion fix: role nouns (customer/representative/
# rep/client) are stopwords too, because content tokens are computed on the SUBJECT-STRIPPED
# item — without both changes, "the representative will draft the MSA" and "the customer
# will get budget approval" share nothing but the leaked role noun, and supersession eats
# real commitments (round-2 criterion catch, hand-verified against the probe-2 renewal
# fixture in the E30 brief).
STOPWORDS = frozenset({
    "send", "share", "schedule", "confirm", "follow", "today", "week", "friday",
    "thursday", "wednesday", "monday", "tuesday", "call", "email", "document", "team",
    "lead", "after", "before", "with", "from", "that", "this", "will", "over", "once",
    "next", "their", "your", "about", "them", "they", "have", "make", "sure", "also",
    "internally", "regarding",
    "customer", "representative", "rep", "client",
})

_SUBJECT_RE = re.compile(r"^(the )?(rep|representative|customer|client)"
                          r"( will| to| is| are)?\s+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z]+")

# Verbatim from docs/probes/e28b-extraction-recall-2026-09-09/probe2_prompt_supersession.py
# (probe 2, the "one that cleared 2/3 by prompt alone" — kept here as a value, not an
# import, so this file has no dependency on a probe script's path).
SUPERSESSION_RULES = """

Three rules that override anything above:
1. A commitment that is later cancelled, withdrawn or superseded in the call gets "withdrawn": true ON THAT COMMITMENT. Do NOT add a separate entry for the sentence that cancels it.
2. A request or question ("could you send...", "is there any chance of...") is NOT a commitment. List only the reply that promises the action, as one entry owned by the party who will do it.
3. One entry per distinct commitment. If a speaker restates or summarises commitments already listed, do not list them again.
"""

ITEM_FORMAT_RULE = ('\n4. Write each "item" as a bare verb phrase with no subject, e.g. '
                     '"send the revised quote by Thursday" — never "The rep will send...".\n')

EXTRACT_SYSTEM_PROMPT_V2 = EXTRACT_SYSTEM_PROMPT + SUPERSESSION_RULES + ITEM_FORMAT_RULE

# Whole-word, casefold-insensitive, inflection-tolerant. Round-1 criterion catch: a literal
# "hold off" list missed "is HOLDING off" — inflections needed, checked against BOTH the
# item text and its verbatim evidence line (the cancel wording sometimes lands in the
# evidence — "no need to draft anything extra" — and not in the item itself).
_CANCEL_RE = re.compile(
    r"\b(skip(s|ped|ping)?|hold(s|ing)? off|(don'?t|do not) worry about|no need|"
    r"not needed|cancel(s|led|ed|ling)?|never mind|scrap(s|ped|ping)?|drop (that|the|it))\b",
    re.IGNORECASE,
)


def _strip_subject(item: str) -> str:
    """Strip ONE leading subject ("The rep will ", "Customer is ", ...), casefold-
    insensitive, applied once; lowercase the new first character. The single
    authoritative regex for E30 — used both to build the assembled owner-prefixed
    string and to compute content tokens, so the two never disagree on what the
    "real" commitment text is."""
    stripped = _SUBJECT_RE.sub("", item, count=1).strip()
    if stripped:
        stripped = stripped[0].lower() + stripped[1:]
    return stripped


def _content_tokens(item: str) -> set[str]:
    """Casefolded alphabetic tokens of length >= 4 of the SUBJECT-STRIPPED item, minus
    STOPWORDS. Computed on `_strip_subject(item)`, never the raw item — a role noun
    surviving only because it was the (now-stripped) subject must not count as a shared
    token between two unrelated commitments."""
    stripped = _strip_subject(item)
    return {t for t in _TOKEN_RE.findall(stripped.casefold())
            if len(t) >= 4 and t not in STOPWORDS}


def _is_cancellation(item_text: str, evidence_text: str) -> bool:
    """True if the cancel regex matches EITHER the item or its verbatim evidence line."""
    return bool(_CANCEL_RE.search(item_text or "") or _CANCEL_RE.search(evidence_text or ""))


def _in_transcript_order(survivors, transcript: str):
    """Sort grounded survivors by where their evidence line sits in the transcript.

    `_supersede` is POSITIONAL (a later superseder cancels an earlier item), which assumes
    the model's JSON array is in transcript order. Every observed extraction is — but nothing
    enforced it, and an out-of-order array would let a genuinely cancelled promise survive
    (delta refuter, PR #86). `_ground_commitments` has already proven each `evidence` is a
    verbatim (whitespace-normalised) substring, so true order is one `find` per item.
    Stable sort: ties (same evidence line twice) keep the model's order."""
    norm_transcript = _ws_norm(transcript)
    return sorted(survivors, key=lambda s: norm_transcript.find(_ws_norm(s["evidence"])))


def _supersede(survivors):
    """Superseders = withdrawn-flagged OR `_is_cancellation`-matched. Every superseder is
    removed, and so is every EARLIER (lower-index) non-superseder sharing >= 1 content
    token with ANY superseder — order-preserving, one pass.

    Returns (kept, n_cancel_removed, n_superseded_removed): n_cancel_removed counts the
    superseders themselves; n_superseded_removed counts the earlier items removed only
    because they shared a token with one.
    """
    # `s["evidence"]` — not `.get(..., "")` — because every survivor here came out of
    # `_ground_commitments`, which now always sets it (dropped otherwise).
    is_superseder = [bool(s["withdrawn"]) or _is_cancellation(s["item"], s["evidence"])
                      for s in survivors]
    tokens = [_content_tokens(s["item"]) for s in survivors]
    kept = []
    n_cancel = n_superseded = 0
    for i, (s, sup) in enumerate(zip(survivors, is_superseder)):
        if sup:
            n_cancel += 1
            continue
        # POSITIONAL: only a LATER superseder can cancel this item. A cancellation that
        # precedes a commitment cannot have withdrawn it — "skip the sheet … actually, I'll
        # send the sheet after all" must keep the second item (correctness refuter, PR #86:
        # a global token union wiped it; every committed fixture happened to place the real
        # item before its superseder, so the suite was blind — T-O now covers the order).
        later_sup_tokens = set()
        for j in range(i + 1, len(survivors)):
            if is_superseder[j]:
                later_sup_tokens |= tokens[j]
        if tokens[i] & later_sup_tokens:
            n_superseded += 1
            continue
        kept.append(s)
    return kept, n_cancel, n_superseded


def _dedupe(kept):
    """A later item by the SAME speaker sharing >= 2 content tokens with an earlier KEPT
    item is dropped (restatements — "send the escalation ticket, SLA document and usage
    report today" repeating three commitments already listed one by one). Returns
    (deduped, n_dropped)."""
    deduped = []
    n_dropped = 0
    for s in kept:
        toks = _content_tokens(s["item"])
        is_dup = any(s["speaker"] is not None and s["speaker"] == k["speaker"]
                     and len(toks & _content_tokens(k["item"])) >= 2
                     for k in deduped)
        if is_dup:
            n_dropped += 1
        else:
            deduped.append(s)
    return deduped, n_dropped


def _assemble(kept) -> list[str]:
    """`kept` -> ["Rep to <item>", "Customer to <item>", ...] in transcript order.
    Owner unrecognised (speaker None) -> the bare subject-stripped item, no prefix —
    never guess an owner the model did not give (ledger 043)."""
    out = []
    for s in kept:
        stripped = _strip_subject(s["item"])
        if s["speaker"] == "rep":
            out.append(f"Rep to {stripped}")
        elif s["speaker"] == "customer":
            out.append(f"Customer to {stripped}")
        else:
            out.append(stripped)
    return out


def extract_then_assemble(ctx, case):
    """E30 — the model extracts, the code writes the list, the model writes only the
    summary prose.

    Call 1 (`EXTRACT_SYSTEM_PROMPT_V2`, `case['input']` verbatim, `max_tokens=4096` — E28b
    measured 5/6 empties at the default 2048 were `finish_reason=length`, not a real
    refusal) asks for the same commitment list as E28, plus the supersession + bare-verb-
    phrase rules. `_ground_commitments` (shared with E28's `commit_list_then_write`, now
    carrying `evidence` through) drops anything unparseable or not actually in the call.
    Then, in order, purely in code: `_supersede` (withdrawn/cancelled items and the earlier
    items that share their wording), `_dedupe` (same-speaker restatements), `_assemble`
    (owner-prefixed strings). Call 2 (the champion's OWN `system_prompt`, the ORIGINAL
    transcript, no suffix — E28's finding: any appended block costs coverage) is exactly
    single-shot's call; its own `action_items` are discarded and replaced.

    `nothing_important`: a non-empty assembled list means a commitment exists, so it is
    forced False; an empty list leaves the model's own flag exactly as call 2 returned it
    (call 2 never saw the assembled list, so it may correctly say True on a truly quiet
    call — this strategy does not touch that judgment either way).

    Never reads `case['expected']` (T-N pattern, same invariant as E28's T-G). Never calls
    `split_items` — transcript-en transcripts carry no `--- item N ---` markers, a
    recap-only convention.
    """
    transcript = case["input"]
    parsed1, metrics1 = ctx.call(EXTRACT_SYSTEM_PROMPT_V2, transcript, max_tokens=4096)
    raw_commitments = (parsed1 or {}).get("commitments") if isinstance(parsed1, dict) else None
    survivors, extracted, dropped = _ground_commitments(raw_commitments, transcript)
    survivors = _in_transcript_order(survivors, transcript)
    superseded_kept, n_cancel, n_superseded = _supersede(survivors)
    deduped, n_dup = _dedupe(superseded_kept)
    assembled = _assemble(deduped)

    parsed2, metrics2 = ctx.call(ctx.agent["system_prompt"], transcript)
    if not isinstance(parsed2, dict):
        raise ValueError(f"extract-then-assemble: call 2 returned non-dict output "
                          f"for case {case['id']!r}: {parsed2!r}")
    parsed2["action_items"] = assembled
    if assembled:
        parsed2["nothing_important"] = False
    parsed2["_strategy_note"] = (f"extracted={extracted} ungrounded={dropped} "
                                 f"cancel={n_cancel} superseded={n_superseded} "
                                 f"dup={n_dup} kept={len(deduped)}")
    print(f"  [extract-then-assemble] {case['id']} extracted={extracted} "
          f"ungrounded={dropped} cancel={n_cancel} superseded={n_superseded} "
          f"dup={n_dup} kept={len(deduped)}", flush=True)
    return parsed2, [metrics1, metrics2]


STRATEGIES = {
    "single-shot": single_shot,
    "filter-then-recap": filter_then_recap,
    "chunk-and-reduce": chunk_and_reduce,
    "extract-then-write": extract_then_write,
    "commit-list-then-write": commit_list_then_write,
    "extract-then-assemble": extract_then_assemble,
}
