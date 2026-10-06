#!/usr/bin/env python3
"""pass_k.py — consistency as pass^k, from files on disk. No inference.
Local champions: evals/<exam>/snapshot.json (3 fresh loads; a case is `stable` iff all loads agree) → pass^3 = held-out cases
passed on all 3 loads = passed AND stable. Hosted GLM-5.3 / Kimi K3: the 1 Sep pin day's six runs (3 pinned reps + 3 unpinned
reps, docs/probes/provider-pin-day1-2026-09-01/results/D) → pass^3 over the pinned reps, pass^3 over the unpinned, pass^6 over
all six. ⚠️ The pin day ran the 1 Sep case sets (transcript-en 22, crm 24 cases); those rows compare only with their own
single-run score, never with the 27 Sep matrix (bigger sets). Candidates = models per table in the 27 Sep matrix tables.md.
Run from the repo root: python3 docs/probes/pass3-column-2026-09-28/pass_k.py"""
import json, os, glob, re
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
ORDER = ["transcript-en", "call-fields", "crm-followup", "recap", "email-triage", "expense-categorization", "reply-draft", "task-intake"]
def held(cases): return [c for c in cases if c.get("split") == "heldout"]
print("## Local champions — pass^3 from the committed 3-load snapshots\n")
print("| exam | model | runtime | held-out n | single-run (held-out) | pass^3 | unstable cases |")
print("|---|---|---|---|---|---|---|")
for e in ORDER:
    p = os.path.join(REPO, "evals", e, "snapshot.json")
    if not os.path.exists(p): continue
    s = json.load(open(p)); h = held(s["cases"])
    single = sum(1 for c in h if c["passed"]); p3 = sum(1 for c in h if c["passed"] and c.get("stable", True))
    unst = [c["id"] for c in s["cases"] if not c.get("stable", True)]
    rt = s.get("runtime") or {}
    print(f"| {e} | {s['model']} | {rt.get('name','?')} {rt.get('version','?')} | {len(h)} | {single}/{len(h)} | **{p3}**/{len(h)} | {len(unst)}" + (": " + ", ".join(unst) if unst else "") + " |")
print("\n## Hosted — pass^k from the 1 Sep pin day (six runs; 1 Sep case sets)\n")
print("| exam | model | held-out n (1 Sep set) | single run (pinned rep1) | pass^3 pinned | pass^3 unpinned | pass^6 all | cases flipping across the six |")
print("|---|---|---|---|---|---|---|---|")
D = os.path.join(REPO, "docs/probes/provider-pin-day1-2026-09-01/results/D")
for e in ["transcript-en", "crm-followup", "recap", "email-triage", "expense-categorization", "reply-draft"]:
    for m in ["z-ai_glm-5.3", "moonshotai_kimi-k3"]:
        runs = {}
        for arm in ["pinned", "unpinned"]:
            for r in (1, 2, 3):
                f = os.path.join(D, f"{arm}_rep{r}", f"{e}__{m}.json")
                if os.path.exists(f): runs[(arm, r)] = {c["id"]: c["passed"] for c in held(json.load(open(f))["cases"])}
        if len(runs) < 6: print(f"| {e} | {m} | — | — | — | — | — | only {len(runs)} of 6 runs on disk |"); continue
        ids = sorted(set.intersection(*[set(v) for v in runs.values()])); n = len(ids)
        single = sum(runs[("pinned", 1)][i] for i in ids)
        p3p = sum(all(runs[("pinned", r)][i] for r in (1, 2, 3)) for i in ids)
        p3u = sum(all(runs[("unpinned", r)][i] for r in (1, 2, 3)) for i in ids)
        p6 = sum(all(v[i] for v in runs.values()) for i in ids)
        flip = [i for i in ids if len({v[i] for v in runs.values()}) > 1]
        print(f"| {e} | {m.replace('_','/')} | {n} | {single}/{n} | {p3p}/{n} | {p3u}/{n} | **{p6}**/{n} | {len(flip)}" + (": " + ", ".join(flip) if flip else "") + " |")
print("\n## Candidates per table (27 Sep matrix + call-fields) — the selection-bias denominator\n")
print("| exam | held-out n | candidates that competed | one case = | tie band (best or one case below) |")
print("|---|---|---|---|---|")
tbl = open(os.path.join(REPO, "docs/probes/matrix-2026-09-27/tables.md")).read()
for blk in tbl.split("\n### ")[1:]:
    m = re.search(r"\(`([a-z-]+)`, (\d+) held-out cases\)", blk)
    if not m: continue
    rows = [l for l in blk.splitlines() if l.startswith("| ") and not l.startswith("| model") and "/" in l.split("|")[3]]
    scores = sorted((int(re.search(r"\*\*(\d+)\*\*", l).group(1)) for l in rows), reverse=True)
    n = int(m.group(2)); band = sum(1 for s in scores if s >= scores[0] - 1)
    print(f"| {m.group(1)} | {n} | {len(rows)} | {100/n:.1f} pts | {band} of {len(rows)} models |")
