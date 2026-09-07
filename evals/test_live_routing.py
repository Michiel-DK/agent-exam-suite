"""LIVE-ROUTING lane (A1 route table · A2 tiered fallback · A2b live output checks) —
the witness tests.

What ships: `routes.yaml` (ordered tiers per agent, tier 0 == the committed champion),
`runner.load_routes`, `runner.live_output_checks` (the exam's EXPECTATION-FREE checks on
a live output, reusing score_trajectory / properties.py — no new checker), and
`live_run_and_log` walking the tiers: escalate on a DEAD run or FAILED checks, never on a
healthy one; an explicit provider/model bypasses the table entirely. The JSONL schema is
additive — `attempts`/`tier`/`checks_failed` appear only when they happened — so
serve.py._live_payload and cmd_promote keep reading the file unchanged.

Every test says what a WRONG build would do and which assertion catches it. Model calls
are scripted per tier by model name (TierAdapter); real agents/<name>/tools.py is used
for the trajectory agent (it is dict-backed). Plain-assert script, also collected by pytest.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import runner  # noqa: E402
from runner import (TerminationError, live_output_checks, live_run_and_log,  # noqa: E402
                    load_agent, load_exam, load_routes)

SCRATCH = ROOT / "results" / "_test_live_routing"   # results/ is gitignored


class TierAdapter:
    """Scripted outputs keyed by MODEL NAME, so one adapter can play every tier.
    A script entry may be a string (returned) or an Exception (raised, e.g. a death).
    Records every call so 'never escalated' is asserted by call count, not by absence
    of a key."""

    def __init__(self, by_model: dict):
        self.by_model = {m: list(v) for m, v in by_model.items()}
        self.calls: list = []

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        self.calls.append(model)
        if model not in self.by_model:
            raise AssertionError(f"unexpected call to tier model {model!r} — "
                                 f"a healthy earlier tier must never escalate")
        out = self.by_model[model].pop(0)
        if isinstance(out, Exception):
            raise out
        return out, {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
                     "content_chars": len(out), "reasoning_chars": 0, "finish_reason": "stop"}


@contextlib.contextmanager
def _routes(table: dict, adapter: TierAdapter):
    """Point runner at a scratch routes.yaml and a scripted adapter, then restore."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "routes.yaml"
    path.write_text(yaml.safe_dump(table))
    saved = (runner.ROUTES_PATH, runner.adapter_for)
    runner.ROUTES_PATH = path
    runner.adapter_for = lambda *a, **k: adapter
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        runner.ROUTES_PATH, runner.adapter_for = saved


def _dead():
    return TerminationError("scripted death", {"finish_reason": "length",
                                               "completion_tokens": 0, "content_chars": 0})


EN_REPLY = json.dumps({"reply": "Thank you for your message. I have read your proposal "
                                "carefully and would be glad to discuss it with you next "
                                "week. Please let me know which afternoon suits you best, "
                                "and I will send a calendar invitation. Best regards, Michiel"})
EN_INPUT = ("Hello, thanks for sending over the proposal. Could we schedule a call to "
            "discuss the next steps sometime next week? Best regards, Anna")


# ------------------------------------------------- (A1) the table itself

def test_1_committed_routes_tier0_is_the_champion_for_every_agent():
    """WRONG BUILD: routes.yaml drifts from agent.yaml (a tier-0 that the exam never
    snapshotted). Also: an agent missing from the table would silently run single-tier;
    the table must be complete."""
    table = yaml.safe_load((ROOT / "routes.yaml").read_text())
    agents = sorted(p.name for p in (ROOT / "agents").iterdir() if (p / "agent.yaml").exists())
    assert sorted(table) == agents, f"routes.yaml agents {sorted(table)} != {agents}"
    for name in agents:
        tiers = load_routes(name)
        champ = load_agent(name)
        assert tiers[0] == {"provider": champ["provider"], "model": champ["model"]}, \
            f"{name}: tier 0 {tiers[0]} is not the champion {champ['provider']}/{champ['model']}"
        assert len(tiers) >= 2, f"{name}: a route table with one tier has no fallback"
        assert len({(t['provider'], t['model']) for t in tiers}) == len(tiers), f"{name}: duplicate tier"


