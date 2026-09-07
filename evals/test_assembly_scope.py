"""E27 SCOPED-ASSEMBLY — the witness tests (evals/test_assembly_scope.py).

What this lane ships: `--assembly {full,scoped}` on `runner.py run|diff`, default
`full`. `scoped` is a per-call PROJECTION of the full history for turn k >= 1 of a
`turns`-bearing case: system prompt + the previous turn's final answer + every prior
tool exchange whose CALL ARGS share a word with the current turn's text + the current
turn. Nothing else. Single-turn cases and turn 0 never see the knob.

Each test names the criterion it witnesses (docs/e27-lane-kit-2026-09-03.md, v1 draft):
  (1) default path byte-identical to master — GOLDEN records generated on master
      (1e04ff1) with master's runner, embedded below, compared after stripping the
      only nondeterministic field (wall_ms).
  (2) scoping is observable and bounded — asserted by CONTENT of the messages the
      model actually received, not by count alone.
  (3) the scope-drop trap is RED under scoped and GREEN under full — the kill test:
      a build that accepts the flag and keeps full history cannot make it red.
  (4) turn 0 and single-turn cases are identical under both arms.
  (5) a scoped results file is self-describing; a full one gains no key.
  (6) real entry point: `--snapshot` refuses a scoped run BEFORE inference; `check`
      does not expose the knob at all (CLAUDE.md gotcha 5 — through the CLI).

Plain-assert script, runnable as `python3 evals/test_assembly_scope.py` or via pytest.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
sys.path.insert(0, str(ROOT / "evals"))
import runner  # noqa: E402
from runner import ROOT as RUNNER_ROOT, load_exam, score_case  # noqa: E402
from test_multiturn import ScriptedAdapter, _AGENT, _traj_tools  # noqa: E402

GOLDEN = json.loads(r"""{"lookup-last-contact": {"golden": [{"answer": "Janssens Bakery was last contacted on 2026-07-02 about a chatbot."}, {"metrics": {"completion_tokens": null, "content_chars": 141, "prompt_tokens": null, "reasoning_chars": 0, "retries": 0, "total_tokens": null, "truncated_calls": 0, "unanswered_calls": 0}, "steps": 2, "tool_calls": [{"args": {"company": "Janssens Bakery"}, "tool": "crm_lookup"}], "tool_results": [{"_meta": {"api_version": "v3.2", "rate_limit_remaining": 6234, "request_id": "req_3386431"}, "activity_history": [{"body_preview": "Discussed timeline and scope; agreed to revisit after the internal review. No commercial terms changed on this touchpoint.", "created_by": "Marieke Claes", "direction": "inbound", "duration_minutes": 0, "id": "act_0158312", "is_logged_automatically": false, "occurred_at": "2026-02-19T09:05:00Z", "subject": "Email regarding account follow-up", "type": "email"}, {"body_preview": "Discussed timeline and scope; agreed to revisit after the internal review. No commercial terms changed on this touchpoint.", "created_by": "Marieke Claes", "direction": "outbound", "duration_minutes": 5, "id": "act_3893488", "is_logged_automatically": true, "occurred_at": "2026-02-22T09:12:00Z", "subject": "Call regarding account follow-up", "type": "call"}, {"body_preview": "Discussed timeline and scope; agreed to revisit after the internal review. No commercial terms changed on this touchpoint.", "created_by": "Marieke Claes", "direction": "inbound", "duration_minutes": 10, "id": "act_5692980", "is_logged_automatically": true, "occurred_at": "2026-02-25T09:19:00Z", "subject": "Meeting regarding account follow-up", "type": "meeting"}, {"body_preview": "Discussed timeline and scope; agreed to revisit after the internal review. No commercial terms changed on this touchpoint.", "created_by": "Marieke Claes", "direction": "outbound", "duration_minutes": 15, "id": "act_8276725", "is_logged_automatically": false, "occurred_at": "2026-02-28T09:26:00Z", "subject": "Note regarding account follow-up", "type": "note"}, {"body_preview": "Discussed timeline and scope; agreed to revisit after the internal review. No commercial terms changed on this touchpoint.", "created_by": "Marieke Claes", "direction": "inbound", "duration_minutes": 20, "id": "act_9055704", "is_logged_automatically": true, "occurred_at": "2026-03-03T09:33:00Z", "subject": "Task regarding account follow-up", "type": "task"}, {"body_preview": "Discussed timeline and scope; agreed to revisit after the internal review. No commercial terms changed on this touchpoint.", "created_by": "Marieke Claes", "direction": "outbound", "duration_minutes": 25, "id": "act_1969099", "is_logged_automatically": true, "occurred_at": "2026-03-06T09:40:00Z", "subject": "Email regarding account follow-up", "type": "email"}, {"body_preview": "Discussed timeline and scope; agreed to revisit after the internal review. No commercial terms changed on this touchpoint.", "created_by": "Marieke Claes", "direction": "inbound", "duration_minutes": 30, "id": "act_1285661", "is_logged_automatically": false, "occurred_at": "2026-03-09T09:47:00Z", "subject": "Call regarding account follow-up", "type": "call"}, {"body_preview": "Discussed timeline and scope; agreed to revisit after the internal review. No commercial terms changed on this touchpoint.", "created_by": "Marieke Claes", "direction": "outbound", "duration_minutes": 35, "id": "act_3857280", "is_logged_automatically": true, "occurred_at": "2026-03-12T09:54:00Z", "subject": "Note regarding account follow-up", "type": "note"}], "address": {"city": "Gent", "country": "BE", "postal_code": "2018", "region": "Oost-Vlaanderen", "street": "Nijverheidslaan 22"}, "annual_revenue_eur": 1240000, "contact": "Sofie Janssens", "created_at": "2026-03-21T08:12:44Z", "custom_fields": {"nps_last_score": 8, "onboarding_completed": true, "payment_terms_days": 30, "preferred_language": "nl", "source_campaign": "inbound/organic-search", "vat_number": "BE 0681.204.337"}, "employee_count": 24, "id": "cmp_9802577", "industry": "SMB services", "integration_metadata": {"last_sync_at": "2026-03-29T02:00:00Z", "record_hash": "h_9179189", "sync_version": 42, "synced_from": "folk"}, "last_interaction": "2026-07-02", "lifecycle_stage": "customer", "notes": "Wants a chatbot for the webshop, wants to go live before September.", "object": "company", "owner": {"email": "marieke.claes@example.com", "id": "u_4417", "name": "Marieke Claes", "team": "Commercial NL/BE"}, "phone": "+32 9 233 41 07", "status": "prospect", "tags": ["nl-be", "smb", "inbound", "newsletter-subscriber"], "updated_at": "2026-03-25T16:03:21Z", "website": "https://janssensbakery.example.com"}], "tools_called": ["crm_lookup"]}, true, [], []], "script": ["{\"tool\": \"crm_lookup\", \"args\": {\"company\": \"Janssens Bakery\"}}", "{\"answer\": \"Janssens Bakery was last contacted on 2026-07-02 about a chatbot.\"}"]}, "peeters-contact-followup-outage": {"golden": [{"answer": "Their contact is listed in the CRM record."}, {"metrics": {"completion_tokens": null, "content_chars": 248, "prompt_tokens": null, "reasoning_chars": 0, "retries": 0, "total_tokens": null, "truncated_calls": 0, "unanswered_calls": 0}, "steps": 4, "tools_called": ["deals_list", "crm_lookup"], "turns": [{"completion_tokens": null, "failures": [], "passed": true, "prompt_tokens": null, "steps": 2, "tool_calls": [{"args": {"company": "Peeters Logistics"}, "tool": "deals_list"}], "tools_called": ["deals_list"], "turn": 0}, {"completion_tokens": null, "failures": ["error_recovery: final answer never acknowledges that the 'crm_lookup' fact (contact, name, crm, record) is unavailable — an apology about something else, or answering as if the lookup succeeded, is not recovery"], "passed": false, "prompt_tokens": null, "steps": 2, "tool_calls": [{"args": {"company": "Peeters Logistics"}, "tool": "crm_lookup"}], "tools_called": ["crm_lookup"], "turn": 1}]}, false, ["turn 1: error_recovery: final answer never acknowledges that the 'crm_lookup' fact (contact, name, crm, record) is unavailable — an apology about something else, or answering as if the lookup succeeded, is not recovery"], [{"bucket": "quality", "check": "error_recovery", "turn": 1}]], "script": ["{\"tool\": \"deals_list\", \"args\": {\"company\": \"Peeters Logistics\"}}", "{\"answer\": \"The deal amount for Peeters Logistics is 4200 EUR.\"}", "{\"tool\": \"crm_lookup\", \"args\": {\"company\": \"Peeters Logistics\"}}", "{\"answer\": \"Their contact is listed in the CRM record.\"}"]}}""")


def _strip_wall(o):
    """wall_ms is measured with perf_counter — the ONE field that legitimately
    differs between two runs of the same script. Everything else must be equal."""
    if isinstance(o, dict):
        return {k: _strip_wall(v) for k, v in o.items() if k != "wall_ms"}
    if isinstance(o, list):
        return [_strip_wall(x) for x in o]
    return o


def _committed(case_id: str) -> dict:
    exam = load_exam("crm-followup")
    return next(c for c in exam["cases"] if c["id"] == case_id)


def _score(case, adapter, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return score_case(_AGENT, case, adapter, "scripted", _traj_tools(), **kw)


def _walk(o):
    """Every dict key anywhere in a nested record."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk(v)
    elif isinstance(o, list):
        for x in o:
            yield from _walk(x)


