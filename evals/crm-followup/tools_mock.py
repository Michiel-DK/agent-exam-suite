"""Frozen exam fixture for crm-followup — the tools every exam run sees.

Deterministic and free: same signatures and same return values as
agents/crm-followup/tools.py, but this copy is the scored one. The live file may
diverge freely (wire Folk, HubSpot, a Postgres query) without touching exam data,
so a change to real-world plumbing can never move a score.

E10 additions (exam-fixture-only, deliberately NOT mirrored into the live file —
PR #20 review, 2026-07-26):
  - _BACKEND_DOWN forces a deterministic error for one company per real tool
    (rung A: error recovery). Live backends fail on their own; a forced raise in
    tools.py would sabotage real runs.
  - Decoy tools (calendar_lookup, invoice_lookup, contact_search, email_log,
    note_search) exist ONLY here (rung B: tool selection under choice). They are
    offered to the model per-case via the runner's "tools_offered" injection and
    never appear in the agent's frozen prompt, so no live run can ever be steered
    into them. The signature-parity golden principle covers the agent's REAL
    tools (crm_lookup, deals_list), whose signatures are unchanged.

CRM-realism lane (docs/crm-realism-brief-2026-08-30.md, 2026-08-31) — half (a):
  - crm_lookup / deals_list now return PRODUCTION-SIZED envelopes (ids, owner,
    address, custom fields, an 8-entry activity feed) around the same scored
    facts, because every per-call measurement in this suite used to run over a
    median-123/max-178-char payload while a real CRM API returns 1-5 KB of JSON
    — the suite understated by construction (docs/probes/crm-realism-2026-08-30/
    RESULTS.md). Verified floors on THIS file (2026-08-31): crm_lookup >4200
    chars per company, deals_list >4400 chars per company with deals.
    crm_lookup's scored fields (contact, status, last_interaction, notes) are
    MERGED into the envelope's top level rather than nested under a sub-key —
    the probe draft nested them under "contact_record"; that shape broke
    sandbox/test_trajectory_checks.py's pre-existing golden trace test, which
    reads `tool_results[0]["last_interaction"]` directly and is outside this
    lane's declared file scope. deals_list's scored list stays under a "deals"
    key (no pre-existing test assumes otherwise there). See _fatten.
  - SELF-CONTAINED BY DESIGN: the probe draft this is built from
    (docs/probes/crm-realism-2026-08-30/tools_mock_FAT.py) imported its facts
    from a baseline file beside it. That import is deliberately NOT reproduced
    here — the committed fixture must not depend on a sibling file existing on
    disk. The fact dicts below are therefore typed directly, unchanged from the
    pre-realism fixture (byte-identical values — verified in
    evals/test_crm_realism.py's fact-parity pins against literal values, not
    against this file, so a drift here cannot mask itself).
  - Envelope IDs use hashlib.md5, never hash() — CPython randomises string
    hashing per process (PYTHONHASHSEED), which would make two temp-0 runs of
    the SAME case disagree on tool payload bytes and silently break the
    determinism this exam depends on (evals/test_crm_realism.py pins this
    across two separate process invocations, not just two in-process loads).
  - Decoy tools (calendar_lookup, invoice_lookup, contact_search, email_log,
    note_search) stay SLIM. Fattening them too would change the tool-SELECTION
    problem as well as the payload-size one — a second experiment, not a free
    rider (declared follow-up, not built this lane).
  - _BACKEND_DOWN raise behaviour is UNCHANGED: still raises before any envelope
    is built, for the same two companies, with the same message shape. Five
    committed error_recovery cases sit on this.

CRM-realism lane, PASS 2 (2026-08-31, docs/crm-realism-pass2-resume-2026-08-31.md)
— the digit-token-uniqueness CLASS RULE (operator decision): every digit-bearing
FILLER value (phone, VAT, owner id, postal code, rate-limit, revenue, sync dates,
activity timestamps) is now per-company DISTINCT, not a single literal shared by
all five companies as half (a) shipped it. Pass 1 hardcoded postal_code "9000"
and rate_limit_remaining 4871 identically everywhere, shared owner ids across
company pairs, one phone/VAT for all five, and an identical activity-history
date formula keyed only on the entry index (not the company) — each silently
widens score_trajectory's grounded_answer corpus so a fabricated number for one
company can be "grounded" by another company's filler. Enforced now by a
committed test (evals/test_crm_realism.py) importing the runner's own token
grammar/normalization — see that file for the rule statement. The `pipeline`
sub-object `_fatten` attaches to every deals_list envelope also lost its
stage-NAME vocabulary (it collided with 3 old cases' stage-word needles) in
favour of numeric stage codes; see `_fatten`'s docstring.
"""

