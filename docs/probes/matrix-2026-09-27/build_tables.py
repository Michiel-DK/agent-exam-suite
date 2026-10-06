#!/usr/bin/env python3
"""build_tables.py — per-task tables (one row per model) from the results files of the 27 Sep matrix, the 25–26 Sep
call-fields probe, and the committed local snapshots. Prints markdown. Cost = metered tokens of THAT run x a rate:
the repo-radar ledger where the model has a row, else list_rates.json (OpenRouter list price, dated) — the tag says which.
pass^k column: the local champion row carries pass^3 from its snapshot (cases passed on all 3 loads); every single-pass hosted row
says "1 run" until the three same-day repeats exist. The heading counts the candidates that competed and how many sit within one
case of the best (the tie band) — the selection-bias denominator (pickup note 2 Oct, arXiv 2609.25848).
Deterministic, no inference. Run from the repo root: python3 docs/probes/matrix-2026-09-27/build_tables.py"""
import json, glob, os, csv, collections
DEATHS = {}; exam_ctx = [None]
ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(ROOT, "..", "..", ".."))
LEDGER = os.path.expanduser("~/code/Michiel-DK/repo-radar/data/prices/ledger.tsv")
rates = {r["id"]: (float(r["prompt_per_m"]), float(r["completion_per_m"]), "ledger " + r["date"]) for r in csv.DictReader(open(LEDGER), delimiter="\t")}
for k, v in json.load(open(os.path.join(ROOT, "list_rates.json"))).items():
    rates.setdefault(k, (v["prompt_per_m"], v["completion_per_m"], "list " + v["date"]))
CAN = {"openai/gpt-5.6-sol": "vendor only", "openai/gpt-5.4-mini": "vendor only", "x-ai/grok-4.6": "vendor only",
       "moonshotai/kimi-k3": "own VM, GPU node", "z-ai/glm-5.3": "own VM, GPU node", "deepseek/deepseek-v4-pro-0813": "own VM, GPU node",
       "google/gemma-4-31b-it": "own VM, one 48 GB card", "mistralai/mistral-small-3.2-24b-instruct": "own VM, one 24–48 GB card",
       "openai/gpt-oss-20b": "own VM, one 24 GB card", "google/gemma-4-26b-a4b-it": "own VM, one 24 GB card", "qwen/qwen3-14b": "own VM, one 24 GB card"}
LOCAL = {"transcript-en": "gemma4-e4b-ctx16k", "recap": "gemma4:e4b-it-qat", "email-triage": "gemma4:e2b-it-qat",
         "expense-categorization": "gemma4:e2b-it-qat", "reply-draft": "gemma4:e2b-it-qat", "crm-followup": "gemma4-e2b-ctx16k", "call-fields": "gemma4-e4b-ctx16k"}
ORDER = ["transcript-en", "call-fields", "crm-followup", "recap", "email-triage", "expense-categorization", "reply-draft"]
TITLE = {"transcript-en": "Call summary + action items", "call-fields": "CRM field write-back from a call", "crm-followup": "Account brief over the CRM (tool calls)",
         "recap": "Digest of many items", "email-triage": "Email triage", "expense-categorization": "Expense fields", "reply-draft": "Reply draft"}

def row(d, model_label, can, rate_key, note=""):
    cs = d["cases"]; h = [c for c in cs if c["split"] == "heldout"]
    walls = [c.get("detail", {}).get("metrics", {}).get("wall_ms") for c in cs]; walls = [w for w in walls if w]
    mt = d.get("metrics_totals") or {}
    if not mt:  # a --snapshot run carries per-case metrics only
        pm = [c.get("detail", {}).get("metrics", {}) for c in cs]
        if any(m.get("prompt_tokens") for m in pm):
            mt = {"prompt_tokens": sum(m.get("prompt_tokens", 0) for m in pm), "completion_tokens": sum(m.get("completion_tokens", 0) for m in pm)}
    deaths = collections.Counter()
    for c in cs:
        det = c.get("detail", {})
        if det.get("termination"): deaths[det["termination"].get("cause", "?")] += 1
        elif not c.get("passed") and "metrics" not in det: deaths["no-detail"] += 1
    dead = sum(deaths.values()); DEATHS[(exam_ctx[0], model_label)] = dict(deaths)
    cost = ""
    if rate_key in rates and mt.get("prompt_tokens"):
        p, q, tag = rates[rate_key]; x = (mt['prompt_tokens']*p + mt['completion_tokens']*q)/1e6/len(cs)*1e4; cost = (f"{x:,.2f}" if x < 10 else f"{x:,.0f}") + f" ({tag.split()[0]})"
    elif rate_key == "local": cost = "≈0"
    return dict(model=model_label, can=can, held=sum(1 for c in h if c["passed"]), n=len(h), wall=(sum(walls)/len(walls)/1000 if walls else None),
                out=(mt.get("completion_tokens", 0)/len(cs) if mt else None), dead=dead, cost=cost, note=note)