class RecallAdapter:
    """A 'perfect recall, no lookup' model: answers the contact question ONLY if a
    tool_result naming the fact is in the context it was handed; otherwise says it
    has nothing. Deterministic and context-sensitive — which is exactly what a
    scripted replay cannot be, and what makes criterion 3 a real red/green witness
    of the MECHANISM rather than of the script."""

    def __init__(self, script: list):
        self.script = list(script)
        self.seen_messages: list = []

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        self.seen_messages.append([dict(m) for m in messages])
        idx = len(self.seen_messages) - 1
        if idx < len(self.script):
            content = self.script[idx]
        else:
            joined = " ".join(m["content"] for m in messages
                              if m["role"] == "user" and m["content"].startswith('{"tool_result"'))
            content = ('{"answer": "Our contact there is Jan De Vos."}' if "Jan De Vos" in joined
                       else '{"answer": "I do not have that company\'s record in this conversation."}')
        meta = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
                "content_chars": len(content), "reasoning_chars": 0, "finish_reason": "stop"}
        return content, meta


# ------------------------------------------------------------ (1) byte-identity

def test_1_default_and_full_equal_master_golden():
    for case_id, fx in GOLDEN.items():
        case = _committed(case_id)
        default = _strip_wall(list(_score(case, ScriptedAdapter(fx["script"]))))
        full = _strip_wall(list(_score(case, ScriptedAdapter(fx["script"]), assembly="full")))
        assert default == fx["golden"], f"{case_id}: default path drifted from master's golden:\n{json.dumps(default)[:600]}"
        assert full == fx["golden"], f"{case_id}: --assembly full drifted from master's golden"
        keys = set(_walk(full[1]))
        assert "assembly" not in keys and "history_msgs_dropped" not in keys, \
            f"{case_id}: a full run must add NO key: {sorted(keys)}"
    assert "turns" in _committed("peeters-contact-followup-outage"), "golden (b) must be a real multi-turn case"
    assert GOLDEN["peeters-contact-followup-outage"]["golden"][2] is False, \
        "golden (b) must be a FAILING multi-turn record (a widening bug hides on passing ones)"