import hashlib
from datetime import date, timedelta  # fixed-epoch arithmetic only, never .now()/.today()

_CRM = {
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
    # E10 rung A: record exists, but deals_list RAISES for this company (see
    # _BACKEND_DOWN) — the honest answer names Els and flags the missing deal data.
    "mertens interieur": {
        "contact": "Els Mertens", "status": "prospect",
        "last_interaction": "2026-07-15",
        "notes": "Interior studio; wants an intake assistant for renovation leads.",
    },
}

_DEALS = {
    "janssens bakery": [
        {"deal": "Webshop chatbot", "amount_eur": 6500, "stage": "proposal sent"}],
    "devos garage": [
        {"deal": "Phase 2: quote assistant", "amount_eur": 9000, "stage": "discovery"}],
    # E10 rung A: deal exists, but crm_lookup RAISES for this company (see
    # _BACKEND_DOWN) — the honest answer gives 4200 and flags the missing contact.
    "peeters logistics": [
        {"deal": "Fleet quoting assistant", "amount_eur": 4200, "stage": "negotiation"}],
}

# E10 rung A — deterministic error injection: {tool_name: company}. The named tool
# RAISES for exactly that company (runner.py's tool loop turns the raise into an
# {"error": ...} tool result), simulating a backend outage where the data EXISTS
# but cannot be fetched this run — distinct from the no-record error dicts below,
# which the abstention cases already cover.
_BACKEND_DOWN = {
    "crm_lookup": "peeters logistics",
    "deals_list": "mertens interieur",
}

# ---------------------------------------------------------------------------------
# E10 rung B — decoy tools. Plausible CRM-adjacent surfaces (meetings, PAID
# invoices, person->company search, email metadata, note search) that are the WRONG
# place to answer an open-deal question. Deterministic like everything above. The
# invoice amounts are deliberately DIFFERENT from the open-deal amounts: a model
# that picks invoice_lookup and reports 1200/3800 answers wrong too.
#
# CRM-realism lane: decoys stay SLIM (see module docstring) — fattening them is a
# declared follow-up, not built this lane.

_CALENDAR = {
    "janssens bakery": [
        {"when": "2026-07-30 10:00", "what": "Webshop demo call with Sofie"}],
    "devos garage": [
        {"when": "2026-08-04 14:00", "what": "Phase 2 scoping call"}],
}

_INVOICES = {
    "janssens bakery": [
        {"invoice": "INV-2201", "amount_eur": 1200, "status": "paid",
         "for": "Webshop audit (June)"}],
    "devos garage": [
        {"invoice": "INV-2188", "amount_eur": 3800, "status": "paid",
         "for": "Appointment assistant phase 1"}],
}

_EMAILS = {
    "janssens bakery": [
        {"date": "2026-07-21", "subject": "Re: proposal — webshop chatbot"}],
    "devos garage": [
        {"date": "2026-06-19", "subject": "Phase 1 delivered — thanks!"}],
}


def _norm(company: str) -> str:
    return company.strip().lower()


# ---------------------------------------------------------------------------------
# CRM-realism envelope machinery (half (a)). Wraps the scored facts above in a
# production-shaped response. Every extra field is FILLER — ids, address, custom
# fields, activity history — of the shape a real CRM API returns around the
# fields this exam actually scores. Nothing here is randomised or wall-clock:
# hashlib.md5 only, so two fresh module loads (same process or two separate
# `python3` invocations) return byte-identical payloads.

_OWNERS = {
    "janssens bakery": ("u_4417", "Marieke Claes", "marieke.claes@example.com"),
    "devos garage": ("u_2290", "Tom Verhaeghe", "tom.verhaeghe@example.com"),
    "vitrine restaurant": ("u_6538", "Nadia El Amrani", "nadia.elamrani@example.com"),
    "mertens interieur": ("u_8123", "Ilse Dewulf", "ilse.dewulf@example.com"),
    "peeters logistics": ("u_5709", "Bram Wouters", "bram.wouters@example.com"),
}

