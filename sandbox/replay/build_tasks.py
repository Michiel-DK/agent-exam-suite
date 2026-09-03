"""Turn admissible PRs into replay TASKS with a deliberately generous spec.

Generosity is a design choice, and it is the reason a zero would be strong:
the model is given the PR title + body, the gating test file verbatim, and the
exact source functions the human touched -- i.e. localisation is handed over,
which the real task never does. If the floor is saturated even here, it is not
saturated because the task was under-specified.

Emits tasks.json: one record per PR with the prompt pieces and the ground truth
needed to grade (test file path, base sha, the functions' original text).

Two task shapes since 2026-08-15 (admit.py classifies):
  modify — rewrite the named functions (the original shape)
  create — write the PR's new module(s) from scratch so its test passes.
           No base source exists, so the record carries the paths to create
           plus the merged file sizes (for scaling MAX_TOKENS); the ground
           truth TEXT stays in git, fetched by oracle.py at grading time.
"""
from __future__ import annotations

import ast
import json
import subprocess

from paths import REPO, artifact, require_corpus


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"git {args[:2]} failed: {p.stderr[:300]}")
    return p.stdout


def fetch_body(pr: int) -> str:
    """candidates.json built by build_candidates.py carries no PR body (kept
    lean, and the selection artifacts are frozen). Fetch it per admissible PR
    only — a handful of gh calls, tolerated to fail into ''. """
    try:
        p = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", "Michiel-DK/mast",
             "--json", "body", "-q", ".body"],
            capture_output=True, text=True, cwd=REPO, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def changed_line_ranges(base: str, merge: str, path: str) -> list[tuple[int, int]]:
    """Line ranges in the BASE file that the real diff touched."""
    diff = git("diff", "-U0", base, merge, "--", path)
    out = []
    for line in diff.splitlines():
        if line.startswith("@@"):
            # @@ -a,b +c,d @@
            old = line.split()[1]           # -a,b
            a, _, b = old[1:].partition(",")
            start = int(a)
            count = int(b) if b else 1
            if count == 0:                  # pure insertion: anchor on the line above
                out.append((start, start + 1))
            else:
                out.append((start, start + count - 1))
    return out


def enclosing_blocks(src: str, ranges: list[tuple[int, int]]) -> list[tuple[str, int, int]]:
    """Top-level def/class blocks in `src` overlapping any changed range."""
    tree = ast.parse(src)
    blocks = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lo = min([node.lineno] + [d.lineno for d in node.decorator_list])
            hi = node.end_lineno
            if any(not (hi < r0 or lo > r1) for r0, r1 in ranges):
                blocks.append((node.name, lo, hi))
    return blocks


def main() -> None:
    require_corpus()
    adm = {r["pr"]: r for r in json.load(open(artifact("admit_results.json")))}
    cands = {c["pr"]: c for c in json.load(open(artifact("candidates.json")))}
    tasks = []
    for pr, a in adm.items():
        if not a["admissible"]:
            continue
        c = cands[pr]
        base, merge = a["base"], a["merge"]
        task_type = a.get("task_type", "modify")
        test_src = git("show", f"{merge}:{c['test_file']}")
        body = (c.get("body") or fetch_body(pr))[:2500]
        rec = {
            "pr": pr, "type": task_type, "title": c["title"], "body": body,
            "base": base, "merge": merge, "test_file": c["test_file"],
            "test_src": test_src, "src_files": c["src_files"],
            "lines_changed": c["lines"],
        }
        if task_type == "create":
            # No base source exists. Ground-truth text stays in git; the record
            # carries the paths and merged sizes so MAX_TOKENS can be scaled
            # per task instead of silently truncating long answers.
            rec["new_files"] = [
                {"path": p, "merged_chars": len(git("show", f"{merge}:{p}"))}
                for p in a["added_src"]]
            rec["functions"] = []
            rec["prompt_chars"] = len(test_src) + len(body)
        else:
            pieces = []
            for path in c["src_files"]:
                base_src = git("show", f"{base}:{path}")
                ranges = changed_line_ranges(base, merge, path)
                lines = base_src.splitlines()
                for name, lo, hi in enclosing_blocks(base_src, ranges):
                    pieces.append({"path": path, "func": name, "lo": lo, "hi": hi,
                                   "text": "\n".join(lines[lo - 1:hi])})
            rec["functions"] = pieces
            rec["prompt_chars"] = (len(test_src) + len(body)
                                   + sum(len(p["text"]) for p in pieces))
        tasks.append(rec)
    tasks.sort(key=lambda t: t["prompt_chars"])
    json.dump(tasks, open(artifact("tasks.json"), "w"), indent=2)
    for t in tasks:
        if t["type"] == "create":
            what = ", ".join(f"{f['path']} ({f['merged_chars']}ch)"
                             for f in t["new_files"])
        else:
            what = ", ".join(f"{p['func']} ({p['hi']-p['lo']+1}L)"
                             for p in t["functions"]) or "NONE"
        print(f"#{t['pr']:>5} {t['type']:<6} prompt~{t['prompt_chars']:>6}ch  {what}")


if __name__ == "__main__":
    main()