# ------------------------------------------------- (2) scoping observable

def _three_company_case(third_turn: str, third_expected: dict) -> dict:
    t0 = "What is our contact at Devos Garage?"
    t1 = "And at Janssens Bakery?"
    return {
        "id": "_e27_probe", "split": "train", "turns": [t0, t1, third_turn],
        "turns_expected": [
            {"turn": t0, "expected": {"tools_called": ["crm_lookup"], "answer_contains": ["De Vos"], "max_steps": 3}},
            {"turn": t1, "expected": {"tools_called": ["crm_lookup"], "answer_contains": ["Janssens"], "max_steps": 3}},
            {"turn": third_turn, "expected": third_expected},
        ],
    }


_SCRIPT_2_TURNS = ['{"tool": "crm_lookup", "args": {"company": "Devos Garage"}}',
                   '{"answer": "Our contact at Devos Garage is Jan De Vos."}',
                   '{"tool": "crm_lookup", "args": {"company": "Janssens Bakery"}}',
                   '{"answer": "At Janssens Bakery it is Sofie Janssens."}']


def test_2_scoped_keeps_named_company_and_last_answer_only():
    t2 = "Back to Devos Garage — what did the record say about phase 2?"
    case = _three_company_case(t2, {"answer_contains": ["phase 2"], "max_steps": 2})
    script = _SCRIPT_2_TURNS + ['{"answer": "Devos Garage is considering phase 2."}']
    full_ad, scoped_ad = ScriptedAdapter(script), ScriptedAdapter(script)
    _score(case, full_ad, assembly="full")
    _, trace, passed, _, fc = _score(case, scoped_ad, assembly="scoped")
    assert passed, fc
    full_ctx, scoped_ctx = full_ad.seen_messages[-1], scoped_ad.seen_messages[-1]
    contents = [m["content"] for m in scoped_ctx]
    # kept: system, the Devos exchange (call + result), the previous answer, this turn
    assert scoped_ctx[0]["role"] == "system"
    assert any('"company": "Devos Garage"' in c for c in contents), contents[:3]
    assert any(c.startswith('{"tool_result"') and "Jan De Vos" in c for c in contents)
    assert _SCRIPT_2_TURNS[3] in contents, "previous final answer (the raw assistant message) must be kept"
    assert contents[-1] == t2
    # dropped: both earlier user turns, the Janssens exchange, the turn-0 answer
    assert "What is our contact at Devos Garage?" not in contents
    assert "And at Janssens Bakery?" not in contents
    assert not any('"company": "Janssens Bakery"' in c for c in contents), "Janssens exchange must be dropped"
    assert not any(c.startswith('{"tool_result"') and "Sofie Janssens" in c for c in contents)
    assert _SCRIPT_2_TURNS[1] not in contents, "turn-0 answer is not 'the previous answer'"
    assert len(scoped_ctx) < len(full_ctx), (len(scoped_ctx), len(full_ctx))
    turns = trace["turns"]
    assert turns[2]["history_msgs_dropped"] == 5, turns[2]   # u0, a0-answer, u1, Janssens call, Janssens result
    assert turns[0]["history_msgs_dropped"] == 0 and turns[1]["history_msgs_dropped"] == 3, [t["history_msgs_dropped"] for t in turns]