def load_rows(exam):
    exam_ctx[0] = exam; rows = []
    for f in glob.glob(os.path.join(ROOT, "results", f"{exam}__*.json")):
        d = json.load(open(f)); m = d["model"]; rows.append(row(d, m, CAN.get(m, "?"), m, "unpinned" if m.startswith(("deepseek", "google", "mistralai", "qwen", "openai/gpt-oss")) else "pinned"))
    if exam == "call-fields":
        for f in glob.glob(os.path.join(REPO, "docs/probes/call-fields-2026-09-25/results/hosted-*-2026-09-25*.json")):
            if "-2026-09-25.json" in f and ("glm" in f or "kimi" in f): continue  # 1024-budget first passes superseded by the reruns
            d = json.load(open(f)); m = d["model"]; rows.append(row(d, m, CAN.get(m, "?"), m, "unpinned" if "small" in f else "pinned"))
    # local champion from the committed snapshot + its results file
    snap = os.path.join(REPO, "evals", exam, "snapshot.json")
    if os.path.exists(snap):
        s = json.load(open(snap)); hc = [c for c in s["cases"] if c["split"] == "heldout"]
        rf = os.path.join(REPO, "results", f"{exam}__ollama__{LOCAL[exam].replace(':','_').replace('/','_')}.json")
        wall = out = None
        if os.path.exists(rf):
            d = json.load(open(rf)); mt = d.get("metrics_totals") or {}
            ws = [c.get("detail", {}).get("metrics", {}).get("wall_ms") for c in d["cases"]]; ws = [w for w in ws if w]
            wall = sum(ws)/len(ws)/1000 if ws else None; out = mt.get("completion_tokens", 0)/len(d["cases"]) if mt else None
        p3 = sum(1 for c in hc if c["passed"] and c.get("stable", True))
        r = dict(model=f"{s['model']} (local champion, 3-load snapshot {s['date'][:10]})", can="local machine", held=sum(1 for c in hc if c["passed"]), n=len(hc), wall=wall, out=out, dead=0, cost="≈0", note="snapshot", passk=f"pass^3 {p3}/{len(hc)}")
        if os.path.exists(rf) and r["wall"] is None:
            rr = row(json.load(open(rf)), r["model"], "local machine", "local", "snapshot"); r["wall"], r["out"] = rr["wall"], rr["out"]
        rows.append(r)
    return rows

for exam in ORDER:
    rows = load_rows(exam)
    if not rows: continue
    n = rows[0]["n"]
    best = max(r["held"] for r in rows); band = sum(1 for r in rows if r["held"] >= best - 1)
    print(f"\n### {TITLE[exam]} (`{exam}`, {n} held-out cases; {len(rows)} candidates competed, {band} within one case of the best)\n")
    print("| model | can run on | heldout | pass^k | s/call | out tok/call | died | $/10k (rate) | run |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: (-r["held"], (r["wall"] or 99))):
        pk = r.get("passk", "1 run")
        print(f"| {r['model']} | {r['can']} | **{r['held']}**/{r['n']} | {pk} | {r['wall']:.1f} | {r['out']:.0f} | {r['dead']} | {r['cost']} | {r['note']} |" if r["wall"] is not None else
              f"| {r['model']} | {r['can']} | **{r['held']}**/{r['n']} | {pk} | | | {r['dead']} | {r['cost']} | {r['note']} |")

print("\n### Deaths by recorded cause (arm → {cause: count}); a death is a failed case with no parseable answer\n")
for (exam, m), d in sorted(DEATHS.items()):
    if d: print(f"- `{exam}` {m}: {d}")
