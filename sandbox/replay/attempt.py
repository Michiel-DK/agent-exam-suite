"""The floor-saturation falsifier: can the best LOCAL model pass a real CI test?

Grading is STAGED, never binary -- a bare 0/3 is an aggregate with no cause, and
those route differently: died-at-generation (context/format) says "fix the
harness", died-at-semantics says "needs a bigger model".

  s1_responded   model returned text at all
  s2_parsed      a code block was recovered for every function asked for
  s3_compiles    the patched file parses as Python
  s4_target      the PR's own gating test passes
  s5_no_regress  the rest of tests/unit still passes

Model calls go through the repo's real sandbox/router.py adapter (rule A4:
measure through the real entry point), not a hand-rolled HTTP call.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

from paths import (PY, REPO, SANDBOX, TEST_ENV as ENV, artifact,  # noqa: E402
                   require_corpus)

sys.path.insert(0, SANDBOX)
from sandbox.router import get_adapter  # noqa: E402

SYSTEM = (
    "You are a senior Python engineer. You fix code so that a given failing test "
    "passes. You reply with code only: for each function you were asked to change, "
    "emit a line '### FUNCTION: <name>' followed by a ```python fenced block "
    "containing the COMPLETE rewritten function, correctly indented at module "
    "level. No explanation, no prose, no other text."
)

SYSTEM_CREATE = (
    "You are a senior Python engineer. You write new modules so that a given "
    "failing test passes. You reply with code only: for each file you were asked "
    "to create, emit a line '### FILE: <path>' (the exact path you were given) "
    "followed by a ```python fenced block containing the COMPLETE file contents. "
    "No explanation, no prose, no other text."
)


def build_prompt(task: dict) -> str:
    parts = [
        f"# Task\n{task['title']}\n",
        f"## Description\n{task['body'].strip()}\n" if task["body"].strip() else "",
        "## The failing test (it must pass after your change)\n"
        f"File: `{task['test_file']}`\n```python\n{task['test_src']}\n```\n",
        "## The current code you must change\n",
    ]
    for p in task["functions"]:
        parts.append(f"From `{p['path']}`:\n```python\n{p['text']}\n```\n")
    names = ", ".join(p["func"] for p in task["functions"])
    parts.append(
        f"## Your job\nRewrite {names} so the test above passes. "
        "Reply with '### FUNCTION: <name>' + a ```python block per function, nothing else."
    )
    return "".join(parts)


def build_prompt_create(task: dict) -> str:
    paths = ", ".join(f"`{f['path']}`" for f in task["new_files"])
    parts = [
        f"# Task\n{task['title']}\n",
        f"## Description\n{task['body'].strip()}\n" if task["body"].strip() else "",
        "## The failing test (it must pass after your change)\n"
        f"File: `{task['test_file']}`\n```python\n{task['test_src']}\n```\n",
        f"## Your job\nThe module(s) under test do not exist yet. Create "
        f"{paths} so the test above passes. Reply with '### FILE: <path>' + a "
        "```python block per file, nothing else.",
    ]
    return "".join(parts)


BLOCK_RE = re.compile(
    r"###\s*FUNCTION:\s*(\w+).*?```(?:python)?\s*\n(.*?)```", re.S | re.I)

FILE_HEADER_RE = re.compile(r"###\s*FILE:\s*`?([\w./-]+)`?", re.I)
# GREEDY body capture, per header segment: a whole FILE often contains its own
# ```python example in a docstring, and a non-greedy match truncates it at the
# inner fence — the loss then reads as a model failure (review-found). The last
# fence in the segment is the closing one.
FENCE_BODY_RE = re.compile(r"```(?:python)?\s*\n(.*)```", re.S)


def parse_file_blocks(text: str, wanted: list[str]) -> dict[str, str]:
    """Only paths the TASK RECORD asked for are kept — the model's output can
    never choose a write location, so a hallucinated '### FILE: ../../evil.py'
    is dropped here, not caught later."""
    parts = FILE_HEADER_RE.split(text)
    found = {}
    for i in range(1, len(parts), 2):
        m = FENCE_BODY_RE.search(parts[i + 1])
        if m:
            found[parts[i]] = m.group(1)
    # Fallback: a single file asked for and a single bare code block given.
    if not found and len(wanted) == 1:
        m = FENCE_BODY_RE.search(text)
        if m:
            found = {wanted[0]: m.group(1)}
    return {k: v for k, v in found.items() if k in wanted}


def parse_blocks(text: str, wanted: list[str]) -> dict[str, str]:
    found = {name: body for name, body in BLOCK_RE.findall(text)}
    # Fallback: a single function asked for and a single bare code block given.
    if not found and len(wanted) == 1:
        m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
        if m:
            found = {wanted[0]: m.group(1)}
    return {k: v for k, v in found.items() if k in wanted}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def pytest(target: str, timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(
            [PY, "-m", "pytest", target, "-q", "--tb=line", "-p", "no:cacheprovider"],
            cwd=REPO, capture_output=True, text=True, env=ENV, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-800:]
    except subprocess.TimeoutExpired:
        return -9, "TIMEOUT"


def apply_blocks(task: dict, blocks: dict[str, str]) -> bool:
    """Splice each returned function back over its original line range.

    Applied high-to-low per file so earlier splices don't shift later ranges.
    """
    by_file: dict[str, list] = {}
    for p in task["functions"]:
        if p["func"] in blocks:
            by_file.setdefault(p["path"], []).append((p["lo"], p["hi"], blocks[p["func"]]))
    for path, edits in by_file.items():
        full = os.path.join(REPO, path)
        with open(full) as fh:
            lines = fh.read().splitlines()
        for lo, hi, new in sorted(edits, key=lambda e: -e[0]):
            lines[lo - 1:hi] = new.rstrip("\n").splitlines()
        with open(full, "w") as fh:
            fh.write("\n".join(lines) + "\n")
    return bool(by_file)


def apply_files(task: dict, blocks: dict[str, str]) -> bool:
    """Write each returned FILE at its task-record path. The whitelist is the
    task record, enforced twice: parse_file_blocks already dropped anything
    not asked for, and this iterates task['new_files'], never blocks' keys."""
    wrote = False
    for f in task["new_files"]:
        path = f["path"]
        if path not in blocks:
            continue
        full = os.path.join(REPO, path)
        # Structural containment, not caller discipline: even a hostile TASK
        # RECORD cannot write outside the corpus clone (review-found gap).
        if not os.path.normpath(full).startswith(os.path.normpath(REPO) + os.sep):
            raise SystemExit(f"apply_files: path escapes the corpus clone: {path!r}")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(blocks[path].rstrip("\n") + "\n")
        wrote = True
    return wrote


