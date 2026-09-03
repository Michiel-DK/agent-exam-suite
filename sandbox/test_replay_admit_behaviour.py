#!/usr/bin/env python3
"""A replay task must grade BEHAVIOUR, not SOURCE TEXT.

WHY THIS EXISTS. `admit.py`'s original and only criterion was red->green
reproduction: the PR's test fails at the base commit and passes at the merge
commit. That is necessary and NOT sufficient, because **172 of mast's 384 unit
tests (45%) assert on source text** — they read the module as a string and check
that certain characters appear in it. A source-text test reproduces red->green
exactly as cleanly as a behaviour test, so the old criterion could not see the
difference.

WHAT THE DIFFERENCE COSTS. A behaviour test asks "did you solve it". A source-text
test asks "did you type these characters somewhere in this file" — satisfiable by
pasting the tokens into dead code, the wrong function, or a comment. An exam built
on those grades transcription and reports it as coding ability. At a 45% base rate,
roughly half the candidate pool carries it, and every indicator stays green: the
corpus builds, the tasks run, the scores look plausible.

This is the same shape as the recap `_exp` hole (evals/test_recap_vacuous_green.py)
one level up: not a check that passes wrongly, but a *corpus* that measures the
wrong thing while every check passes correctly.

NO INFERENCE, NO GIT, NO PYTEST. `grades_source_text` is a pure function of a
file's text, so every assertion here is deterministic and runs in milliseconds.
"""
import inspect as _inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox" / "replay"))
import admit as A  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


# --- fixtures, shaped like mast's real tests ------------------------------------

BEHAVIOUR_TEST = '''
import pytest
from api.query import build_user_query

def test_builds_scoped_query():
    sql = build_user_query(user_id=5, scope="active")
    assert sql == "SELECT * FROM users WHERE id = 5 AND status = 'active'"

def test_rejects_missing_id():
    with pytest.raises(ValueError):
        build_user_query(user_id=None, scope="active")
'''

READ_TEXT_TEST = '''
from pathlib import Path

def test_rollback_is_called_on_failure():
    src = Path("api/models.py").read_text()
    assert "db.rollback()" in src
'''

GETSOURCE_TEST = '''
import inspect
from api import models

def test_handler_guards_the_cluster_flag():
    src = inspect.getsource(models.sync_handler)
    assert "is_primary_in_cluster" in src
'''

REPO_ROOT_TEST = '''
from tests.conftest import REPO_ROOT

def test_migration_declares_the_index():
    body = (REPO_ROOT / "migrations" / "0042_add_index.py").read_text()
    assert "CREATE INDEX" in body
'''

MIXED_TEST = BEHAVIOUR_TEST + READ_TEXT_TEST   # one bad test in an otherwise good file


print("== source-text tests are REJECTED, each pattern on its own ==")

for name, src, want_reason in (
    ("read_text()", READ_TEXT_TEST, "reads the module as text"),
    ("inspect.getsource", GETSOURCE_TEST, "inspects source via inspect.getsource"),
    ("REPO_ROOT", REPO_ROOT_TEST, "resolves files through REPO_ROOT to read them"),
):
    is_src, why = A.grades_source_text(src)
    check(f"{name} is detected as source-text", is_src)
    check(f"{name} names its reason", want_reason in why, f"got {why}")


print()
print("== behaviour tests are ADMITTED (the filter must not reject everything) ==")

is_src, why = A.grades_source_text(BEHAVIOUR_TEST)
check("a pure behaviour test is NOT flagged", not is_src, f"flagged for {why}")
check("and reports no reasons", why == [], f"got {why}")

# The degenerate over-strict filter — `return True, [...]` — would pass every
# rejection assertion above. This pair is what makes those assertions mean something.
check("filter discriminates rather than rejecting everything",
      A.grades_source_text(BEHAVIOUR_TEST)[0] is False
      and A.grades_source_text(READ_TEXT_TEST)[0] is True)


print()
print("== a MIXED file is dropped whole (false drops are the cheap direction) ==")

is_src, _ = A.grades_source_text(MIXED_TEST)
check("a file with good tests AND one source-text test is still flagged", is_src,
      "a mixed file must be dropped whole and overridden by hand if wanted")