def test_1b_malformed_table_raises_never_empty():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    bad = SCRATCH / "bad.yaml"
    saved = runner.ROUTES_PATH
    try:
        bad.write_text("reply-draft:\n  - {model: only-a-model}\n")
        runner.ROUTES_PATH = bad
        try:
            load_routes("reply-draft")
        except ValueError as exc:
            assert "tier 0" in str(exc)
        else:
            raise AssertionError("a tier without a provider must RAISE, not load as []")
        bad.write_text("reply-draft: []\n")
        try:
            load_routes("reply-draft")
        except ValueError:
            pass
        else:
            raise AssertionError("an empty tier list must RAISE")
        runner.ROUTES_PATH = SCRATCH / "does-not-exist.yaml"
        assert load_routes("reply-draft") == [], "no file -> [] (single-tier path), never an error"
    finally:
        runner.ROUTES_PATH = saved


# ------------------------------------------- (default path) explicit model bypasses

def test_2_explicit_model_is_single_tier_and_schema_unchanged():
    """WRONG BUILD: the table is consulted even when the caller pinned a model, or the
    healthy single-tier entry grows new keys. Pre-lane schema: {ts, model, provider,
    input, output, metrics} for a plain agent."""
    ad = TierAdapter({"pinned": [EN_REPLY], "t1": [EN_REPLY]})
    with _routes({"reply-draft": [{"provider": "ollama", "model": "t0"},
                                  {"provider": "ollama", "model": "t1"}]}, ad):
        entry, record = live_run_and_log("reply-draft", EN_INPUT, model="pinned", log=False)
    assert ad.calls == ["pinned"], ad.calls
    assert list(entry) == ["ts", "model", "provider", "input", "output", "metrics"], list(entry)
    assert entry["model"] == "pinned"
    assert "attempts" not in record and "tier" not in record and "checks_failed" not in record


def test_2b_explicit_model_death_never_falls_back_to_the_table():
    """Test-honesty refuter's mutant: an override applied PER TIER (so the table is
    still walked after the pinned model dies) passed every other test. WRONG BUILD:
    a second call to any table tier. Correct: exactly one call, then TerminationError."""
    ad = TierAdapter({"pinned": [_dead()], "t0": [EN_REPLY], "t1": [EN_REPLY]})
    with _routes(_two_tier(), ad):
        try:
            live_run_and_log("reply-draft", EN_INPUT, model="pinned", log=False)
        except TerminationError:
            pass
        else:
            raise AssertionError("a dead explicit-model run must raise, not fall back")
    assert ad.calls == ["pinned"], f"table consulted after an explicit override: {ad.calls}"


def test_2c_explicit_model_bad_answer_is_flagged_on_the_single_tier_path():
    """Correctness refuter: the ONE declared behaviour change. A single-tier run whose
    answer fails the checks carries checks_failed (no attempts/tier — nothing else
    ran) and cmd_live exits 2; master exited 0 on the same input. WRONG BUILD: checks
    gated on len(tiers) > 1, which would let a fabricated answer through unflagged."""
    ad = TierAdapter({"pinned": [json.dumps({"reply": ""})]})
    with _routes(_two_tier(), ad):
        entry, record = live_run_and_log("reply-draft", EN_INPUT, model="pinned", log=False)
    assert ad.calls == ["pinned"]
    assert record["checks_failed"] and "attempts" not in record and "tier" not in record
    assert list(entry) == ["ts", "model", "provider", "input", "output", "metrics", "checks_failed"]
    ad2 = TierAdapter({"pinned": [json.dumps({"reply": ""})]})
    saved = runner.adapter_for
    runner.adapter_for = lambda *a, **k: ad2
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = runner.cmd_live(SimpleNamespace(agent="reply-draft", input=EN_INPUT,
                                                 provider=None, model="pinned"))
    finally:
        runner.adapter_for = saved
    assert rc == 2


# ------------------------------------------------- (A2) escalation rules

