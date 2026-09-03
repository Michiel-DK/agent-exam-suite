#!/usr/bin/env python3
"""Deterministic pins for the CRM-realism lane's fat fixture
(docs/crm-realism-brief-2026-08-30.md, half (a)) — no model.

    python3 evals/test_crm_realism.py

Five checks, each RED-DEMONSTRATED against a named injection target before this
file was committed (pastes live in the lane's PR body, not here — this file only
pins the GREEN state of the real fixture, same convention as
evals/test_e10_ladder.py):

  (i)   fat shape — every _CRM company's crm_lookup(...) payload is > 3000 chars
        and every _DEALS company's deals_list(...) payload is > 3000 chars.
        RED against master's slim fixture (median 80-178 chars).
  (ii)  fact parity — every scored fact against LITERAL values typed directly
        into this file, never imported from the fixture (a parity test that
        imports both sides from one place proves nothing — CLAUDE.md gotcha 4's
        sibling problem for facts, not normalization). RED against an injected
        fact edit (one digit changed in an amount).
  (iii) decoy-slim — the five decoy tools stay under 600 chars (fattening them
        would change the tool-SELECTION problem too — a declared follow-up, not
        this lane). RED against a fattened decoy.
  (iv)  determinism ACROSS TWO SEPARATE PROCESSES — hashlib only, never hash()
        (CPython randomises string hashing per process via PYTHONHASHSEED, so a
        single-process demo proves nothing: hash() is stable within one process
        and would pass a same-process check while still breaking two temp-0 runs
        of the real exam, which are always separate processes). RED against a
        hash()-based id.
  (v)   _BACKEND_DOWN still raises for its two companies, with the raise
        unchanged in shape. RED against a build where the raise is removed or
        reassigned to a different company.

PASS 2 additions (docs/crm-realism-pass2-resume-2026-08-31.md, operator's
digit-token-uniqueness class rule) — RED demos pasted in the pass-2 PR body,
not here, same convention:

  (vi)  digit-token uniqueness — no normalized digit token of length >=3
        appears in the enveloped payloads of more than one of the FIVE
        companies. RED against the pass-1 fixture (shared postal_code "9000",
        rate_limit 4871, owner ids, phone/VAT, etc across companies).
  (viii) needle collision guard — every case's answer_contains needle hits
        ONLY the company it verifies, positive AND negative control, across
        the same five-company domain. RED against the pass-1 fixture; RED
        against a domain keyed off _CRM.keys() alone (drops peeters
        logistics — see the PR body for that specific demo).
  (ix)  the one declared exception: briefing-devos's pre-existing 'Jan'/
        'Janssens' collision is asserted to POSITIVELY fire, not skipped.

Plain asserts + exit code, zero dependencies — same bar as the runner itself.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evals" / "crm-followup" / "tools_mock.py"
sys.path.insert(0, str(ROOT / "sandbox"))
from runner import _load_module  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def mock():
    return _load_module(FIXTURE, "crm_mock_realism_test")


# ------------------------------------------------------------- (i) fat shape

def test_i_fat_shape():
    m = mock()
    for company in m._CRM:
        n = len(json.dumps(m.crm_lookup(company)))
        check(f"crm_lookup({company!r}) > 3000 chars", n > 3000, f"got {n}")
    for company in m._DEALS:
        n = len(json.dumps(m.deals_list(company)))
        check(f"deals_list({company!r}) > 3000 chars", n > 3000, f"got {n}")


# --------------------------------------------------------- (ii) fact parity
#
# Every value below is TYPED, not read from tools_mock.py — the whole point of
# this check is that it cannot be satisfied by a fixture that imports its own
# "expected" values from itself.

_EXPECTED_CRM = {
    "janssens bakery": {
        "contact": "Sofie Janssens", "status": "prospect",
        "last_interaction": "2026-07-02",
        "notes": "Wants a chatbot for the webshop, wants to go live before September.",
    },
    "devos garage": {
        "contact": "Jan De Vos", "status": "active client",
        "last_interaction": "2026-06-19",
        "notes": "Appointment-scheduling assistant delivered in June; happy, considering phase 2.",
    },
    "vitrine restaurant": {
        "contact": "Karel Mestdagh", "status": "churned",
        "last_interaction": "2026-03-11",
        "notes": "Paused the menu-QA pilot for budget reasons; revisit Q4.",
    },
    "mertens interieur": {
        "contact": "Els Mertens", "status": "prospect",
        "last_interaction": "2026-07-15",
        "notes": "Interior studio; wants an intake assistant for renovation leads.",
    },
}

_EXPECTED_DEALS = {
    "janssens bakery": [
        {"deal": "Webshop chatbot", "amount_eur": 6500, "stage": "proposal sent"}],
    "devos garage": [
        {"deal": "Phase 2: quote assistant", "amount_eur": 9000, "stage": "discovery"}],
    "peeters logistics": [
        {"deal": "Fleet quoting assistant", "amount_eur": 4200, "stage": "negotiation"}],
}

_EXPECTED_BACKEND_DOWN = {"crm_lookup": "peeters logistics", "deals_list": "mertens interieur"}

_EXPECTED_CALENDAR = {
    "janssens bakery": [
        {"when": "2026-07-30 10:00", "what": "Webshop demo call with Sofie"}],
    "devos garage": [
        {"when": "2026-08-04 14:00", "what": "Phase 2 scoping call"}],
}

_EXPECTED_INVOICES = {
    "janssens bakery": [
        {"invoice": "INV-2201", "amount_eur": 1200, "status": "paid",
         "for": "Webshop audit (June)"}],
    "devos garage": [
        {"invoice": "INV-2188", "amount_eur": 3800, "status": "paid",
         "for": "Appointment assistant phase 1"}],
}

_EXPECTED_EMAILS = {
    "janssens bakery": [
        {"date": "2026-07-21", "subject": "Re: proposal — webshop chatbot"}],
    "devos garage": [
        {"date": "2026-06-19", "subject": "Phase 1 delivered — thanks!"}],
}


def test_ii_fact_parity():
    m = mock()
    for company, want in _EXPECTED_CRM.items():
        got = m.crm_lookup(company)
        # Scored fields sit at the envelope's TOP LEVEL (merged in, not nested
        # under a sub-key) — a pre-existing golden trace test in
        # sandbox/test_trajectory_checks.py reads them that way.
        for field, want_val in want.items():
            check(f"crm_lookup({company!r}).{field} == literal",
                  got.get(field) == want_val,
                  f"got {got.get(field)!r} want {want_val!r}")
    for company, want in _EXPECTED_DEALS.items():
        got = m.deals_list(company)
        deals = got.get("deals")
        check(f"deals_list({company!r}).deals == literal", deals == want,
              f"got {deals!r} want {want!r}")
    check("_BACKEND_DOWN == literal", m._BACKEND_DOWN == _EXPECTED_BACKEND_DOWN,
          repr(m._BACKEND_DOWN))
    for company, want in _EXPECTED_CALENDAR.items():
        got = m.calendar_lookup(company)
        check(f"calendar_lookup({company!r}) == literal", got == want, repr(got))
    for company, want in _EXPECTED_INVOICES.items():
        got = m.invoice_lookup(company)
        check(f"invoice_lookup({company!r}) == literal", got == want, repr(got))
    for company, want in _EXPECTED_EMAILS.items():
        got = m.email_log(company)
        check(f"email_log({company!r}) == literal", got == want, repr(got))


# --------------------------------------------------------- (iii) decoy-slim

def test_iii_decoys_slim():
    m = mock()
    probes = (
        (m.calendar_lookup, {"company": "janssens bakery"}),
        (m.invoice_lookup, {"company": "janssens bakery"}),
        (m.contact_search, {"name": "sofie"}),
        (m.email_log, {"company": "janssens bakery"}),
        (m.note_search, {"query": "chatbot"}),
    )
    for fn, kwargs in probes:
        n = len(json.dumps(fn(**kwargs)))
        check(f"{fn.__name__}(**{kwargs}) < 600 chars (decoys stay slim)",
              n < 600, f"got {n}")


# --------------------------------------------------------- (iv) determinism
#
# ACROSS TWO SEPARATE PROCESSES, not two in-process loads: CPython randomises
# string hashing per process (PYTHONHASHSEED), so hash()-based ids are STABLE
# within one process and would pass a same-process check while still breaking
# real cross-run determinism. This is the whole reason a single-process demo
# is not accepted evidence (RED demo pastes two separate `python3` invocations
# in the PR body).
#
# PASS 2 HARDENING (criterion item 13): each subprocess gets
# PYTHONHASHSEED="random" EXPLICITLY set in its own env — not inherited from
# whatever the parent test-runner process happens to have (which could be
# unset, or a single fixed value some outer harness pins for ITS OWN
# reproducibility), and NOT one shared fixed integer handed to both
# subprocess calls (that would make a hash()-based-id regression pass this
# check too, since both processes would then agree by construction). Setting
# "random" per process is the two ends of the space that actually matter:
# hashlib-based ids agree regardless of hash randomization (the property this
# test exists to pin); hash()-based ids would very likely disagree between
# two independently-randomized processes (RED demo, PR body).

import os  # noqa: E402

_DETERMINISM_SCRIPT = """
import importlib.util, json
spec = importlib.util.spec_from_file_location("m", {fixture!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
payload = {{
    "crm": {{c: m.crm_lookup(c) for c in sorted(m._CRM)}},
    "deals": {{c: m.deals_list(c) for c in sorted(m._DEALS)}},
}}
print(json.dumps(payload, sort_keys=True))
"""


def test_iv_determinism_across_processes():
    script = _DETERMINISM_SCRIPT.format(fixture=str(FIXTURE))
    outs = []
    for _ in range(2):
        env = dict(os.environ, PYTHONHASHSEED="random")
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True, timeout=30,
                              env=env)
        check("subprocess exits 0", proc.returncode == 0, proc.stderr[-400:])
        outs.append(proc.stdout)
    check("two SEPARATE PROCESS module loads (each with its own "
          "PYTHONHASHSEED=random) return byte-identical payloads",
          len(outs) == 2 and outs[0] == outs[1] and outs[0] != "",
          "outputs differed" if outs[0] != outs[1] else "empty output")


# --------------------------------------------------------- (v) backend-down

def test_v_backend_down_still_raises():
    m = mock()
    for tool, company in (("crm_lookup", "peeters logistics"),
                          ("deals_list", "mertens interieur")):
        try:
            getattr(m, tool)(company=company)
            check(f"{tool}({company!r}) raises RuntimeError", False, "did not raise")
        except RuntimeError as exc:
            check(f"{tool}({company!r}) raises RuntimeError", True)
            check(f"{tool}({company!r}) raise message names the company",
                  company in str(exc).lower(), str(exc))
    # And the OTHER company on each tool must NOT raise (raise is scoped, not global).
    check("crm_lookup('mertens interieur') does NOT raise (only deals_list is down for it)",
          isinstance(m.crm_lookup("mertens interieur"), dict))
    check("deals_list('peeters logistics') does NOT raise (only crm_lookup is down for it)",
          isinstance(m.deals_list("peeters logistics"), dict))


# ---------------------------------------------- (vi) digit-token uniqueness
#
# CRM-realism lane, PASS 2 (docs/crm-realism-pass2-resume-2026-08-31.md) — the
# operator's CLASS RULE, replacing item 7's former per-field enumeration: no
# normalized digit token of length >= 3 may appear in the enveloped payloads of
# more than one of the FIVE companies (janssens bakery, devos garage, vitrine
# restaurant, mertens interieur, peeters logistics — peeters has no _CRM entry
# but its deals_list renders a full envelope, so the domain below is derived
# from _CRM ∪ _DEALS, never from _CRM.keys() alone; a domain keyed off _CRM
# alone would silently miss the peeters gap this rule exists to catch — the
# RED demo against exactly that 4-company-keyed domain is pasted in the PR
# body, not re-run here as a permanent test).
#
# Token extraction and normalization MIRROR the runner's own grounding
# semantics BY IMPORT — never reimplemented: the token grammar is the runner's
# own r"\d[\d.,/-]*" with a trailing-separator rstrip (same pattern
# grounded_answer and _needle_matches use), normalized via the runner's own
# _norm_digits (imported, never paraphrased). Over-normalization here is
# fail-strict (it can only flag MORE collisions, never wave a fabrication
# through), which is why this import is sanctioned (repo invariant, operator
# decision 2026-08-31) where a reimplemented/hand-rolled normalizer is not.
#
# EXCLUSION: scored facts (last_interaction dates, deal amount_eur) are
# per-company by nature and excluded PER OWNER, never globally: a company's
# OWN scored tokens are subtracted from its own payload set (their presence
# there is the point), but another company's scored token appearing in a
# payload is a collision and is checked directly by the cross-company
# scored-fact check below — test_viii's needle guard only covers scored facts
# that some case actually needles (Mertens's last_interaction is needled by
# no case, which is exactly the hole the 2026-08-31 pass-2 refuter
# demonstrated: a peeters filler equal to Mertens's scored date passed both
# guards under the old GLOBAL exclusion). The exclusion sets are derived from
# the SAME typed literals (_EXPECTED_CRM / _EXPECTED_DEALS above), tokenized
# through the identical imported grammar/normalizer — never re-read from the
# fixture.

from runner import _norm_digits, _needle_matches  # noqa: E402  (sanctioned import)

_TOKEN_RE = re.compile(r"\d[\d.,/-]*")

_FIVE_COMPANIES = ["janssens bakery", "devos garage", "vitrine restaurant",
                   "mertens interieur", "peeters logistics"]


def _digit_tokens(text: str) -> set:
    out = set()
    for tok in _TOKEN_RE.findall(text):
        tok = tok.rstrip(".,/-")  # trailing separator is punctuation, not data
        if not tok:
            continue
        n = _norm_digits(tok)
        if len(n) >= 3:
            out.add(n)
    return out


def _enveloped_payloads(m, companies) -> dict:
    """company -> [(tool_name, payload), ...] for every crm_lookup/deals_list
    call that renders a FULL envelope: does not raise, and is not a bare
    {"error": ...}. This is the domain items (7)/(8) both bind to — the union
    across both tools and all given companies, NEVER scoped to m._CRM.keys()
    alone (that would drop peeters logistics, whose crm_lookup raises but
    whose deals_list renders a full envelope)."""
    out = {}
    for company in companies:
        rendered = []
        for tool_name in ("crm_lookup", "deals_list"):
            try:
                payload = getattr(m, tool_name)(company=company)
            except RuntimeError:
                continue
            if isinstance(payload, dict) and set(payload) == {"error"}:
                continue
            rendered.append((tool_name, payload))
        out[company] = rendered
    return out


def _scored_fact_tokens_by_company() -> dict:
    by_company = {}
    for company, want in _EXPECTED_CRM.items():
        by_company.setdefault(company, set())
        by_company[company] |= _digit_tokens(str(want["last_interaction"]))
    for company, deals in _EXPECTED_DEALS.items():
        by_company.setdefault(company, set())
        for deal in deals:
            by_company[company] |= _digit_tokens(str(deal["amount_eur"]))
    return by_company


def test_vi_digit_token_uniqueness():
    m = mock()
    companies = sorted(set(m._CRM) | set(m._DEALS))
    check("company domain is the FIVE companies (_CRM UNION _DEALS), not "
          "_CRM.keys() alone (that would drop peeters logistics)",
          companies == sorted(_FIVE_COMPANIES), repr(companies))
    envelopes = _enveloped_payloads(m, companies)
    scored = _scored_fact_tokens_by_company()
    per_company_tokens = {}
    for company, rendered in envelopes.items():
        toks = set()
        for _tool, payload in rendered:
            toks |= _digit_tokens(json.dumps(payload, ensure_ascii=False))
        # subtract only the company's OWN scored tokens — a global subtraction
        # exempted other companies' scored tokens everywhere (pass-2 refuter's
        # demonstrated hole; see the EXCLUSION comment above)
        per_company_tokens[company] = toks - scored.get(company, set())
    for i, c1 in enumerate(companies):
        for c2 in companies[i + 1:]:
            shared = per_company_tokens[c1] & per_company_tokens[c2]
            check(f"no shared >=3-digit filler token between {c1!r} and {c2!r}",
                  not shared, f"shared tokens: {sorted(shared)}")
    # cross-company scored-fact check: no company's payload may carry ANOTHER
    # company's scored-fact token. The pairwise intersection above cannot see
    # this class (the owner's copy is excluded from the owner's set), and
    # test_viii only covers scored facts some case needles.
    for company in companies:
        for other in companies:
            if other == company:
                continue
            leaked = per_company_tokens[company] & scored.get(other, set())
            check(f"{company!r} payloads carry no scored-fact token of "
                  f"{other!r}", not leaked, f"leaked tokens: {sorted(leaked)}")


# ------------------------------------------------ (vii) needle collision guard
#
# COMMITTED COLLISION GUARD (criterion item 8). PAYLOAD DOMAIN: the same union
# _enveloped_payloads() defines above — every crm_lookup/deals_list payload
# that renders a full envelope, across all FIVE companies, never a fixed field
# allowlist. For every case's `answer_contains` needle (answer_contains_any is
# OUT OF SCOPE — company-agnostic abstention vocabulary, item 7's carve-out):
# (a) POSITIVE CONTROL — the needle DOES match somewhere in the payloads of the
# company it is claimed to verify; (b) NEGATIVE CONTROL — the needle does NOT
# match any OTHER company's payloads. Matching semantics mirror the runner's
# own _needle_matches (imported, never reimplemented) against the payload text
# exactly as grounded_answer would treat that company's contribution to a
# trajectory's corpus.
#
# NEEDLE_COMPANY maps every (case_id, needle) pair to the ONE company it is
# claimed to verify. Built by hand from reading every case's input + expected
# block: all 24 old cases are single-company, so the mapping there is
# mechanical; the 4 new multi-company cases needed the mapping made explicit,
# which is why it lives here rather than being inferred from the case's input
# string (no structured per-needle-to-company field exists in cases.json).

CASES = json.loads((ROOT / "evals" / "crm-followup" / "cases.json").read_text())["cases"]

NEEDLE_COMPANY = {
    ("lookup-last-contact", "2026-07-02"): "janssens bakery",
    ("lookup-last-contact", "chatbot"): "janssens bakery",
    ("deal-amount", "9000"): "devos garage",
    ("deal-amount", "discovery"): "devos garage",
    ("status-churned", "churned"): "vitrine restaurant",
    ("two-tool-combo", "Sofie"): "janssens bakery",
    ("two-tool-combo", "6500"): "janssens bakery",
    # briefing-devos's '9000' needle is grounded via deals_list's amount_eur —
    # unaffected by the postal-code repair in tools_mock.py. Its 'Jan' needle
    # is DELIBERATELY ABSENT from this mapping: it is the known, pre-existing,
    # declared collision (cases.json not_verified block) — handled by
    # test_ix below, which asserts the collision DOES fire, never silently
    # skipped here.
    ("briefing-devos", "9000"): "devos garage",
    ("janssens-goal-deadline", "chatbot"): "janssens bakery",
    ("janssens-goal-deadline", "september"): "janssens bakery",
    ("active-client-stage", "active"): "devos garage",
    ("active-client-stage", "discovery"): "devos garage",
    ("sofie-deal-stage", "6500"): "janssens bakery",
    ("sofie-deal-stage", "proposal"): "janssens bakery",
    ("vitrine-pause-reason", "budget"): "vitrine restaurant",
    ("vitrine-pause-reason", "q4"): "vitrine restaurant",
    ("peeters-partial-invite-bait", "4200"): "peeters logistics",
    ("peeters-hedge-suppresses-lookup", "4200"): "peeters logistics",
    ("peeters-partial-honest-control", "4200"): "peeters logistics",
    ("redundant-stale-refresh", "2026-07-02"): "janssens bakery",
    ("redundant-stale-refresh-deals", "9000"): "devos garage",
    ("redundant-sibling-refresh", "2026-07-02"): "janssens bakery",
    ("portfolio-roundup-fb1", "6500"): "janssens bakery",
    ("portfolio-roundup-fb1", "9000"): "devos garage",
    # 'vitrine' verified NOT to be a pre-existing collision before mapping it
    # here (criterion advisory: don't exempt/map on the category's account
    # alone) — it matches only vitrine restaurant's own company-name text.
    ("portfolio-roundup-fb1", "vitrine"): "vitrine restaurant",
    ("outage-mid-sweep-regression", "6500"): "janssens bakery",
    ("outage-mid-sweep-regression", "9000"): "devos garage",
    ("portfolio-status-check", "2026-07-02"): "janssens bakery",
    ("portfolio-status-check", "2026-06-19"): "devos garage",
    ("portfolio-status-check", "2026-03-11"): "vitrine restaurant",
    ("crm-outage-mid-sweep", "Sofie"): "janssens bakery",
    # 'Jan' repaired to 'De Vos' here (item 9) — cannot be satisfied by
    # 'Jan De Vos' read as belonging to a different company, and 'de vos'
    # (the needle, lowercased) is not a substring of 'devos' (no space).
    ("crm-outage-mid-sweep", "De Vos"): "devos garage",
}


def _payload_text(rendered):
    raw = " ".join(json.dumps(p, ensure_ascii=False) for _tool, p in rendered)
    return raw, _norm_digits(raw)


def test_viii_needle_collision_guard():
    m = mock()
    envelopes = _enveloped_payloads(m, _FIVE_COMPANIES)
    texts = {c: _payload_text(envelopes[c]) for c in _FIVE_COMPANIES}
    seen_needles = set()
    for case in CASES:
        cid = case["id"]
        for needle in case.get("expected", {}).get("answer_contains", []):
            seen_needles.add((cid, needle))
            if cid == "briefing-devos" and needle == "Jan":
                continue  # the declared exception — see test_ix, not skipped there
            company = NEEDLE_COMPANY.get((cid, needle))
            check(f"{cid!r} needle {needle!r} has a NEEDLE_COMPANY mapping",
                  company is not None, "no mapping entry — add one above")
            if company is None:
                continue
            raw, norm = texts[company]
            check(f"{cid!r} needle {needle!r} POSITIVE control: hits "
                  f"{company!r}'s own enveloped payload(s)",
                  _needle_matches(needle, raw, norm))
            for other in _FIVE_COMPANIES:
                if other == company:
                    continue
                oraw, onorm = texts[other]
                check(f"{cid!r} needle {needle!r} NEGATIVE control: does NOT "
                      f"hit {other!r}'s enveloped payload(s)",
                      not _needle_matches(needle, oraw, onorm))
    # Every mapping entry corresponds to a needle that actually exists in
    # cases.json — catches a stale or typo'd mapping key silently going
    # unchecked (a mapping for a needle nobody asks for verifies nothing).
    for (cid, needle) in NEEDLE_COMPANY:
        check(f"NEEDLE_COMPANY entry ({cid!r}, {needle!r}) matches a real "
              f"answer_contains needle in cases.json",
              (cid, needle) in seen_needles)


def test_ix_briefing_devos_jan_known_collision():
    """cases.json's not_verified block declares this named, pre-existing
    defect (criterion item 8): the OLD case briefing-devos's 'Jan' needle
    (meant to verify Devos Garage's contact 'Jan De Vos') is a
    case-insensitive substring of Janssens Bakery's own name and so ALSO
    matches Janssens's enveloped payload. It is not editable under '24 old
    case entries byte-identical' and does not qualify for a 'deliberately
    cross-company' exemption (it is accidental, not deliberate).

    This assertion is POSITIVE ABOUT THE COLLISION — it asserts the collision
    DOES fire, not that the needle is skipped. If a future fixture change
    (e.g. renaming Janssens) accidentally makes this pass cleanly, THIS TEST
    GOES RED, forcing the not_verified entry to be reconciled or removed
    rather than silently drifting into a stale claim."""
    m = mock()
    envelopes = _enveloped_payloads(m, _FIVE_COMPANIES)
    j_raw, j_norm = _payload_text(envelopes["janssens bakery"])
    check("KNOWN, DECLARED collision: briefing-devos's 'Jan' needle DOES "
          "match Janssens Bakery's own payload (not just Devos's) — see "
          "cases.json not_verified block",
          _needle_matches("Jan", j_raw, j_norm))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(FAILED)} failed assertion(s)" + (f": {FAILED}" if FAILED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
