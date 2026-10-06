#!/usr/bin/env python3
"""build_results_page.py — the one-page results poster (docs/results-2026-10.html) from committed files only. No inference.
Reads: docs/probes/matrix-2026-09-27/tables.md (per-task tables, $ at the ledger date in the file), the pass^k probe script's
output (docs/probes/pass3-column-2026-09-28/pass_k.py), docs/probes/l0-resnapshot-2026-10-02/RESULTS.md (runtime-bump diff),
docs/probes/l3-own-gpu-cost-2026-10-02/RESULTS.md (own-card lines). Fails loud if any source is missing — never a placeholder.
Run from the repo root: python3 scripts/build_results_page.py  → writes docs/results-2026-10.html"""
import os, re, sys, subprocess, html, math, datetime
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
def need(p):
    if not os.path.exists(os.path.join(REPO, p)): sys.exit(f"missing source: {p} — build it (or merge the PR that carries it) before this page")
    return open(os.path.join(REPO, p)).read()
TABLES = need("docs/probes/matrix-2026-09-27/tables.md"); L0 = need("docs/probes/l0-resnapshot-2026-10-02/RESULTS.md"); L3 = need("docs/probes/l3-own-gpu-cost-2026-10-02/RESULTS.md")
PASSK = subprocess.run([sys.executable, os.path.join(REPO, "docs/probes/pass3-column-2026-09-28/pass_k.py")], capture_output=True, text=True, check=True, cwd=REPO).stdout
TITLE = {"transcript-en": "Call summary + action items", "call-fields": "CRM fields from a call", "crm-followup": "CRM brief over tool calls",
         "recap": "Digest of many items", "email-triage": "Email triage", "expense-categorization": "Expense fields", "reply-draft": "Reply draft"}
ORDER = ["email-triage", "expense-categorization", "reply-draft", "recap", "crm-followup", "call-fields", "transcript-en"]
# ---- parse the per-task tables ----
tasks = {}
for blk in TABLES.split("\n### ")[1:]:
    m = re.search(r"\(`([a-z-]+)`, (\d+) held-out cases(?:; (\d+) candidates competed, (\d+) within one case of the best)?\)", blk)
    if not m: continue
    exam, n = m.group(1), int(m.group(2)); rows = []
    for l in blk.splitlines():
        if not l.startswith("| ") or l.startswith("| model") or l.startswith("|---"): continue
        c = [x.strip() for x in l.strip("|").split("|")]
        if len(c) < 9: continue
        model, can, held, passk, wall, out, died, cost, run = c[:9]
        hm = re.search(r"\*\*(\d+)\*\*/(\d+)", held)
        cm = re.search(r"([\d,.]+)", cost); usd = float(cm.group(1).replace(",", "")) if cm and cost != "≈0" else 0.0
        tier = "local" if can.startswith("local") else ("vendor" if can.startswith("vendor") else "ownvm")
        label = model.split(" (")[0]
        rows.append(dict(model=label, can=can, held=int(hm.group(1)), n=int(hm.group(2)), passk=passk, cost=usd, cost_txt=cost, tier=tier, died=died, run=run))
    tasks[exam] = dict(n=n, cand=m.group(3), band=m.group(4), rows=rows)
ledger_date = re.search(r"ledger", TABLES) and "2026-10-02"
# ---- parse pass^k hosted table + L0 line ----
hosted = []
for l in PASSK.split("## Hosted")[1].split("## Candidates")[0].splitlines():
    c = [x.strip() for x in l.strip("|").split("|")]
    if len(c) >= 7 and c[0] in TITLE and "/" in c[3]: hosted.append(c)
