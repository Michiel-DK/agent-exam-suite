"""Where the replay harness keeps its working state.

Everything the harness generates -- the clone of the corpus repo, the venv that
reproduces its CI, and the intermediate JSON -- lives OUTSIDE the repo under
$REPLAY_WORK. None of it is committed: the clone is 35 MB of someone else's
history and the venv is machine-specific. What IS committed is this code plus
the result JSON under docs/e-corpus-results/.

Override any of these per run:

    REPLAY_WORK    working dir            (default: ~/.cache/agent-sandbox-replay)
    REPLAY_REPO    the corpus clone       (default: $REPLAY_WORK/mast)
    REPLAY_PY      python that runs the   (default: $REPLAY_WORK/venv/bin/python)
                   corpus's own tests
    MAX_TOKENS     model output budget    (default: 4000 -- raise it for long
                                           answers, see docs/e-corpus-probe)
"""
from __future__ import annotations

import os

WORK = os.path.abspath(os.environ.get(
    "REPLAY_WORK", os.path.expanduser("~/.cache/agent-sandbox-replay")))
REPO = os.path.abspath(os.environ.get("REPLAY_REPO", os.path.join(WORK, "mast")))
PY = os.path.abspath(os.environ.get(
    "REPLAY_PY", os.path.join(WORK, "venv", "bin", "python")))

# The agent-sandbox checkout this file lives in -- used to import sandbox.router
# so model calls go through the repo's REAL adapter (rule A4), never a
# hand-rolled HTTP call that could drift from what the tool actually does.
SANDBOX = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env the corpus's own CI sets. `mast`'s unit-tests job runs with a dummy key;
# reproducing it exactly is what makes a local red->green pair mean anything.
TEST_ENV = {**os.environ, "GOOGLE_API_KEY": "dummy", "PYTHONDONTWRITEBYTECODE": "1"}


def artifact(name: str) -> str:
    """Path for a generated intermediate (candidates.json, tasks.json, ...)."""
    os.makedirs(WORK, exist_ok=True)
    return os.path.join(WORK, name)


def require_corpus() -> None:
    """Fail loud and actionable when the corpus/venv aren't set up yet.

    A missing clone must never look like 'no admissible tasks' -- that is the
    silent-empty-result failure this harness exists to avoid.
    """
    missing = [p for p in (REPO, PY) if not os.path.exists(p)]
    if missing:
        raise SystemExit(
            f"replay corpus not set up: missing {missing}\n"
            f"See sandbox/replay/README.md -- clone the corpus to {REPO} and build "
            f"a venv matching its CI at {os.path.dirname(os.path.dirname(PY))}.")