def _two_tier(agent="reply-draft"):
    return {agent: [{"provider": "ollama", "model": "t0"}, {"provider": "ollama", "model": "t1"}]}


def test_3_healthy_tier0_never_escalates():
    """WRONG BUILD: always tries every tier (or the last). TierAdapter raises on any
    call to t1, and the schema must stay the single-tier one."""
    ad = TierAdapter({"t0": [EN_REPLY]})
    with _routes(_two_tier(), ad):
        entry, record = live_run_and_log("reply-draft", EN_INPUT, log=False)
    assert ad.calls == ["t0"]
    assert entry["model"] == "t0" and "attempts" not in record and "tier" not in record


def test_4_dead_tier0_escalates_to_tier1_once_and_records_both():
    """WRONG BUILD: a death is logged and raised without trying the fallback (the
    pre-lane behaviour), or the fallback is tried twice."""
    ad = TierAdapter({"t0": [_dead()], "t1": [EN_REPLY]})
    with _routes(_two_tier(), ad):
        entry, record = live_run_and_log("reply-draft", EN_INPUT, log=False)
    assert ad.calls == ["t0", "t1"], ad.calls
    assert entry["model"] == "t1" and record["tier"] == 1
    assert [a["tier"] for a in record["attempts"]] == [0, 1]
    assert record["attempts"][0]["termination"]["finish_reason"] == "length"
    assert "termination" not in record, "the FINAL record is the healthy tier-1 answer"
    assert record["output"]["reply"].startswith("Thank you"), record["output"]


def test_5_failed_checks_on_tier0_escalate_and_name_the_check():
    """A2b. WRONG BUILD: escalation only on death — an EMPTY reply from tier 0 would be
    returned as a success. check_has_reply is the exam's own check, reused."""
    ad = TierAdapter({"t0": [json.dumps({"reply": ""})], "t1": [EN_REPLY]})
    with _routes(_two_tier(), ad):
        entry, record = live_run_and_log("reply-draft", EN_INPUT, log=False)
    assert ad.calls == ["t0", "t1"]
    failed = record["attempts"][0]["checks_failed"]
    assert any(f.startswith("check_has_reply") for f in failed), failed
    assert entry["model"] == "t1" and "checks_failed" not in record


def test_6_all_tiers_fail_checks_returns_flagged_and_cli_exits_2():
    """WRONG BUILD: the last tier's bad answer comes back clean (exit 0)."""
    ad = TierAdapter({"t0": [json.dumps({"reply": ""})], "t1": [json.dumps({"reply": ""})]})
    with _routes(_two_tier(), ad):
        entry, record = live_run_and_log("reply-draft", EN_INPUT, log=False)
        assert record["tier"] == 1 and record["checks_failed"], record
        assert all("checks_failed" in a for a in record["attempts"])
        # through cmd_live (log=True path writes to results/live — disposable)
        out = io.StringIO()
        ad2 = TierAdapter({"t0": [json.dumps({"reply": ""})], "t1": [json.dumps({"reply": ""})]})
        runner.adapter_for = lambda *a, **k: ad2
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = runner.cmd_live(SimpleNamespace(agent="reply-draft", input=EN_INPUT,
                                                 provider=None, model=None))
    assert rc == 2, rc
    assert json.loads(out.getvalue())["checks_failed"]


def test_7_all_tiers_dead_raises_after_recording_every_attempt():
    """WRONG BUILD: swallows the final death, or raises before the fallback ran."""
    ad = TierAdapter({"t0": [_dead()], "t1": [_dead()]})
    with _routes(_two_tier(), ad):
        try:
            live_run_and_log("reply-draft", EN_INPUT, log=False)
        except TerminationError as exc:
            assert "emitted no answer" in str(exc)
        else:
            raise AssertionError("two dead tiers must still raise TerminationError")
    assert ad.calls == ["t0", "t1"], ad.calls


# ------------------------------------------ (A2b) the checks, per exam mode