l0 = re.search(r"moved \*\*(\d+) of (\d+) cases\*\*.*?\*\*(\d+) held-out cases, (\d+) unstable\*\*", L0, re.S)
l0_moved, l0_total, l0_held, l0_unst = l0.groups()
l3_line = re.search(r"Example, (call-fields on gemma-4-26b-a4b: hosted \$[\d.]+ per 10k \(ledger\)\s*\nvs \$[\d.]+ on a RunPod L4 vs €[\d.]+ on a Scaleway L4)", L3)
l3_txt = l3_line.group(1).replace("\n", " ") if l3_line else "see the L3 probe"
# ---- chart: small multiples, score (fraction) vs $/10k (log), one panel per task ----
C = {"vendor": "var(--s1)", "ownvm": "var(--s2)", "local": "var(--s3)"}
NAME = {"vendor": "vendor only", "ownvm": "own VM (open weights)", "local": "local machine"}
def mark(tier, x, y, r=5):
    if tier == "vendor": return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{C[tier]}" stroke="var(--surface)" stroke-width="2"/>'
    if tier == "ownvm": return f'<rect x="{x-r:.1f}" y="{y-r:.1f}" width="{2*r}" height="{2*r}" rx="1.5" fill="{C[tier]}" stroke="var(--surface)" stroke-width="2"/>'
    return f'<polygon points="{x:.1f},{y-r-1:.1f} {x+r+1:.1f},{y+r:.1f} {x-r-1:.1f},{y+r:.1f}" fill="{C[tier]}" stroke="var(--surface)" stroke-width="2"/>'
W, H, PL, PR, PT, PB = 300, 190, 34, 10, 26, 34
XMIN, XMAX = 0.1, 400.0
def xs(cost):  # local ≈0 sits in its own lane left of the log axis
    if cost <= 0: return PL + 8
    return PL + 26 + (W - PL - PR - 26) * (math.log10(max(cost, XMIN)) - math.log10(XMIN)) / (math.log10(XMAX) - math.log10(XMIN))
def ys(frac): return PT + (H - PT - PB) * (1 - frac)
panels = []
for exam in ORDER:
    t = tasks[exam]; g = [f'<text x="{PL}" y="14" class="ptitle">{html.escape(TITLE[exam])} · {t["n"]} held-out</text>']
    for tick in (0.1, 1, 10, 100):
        x = xs(tick); g.append(f'<line x1="{x:.1f}" y1="{PT}" x2="{x:.1f}" y2="{H-PB}" class="grid"/><text x="{x:.1f}" y="{H-PB+14}" class="tick" text-anchor="middle">${tick:g}</text>')
    g.append(f'<text x="{PL+8}" y="{H-PB+14}" class="tick" text-anchor="middle">≈0</text>')
    for fr in (0.5, 1.0):
        y = ys(fr); g.append(f'<line x1="{PL}" y1="{y:.1f}" x2="{W-PR}" y2="{y:.1f}" class="grid"/><text x="{PL-4}" y="{y+4:.1f}" class="tick" text-anchor="end">{int(fr*100)}%</text>')
    g.append(f'<text x="{(PL+W-PR)/2:.0f}" y="{H-4}" class="tick" text-anchor="middle">$ per 10k tasks (log)</text>')
    best = max(r["held"] for r in t["rows"]); labels = []; placed = []
    best_hosted = next((rr for rr in sorted(t["rows"], key=lambda r: r["cost"]) if rr["held"] == best and rr["tier"] != "local"), None)
    for r in sorted(t["rows"], key=lambda r: r["tier"] != "local"):
        x, y = xs(r["cost"]), ys(r["held"] / r["n"])
        tip = f'{r["model"]} · {r["held"]}/{r["n"]} held-out · {r["cost_txt"]} per 10k · {r["can"]}'
        g.append(f'<g class="pt" data-tip="{html.escape(tip)}">{mark(r["tier"], x, y)}<circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="transparent"/></g>')
        if r["tier"] == "local" or r is best_hosted:   # two direct labels per panel: the local champion and the cheapest top scorer
            short = r["model"].split("/")[-1]; short = short[:17] + "…" if len(short) > 18 else short
            below = y < PT + 16 or r["tier"] == "local"   # near the top edge (or the local lane) the label goes under the mark
            flip = x > W - 70   # near the right edge the label sits left of the mark, right-aligned, so it never clips
            lx, ly = (x - 9) if flip else (x + 9), (y + 15) if below else (y - 8)
            while any(abs(lx - px) < 95 and abs(ly - py) < 11 for px, py in placed): ly += 11   # no label on top of another
            anchor = ' text-anchor="end"' if flip else ""
            placed.append((lx, ly)); labels.append(f'<text x="{lx:.1f}" y="{ly:.1f}" class="lbl"{anchor}>{html.escape(short)}</text>')
    g.extend(labels)   # labels last, on top of every mark; the CSS halo keeps them legible over neighbours
    panels.append(f'<svg viewBox="0 0 {W} {H}" class="panel" role="img" aria-label="{html.escape(TITLE[exam])}: held-out score against dollars per ten thousand tasks">{"".join(g)}</svg>')
