"""Build candidates.json over the FULL corpus — the selection step of the funnel.

The rest of the harness (admit.py onward) READS candidates.json; until 2026-08-15
the code that produced it was never committed, so the 2026-08-14 sweep
(`docs/e-corpus-sweep-2026-08-14.md`) could not be reproduced from a clean clone.
This is that code, verbatim in logic from the sweep, with paths going through
paths.py instead of hardcoded cache locations.

Selection criteria (deliberately wider than the 2026-08-01 250-PR slice):
  - every merged PR, straight from GitHub
  - <= MAX_SRC source files (was 2) and >= 1 unit-test file (was exactly 1)

Records added-source-lines per candidate so the LONG-FUNCTION band — the only
band the probe found discriminating — can be selected downstream instead of
guessed at.

Read-only against the corpus clone. Never run against a working checkout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import paths

OUT = paths.artifact("candidates.json")
MAX_SRC = 3
TEST_DIR = "tests/unit/"


def require_repo() -> None:
    """A missing clone must fail loud, never look like an empty corpus."""
    if not os.path.isdir(os.path.join(paths.REPO, ".git")):
        raise SystemExit(
            f"replay corpus not set up: {paths.REPO} is not a git clone.\n"
            "See sandbox/replay/README.md step 0.")


def git(*args: str) -> str:
    """Fail LOUD on any git error: a swallowed failure here either drops a PR
    from the funnel uncounted or misfiles it into the tiny band with lines=0 —
    a misleading result, not a crash, on exactly the machines this script
    exists to support."""
    p = subprocess.run(["git", *args], cwd=paths.REPO,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed (rc={p.returncode}) in "
                         f"{paths.REPO}:\n{p.stderr[:400]}")
    return p.stdout


def in_clone(sha: str) -> bool:
    """A PR merged upstream AFTER the clone was taken has a merge commit the
    clone lacks. That is a property of the frozen corpus, not an error — count
    it and skip, never abort on it and never drop it silently."""
    p = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                       cwd=paths.REPO, capture_output=True, text=True)
    return p.returncode == 0


def merged_prs() -> list[dict]:
    """PR number -> merge commit, straight from GitHub. The history mixes squash
    styles (some subjects carry '(#N)', some don't), so parsing messages would
    silently drop the older half of the corpus.

    ⚠️ This is a LIVE query, not pinned to a date or ref: byte-identical
    reproduction of a past sweep holds only while no further PR has merged in
    the corpus repo since that sweep. Needs the `gh` CLI, authenticated."""
    try:
        p = subprocess.run(
            ["gh", "pr", "list", "--repo", "Michiel-DK/mast", "--state",
             "merged", "--limit", "3000",
             "--json", "number,mergeCommit,title"],
            capture_output=True, text=True, cwd=paths.REPO, timeout=300)
    except FileNotFoundError:
        raise SystemExit("`gh` CLI not installed — selection queries GitHub "
                         "for the merged-PR list. See sandbox/replay/README.md "
                         "step 0.")
    except subprocess.TimeoutExpired:
        raise SystemExit("`gh pr list` timed out after 300s — network stall, "
                         "not an empty corpus.")
    if p.returncode != 0:
        sys.exit(f"gh failed: {p.stderr[:400]}")
    return json.loads(p.stdout)


def main() -> None:
    require_repo()
    prs = merged_prs()
    print(f"merged PRs from GitHub: {len(prs)}")

    cands, stats = [], {"no_merge_sha": 0, "merge_not_in_clone": 0,
                        "no_unit_test": 0, "too_many_src": 0, "no_src": 0}
    for pr in prs:
        mc = (pr.get("mergeCommit") or {}).get("oid")
        if not mc:
            stats["no_merge_sha"] += 1
            continue
        if not in_clone(mc):
            stats["merge_not_in_clone"] += 1
            continue
        files = [f for f in git("diff-tree", "--no-commit-id", "--name-only",
                                "-r", mc).splitlines() if f.strip()]
        if not files:
            continue
        tests = [f for f in files if f.startswith(TEST_DIR) and f.endswith(".py")]
        src = [f for f in files
               if f.endswith(".py") and not f.startswith("tests/")]
        if not tests:
            stats["no_unit_test"] += 1
            continue
        if not src:
            stats["no_src"] += 1
            continue
        if len(src) > MAX_SRC:
            stats["too_many_src"] += 1
            continue

        # diff size, for banding downstream (the easy band is ceiling-saturated)
        numstat = git("diff", "--numstat", f"{mc}^1", mc, "--", *src)
        added = sum(int(l.split("\t")[0]) for l in numstat.splitlines()
                    if l.split("\t")[0].isdigit())
        cands.append({"pr": pr["number"], "merge": mc, "test_file": tests[0],
                      "all_test_files": tests, "src_files": src,
                      "title": pr["title"], "lines": added})

    cands.sort(key=lambda c: c["lines"])
    json.dump(cands, open(OUT, "w"), indent=1)
    print(f"candidates: {len(cands)}  -> {OUT}")
    print(f"dropped: {stats}")
    bands = {"tiny <20": 0, "small 20-79": 0, "medium 80-199": 0, "LONG >=200": 0}
    for c in cands:
        n = c["lines"]
        k = ("tiny <20" if n < 20 else "small 20-79" if n < 80
             else "medium 80-199" if n < 200 else "LONG >=200")
        bands[k] += 1
    print("added-source-lines bands:", bands)


if __name__ == "__main__":
    main()