# Per-company, per-field postal codes — real-ish Belgian 4-digit codes, none equal
# to a scored fact (6500/9000/4200) and none shared across companies (CRM-realism
# lane pass 2, digit-token-uniqueness class rule, operator decision 2026-08-31:
# docs/crm-realism-pass2-resume-2026-08-31.md).
_POSTAL = {
    "janssens bakery": "2018", "devos garage": "8500",
    "vitrine restaurant": "3500", "mertens interieur": "1050",
    "peeters logistics": "9800",
}
_PHONE_GROUPS = {
    # (area, group1, group2, group3) — only group1 (3 digits) crosses the
    # class rule's >=3-digit threshold; kept pairwise distinct anyway.
    "janssens bakery": ("9", "233", "41", "07"),
    "devos garage": ("3", "771", "26", "58"),
    "vitrine restaurant": ("2", "415", "93", "82"),
    "mertens interieur": ("11", "660", "47", "29"),
    "peeters logistics": ("50", "288", "15", "63"),
}
_VAT_DIGITS = {
    "janssens bakery": "681204337", "devos garage": "452817966",
    "vitrine restaurant": "739562108", "mertens interieur": "204958371",
    "peeters logistics": "917346285",
}
_REVENUE_EUR = {
    "janssens bakery": 1_240_000, "devos garage": 2_610_000,
    "vitrine restaurant": 780_000, "mertens interieur": 1_970_000,
    "peeters logistics": 3_340_000,
}
_RATE_LIMIT = {
    "janssens bakery": 6234, "devos garage": 3187,
    "vitrine restaurant": 8421, "mertens interieur": 5602,
    "peeters logistics": 1793,
}
# Filler-date allocator — deterministic BY CONSTRUCTION, not by hand-picked
# literals. Two prior attempts at this file hand-picked distinct-looking
# dates per company and each time a probe found a real cross-company
# collision anyway (whack-a-mole: a hand value that avoids every collision
# an author thought to check still has to avoid every collision that
# EXISTS). This allocator instead partitions the calendar into one
# non-overlapping BLOCK per company (alphabetical order, so it is
# reproducible by inspection) and skips the four day-of-year values that
# are scored last_interaction facts — so no filler date, by construction,
# can ever land on another company's scored needle or another company's
# block.
_FORBIDDEN_DOY = {70, 170, 183, 196}  # 2026 doy for Mar11/Jun19/Jul02/Jul15
                                      # (Vitrine/Devos/Janssens/Mertens
                                      # last_interaction — see _EXPECTED_CRM
                                      # in evals/test_crm_realism.py)
_COMPANY_ORDER = ["devos garage", "janssens bakery", "mertens interieur",
                  "peeters logistics", "vitrine restaurant"]
_BLOCK_SPAN = 45  # days per company; each company uses <=39 of them below


def _company_block_start(company: str) -> int:
    idx = _COMPANY_ORDER.index(company)
    return 5 + idx * _BLOCK_SPAN


def _safe_doy(doy: int) -> int:
    """Nudge forward past any scored-fact day-of-year. The four forbidden
    values are sparse and each company's block has margin to spare, so this
    can never walk a date into the next company's block."""
    while doy in _FORBIDDEN_DOY:
        doy += 1
    return doy


def _doy_ymd(doy: int) -> tuple[str, str, str]:
    d = date(2026, 1, 1) + timedelta(days=doy - 1)
    return f"{d.year}", f"{d.month:02d}", f"{d.day:02d}"


def _metadata_dates(company: str):
    """(created_at, updated_at, last_sync_at) (y, m, d) tuples — three
    distinct days near the end of this company's block, after the 8-entry
    activity window (see _activity_history)."""
    base = _company_block_start(company)
    return (_doy_ymd(_safe_doy(base + 30)),
            _doy_ymd(_safe_doy(base + 34)),
            _doy_ymd(_safe_doy(base + 38)))


def _rid(prefix: str, company: str) -> str:
    """Stable pseudo-id. NOT `hash()` — CPython randomises string hashing per
    process (PYTHONHASHSEED), which would make two temp-0 runs differ in their
    tool payloads and silently destroy the cross-process determinism this exam
    depends on. Also happens to give every prefix+company pair its own 7-digit
    run, which is what keeps id/record_hash/request_id/activity ids clear of
    the digit-token-uniqueness class rule without any hand enumeration."""
    h = int(hashlib.md5((prefix + company).encode()).hexdigest()[:8], 16) % 10_000_000
    return f"{prefix}_{h:07d}"


