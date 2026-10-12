"""AS-4 — the Ollama SERVER's KV-cache type and flash attention are part of the runtime
stamp (CLAUDE.md gotcha 21).

Why: Ollama exposes neither setting over its API, and docs/probes/m7-kv-cache-2026-10-08
measured both moving verdicts (q4_0 sank 2 stable held-out cases on each of transcript-en
and crm-followup) while runtime.version read 0.35.0 on every arm — so `check` would have
accepted the q4_0 server as the committed runtime and called the loss a model regression.
The values are read from the environment of the process LISTENING on the ollama base_url
(`runner.ollama_server_settings`, lsof + ps/proc, zero inference), stamped by
`take_snapshot_loads` (read before load 1 and after the last load), and compared by
`snapshot_preflight` (VERSION, RUNTIME presence, KV_CACHE_TYPE, FLASH_ATTENTION — in that
order; hosted and mlx snapshots are never asked for the fields — halt 2).

Everything is offline: no Ollama, no inference. Section (6) spawns a child python that
LISTENS on an ephemeral loopback port with a constructed environment, and points the real
reader at it. check()-style (CLAUDE.md gotcha 17): run directly or via ./.cline/test.sh.
"""
import argparse
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import socket

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sandbox"))
import runner  # noqa: E402

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


def _bomb(*a, **k):
    raise AssertionError("the server-settings reader was invoked when it must not be")


class Counter:
    """A reader stub that records calls and replays a list of values (last one repeats)."""
    def __init__(self, *values):
        self.values, self.n = list(values), 0

    def __call__(self):
        v = self.values[min(self.n, len(self.values) - 1)]
        self.n += 1
        if isinstance(v, BaseException):
            raise v
        return dict(v)


UNSET = {"kv_cache_type": "unset", "flash_attention": "unset"}
EXAM = {"cases": [{"id": "a"}]}


def _case(cid, split, passed, **extra):
    return {"id": cid, "split": split, "passed": passed, "expected": {}, "got": {}, **extra}


def _snap(provider="ollama", version="0.35.0", **runtime_extra):
    rt = {"name": provider, "version": version, **runtime_extra}
    return {"provider": provider, "model": "m", "heldout_score": 1.0, "train_score": None,
            "runtime": rt, "loads": 3, "cases": [_case("a", "heldout", True, stable=True)]}


def _stamped(**over):
    return _snap(**{**UNSET, **over})


def _vfn(v="0.35.0"):
    return lambda: v


def _pf(snap, reader, version="0.35.0", **kw):
    return runner.snapshot_preflight(snap, EXAM, version_fn=_vfn(version),
                                     server_settings_fn=reader, **kw)


