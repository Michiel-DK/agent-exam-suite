#!/usr/bin/env python3
"""transcript-en (S-TRANSCRIPT-EN-EXAM) — check tests: isolation, adversarial
fixtures, and the ledger-017 vacuous-green guard, all in one file (this exam's
declaredFiles list ONE test file; recap split the same coverage across three —
test_e13_recap.py / test_recap_adversarial.py / test_recap_vacuous_green.py — this
file carries their combined role for transcript-en).

Every assertion below was built by hand and SEEN RED before being kept (CLAUDE.md
gotcha 2: "a green guard proves nothing until seen RED" — two adversarial tests in
this repo once looked green while asserting nothing). Concretely: each fixture in
this file was run once through R.run_properties with a manual print of the
resulting `failed_checks` BEFORE the `check(...)` assertion around it was written,
to confirm the fixture actually fails the way the assertion claims.

THREE THINGS THIS FILE PROVES, mirroring recap's three-file split:

  1. ISOLATION (mirrors test_e13_recap.py). For every check, a synthetic output
     fails ONLY that check on some committed case. This is the load-bearing part
     for check_action_items specifically — CLAUDE.md gotcha 3 / the build
     criterion require it, and it has been shipped unfalsifiable three times in
     this repo, each time disguised by a score moving the expected direction.

  2. ADVERSARIAL FIXTURES (mirrors test_recap_adversarial.py). Deliberately
     construct the outputs a lazy or degenerate strategy would produce —
     content-free, echoing, false-abstaining, padding, inventing a figure — and
     assert the exam rejects them. Mutation testing applied to the model's OUTPUT
     space: deterministic, no inference, catches exactly the failure mode that let
     a hand-built degenerate output tie recap's champion while isolation stayed
     green the whole time (recap's Lane A).

  3. THE LEDGER-017 VACUOUS-GREEN GUARD (mirrors test_recap_vacuous_green.py). An
     input that does not match any committed case must RAISE through the real
     scoring path (R.run_properties), never resolve to {} and pass every
     parameterised check for free.

Everything goes through R.run_properties, the SAME function runner.py uses to
score a committed case (CLAUDE.md gotcha 5: an ad-hoc probe is not a witness for
the tool) — never a reimplementation of the check logic.
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import runner as R  # noqa: E402

# `properties` loaded BY PATH (not `import properties`): under pytest every exam's tests
# share one process and a bare import returns whichever exam's properties.py came first —
# the public repo's CI resolved it to recap's on 8 Sep. test.sh (one process per file)
# never showed it.
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location(
    "_transcript_en_properties", ROOT / "evals" / "transcript-en" / "properties.py")
P = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(P)

sys.path.insert(0, str(ROOT / "docs" / "probes" / "transcript-long-2026-09-06"))
from pass1_check_action_owner_ref import check_action_owner_every_hit  # noqa: E402
from pass2_check_action_owner_ref import check_action_owner_pass2  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


CASES = json.loads((ROOT / "evals" / "transcript-en" / "cases.json").read_text())["cases"]
BY_ID = {c["id"]: c for c in CASES}
PROPS = R.load_properties("transcript-en")
LONG_MIN = 3200  # this exam's shortest genuinely long-band case (discovery-heldout-long)
LONG = [c for c in CASES if len(c["input"]) >= LONG_MIN]
QUIET = [c for c in CASES if (c.get("expected") or {}).get("nothing_important") is True]
BUSY = [c for c in CASES if (c.get("expected") or {}).get("nothing_important") is False]
LONGCALL = [c for c in CASES if c["id"].startswith("longcall-")]
LONGCALL_NONQUIET = [c for c in LONGCALL
                     if (c.get("expected") or {}).get("nothing_important") is not True]


def verdict(case_id, output):
    """(ok, [check names]) through the REAL scoring path, never a reimplementation."""
    case = BY_ID[case_id]
    ok, _failures, failed = R.run_properties(PROPS, case["input"], output)
    return ok, [f["check"] for f in failed]


def only(case_id, output, expected_check):
    """Assert this output fails EXACTLY the named check and nothing else."""
    ok, names = verdict(case_id, output)
    check(f"{case_id}: fails ONLY {expected_check}",
          not ok and names == [expected_check], f"failed_checks={names}")


# ---------------------------------------------------------------- 0. sanity: cases load

def test_0_every_committed_case_has_a_bucket_marked_check_set():
    check("8 checks loaded, each with a valid bucket",
          len(PROPS) == 8, f"got {len(PROPS)}: {[n for n, _ in PROPS]}")
    check(f"{len(CASES)} committed cases (22 pre-existing + longcall-* band)",
          len(CASES) >= 32, f"got {len(CASES)}")
    n_train = sum(1 for c in CASES if c["split"] == "train")
    n_heldout = sum(1 for c in CASES if c["split"] == "heldout")
    check("heldout N >= 12 (power requirement)", n_heldout >= 12,
          f"train={n_train} heldout={n_heldout}")
    n_longcall = sum(1 for c in CASES if c["id"].startswith("longcall-"))
    n_longcall_heldout = sum(1 for c in CASES
                             if c["id"].startswith("longcall-") and c["split"] == "heldout")
    n_longcall_train = sum(1 for c in CASES
                           if c["id"].startswith("longcall-") and c["split"] == "train")
    check("longcall-* band N >= 10 (lane 1)", n_longcall >= 10, f"got {n_longcall}")
    check("longcall-* heldout >= 6", n_longcall_heldout >= 6, f"got {n_longcall_heldout}")
    check("longcall-* train >= 4", n_longcall_train >= 4, f"got {n_longcall_train}")


# ---------------------------------------------------------------- 1. baselines pass everything

# A correct summary for a busy call: covers must_mention, lists the required
# commitments, correct nothing_important, well under the ratio cap.
GOOD_BUSY = {
    "summary": "Dana spoke with Marcus at Beacon Freight about scaling shipment "
               "tracking beyond spreadsheets. Quoted 900 EUR per month. Marcus "
               "will loop in finance director Elena before committing.",
    "action_items": ["Rep to send a one-page proposal today",
                     "Rep and prospect to hold a follow-up call Thursday"],
    "nothing_important": False,
}

# A correct summary for a quiet call: abstains, empty action_items, short.
GOOD_QUIET = {
    "summary": "Routine monthly check-in with Sam. Everything running smoothly, "
               "no complaints, no new requests from the team.",
    "action_items": [],
    "nothing_important": True,
}


def test_1_good_outputs_pass_every_check():
    """Direction 2 of both-direction: the checks must be SILENT on a correct
    answer. A check that fires on a good summary is worse than no check."""
    ok, names = verdict("discovery-short-train", GOOD_BUSY)
    check("good busy-call summary passes ALL checks", ok, f"failed={names}")
    ok, names = verdict("quiet-checkin-short-train", GOOD_QUIET)
    check("good quiet-call summary passes ALL checks", ok, f"failed={names}")


# ---------------------------------------------------------------- 2. isolation (the load-bearing part)

def test_2_isolation_check_action_items():
    """THE isolation the build criterion names explicitly. A summary that covers
    every must_mention item, at a correct ratio, with the correct nothing_important
    flag, but whose action_items list omits ONE required commitment ('Thursday')
    fails check_action_items and NOTHING else.

    Verified RED before this assertion was kept: without this fixture,
    check_action_items has never been made to fail on its own by anything in this
    file, which is exactly the "unfalsifiable check" failure mode CLAUDE.md gotcha
    3 names — shipped three times in this repo, each disguised by a score moving
    the right way.
    """
    only("discovery-short-train",
         {"summary": "Dana spoke with Marcus at Beacon Freight about scaling "
                     "shipment tracking. Quoted 900 EUR per month. Marcus will "
                     "loop in Elena before committing.",
          "action_items": ["Rep to send a one-page proposal today"],  # Thursday missing
          "nothing_important": False},
         "check_action_items")


def test_2b_check_output_shape_fires_on_malformed_output():
    """check_output_shape is NOT required to isolate (recap's own
    check_output_shape isolation test uses `in names`, never `== [name]` —
    test_e13_recap.py lines 144-147 — because a malformed/empty output starves
    every other check's inputs too, so several fire together; only
    check_action_items, the NEW check, is required to isolate by the build
    criterion). Assert it FIRES, matching repo precedent."""
    ok, names = verdict("discovery-short-train",
                        {"summary": "", "action_items": [], "nothing_important": False})
    check("empty summary -> check_output_shape fires",
          not ok and "check_output_shape" in names, str(names))
    ok, names = verdict("discovery-short-train", "not a dict")
    check("non-dict output -> check_output_shape fires",
          not ok and "check_output_shape" in names, str(names))
    ok, names = verdict("discovery-short-train",
                        {"summary": "x", "action_items": "not a list", "nothing_important": False})
    check("non-list action_items -> check_output_shape fires",
          not ok and "check_output_shape" in names, str(names))


def test_2c_isolation_check_grounded():
    """Invents a figure. Coverage and action_items still satisfied, still short,
    flag still correct — the ONLY problem is the invented number."""
    only("discovery-short-train",
         {"summary": "Dana spoke with Marcus at Beacon Freight, quoting 900 EUR "
                     "per month plus a surprise 12345 EUR setup fee. Elena will "
                     "review.",
          "action_items": ["Rep to send a one-page proposal today",
                           "Rep and prospect to hold a follow-up call Thursday"],
          "nothing_important": False},
         "check_grounded")


def test_2d_isolation_check_coverage():
    """Omits a required must_mention item (Elena) from the summary while
    everything else — action_items, ratio, flag — stays correct."""
    only("discovery-short-train",
         {"summary": "Dana quoted Marcus 900 EUR per month for the platform "
                     "after discussing spreadsheet scaling issues.",
          "action_items": ["Rep to send a one-page proposal today",
                           "Rep and prospect to hold a follow-up call Thursday"],
          "nothing_important": False},
         "check_coverage")


def test_2e_isolation_check_compression():
    """Echoes most of the source into the summary field — covers everything,
    grounds cleanly, correct flag and action_items, but blows the ratio cap."""
    src = BY_ID["discovery-short-train"]["input"]
    only("discovery-short-train",
         {"summary": src,  # 1421 chars vs a 568-char (0.40 x 1421) cap
          "action_items": ["Rep to send a one-page proposal today",
                           "Rep and prospect to hold a follow-up call Thursday"],
          "nothing_important": False},
         "check_compression")


def test_2f_isolation_check_abstention():
    """Quiet call, correct short summary, but action_items is non-empty — a
    manufactured commitment on a call that agreed nothing. Isolated from
    check_compression by keeping the summary itself short."""
    only("quiet-checkin-short-train",
         {"summary": "Routine check-in, nothing needed attention.",
          "action_items": ["Schedule next check-in"],
          "nothing_important": True},
         "check_abstention")


# ------------------------------------------------- 2g-2i. isolation — lane 1 (longcall-*)

# The load-bearing case for both new checks: longcall-discovery-train-1
# (speakers sana malik / emeka osei, must_commit >= 4, commit_owner covering
# both sides, must_not_commit = ["case study"]). A GOOD output for it, used
# as the base every fixture below mutates exactly one thing in.
LC_GOOD = {
    "summary": "Sana spoke with Emeka at Osei Digital Health about scaling clinician "
               "scheduling for 68 staff. Emeka will loop in finance lead Renata "
               "before committing.",
    "action_items": [
        "Customer to loop in finance lead Renata by end of week",
        "Rep to send the revised quote by Thursday",
        "Rep to schedule a technical call with the integrations engineer",
        "Customer to confirm a time with the IT lead",
    ],
    "nothing_important": False,
}


def test_2g_good_output_passes_every_check_including_the_two_new_ones():
    """Direction 2 of both-direction, extended to lane 1: the two new checks
    must be SILENT on a correct answer, same requirement test_1 proves for
    the six pre-existing checks."""
    ok, names = verdict("longcall-discovery-train-1", LC_GOOD)
    check("good longcall output passes ALL checks incl. the two new ones", ok,
          f"failed={names}")


def test_2h_isolation_check_action_owner():
    """Mis-attributes ONE commit_owner item ('loop in', declared customer) to
    the rep by putting 'Rep' as the item's leading token, while every other
    item, the summary, and the flag stay correct. THE isolation the build
    criterion names explicitly for this check.

    Verified RED before this assertion was kept (CLAUDE.md gotcha 2):
    reverting check_action_owner to `return True, ""` was run against this
    exact fixture and printed `failed_checks=[]` (see the PR body for the
    captured output) before this `only(...)` assertion was written.
    """
    bad = dict(LC_GOOD)
    bad["action_items"] = [
        "Rep to loop in finance lead Renata by end of week",  # was Customer to
        "Rep to send the revised quote by Thursday",
        "Rep to schedule a technical call with the integrations engineer",
        "Customer to confirm a time with the IT lead",
    ]
    only("longcall-discovery-train-1", bad, "check_action_owner")


def test_2i_isolation_check_withdrawn_excluded():
    """The 'case study' proposal was explicitly withdrawn on the call
    (longcall-discovery-train-1's own `why` string). A model that lists it as
    a commitment anyway must fail, and ONLY this check, with every genuine
    commitment still present and correctly attributed.

    Verified RED before this assertion was kept: reverting
    check_withdrawn_excluded to `return True, ""` was run against this exact
    fixture and printed `failed_checks=[]` (PR body carries the output)
    before this `only(...)` assertion was written.
    """
    bad = dict(LC_GOOD)
    bad["action_items"] = LC_GOOD["action_items"] + [
        "Rep to send the case study over to Emeka",
    ]
    only("longcall-discovery-train-1", bad, "check_withdrawn_excluded")


def _wrong_build_anywhere_substring(item: str, owner_word: str) -> bool:
    """The REJECTED alternative implementation (checklist class 14, this
    file's own build criterion): 'does the owner word appear ANYWHERE in the
    item' instead of 'is it the LEADING token'. Used here only to PROVE the
    fixture below is a real risk, never imported by properties.py."""
    return owner_word in item.lower()


def test_2j_wrong_build_twin_owner_check():
    """The brief's own worked example (docs/transcript-long-brief-2026-09-06.md,
    'The two checks' section), adapted to a committed case's real
    commit_owner entry rather than an invented key: 'loop in' is declared
    customer-owned on longcall-discovery-train-1. The item below puts 'Rep'
    as the leading token (a genuine mis-attribution) but also mentions
    'customer' later in the same sentence -- exactly the shape that fools an
    anywhere-substring matcher.

    Demonstrates BOTH halves in one test: the wrong build (anywhere-
    substring) would have PASSED this item (proven directly below, no
    properties.py code involved), while the real, shipped check_action_owner
    -- leading token only -- correctly FAILS it. This is what makes 'leading
    token, never substring' (RESULTS.md finding 3, the probe's own scorer
    bug) a load-bearing design choice rather than a style preference.
    """
    misattributed_item = ("Rep to loop in the finance lead Renata once the "
                          "customer signs off on the plan")
    wrong_build_would_pass = not _wrong_build_anywhere_substring(misattributed_item, "rep") \
        or _wrong_build_anywhere_substring(misattributed_item, "customer")
    check("the anywhere-substring wrong build finds 'customer' in the item and "
          "would PASS a mis-attributed item",
          wrong_build_would_pass, misattributed_item)

    bad = dict(LC_GOOD)
    bad["action_items"] = [
        misattributed_item,
        "Rep to send the revised quote by Thursday",
        "Rep to schedule a technical call with the integrations engineer",
        "Customer to confirm a time with the IT lead",
    ]
    only("longcall-discovery-train-1", bad, "check_action_owner")


def _props_with_action_owner_swapped(replacement) -> list:
    """PROPS with `check_action_owner` replaced by `replacement` — everything
    else (the other 7 checks) stays the SHIPPED code. Used only to demonstrate
    what pass 1's every-hit rule would have done, never to change what ships."""
    return [(name, replacement if name == "check_action_owner" else fn)
            for name, fn in PROPS]