def test_8_trajectory_checks_catch_a_fabricated_number_and_pass_a_grounded_one():
    """Uses the REAL agents/crm-followup/tools.py (dict-backed) and score_trajectory
    with an empty expected block. WRONG BUILD: a checker that needs `expected`, or a
    new normaliser (gotcha 4) — this reuses the one in score_trajectory."""
    exam = load_exam("crm-followup")
    q = "How much is the Janssens Bakery deal?"
    fab = TierAdapter({"t0": [json.dumps({"answer": "The Janssens Bakery deal is 7777 EUR."})],
                       "t1": [json.dumps({"tool": "deals_list", "args": {"company": "Janssens Bakery"}}),
                              json.dumps({"answer": "The Janssens Bakery deal is 6500 EUR."})]})
    with _routes(_two_tier("crm-followup"), fab):
        entry, record = live_run_and_log("crm-followup", q, log=False)
    assert fab.calls == ["t0", "t1", "t1"], fab.calls
    failed = record["attempts"][0]["checks_failed"]
    assert any("7777" in f for f in failed), failed          # ungrounded number named
    assert entry["model"] == "t1" and "checks_failed" not in record
    assert record["trace"]["tools_called"] == ["deals_list"]
    # direct: the function itself, both directions
    good_trace = {"tools_called": ["deals_list"], "tool_calls": [{"tool": "deals_list", "args": {"company": "Janssens Bakery"}}],
                  "tool_results": [{"amount_eur": 6500}], "steps": 2}
    assert live_output_checks("crm-followup", exam, {"answer": "6500 EUR"}, good_trace, q) == []
    bad = live_output_checks("crm-followup", exam, {"answer": "6500 EUR"},
                             {"tools_called": [], "tool_calls": [], "tool_results": [], "steps": 1}, q)
    assert bad and "6500" in bad[0], bad


def test_9_label_and_field_modes_are_structural_only_and_say_so():
    """Declared gap: vocabulary is not checked (it lives in the prompt). A missing key
    IS caught."""
    assert live_output_checks("email-triage", load_exam("email-triage"), {"label": "reply_now"}, None, "x") == []
    assert live_output_checks("email-triage", load_exam("email-triage"), {"lable": "reply_now"}, None, "x") == ["output missing 'label'"]
    assert live_output_checks("expense-categorization", load_exam("expense-categorization"),
                              {"category": "software"}, None, "x") == ["output missing 'recurring'"]
    assert "structural only" in live_output_checks.__doc__


def test_10_non_termination_error_on_a_tier_propagates_loud_no_fallback():
    """Declared, not handled: an unpulled model / unknown provider / parse ValueError
    is NOT a termination — it propagates immediately, no escalation, no swallow.
    WRONG BUILD: a bare except that escalates (hides the operational error) or
    returns a placeholder."""
    class Unpulled(RuntimeError):
        pass
    ad = TierAdapter({"t0": [Unpulled("model 't0' not found (pull it first)")], "t1": [EN_REPLY]})
    with _routes(_two_tier(), ad):
        try:
            live_run_and_log("reply-draft", EN_INPUT, log=False)
        except Unpulled as exc:
            assert "not found" in str(exc)
        else:
            raise AssertionError("an operational error must propagate, never be swallowed")
    assert ad.calls == ["t0"], f"must not escalate past an operational error: {ad.calls}"


def test_11_logged_flagged_line_has_what_promote_needs():
    """cmd_promote reads a live line and requires only valid JSON with an 'input'
    field (runner.py cmd_promote); a flagged multi-tier line must still satisfy that.
    Uses the line test_6 wrote to results/live/ (gitignored)."""
    # Self-contained: writes its OWN flagged multi-tier line (log=True) and reads it
    # back — the first version read test_6's line and failed under the plain-assert
    # runner's name-sorted order (test_11 runs before test_6). Order-independent now.
    ad = TierAdapter({"t0": [json.dumps({"reply": ""})], "t1": [json.dumps({"reply": ""})]})
    with _routes(_two_tier(), ad):
        live_run_and_log("reply-draft", EN_INPUT, log=True)
    path = ROOT / "results" / "live" / "reply-draft.jsonl"
    last = json.loads(path.read_text().splitlines()[-1])
    assert "input" in last and last["checks_failed"] and last["tier"] == 1, last.keys()
    assert [a["tier"] for a in last["attempts"]] == [0, 1]


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        print(f"running {t.__name__}")
        t()
        print("  PASS")
    print(f"\n{len(tests)} test groups; all passed (plain-assert script)")
    return 0


