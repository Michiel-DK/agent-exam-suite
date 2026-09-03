#!/usr/bin/env python3
"""Release watcher: when a new model appears, re-run every exam and report swaps.

    python3 harness/watcher.py            # detect new Ollama models, exam them, report
    python3 harness/watcher.py --baseline # just record current models as known (no runs)

Detection is against harness/known_models.json (committed). A "new model" is any
installed Ollama chat model not in that file. For each new model, every agent with a
snapshot gets its exam run; the report compares heldout scores against the champion
snapshot. Nothing is auto-swapped — the human approves by editing agent.yaml
(or, later, a scoreboard button). Cron-shaped: run it from launchd/cron nightly
(repo-radar-cron lesson: laptop cron misses when the Mac sleeps — best-effort is fine).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runner import ROOT, load_agent, load_exam, run_exam, save_result  # noqa: E402

KNOWN_PATH = Path(__file__).resolve().parent / "known_models.json"


def installed_chat_models() -> list[str]:
    resp = requests.get("http://localhost:11434/api/tags", timeout=10)
    resp.raise_for_status()
    names = [m["name"] for m in resp.json().get("models", [])]
    return sorted(n for n in names if "embed" not in n.lower())


def known_models() -> set[str]:
    if KNOWN_PATH.exists():
        return set(json.loads(KNOWN_PATH.read_text()))
    return set()


def agents_with_snapshots() -> list[tuple[str, dict]]:
    out = []
    for snap_path in sorted(ROOT.glob("evals/*/snapshot.json")):
        out.append((snap_path.parent.name, json.loads(snap_path.read_text())))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", action="store_true",
                    help="record current models as known without running exams")
    args = ap.parse_args()

    installed = installed_chat_models()
    if args.baseline:
        KNOWN_PATH.write_text(json.dumps(installed, indent=2))
        print(f"baseline: {len(installed)} models recorded -> {KNOWN_PATH.name}")
        return 0

    new = [m for m in installed if m not in known_models()]
    if not new:
        print("no new models")
        return 0

    agents = agents_with_snapshots()
    print(f"new model(s): {', '.join(new)} — running {len(agents)} exam(s) each\n")
    recommendations = []
    for model in new:
        for agent_name, snap in agents:
            agent = load_agent(agent_name)
            exam = load_exam(agent_name)
            print(f"--- {agent_name} on {model} ---")
            result = run_exam(agent, exam, snap["provider"], model)
            save_result(result)
            new_score = result["heldout"]["score"] or 0.0
            old_score = snap["heldout_score"] or 0.0
            verdict = "IMPROVES" if new_score > old_score else \
                      "regresses" if new_score < old_score else "ties"
            line = (f"{agent_name}: {model} heldout {new_score:.0%} vs champion "
                    f"{snap['model']} {old_score:.0%} -> {verdict}")
            print(f"    {line}\n")
            if new_score > old_score:
                recommendations.append(line)

    print("=" * 60)
    if recommendations:
        print("swap candidates (edit agent.yaml to approve):")
        for line in recommendations:
            print(f"  {line}")
    else:
        print("no swaps recommended — champions hold.")
    KNOWN_PATH.write_text(json.dumps(installed, indent=2))
    print(f"known_models.json updated ({len(installed)} models)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
