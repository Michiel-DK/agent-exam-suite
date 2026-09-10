#!/usr/bin/env python3
"""E6-train — the lesson library: leak guard, train-only extraction, deterministic
retrieval, injection through the REAL entry point, and the snapshot pin.

WHAT THIS PINS, AND WHY EACH ASSERTION EXISTS
---------------------------------------------
The library changes the prompt of a scored run, which puts it one mistake away from
two known disasters in this repo's history:
  - the answer key in the prompt (transcript-long owner-check: scored 5/5 until made
    inert) -> the LEAK GUARD tests, which are run RED here with a hand-built attacker
    input made from a REAL committed expected string (gotcha 2);
  - a prompt that drifts while the gate keeps comparing (rule A) -> the SNAPSHOT PIN
    tests, incl. the isolation requirement of gotcha 3: a snapshot that passes every
    OTHER preflight refusal and fails ONLY on library_sha.
The DEFAULT-UNCHANGED assertions are the important ones (the router-knobs pattern):
no committed agent.yaml sets `library`, load_agent adds no key without it, and the
outgoing system prompt is BYTE-IDENTICAL with no library — asserted through
run_plain_case with a capturing adapter, the real entry point, because presence in a
variable is not effect in a prompt (gotcha 1).

Deterministic: no server, no inference.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import library as L  # noqa: E402
import runner  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


def raises(fn, needle=""):
    try:
        fn()
        return False, "no exception"
    except Exception as exc:  # noqa: BLE001 — asserting on the message
        return (needle.lower() in str(exc).lower(), str(exc)[:120]) if needle else (True, "")


# The attacker input is built from a REAL committed expected string, not a synthetic
# one — if this case is ever rewritten, pick another long expected string; the guard
# must always be shown RED against the actual answer key it protects.
REAL_CASES = json.loads((ROOT / "evals" / "transcript-en" / "cases.json").read_text())["cases"]
_LEAK_CASE = next(c for c in REAL_CASES if c["id"] == "longcall-discovery-train-1")
_REAL_EXPECTED = next(s for s in L._expected_strings(_LEAK_CASE["expected"]) if len(s) >= 25)

GOOD_LESSON = {"situation": "customer retracts an offer mid-call and it resurfaces",
               "what_went_wrong": "withdrawn item listed as a commitment",
               "fix": "when a speaker cancels an item, drop it and do not mention it"}

# ---------------------------------------------------------------- leak guard (RED first)
print("leak guard — seen RED against a real committed expected string")

leaky = dict(GOOD_LESSON, fix="remember: " + _REAL_EXPECTED)
ok, msg = raises(lambda: L.validate_library([leaky], REAL_CASES), "expected-answer")
check("full-quote leak raises naming the leak", ok, msg)

mid = _REAL_EXPECTED[8:8 + 40]  # a window from the MIDDLE of the expected string
ok, msg = raises(lambda: L.validate_library([dict(GOOD_LESSON, fix=mid)], REAL_CASES),
                 "expected-answer")
check("mid-string 40-char quote raises (windowed containment)", ok, msg)

# The two bypasses the correctness verifier reproduced on the first draft, now
# pinned as fixtures (both were NOT CAUGHT before the step-1 + NFKC fixes):
_norm_exp = L._norm(_REAL_EXPECTED)
unaligned = _norm_exp[1:1 + L.MIN_LEAK_CHARS]  # minimal leak at a stride-breaking offset
ok, msg = raises(lambda: L.validate_library([dict(GOOD_LESSON, fix=unaligned)], REAL_CASES),
                 "expected-answer")
check("minimal 15-char leak at an UNALIGNED offset raises (stride-5 bypass, fixed)", ok, msg)

_fullwidth = "".join(chr(0xFF00 + ord(c) - 0x20) if 0x20 < ord(c) < 0x7f else c
                     for c in _REAL_EXPECTED[8:8 + 30])
ok, msg = raises(lambda: L.validate_library([dict(GOOD_LESSON, fix=_fullwidth)], REAL_CASES),
                 "expected-answer")
check("fullwidth-unicode lookalike quote raises (NFKC bypass, fixed)", ok, msg)

try:
    L.validate_library([GOOD_LESSON], REAL_CASES)
    check("clean lesson passes the guard against the full real case set", True)
except Exception as exc:  # noqa: BLE001
    check("clean lesson passes the guard against the full real case set", False, str(exc)[:120])

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "library.json"
    p.write_text(json.dumps({"lessons": [leaky]}))
    ok, msg = raises(lambda: L.load_library(p, REAL_CASES), "expected-answer")
    check("load_library refuses a leaky file (guard runs at LOAD, not only in tests)", ok, msg)
    p.write_text(json.dumps({"lessons": []}))
    ok, msg = raises(lambda: L.load_library(p, REAL_CASES), "non-empty")
    check("empty lessons list refuses loudly (never a silent no-op library)", ok, msg)
    p.write_text(json.dumps({"lessons": [{"situation": "x"}]}))
    ok, msg = raises(lambda: L.load_library(p, REAL_CASES), "required key")
    check("lesson missing required keys refuses loudly", ok, msg)

# ---------------------------------------------------------------- extraction (train only)
print("\nextraction — train failures only, no expected text, fail loud on heldout")

exam_cases = [
    {"id": "t1", "split": "train", "input": "alpha beta", "expected": {"answer_contains": ["SECRETVALUE-123456789"]}},
    {"id": "t2", "split": "train", "input": "gamma delta", "expected": {}},
    {"id": "h1", "split": "heldout", "input": "epsilon", "expected": {}},
]
res = [{"id": "t1", "passed": False, "failed_checks": ["check_x: missing tool call"]},
       {"id": "t2", "passed": True, "failed_checks": []}]
lessons = L.extract_lessons(res, exam_cases)
check("one lesson per failing train case, passing cases skipped",
      len(lessons) == 1 and lessons[0]["source_case"] == "t1", repr(lessons))
check("skeleton carries situation=input + what_went_wrong=failed_checks, fix empty",
      lessons[0]["situation"] == "alpha beta"
      and "missing tool call" in lessons[0]["what_went_wrong"]
      and lessons[0]["fix"] == "")
check("no expected text in any extracted field",
      all("SECRETVALUE" not in str(v) for lesson in lessons for v in lesson.values()))
ok, msg = raises(lambda: L.extract_lessons([{"id": "h1", "passed": False}], exam_cases), "train")
check("a heldout id RAISES (never skipped — fail loud)", ok, msg)
ok, msg = raises(lambda: L.extract_lessons([{"id": "nope", "passed": False}], exam_cases), "unknown")
check("an unknown id raises", ok, msg)

# ---------------------------------------------------------------- retrieval (deterministic)
print("\nretrieval — keyword overlap, deterministic order, zero-overlap never injects")

lib = [{"situation": "invoice number missing from summary", "what_went_wrong": "w", "fix": "f"},
       {"situation": "meeting summary drops the invoice date", "what_went_wrong": "w", "fix": "f"},
       {"situation": "unrelated topic entirely about weather", "what_went_wrong": "w", "fix": "f"}]
got = L.retrieve(lib, "the invoice summary is missing a number", k=2)
check("top-k by overlap", len(got) == 2 and got[0] is lib[0] and got[1] is lib[1],
      repr([lesson["situation"] for lesson in got]))
check("retrieval is deterministic across calls",
      L.retrieve(lib, "the invoice summary is missing a number", k=2) == got)
check("zero-overlap lesson never retrieved even with room in k",
      L.retrieve(lib, "completely disjoint text zzz", k=3) == [])
check("render of nothing is the empty string (true no-op)", L.render([]) == "")

tie = [{"situation": "invoice paid", "what_went_wrong": "w", "fix": "f"},
       {"situation": "invoice sent", "what_went_wrong": "w", "fix": "f"}]
check("equal-score tie breaks by library index (total order — gates must reproduce)",
      L.retrieve(tie, "invoice", k=1)[0] is tie[0])
ok, msg = raises(lambda: L.retrieve(tie, "invoice", k=0), ">= 1")
check("k < 1 raises (a negative k would silently slice wrong — fail loud)", ok, msg)

# ---------------------------------------------------------------- injection (real entry point)
print("\ninjection — through run_plain_case with a capturing adapter (gotcha 1)")


class _CapturingAdapter:
    def __init__(self):
        self.messages = None

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        self.messages = messages
        return '{"ok": 1}', {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}


case = {"id": "c", "input": "the invoice summary is missing a number", "expected": {}}
base_agent = {"name": "x", "provider": "ollama", "system_prompt": "STATIC-BLOCK-TEXT"}

ad = _CapturingAdapter()
runner.run_plain_case(base_agent, case, ad, "m")
check("no library -> outgoing system prompt BYTE-IDENTICAL to the static block",
      ad.messages[0]["content"] == "STATIC-BLOCK-TEXT")

lib_agent = dict(base_agent, _lessons=lib, library_k=2)
ad = _CapturingAdapter()
runner.run_plain_case(lib_agent, case, ad, "m")
sysmsg = ad.messages[0]["content"]
check("library ON -> lesson text actually present in the OUTGOING prompt",
      "invoice number missing from summary" in sysmsg)
check("lessons injected AFTER the static block (prefix-cache layout, measured "
      "docs/probes/prefix-cache-2026-09-09/RESULTS.md)",
      # .find, not .index: a missing substring must be a FAIL on this line, never
      # an uncaught ValueError that aborts the file and silently truncates every
      # later check (found by the test-honesty verifier under mutation 3).
      sysmsg.startswith("STATIC-BLOCK-TEXT")
      and sysmsg.find("invoice number") > len("STATIC-BLOCK-TEXT"))
ad = _CapturingAdapter()
runner.run_plain_case(dict(base_agent, _lessons=lib, library_k=2),
                      {"id": "c2", "input": "disjoint zzz", "expected": {}}, ad, "m")
check("library ON but zero-overlap case -> prompt byte-identical (no empty header)",
      ad.messages[0]["content"] == "STATIC-BLOCK-TEXT")

# The turns path is the one that actually broke in this lane's first gate run
# (case["input"] KeyError on a turns-bearing case), so its ON path gets its own
# pin through the REAL score_case, with a real committed multi-turn case.
print("\ninjection — turns path through the real score_case (the site that broke)")


class _TurnsCapturingAdapter:
    def __init__(self):
        self.first_system = None

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        if self.first_system is None:
            self.first_system = messages[0]["content"]
        return ('{"answer": "done"}',
                {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                 "content_chars": 18, "reasoning_chars": 0, "finish_reason": "stop"})


import contextlib  # noqa: E402
import io  # noqa: E402
import importlib.util as _ilu  # noqa: E402

_exam_cases = json.loads((ROOT / "evals" / "crm-followup" / "cases.json").read_text())["cases"]
_turns_case = next(c for c in _exam_cases if "turns" in c)
_spec = _ilu.spec_from_file_location(
    "tools_mock_library_test", ROOT / "evals" / "crm-followup" / "tools_mock.py")
_tools = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_tools)
_deal_lesson = {"situation": "asked what stage the Janssens Bakery deal is in",
                "what_went_wrong": "w", "fix": "f"}
_turns_agent = {"name": "x", "provider": "ollama", "system_prompt": "STATIC-BLOCK-TEXT",
                "_lessons": [_deal_lesson], "library_k": 2}
_tad = _TurnsCapturingAdapter()
with contextlib.redirect_stdout(io.StringIO()):
    runner.score_case(_turns_agent, _turns_case, _tad, "m", _tools)
check("turns case, library ON -> lesson in the outgoing system prompt, static block first",
      _tad.first_system is not None
      and _tad.first_system.startswith("STATIC-BLOCK-TEXT")
      and "Janssens Bakery deal" in _tad.first_system)

# ---------------------------------------------------------------- snapshot pin
print("\nsnapshot pin — payload key omitted-when-absent; preflight isolation (gotcha 3)")

result = {"train": {"score": 1.0}, "heldout": {"score": 1.0},
          "cases": [{"id": "t1", "split": "train", "passed": True}]}
exam = {"cases": [{"id": "t1"}]}
pay = runner.snapshot_payload(dict(base_agent), exam, "ollama", "m", result)
check("no library -> no library_sha key at all (exact-key-set contract preserved)",
      "library_sha" not in pay)
pay2 = runner.snapshot_payload(dict(base_agent, library_sha="abc123"), exam, "ollama", "m", result)
check("with library -> library_sha present and equal to the agent's pin",
      pay2.get("library_sha") == "abc123")

snap_ok = {"provider": "hosted", "runtime": {"version": None},
           "cases": [{"id": "t1"}]}
vfn_bomb = lambda: (_ for _ in ()).throw(AssertionError("network touched"))  # noqa: E731
check("legacy snapshot + no library passes preflight (both None)",
      runner.snapshot_preflight(snap_ok, exam, version_fn=vfn_bomb) is None)
cause = runner.snapshot_preflight(snap_ok, exam, version_fn=vfn_bomb, library_sha="abc123")
check("library added since snapshot -> refused, cause is LIBRARY: and ONLY that "
      "(snapshot passes every other refusal — the gotcha-3 isolation case)",
      cause is not None and cause.startswith("LIBRARY:"), repr(cause))
cause = runner.snapshot_preflight(dict(snap_ok, library_sha="abc123"), exam,
                                  version_fn=vfn_bomb)
check("library removed since snapshot -> refused (asymmetry both directions)",
      cause is not None and cause.startswith("LIBRARY:"), repr(cause))
cause = runner.snapshot_preflight(dict(snap_ok, library_sha="abc123"), exam,
                                  version_fn=vfn_bomb, library_sha="def456")
check("changed hash -> refused", cause is not None and cause.startswith("LIBRARY:"), repr(cause))
check("matching hash passes",
      runner.snapshot_preflight(dict(snap_ok, library_sha="abc123"), exam,
                                version_fn=vfn_bomb, library_sha="abc123") is None)

# ---------------------------------------------------------------- defaults unchanged
print("\nno committed agent turns the library on (gates stay unmoved)")
for ay in sorted((ROOT / "agents").glob("*/agent.yaml")):
    check(f"{ay.parent.name}: no 'library' key in committed config",
          "library" not in ay.read_text())
for name in sorted(p.name for p in (ROOT / "agents").iterdir() if p.is_dir()):
    cfg = runner.load_agent(name)
    check(f"{name}: load_agent adds no library keys without the yaml key",
          "_lessons" not in cfg and "library_sha" not in cfg)

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
    sys.exit(1)
print("all library assertions hold")