PROPS_EVERY_HIT = _props_with_action_owner_swapped(check_action_owner_every_hit)


def test_2k_any_hit_correct_fixture_a():
    """Pass-2 criterion clause (2), fixture A. `longcall-discovery-train-1`
    declares `commit_owner['loop in'] == 'customer'`. LC_GOOD already has ONE
    correctly-attributed 'loop in' item ('Customer to loop in finance lead
    Renata...'); this fixture ADDS a second 'loop in' item wrongly attributed
    to the rep, while every other required commitment stays present and
    correctly owned, no invented number (check_grounded scans action_items
    too), and the summary is untouched (check_compression reads summary
    only) -- so no other check is disturbed.

    ANY-HIT-CORRECT (the shipped rule): the key has 2 hits, >= 1 correctly
    owned ('Customer to loop in...') -> PASSES. Asserted here via the REAL
    R.run_properties against the SHIPPED PROPS -- not a claim, a green
    assertion.

    The PR body additionally pastes this exact fixture run through
    PROPS_EVERY_HIT (pass 1's rule, `pass1_check_action_owner_ref.py`,
    swapped in for `check_action_owner` only, every other check untouched)
    to show it FAILS -- the revert-demo clause (2) requires. That comparison
    is ALSO asserted mechanically right here, not left as a PR-body-only
    claim: two hits, one wrong, fails every-hit by construction.
    """
    fixture_a = dict(LC_GOOD)
    fixture_a["action_items"] = LC_GOOD["action_items"] + [
        "Rep to loop in the solutions architect before the demo",
    ]

    ok, names = verdict("longcall-discovery-train-1", fixture_a)
    check("fixture A: any-hit-correct PASSES a duplicate 'loop in' hit with "
          "one correctly owned (shipped rule, real run_properties)",
          ok, f"failed={names}")

    ok_ref, _f_ref, failed_ref = R.run_properties(
        PROPS_EVERY_HIT, BY_ID["longcall-discovery-train-1"]["input"], fixture_a)
    names_ref = [f["check"] for f in failed_ref]
    check("fixture A, IDENTICAL fixture, pass-1's every-hit rule swapped in: "
          "FAILS check_action_owner (the revert-demo clause (2) requires)",
          not ok_ref and "check_action_owner" in names_ref,
          f"ok={ok_ref} failed={names_ref}")