# --------------------------------------------- (3) the scope-drop trap, RED

def test_3_referential_callback_red_under_scoped_green_under_full():
    t2 = "Going back to the FIRST company we discussed — what is our contact there?"
    case = _three_company_case(t2, {"answer_contains": ["De Vos"], "max_steps": 2})
    _, _, passed_full, _, fc_full = _score(case, RecallAdapter(_SCRIPT_2_TURNS), assembly="full")
    _, trace_s, passed_scoped, _, fc_scoped = _score(case, RecallAdapter(_SCRIPT_2_TURNS), assembly="scoped")
    assert passed_full, f"under full history the recall model finds De Vos: {fc_full}"
    assert not passed_scoped, "scoped MUST drop the un-named company's record — the trap is the point"
    assert [f["check"] for f in fc_scoped] == ["answer_contains"] and fc_scoped[0]["turn"] == 2, fc_scoped
    assert trace_s["turns"][2]["history_msgs_dropped"] == 7, trace_s["turns"][2]   # everything but the last answer


# ------------------------------------ (4) turn 0 and single-turn never see it

def test_4_turn0_and_single_turn_identical_across_arms():
    fx = GOLDEN["lookup-last-contact"]
    case = _committed("lookup-last-contact")
    assert "turns" not in case
    scoped = _strip_wall(list(_score(case, ScriptedAdapter(fx["script"]), assembly="scoped")))
    assert scoped == fx["golden"], "a single-turn case under --assembly scoped must equal master's golden"
    assert "assembly" not in set(_walk(scoped[1]))
    t2 = "Back to Devos Garage — what did the record say about phase 2?"
    case = _three_company_case(t2, {"answer_contains": ["phase 2"], "max_steps": 2})
    script = _SCRIPT_2_TURNS + ['{"answer": "Devos Garage is considering phase 2."}']
    a_full, a_scoped = ScriptedAdapter(script), ScriptedAdapter(script)
    _score(case, a_full, assembly="full")
    _score(case, a_scoped, assembly="scoped")
    assert a_full.seen_messages[0] == a_scoped.seen_messages[0], "turn 0's first call must be identical"
    assert a_full.seen_messages[1] == a_scoped.seen_messages[1], "turn 0's second call (after its tool result) too"


