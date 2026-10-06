#!/usr/bin/env python3
"""build.py — L3: the modelled own-GPU cost column for the movable tier. One line per (task, model) from repo-radar's
scripts/cost_per_10k.py --gpu (the ONLY source of a dollar figure), pasted verbatim into the table. Deterministic, no inference.
Inputs: the 27 Sep matrix results + the 25 Sep call-fields hosted results (hosted-API wall_ms per case), the card the tiers doc's
CAN map names for the model, and data/prices/gpu-hours.tsv (hand-dated, source URL per row).
Run from the agent-sandbox root: python3 docs/probes/l3-own-gpu-cost-2026-10-02/build.py"""
import glob, os, subprocess, json, re
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SCRIPT = os.path.expanduser("~/code/Michiel-DK/repo-radar/scripts/cost_per_10k.py")
# tiers doc §1 (hand-maintained CAN map in build_tables.py): which card class the weights need
CARD = {"google/gemma-4-26b-a4b-it": "24", "openai/gpt-oss-20b": "24", "qwen/qwen3-14b": "24",
        "mistralai/mistral-small-3.2-24b-instruct": "24", "google/gemma-4-31b-it": "48"}
CARDS = {"24": ["runpod/l4-secure", "scaleway/l4-1-24g"], "48": ["runpod/l40s-secure", "scaleway/l40s-1-48g"]}
ORDER = ["transcript-en", "call-fields", "crm-followup", "recap", "email-triage", "expense-categorization", "reply-draft"]
files = {}
for f in glob.glob(os.path.join(REPO, "docs/probes/matrix-2026-09-27/results/*.json")):
    files.setdefault(os.path.basename(f).split("__")[0], []).append(f)
for f in glob.glob(os.path.join(REPO, "docs/probes/call-fields-2026-09-25/results/hosted-*-small.json")):
    files.setdefault("call-fields", []).append(f)
lines = []
print("| task | model | heldout | hosted $/10k (ledger, from tables.md) | card | hosted wall s/call | own card, cheapest datacenter (RunPod secure) | own card, EU (Scaleway Paris) | tasks per card-month, serial |")
print("|---|---|---|---|---|---|---|---|---|")
hosted = {}
for blk in re.split(r"\n### ", open(os.path.join(REPO, "docs/probes/matrix-2026-09-27/tables.md")).read()):
    m = re.search(r"\(`([a-z-]+)`", blk)
    if not m: continue
    for row in blk.splitlines():
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) >= 7 and cells[0] in CARD: hosted[(m.group(1), cells[0])] = (cells[2], cells[6])
for exam in ORDER:
    for f in sorted(files.get(exam, [])):
        d = json.load(open(f)); m = d["model"]
        if m not in CARD: continue
        out = subprocess.run(["python3", SCRIPT, "--gpu", ",".join(CARDS[CARD[m]]), "--volumes", f], capture_output=True, text=True, check=True).stdout.strip().splitlines()
        lines.append((exam, m, out))
        us, eu = out[1], out[2]
        g = lambda s: re.search(r"(\$|€)([\d,]+\.\d\d) per 10k", s).group(0).replace(" per 10k", "")
        wall_s = re.search(r"([\d.]+) s/call", us).group(1); pm = re.search(r"([\d,]+) tasks per card-month", us).group(1)
        card = re.search(r"on (.+?) \(", us).group(1)
        h = hosted.get((exam, m), ("?", "?"))
        print(f"| {exam} | {m} | {h[0]} | {h[1]} | {card} | {wall_s} | {g(us)} | {g(eu)} | {pm} |")
print("\n### The pasted lines (one per row above; the table is derived from these, never the other way round)\n")
for exam, m, out in lines:
    print(f"**{exam} · {m}**"); print("```"); print("\n".join(out)); print("```")