# ------------------------------------------------- HOSTED-TIERS (2026-09-05)

def test_12_committed_hosted_tiers_are_pinned_and_last():
    """A hosted tier is the configuration it was MEASURED under: pinned to the creator
    endpoint (docs/probes/hosted-sameday-2026-09-04/RESULTS.md) and behind every local
    tier (data leaves the laptop last). WRONG BUILD: an unpinned openrouter tier, or a
    hosted tier ahead of a local one."""
    table = yaml.safe_load((ROOT / "routes.yaml").read_text())
    hosted = [(name, i, t) for name, tiers in table.items() for i, t in enumerate(tiers)
              if t["provider"] != "ollama"]
    assert hosted, "the committed table carries no hosted tier — this test would be vacuous"
    for name, i, t in hosted:
        assert t.get("provider_routing", {}).get("allow_fallbacks") is False and \
            t["provider_routing"].get("order"), f"{name} tier {i} is not pinned: {t}"
        assert all(x["provider"] == "ollama" for x in table[name][:i]), \
            f"{name}: hosted tier {i} sits ahead of a local tier"
        loaded = load_routes(name)[i]
        assert loaded["provider_routing"] == t["provider_routing"], loaded


def test_13_tier_pin_reaches_the_adapter_on_that_tier_only():
    """The pin travels from the tier to adapter_for as provider_routing, and the NEXT
    tier starts clean (the agent dict is not mutated). Captured at get_adapter, the
    single seam every adapter is built through. WRONG BUILD: pin applied per agent
    (leaks to tier 1), or dropped by load_routes' whitelist copy."""
    seen = []
    ad = TierAdapter({"t0": [_dead()], "t1": [EN_REPLY]})
    real_get = runner.get_adapter

    def fake_get(provider, timeout=None, **kw):
        seen.append((provider, kw.get("provider_routing")))
        return ad
    table = {"reply-draft": [{"provider": "ollama", "model": "t0",
                              "provider_routing": {"order": ["x"], "allow_fallbacks": False}},
                             {"provider": "ollama", "model": "t1"}]}
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "routes.yaml"
    path.write_text(yaml.safe_dump(table))
    saved = (runner.ROUTES_PATH, runner.get_adapter)
    runner.ROUTES_PATH, runner.get_adapter = path, fake_get
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            entry, record = live_run_and_log("reply-draft", EN_INPUT, log=False)
    finally:
        runner.ROUTES_PATH, runner.get_adapter = saved
    assert seen == [("ollama", {"order": ["x"], "allow_fallbacks": False}), ("ollama", None)], seen
    assert entry["model"] == "t1"


def test_14_unknown_tier_key_raises_never_dropped():
    """A typo'd pin key (`provider_rounting`) must not load as an unpinned tier."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "routes.yaml"
    path.write_text(yaml.safe_dump({"reply-draft": [{"provider": "ollama", "model": "a"},
                                                   {"provider": "ollama", "model": "b",
                                                    "provider_rounting": {"order": ["x"]}}]}))
    saved = runner.ROUTES_PATH
    runner.ROUTES_PATH = path
    try:
        try:
            load_routes("reply-draft")
        except ValueError as exc:
            assert "unknown key" in str(exc) and "provider_rounting" in str(exc), str(exc)
        else:
            raise AssertionError("an unknown tier key loaded silently")
        path.write_text(yaml.safe_dump({"reply-draft": [{"provider": "ollama", "model": "a"},
                                                       {"provider": "ollama", "model": "b",
                                                        "provider_routing": "z-ai"}]}))
        try:
            load_routes("reply-draft")
        except ValueError as exc:
            assert "must be a mapping" in str(exc), str(exc)
        else:
            raise AssertionError("a non-mapping provider_routing loaded silently")
    finally:
        runner.ROUTES_PATH = saved


if __name__ == "__main__":
    sys.exit(main())
