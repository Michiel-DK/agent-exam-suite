#!/usr/bin/env python3
"""Set or clear provider_routing in an agent.yaml (single flow-style line, so the
line-based edit pattern from set_effort.py still applies; yaml.safe_load parses it
into a real dict — verified in this probe's logs).
Usage: set_pin.py <agent.yaml> <unset|provider-slug> [provider-slug2 ...]"""
import sys
import yaml

path, arg = sys.argv[1], sys.argv[2]
extra = sys.argv[3:]
lines = [l for l in open(path).read().splitlines() if not l.startswith("provider_routing:")]
if arg != "unset":
    order = ", ".join(f'"{s}"' for s in [arg] + extra)
    lines.append(f'provider_routing: {{order: [{order}], allow_fallbacks: false}}')
open(path, "w").write("\n".join(lines) + "\n")
# fail-loud verification through the same parse the runner uses
cfg = yaml.safe_load(open(path).read())
got = cfg.get("provider_routing")
if arg == "unset":
    assert got is None, (path, got)
else:
    assert got == {"order": [arg] + extra, "allow_fallbacks": False}, (path, got)
print(f"{path}: provider_routing -> {got}")