# --------------------- 2l-2m. no-shared-joiner rule (criterion clause 4, ledger 041 finding 3)

_PROPERTIES_SOURCE = (ROOT / "evals" / "transcript-en" / "properties.py").read_text()

# The exact statement `check_withdrawn_excluded` uses today to build its own
# joined/lowercased action-items string -- unique in the file (grepped before
# writing this constant), which is what makes the string-replace below a safe
# way to construct a SCRATCH "as if it still called the presence join"
# variant without ever touching the real, shipped file.
_WITHDRAWN_OWN_JOIN_LINE = (
    'text = " | ".join(str(i) for i in _action_items(output)).lower()')
_WITHDRAWN_REVERTED_JOIN_LINE = "text = _action_items_text(output).lower()"
assert _PROPERTIES_SOURCE.count(_WITHDRAWN_OWN_JOIN_LINE) == 1, (
    "the join line this test scratch-reverts is not unique in properties.py "
    "-- the string-replace below would be ambiguous")


def _transitive_calls(source: str) -> dict:
    """{function name: set of module-level function names reachable by a
    chain of DIRECT `name(...)` calls}, over every top-level `def` in
    `source`. An Attribute call (`" ".join(...)`, `x.lower()`) is not an edge
    -- only calls to another function DEFINED in this same module are, which
    is exactly the shape needed to ask "does check_withdrawn_excluded's call
    chain ever reach a function also reachable from another check"."""
    tree = ast.parse(source)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    direct = {}
    for name, node in funcs.items():
        direct[name] = {sub.func.id for sub in ast.walk(node)
                        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id in funcs and sub.func.id != name}
    closure = {}
    for name in funcs:
        seen, stack = set(), list(direct.get(name, ()))
        while stack:
            f = stack.pop()
            if f in seen:
                continue
            seen.add(f)
            stack.extend(direct.get(f, ()))
        closure[name] = seen
    return closure


