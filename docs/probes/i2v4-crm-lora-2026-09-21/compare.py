#!/usr/bin/env python3
"""Rule-A verdict: snapshot-base.json vs snapshot-adapter.json, per case. Kill fires on any heldout case that is
STABLE on both arms, passed on base and failed on the adapter. Prints stamps too."""
import json, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
b = json.loads((HERE / "snapshot-base.json").read_text()); a = json.loads((HERE / "snapshot-adapter.json").read_text())
for n, s in (("base", b), ("adapter", a)):
    r = s.get("runtime", {}); print(f"{n}: train {s['train_score']:.3f} heldout {s['heldout_score']:.3f} loads {s.get('loads')} mlx {r.get('version')} model {str(r.get('model_sha'))[:8]} adapter {str(r.get('adapter_sha'))[:8]} unstable {sum(1 for c in s['cases'] if not c.get('stable', True))}/{len(s['cases'])}")
bc = {c["id"]: c for c in b["cases"]}; ac = {c["id"]: c for c in a["cases"]}
if set(bc) != set(ac): sys.exit("case sets differ")
up, down, kill = [], [], []
for cid in sorted(bc):
    x, y = bc[cid], ac[cid]; st = x.get("stable", True) and y.get("stable", True)
    if x["passed"] != y["passed"]:
        (up if y["passed"] else down).append(f"{cid} [{x['split']}{'' if st else ', unstable'}]")
        if st and x["split"] == "heldout" and not y["passed"]: kill.append(cid)
for split in ("train", "heldout"):
    print(f"{split}: base {sum(1 for c in bc.values() if c['split']==split and c['passed'])}/{sum(1 for c in bc.values() if c['split']==split)} -> adapter {sum(1 for c in ac.values() if c['split']==split and c['passed'])}/{sum(1 for c in ac.values() if c['split']==split)}")
print("UP:", up or "-"); print("DOWN:", down or "-")
print("KILL FIRES — stable heldout down:" if kill else "kill does not fire (0 stable heldout down)", kill or "")
