#!/usr/bin/env python3
"""Scoreboard from committed snapshots.

Reads evals/<agent>/snapshot.json (heldout_score, model, date) and
evals/<agent>/cases.json (split counts, exam mode) and emits the README
scoreboard table on stdout, plus docs/img/heldout-by-agent.png.
The README table is pasted from this output, never typed.

    python3 scripts/scoreboard.py            # table + png
    python3 scripts/scoreboard.py --no-png   # table only (no matplotlib needed)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
PNG = ROOT / "docs" / "img" / "heldout-by-agent.png"

# Exam mode when cases.json does not carry one (email-triage predates the field).
MODE_FALLBACK = {"email-triage": "labels"}

# Hand-written context per agent; everything numeric comes from the files.
NOTES = {
    "reply-draft": "saturated, useless for ranking",
    "crm-followup": "production-size payloads; 4 multi-turn cases; champion swapped 4B to 2B (PR #60)",
    "recap": "the hardest exam, on purpose",
    "transcript-en": "English call transcripts incl. a 10-case long-call band (12k-33k chars); local 4B ties Kimi-K3 2/6 on it",
    "task-intake": "seventh agent: routes a typed request to the right specialist, or refuses",
}


def load():
    rows = []
    for d in sorted(EVALS.iterdir()):
        snap, cases = d / "snapshot.json", d / "cases.json"
        if not (snap.exists() and cases.exists()):
            continue
        s = json.loads(snap.read_text())
        c = json.loads(cases.read_text())
        heldout = [x for x in s["cases"] if x["split"] == "heldout"]
        passed = sum(1 for x in heldout if x["passed"])
        rows.append({
            "agent": d.name,
            "mode": c.get("mode") or MODE_FALLBACK.get(d.name, "?"),
            "model": s["model"],
            "score": s["heldout_score"],
            "passed": passed,
            "n": len(heldout),
            "date": s["date"][:10],
            "note": NOTES.get(d.name, ""),
        })
    rows.sort(key=lambda r: -r["score"])
    return rows


def table(rows):
    out = ["| agent | exam mode | champion | held-out | snapshot date | note |", "|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['agent']} | {r['mode']} | {r['model']} | {r['score']:.3f} ({r['passed']}/{r['n']}) | {r['date']} | {r['note']} |")
    return "\n".join(out)


def png(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    latest = max(r["date"] for r in rows)
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    names = [r["agent"] for r in rows][::-1]
    scores = [r["score"] for r in rows][::-1]
    labels = [f"{r['score']:.2f}  ({r['passed']}/{r['n']})" for r in rows][::-1]
    bars = ax.barh(names, scores, color="#2b8a7e")
    for b, lab in zip(bars, labels):
        ax.text(b.get_width() + 0.01, b.get_y() + b.get_height() / 2, lab, va="center", fontsize=8)
    ax.set_xlim(0, 1.18)
    ax.set_xlabel("held-out score of the committed champion")
    ax.set_title(f"Held-out score per agent (snapshots up to {latest}; a 1.00 is a broken exam)", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(PNG)


if __name__ == "__main__":
    rows = load()
    print(table(rows))
    if "--no-png" not in sys.argv:
        png(rows)
        print(f"\nwrote {PNG.relative_to(ROOT)}", file=sys.stderr)
