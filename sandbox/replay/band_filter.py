"""Apply the CHEAP filter (behaviour-not-source-text) to all candidates first.

grades_source_text() is a pure function of the test file's text — no git checkout,
no pytest. Running it before the expensive red->green probe shrinks the sweep set,
and it produces the number that matters most: how much of the corpus is graded on
behaviour at all (52% of 261 survived on 2026-08-14, near the documented 45%
source-text base rate).

Reads $REPLAY_WORK/candidates.json (from build_candidates.py), writes
$REPLAY_WORK/candidates_behaviour.json. Band-select from that and stage the
survivors as candidates.json before running admit.py.
"""
from __future__ import annotations

import json
import os
import subprocess

import paths
from admit import SOURCE_TEXT_OVERRIDES, grades_source_text


def main() -> None:
    if not os.path.isdir(os.path.join(paths.REPO, ".git")):
        raise SystemExit(
            f"replay corpus not set up: {paths.REPO} is not a git clone.\n"
            "See sandbox/replay/README.md step 0.")
    cands = json.load(open(paths.artifact("candidates.json")))
    kept, dropped = [], []
    for c in cands:
        p = subprocess.run(["git", "show", f"{c['merge']}:{c['test_file']}"],
                           cwd=paths.REPO, capture_output=True, text=True)
        if p.returncode != 0:
            dropped.append((c, ["test file not readable at merge commit"]))
            continue
        is_src, why = grades_source_text(p.stdout)
        if is_src and c["pr"] in SOURCE_TEXT_OVERRIDES:
            is_src = False
        (dropped if is_src else kept).append((c, why))

    out = paths.artifact("candidates_behaviour.json")
    json.dump([c for c, _ in kept], open(out, "w"), indent=1)
    print(f"{len(kept)}/{len(cands)} grade BEHAVIOUR "
          f"({len(dropped)} grade source text)  -> {out}")
    bands = {"tiny <20": 0, "small 20-79": 0, "medium 80-199": 0, "LONG >=200": 0}
    for c, _ in kept:
        n = c["lines"]
        k = ("tiny <20" if n < 20 else "small 20-79" if n < 80
             else "medium 80-199" if n < 200 else "LONG >=200")
        bands[k] += 1
    print("surviving bands:", bands)


if __name__ == "__main__":
    main()