def run_task(task: dict, model: str, provider: str, timeout: int,
             max_tokens: int) -> dict:
    create = task.get("type") == "create"
    r = {"pr": task["pr"], "model": model, "type": task.get("type", "modify"),
         "prompt_chars": task["prompt_chars"],
         "s1_responded": False, "s2_parsed": False, "s3_compiles": False,
         "s4_target": False, "s5_no_regress": None}
    prompt = build_prompt_create(task) if create else build_prompt(task)
    r["prompt_sent_chars"] = len(prompt)

    adapter = get_adapter(provider, timeout=timeout)
    t0 = time.time()
    try:
        text, meta = adapter.generate(
            [{"role": "system", "content": SYSTEM_CREATE if create else SYSTEM},
             {"role": "user", "content": prompt}],
            model=model, temperature=0.0, max_tokens=max_tokens)
    except Exception as exc:                                  # noqa: BLE001
        r["error"] = f"{type(exc).__name__}: {exc}"[:300]
        r["wall_s"] = round(time.time() - t0, 1)
        return r
    r["wall_s"] = round(time.time() - t0, 1)
    r["usage"] = meta
    r["reply_chars"] = len(text or "")
    r["reply_head"] = (text or "")[:600]
    if not (text or "").strip():
        return r
    r["s1_responded"] = True

    if create:
        wanted = [f["path"] for f in task["new_files"]]
        blocks = parse_file_blocks(text, wanted)
    else:
        wanted = [p["func"] for p in task["functions"]]
        blocks = parse_blocks(text, wanted)
    r["funcs_wanted"] = wanted
    r["funcs_parsed"] = list(blocks)
    if set(blocks) != set(wanted):
        return r
    r["s2_parsed"] = True

    # --- apply at the base commit, with the PR's test file grafted in -------
    git("checkout", "-f", "master"); git("clean", "-fdq")
    git("checkout", "-f", task["base"])
    git("checkout", task["merge"], "--", task["test_file"])
    (apply_files if create else apply_blocks)(task, blocks)

    for path in task["src_files"]:
        p = subprocess.run([PY, "-m", "py_compile", os.path.join(REPO, path)],
                           capture_output=True, text=True, env=ENV)
        if p.returncode != 0:
            r["compile_err"] = p.stderr[-400:]
            git("checkout", "-f", "master"); git("clean", "-fdq")
            return r
    r["s3_compiles"] = True

    rc, tail = pytest(task["test_file"], timeout=300)
    r["target_rc"], r["target_tail"] = rc, tail[-400:]
    r["s4_target"] = rc == 0

    if r["s4_target"]:
        rc2, tail2 = pytest("tests/unit/", timeout=900)
        r["regress_rc"], r["regress_tail"] = rc2, tail2[-400:]
        r["s5_no_regress"] = rc2 == 0

    git("checkout", "-f", "master"); git("clean", "-fdq")
    return r


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen3:8b"
    prs = [int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else "973,941,937".split(","))]
    tag = sys.argv[3] if len(sys.argv) > 3 else "run"
    require_corpus()
    tasks = {t["pr"]: t for t in json.load(open(artifact("tasks.json")))}
    out = []
    for pr in prs:
        print(f"--- PR #{pr} with {model}", flush=True)
        # max_tokens is deliberately generous: qwen3 spends most of its budget
        # thinking (87-97% on this box), so a tight cap would cut the answer off
        # and score deliberation as incapacity.
        r = run_task(tasks[pr], model, "ollama", timeout=2400,
                     max_tokens=int(os.environ.get("MAX_TOKENS", "4000")))
        stages = [k for k in ("s1_responded", "s2_parsed", "s3_compiles", "s4_target")
                  if r.get(k)]
        print(f"    {r.get('wall_s')}s reached: {stages[-1] if stages else 'NOTHING'}"
              f"  err={r.get('error','-')}", flush=True)
        out.append(r)
    path = artifact(f"attempts_{tag}.json")
    json.dump(out, open(path, "w"), indent=2)
    n = sum(1 for r in out if r["s4_target"])
    print(f"\n=== {model}: {n}/{len(out)} passed the original gating test ===")


if __name__ == "__main__":
    main()
