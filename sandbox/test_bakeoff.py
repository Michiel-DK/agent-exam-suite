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
                "extract-then-write", "commit-list-then-write", "extract-then-assemble"}
    check("all six strategies registered", set(S.STRATEGIES) == expected,
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


# ---------------------------------------------------------- E28 commit-list-then-write
#
# Fixtures below are SYNTHETIC (not real transcript-en cases) and independent of the
# recap fixtures above — commit-list-then-write's mechanics (two calls, grounding
# filter, withdrawn handling) are agent-agnostic; T-E is the one test that reaches into
# a real committed transcript-en case, to pin the scoring invariant against the new
# strategy's actual target agent. No inference anywhere in this file.

AGENT_SYSTEM_PROMPT = "AGENT SYSTEM PROMPT — the champion's real prompt.md text stands in here."
METRICS_STUB = {"total_tokens": 1, "reasoning_chars": 0, "content_chars": 1}

TRANSCRIPT_CASES = json.loads((ROOT / "evals" / "transcript-en" / "cases.json").read_text())["cases"]
TRANSCRIPT_PROPS = R.load_properties("transcript-en")
TRANSCRIPT_BY_ID = {c["id"]: c for c in TRANSCRIPT_CASES}


class _RecordingCtx:
    """Canned ctx for commit-list-then-write: `call(system_prompt, user_text)` records
    every invocation (in order) and returns a pre-scripted (parsed, metrics) pair per
    call. No model, no server — mirrors _FakeCtx's role above for the recap strategies."""

    def __init__(self, agent, replies):
        self.agent = agent
        self._replies = list(replies)
        self.calls = []  # [(system_prompt, user_text), ...] in call order

    def call(self, system_prompt, user_text):
        idx = len(self.calls)
        self.calls.append((system_prompt, user_text))
        return self._replies[idx]


FAKE_TRANSCRIPT = (
    "REP: Thanks for joining today.\n"
    "CUSTOMER: Happy to be here, we want to discuss pricing.\n"
    "REP: I will send over the proposal by Thursday.\n"
    "CUSTOMER: One more thing, can you loop in your engineering lead?\n"
    "REP: Yes, I will schedule a call with them next week.\n"
)
FAKE_CASE = {"id": "fake-commit-case", "split": "train", "input": FAKE_TRANSCRIPT,
             "expected": {}}


def test_A_commit_list_then_write_makes_exactly_two_calls():
    """Injection: collapsing the strategy to one call goes RED on the call count;
    `return parsed2, [metrics2]` (dropping metrics1) goes RED on the metrics-list
    assertions below."""
    call1_reply = ({"commitments": [
        {"speaker": "rep", "item": "send proposal",
         "evidence": "I will send over the proposal by Thursday.", "withdrawn": False},
    ]}, {"total_tokens": 10, "reasoning_chars": 1, "content_chars": 9})
    call2_reply = ({"summary": "s", "action_items": ["x"], "nothing_important": False},
                   {"total_tokens": 20, "reasoning_chars": 2, "content_chars": 18})
    agent = {"system_prompt": AGENT_SYSTEM_PROMPT}
    ctx = _RecordingCtx(agent, [call1_reply, call2_reply])
    parsed, metrics = S.commit_list_then_write(ctx, FAKE_CASE)
    check("exactly two calls made", len(ctx.calls) == 2, f"{len(ctx.calls)} calls")
    sp1, ut1 = ctx.calls[0]
    check("call 1 system prompt is EXTRACT_SYSTEM_PROMPT", sp1 == S.EXTRACT_SYSTEM_PROMPT)
    check("call 1 user text is the case input verbatim", ut1 == FAKE_CASE["input"])
    sp2, ut2 = ctx.calls[1]
    check("call 2 system prompt is the agent's own system_prompt", sp2 == agent["system_prompt"])
    check("call 2 user text starts with the original transcript", ut2.startswith(FAKE_CASE["input"]))
    check("returned metrics list has length 2", len(metrics) == 2, f"len={len(metrics)}")
    check("returned metrics are [call1, call2] in order",
          metrics == [call1_reply[1], call2_reply[1]], f"got {metrics}")
    check("returned parsed output is call 2's parsed reply",
          parsed.get("summary") == "s" and parsed.get("action_items") == ["x"])


TRANSCRIPT_B = (
    "REP: Thanks for joining today.\n"
    "CUSTOMER: We wanted to talk about the proposal.\n"
    "REP: I will send over the proposal by Thursday.\n"
    "CUSTOMER: Great, and can you also loop in your engineering lead?\n"
    "REP: Yes, I will schedule a call with them next week.\n"
)
CASE_B = {"id": "fake-b", "split": "train", "input": TRANSCRIPT_B, "expected": {}}


def test_B_grounding_filter_drops_ungrounded_and_malformed_entries():
    """Injection: disabling the substring filter lets 'refund the customer' through ->
    RED. An exact-match-only filter (no whitespace/case normalization) drops the
    tolerant entry -> RED. An unguarded `c['evidence']` raises KeyError on the
    missing-evidence entry -> RED. An unguarded `c.get(...)` on the bare-string element
    raises AttributeError -> RED (this is the entry required by clause (4))."""
    raw_commitments = [
        {"speaker": "rep", "item": "send proposal",
         "evidence": "I will send over the proposal by Thursday.", "withdrawn": False},
        {"speaker": "rep", "item": "refund the customer",
         "evidence": "I will refund the customer in full today.", "withdrawn": False},
        {"speaker": "rep", "item": "no evidence key here"},
        {"speaker": "rep", "item": 12345,
         "evidence": "I will schedule a call with them next week."},
        "just a bare string, not a dict at all",
        {"speaker": "REP", "item": "schedule engineering call",
         "evidence": "i will  SCHEDULE a call with them   next week."},
    ]
    call1_reply = ({"commitments": raw_commitments}, METRICS_STUB)
    call2_reply = ({"summary": "s", "action_items": [], "nothing_important": False}, METRICS_STUB)
    agent = {"system_prompt": AGENT_SYSTEM_PROMPT}
    ctx = _RecordingCtx(agent, [call1_reply, call2_reply])
    parsed, _metrics = S.commit_list_then_write(ctx, CASE_B)
    _sp2, ut2 = ctx.calls[1]
    check("grounded commitment present in the required block", "send proposal" in ut2)
    check("case/whitespace-tolerant commitment survives",
          "schedule engineering call" in ut2)
    check("an upper-case speaker label keeps its owner tag (injection: case-sensitive "
          "match -> the line has no [rep] prefix -> RED)",
          "- [rep] schedule engineering call" in ut2, f"ut2={ut2!r}")
    check("ungrounded commitment is absent from the required block",
          "refund the customer" not in ut2)
    check("missing-evidence entry dropped without raising",
          "no evidence key here" not in ut2)
    check("non-string-item entry dropped without raising", "12345" not in ut2)
    check("dropped count is 4 (ungrounded + missing-evidence + non-string-item + non-dict)",
          parsed.get("_strategy_note") == "extracted=6 dropped=4 withdrawn=0",
          f"note={parsed.get('_strategy_note')}")


TRANSCRIPT_C = (
    "REP: We discussed a pilot program.\n"
    "REP: I originally offered a 20% discount.\n"
    "CUSTOMER: Actually let's skip the discount, we don't need it.\n"
    "REP: Understood, no discount then.\n"
)
CASE_C = {"id": "fake-c", "split": "train", "input": TRANSCRIPT_C, "expected": {}}


def test_C_withdrawn_commitments_excluded_from_required_items():
    """Injection: a build that ignores the `withdrawn` flag lists the discount as a
    plain required item -> RED (the WITHDRAWN marker check fails)."""
    raw_commitments = [
        {"speaker": "rep", "item": "offer 20% discount",
         "evidence": "I originally offered a 20% discount.", "withdrawn": True},
        {"speaker": "customer", "item": "confirm pilot",
         "evidence": "We discussed a pilot program.", "withdrawn": False},
    ]
    call1_reply = ({"commitments": raw_commitments}, METRICS_STUB)
    call2_reply = ({"summary": "s", "action_items": [], "nothing_important": False}, METRICS_STUB)
    agent = {"system_prompt": AGENT_SYSTEM_PROMPT}
    ctx = _RecordingCtx(agent, [call1_reply, call2_reply])
    S.commit_list_then_write(ctx, CASE_C)
    _sp2, ut2 = ctx.calls[1]
    lines = ut2.splitlines()
    withdrawn_lines = [l for l in lines if "offer 20% discount" in l]
    check("withdrawn commitment appears exactly once", len(withdrawn_lines) == 1,
          f"{withdrawn_lines}")
    check("withdrawn commitment is marked WITHDRAWN on its own line",
          bool(withdrawn_lines) and "WITHDRAWN" in withdrawn_lines[0])
    surviving_lines = [l for l in lines if "confirm pilot" in l]
    check("surviving commitment listed as a plain required item (no WITHDRAWN marker)",
          bool(surviving_lines) and "WITHDRAWN" not in surviving_lines[0])


class _MsgCapturingAdapter:
    """A real Adapter-shaped double: generate() -> (raw_json_text, meta), the contract
    call_with_retry/call_model actually use (see sandbox/router.py Adapter.generate)."""

    def __init__(self):
        self.seen = None

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        self.seen = [dict(m) for m in messages]
        return (json.dumps({"recap": "r", "nothing_important": False}),
                {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                 "finish_reason": "stop", "content_chars": 1, "reasoning_chars": 0})


def test_D_call_recap_regression_pin_messages_unchanged():
    """PIN, not a new-feature test: green on baseline (master's call_recap built these
    exact messages inline) and green here too, because call_recap now delegates through
    the new `call()` method to the SAME two messages in the SAME order. Injection (the
    wrong fix this pin exists to catch): a `call()` that prepends/alters the system
    prompt, or reorders [system, user] -> RED. Exercises the REAL runner._BakeoffCtx,
    not a canned double.
    """
    agent = {"system_prompt": "AGENT SYSTEM PROMPT", "temperature": 0.0, "max_tokens": 2048}
    adapter = _MsgCapturingAdapter()
    ctx = R._BakeoffCtx(agent, adapter, "fake-model")
    ctx.call_recap("HELLO DAY TEXT")
    expected_msgs = [{"role": "system", "content": agent["system_prompt"]},
                      {"role": "user", "content": "HELLO DAY TEXT"}]
    check("call_recap's messages are byte-identical to master's inline construction",
          adapter.seen == expected_msgs, f"got {adapter.seen}")


def test_E_commit_list_registered_and_still_scores_against_original_input():
    """Extends test_4 (its registered-strategy-name set gained the 5th name above) and
    MIRRORS test_1's invariant for commit-list-then-write's own target agent
    (transcript-en, not recap). Two different claims, two different arm levels:

    - The two `registered`/`callable` checks are ARMED, same as test_4's own — remove
      the "commit-list-then-write" entry from STRATEGIES and both go RED.
    - The `_bakeoff_score` check below is VACUOUS on master by construction, same as
      test_1's own mechanism: `_exp()` RAISES on any input that is not some committed
      case's exact text (ledger 017), so almost any wrong-input substitution in
      `_bakeoff_score` fails LOUD rather than silently passing vacuously — there is no
      cheap mutation that turns this specific assertion RED. It is kept anyway because
      it is the one place this suite exercises `_bakeoff_score` against the new
      strategy's actual target agent (transcript-en) rather than only recap.
    """
    check("commit-list-then-write is registered", "commit-list-then-write" in S.STRATEGIES)
    check("commit-list-then-write is callable", callable(S.STRATEGIES["commit-list-then-write"]))
    tcase = TRANSCRIPT_BY_ID["discovery-short-train"]
    empty_ish = {"summary": "Nothing happened on this call.", "action_items": [],
                "nothing_important": True}
    ok, checks = R._bakeoff_score(TRANSCRIPT_PROPS, tcase, empty_ish)
    check(f"{tcase['id']} still armed under bake-off scoring for the new strategy's agent",
          not ok, f"passed with checks={checks} — expectations did not resolve")


def test_F_degrades_to_zero_required_items_never_fabricates():
    """Injection: a build that INVENTS commitments when call 1's reply is unusable, or
    that RAISES instead of degrading, goes RED. This strategy's chosen degrade shape
    (stated in commit_list_then_write's docstring): call 2 still receives the required-
    commitments HEADER even at zero surviving items — no bullet line follows it."""
    agent = {"system_prompt": AGENT_SYSTEM_PROMPT}
    bad_call1_replies = [
        ("dict without a commitments key", {"nope": "not a commitments key"}),
        ("not a dict at all", ["not", "a", "dict"]),
        ("None", None),
    ]
    for label, parsed1 in bad_call1_replies:
        # A FRESH call-2 dict per iteration. The strategy writes `_strategy_note` onto
        # the dict it returns, so a shared dict would carry iteration 1's note into
        # iterations 2-3 as residue (test-honesty refuter, PR #85). Hygiene, not a
        # demonstrated kill: all three iterations take the same degrade path and
        # cmd_bakeoff hands the strategy a fresh parsed2 per call, so no reachable
        # defect was found that the shared fixture hid — but a test should not rely
        # on that argument.
        call2_reply = ({"summary": "s", "action_items": [], "nothing_important": True},
                       METRICS_STUB)
        ctx = _RecordingCtx(agent, [(parsed1, METRICS_STUB), call2_reply])
        parsed, metrics = S.commit_list_then_write(ctx, FAKE_CASE)
        check(f"still makes exactly two calls on a degraded call-1 reply ({label})",
              len(ctx.calls) == 2, f"{len(ctx.calls)} calls")
        check(f"returned metrics list still has length 2 ({label})", len(metrics) == 2)
        _sp2, ut2 = ctx.calls[1]
        check(f"header still appended at zero survivors ({label})",
              S._REQUIRED_HEADER in ut2, f"ut2={ut2!r}")
        check(f"zero required items — no bullet line follows the header ({label})",
              "\n- " not in ut2, f"ut2={ut2!r}")
        check(f"note says extracted=0 dropped=0 withdrawn=0 ({label})",
              parsed.get("_strategy_note") == "extracted=0 dropped=0 withdrawn=0",
              f"note={parsed.get('_strategy_note')}")


TRANSCRIPT_G = (
    "REP: Thanks for joining.\n"
    "REP: I will send the pricing sheet by Friday.\n"
    "CUSTOMER: Great, looking forward to it.\n"
)
CASE_G = {
    "id": "fake-g", "split": "train", "input": TRANSCRIPT_G,
    "expected": {
        "must_commit": ["ZZ-SENTINEL-MUST-COMMIT-ZZ"],
        "commit_owner": {"ZZ-SENTINEL-MUST-COMMIT-ZZ": "rep"},
    },
}


def test_G_answer_key_never_leaks_into_call_2_or_the_return_value():
    """cmd_bakeoff hands every strategy the FULL committed case dict, `case['expected']`
    (the scorer's answer key) included — that is a repo invariant this test exercises
    directly, not a hypothetical. The sentinel strings below appear NOWHERE in the
    canned transcript or the canned call-1 reply. Injection: a build that unions
    `case['expected']['must_commit']` into the required block as a 'defensive top-up'
    -> RED. Vacuous on any build that never touches `case['expected']` — which is the
    only correct shape; this test exists to catch a future build that reads it.
    """
    raw_commitments = [
        {"speaker": "rep", "item": "send pricing sheet",
         "evidence": "I will send the pricing sheet by Friday.", "withdrawn": False},
    ]
    call1_reply = ({"commitments": raw_commitments}, METRICS_STUB)
    call2_reply = ({"summary": "s", "action_items": [], "nothing_important": False}, METRICS_STUB)
    agent = {"system_prompt": AGENT_SYSTEM_PROMPT}
    ctx = _RecordingCtx(agent, [call1_reply, call2_reply])
    parsed, _metrics = S.commit_list_then_write(ctx, CASE_G)
    _sp2, ut2 = ctx.calls[1]
    sentinel = "ZZ-SENTINEL-MUST-COMMIT-ZZ"
    check("sentinel absent from call 2's user text", sentinel not in ut2)
    check("sentinel absent from the returned parsed output",
          sentinel not in json.dumps(parsed))


# ---------------------------------------------------------- E30 extract-then-assemble
#
# Fixtures below are LITERAL copies of real E28b probe outputs (not invented shapes):
# docs/probes/e28b-extraction-recall-2026-09-09/raw_probe2.json `commitments` for the
# three probe-2 calls, and .../raw.json arm 'A' `longcall-renewal-train-1` for the
# fourth. `#N` in comments is 1-indexed against the source list (index N-1). Each
# fixture's fake `input` is the join of its OWN evidence lines — enough for
# `_ground_commitments`'s substring check without embedding the real ~15k-char
# transcript; the real transcripts were hand-traced separately (E30 criterion
# advisories) and every evidence line here is a verbatim substring of them.


class _RecordingCtxV2:
    """Canned ctx for extract_then_assemble: `call(system_prompt, user_text,
    max_tokens=None)` records every invocation IN ORDER, including max_tokens, and
    returns a pre-scripted (parsed, metrics) pair per call. A separate class from
    `_RecordingCtx` above (not an extension of it) so E28's tests, which unpack
    `ctx.calls[i]` as a 2-tuple, are untouched."""

    def __init__(self, agent, replies):
        self.agent = agent
        self._replies = list(replies)
        self.calls = []  # [(system_prompt, user_text, max_tokens), ...] in call order

    def call(self, system_prompt, user_text, max_tokens=None):
        idx = len(self.calls)
        self.calls.append((system_prompt, user_text, max_tokens))
        return self._replies[idx]


class _MTCapturingAdapter:
    """Real Adapter-shaped double (mirrors `_MsgCapturingAdapter` above) that records
    the `max_tokens` value `call_model` actually forwarded to `generate()`."""

    def __init__(self):
        self.seen_max_tokens = None

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        self.seen_max_tokens = max_tokens
        return (json.dumps({"ok": True}),
                {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                 "finish_reason": "stop", "content_chars": 1, "reasoning_chars": 0})


def _fixture_case(case_id, commitments):
    """A fake case whose `input` is the join of the fixture's own evidence lines."""
    transcript = "\n".join(c["evidence"] for c in commitments)
    return {"id": case_id, "split": "train", "input": transcript, "expected": {}}


def _assembled_via_strategy(commitments, name):
    """Run the real `extract_then_assemble` end to end over one fixture and return the
    assembled `action_items` list — the public-interface view every T-I..T-M assertion
    below is stated against. `name` is a stable id (not `id(commitments)`, which varies
    run to run and would make the strategy's own stdout line look different on every
    invocation of this test file)."""
    case = _fixture_case("fixture-" + name, commitments)
    call1_reply = ({"commitments": commitments}, METRICS_STUB)
    call2_reply = ({"summary": "s", "action_items": [], "nothing_important": True}, METRICS_STUB)
    agent = {"system_prompt": AGENT_SYSTEM_PROMPT}
    ctx = _RecordingCtxV2(agent, [call1_reply, call2_reply])
    parsed, _metrics = S.extract_then_assemble(ctx, case)
    return parsed["action_items"]


PROBE2_DISCOVERY = [
    {"speaker": "customer", "item": "Loop in the finance lead, Renata, by the end of the week.",
     "evidence": "I'll loop in our finance lead, Renata, by the end of the week so she's "
                 "looped in before the follow-up.", "withdrawn": False},  # #1
    {"speaker": "rep", "item": "Send over the revised quote by Thursday.",
     "evidence": "I'll send over the revised quote by Thursday so you have something "
                 "concrete for Renata.", "withdrawn": False},  # #2
    {"speaker": "rep", "item": "Dig out a case study from a similar clinic network.",
     "evidence": "Sure, we've got one from a similar clinic network, I can dig it out.",
     "withdrawn": True},  # #3 -- withdrawn
    {"speaker": "rep", "item": "Schedule a technical call with the integrations engineer "
                               "for next week.",
     "evidence": "I'll also schedule a technical call with our integrations engineer for "
                 "next week so you can go through the multi-site setup.", "withdrawn": False},  # #4
    {"speaker": "customer", "item": "Confirm a time with the IT lead after receiving the "
                                    "calendar invite.",
     "evidence": "I'll confirm a time with our IT lead once I see your calendar invite.",
     "withdrawn": False},  # #5
]

PROBE2_RENEWAL = [
    {"speaker": "customer", "item": "The customer will get budget approval from their ops "
                                    "director by next Wednesday.",
     "evidence": "I'll get budget approval from our ops director by next Wednesday.",
     "withdrawn": False},  # #1
    {"speaker": "rep", "item": "The representative will draft and send the updated MSA today.",
     "evidence": "Great, I'll draft the updated MSA and send it over today so it's ready "
                 "once you have approval.", "withdrawn": False},  # #2
    {"speaker": "rep", "item": "The representative will put together a whitepaper on the "
                               "audit-log feature.",
     "evidence": "Sure, I can put that together.", "withdrawn": True},  # #3 -- withdrawn
    {"speaker": "customer", "item": "The customer is holding off on the whitepaper because "
                                    "standard product docs will suffice.",
     "evidence": "Actually, hold off on the whitepaper -- our compliance lead said the "
                 "standard product docs will cover what they need, so no need to draft "
                 "anything extra.", "withdrawn": False},  # #4 -- cancel-worded, UNFLAGGED
    {"speaker": "rep", "item": "The representative will revisit the training session for "
                               "new supervisors later.",
     "evidence": "Noted, we can revisit that later if you want it.", "withdrawn": False},  # #5
    {"speaker": "rep", "item": "The representative will send a summary email recapping "
                               "today's numbers.",
     "evidence": "I'll also send a summary email recapping today's numbers for your records.",
     "withdrawn": False},  # #6
    {"speaker": "customer", "item": "The customer will confirm the exact seat count with "
                                    "HR by Friday.",
     "evidence": "I'll also confirm the exact seat count with HR by Friday so the MSA "
                 "numbers are final.", "withdrawn": False},  # #7
    {"speaker": "rep", "item": "The representative will get the MSA over today.",
     "evidence": "I'll get the MSA over today and we can finalise once your ops director "
                 "signs off.", "withdrawn": False},  # #8
]

PROBE2_SUPPORT = [
    {"speaker": "rep", "item": "Open an escalation ticket with the infrastructure team and "
                               "push for a fix this week.",
     "evidence": "I'll open an escalation ticket with our infrastructure team today and "
                 "push for a fix this week.", "withdrawn": False},  # #1
    {"speaker": "rep", "item": "Send the SLA document after the call.",
     "evidence": "Sure, I'll send that over after the call.", "withdrawn": False},  # #2
    {"speaker": "rep", "item": "Share a usage report showing sync volume over the last 90 days.",
     "evidence": "While I have you -- I'll also share a usage report showing sync volume "
                 "over the last 90 days so you have context for the ticket.", "withdrawn": False},  # #3
    {"speaker": "rep", "item": "Send the escalation ticket, SLA document, and usage report "
                               "today, and follow up once infrastructure confirms a fix window.",
     "evidence": "I'll get the escalation ticket, the SLA document and the usage report "
                 "sent today, and follow up once infrastructure confirms a fix window.",
     "withdrawn": False},  # #4 -- rep restatement, dedupe target
    {"speaker": "customer", "item": "Follow up internally with the IT team regarding the "
                                    "batch job timing.",
     "evidence": "I'll also follow up internally with our IT team about the batch job "
                 "timing on our side just in case.", "withdrawn": False},  # #5
    {"speaker": "customer", "item": "Skip the extra onboarding session for new warehouse staff.",
     "evidence": "Actually, let's skip the extra onboarding session for now -- our team "
                 "lead said she'd rather just have people shadow existing staff, no need "
                 "to schedule anything.", "withdrawn": False},  # #6 -- cancel-worded, UNFLAGGED
]

# arm-A `longcall-renewal-train-1` (raw.json, arm 'A' -- the original prompt, no
# supersession rules in call 1, hence the messier "REP promises"/"customer requests" shape).
ARM_A_RENEWAL = [
    {"speaker": "customer", "item": "Customer will get budget approval from the ops "
                                    "director by next Wednesday.",
     "evidence": "I'll get budget approval from our ops director by next Wednesday.",
     "withdrawn": False},  # #1
    {"speaker": "rep", "item": "REP will draft and send the updated MSA today.",
     "evidence": "Great, I'll draft the updated MSA and send it over today so it's ready "
                 "once you have approval.", "withdrawn": False},  # #2
    {"speaker": "customer", "item": "Customer requests a whitepaper on the audit-log feature.",
     "evidence": "Also, could you send over a whitepaper on the audit-log feature "
                 "specifically? Something for our compliance file.", "withdrawn": False},  # #3
    {"speaker": "rep", "item": "REP promises to put together the whitepaper.",
     "evidence": "Sure, I can put that together.",
     "withdrawn": False},  # #4 -- UNFLAGGED, removed via shared token with #5
    {"speaker": "customer", "item": "Customer withdraw/cancels the request for the whitepaper.",
     "evidence": "Actually, hold off on the whitepaper -- our compliance lead said the "
                 "standard product docs will cover what they need, so no need to draft "
                 "anything extra.", "withdrawn": True},  # #5 -- flagged withdrawn
    {"speaker": "rep", "item": "REP corrects the active seat count from 47 to 49.",
     "evidence": "Sorry, one correction on the seat count -- I misspoke earlier, you're "
                 "actually at 49 active seats today, not 47, we just got an updated export.",
     "withdrawn": False},  # #6
    {"speaker": "customer", "item": "Customer raises a future need for a training session "
                                    "for new supervisors.",
     "evidence": "One more thing, we might want a training session for the new "
                 "supervisors at some point down the line, but that's not urgent, just "
                 "something to keep in mind.", "withdrawn": False},  # #7
    {"speaker": "rep", "item": "REP will send a summary email recapping today's numbers.",
     "evidence": "I'll also send a summary email recapping today's numbers for your records.",
     "withdrawn": False},  # #8
    {"speaker": "customer", "item": "Customer will confirm the exact seat count with HR "
                                    "by Friday.",
     "evidence": "I'll also confirm the exact seat count with HR by Friday so the MSA "
                 "numbers are final.", "withdrawn": False},  # #9
    {"speaker": "rep", "item": "REP reiterates commitment to get the MSA over today.",
     "evidence": "I'll get the MSA over today and we can finalise once your ops director "
                 "signs off.", "withdrawn": False},  # #10
]

# Synthetic (not a real transcript): the withdrawn item and the real commitment below
# share ONLY the stopword "today" -- no other token in common, in either direction.
SYNTHETIC_STOPWORD_ONLY_OVERLAP = [
    {"speaker": "rep", "item": "Never mind that update today.",
     "evidence": "Never mind that update today, it's not needed after all.",
     "withdrawn": True},
    {"speaker": "rep", "item": "I will confirm the seat count today.",
     "evidence": "I will confirm the seat count today so the numbers are final.",
     "withdrawn": False},
]


def test_H_two_calls_max_tokens_plumbed_on_call_1_only():
    """Injection: drop the `max_tokens` kwarg on call 1, or append anything to call 2's
    user text -> RED on the checks below."""
    case = _fixture_case("fixture-h", PROBE2_DISCOVERY)
    call1_reply = ({"commitments": PROBE2_DISCOVERY}, METRICS_STUB)
    call2_reply = ({"summary": "s", "action_items": ["model's own guess"],
                    "nothing_important": True}, METRICS_STUB)
    agent = {"system_prompt": AGENT_SYSTEM_PROMPT}
    ctx = _RecordingCtxV2(agent, [call1_reply, call2_reply])
    parsed, metrics = S.extract_then_assemble(ctx, case)
    check("exactly two calls made", len(ctx.calls) == 2, f"{len(ctx.calls)} calls")
    sp1, ut1, mt1 = ctx.calls[0]
    check("call 1 system prompt is EXTRACT_SYSTEM_PROMPT_V2", sp1 == S.EXTRACT_SYSTEM_PROMPT_V2)
    check("call 1 user text is the case input verbatim", ut1 == case["input"])
    check("call 1 max_tokens is 4096", mt1 == 4096, f"got {mt1}")
    sp2, ut2, mt2 = ctx.calls[1]
    check("call 2 system prompt is the agent's own system_prompt", sp2 == agent["system_prompt"])
    check("call 2 user text is the case input EXACTLY, no suffix", ut2 == case["input"])
    check("call 2 max_tokens is not overridden (None)", mt2 is None, f"got {mt2}")
    check("returned metrics list is [call1, call2] in order",
          metrics == [call1_reply[1], call2_reply[1]], f"got {metrics}")
    check("model's own action_items were discarded",
          parsed["action_items"] != ["model's own guess"], f"{parsed['action_items']}")

    # One new check on the REAL runner._BakeoffCtx (clause 3), not the canned double:
    # `.call()` without `max_tokens` must leave the agent dict's OWN budget untouched.
    # RED: a build that always overrides (e.g. `dict(self.agent, max_tokens=max_tokens
    # or 2048)`) would send 2048 here instead of the agent's real 777.
    real_agent = {"system_prompt": "SYS", "temperature": 0.0, "max_tokens": 777}
    adapter_no_override = _MTCapturingAdapter()
    real_ctx = R._BakeoffCtx(real_agent, adapter_no_override, "fake-model")
    real_ctx.call("SYS", "text")
    check("ctx.call without max_tokens passes the agent dict through unchanged",
          adapter_no_override.seen_max_tokens == 777, f"got {adapter_no_override.seen_max_tokens}")
    adapter_override = _MTCapturingAdapter()
    real_ctx2 = R._BakeoffCtx(real_agent, adapter_override, "fake-model")
    real_ctx2.call("SYS", "text", max_tokens=4096)
    check("ctx.call WITH max_tokens overrides the agent dict for that one call",
          adapter_override.seen_max_tokens == 4096, f"got {adapter_override.seen_max_tokens}")



# Synthetic, PRIVATE to T-I (not reused by T-J/T-L): the only mechanism this fixture
# can exercise is cancellation-by-wording. The two items share ZERO content tokens
# (isolation: disabling `_supersede` entirely would also fail this, same as it fails
# T-J -- expected, `_supersede` calls `_is_cancellation` -- but no OTHER test's
# checks touch this fixture, so disabling `_is_cancellation` alone fails T-I and
# nothing else, per CLAUDE.md gotcha 3).
ISOLATED_CANCELLATION_ONLY = [
    {"speaker": "rep", "item": "I will send the pricing sheet by Friday.",
     "evidence": "I will send the pricing sheet by Friday.", "withdrawn": False},
    {"speaker": "rep", "item": "Skip the onboarding call for the new hire.",
     "evidence": "Actually, let's skip the onboarding call for the new hire, it's "
                 "not needed.", "withdrawn": False},  # cancel-worded, UNFLAGGED
]


def test_I_cancellation_removes_the_item_and_nothing_downstream_mentions_it():
    """A cancellation-worded item ('Skip the onboarding call...', never
    withdrawn=True) sharing NO content token with the real commitment beside it.
    Injection: disable `_is_cancellation` (always return False) -> the item is never
    treated as a superseder, kept count is 2 not 1, and 'onboarding' leaks into the
    assembled list -> RED. This fixture is private to T-I -- no other test's checks
    read it, so this is the one case where the injection fails ONLY this test.
    """
    items = _assembled_via_strategy(ISOLATED_CANCELLATION_ONLY, "i-isolated-cancel")
    check("kept count is 1 (the cancelled item is removed)", len(items) == 1, f"items={items}")
    check("no assembled item mentions 'onboarding'",
          all("onboarding" not in i.casefold() for i in items), f"items={items}")
    check("the real commitment (pricing sheet) survives",
          any("pricing sheet" in i.casefold() for i in items), f"items={items}")


def test_J_supersession_executed_kept_counts_match_the_four_hand_traced_fixtures():
    """Injection: disable `_supersede` (return survivors unchanged, counts 0) -> every
    kept count below grows and the leak terms ('case study' / 'whitepaper' /
    'onboarding') reappear in the assembled list -> RED. Counts and survivals are the
    EXECUTED outcomes of running this exact pipeline against all four fixtures (E30
    brief, criterion round 3) -- not derived by inspection.
    """
    discovery = _assembled_via_strategy(PROBE2_DISCOVERY, "j-discovery")
    check("probe-2 discovery kept count is 4", len(discovery) == 4, f"{discovery}")
    check("no 'case study' in any discovery item",
          all("case study" not in i.casefold() for i in discovery), f"{discovery}")

    renewal = _assembled_via_strategy(PROBE2_RENEWAL, "j-renewal")
    check("probe-2 renewal kept count is 6", len(renewal) == 6, f"{renewal}")
    check("no 'whitepaper' in any probe-2 renewal item",
          all("whitepaper" not in i.casefold() for i in renewal), f"{renewal}")
    for term in ("budget approval", "msa", "summary email", "seat count"):
        check(f"probe-2 renewal keeps a '{term}' item",
              any(term in i.casefold() for i in renewal), f"{renewal}")
    check("'get the MSA over today' survives dedupe -- 0 shared content tokens with "
          "'draft and send the updated MSA' once stopwords strip the rest of both",
          any("get the msa over today" in i.casefold() for i in renewal), f"{renewal}")

    support = _assembled_via_strategy(PROBE2_SUPPORT, "j-support")
    check("probe-2 support kept count is 4", len(support) == 4, f"{support}")
    check("no 'onboarding' in any support item",
          all("onboarding" not in i.casefold() for i in support), f"{support}")

    arm_a = _assembled_via_strategy(ARM_A_RENEWAL, "j-arm-a")
    check("arm-A renewal kept count is 7", len(arm_a) == 7, f"{arm_a}")
    check("no 'whitepaper' in any arm-A renewal item",
          all("whitepaper" not in i.casefold() for i in arm_a), f"{arm_a}")
    for term in ("budget approval", "msa", "summary email", "seat count"):
        check(f"arm-A renewal keeps a '{term}' item",
              any(term in i.casefold() for i in arm_a), f"{arm_a}")


def test_K_stopwords_are_load_bearing_generic_words_never_supersede():
    """T-K primary: the withdrawn item below shares ONLY the stopword 'today' with the
    real commitment that follows it -- under real STOPWORDS that shared token is
    filtered from both sides (0 overlap) and the real one survives. RED: empty
    STOPWORDS (`S.STOPWORDS = frozenset()`) -- 'today' then counts as a shared content
    token on both sides and the real commitment is wrongly superseded too.
    """
    items = _assembled_via_strategy(SYNTHETIC_STOPWORD_ONLY_OVERLAP, "k-stopword-only")
    check("the real commitment (confirm the seat count) survives the stopword-only overlap",
          any("seat count" in i.casefold() for i in items), f"items={items}")
    check("the withdrawn item itself is not listed",
          all("update" not in i.casefold() for i in items), f"items={items}")

    # T-K secondary sub-check -- INFORMATIONAL ONLY, not a gate (E30 brief): with the
    # four role-noun stopwords removed but _content_tokens still computed on the
    # subject-stripped item, probe-2 renewal still keeps 6 -- the subject-strip alone
    # suffices there, independent of the role-noun stopword fix. No check() call: this
    # cannot move FAILED either way.
    orig_stopwords = S.STOPWORDS
    try:
        S.STOPWORDS = frozenset(orig_stopwords - {"customer", "representative", "rep", "client"})
        renewal_no_role_stopwords = _assembled_via_strategy(PROBE2_RENEWAL, "k-info-renewal")
    finally:
        S.STOPWORDS = orig_stopwords
    print(f"  [INFO] T-K sub-check (informational, not a gate): probe-2 renewal keeps "
          f"{len(renewal_no_role_stopwords)} items with role nouns removed from STOPWORDS "
          f"(subject-strip alone) -- expect 6")


def test_L_dedupe_drops_the_same_speaker_restatement():
    """Support fixture: #4 is the rep restating #1-#3 in one sentence. Injection:
    disable `_dedupe` (no-op, returns (kept, 0)) -> the restatement survives alongside
    the three items it restates, kept count is 5 not 4 -> RED."""
    items = _assembled_via_strategy(PROBE2_SUPPORT, "l-support")
    check("kept count is 4 after dedupe", len(items) == 4, f"items={items}")
    check("customer follow-up survives",
          any("follow up" in i.casefold() for i in items), f"items={items}")
    check("rep restatement (escalation + SLA + usage in one line) is deduped away",
          not any("escalation" in i.casefold() and "sla" in i.casefold() for i in items),
          f"items={items}")


# T-O fixture (correctness refuter, PR #86): a cancellation FOLLOWED by a fresh commitment
# about the same thing. Only the earlier promise is withdrawn; the later one stands.
RECOMMIT_AFTER_CANCEL = [
    {"speaker": "rep", "item": "send the pricing sheet by Friday", "withdrawn": False,
     "evidence": "I'll send the pricing sheet by Friday."},
    {"speaker": "rep", "item": "skip the pricing sheet for now", "withdrawn": False,
     "evidence": "Actually, let's skip the pricing sheet for now, the numbers are moving."},
    {"speaker": "rep", "item": "send the pricing sheet after all, once the numbers settle",
     "withdrawn": False,
     "evidence": "You know what, I'll send the pricing sheet after all once the numbers settle."},
]


def test_O_supersession_is_positional_a_later_recommitment_survives():
    """Order matters: a cancellation withdraws only what came BEFORE it. Fixture: promise ->
    cancellation -> fresh promise about the same sheet. Expected: item #1 superseded,
    #2 removed as the cancellation, #3 KEPT — the rep's final word stands.
    Injection (the bug the refuters found on the first build): compute one global union of
    superseder tokens and drop every sharer regardless of position -> #3 is wiped ->
    kept == 0 -> RED. The four measured fixtures never place a real item after its
    superseder, so without this test the suite is blind to the direction."""
    items = _assembled_via_strategy(RECOMMIT_AFTER_CANCEL, "o-recommit")
    check("exactly one item survives (the later re-commitment)", len(items) == 1,
          f"items={items}")
    check("the survivor is the AFTER-ALL commitment, not the first promise",
          len(items) == 1 and "after all" in items[0].casefold(), f"items={items}")
    check("the cancellation itself is not listed",
          not any("skip" in i.casefold() for i in items), f"items={items}")


def test_P_out_of_order_extraction_is_reordered_by_transcript_position():
    """The model's array is not trusted for order. Fixture = RECOMMIT_AFTER_CANCEL with the
    items SCRAMBLED (re-commitment, cancellation, first promise) but the transcript in true
    order (built from the evidence lines in chronological order). Expected: identical outcome
    to T-O — exactly the after-all re-commitment survives. Injection: remove the
    `_in_transcript_order` sort -> the positional rule reads the scrambled order as
    chronology -> the first promise survives and the re-commitment is superseded -> RED."""
    chronological = RECOMMIT_AFTER_CANCEL
    scrambled = [dict(chronological[2]), dict(chronological[1]), dict(chronological[0])]
    transcript = "\n".join(c["evidence"] for c in chronological)
    case = {"id": "fixture-p-scrambled", "split": "train", "input": transcript, "expected": {}}
    call1_reply = ({"commitments": scrambled}, METRICS_STUB)
    call2_reply = ({"summary": "s", "action_items": [], "nothing_important": True}, METRICS_STUB)
    ctx = _RecordingCtxV2({"system_prompt": AGENT_SYSTEM_PROMPT}, [call1_reply, call2_reply])
    parsed, _m = S.extract_then_assemble(ctx, case)
    items = parsed["action_items"]
    check("scrambled input still yields exactly one survivor", len(items) == 1, f"items={items}")
    check("the survivor is the AFTER-ALL re-commitment (transcript order won, not array order)",
          len(items) == 1 and "after all" in items[0].casefold(), f"items={items}")


def test_M_assembly_shape_and_nothing_important_rule():
    """Injection: keep the model's own `action_items` (skip the assignment), or
    hard-code `nothing_important` regardless of the assembled list -> RED."""
    commitments = [
        {"speaker": "rep", "item": "The rep will draft the proposal by Friday.",
         "evidence": "I will draft the proposal by Friday.", "withdrawn": False},
        {"speaker": "customer", "item": "The customer will review the proposal.",
         "evidence": "I will review the proposal once I get it.", "withdrawn": False},
        {"speaker": "legal", "item": "Legal signs off before the contract is final.",
         "evidence": "Legal signs off before the contract is final.", "withdrawn": False},
    ]
    case = _fixture_case("fixture-m", commitments)
    call1_reply = ({"commitments": commitments}, METRICS_STUB)
    call2_reply = ({"summary": "s", "action_items": ["totally wrong guessed item"],
                    "nothing_important": True}, METRICS_STUB)
    agent = {"system_prompt": AGENT_SYSTEM_PROMPT}
    ctx = _RecordingCtxV2(agent, [call1_reply, call2_reply])
    parsed, _metrics = S.extract_then_assemble(ctx, case)
    items = parsed["action_items"]
    check("owner-prefixed rep item, subject stripped", items[0] == "Rep to draft the proposal by Friday.",
          f"{items}")
    check("owner-prefixed customer item, subject stripped",
          items[1] == "Customer to review the proposal.", f"{items}")
    check("unrecognised speaker -> bare item, NO owner prefix (never guess an owner)",
          items[2] == "legal signs off before the contract is final.", f"{items}")
    check("model's own action_items were discarded", "totally wrong guessed item" not in items)
    check("nothing_important forced False when the assembled list is non-empty",
          parsed["nothing_important"] is False, f"got {parsed.get('nothing_important')}")

    # Empty-assembled branch: nothing_important is left EXACTLY as call 2 returned it.
    empty_case = _fixture_case("fixture-m-empty", [])
    call1_reply_empty = ({"commitments": []}, METRICS_STUB)
    call2_reply_empty = ({"summary": "s", "action_items": ["model guess"],
                          "nothing_important": True}, METRICS_STUB)
    ctx2 = _RecordingCtxV2(agent, [call1_reply_empty, call2_reply_empty])
    parsed_empty, _m = S.extract_then_assemble(ctx2, empty_case)
    check("empty assembled list leaves the model's own nothing_important flag untouched",
          parsed_empty["nothing_important"] is True, f"got {parsed_empty.get('nothing_important')}")
    check("empty assembled list still replaces action_items with []",
          parsed_empty["action_items"] == [], f"got {parsed_empty.get('action_items')}")


def test_N_answer_key_never_leaks_and_the_registry_gained_the_name():
    """Vacuous by construction on a correct build -- extract_then_assemble never reads
    `case['expected']`, so the sentinel below can never appear in call 2's user text or
    the return value. Declared vacuous, kept anyway (T-G's pattern): it exists to catch
    a future build that reads the answer key as a 'defensive top-up'. Also mirrors
    test_E's registration + scoring-invariant checks for this strategy's own target
    agent (transcript-en).
    """
    check("extract-then-assemble is registered", "extract-then-assemble" in S.STRATEGIES)
    check("extract-then-assemble is callable", callable(S.STRATEGIES["extract-then-assemble"]))

    commitments = [
        {"speaker": "rep", "item": "Send the pricing sheet by Friday.",
         "evidence": "I will send the pricing sheet by Friday.", "withdrawn": False},
    ]
    case = _fixture_case("fixture-n", commitments)
    case["expected"] = {"must_commit": ["ZZ-SENTINEL-MUST-COMMIT-ZZ"],
                        "commit_owner": {"ZZ-SENTINEL-MUST-COMMIT-ZZ": "rep"}}
    call1_reply = ({"commitments": commitments}, METRICS_STUB)
    call2_reply = ({"summary": "s", "action_items": [], "nothing_important": False}, METRICS_STUB)
    agent = {"system_prompt": AGENT_SYSTEM_PROMPT}
    ctx = _RecordingCtxV2(agent, [call1_reply, call2_reply])
    parsed, _metrics = S.extract_then_assemble(ctx, case)
    sentinel = "ZZ-SENTINEL-MUST-COMMIT-ZZ"
    _sp2, ut2, _mt2 = ctx.calls[1]
    check("sentinel absent from call 2's user text", sentinel not in ut2)
    check("sentinel absent from the returned parsed output", sentinel not in json.dumps(parsed))

    tcase = TRANSCRIPT_BY_ID["discovery-short-train"]
    empty_ish = {"summary": "Nothing happened on this call.", "action_items": [],
                "nothing_important": True}
    ok, checks = R._bakeoff_score(TRANSCRIPT_PROPS, tcase, empty_ish)
    check(f"{tcase['id']} still armed under bake-off scoring for extract-then-assemble's agent",
          not ok, f"passed with checks={checks} — expectations did not resolve")


def main() -> int:
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)), key=lambda f: f.__name__):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all green'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
