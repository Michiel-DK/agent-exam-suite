#!/usr/bin/env python3
"""call-fields (CRM field extraction from one call transcript) — check tests.

Every assertion here was built by hand and SEEN RED before being kept (CLAUDE.md gotcha 2).
The red runs are in the PR body. Everything that scores goes through R.score_fields, the
SAME function runner.py uses in `fields` mode (gotcha 5: an ad-hoc probe is not a witness).

What this file proves:

  1. STRUCTURE — the exam is the transcript-en inputs, byte for byte, same ids, same split;
     every expected block has exactly the eight keys, every value a string.
  2. THE VERBATIM GUARD, seen red — every non-"not stated" label is a whitespace-normalised,
     case-insensitive substring of its transcript. An injected invented value is caught; a
     label that only differs by a line-wrap is deliberately allowed.
  3. THE SENTINEL — "not stated" is a literal expected VALUE. The fields scorer reads a
     missing key as None; had the exam used null for absence, an output that simply omits
     every uncertain key would have passed those fields for free. The counterfactual is run.
  4. ISOLATION — each of the eight fields can fail ALONE (fields_matched == 7 of 8) on a
     committed case (gotcha 3).
  5. ADVERSARIAL OUTPUTS — all-"not stated", the REP's name as contact, the onboarding fee
     as the amount, a converted date: each is rejected. Case-insensitivity is confirmed.
  6. THE AGENT LOADS through R.load_agent, at the 16k window, and its prompt names the
     eight keys and the sentinel.
  7. NO LABEL LEAKS INTO THE PROMPT — the prompt's worked examples share no name, company,
     amount or ticket with any committed case.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import runner as R  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


NS = "not stated"
KEYS = ["contact_name", "company", "amount", "currency", "decision_maker",
        "next_step_date", "competitor", "ticket_id"]
EXAM = R.load_exam("call-fields")
CASES = EXAM["cases"]
BY_ID = {c["id"]: c for c in CASES}
TX = json.loads((ROOT / "evals" / "transcript-en" / "cases.json").read_text())["cases"]
TX_BY_ID = {c["id"]: c for c in TX}
PROMPT = (ROOT / "agents" / "call-fields" / "prompt.md").read_text()


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).lower()


def verbatim_violations(cases):
    """The guard the exam ships: (id, key, value) for every label not found in its input as a
    WHOLE token -- not flanked by a letter or digit on either side, so a truncation ('90' for
    '900', 'arc' for 'Marcus') is a violation (test-honesty refuter, 25 Sep)."""
    def found(v, text):
        return re.search(r"(?<![a-z0-9])" + re.escape(norm(v)) + r"(?![a-z0-9])", norm(text)) is not None
    return [(c["id"], k, v) for c in cases for k, v in c["expected"].items()
            if v != NS and not found(v, c["input"])]


def perfect(case):
    return dict(case["expected"])


def test_1_structure():
    check("mode is fields", EXAM.get("mode") == "fields", EXAM.get("mode"))
    check("agent is call-fields", EXAM.get("agent") == "call-fields")
    check("32 cases", len(CASES) == 32, len(CASES))
    check("same ids as transcript-en", set(BY_ID) == set(TX_BY_ID),
          sorted(set(BY_ID) ^ set(TX_BY_ID)))
    same = all(BY_ID[i]["input"] == TX_BY_ID[i]["input"] and BY_ID[i]["split"] == TX_BY_ID[i]["split"]
               for i in BY_ID)
    check("inputs and splits byte-identical to transcript-en, per id", same)
    check("split is 13 train / 19 heldout",
          sum(c["split"] == "train" for c in CASES) == 13 and sum(c["split"] == "heldout" for c in CASES) == 19)
    check("every expected has exactly the eight keys",
          all(list(c["expected"].keys()) == KEYS for c in CASES))
    check("every expected value is a non-empty string",
          all(isinstance(v, str) and v.strip() for c in CASES for v in c["expected"].values()))
    check("no expected value carries an HTML entity or surrounding whitespace",
          all(v == v.strip() and "&amp;" not in v for c in CASES for v in c["expected"].values()))


def test_2_verbatim_guard_seen_red():
    check("committed labels: zero verbatim violations", verbatim_violations(CASES) == [],
          verbatim_violations(CASES)[:3])
    bad = json.loads(json.dumps(BY_ID["discovery-short-train"]))
    bad["expected"]["amount"] = "999999"
    check("RED: an invented amount is caught, and only it",
          verbatim_violations([bad]) == [("discovery-short-train", "amount", "999999")],
          verbatim_violations([bad]))
    wrapped = BY_ID["discovery-long-train"]  # 'Torvane\nManufacturing' in the transcript
    check("a label split by a line-wrap in the transcript is allowed (whitespace-normalised)",
          verbatim_violations([wrapped]) == [] and "\n" in wrapped["input"][
              wrapped["input"].lower().find("torvane"):wrapped["input"].lower().find("torvane") + 30])
    dropped = json.loads(json.dumps(wrapped))
    dropped["expected"]["company"] = "Torvane Corp"
    check("RED: a company with a changed word is caught", verbatim_violations([dropped]) != [])
    trunc = json.loads(json.dumps(BY_ID["discovery-short-train"]))
    trunc["expected"]["amount"] = "90"  # a substring of the real '900'
    check("RED: a truncated amount ('90' inside '900') is caught -- whole-token match, not substring",
          verbatim_violations([trunc]) == [("discovery-short-train", "amount", "90")], verbatim_violations([trunc]))
    trunc["expected"]["amount"] = "900"; trunc["expected"]["contact_name"] = "arc"  # inside 'Marcus'
    check("RED: a name fragment ('arc' inside 'Marcus') is caught",
          verbatim_violations([trunc]) == [("discovery-short-train", "contact_name", "arc")])
    check("competitor is 'not stated' in ALL 32 cases, both splits: the field is abstention-only (declared in not_verified)",
          all(c["expected"]["competitor"] == NS for c in CASES) and "every one of the 32" in EXAM["not_verified"])
    check("every heldout case has at least two non-'not stated' labels (the exam is not an abstention-only exam)",
          all(sum(v != NS for v in c["expected"].values()) >= 2 for c in CASES if c["split"] == "heldout"),
          [c["id"] for c in CASES if sum(v != NS for v in c["expected"].values()) < 2])


def test_3_missing_key_sentinel_through_real_scorer():
    case = BY_ID["discovery-short-train"]  # competitor is 'not stated' here
    out = perfect(case)
    del out["competitor"]
    passed, detail = R.score_fields(out, case["expected"])
    check("an output that OMITS a 'not stated' key fails, exactly one field short",
          passed is False and detail == {"fields_matched": 7, "fields_total": 8}, detail)
    passed, detail = R.score_fields(perfect(case), case["expected"])
    check("the perfect output passes 8/8", passed is True and detail["fields_matched"] == 8, detail)
    # Counterfactual: the null-as-null design this exam deliberately did NOT use.
    null_expected = dict(case["expected"], competitor=None)
    passed_null, _ = R.score_fields(out, null_expected)
    check("COUNTERFACTUAL: with null instead of the sentinel, the same omission would PASS "
          "(missing key reads as None) -- the sentinel is load-bearing", passed_null is True)


def test_4_every_field_isolates():
    for key in KEYS:
        case = next((c for c in CASES if c["expected"][key] != NS), None) or BY_ID["discovery-short-train"]
        out = perfect(case)
        out[key] = "Acme Corp" if case["expected"][key] == NS else NS
        passed, detail = R.score_fields(out, case["expected"])
        check(f"field {key!r} fails alone on {case['id']} (7 of 8)",
              passed is False and detail["fields_matched"] == 7, detail)


def test_5_adversarial_outputs():
    all_ns = {k: NS for k in KEYS}
    n_pass = sum(R.score_fields(all_ns, c["expected"])[0] for c in CASES)
    check("an all-'not stated' output passes 0 of 32 cases", n_pass == 0, n_pass)
    best = max(R.score_fields(all_ns, c["expected"])[1]["fields_matched"] for c in CASES)
    check("...and never more than 7 of 8 fields on any case", best <= 7, best)
    case = BY_ID["discovery-short-train"]
    out = perfect(case); out["contact_name"] = "Dana"  # the REP
    check("the REP's name as contact is rejected", R.score_fields(out, case["expected"]) == (False, {"fields_matched": 7, "fields_total": 8}))
    out = perfect(case); out["amount"] = "500"  # the one-time onboarding fee, not the plan
    check("the onboarding fee as the amount is rejected", not R.score_fields(out, case["expected"])[0])
    out = perfect(case); out["next_step_date"] = "Thursday 2pm"
    check("a padded date token is rejected (exact match is the contract, see not_verified)",
          not R.score_fields(out, case["expected"])[0])
    out = perfect(case); out["company"] = "beacon freight"; out["contact_name"] = "MARCUS"
    check("case differences are forgiven by the scorer", R.score_fields(out, case["expected"])[0] is True)
    quiet = BY_ID["quiet-checkin-heldout-short"]
    out = perfect(quiet); out["amount"] = "0"
    check("inventing an amount on a quiet call is rejected", not R.score_fields(out, quiet["expected"])[0])


def test_6_agent_loads():
    agent = R.load_agent("call-fields")
    check("agent provider is ollama", agent.get("provider") == "ollama", agent.get("provider"))
    check("agent model is the 16k-window champion config", agent.get("model") == "gemma4-e4b-ctx16k", agent.get("model"))
    mf = (ROOT / "agents" / "call-fields" / "Modelfile").read_text()
    check("Modelfile pins num_ctx 16384 on gemma4:e4b-it-qat",
          "PARAMETER num_ctx 16384" in mf and "FROM gemma4:e4b-it-qat" in mf)
    check("prompt names all eight keys", all(f"`{k}`" in PROMPT for k in KEYS))
    check("prompt states the sentinel and the every-key rule",
          "`not stated`" in PROMPT and "every one of the eight keys must be present" in norm(PROMPT))
    check("agent temperature is 0", float(agent.get("temperature", 1)) == 0.0)


def test_7_no_label_leaks_into_prompt():
    leaky = []
    for c in CASES:
        for k in ("contact_name", "company", "amount", "decision_maker", "ticket_id"):
            v = c["expected"][k]
            if v != NS and _leaks(v, PROMPT):
                leaky.append((c["id"], k, v))
    check("no committed name, company, amount, decision maker or ticket id appears in the prompt",
          leaky == [], leaky[:5])
    train_vals = {v for c in CASES if c["split"] == "train" for v in c["expected"].values()}
    heldout_only = sorted({(k, v) for c in CASES if c["split"] == "heldout" for k, v in c["expected"].items()
                           if v != NS and v not in train_vals})
    leaky_h = [(k, v) for k, v in heldout_only if _leaks(v, PROMPT)]
    check("no heldout-ONLY label of ANY field (dates and currency included) appears in the prompt "
          "-- a generic token that is also a train label ('Thursday', 'EUR') is allowed",
          leaky_h == [], leaky_h)
    check("...and that set is non-trivial (at least 4 heldout-only labels exist)", len(heldout_only) >= 4, len(heldout_only))
    check("RED: a label followed by a sentence-ending period is caught ('Marcus.')",
          _leaks("Marcus", "The prospect is Marcus. He runs ops.") and _leaks("2450.00", "flat 2450.00 monthly"))
    check("a label that is only the integer part of a decimal is still treated as a leak (conservative)",
          _leaks("2450", "flat 2450.00 monthly"))
    check("a label inside a longer token is not a leak ('900' in '2900')", not _leaks("900", "at 2900 a month"))


def _leaks(value: str, text: str) -> bool:
    return re.search(r"(?<![\w.])" + re.escape(value.lower()) + r"(?!\w)", text.lower()) is not None


def main() -> int:
    print(f"call-fields checks — {len(CASES)} cases "
          f"({sum(c['split']=='train' for c in CASES)} train, {sum(c['split']=='heldout' for c in CASES)} heldout)")
    for fn in sorted((v for k, v in globals().items() if k.startswith("test_") and callable(v)),
                     key=lambda f: f.__name__):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all green'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