print()
print("== the override list is a human claim, not a volume dial ==")

check("overrides exist and are documented", all(
    isinstance(v, str) and len(v.strip()) > 20
    for v in A.SOURCE_TEXT_OVERRIDES.values()),
    f"got {A.SOURCE_TEXT_OVERRIDES}")
check("#1043 is the audited override", 1043 in A.SOURCE_TEXT_OVERRIDES)
# An override list that grows silently is how a corpus gets poisoned politely.
check("the override list stays small (<=3); growing it is a reviewed decision",
      len(A.SOURCE_TEXT_OVERRIDES) <= 3, f"{len(A.SOURCE_TEXT_OVERRIDES)} overrides")


print()
print("== structural: admissibility actually GATES on it ==")

# The RED demonstration for this file is: delete the `and not is_src` term from
# probe() and this assertion fails while every behavioural assertion above still
# passes — because those test the detector, and this tests that the detector is WIRED.
# Presence is not effect: a perfect detector nobody consults changes nothing.
probe_src = _inspect.getsource(A.probe)
check("probe() consults grades_source_text", "grades_source_text(" in probe_src)
check("probe() gates `admissible` on it, not merely records it",
      "and not is_src" in probe_src, "detector present but not wired into admissible")
check("probe() records WHY a task was dropped", '"source_text_reasons"' in probe_src)


print()
print("== create tasks: shape classification (2026-08-15) ==")

check("path -> module: plain file",
      A.module_name("mast/utils/social_url.py") == "mast.utils.social_url")
check("path -> module: package __init__",
      A.module_name("mast/newpkg/__init__.py") == "mast.newpkg")
check("no added files -> modify",
      A.classify_shape(["a.py", "b.py"], []) == "modify")
check("all files added -> create",
      A.classify_shape(["a.py", "b.py"], ["a.py", "b.py"]) == "create")
check("some added, some modified -> mixed (dropped, not represented)",
      A.classify_shape(["a.py", "b.py"], ["a.py"]) == "mixed")


print()
print("== create tasks: the RED must name a module THIS PR adds ==")

TAIL = "ERROR ... ModuleNotFoundError: No module named 'mast.utils.social_url'"

ok, why = A.valid_create_red(2, TAIL, ["mast/utils/social_url.py"])
check("collection error naming the added module is a valid create red", ok, why)
check("and the verdict names the module", "mast.utils.social_url" in why)

ok, _ = A.valid_create_red(2, TAIL, ["mast/utils/social.py"])
check("SIBLING-PREFIX module must NOT claim the error "
      "(social.py vs social_url — substring match admitted this before "
      "the boundary fix, caught by hand-building this exact input)",
      not ok, "substring matching is back")

ok, _ = A.valid_create_red(
    2, "ModuleNotFoundError: No module named 'mast.newpkg.helper'",
    ["mast/newpkg/__init__.py"])
check("missing SUBmodule of an added package is still this PR's module", ok)

ok, _ = A.valid_create_red(2, "ModuleNotFoundError: No module named 'lxml'",
                           ["mast/utils/social_url.py"])
check("a collection error about an UNRELATED module stays a drop", not ok,
      "missing third-party dep would be graded as a create task")

ok, _ = A.valid_create_red(1, "assert failed", ["mast/utils/social_url.py"])
check("an ordinary test failure (rc=1) is not a create red", not ok)


print()
print("== structural: the create path actually GATES admissible ==")

# RED demonstration: replace `red_ok` with `rc_red in (1, 2)` in probe()'s
# admissible line and these fail while every pure-function check above passes.
probe_src = _inspect.getsource(A.probe)
check("probe() classifies the task shape", "classify_shape(" in probe_src)
check("probe() validates create reds through valid_create_red",
      "valid_create_red(" in probe_src)
check("probe() gates admissible on the validated red, not the raw rc",
      '"admissible"] = red_ok' in probe_src,
      "red validation present but not wired into admissible")
check("mixed shape can never produce a valid red",
      "mixed create+modify shape" in probe_src)


print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
    sys.exit(1)
print("all replay-admissibility invariants hold")