def _shared_joiner_violations(source: str, target: str = "check_withdrawn_excluded") -> list:
    """Every violation of criterion clause 4's EXEMPTION-SCOPED rule: no
    joined/lowercased-action-items-producing function shared between
    `target` and any OTHER check_* in `source` -- not "no shared function of
    any kind" (that would also flag _exp / _action_items, both explicitly
    permitted). Returns [] when clean.

    _exp is exempt by the criterion's own text (every check resolves
    expectations through it, presence and absence alike -- the ledger-017
    RAISE, not a joined/lowercased action-items producer); _action_items is
    exempt too (the raw list accessor). The exemption covers each one's OWN
    transitive call set as well (e.g. _exp's own `_expectations_by_input`
    helper) -- not because that helper is separately blessed, but because
    penalising a check for reaching a private implementation detail of an
    explicitly-permitted function would just be the same rule under a
    different name.
    """
    closure = _transitive_calls(source)
    exempt = ({"_exp", "_action_items"}
             | closure.get("_exp", set()) | closure.get("_action_items", set()))
    target_calls = closure.get(target, set())
    violations = []
    if "_action_items_text" in target_calls:
        violations.append(f"{target} reaches _action_items_text (the PRESENCE "
                          "join check_grounded/check_action_items also call) "
                          "directly or transitively")
    for name in closure:
        if not name.startswith("check_") or name == target:
            continue
        shared = (target_calls & closure[name]) - exempt
        if shared:
            violations.append(f"{target} shares {sorted(shared)} with {name}")
    return violations


def test_2l_no_shared_joiner_withdrawn_excluded():
    """Criterion clause 4, pinned mechanically over the REAL, shipped
    properties.py source (ledger 041 finding 3 — pass 1's
    check_withdrawn_excluded called `_action_items_text`, the same
    joined/lowercased helper check_grounded and check_action_items call,
    violating the directionality-rule docstring's own "presence and absence
    must never share a helper"). `_exp` and `_action_items` are exempt by
    the criterion's explicit text; every other shared reachable function
    would be a violation."""
    violations = _shared_joiner_violations(_PROPERTIES_SOURCE)
    check("check_withdrawn_excluded shares no joined/lowercased "
          "action-items-producing function with any other check, and does "
          "not reach _action_items_text",
          not violations, f"violations={violations}")


def test_2m_no_shared_joiner_red_demo():
    """Seen RED before test_2l was trusted (CLAUDE.md gotcha 2 / the repo
    invariant that a guard is untrusted until seen RED on the defect it
    exists to catch, injection target named). Builds a SCRATCH copy of
    properties.py's source with ONLY check_withdrawn_excluded's own join
    line reverted to pass 1's `_action_items_text(output).lower()` call --
    exactly ledger 041 finding 3 -- and re-runs the identical rule from
    test_2l against that scratch source. The real, committed
    evals/transcript-en/properties.py is never touched; this is a string
    in memory, parsed and discarded."""
    reverted_source = _PROPERTIES_SOURCE.replace(
        _WITHDRAWN_OWN_JOIN_LINE, _WITHDRAWN_REVERTED_JOIN_LINE, 1)
    check("the scratch source actually differs from the shipped source "
          "(the revert took effect)",
          reverted_source != _PROPERTIES_SOURCE)

    violations = _shared_joiner_violations(reverted_source)
    check("RED: the rule fires on the pass-1-shaped scratch source, naming "
          "check_withdrawn_excluded and _action_items_text (the injection "
          "target)",
          any("_action_items_text" in v for v in violations),
          f"violations={violations}")


# --------------- 2n-2p. `_leading_owner_token` parser tolerance (pass 3, criterion clause 2)

PROPS_PASS2_PARSER = _props_with_action_owner_swapped(check_action_owner_pass2)


def test_2n_parenthetical_owner_resolves():
    """`Customer (Emeka) to confirm a time with the IT lead` -- the real,
    recorded Kimi phrasing this pass fixes (ledger 041 finding: 'Customer
    (Callan) to ...' on longcall-renewal-heldout-2). `_leading_owner_token`
    strips the parenthetical before the whole-word owner search, so this
    resolves to 'customer' -- PASSES under the shipped rule.

    RED AGAINST THE PASS-2 PARSER (real run_properties, PROPS_PASS2_PARSER
    swapped in for check_action_owner only, every other check the shipped
    code): 'customer (emeka)' never equals the bare token 'customer' under
    pass 2's set-equality match, so pass 2 reads this hit as unrecognised
    and FAILS the key -- asserted mechanically here, not left as a PR-body
    claim.
    """
    fixture = dict(LC_GOOD)
    fixture["action_items"] = [
        "Customer to loop in finance lead Renata by end of week",
        "Rep to send the revised quote by Thursday",
        "Rep to schedule a technical call with the integrations engineer",
        "Customer (Emeka) to confirm a time with the IT lead",  # was "Customer to ..."
    ]

    ok, names = verdict("longcall-discovery-train-1", fixture)
    check("parenthetical fixture: 'Customer (Emeka) to ...' resolves to "
          "customer and PASSES (shipped rule, real run_properties)",
          ok, f"failed={names}")

    ok_p2, _f_p2, failed_p2 = R.run_properties(
        PROPS_PASS2_PARSER, BY_ID["longcall-discovery-train-1"]["input"], fixture)
    names_p2 = [f["check"] for f in failed_p2]
    check("RED: identical fixture, pass-2's set-equality parser swapped in: "
          "FAILS check_action_owner ('customer (emeka)' != 'customer')",
          not ok_p2 and "check_action_owner" in names_p2,
          f"ok={ok_p2} failed={names_p2}")


