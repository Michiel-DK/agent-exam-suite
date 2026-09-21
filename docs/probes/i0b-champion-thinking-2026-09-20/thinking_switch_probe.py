#!/usr/bin/env python3
"""I0c — is the I0 token cut a TEMPLATE SWITCH rather than a fine-tune?
The gemma-4 chat template injects <|think|> unless enable_thinking=False. mlx_lm.server accepts
`chat_template_kwargs` in the request body; the runner's router cannot send a dict yet (body_from_env
carries strings only), so this probe calls the server DIRECTLY for all 46 task-intake cases, two arms
(default / enable_thinking=False), parses with runner.extract_json (same parser, but NO re-ask retry —
harsher than the runner, declared) and scores with runner.score_labels + the exam's properties, the
E38 probe pattern. NOT through the real entry point (gotcha 5) — labelled as such in RESULTS.
"""
import json, os, pathlib, sys, time, urllib.request
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sandbox")); sys.path.insert(0, str(ROOT))
import runner as R  # noqa: E402
OUT = pathlib.Path(__file__).resolve().parent
agent = R.load_agent("task-intake") if hasattr(R, "load_agent") else None
system = (ROOT / "agents/task-intake/prompt.md").read_text()
cases = json.loads((ROOT / "evals/task-intake/cases.json").read_text())["cases"]
props = R.load_properties("task-intake") if hasattr(R, "load_properties") else []
URL = "http://127.0.0.1:8080/v1/chat/completions"

def call(msgs, extra):
    body = {"model": "default_model", "messages": msgs, "temperature": 0.0, "max_tokens": 2048, "stream": False, **extra}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t = time.time(); d = json.load(urllib.request.urlopen(req, timeout=300)); wall = (time.time() - t) * 1000
    m = d["choices"][0]["message"]; u = d.get("usage", {})
    return (m.get("content") or ""), (m.get("reasoning") or ""), u, wall

def score(case, parsed):
    passed, detail = R.score_labels(parsed, case["expected"]); fc = [] if passed else [{"bucket": "quality", "check": "labels"}]
    if props:
        ok, fails, pf = R.run_properties(props, case["input"], parsed); passed = passed and ok; fc += pf
    return passed, fc

arms = {"default": {}, "thinking_off": {"chat_template_kwargs": {"enable_thinking": False}}}
report = {}
for name, extra in arms.items():
    rows = []; tot = {"completion_tokens": 0, "prompt_tokens": 0, "reasoning_chars": 0, "wall_ms": 0.0}
    for c in cases:
        content, reasoning, u, wall = call([{"role": "system", "content": system}, {"role": "user", "content": c["input"]}], extra)
        try:
            parsed = R.extract_json(content)
        except Exception:
            parsed = None
        parsed = parsed if isinstance(parsed, dict) else {}
        passed, fc = score(c, parsed)
        tot["completion_tokens"] += u.get("completion_tokens") or 0; tot["prompt_tokens"] += u.get("prompt_tokens") or 0
        tot["reasoning_chars"] += len(reasoning); tot["wall_ms"] += wall
        rows.append({"id": c["id"], "split": c["split"], "passed": passed, "failed_checks": fc, "got": parsed,
                     "content_head": content[:160], "reasoning_chars": len(reasoning), "completion_tokens": u.get("completion_tokens")})
        print(f"  [{'PASS' if passed else 'FAIL'}] {name} {c['id']} ({c['split']}) ct={u.get('completion_tokens')} rc={len(reasoning)}", flush=True)
    tr = [r for r in rows if r["split"] == "train"]; ho = [r for r in rows if r["split"] == "heldout"]
    report[name] = {"train": f"{sum(r['passed'] for r in tr)}/{len(tr)}", "heldout": f"{sum(r['passed'] for r in ho)}/{len(ho)}", "totals": tot, "cases": rows}
    print(f"=== {name}: train {report[name]['train']} heldout {report[name]['heldout']} totals {tot}", flush=True)
(OUT / "thinking_switch_raw.json").write_text(json.dumps(report, indent=1))
print("written thinking_switch_raw.json")
