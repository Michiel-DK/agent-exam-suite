"""Invariants of the replay harness's parse -> apply path.

This is the part that can be WRONG WHILE GREEN: if `parse_blocks` silently drops
a function or `apply_blocks` splices to the wrong line range, every downstream
score is garbage and the gating test just reports a failure that the model did
not cause. The oracle check (sandbox/replay/oracle.py) catches that end-to-end
but needs a 35 MB clone and a venv; these run in milliseconds with neither.

Method is the repo's standing one: build the degenerate/hostile MODEL OUTPUT by
hand and assert the harness rejects or handles it -- never assert only that the
happy path works. Run: python3 sandbox/test_replay_splice.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "replay"))
import attempt as A  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        FAILS.append(name)


def test_parse() -> None:
    print("parse_blocks")
    two = ("### FUNCTION: alpha\n```python\ndef alpha():\n    return 1\n```\n"
           "### FUNCTION: beta\n```python\ndef beta():\n    return 2\n```")
    got = A.parse_blocks(two, ["alpha", "beta"])
    check("both functions recovered", set(got) == {"alpha", "beta"})
    check("body kept verbatim", got["alpha"].strip() == "def alpha():\n    return 1")

    # A model that answers only half the request must NOT look complete -- this
    # is what gemma4 did on PR #1008 at a 4000-token cap.
    half = A.parse_blocks("### FUNCTION: alpha\n```python\ndef alpha():\n    return 1\n```",
                          ["alpha", "beta"])
    check("partial answer stays partial (s2 must fail)", set(half) != {"alpha", "beta"})

    # Pure reasoning, no answer -- qwen3:8b's actual failure mode. Must yield
    # nothing rather than a plausible-looking empty block.
    check("thinking-only reply yields no blocks",
          A.parse_blocks("Okay, let me think about how the SQL should work...",
                         ["alpha"]) == {})

    # Bare block accepted ONLY when exactly one function was requested; with two
    # requested it is ambiguous and must not be guessed at.
    check("bare block ok for single-function ask",
          set(A.parse_blocks("```python\ndef alpha():\n    return 1\n```", ["alpha"])) == {"alpha"})
    check("bare block NOT guessed for multi-function ask",
          A.parse_blocks("```python\ndef alpha():\n    return 1\n```", ["alpha", "beta"]) == {})

    # A model inventing a function nobody asked for must be discarded, not applied.
    check("unrequested function discarded",
          A.parse_blocks("### FUNCTION: evil\n```python\ndef evil():\n    pass\n```",
                         ["alpha"]) == {})


def test_apply() -> None:
    print("apply_blocks")
    original = ["import os", "", "def alpha():", "    return 1", "", "def beta():",
                "    return 2", "", "TRAILER = 3"]
    with tempfile.TemporaryDirectory() as d:
        path = "mod.py"
        full = os.path.join(d, path)
        with open(full, "w") as fh:
            fh.write("\n".join(original) + "\n")

        task = {"functions": [{"path": path, "func": "alpha", "lo": 3, "hi": 4},
                              {"path": path, "func": "beta", "lo": 6, "hi": 7}],
                "src_files": [path]}
        real_repo, A.REPO = A.REPO, d
        try:
            # Replacement bodies differ in LENGTH -- the case where splicing
            # low-to-high would corrupt the second range.
            A.apply_blocks(task, {"alpha": "def alpha():\n    x = 10\n    return x",
                                  "beta": "def beta():\n    return 99"})
            with open(full) as fh:
                out = fh.read().splitlines()
        finally:
            A.REPO = real_repo

    check("surrounding code untouched (head)", out[0] == "import os")
    check("surrounding code untouched (tail)", out[-1] == "TRAILER = 3")
    check("alpha replaced", "    x = 10" in out and "    return 1" not in out)
    check("beta replaced at the right range despite alpha growing",
          "    return 99" in out and "    return 2" not in out)
    check("file still parses", __import__("ast").parse("\n".join(out)) is not None)


def test_parse_files() -> None:
    print("parse_file_blocks (create tasks, 2026-08-15)")
    two = ("### FILE: mast/utils/a.py\n```python\nA = 1\n```\n"
           "### FILE: mast/utils/b.py\n```python\nB = 2\n```")
    got = A.parse_file_blocks(two, ["mast/utils/a.py", "mast/utils/b.py"])
    check("both files recovered", set(got) == {"mast/utils/a.py", "mast/utils/b.py"})
    check("file body kept verbatim", got["mast/utils/a.py"].strip() == "A = 1")

    # THE hostile input: a model choosing its own write location. The task
    # record is the only authority on paths — anything else is dropped at parse.
    check("path traversal is dropped, not written",
          A.parse_file_blocks("### FILE: ../../evil.py\n```python\nX = 1\n```",
                              ["mast/utils/a.py"]) == {})
    check("an unrequested but plausible path is dropped",
          A.parse_file_blocks("### FILE: mast/utils/other.py\n```python\nX = 1\n```",
                              ["mast/utils/a.py"]) == {})

    check("partial answer stays partial (s2 must fail)",
          set(A.parse_file_blocks("### FILE: mast/utils/a.py\n```python\nA = 1\n```",
                                  ["mast/utils/a.py", "mast/utils/b.py"]))
          != {"mast/utils/a.py", "mast/utils/b.py"})
    check("thinking-only reply yields no files",
          A.parse_file_blocks("Let me think about the module layout...",
                              ["mast/utils/a.py"]) == {})
    check("bare block ok for single-file ask",
          set(A.parse_file_blocks("```python\nA = 1\n```", ["mast/utils/a.py"]))
          == {"mast/utils/a.py"})
    check("bare block NOT guessed for multi-file ask",
          A.parse_file_blocks("```python\nA = 1\n```",
                              ["mast/utils/a.py", "mast/utils/b.py"]) == {})

    # A file whose DOCSTRING contains its own ```python fence. A non-greedy
    # single-regex parser truncates this at the INNER fence and the loss
    # surfaces downstream as a compile/test failure blamed on the model —
    # a misleading-result path, review-found, seen RED before the fix.
    inner = ("### FILE: mast/utils/a.py\n```python\n"
             '"""Example:\n```python\nfrom mast.utils.a import go\n```\n"""\n'
             "def go():\n    return 1\n```")
    got = A.parse_file_blocks(inner, ["mast/utils/a.py"])
    check("a file containing its own code fence is captured WHOLE",
          "def go():" in got.get("mast/utils/a.py", ""))


def test_apply_files() -> None:
    print("apply_files (create tasks)")
    with tempfile.TemporaryDirectory() as d:
        task = {"new_files": [{"path": "mast/newpkg/mod.py", "merged_chars": 10}]}
        real_repo, A.REPO = A.REPO, d
        try:
            wrote = A.apply_files(task, {"mast/newpkg/mod.py": "X = 41\n"})
            with open(os.path.join(d, "mast/newpkg/mod.py")) as fh:
                body = fh.read()
            # Defence in depth: even if a hostile path somehow survived parsing,
            # apply iterates the TASK's paths, never the model's keys.
            A.apply_files(task, {"../evil.py": "X = 666\n"})
            evil = os.path.exists(os.path.join(os.path.dirname(d), "evil.py"))
            # And the third gate: a hostile TASK RECORD itself (review-found
            # gap — containment was caller-discipline, not structure).
            try:
                A.apply_files({"new_files": [{"path": "../evil2.py"}]},
                              {"../evil2.py": "X = 1\n"})
                raised = False
            except SystemExit:
                raised = True
            evil2 = os.path.join(os.path.dirname(d), "evil2.py")
            outside = os.path.exists(evil2)
            if outside:
                os.remove(evil2)
        finally:
            A.REPO = real_repo

    check("file created at the task-record path, dirs included", body == "X = 41\n")
    # (a True here would mean apply_files wrote a path the task never declared)
    check("a block keyed outside the task record is never written", not evil)
    check("a hostile TASK RECORD path raises and never writes outside the clone",
          raised and not outside)
    check("nothing written -> False is reported, not silent success",
          not A.apply_files({"new_files": [{"path": "mast/x.py"}]}, {}))


if __name__ == "__main__":
    test_parse()
    test_apply()
    test_parse_files()
    test_apply_files()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("\nall replay splice invariants hold")