@contextlib.contextmanager
def patched(mod, **attrs):
    saved = {k: getattr(mod, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)


# ======================================================== (1) same settings pass
print("\n(1) same settings pass")
r = Counter(UNSET)
check("snapshot unset/unset + reader unset/unset + matching version -> None",
      _pf(_stamped(), r) is None, str(_pf(_stamped(), Counter(UNSET))))
check("the reader WAS consulted (the pass is a comparison, not a skip)", r.n == 1, str(r.n))
q = {"kv_cache_type": "q8_0", "flash_attention": "1"}
check("non-default stamp that equals the live server also passes",
      _pf(_stamped(**q), Counter(q)) is None)

# ======================================================== (2) different settings refused
print("\n(2) different settings refused; ordering VERSION > RUNTIME > KV > FLASH")
c = _pf(_stamped(), Counter({**UNSET, "kv_cache_type": "q4_0"}))
check("kv q4_0 vs unset -> KV_CACHE_TYPE: naming both values",
      bool(c) and c.startswith("KV_CACHE_TYPE:") and "q4_0" in c and "unset" in c, str(c))
c = _pf(_stamped(), Counter({**UNSET, "flash_attention": "1"}))
check("flash '1' vs unset -> FLASH_ATTENTION:", bool(c) and c.startswith("FLASH_ATTENTION:"), str(c))
c = _pf(_stamped(), Counter(UNSET), version="0.40.2")
check("version mismatch -> VERSION:", bool(c) and c.startswith("VERSION:"), str(c))
# Ordering: every earlier axis loses to the earlier prefix when SEVERAL axes are wrong at once.
bad_srv = {"kv_cache_type": "q4_0", "flash_attention": "1"}
r = Counter(bad_srv)
c = _pf(_stamped(), r, version="0.40.2")
check("version AND kv AND flash all wrong -> VERSION wins", bool(c) and c.startswith("VERSION:"), str(c))
check("VERSION refusal returns before the reader is called", r.n == 0, str(r.n))
r = Counter(bad_srv)
c = _pf(_snap(version="0.35.0"), r, version="0.35.0")
check("pre-field snapshot AND a differing live server -> RUNTIME wins over KV/FLASH",
      bool(c) and c.startswith("RUNTIME:"), str(c))
c = _pf(_snap(version="0.30.0"), Counter(bad_srv), version="0.35.0")
check("pre-field snapshot AND version mismatch -> VERSION wins over RUNTIME",
      bool(c) and c.startswith("VERSION:"), str(c))
c = _pf(_stamped(), Counter(bad_srv))
check("kv AND flash both differ -> KV_CACHE_TYPE wins over FLASH_ATTENTION",
      bool(c) and c.startswith("KV_CACHE_TYPE:"), str(c))

# ======================================================== (3) pre-field snapshot refused
print("\n(3) pre-field snapshots are refused, never read as a match; the reader is not called")
r = Counter(UNSET)
c = _pf(_snap(), r)
check("{name, version}-only ollama runtime -> RUNTIME: naming kv_cache_type",
      bool(c) and c.startswith("RUNTIME:") and "kv_cache_type" in c, str(c))
check("  reader never invoked", r.n == 0, str(r.n))
r = Counter(UNSET)
c = _pf(_snap(kv_cache_type="unset"), r)
check("kv_cache_type present, flash_attention missing -> RUNTIME: naming flash_attention",
      bool(c) and c.startswith("RUNTIME:") and "flash_attention" in c, str(c))
check("  reader never invoked", r.n == 0, str(r.n))
c = _pf(_snap(flash_attention="unset"), Counter(UNSET))
check("flash present, kv missing -> RUNTIME: naming kv_cache_type",
      bool(c) and c.startswith("RUNTIME:") and "kv_cache_type" in c, str(c))


def _committed_ollama_snapshot():
    for p in sorted((ROOT / "evals").glob("*/snapshot.json")):
        d = json.loads(p.read_text())
        if d.get("provider") == "ollama":
            return p.parent.name, d
    return None, None


def _run_cmd(fn, args, **patches):
    """Drive a REAL cmd_* with stdout captured; returns (rc_or_None, SystemExit_or_None, out)."""
    buf, rc, exited = io.StringIO(), None, None
    with patched(runner, **patches), contextlib.redirect_stdout(buf):
        try:
            rc = fn(args)
        except SystemExit as e:
            exited = e
    return rc, exited, buf.getvalue()


agent_name, committed = _committed_ollama_snapshot()
check("a committed evals/*/snapshot.json with provider 'ollama' exists to copy", committed is not None)
if committed is not None:
    # Pre-stamp shape built from the committed file, not assumed of it: the re-snapshot after
    # this lane stamps every committed snapshot, and this test must stay true then.
    committed = json.loads(json.dumps(committed))
    for field in runner.OLLAMA_STAMP_FIELDS:
        committed["runtime"].pop(field, None)
    with tempfile.TemporaryDirectory() as tmp:
        copy = pathlib.Path(tmp) / "snapshot.json"
        copy.write_text(json.dumps(committed))
        r = Counter(UNSET)
        rc, ex, out = _run_cmd(
            runner.cmd_check, argparse.Namespace(agent=agent_name, dedupe_tools=False, tolerance=0.0),
            _load_snapshot=lambda name: json.loads(copy.read_text()),
            ollama_version=_vfn(committed["runtime"]["version"]),
            ollama_server_settings=r, run_exam=_bomb,
            ollama_unload=lambda m: (_ for _ in ()).throw(AssertionError("unload reached")))
        msg = str(ex.code) if ex is not None else ""
        check("real cmd_check on a temp copy of a committed ollama snapshot, stamp fields removed, exits non-zero "
              "BEFORE run_exam, printing the RUNTIME cause",
              ex is not None and ex.code not in (0, None) and "RUNTIME:" in msg and "kv_cache_type" in msg,
              f"rc={rc} exited={ex!r}")
        check("  the reader was not invoked on that path", r.n == 0, str(r.n))

# ======================================================== (3b) undeterminable settings refuse
print("\n(3b) undeterminable settings refuse, never pass")
try:
    out = _pf(_stamped(), Counter(SystemExit("error: ollama_server_settings: expected exactly 1 listener")))
    check("preflight with a SystemExit reader raises SystemExit (it is not swallowed)", False, f"returned {out!r}")
except SystemExit:
    check("preflight with a SystemExit reader raises SystemExit (it is not swallowed)", True)

if True:
    rc, ex, out = _run_cmd(
        runner.cmd_check, argparse.Namespace(agent="fx", dedupe_tools=False, tolerance=0.0),
        _load_snapshot=lambda name: _stamped(), load_agent=lambda n: {"name": n},
        load_exam=lambda n: EXAM, ollama_version=_vfn(),
        ollama_server_settings=Counter(SystemExit("error: undeterminable")), run_exam=_bomb)
check("real cmd_check: reader SystemExit -> exits non-zero before run_exam",
      ex is not None and ex.code not in (0, None) and rc is None, f"rc={rc} exited={ex!r}")


def _check_all_env(snap, reader):
    """Real cmd_check_all over a temp ROOT holding one agent 'fx' with `snap`."""
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        (t / "agents" / "fx").mkdir(parents=True)
        (t / "agents" / "fx" / "agent.yaml").write_text("name: fx\n")
        (t / "evals" / "fx").mkdir(parents=True)
        (t / "evals" / "fx" / "snapshot.json").write_text(json.dumps(snap))
        return _run_cmd(runner.cmd_check_all, argparse.Namespace(tolerance=0.0),
                        ROOT=t, load_agent=lambda n: {"name": n}, load_exam=lambda n: EXAM,
                        ollama_version=_vfn(), ollama_server_settings=reader, run_exam=_bomb,
                        ollama_unload=lambda m: None)


rc, ex, out = _check_all_env(_stamped(), Counter(SystemExit("error: undeterminable")))
check("real cmd_check_all: reader SystemExit propagates (not caught, not counted as a pass)",
      ex is not None and rc is None, f"rc={rc} exited={ex!r}")
r = Counter(UNSET)
rc, ex, out = _check_all_env(_snap(), r)
check("real cmd_check_all: pre-field ollama snapshot -> REFUSED RUNTIME, rc 1, run_exam never reached",
      ex is None and rc == 1 and "REFUSED: RUNTIME:" in out and "kv_cache_type" in out, f"rc={rc} out={out!r}")
check("  reader not invoked", r.n == 0, str(r.n))
rc, ex, out = _check_all_env(_stamped(), Counter({**UNSET, "kv_cache_type": "q4_0"}))
check("real cmd_check_all: differing live kv -> REFUSED KV_CACHE_TYPE, rc 1",
      ex is None and rc == 1 and "REFUSED: KV_CACHE_TYPE:" in out, f"rc={rc} out={out!r}")

# ======================================================== (4) halt-2 fence
print("\n(4) hosted and mlx snapshots: unchanged results, reader never invoked")
for prov in ("openrouter", "scaleway"):
    check(f"{prov} snapshot (version None) -> None, reader never invoked",
          runner.snapshot_preflight(_snap(prov, None), EXAM, version_fn=_bomb,
                                    server_settings_fn=_bomb) is None)
    c = runner.snapshot_preflight(_snap(prov, None), {"cases": [{"id": "b"}]}, version_fn=_bomb,
                                  server_settings_fn=_bomb)
    check(f"{prov} case-id mismatch -> the existing CASES: cause", bool(c) and c.startswith("CASES:"), str(c))
MLX = {"version": "0.1", "model_sha": "m", "adapter_sha": None}
mlx_snap = _snap("mlx", None)
mlx_snap["runtime"] = {"name": "mlx", **MLX}
check("mlx snapshot with a matching stamp -> None, reader never invoked",
      runner.snapshot_preflight(mlx_snap, EXAM, version_fn=_bomb, server_settings_fn=_bomb,
                                mlx_runtime_fn=lambda: dict(MLX)) is None)
c = runner.snapshot_preflight(mlx_snap, EXAM, version_fn=_bomb, server_settings_fn=_bomb,
                              mlx_runtime_fn=lambda: {**MLX, "model_sha": "other"})
check("mlx stamp mismatch -> the existing MODEL_SHA: cause (reader never invoked)",
      bool(c) and c.startswith("MODEL_SHA:"), str(c))

# ======================================================== (5) take_snapshot_loads writes the stamp
print("\n(5) take_snapshot_loads stamps the runtime by the real mechanism")


def _fake_result(provider, model):
    cases = [_case("a", "heldout", True)]
    return {"agent": "fx", "provider": provider, "model": model, "mode": "labels",
            "train": {"passed": 0, "total": 0, "score": None},
            "heldout": {"passed": 1, "total": 1, "score": 1.0}, "cases": cases}


def _take(provider, reader, mlx=False):
    runs = {"n": 0}

    def _run(agent, exam, prov, model, **kw):
        runs["n"] += 1
        return _fake_result(prov, model)
    over = dict(run_exam=_run, ollama_unload=lambda m: None, ollama_version=_vfn(),
                save_result=lambda *a, **k: pathlib.Path("/dev/null"))
    if mlx:
        over["mlx_runtime"] = lambda: {"name": "mlx", **MLX}
    out, exited, rt = io.StringIO(), None, None
    with patched(runner, **over), contextlib.redirect_stdout(out):
        try:
            _agg, rt = runner.take_snapshot_loads({"name": "fx"}, {"cases": []}, provider, "m", 3,
                                                  server_settings_fn=reader)
        except SystemExit as e:
            exited = e
    return rt, exited, runs["n"]


srv = {"kv_cache_type": "q8_0", "flash_attention": "1"}
r = Counter(srv)
rt, ex, n = _take("ollama", r)
check("ollama: runtime kv_cache_type / flash_attention equal the reader's values",
      rt is not None and rt.get("kv_cache_type") == "q8_0" and rt.get("flash_attention") == "1", str(rt))
check("  name/version unchanged, 3 loads ran, reader read before AND after (2 calls)",
      rt is not None and rt["name"] == "ollama" and rt["version"] == "0.35.0" and n == 3 and r.n == 2,
      f"{rt} runs={n} reads={r.n}")
rt, ex, n = _take("ollama", Counter(srv, {**srv, "kv_cache_type": "q4_0"}))
check("second read differs in kv_cache_type -> raises", ex is not None and "kv_cache_type" in str(ex.code), str(ex))
rt, ex, n = _take("ollama", Counter(srv, {**srv, "flash_attention": "0"}))
check("second read differs in flash_attention -> raises", ex is not None and "flash_attention" in str(ex.code), str(ex))
rt, ex, n = _take("ollama", Counter(SystemExit("error: undeterminable")))
check("reader SystemExit -> raises BEFORE the first run_exam", ex is not None and n == 0, f"{ex!r} runs={n}")
for prov, mlx in (("openrouter", False), ("mlx", True)):
    rt, ex, n = _take(prov, _bomb, mlx=mlx)
    check(f"{prov}: reader never invoked, runtime has neither key",
          ex is None and rt is not None and "kv_cache_type" not in rt and "flash_attention" not in rt, f"{rt} {ex!r}")
# The runtime dict reaches the written payload unchanged (cmd_run / cmd_run_all pass it through).
payload = runner.snapshot_payload({"name": "fx"}, {"cases": []}, "ollama", "m", _fake_result("ollama", "m"),
                                  loads=3, runtime={"name": "ollama", "version": "0.35.0", **srv})
check("snapshot_payload persists the runtime block verbatim, both fields included",
      payload["runtime"] == {"name": "ollama", "version": "0.35.0", **srv}, str(payload.get("runtime")))
src = pathlib.Path(runner.__file__).read_text()
check("both --snapshot writers take their runtime from take_snapshot_loads (the one mechanism)",
      src.count("aggregate, runtime = take_snapshot_loads(") == 2, str(src.count("aggregate, runtime = take_snapshot_loads(")))

# ======================================================== (6) the real reader reads a server's environment
print("\n(6) the real reader reads a listening server's environment")
CHILD = ("import socket,sys,time\n"
         "s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(5)\n"
         "print(s.getsockname()[1], flush=True); time.sleep(120)\n")
PLAT_OK = sys.platform == "darwin" or sys.platform.startswith("linux")
TOOLS_OK = bool(shutil.which("lsof") or os.access("/usr/sbin/lsof", os.X_OK)) and (
    sys.platform != "darwin" or bool(shutil.which("ps") or os.access("/bin/ps", os.X_OK)))


@contextlib.contextmanager
def child_server(env_pairs, extra_argv=(), path=True):
    env = {**({"PATH": "/usr/bin:/bin"} if path else {}), **env_pairs}   # constructed, not inherited
    p = subprocess.Popen([sys.executable, "-c", CHILD, *extra_argv], env=env, stdout=subprocess.PIPE, text=True)
    try:
        port = int(p.stdout.readline().strip())
        global CHILD_NAME
        CHILD_NAME = runner._process_name(str(p.pid), sys.platform,
                                          runner._find_tool("ps") if sys.platform == "darwin" else None)
        yield port
    finally:
        p.kill()
        p.wait()


CHILD_NAME = None   # the stand-in listener is python, not ollama: named per child


def _read(port, server_name=None):
    try:
        return runner.ollama_server_settings(f"http://127.0.0.1:{port}",
                                             server_name=server_name or CHILD_NAME), None
    except SystemExit as e:
        return None, str(e.code)


if PLAT_OK and TOOLS_OK:
    with child_server({"OLLAMA_KV_CACHE_TYPE": "q8_0"}) as port:
        got, err = _read(port)
        check("OLLAMA_KV_CACHE_TYPE=q8_0, flash absent -> {'q8_0', 'unset'}",
              got == {"kv_cache_type": "q8_0", "flash_attention": "unset"}, f"{got} {err}")
        with patched(runner, PROVIDERS={
                **runner.PROVIDERS, "ollama": {**runner.PROVIDERS["ollama"],
                                               "base_url": f"http://127.0.0.1:{port}/v1"}}):
            try:
                via_default = runner.ollama_server_settings(server_name=CHILD_NAME)
            except SystemExit as e:
                via_default = str(e.code)
        check("with no argument the reader takes host+port from PROVIDERS['ollama']['base_url']",
              via_default == {"kv_cache_type": "q8_0", "flash_attention": "unset"}, str(via_default))
    with child_server({"OLLAMA_FLASH_ATTENTION": "1"}) as port:
        got, err = _read(port)
        check("kv absent, OLLAMA_FLASH_ATTENTION=1 -> {'unset', '1'}",
              got == {"kv_cache_type": "unset", "flash_attention": "1"}, f"{got} {err}")
    with child_server({}) as port:
        got, err = _read(port)
        check("neither set -> both 'unset' (a known state, not None, not 'f16')", got == UNSET, f"{got} {err}")
    # A token in ARGV that looks like the variable, while the env also has it: ps -E (darwin)
    # cannot tell them apart -> refuse; /proc/<pid>/environ (linux) is unambiguous -> reads the env.
    with child_server({"OLLAMA_KV_CACHE_TYPE": "q8_0"}, ("OLLAMA_KV_CACHE_TYPE=q4_0",)) as port:
        got, err = _read(port)
        if sys.platform == "darwin":
            check("darwin: variable in argv AND env -> refuses rather than guess",
                  got is None and err and "appears 2 times" in err, f"{got} {err}")
        else:
            check("linux: argv token ignored, environ value read", got and got["kv_cache_type"] == "q8_0", f"{got} {err}")
    # The listener is not ollama (a port-forward, a stand-in): its env says nothing -> refuse.
    with child_server({}) as port:
        try:   # NO server_name: the production default is what is under test
            got, err = runner.ollama_server_settings(f"http://127.0.0.1:{port}"), None
        except SystemExit as e:
            got, err = None, str(e.code)
        check("listener executable is not 'ollama' (default server_name) -> SystemExit naming it, never 'unset'",
              got is None and err and "not 'ollama'" in err and repr(CHILD_NAME) in err, f"{got} {err}")
    # No PATH= in what was read stands in for an environment ps -E could not see (it prints
    # argv alone, rc 0): an absent variable cannot be told from an unread one -> refuse.
    with child_server({}, path=False) as port:
        got, err = _read(port)
        check("no PATH= in the read environment -> SystemExit, never 'unset'",
              got is None and err and "no PATH=" in err, f"{got} {err}")
else:
    got, err = _read(1, server_name="ollama")
    check("unsupported platform / tools missing: the reader's refusal is positively identified",
          got is None and err and ("unsupported platform" in err or "not found" in err), f"{got} {err}")

# Platform- and tool-independent refusals (injected so both branches are exercised everywhere).
s = socket.socket()
s.bind(("127.0.0.1", 0))
free_port = s.getsockname()[1]
s.close()
if PLAT_OK and TOOLS_OK:
    got, err = _read(free_port)
    check("nothing listening -> SystemExit naming the listener count (0) and the port",
          got is None and err and "found 0" in err and str(free_port) in err, f"{got} {err}")
try:
    runner.ollama_server_settings("http://192.0.2.1:11434")
    check("non-loopback base_url -> SystemExit naming loopback", False, "returned")
except SystemExit as e:
    check("non-loopback base_url -> SystemExit naming loopback", "loopback" in str(e.code), str(e.code))
try:
    runner.ollama_server_settings("http://127.0.0.1:11434", platform="win32")
    check("unsupported platform -> SystemExit naming the platform", False, "returned")
except SystemExit as e:
    check("unsupported platform -> SystemExit naming the platform",
          "unsupported platform" in str(e.code) and "win32" in str(e.code), str(e.code))
with patched(runner, _TOOL_FALLBACKS={}):
    try:
        runner.ollama_server_settings("http://127.0.0.1:11434", platform="linux", which_fn=lambda n: None)
        check("lsof missing -> SystemExit naming the tool", False, "returned")
    except SystemExit as e:
        check("lsof missing -> SystemExit naming the tool", "'lsof'" in str(e.code) and "not found" in str(e.code),
              str(e.code))

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
    sys.exit(1)
print("all kv-stamp checks passed")
