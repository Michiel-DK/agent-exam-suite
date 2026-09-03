#!/usr/bin/env python3
"""Deterministic proof of PR2's allocation (S-PR2-HARDCASES) — no model, no server.

    python3 evals/test_pr2_hardcases.py

Pins the +28 hard-case allocation (suite 35 -> 63) from the operator-approved table
(docs/exam-audit-2026-07-22.md C0 + the 6 re-derived reply-draft cases):

  email-triage           10 -> 19  (+2 train, +7 heldout: 6x D1 borderline + 1x D4 long)
  expense-categorization 10 -> 15  (+1 train, +4 heldout, none 'other'   — D2)
  crm-followup            7 -> 12  (+2 train, +3 heldout, non-abstention — D3)
  reply-draft             8 -> 17  (+3 train, +6 heldout: D8 French pair, D4 long,
                                    3 capability keeps, 1 caught-class probe,
                                    2 instrument-probes)

and the per-finding targets that motivated them:
  D2: heldout 'other' share falls 40% -> 22% (2 of 9)
  D3: heldout abstention share falls 75% -> 43% (3 of 7)
  D4: one input > 294 chars in email-triage AND reply-draft
  D8: both French inputs detect as 'fr' (never 'unknown') via properties._lang
  QA: every new crm answer_contains needle is derivable from tools_mock data
      (a case whose answer is not in the mock is a broken case)

Plain asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
from runner import _load_module  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def load(agent: str) -> list[dict]:
    return json.loads((ROOT / "evals" / agent / "cases.json").read_text())["cases"]


def split_counts(cases: list[dict]) -> tuple[int, int]:
    train = sum(1 for c in cases if c.get("split", "train") == "train")
    return train, len(cases) - train


# (agent, total, train, heldout) — FLOORS, not equalities.
#
# These were exact pins in the first draft. Adversarial review (scope-adherence +
# pr-test-analyzer, 2026-07-26) correctly called that a snapshot-of-a-snapshot: E10 is
# the very next lane and adds crm-followup cases, which would have broken this test for
# no behavioural reason. A floor keeps the real guarantee — PR2's cases are still here
# and nobody quietly deleted one — while letting later lanes add cases freely.
# The exact-composition claim is carried by NEW_IDS below, which stays true forever.
EXPECTED_COUNTS = [
    ("email-triage", 19, 8, 11),
    ("expense-categorization", 15, 6, 9),
    ("crm-followup", 12, 5, 7),
    ("reply-draft", 17, 7, 10),
]

# The 28 new case ids with their approved split (split assignment is an operator
# decision — this pins it against silent re-splitting).
NEW_IDS = {
    "email-triage": {
        "client-question-no-rush": "train",
        "agency-whitelabel-offer": "train",
        "invoice-error-client": "heldout",
        "dpa-signature-compliance": "heldout",
        "recruiter-fake-urgency": "heldout",
        "paid-workshop-invite": "heldout",
        "intro-no-ask": "heldout",
        "disk-warning-no-action": "heldout",
        "long-ramble-buried-incident": "heldout",
    },
    "expense-categorization": {
        "godaddy-domain-renewal": "train",
        "paypal-adobe-subscription": "heldout",
        "square-cafe-cryptic": "heldout",
        "uber-trip-cryptic": "heldout",
        "telenet-daypass": "heldout",
    },
    "crm-followup": {
        "briefing-devos": "train",
        "janssens-goal-deadline": "train",
        "active-client-stage": "heldout",
        "sofie-deal-stage": "heldout",
        "vitrine-pause-reason": "heldout",
    },
    "reply-draft": {
        "suivi-boutique-fr": "train",
        "multipart-request-en": "train",
        "refund-angry-nl": "train",
        "devis-exact-fr": "heldout",
        "long-thread-buried-ask-en": "heldout",
        "refund-demand-en": "heldout",
        "september-firm-day-en": "heldout",
        "may-delivery-date-en": "heldout",
        "weekday-call-nl": "heldout",
    },
}


def test_counts_and_ids():
    total = 0
    for agent, want_total, want_train, want_heldout in EXPECTED_COUNTS:
        cases = load(agent)
        ids = [c["id"] for c in cases]
        train, heldout = split_counts(cases)
        total += len(cases)
        check(f"{agent}: >= {want_total} cases", len(cases) >= want_total,
              f"got {len(cases)}")
        check(f"{agent}: split >= {want_train} train / >= {want_heldout} heldout",
              train >= want_train and heldout >= want_heldout,
              f"got {train}/{heldout}")
        check(f"{agent}: case ids unique", len(ids) == len(set(ids)))
        by_id = {c["id"]: c for c in cases}
        for cid, split in NEW_IDS[agent].items():
            c = by_id.get(cid)
            check(f"{agent}/{cid}: present in split {split!r}",
                  c is not None and c.get("split") == split,
                  "missing" if c is None else f"split {c.get('split')!r}")
    check("suite total is >= 63 (+28 over the 35 baseline)", total >= 63,
          f"got {total}")


def test_d2_expense_other_share():
    cases = load("expense-categorization")
    heldout = [c for c in cases if c["split"] == "heldout"]
    other = [c for c in heldout if c["expected"].get("category") == "other"]
    # CEILING, not equality: what D2 bought is that a degenerate all-'other'
    # answer can no longer score well. A later lane adding heldout cases must not
    # regress that share upward; adding NON-'other' cases (which lowers it) is fine.
    check("D2: heldout 'other' share stays <= 2/9 (~22%)",
          len(other) * 9 <= 2 * len(heldout),
          f"got {len(other)}/{len(heldout)}")
    for cid in NEW_IDS["expense-categorization"]:
        c = next(c for c in cases if c["id"] == cid)
        check(f"D2: {cid} is not 'other'", c["expected"]["category"] != "other")


def test_d3_crm_abstention_share():
    cases = load("crm-followup")
    heldout = [c for c in cases if c["split"] == "heldout"]
    # Abstention cases are exactly the ones scored by an ANY-of abstention
    # vocabulary (answer_contains_any) rather than grounded facts.
    abstention = [c for c in heldout if "answer_contains_any" in c["expected"]]
    # CEILING, not equality — same reasoning as D2. E10 (the next lane) adds
    # crm-followup rungs; those are non-abstention, so the share only falls further.
    check("D3: heldout abstention share stays <= 3/7 (~43%)",
          len(abstention) * 7 <= 3 * len(heldout),
          f"got {len(abstention)}/{len(heldout)}")
    for cid in NEW_IDS["crm-followup"]:
        c = next(c for c in cases if c["id"] == cid)
        check(f"D3: {cid} is non-abstention",
              "answer_contains_any" not in c["expected"])


def test_d3_crm_needles_derivable_from_mock():
    """A crm case whose expected answer is not in tools_mock data is broken."""
    mock = _load_module(ROOT / "evals" / "crm-followup" / "tools_mock.py",
                        "crm_mock_pr2_test")
    corpus = json.dumps({"crm": mock._CRM, "deals": mock._DEALS}).lower()
    for cid in NEW_IDS["crm-followup"]:
        c = next(c for c in load("crm-followup") if c["id"] == cid)
        for needle in c["expected"].get("answer_contains", []):
            check(f"D3: {cid} needle {needle!r} exists in mock data",
                  needle.lower() in corpus)


def test_d4_long_inputs():
    for agent, cid in [("email-triage", "long-ramble-buried-incident"),
                       ("reply-draft", "long-thread-buried-ask-en")]:
        c = next(c for c in load(agent) if c["id"] == cid)
        check(f"D4: {agent}/{cid} exceeds the old 294-char ceiling "
              f"({len(c['input'])} chars)", len(c["input"]) > 294)
        check(f"D4: {agent}/{cid} is genuinely long (> 1000 chars)",
              len(c["input"]) > 1000, f"{len(c['input'])} chars")


def test_d8_french_detects_as_fr():
    """ACCEPTANCE CRITERION (brief): French inputs must detect 'fr', not 'unknown'."""
    props = _load_module(ROOT / "evals" / "reply-draft" / "properties.py",
                         "props_pr2_test")
    for cid in ("suivi-boutique-fr", "devis-exact-fr"):
        c = next(c for c in load("reply-draft") if c["id"] == cid)
        got = props._lang(c["input"])
        check(f"D8: {cid} input detects as 'fr'", got == "fr", f"got {got!r}")


def test_probes_are_labelled():
    """Instrument-probes must carry a note flagging them, so a future reader
    triages checker-gap-vs-capability before reading the score as capability."""
    cases = {c["id"]: c for c in load("reply-draft")}
    for cid in ("may-delivery-date-en", "weekday-call-nl"):
        note = cases[cid].get("note", "")
        check(f"probe {cid} is labelled INSTRUMENT-PROBE", "INSTRUMENT-PROBE" in note)
    check("september-firm-day-en is labelled as caught-class regression probe",
          "CAUGHT-CLASS" in cases["september-firm-day-en"].get("note", ""))
    for cid in ("may-delivery-date-en", "weekday-call-nl", "september-firm-day-en"):
        check(f"probe {cid} asserts nothing (expected == {{}})",
              cases[cid]["expected"] == {})


def main() -> int:
    test_counts_and_ids()
    test_d2_expense_other_share()
    test_d3_crm_abstention_share()
    test_d3_crm_needles_derivable_from_mock()
    test_d4_long_inputs()
    test_d8_french_detects_as_fr()
    test_probes_are_labelled()
    print(f"\n{len(FAILED)} failed assertion(s)" + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
