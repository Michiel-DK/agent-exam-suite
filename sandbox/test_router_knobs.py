#!/usr/bin/env python3
"""E22a — the two router knobs that need no endpoint switch: `timeout` and JSON mode.

WHAT THIS PINS, AND WHY EACH ASSERTION EXISTS
---------------------------------------------
`router.py` has carried `timeout: int = 120` since it was written, and `get_adapter()`
never passed one — so 120s was the ONLY value any model call has ever used. A thinking
model on a long input exceeds it, burns retry.py's attempts and dies; `qwen3:4b` took
39 minutes to fail that way (docs/recap-sweep-2026-07-29.md). The knob existed and was
unreachable, which is this repo's documented failure shape: present and inert.

The DEFAULT-UNCHANGED assertions are the important ones. E22a must not move a single
committed score, so:
  - the default timeout is still 120, and
  - JSON mode is OFF unless asked for, and when off the request body is byte-identical
    to what it was before (no `response_format` key at all).
A knob that silently changed every call would be a score-moving change wearing a
config costume.

Deterministic: no server, no inference. The real adapter runs against a canned body,
and the request it WOULD have sent is captured and asserted on.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import router as R  # noqa: E402
import runner  # noqa: E402
from router import DEFAULT_TIMEOUT_S, ChatCompletionsAdapter, get_adapter  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


def capture(adapter):
    """Run the REAL generate() and return the (kwargs, body) it would have sent."""
    seen = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        seen["url"] = url
        seen["timeout"] = timeout
        seen["raw"] = data
        seen["body"] = json.loads(data)
        return _FakeResp()

    orig = R.requests.post
    R.requests.post = fake_post
    try:
        adapter.generate([{"role": "user", "content": "hi"}], "m")
    finally:
        R.requests.post = orig
    return seen


print("E22a — router knobs\n")

# ---------------------------------------------------------------- defaults hold
print("defaults — nothing moves unless asked")
check("DEFAULT_TIMEOUT_S is still 120 (no committed score may move)",
      DEFAULT_TIMEOUT_S == 120, f"got {DEFAULT_TIMEOUT_S}")
check("a bare adapter still uses the 120s default",
      ChatCompletionsAdapter("http://x/v1").timeout == 120)
check("get_adapter() with no timeout still uses the default",
      get_adapter("ollama").timeout == DEFAULT_TIMEOUT_S)

seen = capture(ChatCompletionsAdapter("http://x/v1"))
check("default request carries NO response_format key (body unchanged)",
      "response_format" not in seen["body"], f"body keys={sorted(seen['body'])}")
check("default request carries NO reasoning_effort key (body unchanged)",
      "reasoning_effort" not in seen["body"], f"body keys={sorted(seen['body'])}")
check("default request posts with the 120s timeout",
      seen["timeout"] == 120, f"got {seen['timeout']}")
# Byte-identical to master's body for identical inputs (router.py:116-122, verified
# via `git show origin/master:sandbox/router.py`) — a FULL body compare, not a
# key-absence check, so the byte-identity claim that licenses touching two
# sensitivePaths:full files without a snapshot rerun is asserted, not eyeballed.
MASTER_DEFAULT_BODY = {"model": "m", "messages": [{"role": "user", "content": "hi"}],
                       "temperature": 0.0, "max_tokens": 512, "stream": False}
check("default request body is byte-identical to master's (full compare, not key-absence)",
      seen["raw"] == json.dumps(MASTER_DEFAULT_BODY), f"got {seen['raw']}")

# ---------------------------------------------------------------- timeout reaches the wire
print("\ntimeout — reachable, and it reaches requests.post")
check("get_adapter() accepts a timeout and stores it",
      get_adapter("ollama", timeout=900).timeout == 900)
seen = capture(get_adapter("ollama", timeout=900))
check("the configured timeout is what requests.post actually receives",
      seen["timeout"] == 900, f"got {seen['timeout']}")

# ---------------------------------------------------------------- json mode
print("\njson_mode — off by default, present when asked")
seen = capture(get_adapter("ollama", json_mode=True))
check("json_mode=True sends response_format={'type': 'json_object'}",
      seen["body"].get("response_format") == {"type": "json_object"},
      f"got {seen['body'].get('response_format')!r}")
check("json_mode=True leaves every other request field alone",
      seen["body"]["model"] == "m" and seen["body"]["stream"] is False
      and seen["body"]["temperature"] == 0.0)

# ---------------------------------------------------------------- reasoning_effort
print("\nreasoning_effort — off by default, present when asked")
seen = capture(get_adapter("ollama", reasoning_effort="low"))
check("reasoning_effort='low' sends exactly {reasoning_effort: 'low'}",
      seen["body"].get("reasoning_effort") == "low",
      f"got {seen['body'].get('reasoning_effort')!r}")
check("reasoning_effort='low' leaves every other request field unchanged",
      seen["body"]["model"] == "m" and seen["body"]["messages"] == [{"role": "user", "content": "hi"}]
      and seen["body"]["temperature"] == 0.0 and seen["body"]["max_tokens"] == 512
      and seen["body"]["stream"] is False and "response_format" not in seen["body"])

# ---------------------------------------------------------------- provider_routing
# Provider-pin-knob lane (2026-09-01): third sibling knob, same shape. This is the
# routing-payload sense of "provider" (OpenRouter's `provider` request-body key) — NOT
# the backend selector (agent.yaml's `provider: ollama`) and NOT the PROVIDERS registry.
print("\nprovider_routing — off by default, opaque dict passed through unmodified when asked")
PIN = {"order": ["together"], "allow_fallbacks": False}
seen = capture(get_adapter("ollama", provider_routing=PIN))
check("provider_routing={...} sends body['provider'] equal to that exact dict, unmodified",
      seen["body"].get("provider") == PIN, f"got {seen['body'].get('provider')!r}")
check("provider_routing={...} leaves every other request field unchanged",
      seen["body"]["model"] == "m" and seen["body"]["messages"] == [{"role": "user", "content": "hi"}]
      and seen["body"]["temperature"] == 0.0 and seen["body"]["max_tokens"] == 512
      and seen["body"]["stream"] is False and "response_format" not in seen["body"]
      and "reasoning_effort" not in seen["body"],
      f"got body keys={sorted(seen['body'])}")
# EMPTY-DICT DECISION (pinned, see router.py comment above `if self.provider_routing:`):
# an explicit {} is treated as OFF, identically to unset — the truthiness pattern
# already used by json_mode/reasoning_effort, not an `is not None` check.
seen = capture(get_adapter("ollama", provider_routing={}))
check("provider_routing={} (explicit empty dict) is treated as OFF — no provider key sent",
      "provider" not in seen["body"], f"got body keys={sorted(seen['body'])}")

# ---------------------------------------------------------------- agent config path
print("\nagent config — timeout_s / json_mode travel from agent.yaml to the adapter")
ad = runner.adapter_for({"provider": "ollama", "timeout_s": 600})
check("agent.yaml timeout_s reaches the adapter", ad.timeout == 600, f"got {ad.timeout}")
ad = runner.adapter_for({"provider": "ollama"})
check("an agent with no timeout_s gets the default", ad.timeout == DEFAULT_TIMEOUT_S)
ad = runner.adapter_for({"provider": "ollama", "timeout_s": 600}, timeout=30)
check("an explicit override beats agent.yaml", ad.timeout == 30, f"got {ad.timeout}")
ad = runner.adapter_for({"provider": "ollama", "json_mode": True})
check("agent.yaml json_mode reaches the adapter", ad.json_mode is True)
ad = runner.adapter_for({"provider": "ollama", "reasoning_effort": "low"})
check("agent.yaml reasoning_effort reaches the adapter via runner.adapter_for",
      ad.reasoning_effort == "low", f"got {ad.reasoning_effort!r}")
ad = runner.adapter_for({"provider": "ollama"})
check("an agent with no reasoning_effort gets None (off)", ad.reasoning_effort is None)
ad = runner.adapter_for({"provider": "ollama", "provider_routing": {"order": ["fireworks"]}})
check("agent.yaml provider_routing reaches the adapter via runner.adapter_for, unmodified",
      ad.provider_routing == {"order": ["fireworks"]}, f"got {ad.provider_routing!r}")
ad = runner.adapter_for({"provider": "ollama"})
check("an agent with no provider_routing gets None (off)", ad.provider_routing is None)
# RAW READ, not bool() coercion (unlike json_mode's bool() wrap in the same
# get_adapter(...) call in runner.adapter_for — that wrap would collapse an explicit
# {} to False). An agent that explicitly sets provider_routing={} must see {} survive,
# not False and not None.
ad = runner.adapter_for({"provider": "ollama", "provider_routing": {}})
check("runner reads provider_routing RAW — explicit {} survives as {} (not bool-coerced)",
      ad.provider_routing == {} and ad.provider_routing is not False,
      f"got {ad.provider_routing!r}")

# ---------------------------------------------------------------- no committed agent opts in
print("\nno committed agent turns any knob on (gates stay unmoved)")
for ay in sorted((ROOT / "agents").glob("*/agent.yaml")):
    cfg = ay.read_text()
    check(f"{ay.parent.name}: no timeout_s/json_mode/reasoning_effort/provider_routing in "
          "committed config",
          "timeout_s" not in cfg and "json_mode" not in cfg
          and "reasoning_effort" not in cfg and "provider_routing" not in cfg)

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
    sys.exit(1)
print("all router-knob assertions hold")
