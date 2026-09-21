#!/usr/bin/env python3
"""E38 — encoder extractors (GLiNER2 / GLiFormer) sit the three labels/fields exams.

CPU only, no Ollama. No runner change: each case is scored THROUGH the exam's own scorer
imported from sandbox/runner.py — `score_labels` (email-triage, task-intake) and
`score_fields` (expense-categorization) — plus the exam's committed `properties.py`
where one exists (task-intake), via `runner.load_properties` / `runner.run_properties`,
combined exactly as `run_exam.attempt` combines them (runner.py ~1506-1517).

The schema is DERIVED from cases.json: the label set of every task is the sorted set of
values in the committed `expected` blocks. Two schemas per GLiNER2 model:
  bare  — label names only
  desc  — label names + the definition copied VERBATIM from the champion's committed
          agents/<exam>/prompt.md (asserted as a substring at start-up: a drifted prompt
          makes the probe RAISE, never silently run a different schema)

Output shape per exam (what the runner's scorer consumes):
  email-triage           {"label": <str>}
  expense-categorization {"category": <str>, "recurring": <bool>}
  task-intake            {"agent": <str>, "input": "" if agent == "none" else THE WHOLE
                          REQUEST} — the hand-over half is a CODE RULE, not the encoder:
                          properties.py declares a whole-request hand-over as passing
                          (check_input_is_verbatim_span: "a hand-over of the whole request
                          still passes — the instruction-stripping gap stays declared").
                          So the task-intake verdict here measures agent selection + the
                          none/not-none distinction, nothing about hand-over quality.

Usage (repo root; the venv is NOT the repo's python — see RESULTS.md install line):
  <venv>/bin/python -u docs/probes/e38-.../probe.py run --backend gliner2 --model fastino/gliner2.5-small-v1 --tag g25small
  <venv>/bin/python -u docs/probes/e38-.../probe.py run --backend gliformer --model knowledgator/gliformer-base-v1 --tag gfbase
  python3 docs/probes/e38-.../probe.py summarize          # tables + flips vs the committed snapshots
Heldout is run once per arm and reported; nothing is tuned on it. No snapshot, no gate,
no champion field touched.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sandbox"))
import runner as R  # noqa: E402  (scorers + property loader; never call_model / ollama here)

OUT = Path(__file__).resolve().parent
EXAMS = ("email-triage", "expense-categorization", "task-intake")


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# Definitions copied verbatim from agents/<exam>/prompt.md (whitespace-collapsed). Checked
# against the file at start-up — see `check_descriptions`.
DESCRIPTIONS = {
    "email-triage": {"label": {
        "reply_now": "needs a response today — client requests, money matters, legal/compliance requests, production incidents.",
        "reply_later": "worth answering but not urgent — networking, invitations, non-urgent personal messages, recruiter outreach.",
        "ignore": "no reply needed — newsletters, promotions, cold sales spam, automated notifications that require no action.",
    }},
    "expense-categorization": {
        "category": {
            "software": "SaaS, cloud, APIs",
            "hardware": "hardware",
            "meals": "restaurants, client lunches",
            "travel": "transport, hotels, fuel",
            "telecom": "phone, internet",
            "office": "supplies, coworking",
            "marketing": "ads, domains, design",
            "other": "other",
        },
        "recurring": {
            "true": "true if this is clearly a subscription or repeating charge (monthly/yearly SaaS, telecom plans)",
            "false": "false otherwise",
        },
    },
    "task-intake": {"agent": {
        "email-triage": "an incoming email with NO instruction attached, or a request to sort / prioritise / judge urgency of an email. Input = the email text.",
        "reply-draft": "a request to reply to, answer, or write back to an email (in any language). Input = the email being replied to.",
        "crm-followup": "a question about a client, prospect, deal, contact, status or notes. Input = the question.",
        "expense-categorization": "a bank/card transaction line to book or categorise, or a question about which category / whether it is recurring. Input = the transaction line.",
        "recap": "a request to summarise a day's incoming messages or activity log. Input = the log (the items), not the request sentence.",
        "transcript-en": "a business call transcript to summarise or tidy into a recap. Input = the transcript.",
        "none": "nothing above fits — bookings, weather, reminders, invoice generation, translation, document editing, chit-chat, or a request for a capability not listed.",
    }},
}

# GLiFormer's classify() scores free-text label strings (smoke test 18 Sep: "reply_now" 0.11,
# "reply now" 0.99 on the same mail; "true"/"false" ~0.01). Its arm therefore gets label
# names with _ and - replaced by spaces, and — MY WORDING, not the exam's — a descriptive
# pair for the boolean field. Diagnostic arm only.
GLIFORMER_BOOL = {"recurring": {"true": "recurring subscription or repeating charge",
                                "false": "one-off charge"}}


def check_descriptions() -> None:
    for exam, tasks in DESCRIPTIONS.items():
        prompt = _ws((ROOT / "agents" / exam / "prompt.md").read_text())
        for task, labels in tasks.items():
            for label, desc in labels.items():
                if _ws(desc) not in prompt:
                    raise RuntimeError(f"{exam}/{task}/{label}: description is not a verbatim "
                                       f"substring of agents/{exam}/prompt.md: {desc!r}")


def derive_schema(exam_name: str, cases: list) -> dict:
    """task -> sorted label list, from the committed expected blocks. Bools become
    'true'/'false' strings for the classifier and are converted back on output."""
    tasks: dict[str, set] = {}
    for c in cases:
        for k, v in c["expected"].items():
            tasks.setdefault(k, set()).add(json.dumps(v) if isinstance(v, bool) else v)
    return {k: sorted(v) for k, v in tasks.items()}


def bool_tasks(cases: list) -> set:
    return {k for c in cases for k, v in c["expected"].items() if isinstance(v, bool)}


# ---------------------------------------------------------------- backends

class Gliner2Backend:
    name = "gliner2"

    def __init__(self, model_id: str):
        from gliner2 import AutoExtractor
        self.m = AutoExtractor.from_pretrained(model_id, map_location="cpu")
        self.arch = type(self.m).__name__

    def classify(self, text: str, schema: dict, desc: dict | None) -> tuple[dict, dict]:
        """schema: task -> labels. desc: task -> {label: description} or None (bare).
        Returns (task -> label-or-None, raw)."""
        tasks = {t: ({lab: desc[t][lab] for lab in labs} if desc else list(labs))
                 for t, labs in schema.items()}
        raw = self.m.classify_text(text, tasks, include_confidence=True)
        out = {}
        for t in schema:
            r = raw.get(t)
            out[t] = r.get("label") if isinstance(r, dict) else (r if isinstance(r, str) else None)
        return out, raw


class GliformerBackend:
    name = "gliformer"

    def __init__(self, model_id: str):
        from gliformer import GLiFormer
        self.m = GLiFormer.from_pretrained(model_id, load_tokenizer=True).to("cpu").eval()
        self.arch = type(self.m).__name__

    def classify(self, text: str, schema: dict, desc: dict | None) -> tuple[dict, dict]:
        out, raw = {}, {}
        for t, labs in schema.items():
            if t in GLIFORMER_BOOL:
                display = {GLIFORMER_BOOL[t][lab]: lab for lab in labs}
            else:
                display = {lab.replace("_", " ").replace("-", " "): lab for lab in labs}
            scored = self.m.classify(text, list(display), threshold=0.01)
            raw[t] = scored
            if scored:
                best = max(scored, key=lambda d: d["score"])
                out[t] = display.get(best["class_name"])
            else:
                out[t] = None
        return out, raw


# ---------------------------------------------------------------- scoring (real entry point)

def to_output(exam_name: str, case: dict, labels: dict, bools: set) -> dict:
    parsed = {}
    for t, lab in labels.items():
        if t in bools:
            parsed[t] = None if lab is None else (lab == "true")
        else:
            parsed[t] = lab
    if exam_name == "task-intake":
        parsed["input"] = "" if parsed.get("agent") == "none" else case["input"]
    return parsed


def score(mode: str, props: list, case: dict, parsed: dict) -> dict:
    """Byte-for-byte the non-trajectory branch of runner.run_exam.attempt (~1506-1517)."""
    failed_checks: list = []
    failures: list = []
    if mode == "fields":
        passed, detail = R.score_fields(parsed, case["expected"])
    elif mode == "properties":
        passed, detail = True, {}
    else:
        passed, detail = R.score_labels(parsed, case["expected"])
    labels_ok = passed
    if not passed:
        failed_checks.append({"bucket": "quality", "check": mode})
    props_ok = True
    if props:
        props_ok, prop_failures, prop_failed = R.run_properties(props, case["input"], parsed)
        passed = passed and props_ok
        failures.extend(prop_failures)
        failed_checks += prop_failed
    return {"passed": passed, "labels_ok": labels_ok, "props_ok": props_ok,
            "failed_checks": failed_checks, "failures": failures, "detail": detail}


def run(args) -> int:
    check_descriptions()
    t_all = time.perf_counter()
    be = Gliner2Backend(args.model) if args.backend == "gliner2" else GliformerBackend(args.model)
    load_s = round(time.perf_counter() - t_all, 1)
    schemas = ["bare", "desc"] if args.backend == "gliner2" else ["bare"]
    stamp = datetime.now().isoformat(timespec="seconds")
    print(f"=== E38 {stamp} backend={be.name} arch={be.arch} model={args.model} tag={args.tag} "
          f"load={load_s}s", flush=True)
    rows = []
    for exam_name in EXAMS:
        exam = R.load_exam(exam_name)
        mode = exam.get("mode", "labels")
        props = R.load_properties(exam_name)
        cases = exam["cases"]
        schema = derive_schema(exam_name, cases)
        bools = bool_tasks(cases)
        desc_all = DESCRIPTIONS[exam_name]
        for t, labs in schema.items():
            missing = [lab for lab in labs if lab not in desc_all[t]]
            if missing:
                raise RuntimeError(f"{exam_name}/{t}: labels in cases.json without a prompt.md "
                                   f"definition: {missing}")
        print(f"\n--- {exam_name} mode={mode} props={len(props)} cases={len(cases)} "
              f"schema={json.dumps(schema)}", flush=True)
        for sch in schemas:
            desc = {t: {lab: desc_all[t][lab] for lab in labs} for t, labs in schema.items()} \
                if sch == "desc" else None
            tally = {"train": [0, 0], "heldout": [0, 0]}
            for case in cases:
                t0 = time.perf_counter()
                labels, raw = be.classify(case["input"], schema, desc)
                wall_ms = round((time.perf_counter() - t0) * 1000)
                parsed = to_output(exam_name, case, labels, bools)
                sc = score(mode, props, case, parsed)
                tally[case["split"]][0] += int(sc["passed"])
                tally[case["split"]][1] += 1
                rows.append({"exam": exam_name, "schema": sch, "id": case["id"],
                             "split": case["split"], "expected": case["expected"],
                             "parsed": parsed if exam_name != "task-intake"
                             else {"agent": parsed["agent"], "input_len": len(parsed["input"])},
                             "raw": raw, "wall_ms": wall_ms, **sc})
                mark = "PASS" if sc["passed"] else "FAIL"
                print(f"  [{sch}] {mark} {case['split']:7s} {case['id']:42s} "
                      f"exp={json.dumps(case['expected'])} got={json.dumps(labels)} "
                      f"{wall_ms}ms" + (f"  {sc['failures']}" if sc["failures"] else ""), flush=True)
            print(f"  [{sch}] {exam_name}: train {tally['train'][0]}/{tally['train'][1]}  "
                  f"heldout {tally['heldout'][0]}/{tally['heldout'][1]}", flush=True)
    total_s = round(time.perf_counter() - t_all, 1)
    (OUT / f"raw-{args.tag}.json").write_text(json.dumps({
        "stamp": stamp, "backend": be.name, "arch": be.arch, "model": args.model,
        "tag": args.tag, "python": sys.version.split()[0], "load_s": load_s,
        "total_wall_s": total_s, "rows": rows}, indent=1, ensure_ascii=False))
    print(f"\ntotal wall {total_s}s (incl. {load_s}s load) -> raw-{args.tag}.json", flush=True)
    return 0


def summarize(args) -> int:
    snaps = {e: json.loads((ROOT / "evals" / e / "snapshot.json").read_text()) for e in EXAMS}
    files = sorted(OUT.glob("raw-*.json"))
    if not files:
        sys.exit("no raw-*.json yet")
    print("| exam | champion (snapshot) | arm | train | heldout | up (encoder passes, champion fails) | down |")
    print("|---|---|---|---|---|---|---|")
    for e in EXAMS:
        s = snaps[e]
        champ = {c["id"]: c["passed"] for c in s["cases"]}
        tr = [c for c in s["cases"] if c["split"] == "train"]
        ho = [c for c in s["cases"] if c["split"] == "heldout"]
        champ_txt = (f"{s['model']} train {sum(c['passed'] for c in tr)}/{len(tr)} "
                     f"heldout {sum(c['passed'] for c in ho)}/{len(ho)}")
        for f in files:
            d = json.loads(f.read_text())
            for sch in sorted({r["schema"] for r in d["rows"] if r["exam"] == e}):
                rows = [r for r in d["rows"] if r["exam"] == e and r["schema"] == sch]
                t = [r for r in rows if r["split"] == "train"]
                h = [r for r in rows if r["split"] == "heldout"]
                up = [r["id"] for r in rows if r["passed"] and not champ[r["id"]]]
                down = [r["id"] for r in rows if not r["passed"] and champ[r["id"]]]
                print(f"| {e} | {champ_txt} | {d['tag']}/{sch} | "
                      f"{sum(r['passed'] for r in t)}/{len(t)} | {sum(r['passed'] for r in h)}/{len(h)} | "
                      f"{', '.join(up) or '—'} | {', '.join(down) or '—'} |")
    print()
    for f in files:
        d = json.loads(f.read_text())
        ms = [r["wall_ms"] for r in d["rows"]]
        ti = [r for r in d["rows"] if r["exam"] == "task-intake"]
        print(f"{d['tag']}: {d['model']} arch={d['arch']} load {d['load_s']}s total {d['total_wall_s']}s "
              f"per-call {min(ms)}–{max(ms)}ms median {sorted(ms)[len(ms)//2]}ms | task-intake label-only "
              + " ".join(f"{sch}:{sum(r['labels_ok'] for r in ti if r['schema']==sch)}/{sum(1 for r in ti if r['schema']==sch)}"
                         for sch in sorted({r['schema'] for r in ti})))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--backend", choices=("gliner2", "gliformer"), required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--tag", required=True)
    sub.add_parser("summarize")
    a = ap.parse_args()
    sys.exit(run(a) if a.cmd == "run" else summarize(a))