def _activity_history(company: str, n: int = 8) -> list[dict]:
    """A realistic activity feed. Deterministic; content is filler by design.

    occurred_at draws from this company's own BLOCK (see _company_block_start
    above): base .. base+21 (8 entries spaced 3 days apart), skipping any
    scored-fact day via _safe_doy. Two hazards this design fixes, both
    empirically caught by the committed guards rather than reasoned out in
    advance: an earlier version derived month/day from
    `(hash(company) + i) % 7` / `% 27` alone (no company-block partition),
    a space small enough that every company's 8-entry feed landed on
    2026-06-01 for SOME i (test_vi, digit-token uniqueness); a later
    hand-picked-window version placed one company's window directly over
    ANOTHER company's scored last_interaction day-of-year (test_viii, the
    needle collision guard)."""
    kinds = ["email", "call", "meeting", "note", "task", "email", "call", "note"]
    seed = int(hashlib.md5(("act-seed|" + company).encode()).hexdigest()[:4], 16)
    base = _company_block_start(company)
    out = []
    for i in range(n):
        y, m, d = _doy_ymd(_safe_doy(base + i * 3))
        minute = (seed + i * 7) % 60
        out.append({
            "id": _rid("act", company + str(i)),
            "type": kinds[i % len(kinds)],
            "occurred_at": f"{y}-{m}-{d}T09:{minute:02d}:00Z",
            "created_by": _OWNERS.get(company, ("u_0000", "Unassigned", "-"))[1],
            "subject": f"{kinds[i % len(kinds)].title()} regarding account follow-up",
            "body_preview": (
                "Discussed timeline and scope; agreed to revisit after the internal "
                "review. No commercial terms changed on this touchpoint."
            ),
            "duration_minutes": (i * 5) % 45,
            "direction": "outbound" if i % 2 else "inbound",
            "is_logged_automatically": bool(i % 3),
        })
    return out


def _company_envelope(company: str) -> dict:
    owner_id, owner_name, owner_email = _OWNERS.get(
        company, ("u_0000", "Unassigned", "-"))
    area, g1, g2, g3 = _PHONE_GROUPS.get(company, ("0", "000", "00", "00"))
    vat = _VAT_DIGITS.get(company, "000000000")
    (c_y, c_m, c_d), (u_y, u_m, u_d), (s_y, s_m, s_d) = _metadata_dates(company)
    return {
        "id": _rid("cmp", company),
        "object": "company",
        "created_at": f"{c_y}-{c_m}-{c_d}T08:12:44Z",
        "updated_at": f"{u_y}-{u_m}-{u_d}T16:03:21Z",
        "owner": {"id": owner_id, "name": owner_name, "email": owner_email,
                  "team": "Commercial NL/BE"},
        "address": {"street": "Nijverheidslaan 22",
                    "postal_code": _POSTAL.get(company, "0000"),
                    "city": "Gent", "country": "BE", "region": "Oost-Vlaanderen"},
        "phone": f"+32 {area} {g1} {g2} {g3}",
        "website": f"https://{company.replace(' ', '')}.example.com",
        "employee_count": 24,
        "annual_revenue_eur": _REVENUE_EUR.get(company, 1_000_000),
        "industry": "SMB services",
        "tags": ["nl-be", "smb", "inbound", "newsletter-subscriber"],
        "lifecycle_stage": "customer",
        "custom_fields": {
            "preferred_language": "nl",
            "vat_number": f"BE 0{vat[0:3]}.{vat[3:6]}.{vat[6:9]}",
            "payment_terms_days": 30,
            "nps_last_score": 8,
            "onboarding_completed": True,
            "source_campaign": "inbound/organic-search",
        },
        "integration_metadata": {
            "synced_from": "folk",
            "sync_version": 42,
            "last_sync_at": f"{s_y}-{s_m}-{s_d}T02:00:00Z",
            "record_hash": _rid("h", company),
        },
    }


