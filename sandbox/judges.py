"""LLM-as-judge: grade qualitative agent output against a rubric.

Wired in when evals/<agent>/rubric.md exists. The exam's cases.json must then declare
which model judges, e.g. {"judge": {"provider": "ollama", "model": "llama3.1:latest"}}.
Pattern from mast/mast/agents/_claim_auditor.py (structured verdicts, downstream gate)
and mast/matching/reranker.py — including its circularity caveat: the judge is NEVER
the model under test (CLAUDE.md golden principle). load_judge REFUSES the collision —
it used to only warn, which meant a `diff` sweep listing the judge model as a
candidate silently self-judged inside a run that looked normal (J3, 2026-07-22).

The judge is the only eval type that can lie to you. Spot-check its verdicts against
your own judgment for the first runs of any new rubric.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from retry import call_with_retry, extract_json  # noqa: E402
from router import TerminationError, get_adapter  # noqa: E402

_JUDGE_PROMPT = """You are a strict, impartial quality judge. You will receive the TASK
an assistant was given, the assistant's OUTPUT, and a RUBRIC of criteria.

Judge the OUTPUT against each criterion independently. Fail a criterion only for a
CLEAR violation — not for stylistic nitpicks, hypothetical concerns, or things the
output "could be seen as". When in doubt, the criterion passes.

Respond with ONLY a JSON object, no other text:
{"criteria": [{"name": "<short criterion name>", "pass": true|false, "reason": "<one sentence>"}]}

Include exactly one entry per rubric criterion, in order."""


def _parse_rubric(text: str) -> list[str]:
    return [line.lstrip("-* ").strip() for line in text.splitlines()
            if line.strip().startswith(("-", "*"))]


def load_judge(agent_name: str, exam: dict, run_model: str, root: Path):
    """Returns judge(input_text, output: dict) -> (ok, failures) or None if no rubric."""
    rubric_path = root / "evals" / agent_name / "rubric.md"
    if not rubric_path.exists():
        return None
    cfg = exam.get("judge")
    if not cfg or "model" not in cfg:
        sys.exit(f"error: {rubric_path} exists but cases.json has no "
                 f'"judge": {{"provider": ..., "model": ...}} config')
    criteria = _parse_rubric(rubric_path.read_text())
    if not criteria:
        sys.exit(f"error: {rubric_path} contains no '-' bullet criteria")
    if cfg["model"] == run_model:
        # Refuse, never warn: a self-judged score is not an unreliable score, it is
        # not a score. A warning was invisible inside `diff` output and the run
        # completed with a normal-looking number (J3).
        sys.exit(f"error: exam {agent_name!r}: judge model == model under test "
                 f"({run_model!r}) — 'the judge is never the model under test' "
                 f"(CLAUDE.md). Declare a different judge in "
                 f"evals/{agent_name}/cases.json, or drop {run_model!r} from the "
                 f"candidate list.")
    adapter = get_adapter(cfg.get("provider", "ollama"))
    judge_model = cfg["model"]
    rubric_block = "\n".join(f"- {c}" for c in criteria)

    def judge(input_text: str, output: dict) -> tuple[bool, list[str]]:
        messages = [
            {"role": "system", "content": _JUDGE_PROMPT},
            {"role": "user", "content":
                f"TASK:\n{input_text}\n\nOUTPUT:\n"
                f"{json.dumps(output, ensure_ascii=False)}\n\nRUBRIC:\n{rubric_block}"},
        ]
        try:
            # Judge tokens/latency are fixed infra cost, not part of the model-under-
            # test's metrics — scoped out of the diff table's tokens/latency columns
            # so a rubric change can't be mistaken for the candidate getting slower.
            verdict, _raw, _meta, _retries = call_with_retry(
                lambda: adapter.generate(messages, judge_model,
                                         temperature=0.0, max_tokens=2048),
                extract_json)
            entries = verdict.get("criteria", [])
        except TerminationError as exc:
            # TERMINATION-DETECT: the JUDGE emitted no answer. Caught HERE, and
            # deliberately reported in the judge's own vocabulary rather than the
            # model-under-test's.
            #
            # Without this clause the exception escapes into run_exam's case boundary,
            # which would record `{"bucket": "termination"}` plus
            # detail["termination"] — attributing the JUDGE's failure to terminate to
            # the CANDIDATE, and overwriting the candidate's real detail. That is a
            # fabricated measurement of the wrong model, and it is precisely the
            # misattribution this lane exists to remove.
            #
            # A judge that emitted nothing is a judge that produced no verdict, which
            # is the same class of event as one that produced garbage — so it folds
            # into the existing "judge unparseable" string, which _judge_check_id
            # already maps and taxonomy.py already classifies.
            #
            # ⚠️ UNREACHABLE TODAY, and that is verified, not assumed: no
            # evals/*/rubric.md exists anywhere in the repo (checked 2026-08-27), so
            # load_judge returns None for every agent and this whole module is dormant.
            # It is mirrored now because the boundary is two lines and a future rubric
            # would otherwise reintroduce the exact bug in a place nobody is looking.
            return False, [f"judge unparseable: emitted no answer ({exc.details})"]
        except (ValueError, TypeError) as exc:
            # An unparseable judge is a failed check, loudly (scorecard.js pattern) —
            # never silently skipped.
            return False, [f"judge unparseable: {exc}"]
        failures = [f"judge:{e.get('name', '?')}: {e.get('reason', '')}"
                    for e in entries if not e.get("pass")]
        if len(entries) != len(criteria):
            failures.append(f"judge returned {len(entries)} verdicts "
                            f"for {len(criteria)} criteria")
        return not failures, failures

    return judge