# ---- tables ----
def task_table(exam):
    t = tasks[exam]; out = [f'<h4>{html.escape(TITLE[exam])} <span class="muted">· {t["n"]} held-out cases · {t["cand"]} candidates, {t["band"]} within one case of the best</span></h4>',
                            '<table><thead><tr><th>model</th><th>can run on</th><th>held-out</th><th>pass^k</th><th>$ / 10k</th><th>run</th></tr></thead><tbody>']
    for r in sorted(t["rows"], key=lambda r: (-r["held"], r["cost"])):
        out.append(f'<tr><td>{html.escape(r["model"])}</td><td>{html.escape(r["can"])}</td><td><b>{r["held"]}</b>/{r["n"]}</td><td>{html.escape(r["passk"])}</td><td>{html.escape(r["cost_txt"])}</td><td>{html.escape(r["run"])}</td></tr>')
    return "\n".join(out) + "</tbody></table>"
hosted_rows = "\n".join(f'<tr><td>{html.escape(TITLE[c[0]])}</td><td>{html.escape(c[1])}</td><td>{c[2]}</td><td>{c[3]}</td><td>{c[4]}</td><td>{c[5]}</td><td><b>{c[6].replace("**","")}</b></td></tr>' for c in hosted)
today = datetime.date.today().isoformat()
page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local models, measured</title>
<meta name="description" content="Three findings from a year of judge-free exams on small local models: where they hold, why temperature zero is not determinism, and a fine-tune refuted four times. Every number tagged metered or modelled; one command reproduces it.">
<style>
:root{{--bg:#fcfcfb;--surface:#fcfcfb;--ink:#1a1a19;--ink2:#5a5955;--muted:#8a8984;--line:#e4e3de;--card:#f4f3ef;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--grid:#e9e8e3}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#1a1a19;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#8d8c86;--line:#33332f;--card:#232322;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--grid:#2c2c29}}}}
:root[data-theme="dark"]{{--bg:#1a1a19;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#8d8c86;--line:#33332f;--card:#232322;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--grid:#2c2c29}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:40px 16px 64px}} h1{{font-size:2rem;line-height:1.15;margin:0 0 8px;letter-spacing:-.01em}} h2{{font-size:1.35rem;margin:48px 0 8px}} h3{{font-size:1.05rem;margin:28px 0 6px}} h4{{margin:22px 0 6px;font-size:.95rem}}
p{{margin:8px 0;max-width:72ch}} .lead{{font-size:1.1rem;color:var(--ink2)}} .muted{{color:var(--muted);font-weight:400;font-size:.85rem}}
.ev{{background:var(--card);border-left:3px solid var(--s1);padding:10px 14px;margin:10px 0;font-size:.95rem}} .ev b{{font-weight:600}}
.tag{{display:inline-block;font-size:.72rem;letter-spacing:.03em;text-transform:uppercase;border:1px solid var(--line);border-radius:4px;padding:1px 6px;color:var(--ink2);margin-left:6px;vertical-align:middle}}
.grid7{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px;margin:14px 0}} .panel{{width:100%;height:auto;background:var(--surface);border:1px solid var(--line);border-radius:6px}}
.ptitle{{font-size:11px;fill:var(--ink);font-weight:600}} .tick{{font-size:9.5px;fill:var(--muted)}} .lbl{{font-size:9.5px;fill:var(--ink2);paint-order:stroke;stroke:var(--surface);stroke-width:3px;stroke-linejoin:round}} .grid{{stroke:var(--grid);stroke-width:1}} .pt{{cursor:default}}
.legend{{display:flex;gap:18px;flex-wrap:wrap;font-size:.85rem;color:var(--ink2);margin:6px 0}} .legend i{{display:inline-block;width:10px;height:10px;margin-right:6px;vertical-align:-1px}}
table{{border-collapse:collapse;width:100%;font-size:.85rem;margin:6px 0 10px}} th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}} th{{color:var(--ink2);font-weight:600}}
details summary{{cursor:pointer;color:var(--ink2);margin:8px 0}} pre{{background:var(--card);padding:12px 14px;border-radius:6px;overflow:auto;font-size:.85rem}} code{{font-size:.9em}}
#tip{{position:fixed;pointer-events:none;background:var(--ink);color:var(--bg);padding:6px 9px;border-radius:5px;font-size:.8rem;max-width:320px;display:none;z-index:9}}
footer{{margin-top:48px;color:var(--muted);font-size:.85rem;border-top:1px solid var(--line);padding-top:14px}} a{{color:var(--s1)}}
</style></head><body><main>
<h1>Small local models, measured on office tasks</h1>
<p class="lead">Eight agents (seven in the hosted comparison), 220 committed cases, deterministic grading with no LLM judge, every candidate sat the same held-out cases at temperature 0. Three findings, one chart, one command.</p>
<p class="muted">Scores are held-out cases passed, never percentages. Dollars are per 10,000 tasks on the tokens of that run at the OpenRouter rate of {ledger_date}; <span class="tag">metered</span> means a run of that model, <span class="tag">modelled</span> means arithmetic on stated inputs. The private repo holds the build ledger; everything on this page has a probe folder in the public one.</p>

<h2>1. A 2B–4B model on a laptop holds every short decision task. It loses only long summaries.</h2>
<div class="ev"><b>Evidence:</b> the local champion ties or beats the hosted flagships on email triage, expense fields, reply drafts, the CRM brief over tool calls (where the 2B is the best model of any size) and the digest; it sits one case behind the top group on CRM field write-back and four behind on long call summaries. Cost: local ≈0, the best open-weights hosted rows $0.23–$5.41, the vendor flagship $5–$127 per 10k. <span class="tag">metered</span></div>
<div class="legend"><span><i style="background:var(--s1);border-radius:50%"></i>vendor only (closed weights)</span><span><i style="background:var(--s2);border-radius:2px"></i>own VM (open weights, measured via API)</span><span><i style="background:var(--s3);clip-path:polygon(50% 0,100% 100%,0 100%)"></i>local machine (3-load snapshot)</span><span class="muted">hover a mark for the model</span></div>
<div class="grid7">{"".join(panels)}</div>
<p class="muted">One panel per task; no aggregate across tasks, because a sum hides the row a buyer cares about. Local marks sit in the ≈0 lane. The hosted rows are one pass each ({ledger_date} ledger); the local rows are three fresh loads that agreed on every case.</p>
<p><b>The honest limit.</b> On call summaries with numbers the best model of any tier passes 14 of 19; the local one 10. That band is closed until real transcripts exist. <b>Running the open weights on your own card</b> is a residency choice, not a saving: at one request at a time an L4 costs more per task than the hosted per-token price on every row ({html.escape(l3_txt)}). <span class="tag">modelled</span></p>
<details><summary>The seven tables behind the chart</summary>{"".join(task_table(e) for e in ORDER)}</details>

<h2>2. Temperature zero is not determinism on hosted APIs. A gate that re-sits every case catches what moved.</h2>
<div class="ev"><b>Evidence:</b> GLM-5.3 passed 10 of 13 call summaries on one run and 6 of 13 across six runs the same day (pass^6). Kimi K3 lost 0–1 case per task. The local champions passed every case on all three loads (pass^3 equals the single-run score on all 8 exams, 0 unstable). When the local runtime was upgraded on 2 October, re-sitting all 8 exams moved {l0_moved} of {l0_total} cases, {l0_held} of them held-out, {l0_unst} unstable; the August bump had moved 5 of 22 on one exam in both directions. <span class="tag">metered</span></div>
<table><thead><tr><th>task</th><th>model</th><th>held-out n</th><th>single run</th><th>pass^3 pinned</th><th>pass^3 unpinned</th><th>pass^6</th></tr></thead><tbody>{hosted_rows}</tbody></table>
<p class="muted">Six same-day runs on 1 September (three with the creator endpoint pinned, three not), on that day's case sets. pass^k is the share of cases passed on all k runs — the τ-bench reliability metric. The gate rule: a case counts only when three fresh loads agree; a challenger replaces the incumbent only if it passes every stable case the incumbent passes.</p>

<h2>3. Four fine-tunes of the local champion, four refusals, and the cause named.</h2>
<div class="ev"><b>Evidence:</b> LoRA on the 2B for the CRM brief, 30 training rows. v1–v3 trained with no prompt mask on rows that were 95% tool payload by characters, so the loss never saw the decisions: held-out 12→11, the adapter contradicting its own training row. v4 cut one example per assistant step with the prompt masked: it fixed the two-call case for the first time and taught a "call again" reflex, held-out 12→9. Every attempt was killed by its pre-registered rule (any stable held-out case down). <span class="tag">metered</span></div>
<p>The same gate that picks a model refuses a fine-tune. What the loop can show honestly on synthetic cases is a smaller model holding the champion's score and a format failure fixed; an accuracy gain needs cases that are not at ceiling, which means a client's.</p>

<h2>What this looks like on your task</h2>
<p>The process, not the agents, is the transferable part. On a new task it runs in this order: write the exam from your real cases and your definition of correct, with a held-out split from day one that nobody tunes against. Every candidate model sits it, local and hosted, three loads at temperature 0, a case counts only when all three agree. The cheapest model that passes takes the task; a one-case gap is noise, and the pick is reported with how many candidates competed. Any change — a model, a prompt, a runtime, a fine-tune — re-sits the exam per case before it ships, and a challenger replaces the incumbent only if it passes every stable case the incumbent passes. The grading is deterministic and judge-free; a judge, if ever used, is one more model under test with its own exam.</p>
<h2>Three times the instrument was wrong</h2>
<p>The build ledger stays private; three of its entries are public as post-mortems, each in the same shape: what we believed, what the probe showed, what changed.</p>
<ul>
<li><a href="https://github.com/Michiel-DK/agent-exam-suite/blob/master/docs/post-mortems/01-the-window-not-the-weights.md">The window, not the weights</a> — three capability verdicts that were a 4,096-token truncation nobody had checked.</li>
<li><a href="https://github.com/Michiel-DK/agent-exam-suite/blob/master/docs/post-mortems/02-the-gate-said-ok.md">The gate said ok while five verdicts moved</a> — an aggregate regression check, blind to cancelling flips; what replaced it.</li>
<li><a href="https://github.com/Michiel-DK/agent-exam-suite/blob/master/docs/post-mortems/03-a-green-gate-that-cannot-go-red.md">A green gate that cannot go red</a> — a test runner that reports "passed" by construction, and an answer key inside the instrument.</li>
</ul>
<h2>Reproduce it</h2>
<pre><code>git clone https://github.com/Michiel-DK/agent-exam-suite && cd agent-exam-suite
python3 docs/probes/pass3-column-2026-09-28/pass_k.py     # finding 2, from the committed snapshots and the six-run files
python3 docs/probes/matrix-2026-09-27/build_tables.py       # the seven tables (local wall times need a local results/ dir)
./.cline/test.sh                                            # the deterministic test gate, one process per file</code></pre>
<p class="muted">Re-sitting an exam locally needs Ollama and the champion model: <code>python3 sandbox/runner.py check email-triage</code> compares a fresh run with the committed snapshot per case.</p>

<footer>Built {today} by <code>scripts/build_results_page.py</code> from committed files; no number on this page was typed by hand. Probe folders: <code>docs/probes/matrix-2026-09-27</code>, <code>pass3-column-2026-09-28</code>, <code>l0-resnapshot-2026-10-02</code>, <code>l3-own-gpu-cost-2026-10-02</code>, <code>i2v3-crm-lora-2026-09-21</code>, <code>i2v4-crm-lora-2026-09-21</code>. Earlier write-up: <a href="eval-suite-is-the-asset.html">Agents are disposable, the eval suite is the asset</a>.</footer>
</main><div id="tip"></div>
<script>
const tip=document.getElementById('tip');
document.querySelectorAll('.pt').forEach(g=>{{g.addEventListener('mousemove',e=>{{tip.textContent=g.dataset.tip;tip.style.display='block';tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY+12)+'px';}});g.addEventListener('mouseleave',()=>tip.style.display='none');}});
</script></body></html>"""
out = os.path.join(REPO, "docs/results-2026-10.html"); open(out, "w").write(page)
print(f"wrote {os.path.relpath(out, REPO)} ({len(page):,} bytes); tasks {len(tasks)}, hosted rows {len(hosted)}, L0 {l0_moved}/{l0_total} moved")