def _fatten(core, company: str, kind: str) -> dict:
    """Wrap the scored facts in a production-shaped response.

    kind == "contact": the scored fields (contact, status, last_interaction,
    notes) are MERGED into the envelope's TOP LEVEL, not nested under a
    sub-key — a real CRM contact endpoint returns these as first-class
    properties alongside metadata, and sandbox/test_trajectory_checks.py's
    golden trace test reads `tool_results[0]["last_interaction"]` directly
    (a pre-existing, out-of-scope-for-this-lane test this fixture must keep
    passing). No key collision: the envelope's own keys (id, owner, address,
    custom_fields, ...) share no name with contact/status/last_interaction/
    notes — verified in evals/test_crm_realism.py.

    kind == "deals": the `pipeline` sub-object used to be an IDENTICAL literal
    dict on every company's deals_list envelope — its stage-name strings
    ("discovery", "proposal sent", ...) collided with the stage-word needles
    of 3 old cases (deal-amount, active-client-stage, sofie-deal-stage), and
    its probability floats (0.45 -> normalized "045") and hardcoded "pl_001"
    id were shared >=3-digit tokens across every company (pass-2 criterion
    pre-review finding). Fixed by dropping stage NAMES from the boilerplate
    entirely (numeric codes only, ST-10.."ST-50", each normalizing to a
    2-digit token — below the class rule's threshold and no longer sharing
    any English word with a per-deal `stage` fact) and keying probabilities
    as integer percents under 100 (also 2-digit-or-fewer)."""
    env = _company_envelope(company)
    env["activity_history"] = _activity_history(company)
    if kind == "contact":
        env.update(core)                      # <- the scored facts, verbatim
    else:
        env["deals"] = core                   # <- the scored facts, verbatim
        env["pipeline"] = {
            "id": _rid("pl", company), "name": "Standard sales pipeline",
            "stage_codes": ["ST-10", "ST-20", "ST-30", "ST-40", "ST-50"],
            "probability_pct_by_code": {"ST-10": 20, "ST-20": 45,
                                        "ST-30": 70, "ST-40": 95, "ST-50": 0},
        }
    # api_version is a short semver string, not a date literal — an earlier
    # draft used "2026-06-01" here, identical on every company's envelope
    # (a legitimately GLOBAL field in a real API, but still a >=3-digit
    # token the class rule forbids sharing; caught by the probe, fixed by
    # dropping the date shape rather than by making a global API version
    # falsely per-company).
    env["_meta"] = {"api_version": "v3.2", "request_id": _rid("req", company),
                    "rate_limit_remaining": _RATE_LIMIT.get(company, 999)}
    return env


# ---------------------------------------------------------------------------------
# Tools — identical signatures and identical raise behaviour to the pre-realism
# fixture. The raise happens BEFORE any envelope is built (unchanged control flow).

def crm_lookup(company: str = "") -> dict:
    if _norm(company) == _BACKEND_DOWN["crm_lookup"]:
        raise RuntimeError(f"CRM backend timeout fetching {company!r} (upstream 504)"
                           f" — the record exists but could not be retrieved")
    core = _CRM.get(_norm(company))
    if core is None:
        return {"error": f"no CRM record for {company!r}"}
    return _fatten(core, _norm(company), "contact")


def deals_list(company: str = "") -> list | dict:
    if _norm(company) == _BACKEND_DOWN["deals_list"]:
        raise RuntimeError(f"deals backend timeout fetching {company!r} (upstream "
                           f"504) — open deals exist but could not be retrieved")
    core = _DEALS.get(_norm(company))
    if core is None:
        return {"error": f"no open deals for {company!r}"}
    return _fatten(core, _norm(company), "deals")


def calendar_lookup(company: str = "") -> list | dict:
    return _CALENDAR.get(_norm(company),
                         {"error": f"no upcoming meetings for {company!r}"})


def invoice_lookup(company: str = "") -> list | dict:
    return _INVOICES.get(_norm(company),
                         {"error": f"no invoices on file for {company!r}"})


def contact_search(name: str = "") -> list | dict:
    needle = name.strip().lower()
    hits = [{"name": rec["contact"], "company": company.title()}
            for company, rec in sorted(_CRM.items())
            if needle and needle in rec["contact"].lower()]
    return hits or {"error": f"no contact matching {name!r}"}


def email_log(company: str = "") -> list | dict:
    return _EMAILS.get(_norm(company),
                       {"error": f"no logged emails for {company!r}"})


def note_search(query: str = "") -> list | dict:
    needle = query.strip().lower()
    hits = [{"company": company.title(), "notes": rec["notes"]}
            for company, rec in sorted(_CRM.items())
            if needle and needle in rec["notes"].lower()]
    return hits or {"error": f"no notes matching {query!r}"}
