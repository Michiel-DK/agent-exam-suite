"""E6-train — the lesson library: extract from TRAIN failures, retrieve by keyword
overlap, render for injection AFTER the agent's static prompt block.

Brief: docs/e6-train-brief-2026-09-09.md. Boundary rules this module enforces, both
from the E6 spec (docs/experiments.md) and the brief:

1. LESSONS NEVER CARRY EXPECTED-ANSWER TEXT. A lesson quoting a case's `expected`
   block is the answer key with extra steps (the transcript-long owner-check
   precedent: an answer key scored 5/5 until made inert). `validate_library` raises
   on any lesson sharing a >=MIN_LEAK_CHARS normalized substring with any expected
   field of the same agent's cases — train AND heldout, because a heldout expected
   in a prompt is the worse leak. The validator READS heldout expectations to check
   absence; nothing it reads enters any prompt (measuring-side read, like a check).
2. EXTRACTION REFUSES NON-TRAIN CASES. `extract_lessons` raises on a heldout case
   id rather than skipping it — fail loud, never vacuous (repo convention).
3. DETERMINISM. Retrieval is pure string arithmetic with a total order
   (score desc, then library index asc). Same inputs, same lessons, every load —
   a gate whose prompt varies is not a gate.

Injection layout is a MEASURED constraint, not folklore: lessons go AFTER the static
block because a varying prefix costs ~+4.7 s/call (~60% of wall) at a 2k-token prompt
(docs/probes/prefix-cache-2026-09-09/RESULTS.md, Ollama 0.33.2).
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

# A leaked expected-substring shorter than this is more likely a shared English
# phrase than the answer key; 15 normalized chars is the shortest string that
# reliably identified an expected block in this repo's cases when the guard was
# built (and the guard test pins one real leak at exactly this scale, seen RED).
MIN_LEAK_CHARS = 15

# Keyword retrieval: words this short/common carry no signal between a case input
# and a lesson situation. Deliberately tiny — retrieval "starts dumb" (brief);
# an embedding retriever is a v2, not a tuning knob for this lane.
_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i in is it its of on or that "
    "the this to was were will with you your".split())

_REQUIRED_LESSON_KEYS = ("situation", "what_went_wrong", "fix")


def _norm(text: str) -> str:
    """NFKC + lower-case + collapse whitespace. NFKC folds compatibility
    lookalikes (fullwidth chars etc.) so a cosmetically-rewritten quote of an
    expected string still trips the leak guard — found by the correctness
    verifier's fullwidth bypass probe. Directional-normalization rule (gotcha 4)
    does not bite here: this helper serves ABSENCE checks (leak guard) and
    similarity only; no presence-grading check may ever share it — aggressive
    normalization makes an absence check STRICTER, which is the safe direction."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", _norm(text))
            if len(t) > 2 and t not in _STOPWORDS}


def _expected_strings(case_expected) -> list:
    """Every string anywhere inside a case's expected block (nested dicts/lists
    included) — the leak guard must see all of it, not just top-level values."""
    out: list = []
    stack = [case_expected]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            stack.extend(v.values())
        elif isinstance(v, (list, tuple)):
            stack.extend(v)
    return out


def library_sha(path: Path) -> str:
    """sha256 of the committed library file's bytes — the pin `snapshot.json`
    carries (E6 spec constraint 2: a library change is a champion change)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_library(path: Path, cases: list) -> list:
    """Read + validate agents/<name>/library.json against the agent's cases.
    Returns the lesson list. Raises (never warns, never skips) on: missing/malformed
    file, a lesson missing a required key, or any expected-text leak. Validation at
    LOAD time means a leaky library can never produce a scored run — not just a
    failing test."""
    data = json.loads(path.read_text())
    lessons = data.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        raise ValueError(f"library {path}: 'lessons' must be a non-empty list")
    for i, lesson in enumerate(lessons):
        if not isinstance(lesson, dict):
            raise ValueError(f"library {path}: lesson {i} is not a dict")
        for key in _REQUIRED_LESSON_KEYS:
            if not isinstance(lesson.get(key), str) or not lesson[key].strip():
                raise ValueError(
                    f"library {path}: lesson {i} missing/empty required key {key!r}")
    validate_library(lessons, cases, source=str(path))
    return lessons


def validate_library(lessons: list, cases: list, source: str = "library") -> None:
    """The leak guard. Raises if any lesson text contains a >=MIN_LEAK_CHARS
    normalized substring of any string in any case's expected block."""
    fragments: list = []  # (case_id, normalized fragment)
    for case in cases:
        for s in _expected_strings(case.get("expected", {})):
            ns = _norm(s)
            if len(ns) >= MIN_LEAK_CHARS:
                fragments.append((case["id"], ns))
    for i, lesson in enumerate(lessons):
        body = _norm(" ".join(lesson[k] for k in _REQUIRED_LESSON_KEYS))
        for cid, frag in fragments:
            # whole-fragment containment AND windowed containment: a lesson
            # quoting the middle of a long expected string must also trip.
            if frag in body or _shares_window(frag, body):
                raise ValueError(
                    f"{source}: lesson {i} contains expected-answer text from case "
                    f"{cid!r} — lessons may describe the failure, never the answer")