def test_2o_clause_prefixed_owner_resolves():
    """`After confirming budget with finance, Sana will send the revised
    quote by Thursday` -- the real, recorded Kimi phrasing this pass fixes
    (ledger 041 finding: 'Sana will send updated pricing ...', Sana IS the
    rep). longcall-discovery-train-1 declares speakers.rep = 'sana malik',
    so the whole-word search over the leading clause finds 'sana' and no
    customer token -- resolves to rep, PASSES under the shipped rule.

    RED AGAINST THE PASS-2 PARSER: the entire clause before ' will ' is the
    leading segment under set-equality too, but it never equals a bare
    token in rep_tokens ('rep', 'the rep', 'sana malik', 'sana', 'malik'),
    so pass 2 reads it as unrecognised and FAILS the key.
    """
    fixture = dict(LC_GOOD)
    fixture["action_items"] = [
        "Customer to loop in finance lead Renata by end of week",
        "After confirming budget with finance, Sana will send the revised "
        "quote by Thursday",  # was "Rep to send the revised quote by Thursday"
        "Rep to schedule a technical call with the integrations engineer",
        "Customer to confirm a time with the IT lead",
    ]

    ok, names = verdict("longcall-discovery-train-1", fixture)
    check("clause-prefixed fixture: 'After confirming budget with finance, "
          "Sana will ...' resolves to rep and PASSES (shipped rule, real "
          "run_properties)",
          ok, f"failed={names}")

    ok_p2, _f_p2, failed_p2 = R.run_properties(
        PROPS_PASS2_PARSER, BY_ID["longcall-discovery-train-1"]["input"], fixture)
    names_p2 = [f["check"] for f in failed_p2]
    check("RED: identical fixture, pass-2's set-equality parser swapped in: "
          "FAILS check_action_owner (the whole clause != 'sana')",
          not ok_p2 and "check_action_owner" in names_p2,
          f"ok={ok_p2} failed={names_p2}")


def test_2p_both_sides_named_is_unrecognised():
    """A leading segment naming BOTH sides ('Rep and Customer to loop in
    ...') must not count as evidence for EITHER declared owner -- an
    ambiguous lead is not an attribution, so the 'loop in' key (declared
    customer) fails for lack of an unambiguous hit, exactly as if no hit had
    resolved at all. This is the isolation fixture for the 'unrecognised if
    neither or both' half of the pass-3 rule; every other required
    commitment stays present and correctly owned, so this fails ONLY
    check_action_owner.

    Also RED against the pass-2 parser, for a different reason: 'rep and
    customer' never equals a bare token there either, so pass 2 fails this
    key too -- included for completeness, not because pass 2 got the right
    answer for the right reason (pass 2's parser cannot even ask the
    'ambiguous vs. unrecognised' question; it only ever asks 'does the whole
    segment equal one exact token').
    """
    bad = dict(LC_GOOD)
    bad["action_items"] = [
        "Rep and Customer to loop in finance lead Renata by end of week",  # was "Customer to ..."
        "Rep to send the revised quote by Thursday",
        "Rep to schedule a technical call with the integrations engineer",
        "Customer to confirm a time with the IT lead",
    ]
    only("longcall-discovery-train-1", bad, "check_action_owner")

    ok_p2, _f_p2, failed_p2 = R.run_properties(
        PROPS_PASS2_PARSER, BY_ID["longcall-discovery-train-1"]["input"], bad)
    names_p2 = [f["check"] for f in failed_p2]
    check("RED (for a different reason): pass-2's set-equality parser also "
          "fails this key ('rep and customer' != any exact token)",
          not ok_p2 and "check_action_owner" in names_p2,
          f"ok={ok_p2} failed={names_p2}")


def test_2r_topic_label_prefix_resolves():
    """`Escalation: Rep to open an escalation ticket ...` -- the shape the
    pass-3 correctness refuter built (8 Sep): a TOPIC LABEL before the owner,
    where the earliest delimiter is the label's colon and the pre-colon
    segment ('escalation') names nobody. `_leading_owner_segment` drops such
    a label (only when the pre-colon segment carries no known owner token,
    so 'Rep: send ...' is untouched) and re-slices after it, so the segment
    becomes 'rep' and the key PASSES. Same fixture with the owner flipped
    ('Escalation: Customer to open ...') still FAILS -- the tolerance does
    not weaken attribution.

    RED AGAINST THE PASS-2 PARSER: pass 2 slices at the colon and reads
    'escalation' as the leading token -> unrecognised -> FAILS the key.
    """
    fixture = dict(LC_GOOD)
    fixture["action_items"] = [
        "Escalation: Customer to loop in finance lead Renata by end of week",
        "Quote: Rep to send the revised quote by Thursday",
        "Technical call: Rep to schedule a technical call with the integrations "
        "engineer",
        "IT: Customer to confirm a time with the IT lead",
    ]
    ok, names = verdict("longcall-discovery-train-1", fixture)
    check("topic-label fixture: 'Quote: Rep to send ...' resolves to rep and "
          "PASSES (shipped rule, real run_properties)", ok, f"failed={names}")

    flipped = dict(fixture)
    flipped["action_items"] = [
        "Escalation: Customer to loop in finance lead Renata by end of week",
        "Quote: Customer to send the revised quote by Thursday",   # rep's commitment, mis-owned
        "Technical call: Rep to schedule a technical call with the integrations "
        "engineer",
        "IT: Customer to confirm a time with the IT lead",
    ]
    ok_f, names_f = verdict("longcall-discovery-train-1", flipped)
    check("topic-label fixture, owner flipped: still FAILS check_action_owner "
          "(the tolerance does not weaken attribution)",
          not ok_f and "check_action_owner" in names_f, f"ok={ok_f} failed={names_f}")

    ok_p2, _f_p2, failed_p2 = R.run_properties(
        PROPS_PASS2_PARSER, BY_ID["longcall-discovery-train-1"]["input"], fixture)
    names_p2 = [f["check"] for f in failed_p2]
    check("RED: identical fixture, pass-2's parser swapped in: FAILS "
          "check_action_owner ('escalation'/'quote' read as the leading token)",
          not ok_p2 and "check_action_owner" in names_p2,
          f"ok={ok_p2} failed={names_p2}")


