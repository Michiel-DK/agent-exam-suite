#!/usr/bin/env python3
"""Filter a scratch copy's evals/transcript-en/cases.json down to ONLY the
longcall-* cases, so a scorecard run against a hosted model (Kimi) costs
~10 calls instead of ~32 -- the same technique
docs/probes/transcript-long-step0-2026-09-06/probe_setup.py used, applied to
a git-archive scratch copy (never the real worktree's cases.json) so the
committed exam is never at risk of being clobbered by a scorecard run.
"""
import json
import sys
from pathlib import Path

cases_path = Path(sys.argv[1])
data = json.loads(cases_path.read_text())
longcall = [c for c in data["cases"] if c["id"].startswith("longcall-")]
assert len(longcall) >= 10, f"expected >=10 longcall- cases, got {len(longcall)}"
data["cases"] = longcall
cases_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
print(f"{cases_path}: filtered to {len(longcall)} longcall-* cases")