def _shares_window(frag: str, body: str) -> bool:
    """Any MIN_LEAK_CHARS-length window of `frag` appearing in `body`.

    Step is 1, not a stride: with a stride of 5 the correctness verifier showed
    9 of 12 minimal 15-char leaks at unaligned offsets pass undetected — a leak
    guard with alignment holes is a guard seen green while asserting little
    (gotcha 2). Cost is fine: fragments × windows × `in` over short lesson
    bodies, all pure string ops at load time, no inference."""
    if len(frag) < MIN_LEAK_CHARS:
        return False
    return any(frag[j:j + MIN_LEAK_CHARS] in body
               for j in range(0, len(frag) - MIN_LEAK_CHARS + 1))


def extract_lessons(result_cases: list, exam_cases: list) -> list:
    """Lesson SKELETONS from failing TRAIN cases of one run's per-case results
    (situation = the case input, what_went_wrong = its failed checks, fix = empty,
    authored by a human at measurement time from the failing OUTPUT — never from
    `expected`). Raises on a non-train case id in `result_cases`: the caller
    filters to train first, and a heldout id reaching this function is a leak in
    the making, not an item to skip."""
    by_id = {c["id"]: c for c in exam_cases}
    lessons: list = []
    for rc in result_cases:
        case = by_id.get(rc["id"])
        if case is None:
            raise ValueError(f"extract_lessons: unknown case id {rc['id']!r}")
        if case.get("split") != "train":
            raise ValueError(
                f"extract_lessons: case {rc['id']!r} is split={case.get('split')!r} "
                f"— lessons source from TRAIN failures only")
        if rc.get("passed"):
            continue
        lessons.append({
            "situation": case["input"],
            "what_went_wrong": "; ".join(rc.get("failed_checks", []) or
                                         rc.get("failures", [])),
            "fix": "",
            "source_case": case["id"],
        })
    return lessons


def retrieve(lessons: list, case_input: str, k: int) -> list:
    """Top-k lessons by keyword overlap with the case input. Deterministic:
    score desc, library index asc. Lessons with zero overlap never inject —
    an irrelevant lesson is pure token cost. k < 1 raises (fail loud — a
    negative k would silently slice from the wrong end; correctness-verifier
    observation, round 2)."""
    if k < 1:
        raise ValueError(f"retrieve: k must be >= 1, got {k}")
    case_toks = _tokens(case_input)
    scored = []
    for i, lesson in enumerate(lessons):
        score = len(case_toks & _tokens(lesson["situation"]))
        if score > 0:
            scored.append((-score, i, lesson))
    scored.sort()
    return [lesson for _, _, lesson in scored[:k]]


def render(lessons: list) -> str:
    """The injected block. Returns '' for no lessons — the caller appends nothing
    and the prompt stays byte-identical (presence-is-not-effect, inverted: absence
    must be a true no-op)."""
    if not lessons:
        return ""
    lines = ["\n\n## Lessons from past failures on similar inputs",
             "Apply these where they fit; they never override the task rules above."]
    for lesson in lessons:
        lines.append(f"- Situation: {lesson['situation'][:300]}\n"
                     f"  What went wrong: {lesson['what_went_wrong']}\n"
                     f"  Fix: {lesson['fix']}")
    return "\n".join(lines)
