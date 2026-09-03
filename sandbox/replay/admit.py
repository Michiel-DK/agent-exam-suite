"""Admissibility probe for the E-CORPUS replay exam.

A merged PR is an admissible replay TASK only if its own gating test reproduces
locally as a red->green pair:

    base commit  + the PR's test file   -> test FAILS   (RED)
    merge commit                        -> test PASSES  (GREEN)

If that pair does not reproduce, the PR is dropped, not debugged: a task whose
test cannot fail at base cannot grade a model attempt, and a 0/3 from such a
harness would be indistinguishable from model incapacity.

SECOND CRITERION: THE TEST MUST GRADE BEHAVIOUR, NOT SOURCE TEXT
----------------------------------------------------------------
red->green reproduction is necessary and NOT sufficient. **172 of mast's 384 unit
tests (45%) assert on source text** — they `read_text()` the module and check that
a string appears in it, rather than calling the function and checking what it
returns. Both kinds reproduce red->green identically, so the criterion above
cannot tell them apart.

The difference decides what the exam measures. A behaviour test asks "did you
solve it"; a source-text test asks "did you type these characters somewhere in
this file", which a model can satisfy by pasting the tokens in the wrong place,
in dead code, or in a comment. An exam built on those grades transcription and
reports it as coding ability — a silent vacuous green at corpus scale, and at a
45% base rate roughly half the candidate pool carries it.

Bias is deliberately toward FALSE DROPS: a wrongly-dropped PR costs one candidate
out of hundreds, a wrongly-admitted one silently corrupts every score computed
from it. A file mixing both kinds is dropped whole; override explicitly below
after reading the test, as #1043 was.

THIRD SHAPE: NEW-MODULE (CREATE) TASKS — added 2026-08-15
---------------------------------------------------------
The 2026-08-14 sweep found the hard band dominated by PRs that CREATE a module:
64 of 76 drops failed RED with a collection error because the module under test
does not exist at base. That is not a broken red — for a create task it is the
CORRECT red. A candidate is admissible as a `create` task iff:

    - every source file the PR touches is ADDED at the merge commit
      (`git diff --diff-filter=A`), and
    - the RED collection error NAMES a module this PR adds (any other
      collection error — missing third-party dep, broken test file — still
      grades nothing and stays a drop), and
    - green + behaviour criteria hold unchanged.

PRs that both create and modify source files are `mixed` — counted and dropped,
not represented, this pass.

Read-only w.r.t. the operator's working copies: operates on its own clone under
$REPLAY_WORK. Never check out old commits in a tree another session may be using.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

from paths import PY, REPO, TEST_ENV as ENV, artifact, require_corpus

# The measured signature of mast's source-text tests (docs/e-corpus-probe-2026-08-01.md:
# 172/384 match). Kept to exactly these three rather than a cleverer heuristic — they
# are what was counted, so they are what can be claimed.
_SOURCE_TEXT_PATTERNS = (
    (r"\.read_text\s*\(", "reads the module as text"),
    (r"\binspect\.getsource\b", "inspects source via inspect.getsource"),
    (r"\bREPO_ROOT\b", "resolves files through REPO_ROOT to read them"),
)

# PRs admitted despite a match, each after reading the test by hand. A number here is
# a claim that a human checked it — never add one to make a sweep produce more tasks.
SOURCE_TEXT_OVERRIDES: dict[int, str] = {
    # 1043 was audited separately: it calls the builder and asserts on the SQL it
    # RETURNS, which for a SQL builder is behaviour. It matches on an unrelated line.
    1043: "audited 2026-08-01 — asserts on returned SQL, not on file contents",
}


def grades_source_text(test_source: str) -> tuple[bool, list[str]]:
    """Does this test file grade source TEXT rather than BEHAVIOUR?

    Pure function of the file's contents: no git, no pytest, no network — so it is
    testable deterministically and cheap to run over a whole corpus.

    Returns (is_source_text, reasons). Matches inside comments and docstrings count:
    over-matching costs a candidate, under-matching corrupts the corpus.
    """
    hits = []
    for pattern, why in _SOURCE_TEXT_PATTERNS:
        if re.search(pattern, test_source):
            hits.append(why)
    return bool(hits), hits


def module_name(path: str) -> str:
    """mast/utils/social_url.py -> mast.utils.social_url  (packages too:
    mast/utils/__init__.py -> mast.utils). Pure function."""
    p = path[:-3] if path.endswith(".py") else path
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    return p.replace("/", ".")


def classify_shape(src_files: list[str], added_src: list[str]) -> str:
    """'create' = every touched source file is new at merge; 'modify' = none is;
    'mixed' = some of each (dropped, not represented). Pure function."""
    if not added_src:
        return "modify"
    if set(added_src) >= set(src_files):
        return "create"
    return "mixed"


def valid_create_red(red_rc: int, red_tail: str,
                     added_src: list[str]) -> tuple[bool, str]:
    """Is this RED the right red for a create task? Pure function.

    rc=2 is a pytest collection error. It is only meaningful here when the
    error NAMES a module this PR adds — a collection error about anything else
    (missing third-party dep, syntax error in the test) grades nothing about
    the change and must stay a drop.
    """
    if red_rc != 2:
        return False, f"red_rc={red_rc}; a create red is a collection error (rc=2)"
    # Boundary-anchored, not substring: added `mast/utils/social.py` must NOT
    # claim an error naming `mast.utils.social_url`. A trailing `.` is allowed
    # (a missing submodule of an added package is still this PR's module).
    named = [f for f in added_src
             if re.search(r"(?<![\w.])" + re.escape(module_name(f)) + r"(?!\w)",
                          red_tail)]
    if not named:
        return False, "collection error does not name any module this PR adds"
    return True, f"missing module is PR-added: {module_name(named[0])}"


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def pytest(test_path: str, timeout: int = 300) -> tuple[int, str]:
    p = subprocess.run(
        [PY, "-m", "pytest", test_path, "-q", "--tb=line", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, env=ENV, timeout=timeout,
    )
    return p.returncode, (p.stdout + p.stderr)[-1500:]


def reset() -> None:
    git("checkout", "-f", "master")
    git("clean", "-fdq")


def probe(num: int, merge_sha: str, test_file: str, src_files: list[str]) -> dict:
    out = {"pr": num, "test_file": test_file, "src_files": src_files,
           "merge": merge_sha, "admissible": False}
    reset()
    base = git("rev-parse", f"{merge_sha}^1").stdout.strip()
    out["base"] = base

    # --- task shape: which of the PR's source files are NEW at merge? -------
    added = git("diff", "--diff-filter=A", "--name-only", base, merge_sha,
                "--", *src_files)
    added_src = [f for f in added.stdout.splitlines() if f.strip()]
    out["added_src"] = added_src
    out["task_type"] = classify_shape(src_files, added_src)

    # --- RED: base commit, PR's test file grafted in -----------------------
    r = git("checkout", "-f", base)
    if r.returncode != 0:
        out["error"] = f"checkout base failed: {r.stderr[:200]}"
        reset()
        return out
    r = git("checkout", merge_sha, "--", test_file)
    if r.returncode != 0:
        out["error"] = f"graft test failed: {r.stderr[:200]}"
        reset()
        return out
    try:
        rc_red, tail_red = pytest(test_file)
    except subprocess.TimeoutExpired:
        rc_red, tail_red = -9, "TIMEOUT"
    out["red_rc"] = rc_red
    out["red_tail"] = tail_red[-400:]

    # --- GREEN: the merge commit as it shipped -----------------------------
    reset()
    r = git("checkout", "-f", merge_sha)
    if r.returncode != 0:
        out["error"] = f"checkout merge failed: {r.stderr[:200]}"
        reset()
        return out
    try:
        rc_green, tail_green = pytest(test_file)
    except subprocess.TimeoutExpired:
        rc_green, tail_green = -9, "TIMEOUT"
    out["green_rc"] = rc_green
    out["green_tail"] = tail_green[-400:]
    reset()

    # rc 1 = tests ran and failed (the useful RED for a MODIFY task). rc 2/3/4
    # = collection or usage error — for a MODIFY task that grades nothing; for
    # a CREATE task rc=2 is the correct red IFF the error names a module this
    # PR adds (checked against the full 1500-char tail, not the stored 400).
    out["red_is_test_failure"] = rc_red == 1
    if out["task_type"] == "create":
        red_ok, red_why = valid_create_red(rc_red, tail_red, added_src)
    elif out["task_type"] == "modify":
        red_ok, red_why = rc_red == 1, "modify red must be a test failure (rc=1)"
    else:
        red_ok, red_why = False, "mixed create+modify shape — not represented"
    out["red_valid"], out["red_verdict"] = red_ok, red_why

    # --- BEHAVIOUR, not source text ----------------------------------------
    # Read the test as it shipped at the merge commit — the same text the graft
    # above put at base, so this judges the file that actually grades the model.
    shipped = git("show", f"{merge_sha}:{test_file}")
    if shipped.returncode != 0:
        out["error"] = f"could not read test file at merge: {shipped.stderr[:200]}"
        out["admissible"] = False
        return out
    is_src, why = grades_source_text(shipped.stdout)
    out["grades_source_text"] = is_src
    out["source_text_reasons"] = why
    if is_src and num in SOURCE_TEXT_OVERRIDES:
        out["source_text_override"] = SOURCE_TEXT_OVERRIDES[num]
        is_src = False

    out["admissible"] = red_ok and rc_green == 0 and not is_src
    return out


def main() -> None:
    require_corpus()
    cands = json.load(open(artifact("candidates.json")))
    results = []
    for c in cands:
        print(f"--- PR #{c['pr']} {c['test_file']}", flush=True)
        r = probe(c["pr"], c["merge"], c["test_file"], c["src_files"])
        verdict = (f"ADMISSIBLE ({r.get('task_type')})" if r["admissible"]
                   else f"dropped ({r.get('task_type', '?')})")
        note = ""
        if r.get("grades_source_text"):
            note = ("  [SOURCE-TEXT: " + "; ".join(r["source_text_reasons"]) + "]"
                    + (f" OVERRIDDEN: {r['source_text_override']}"
                       if r.get("source_text_override") else ""))
        print(f"    red_rc={r.get('red_rc')} green_rc={r.get('green_rc')} -> {verdict}{note}",
              flush=True)
        results.append(r)
    json.dump(results, open(artifact("admit_results.json"), "w"), indent=2)
    n = sum(1 for r in results if r["admissible"])
    # Report drops per cause AND admissions per shape: "12/40 admissible" hides
    # whether the rest failed to reproduce or were rejected for grading the
    # wrong thing, and those numbers mean opposite things about the corpus.
    by_type = {}
    for r in results:
        if r["admissible"]:
            t = r.get("task_type", "modify")
            by_type[t] = by_type.get(t, 0) + 1
    src = sum(1 for r in results if r.get("grades_source_text")
              and not r.get("source_text_override"))
    mixed = sum(1 for r in results if r.get("task_type") == "mixed")
    bad_red = sum(1 for r in results
                  if not r.get("red_valid") and r.get("task_type") != "mixed")
    print(f"\n{n}/{len(results)} admissible {by_type} "
          f"({bad_red} invalid red, {mixed} mixed shape, "
          f"{src} graded source text not behaviour)")


if __name__ == "__main__":
    sys.exit(main())