# -------------------------------------------- (5) self-describing records

def test_5_scoped_records_self_describing_full_adds_nothing():
    t2 = "Back to Devos Garage — what did the record say about phase 2?"
    case = _three_company_case(t2, {"answer_contains": ["phase 2"], "max_steps": 2})
    script = _SCRIPT_2_TURNS + ['{"answer": "Devos Garage is considering phase 2."}']
    _, trace_f, *_ = _score(case, ScriptedAdapter(script), assembly="full")
    _, trace_s, *_ = _score(case, ScriptedAdapter(script), assembly="scoped")
    for t in trace_s["turns"]:
        assert t["assembly"] == "scoped" and isinstance(t["history_msgs_dropped"], int), t
    assert trace_s["turns"][0]["history_msgs_dropped"] == 0
    for t in trace_f["turns"]:
        assert "assembly" not in t and "history_msgs_dropped" not in t, t
    try:
        _score(case, ScriptedAdapter(script), assembly="summarised")
    except ValueError as exc:
        assert "assembly" in str(exc)
    else:
        raise AssertionError("an unknown assembly mode must RAISE, never silently run full")


# ------------------------------------------------- (6) real entry point

def test_6_cli_snapshot_refuses_scoped_and_check_has_no_knob():
    snap = RUNNER_ROOT / "evals" / "crm-followup" / "snapshot.json"
    before = snap.read_bytes()
    p = subprocess.run([sys.executable, "sandbox/runner.py", "run", "crm-followup",
                        "--provider", "stub", "--assembly", "scoped", "--snapshot"],
                       cwd=RUNNER_ROOT, capture_output=True, text=True, timeout=120)
    assert p.returncode != 0, p.stdout[-400:]
    assert "--snapshot requires --assembly full" in (p.stderr + p.stdout)
    assert "-> results/" not in p.stdout and "heldout" not in p.stdout, \
        f"must refuse BEFORE running any case (no summary line, no results file): {p.stdout[-300:]}"
    assert snap.read_bytes() == before, "the committed snapshot must be untouched"
    h = subprocess.run([sys.executable, "sandbox/runner.py", "check", "--help"],
                       cwd=RUNNER_ROOT, capture_output=True, text=True)
    assert "--assembly" not in h.stdout, "check is the gate: it reproduces the full-history snapshot only"
    for cmd in ("run", "diff"):   # wired onto both; check (the gate) deliberately not
        h = subprocess.run([sys.executable, "sandbox/runner.py", cmd, "--help"],
                           cwd=RUNNER_ROOT, capture_output=True, text=True)
        assert "--assembly {full,scoped}" in h.stdout, (cmd, h.stdout)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        print(f"running {t.__name__}")
        t()
        print("  PASS")
    print(f"\n{len(tests)} test groups; all passed (plain-assert script)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