def test_2q_fixture_c_wrong_build_twin_still_fails():
    """Criterion clause (2)'s closing sentence: fixture C (test_2j, the
    anywhere-substring wrong-build twin) must STILL fail after the pass-3
    tolerance fix -- the parenthetical/clause tolerance must not have
    widened the leading segment to reach text AFTER the first delimiter.
    Re-run here explicitly (not just relying on test_2j staying green) so
    the PR body has one assertion that names this exact regression risk."""
    misattributed_item = ("Rep to loop in the finance lead Renata once the "
                          "customer signs off on the plan")
    bad = dict(LC_GOOD)
    bad["action_items"] = [
        misattributed_item,
        "Rep to send the revised quote by Thursday",
        "Rep to schedule a technical call with the integrations engineer",
        "Customer to confirm a time with the IT lead",
    ]
    only("longcall-discovery-train-1", bad, "check_action_owner")


# ---------------------------------------------------------------- 3. adversarial fixtures

CONTENT_FREE = {"summary": "A call took place covering a few topics and some "
                           "follow-up items were discussed.",
                "action_items": [], "nothing_important": False}


def test_3_content_free_summary_fails_every_long_case():
    """The degenerate over-compressing strategy: fluent, short, grounded by
    vacuity (no numbers at all, so the absence-style check_grounded cannot fire),
    naming nobody. Must be rejected everywhere in the long band, via coverage
    (named anchors missing) or action_items (no real commitments listed)."""
    for c in LONG:
        ok, checks = verdict(c["id"], CONTENT_FREE)
        check(f"content-free rejected by {c['id']} ({len(c['input'])} ch)",
              not ok, f"PASSED with checks={checks}")


def test_3b_content_free_rejected_on_substance():
    """Must fail on SUBSTANCE (coverage / action_items / abstention), not merely
    on compression — otherwise the rejection is an artifact of length alone."""
    for c in LONG:
        _ok, checks = verdict(c["id"], CONTENT_FREE)
        substantive = {"check_coverage", "check_action_items", "check_abstention"} & set(checks)
        check(f"{c['id']} rejects content-free on substance",
              bool(substantive), f"only tripped {checks}")


def test_4_echoing_the_input_fails_compression_everywhere():
    """A 'summary' the length of its source has not summarised."""
    for c in CASES:
        if (c.get("expected") or {}).get("max_ratio") is None:
            continue
        out = {"summary": c["input"], "action_items": [], "nothing_important": False}
        _ok, checks = verdict(c["id"], out)
        check(f"echo fails compression on {c['id']}",
              "check_compression" in checks, f"checks={checks}")


def test_5_abstaining_on_a_busy_call_fails():
    """The inverse of over-significance: declaring a call quiet when it produced
    a real decision."""
    for c in BUSY:
        out = {"summary": "Nothing important came up on this call.",
              "action_items": [], "nothing_important": True}
        _ok, checks = verdict(c["id"], out)
        check(f"false abstention caught on {c['id']}",
              "check_abstention" in checks, f"checks={checks}")


def test_6_false_busy_on_a_quiet_call_fails():
    """The other direction: claiming a decision was made on a call that agreed
    nothing."""
    for c in QUIET:
        out = {"summary": "The call resulted in a firm decision to proceed.",
              "action_items": ["Rep to follow up with next steps"],
              "nothing_important": False}
        _ok, checks = verdict(c["id"], out)
        check(f"false busy-flag caught on {c['id']}",
              "check_abstention" in checks, f"checks={checks}")


def test_7_padding_while_abstaining_fails_where_capped():
    for c in QUIET:
        exp = c.get("expected") or {}
        if exp.get("abstain_max_chars") is None:
            check(f"{c['id']} declares an abstain cap", False,
                  "quiet case with no abstain_max_chars — padding is unchecked here")
            continue
        out = {"summary": "Nothing needed your attention on this call. " * 30,
              "action_items": [], "nothing_important": True}
        _ok, checks = verdict(c["id"], out)
        check(f"padded abstention caught on {c['id']}",
              "check_abstention" in checks, f"checks={checks}")


def test_8_action_items_on_a_quiet_call_fails_even_if_short():
    """A model can set the flag honestly, keep the summary short, and still
    manufacture a 'commitment' in action_items — this is the FAILURE OBSERVED FOR
    REAL on quiet-checkin-short-train during the calibration probe (2026-08-26):
    the champion set nothing_important=False AND invented a 'schedule next
    check-in' action item on a call that agreed nothing. This test proves the
    check would catch it even in the (harder) case where the flag itself is set
    correctly and only action_items leaks a manufactured item."""
    for c in QUIET:
        out = {"summary": "A quiet call, nothing needed attention.",
              "action_items": ["Schedule the next check-in call"],
              "nothing_important": True}
        _ok, checks = verdict(c["id"], out)
        check(f"manufactured action item on quiet call caught on {c['id']}",
              "check_abstention" in checks, f"checks={checks}")


def test_9_an_invented_figure_fails_grounding_in_either_field():
    """check_grounded is an ABSENCE check, proven by injecting a figure that is
    demonstrably not in the source — not by observing an honest summary pass.
    Checked in BOTH `summary` and `action_items`, since a fabricated number in an
    action item is exactly as much a fabrication."""
    needle = "999777333"  # absent from every committed case by construction
    for c in CASES:
        assert needle not in c["input"], f"{c['id']} contains the sentinel"
    for c in CASES:
        out_summary = {"summary": f"Total discussed was {needle} EUR.",
                       "action_items": [], "nothing_important": False}
        _ok, checks = verdict(c["id"], out_summary)
        check(f"invented figure in summary caught on {c['id']}",
              "check_grounded" in checks, f"checks={checks}")
        out_items = {"summary": "A call took place.",
                    "action_items": [f"Rep to send the {needle} EUR discount"],
                    "nothing_important": False}
        _ok2, checks2 = verdict(c["id"], out_items)
        check(f"invented figure in action_items caught on {c['id']}",
              "check_grounded" in checks2, f"checks={checks2}")


# ---------------------------------------------------------------- 4. ledger-017 vacuous-green guard

def test_11_committed_inputs_resolve():
    resolved = 0
    for c in CASES:
        try:
            P._exp(c["input"])
            resolved += 1
        except Exception as exc:  # noqa: BLE001
            check(f"committed case {c['id']} resolves", False, repr(exc))
    check(f"all {len(CASES)} committed cases resolve their expectations",
          resolved == len(CASES), f"{resolved}/{len(CASES)}")


