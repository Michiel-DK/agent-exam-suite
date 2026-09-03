"""Oracle check: feed the HUMAN's merged answer through the model's own
parse -> apply -> pytest path and require s4_target == True.

Without this, a 0/3 from `attempt.py` is uninterpretable -- it could be a model
that cannot code or a harness that cannot splice. The oracle answers "can any
answer pass?" using the one answer known to be correct. It is the falsifier's
falsifier, and it must be run BEFORE any model call.

Handles both task shapes: modify (merged functions, spliced) and create
(merged files, written whole — `python3 oracle.py create` runs every create
task in tasks.json). A harness that cannot create a file would score every
model 0 and look exactly like model incapacity; this is the check that says so
first.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attempt as A  # noqa: E402
from paths import artifact, require_corpus  # noqa: E402


def merged_function_text(task: dict, path: str, name: str) -> str | None:
    """The same top-level function, as it looks at the MERGE commit."""
    p = subprocess.run(["git", "show", f"{task['merge']}:{path}"],
                       cwd=A.REPO, capture_output=True, text=True)
    if p.returncode != 0:
        return None
    src = p.stdout
    lines = src.splitlines()
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.name == name:
            lo = min([node.lineno] + [d.lineno for d in node.decorator_list])
            return "\n".join(lines[lo - 1:node.end_lineno])
    return None


def merged_file_text(task: dict, path: str) -> str | None:
    """The whole file as it shipped at the MERGE commit — the known-good
    answer for a create task."""
    p = subprocess.run(["git", "show", f"{task['merge']}:{path}"],
                       cwd=A.REPO, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def perfect_reply(task: dict) -> tuple[str, list[str], list[str]]:
    """(reply text in attempt.py's exact wire format, wanted keys, missing).
    Parsing is exercised too, not bypassed."""
    chunks, missing = [], []
    if task.get("type") == "create":
        wanted = [f["path"] for f in task["new_files"]]
        for path in wanted:
            txt = merged_file_text(task, path)
            if txt is None:
                missing.append(path)
                continue
            chunks.append(f"### FILE: {path}\n```python\n{txt}\n```\n")
    else:
        wanted = [p["func"] for p in task["functions"]]
        for p in task["functions"]:
            txt = merged_function_text(task, p["path"], p["func"])
            if txt is None:
                missing.append(p["func"])
                continue
            chunks.append(f"### FUNCTION: {p['func']}\n```python\n{txt}\n```\n")
    return "\n".join(chunks), wanted, missing


def main() -> None:
    require_corpus()
    all_tasks = json.load(open(artifact("tasks.json")))
    if len(sys.argv) > 1 and sys.argv[1] == "create":
        prs = [t["pr"] for t in all_tasks if t.get("type") == "create"]
        if not prs:
            raise SystemExit("no create tasks in tasks.json — nothing to grade "
                             "is a loud result, not a green one")
    else:
        prs = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1
                                else "973,941,937".split(","))]
    tasks = {t["pr"]: t for t in all_tasks}
    ok = 0
    for pr in prs:
        t = tasks[pr]
        create = t.get("type") == "create"
        reply, wanted, missing = perfect_reply(t)
        if missing:
            print(f"#{pr}: GROUND TRUTH VANISHED AT MERGE {missing} -> inadmissible")
            continue

        parse = A.parse_file_blocks if create else A.parse_blocks
        blocks = parse(reply, wanted)
        parsed = set(blocks) == set(wanted)

        A.git("checkout", "-f", "master"); A.git("clean", "-fdq")
        A.git("checkout", "-f", t["base"])
        A.git("checkout", t["merge"], "--", t["test_file"])
        (A.apply_files if create else A.apply_blocks)(t, blocks)
        rc, tail = A.pytest(t["test_file"], timeout=300)
        A.git("checkout", "-f", "master"); A.git("clean", "-fdq")

        verdict = "ORACLE GREEN" if rc == 0 else f"ORACLE RED (rc={rc})"
        print(f"#{pr} ({t.get('type', 'modify')}): parsed={parsed} "
              f"target_rc={rc} -> {verdict}", flush=True)
        if rc != 0:
            print(f"    {tail[-300:]}")
        ok += rc == 0
    print(f"\n{ok}/{len(prs)} tasks are gradeable end-to-end by the harness")


if __name__ == "__main__":
    main()
