"""Sprint I (2026-09-18) — the `mlx` provider entry + the env-resolved extra-body hook.

Why a hook at all: mlx_lm.server (0.31.3) applies a LoRA adapter ONLY when the request body
carries "adapters": <path>; its CLI --adapter-path is inert for the default model (measured
18 Sep: 46/46 outputs byte-identical with the flag alone, the adapter applied with the key —
docs/probes/i0-mlx-lora-2026-09-18/RESULTS.md). So the runner has to be able to put a
provider-specific key in the body, resolved from an env var, without touching any committed
provider's request. This file pins both halves and the byte-identity of every other provider.

check()-style (CLAUDE.md gotcha 17): run it directly, or through ./.cline/test.sh.
"""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sandbox.router as R  # noqa: E402

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
    seen = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        seen["url"] = url
        seen["body"] = json.loads(data)
        return _FakeResp()

    orig = R.requests.post
    R.requests.post = fake_post
    try:
        adapter.generate([{"role": "user", "content": "hi"}], "m")
    finally:
        R.requests.post = orig
    return seen


print("sprint I — mlx provider + extra-body hook\n")

# ---------------------------------------------------------------- the entry itself
print("the mlx entry")
check("PROVIDERS has an 'mlx' entry", "mlx" in R.PROVIDERS)
check("mlx is local, no api key", R.PROVIDERS["mlx"]["api_key_env"] is None
      and R.PROVIDERS["mlx"]["base_url"].startswith("http://127.0.0.1"))
check("mlx maps the 'adapters' body key to MLX_ADAPTER_PATH",
      R.PROVIDERS["mlx"].get("body_from_env") == {"adapters": "MLX_ADAPTER_PATH"})

# ---------------------------------------------------------------- env off: byte-identical body
print("\nenv unset — nothing moves")
os.environ.pop("MLX_ADAPTER_PATH", None)
seen_off = capture(R.get_adapter("mlx"))
check("no MLX_ADAPTER_PATH -> no 'adapters' key in the body", "adapters" not in seen_off["body"])
check("mlx body without env has exactly the pre-lane keys",
      set(seen_off["body"]) == {"model", "messages", "temperature", "max_tokens", "stream"},
      f"got {sorted(seen_off['body'])}")
check("URL is the mlx chat-completions endpoint",
      seen_off["url"] == "http://127.0.0.1:8080/v1/chat/completions", seen_off["url"])

# ---------------------------------------------------------------- env on: the key travels
print("\nenv set — the adapter path travels as 'adapters'")
os.environ["MLX_ADAPTER_PATH"] = "/tmp/some-adapter-dir"
seen_on = capture(R.get_adapter("mlx"))
check("'adapters' in the body equals the env value", seen_on["body"].get("adapters") == "/tmp/some-adapter-dir",
      f"got {seen_on['body'].get('adapters')!r}")
check("everything else in the body is unchanged",
      {k: v for k, v in seen_on["body"].items() if k != "adapters"} == seen_off["body"])

# ---------------------------------------------------------------- the merge line is what carries it
# Seen RED (18 Sep, test-honesty refuter): dead-coding the merge in router.generate
# (`if False and self.extra_body:` in a /tmp copy) turns the "'adapters' in the body equals
# the env value" check above red and leaves everything else green — that check IS the guard
# on the hook. The two below pin the merge's shape: it goes through generate's body (not a
# header, not the URL) and it can never override a core key.
print("\nthe merge line — shape")
os.environ["MLX_ADAPTER_PATH"] = "/tmp/some-adapter-dir"
ad = R.get_adapter("mlx")
ad.extra_body = {"adapters": "/tmp/some-adapter-dir", "model": "CLOBBER", "temperature": 99}
seen_clobber = capture(ad)
check("an extra_body key that collides with a core key never wins (model stays 'm')",
      seen_clobber["body"]["model"] == "m" and seen_clobber["body"]["temperature"] == 0.0,
      f"got model={seen_clobber['body']['model']!r} temperature={seen_clobber['body']['temperature']!r}")
check("…while the non-colliding key still travels", seen_clobber["body"].get("adapters") == "/tmp/some-adapter-dir")
ad.extra_body = {}
check("emptying extra_body on a built adapter removes the key (the merge reads the live dict)",
      "adapters" not in capture(ad)["body"])

# ---------------------------------------------------------------- every other provider: untouched
print("\nother providers — the env var must not leak into them")
for name in ("ollama", "openrouter", "scaleway", "ovh", "nebius"):
    cfg = R.PROVIDERS[name]
    if cfg["api_key_env"]:
        os.environ.setdefault(cfg["api_key_env"], "x")
    seen = capture(R.get_adapter(name))
    check(f"{name}: no 'adapters' key with MLX_ADAPTER_PATH set", "adapters" not in seen["body"])
    check(f"{name}: no body_from_env mapping", "body_from_env" not in cfg)
os.environ.pop("MLX_ADAPTER_PATH", None)

