#!/usr/bin/env python3
"""Deterministic pins for E10's ladder rungs, v2 (S-E10-LADDER-RUNGS-V2) — no model.

    python3 evals/test_e10_ladder.py

The scorer semantics themselves are tested both-direction in
sandbox/test_trajectory_checks.py; this file pins the fixtures and case wiring:

  A. the 3 new crm-followup rung-A case ids exist with their committed splits, all
     non-abstention (the D3 ceiling in test_pr2_hardcases.py stays honest);
  B. error induction is DETERMINISTIC: the mock raises for exactly the two
     _BACKEND_DOWN companies, twice in a row, and each rung-A case requires the
     erroring tool via tools_called (the 'designed outage occurred' clause is only
     deterministic because of that coupling);
  C. every rung-A case declares the full error_recovery object ({tool, fact}) and
     its declared tool IS the one _BACKEND_DOWN forces down — a case anchored on a
     tool that never errors would fail loud on every run;
  D. the rung-B decoys exist in the MOCK ONLY and are deterministic; the live
     agents/crm-followup/tools.py deliberately has NO decoys and NO forced raise
     (PR #20 review: exams never touch the live file), while the two REAL tools
     keep identical signatures mock-vs-live (golden principle);
  E. the invoice decoy amounts differ from the open-deal amounts (the trap answers
     wrong, not right) — kept armed for the future case that isolates rung B;
  F. no committed case carries tools_offered / tools_allowed yet — rung B is
     declared UNARMED in cases.json not_verified; if a case arms it, that
     declaration must be rewritten (this check will remind whoever does it).

Plain asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
from runner import _load_module  # noqa: E402

FAILED: list[str] = []

RUNG_A_IDS = {
    "peeters-outage-guess-bait": "train",
    "peeters-outage-fill-in": "heldout",
    "peeters-outage-honest-ack": "heldout",
}
DECOY_TOOLS = ("calendar_lookup", "invoice_lookup", "contact_search",
               "email_log", "note_search")
REAL_TOOLS = ("crm_lookup", "deals_list")


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def load_cases() -> dict[str, dict]:
    cases = json.loads(
        (ROOT / "evals" / "crm-followup" / "cases.json").read_text())["cases"]
    return {c["id"]: c for c in cases}


def mock():
    return _load_module(ROOT / "evals" / "crm-followup" / "tools_mock.py",
                        "crm_mock_e10_test")


def live():
    return _load_module(ROOT / "agents" / "crm-followup" / "tools.py",
                        "crm_live_e10_test")


def test_a_ids_splits_nonabstention():
    cases = load_cases()
    for cid, split in RUNG_A_IDS.items():
        c = cases.get(cid)
        check(f"{cid}: present in split {split!r}",
              c is not None and c.get("split") == split,
              "missing" if c is None else f"split {c.get('split')!r}")
        if c is not None:
            check(f"{cid}: non-abstention (no answer_contains_any)",
                  "answer_contains_any" not in c["expected"])


def test_b_error_induction_deterministic():
    m = mock()
    for tool, company in (("crm_lookup", "Peeters Logistics"),
                          ("deals_list", "Mertens Interieur")):
        raised = 0
        for _ in range(2):
            try:
                getattr(m, tool)(company=company)
            except RuntimeError:
                raised += 1
        check(f"mock {tool}({company!r}) raises, deterministically", raised == 2,
              f"raised {raised}/2")
    for cid in RUNG_A_IDS:
        exp = load_cases()[cid]["expected"]
        check(f"{cid}: requires the erroring tool via tools_called",
              exp["error_recovery"]["tool"] in exp.get("tools_called", []))


def test_c_error_recovery_config_anchored_on_forced_outage():
    m = mock()
    for cid in RUNG_A_IDS:
        er = load_cases()[cid]["expected"].get("error_recovery")
        check(f"{cid}: error_recovery is a full object",
              isinstance(er, dict) and isinstance(er.get("tool"), str)
              and isinstance(er.get("fact"), list) and len(er["fact"]) > 0,
              repr(er))
        if isinstance(er, dict):
            check(f"{cid}: declared tool {er.get('tool')!r} is a forced outage",
                  er.get("tool") in m._BACKEND_DOWN)


def test_d_decoys_mock_only_and_signatures_match():
    m, lv = mock(), live()
    for tool in DECOY_TOOLS:
        check(f"decoy {tool}: exists in mock", callable(getattr(m, tool, None)))
        check(f"decoy {tool}: deliberately ABSENT from live tools.py",
              getattr(lv, tool, None) is None)
    for tool in REAL_TOOLS:
        check(f"real {tool}: same signature mock vs live",
              inspect.signature(getattr(m, tool))
              == inspect.signature(getattr(lv, tool)))
        if callable(getattr(m, tool, None)):
            arg = {"company": "Janssens Bakery"}
            check(f"real {tool}: mock deterministic",
                  getattr(m, tool)(**arg) == getattr(m, tool)(**arg))
    # The forced outage is exam-fixture-only: the live file must not raise for
    # the _BACKEND_DOWN companies (it simply has no such records).
    for tool, company in (("crm_lookup", "Peeters Logistics"),
                          ("deals_list", "Mertens Interieur")):
        try:
            lv_result = getattr(lv, tool)(company=company)
            check(f"live {tool}({company!r}) does NOT raise (no forced outage "
                  f"in live)", isinstance(lv_result, (dict, list)))
        except Exception as exc:
            check(f"live {tool}({company!r}) does NOT raise (no forced outage "
                  f"in live)", False, repr(exc))
    for tool in DECOY_TOOLS:
        fn = getattr(m, tool)
        arg = ({"name": "Sofie"} if tool == "contact_search" else
               {"query": "chatbot"} if tool == "note_search" else
               {"company": "Janssens Bakery"})
        check(f"decoy {tool}: deterministic", fn(**arg) == fn(**arg))


def test_e_invoice_trap_answers_wrong():
    m = mock()
    for company, open_amount in (("Janssens Bakery", 6500), ("Devos Garage", 9000)):
        invoices = m.invoice_lookup(company=company)
        amounts = {i["amount_eur"] for i in invoices}
        check(f"invoice decoy for {company} never returns the open-deal "
              f"amount {open_amount}", open_amount not in amounts, str(amounts))


def test_f_rung_b_unarmed_matches_declaration():
    """cases.json's not_verified declares rung B UNARMED. If a future case arms
    tools_offered / tools_allowed, that declaration is stale — rewrite it (and
    this pin) in the same change."""
    armed = [cid for cid, c in load_cases().items()
             if "tools_offered" in c or "tools_allowed" in c["expected"]]
    check("no committed case arms tools_offered/tools_allowed (rung B declared "
          "unarmed; rewrite not_verified if you arm it)", not armed, str(armed))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(FAILED)} failed assertion(s)" + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