def test_12_uncommitted_input_fails_loudly_not_vacuously():
    """THE ATTACK, built by hand: take a real committed case and append a
    constraint to its input, exactly how a plausible new case gets authored by
    mistake (E26's first design, per recap's own docstring)."""
    base = CASES[0]["input"]
    mutated = base + "\n\nExtra constraint: keep the summary under 200 characters."
    raised = False
    try:
        P._exp(mutated)
    except KeyError:
        raised = True
    except Exception as exc:  # noqa: BLE001
        check("mutated input raises KeyError specifically", False,
              f"raised {type(exc).__name__}")
    check("appending a constraint to a committed input raises rather than "
          "returning {}", raised)

    good_enough = {"summary": "x", "action_items": [], "nothing_important": False}
    ok, failures, failed = R.run_properties(PROPS, mutated, good_enough)
    check("run_properties REJECTS an uncommitted input (was: silent full pass)",
          ok is False, f"ok={ok} failed={[f['check'] for f in failed]}")
    check("the rejection names the cause rather than failing opaquely",
          any("does not match any committed case" in f for f in failures),
          f"failures={failures}")

    truncated = base[: len(base) // 2]
    ok_t, _f_t, _fc_t = R.run_properties(PROPS, truncated, good_enough)
    check("run_properties REJECTS a truncated committed input", ok_t is False,
          f"ok={ok_t}")

    ok_e, _f_e, _fc_e = R.run_properties(PROPS, "", good_enough)
    check("run_properties REJECTS an empty input", ok_e is False, f"ok={ok_e}")

    prefix = base[:-1]
    ok_p, _f_p, _fc_p = R.run_properties(PROPS, prefix, good_enough)
    check("a one-character-short prefix of a committed input is REJECTED",
          ok_p is False, f"ok={ok_p}")


# --------------------------------------------- 5. non-vacuity of the longcall-* band

def test_13_longcall_band_is_not_vacuous_on_withdrawn_proposals():
    """The build criterion's own rule, promoted from a fixture-only guarantee
    into a check over the REAL committed band: check_withdrawn_excluded can
    ship isolation-proven (test_2i above) and still be INERT on every real
    case if no committed `must_not_commit` substring is actually reachable —
    absent from every transcript, or double-booked as one of that case's own
    `must_commit` substrings (which would make the check contradict
    check_action_items on the same case). This is what makes
    check_withdrawn_excluded able to fail on the real band, not only on a
    hand-built isolation fixture (criterion clause 3's own wording).

    Checked over every NON-QUIET longcall-* case (the quiet case carries no
    must_not_commit by construction — see test_0). Rule (b), that a
    must_not_commit substring's LAST mention is an unambiguous cancellation
    rather than a hedge, is a per-case authorial judgment recorded in that
    case's `why` string and is verified by READING the diff — no command can
    see it (docs/transcript-long-brief-2026-09-06.md, criterion clause 3's
    own caveat), so it is deliberately not asserted here.
    """
    checked = 0
    for c in LONGCALL_NONQUIET:
        exp = c.get("expected") or {}
        forbidden = exp.get("must_not_commit") or []
        must_commit = [str(m).lower() for m in (exp.get("must_commit") or [])]
        check(f"{c['id']} declares must_not_commit", bool(forbidden), "empty or missing")
        low_input = c["input"].lower()
        for substring in forbidden:
            low_sub = str(substring).lower()
            checked += 1
            check(f"{c['id']}: must_not_commit {substring!r} appears in the transcript",
                  low_sub in low_input, f"absent from input (len={len(c['input'])})")
            check(f"{c['id']}: must_not_commit {substring!r} is not also a must_commit "
                  "substring of the same case",
                  low_sub not in must_commit, f"must_commit={must_commit}")
    check(f"at least one must_not_commit substring checked across the band "
          f"({checked} checked over {len(LONGCALL_NONQUIET)} non-quiet longcall-* cases)",
          checked >= 1, f"checked={checked}")


def test_14_longcall_band_expected_shape():
    """Structural guard on the band itself (build criterion clause 2), over
    the REAL committed cases.json — not the generator's own self-check
    (docs/probes/transcript-long-2026-09-06/build_cases.py runs the same
    shape of assertion at generation time; this is the independent, committed
    copy that survives even if that script is later deleted)."""
    check(f"longcall-* band has >= 10 cases", len(LONGCALL) >= 10, f"got {len(LONGCALL)}")
    n_heldout = sum(1 for c in LONGCALL if c["split"] == "heldout")
    n_train = sum(1 for c in LONGCALL if c["split"] == "train")
    check("longcall-* heldout >= 6", n_heldout >= 6, f"got {n_heldout}")
    check("longcall-* train >= 4", n_train >= 4, f"got {n_train}")
    quiet = [c for c in LONGCALL if (c.get("expected") or {}).get("nothing_important") is True]
    check("exactly one quiet longcall-* case", len(quiet) == 1, f"got {len(quiet)}")
    for c in quiet:
        exp = c.get("expected") or {}
        for k in ("must_commit", "commit_owner", "must_not_commit"):
            check(f"{c['id']} (quiet) carries no {k!r}", k not in exp, f"has {k!r}")
    at_least_30k = [c for c in LONGCALL if len(c["input"]) >= 30000]
    check("at least one longcall-* case >= 30000 chars", len(at_least_30k) >= 1,
          f"lengths={sorted(len(c['input']) for c in LONGCALL)}")
    for c in LONGCALL:
        check(f"{c['id']}: input >= 12000 chars", len(c["input"]) >= 12000,
              f"got {len(c['input'])}")
    for c in LONGCALL_NONQUIET:
        exp = c.get("expected") or {}
        must_commit = exp.get("must_commit") or []
        commit_owner = exp.get("commit_owner") or {}
        must_not_commit = exp.get("must_not_commit") or []
        speakers = exp.get("speakers") or {}
        check(f"{c['id']}: speakers present", bool(speakers.get("rep")) and bool(speakers.get("customer")),
              f"speakers={speakers}")
        check(f"{c['id']}: must_commit >= 4", len(must_commit) >= 4, f"got {len(must_commit)}")
        check(f"{c['id']}: commit_owner >= 4", len(commit_owner) >= 4, f"got {len(commit_owner)}")
        check(f"{c['id']}: commit_owner keys subset of must_commit",
              set(commit_owner) <= set(must_commit),
              f"extra keys={set(commit_owner) - set(must_commit)}")
        check(f"{c['id']}: commit_owner covers both rep and customer",
              {"rep", "customer"} <= set(commit_owner.values()),
              f"owners={set(commit_owner.values())}")
        check(f"{c['id']}: must_not_commit >= 1", len(must_not_commit) >= 1,
              f"got {len(must_not_commit)}")


# ----------------------- 6. commit_owner key distinctiveness (criterion clause 3)

def _distinctive_key_violations(case: dict) -> list:
    """Every violation, on ONE case dict, of the rule criterion clause 3
    requires: each `commit_owner` key must be a substring of EXACTLY ONE
    `must_commit` entry of that same case, and of NO `must_not_commit`
    entry of that same case. `== 1`, never `<= 1` -- an orphaned key (0
    matches) is the vacuous-pass hole check_action_owner's own "no hits ->
    PASS" design creates (a key nobody's action items could ever contain
    silently never fires), and duplicate` (>= 2 matches) is what breaks
    "exactly one". Pure function, no cases.json, no _exp, no run_properties
    -- takes a case dict directly so it can be run against SCRATCH fixtures
    that were never committed."""
    exp = case.get("expected") or {}
    must_commit = [str(m) for m in (exp.get("must_commit") or [])]
    must_not_commit = [str(m) for m in (exp.get("must_not_commit") or [])]
    violations = []
    for key in (exp.get("commit_owner") or {}):
        klow = str(key).lower()
        n_matches = sum(1 for m in must_commit if klow in m.lower())
        if n_matches != 1:
            violations.append(f"{case.get('id', '<scratch>')}: commit_owner key "
                              f"{key!r} is a substring of {n_matches} must_commit "
                              f"entries (need exactly 1)")
        if any(klow in m.lower() for m in must_not_commit):
            violations.append(f"{case.get('id', '<scratch>')}: commit_owner key "
                              f"{key!r} is also a substring of a must_not_commit "
                              "entry of the same case")
    return violations


def test_15_commit_owner_keys_distinctive_over_committed_band():
    """Criterion clause 3, pinned over EVERY committed `longcall-*` case --
    the criterion's own words, so this iterates LONGCALL (all 10), not just
    the 9 non-quiet ones: `longcall-quiet-train-1` carries no `commit_owner`
    today (confirmed: `_distinctive_key_violations` reads
    `exp.get("commit_owner") or {}`, so it contributes 0 keys and 0
    violations either way), but a future quiet case that gained one would be
    silently skipped by a NONQUIET-scoped loop. Pre-review claimed 34
    committed keys already satisfy the rule; this build's own count is 36
    (9 non-quiet cases x 4 keys each, the quiet case contributing 0) --
    stated here as the verified number, not the criterion's parenthetical,
    since this assertion is the authority on the count, not a recollection
    of it. No rename was forced: every violation list below is empty
    without editing cases.json."""
    all_violations = []
    n_keys = 0
    for c in LONGCALL:
        n_keys += len((c.get("expected") or {}).get("commit_owner") or {})
        all_violations.extend(_distinctive_key_violations(c))
    check(f"36 commit_owner keys checked (9 non-quiet longcall-* cases x 4 "
          "each) -- the number this test verified, not the criterion's own "
          "parenthetical '34'",
          n_keys == 36, f"got {n_keys}")
    check("every committed longcall-* case's commit_owner keys are each a "
          "substring of exactly one must_commit entry and no must_not_commit "
          "entry -- 0 renames forced",
          not all_violations, f"violations={all_violations}")


def test_16_commit_owner_distinctiveness_red_both_directions():
    """RED in BOTH directions (criterion clause 3's own explicit demand,
    the ceiling-halt finding: an at-most-one implementation passes the
    letter and lets an orphaned key through). Two hand-built SCRATCH case
    dicts -- never written to cases.json, never touched by _exp or
    run_properties, so there is no vacuous-green exposure from committing
    them: _distinctive_key_violations reads the dict directly."""
    duplicate_case = {
        "id": "scratch-duplicate-not-committed",
        "expected": {
            "must_commit": ["loop in finance", "loop in the legal team", "send the quote"],
            "must_not_commit": ["case study"],
            "commit_owner": {"loop in": "customer"},  # substring of 2 must_commit entries
        },
    }
    dup_violations = _distinctive_key_violations(duplicate_case)
    check("RED (duplicate direction): a commit_owner key matching a SECOND "
          "must_commit entry is flagged",
          any("substring of 2 must_commit entries" in v for v in dup_violations),
          f"violations={dup_violations}")

    orphan_case = {
        "id": "scratch-orphan-not-committed",
        "expected": {
            "must_commit": ["send the quote", "confirm a time"],
            "must_not_commit": ["case study"],
            # 'loop in' matches NO must_commit entry -- the orphaned-key
            # vacuous-pass hole: check_action_owner passes on 0 hits by
            # design, so an at-most-one rule (<= 1, never == 1) would wave
            # this key through unnoticed.
            "commit_owner": {"loop in": "customer"},
        },
    }
    orphan_violations = _distinctive_key_violations(orphan_case)
    check("RED (orphan direction): a commit_owner key matching NO must_commit "
          "entry is flagged (the vacuous-pass hole an at-most-one rule misses)",
          any("substring of 0 must_commit entries" in v for v in orphan_violations),
          f"violations={orphan_violations}")

    # An at-most-one implementation (`n_matches <= 1` instead of `== 1`)
    # would PASS the orphan case -- proven directly, no properties.py code
    # involved, the same style test_2j uses to prove the wrong-build twin
    # is a real risk rather than a hypothetical one.
    n_matches_orphan = sum(
        1 for m in orphan_case["expected"]["must_commit"] if "loop in" in m.lower())
    at_most_one_would_pass = n_matches_orphan <= 1
    check("an at-most-one ('<= 1') implementation would have PASSED the "
          "orphan fixture -- proving == 1 is load-bearing, not a style choice",
          at_most_one_would_pass, f"n_matches={n_matches_orphan}")


def main() -> int:
    print(f"transcript-en checks — {len(CASES)} cases "
          f"({sum(1 for c in CASES if c['split']=='train')} train, "
          f"{sum(1 for c in CASES if c['split']=='heldout')} heldout), "
          f"{len(LONG)} in the long band (>= {LONG_MIN} chars)")
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)), key=lambda f: f.__name__):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all green'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