# ---------------------------------------------------------------- --snapshot on mlx: stamp or refuse
# PR #93 refused `--snapshot` for mlx outright (no runtime probe, no adapter stamp). Sprint I / I3
# replaced that with a real stamp (runner.mlx_runtime: installed mlx_lm version + sha256 of the
# MLX_MODEL_PATH model dir + sha256 of the MLX_ADAPTER_PATH adapter dir). The refusal that
# remains is the one that keeps gotcha 15 closed: without MLX_MODEL_PATH the served weights
# cannot be resolved (the runner sends model='default_model'), so a snapshot must not be
# written. It must still fire BEFORE any inference: run_exam explodes if reached. The full
# stamp is pinned in sandbox/test_mlx_stamp.py; this block only keeps the provider file's
# own red/green pair current.
print("\n--snapshot on mlx: refuses without MLX_MODEL_PATH (before any inference), proceeds with it")
import contextlib  # noqa: E402
import io  # noqa: E402
import tempfile  # noqa: E402
sys.path.insert(0, str(ROOT / "sandbox"))
import runner  # noqa: E402

def _boom(*a, **k):
    raise AssertionError("run_exam was reached — the refusal did not fire first")

_saved_env = {k: os.environ.pop(k, None) for k in ("MLX_MODEL_PATH", "MLX_ADAPTER_PATH")}
_orig_run_exam, runner.run_exam = runner.run_exam, _boom
try:
    try:
        runner.take_snapshot_loads({"name": "x"}, {"cases": []}, "mlx", "default_model", 3)
        check("take_snapshot_loads(provider='mlx') without MLX_MODEL_PATH raises SystemExit", False, "returned normally")
    except SystemExit as e:
        check("take_snapshot_loads(provider='mlx') without MLX_MODEL_PATH raises SystemExit", True)
        check("…and names MLX_MODEL_PATH as the missing piece", "MLX_MODEL_PATH" in str(e), str(e)[:120])
    except AssertionError as e:
        check("take_snapshot_loads(provider='mlx') without MLX_MODEL_PATH raises SystemExit", False, str(e))
finally:
    runner.run_exam = _orig_run_exam

_n = {"runs": 0}

def _fake_run(agent, exam, provider, model, **kw):
    _n["runs"] += 1
    return {"agent": "x", "provider": provider, "model": model, "mode": "labels",
            "train": {"passed": 0, "total": 0, "score": None},
            "heldout": {"passed": 1, "total": 1, "score": 1.0},
            "cases": [{"id": "a", "split": "heldout", "passed": True, "expected": {}, "got": {}}]}

_orig = (runner.run_exam, runner.save_result)
with tempfile.TemporaryDirectory() as _tmp:
    _model = pathlib.Path(_tmp) / "model"; _model.mkdir()
    (_model / "config.json").write_bytes(b"{}")
    (_model / "model.safetensors").write_bytes(b"weights")
    _adapter = pathlib.Path(_tmp) / "adapter"; _adapter.mkdir()
    (_adapter / "adapters.safetensors").write_bytes(b"lora")
    (_adapter / "adapter_config.json").write_bytes(b"{}")
    os.environ["MLX_MODEL_PATH"], os.environ["MLX_ADAPTER_PATH"] = str(_model), str(_adapter)
    # mlx-lm is Apple-only and not in requirements.txt. Where it is installed (this Mac) the
    # stamp must PROCEED; where it is not (the public repo's Linux CI, 21 Sep: collection error,
    # ModuleNotFoundError from runner.mlx_runtime) the runner must refuse LOUDLY, naming the
    # package, before any inference — that is the fail-loud contract, so it is a check, not a
    # skip. Both branches are effect checks; which one runs is decided by the environment.
    def _mlx_installed() -> bool:
        try:
            import importlib.metadata as _md
            _md.version("mlx-lm"); return True
        except Exception:
            try:
                import mlx_lm  # noqa: F401
                return True
            except Exception:
                return False
    try:
        runner.run_exam, runner.save_result = _fake_run, lambda *a, **k: pathlib.Path("/dev/null")
        _rt = {}
        if _mlx_installed():
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    _agg, _rt = runner.take_snapshot_loads({"name": "x"}, {"cases": []}, "mlx", "default_model", 3)
                except SystemExit as e:              # the PR #93 blanket refusal come back = red
                    check(f"--snapshot refused with both env vars set: {e}", False)
            check("with MLX_MODEL_PATH + MLX_ADAPTER_PATH set, --snapshot proceeds (3 loads ran)", _n["runs"] == 3, str(_n))
            check("…and the runtime stamp carries version, model_sha, adapter_sha (all non-null)",
                  all(isinstance(_rt.get(k), str) and _rt[k] for k in ("version", "model_sha", "adapter_sha")), str(_rt))
        else:
            _err = None
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    runner.take_snapshot_loads({"name": "x"}, {"cases": []}, "mlx", "default_model", 3)
                except (SystemExit, ImportError) as e:
                    _err = e
            check("mlx-lm NOT installed: --snapshot on mlx refuses loudly BEFORE any inference (no loads ran)",
                  _err is not None and _n["runs"] == 0, f"err={_err!r} runs={_n['runs']}")
            # Positive cause identification (refuter on PR #95): the provider is itself called "mlx",
            # so a bare substring match would also accept the unrelated MLX_MODEL_PATH refusal.
            check("…and the refusal IS the missing-package ImportError, not the env-var refusal",
                  isinstance(_err, ImportError) and ("mlx_lm" in str(_err) or "mlx-lm" in str(_err))
                  and "MLX_MODEL_PATH" not in str(_err), f"{type(_err).__name__}: {str(_err)[:120]}")
    finally:
        runner.run_exam, runner.save_result = _orig
        for k, v in _saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
    sys.exit(1)
print("all mlx-provider assertions hold")
