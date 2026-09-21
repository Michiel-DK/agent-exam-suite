#!/usr/bin/env python3
"""I2 training rows for crm-followup — TRAIN split, single-turn cases only, replayed from PASSING stored
trajectories: the champion's (gemma4-e2b-ctx16k, 9 Sep) first, the local 14B's (qwen3:14b, 3 Sep) for cases
the champion fails. Each row = system prompt, user request, then the exact protocol turns the runner would
have seen: assistant {"tool":…}, user {"tool_result":…}, …, assistant {"answer":…}. Multi-turn cases are
NOT replayable from results (per-turn answers are not stored) and are skipped, declared. Leak guard: no
heldout case input text (or a 40-char window) in any written line; --selftest proves the guard RED.
"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[3]; OUT = pathlib.Path(__file__).resolve().parent / "data"
cases = {c["id"]: c for c in json.loads((ROOT / "evals/crm-followup/cases.json").read_text())["cases"]}
system = (ROOT / "agents/crm-followup/prompt.md").read_text()
heldout = [c for c in cases.values() if c["split"] == "heldout"]
SOURCES = [("champion", "results/crm-followup__ollama__gemma4-e2b-ctx16k.json"),
           ("qwen3-14b", "results/crm-followup__ollama__qwen3_14b.json")]

def replay(c: dict) -> list | None:
    d = c.get("detail") or {}
    calls, results, got = d.get("tool_calls") or [], d.get("tool_results") or [], c.get("got")
    if not isinstance(got, dict) or "answer" not in got or len(calls) != len(results):
        return None
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": cases[c["id"]]["input"]}]
    for call, res in zip(calls, results):
        msgs.append({"role": "assistant", "content": json.dumps({"tool": call["tool"], "args": call["args"]}, ensure_ascii=False)})
        msgs.append({"role": "user", "content": json.dumps({"tool_result": res}, ensure_ascii=False)})
    msgs.append({"role": "assistant", "content": json.dumps({"answer": got["answer"]}, ensure_ascii=False)})
    return msgs

TRAIN_INPUTS = "\n".join(c["input"] for c in cases.values() if c["split"] == "train")
DECLARED_OVERLAPS: list = []

def leak_guard(lines):
    """A heldout needle found in the training rows is a LEAK unless that exact text already sits in
    a COMMITTED train case input (the outage variants share their question sentence by design —
    operator-signed split, cases.json). Such overlaps are declared in provenance, never silent."""
    blob = "\n".join(lines)
    for h in heldout:
        t = h["input"].strip()
        needles = {t} | ({t[i:i + 40] for i in range(0, max(1, len(t) - 40), 20)} if len(t) >= 40 else set())
        for n in needles:
            if n and n in blob:
                if n in TRAIN_INPUTS:
                    DECLARED_OVERLAPS.append({"heldout": h["id"], "text": n[:80]}); continue
                raise SystemExit(f"LEAK: heldout {h['id']!r}: {n[:60]!r}")

if "--selftest" in sys.argv:
    try:
        leak_guard([json.dumps({"messages": [{"role": "user", "content": heldout[0]["input"]}]})]); print("SELFTEST FAILED"); sys.exit(1)
    except SystemExit as e:
        if str(e).startswith("LEAK"): print("selftest: guard RED as required ->", str(e)[:70]); sys.exit(0)
        raise

rows, origin = {}, {}
for name, path in SOURCES:
    for c in json.loads((ROOT / path).read_text())["cases"]:
        cid = c["id"]
        if cid not in cases or cases[cid]["split"] != "train" or "turns" in cases[cid] or not c.get("passed") or cid in rows:
            continue
        m = replay(c)
        if m: rows[cid], origin[cid] = m, name
skipped_multi = [k for k, v in cases.items() if v["split"] == "train" and "turns" in v]
missing = [k for k, v in cases.items() if v["split"] == "train" and "turns" not in v and k not in rows]
ids = sorted(rows); valid_ids, train_ids = ids[:2], ids[2:]
tl = [json.dumps({"messages": rows[k]}, ensure_ascii=False) for k in train_ids]
vl = [json.dumps({"messages": rows[k]}, ensure_ascii=False) for k in valid_ids]
leak_guard(tl + vl)
OUT.mkdir(exist_ok=True)
(OUT / "train.jsonl").write_text("\n".join(tl) + "\n"); (OUT / "valid.jsonl").write_text("\n".join(vl) + "\n"); (OUT / "test.jsonl").write_text("\n".join(vl) + "\n")
(OUT / "provenance.json").write_text(json.dumps({"train": train_ids, "valid": valid_ids, "origin": origin, "skipped_multiturn": skipped_multi, "no_passing_trajectory": missing, "declared_overlaps_with_committed_train_inputs": DECLARED_OVERLAPS}, indent=1))
print(f"declared overlaps (heldout text that is also a committed train input): {len(DECLARED_OVERLAPS)}")
print(f"rows {len(rows)} (train {len(tl)}, valid {len(vl)}); origin: champion {sum(v=='champion' for v in origin.values())}, qwen3-14b {sum(v=='qwen3-14b' for v in origin.values())}; skipped multi-turn {len(skipped_multi)}; no passing trajectory: {missing}; heldout untouched ({len(heldout)})")
import statistics; print("row chars: max", max(len(l) for l in tl + vl), "median", int(statistics.median(len(l) for l in tl + vl)))
