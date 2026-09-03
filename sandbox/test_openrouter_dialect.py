#!/usr/bin/env python3
"""OPENROUTER — the provider entry, and the response-dialect audit behind it.

WHY A SEPARATE FILE. `test_reasoning_split.py` is scoped to E24 (where the completion
budget went) and its test_7 greps router.py's SOURCE TEXT; this file is scoped to one
question — does our OpenAI-compat reader survive OpenRouter's documented response shape
without moving a single byte of what it returns on Ollama.

NO LIVE CALLS. No OPENROUTER_API_KEY exists yet. Every assertion below is driven by a
canned body through the REAL ChatCompletionsAdapter.generate, or by the REAL
get_adapter() with the env var set/unset around the call. An ad-hoc probe is not a
witness for the tool (CLAUDE.md gotcha 5) — so nothing here reimplements the reader.

THE AUDIT, source-cited. All four rows verified 2026-08-29 against OpenRouter's RAW
markdown docs (`.md` suffix on the doc URL), NOT a WebFetch paraphrase — MEMORY.md
records a paraphrase inverting a competitor's definition, and it happened again here:
a paraphrase reported `reasoning_content` as a response alias when the raw source has
it only in the "Preserving Reasoning" REQUEST section.

  field           | ollama (measured)   | openrouter (documented)          | handling
  ----------------|---------------------|----------------------------------|--------------------
  message.content | str                 | `content: string | null`          | same, `or ""`
  message.reasoning| str, when thinking | "Reasoning tokens will appear in  | same field, no
                  |                     |  the `reasoning` field"          | change needed
  reasoning_content| never present      | NOT a documented response field  | defensive fallback
  finish_reason   | 'stop'/'length'     | normalized to stop|length|       | opaque data, never
                  |                     | tool_calls|content_filter|error  | branched on
  native_finish_reason | absent         | raw provider string              | NOT read (would add
                  |                     |                                  | a meta key)
  usage           | populated           | "always returned for             | .get() per field,
                  |                     |  non-streaming", typed `usage?:` | None never 0
  choices[0].error| absent              | DOCUMENTED: rides in the choice  | ⚠️ DECLARED GAP —
   + partial      |                     | ALONGSIDE partial content,       | scored as a normal
   content        |                     | finish_reason 'error'            | answer today (7c)
  choices absent  | n/a                 | ErrorResponse envelope shape is  | hardened (7b) —
   (envelope)     |                     | documented; 200-OK delivery for  | was an uncatchable
                  |                     | non-streaming is INFERRED        | KeyError, run-killer
  message absent  | n/a                 | UNDOCUMENTED — ChatChoice has    | hardened defensively
   inside a choice|                     | `required: [.., message]`        | (7), not doc-driven

⚠️ Two rows above were CORRECTED by a round-trip refutation on 2026-08-29, after an
earlier draft of this file overclaimed them. The message-absent row was justified with
an errors.md sentence that is actually about the choices-less envelope, and the real
documented provider-error shape (partial content) was missed entirely. Both corrections
are recorded rather than quietly rewritten, because the overclaim is the reusable lesson.
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import router as R  # noqa: E402
from router import (  # noqa: E402
    DEFAULT_TIMEOUT_S,
    PROVIDERS,
    ChatCompletionsAdapter,
    TerminationError,
    get_adapter,
)

FAILED = []


def check(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {extra}" if not ok and extra else ""))
    if not ok:
        FAILED.append(label)


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def drive(payload, adapter=None):
    """Run the REAL generate() against a canned body. Returns (text, meta) or raises."""
    ad = adapter or ChatCompletionsAdapter("http://x/v1")
    orig = R.requests.post
    R.requests.post = lambda *a, **k: _FakeResp(payload)
    try:
        return ad.generate([{"role": "user", "content": "hi"}], "m")
    finally:
        R.requests.post = orig


def capture(adapter, payload):
    """Return what the REAL generate() actually put on the wire."""
    seen = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        seen.update(url=url, headers=headers, timeout=timeout)
        return _FakeResp(payload)

    orig = R.requests.post
    R.requests.post = fake_post
    try:
        adapter.generate([{"role": "user", "content": "hi"}], "m")
    finally:
        R.requests.post = orig
    return seen


OLLAMA_USAGE = {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33}
OK_BODY = {"choices": [{"message": {"role": "assistant", "content": '{"ok": true}'},
                        "finish_reason": "stop"}],
           "usage": OLLAMA_USAGE}


# ------------------------------------------------------------------ 1. the entry is LIVE
def test_1_provider_entry_is_reachable_not_merely_present():
    """CLAUDE.md gotcha 1: presence is not effect. A PROVIDERS dict entry proves nothing
    until get_adapter() builds a real adapter from it and its base_url + Authorization
    header are what requests.post actually receives."""
    check("openrouter is in PROVIDERS", "openrouter" in PROVIDERS)
    cfg = PROVIDERS.get("openrouter", {})
    check("base_url is the documented v1 endpoint",
          cfg.get("base_url") == "https://openrouter.ai/api/v1", f"got {cfg.get('base_url')!r}")
    check("api_key_env is OPENROUTER_API_KEY",
          cfg.get("api_key_env") == "OPENROUTER_API_KEY", f"got {cfg.get('api_key_env')!r}")
    check("the entry has EXACTLY the shape of the other keyed providers",
          sorted(cfg) == sorted(PROVIDERS["scaleway"]), f"got {sorted(cfg)}")

    # No key set -> the same loud ValueError every other keyed provider raises. This is
    # the state the repo is in TODAY, so it is the state that must fail cleanly.
    saved = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        try:
            get_adapter("openrouter")
            check("get_adapter with no key raises", False, "it returned an adapter")
        except ValueError as exc:
            check("get_adapter with no key raises ValueError naming the env var",
                  "OPENROUTER_API_KEY" in str(exc), str(exc))
        # With a key, the adapter is real and the key reaches the wire.
        os.environ["OPENROUTER_API_KEY"] = "sk-or-TESTONLY"
        ad = get_adapter("openrouter")
        check("get_adapter builds a ChatCompletionsAdapter",
              isinstance(ad, ChatCompletionsAdapter))
        check("adapter carries the openrouter base_url",
              ad.base_url == "https://openrouter.ai/api/v1", ad.base_url)
        check("adapter still gets the repo default timeout",
              ad.timeout == DEFAULT_TIMEOUT_S, f"got {ad.timeout}")
        seen = capture(ad, OK_BODY)
        check("POSTs to the openrouter /chat/completions URL",
              seen["url"] == "https://openrouter.ai/api/v1/chat/completions", seen["url"])
        check("the API key actually reaches the Authorization header",
              seen["headers"].get("Authorization") == "Bearer sk-or-TESTONLY",
              f"got {seen['headers'].get('Authorization')!r}")
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)
        if saved is not None:
            os.environ["OPENROUTER_API_KEY"] = saved


# ------------------------------------------------------- 2. openrouter reasoning dialects
def test_2_openrouter_reasoning_field_is_read():
    """OpenRouter's DOCUMENTED response field is `reasoning` — the same one Ollama uses,
    so this must already work. Asserted anyway: it is the row of the audit table that
    says 'no change needed', and an unasserted 'no change needed' is a guess."""
    body = {"choices": [{"message": {"role": "assistant", "content": "A" * 12,
                                     "reasoning": "T" * 340},
                         "finish_reason": "stop", "native_finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 9, "total_tokens": 14,
                      "completion_tokens_details": {"reasoning_tokens": 80}}}
    text, meta = drive(body)
    check("content is the answer, not the thinking", text == "A" * 12, repr(text[:30]))
    check("openrouter message.reasoning -> reasoning_chars",
          meta["reasoning_chars"] == 340, f"got {meta['reasoning_chars']}")
    check("content_chars measured separately", meta["content_chars"] == 12,
          f"got {meta['content_chars']}")
    check("native_finish_reason does NOT leak into meta (no new key)",
          "native_finish_reason" not in meta, f"meta keys={sorted(meta)}")
    check("reasoning_tokens is NOT read into meta (cross-provider field stays chars)",
          "reasoning_tokens" not in meta, f"meta keys={sorted(meta)}")


def test_3_reasoning_content_dialect_is_read_when_it_is_the_only_one():
    """THE MUTATION TARGET. Deleting `or message.get("reasoning_content")` from router.py
    reddens exactly this check and nothing else in the suite.

    Register: DEFENSIVE, NOT MEASURED. `reasoning_content` is DeepSeek/vLLM's response
    dialect; OpenRouter documents it only as a request-side alias. No provider in
    PROVIDERS has been observed emitting it. It is here so a backend that does cannot
    silently report 0 chars of thinking on a model that thought for thousands."""
    body = {"choices": [{"message": {"role": "assistant", "content": "answer",
                                     "reasoning_content": "R" * 275},
                         "finish_reason": "stop"}],
            "usage": OLLAMA_USAGE}
    _t, meta = drive(body)
    check("message.reasoning_content -> reasoning_chars (2nd dialect)",
          meta["reasoning_chars"] == 275,
          f"got {meta['reasoning_chars']} — the fallback dialect is not being read")


def test_4_precedence_is_first_NON_EMPTY_not_reasoning_always_wins():
    """The semantics are a chain of `or`, i.e. FIRST NON-EMPTY — pinned in BOTH
    directions because the difference is observable and an earlier comment got it wrong.

    A round-trip refutation (2026-08-29) reproduced the falsy-or fall-through: the code
    was fine, the comment claiming '`reasoning` always wins' was false. These two cases
    are what make that claim unstateable again without going red."""
    both = {"choices": [{"message": {"role": "assistant", "content": "answer",
                                     "reasoning": "M" * 100,
                                     "reasoning_content": "X" * 999},
                         "finish_reason": "stop"}],
            "usage": OLLAMA_USAGE}
    _t, meta = drive(both)
    check("both NON-EMPTY -> `reasoning` is the one reported",
          meta["reasoning_chars"] == 100, f"got {meta['reasoning_chars']}")

    # THE CASE THE OLD COMMENT GOT WRONG. "" is falsy, so the chain falls through.
    empty_first = {"choices": [{"message": {"role": "assistant", "content": "answer",
                                            "reasoning": "",
                                            "reasoning_content": "X" * 999},
                                "finish_reason": "stop"}],
                   "usage": OLLAMA_USAGE}
    _t, m2 = drive(empty_first)
    check("reasoning='' falls THROUGH to reasoning_content (first non-empty wins)",
          m2["reasoning_chars"] == 999,
          f"got {m2['reasoning_chars']} — if this is 0, the precedence changed to "
          f"'reasoning always wins' and the comment must change with it")


# ------------------------------------------------------------ 5. the ollama byte-identity
def test_5_ollama_shaped_response_is_byte_identical():
    """THE PIN. The dialect widening must not move one byte of what Ollama returns, so
    this compares the WHOLE meta dict to a literal — spot-checking fields would not
    catch an ADDED key, which is the realistic way this change breaks a committed
    snapshot (a new key propagates into combine_metrics/_null_safe_sum)."""
    text, meta = drive(OK_BODY)
    check("ollama-shaped content unchanged", text == '{"ok": true}', repr(text))
    check("ollama-shaped meta is EXACTLY the pre-change dict",
          meta == {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33,
                   "content_chars": 12, "reasoning_chars": 0, "finish_reason": "stop"},
          f"got {meta!r}")

    # A thinking Ollama response: `reasoning` present, `reasoning_content` absent — the
    # fallback branch is UNREACHABLE on this shape, which is why it cannot regress it.
    think = {"choices": [{"message": {"role": "assistant", "content": "hi",
                                      "reasoning": "z" * 64},
                          "finish_reason": "stop"}],
             "usage": OLLAMA_USAGE}
    _t, m2 = drive(think)
    check("thinking ollama meta is EXACTLY the pre-change dict",
          m2 == {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33,
                 "content_chars": 2, "reasoning_chars": 64, "finish_reason": "stop"},
          f"got {m2!r}")


# ---------------------------------------------------------------- 6. empty-content death
def test_6_empty_content_raises_with_openrouter_finish_reasons():
    """TerminationError must fire on OpenRouter's shapes too, and finish_reason must be
    recorded as OPAQUE DATA — the raise is never gated on its value, so an unexpected
    string cannot crash it or suppress it. Includes `content_filter` and `error` (both
    in OpenRouter's normalized set and both unobserved on ollama) and a raw provider
    string that no normalization covers."""
    for fr in ("length", "content_filter", "error", "ERR_PROVIDER_QUOTA_9x", None):
        body = {"choices": [{"message": {"role": "assistant", "content": "",
                                         "reasoning": "t" * 700},
                             "finish_reason": fr, "native_finish_reason": "whatever"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2048,
                          "total_tokens": 2051}}
        try:
            drive(body)
            check(f"finish_reason={fr!r}: empty content raises TerminationError", False,
                  "generate() returned — an empty answer is being scored")
        except TerminationError as exc:
            d = exc.details
            check(f"finish_reason={fr!r}: raises TerminationError", True)
            check(f"finish_reason={fr!r}: recorded verbatim, not normalized or defaulted",
                  d.get("finish_reason") == fr, f"got {d.get('finish_reason')!r}")
            check(f"finish_reason={fr!r}: content_chars 0, reasoning_chars 700",
                  d.get("content_chars") == 0 and d.get("reasoning_chars") == 700,
                  f"got {d.get('content_chars')}/{d.get('reasoning_chars')}")
            check(f"finish_reason={fr!r}: completion_tokens carried for attribution",
                  d.get("completion_tokens") == 2048, f"got {d.get('completion_tokens')}")


def test_7_choice_level_error_fails_the_case_instead_of_killing_the_run():
    """MUTATION TARGET 2. Revert `choice.get("message") or {}` to `choice["message"]` and
    this reddens alone (with a KeyError escaping the test's own try, which is the point).

    OpenRouter's NonStreamingChoice types `error?: ErrorResponse`, and its error docs say
    a failure while the LLM is producing output comes back 200 OK with the error in the
    body. A KeyError here is caught by NOTHING — not call_with_retry, not run_exam's
    `except (ValueError, TypeError)` — so it kills the run rather than failing the case,
    which inverts 'fail loud, never a placeholder'."""
    body = {"choices": [{"finish_reason": "error", "native_finish_reason": None,
                         "error": {"code": 502, "message": "provider disconnected"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 0, "total_tokens": 7}}
    try:
        drive(body)
        check("a message-less error choice raises TerminationError", False,
              "generate() returned a value for a response with no message")
    except TerminationError as exc:
        check("a message-less error choice raises TerminationError (case fails, run lives)",
              True)
        check("finish_reason 'error' is recorded so the cause is not lost",
              exc.details.get("finish_reason") == "error",
              f"got {exc.details.get('finish_reason')!r}")
        check("content_chars 0 on a message-less choice",
              exc.details.get("content_chars") == 0, f"got {exc.details.get('content_chars')}")
    except KeyError as exc:
        check("a message-less error choice raises TerminationError, not KeyError", False,
              f"KeyError({exc!r}) — uncatchable by retry.py AND runner.run_exam, kills the run")


def test_7b_choices_less_error_envelope_does_not_kill_the_run():
    """MUTATION TARGET 3, and the round-trip's headline finding. Revert the
    `body.get("choices") or []` guard to `body["choices"][0]` and this reddens with an
    escaping KeyError('choices') — reproduced on master too, so this is a PRE-EXISTING
    run-killer that the openrouter entry merely makes reachable in a new way.

    Uncatchable by design of the surrounding code: retry.py's clauses are requests-only
    around call_fn and (TypeError, ValueError) around parse_fn; run_exam catches
    (ValueError, TypeError). A KeyError walks past all of them and ends the run.

    ⚠️ Warrant: the envelope SHAPE is documented (ErrorResponse, api-reference/errors);
    its delivery at 200 OK for a non-streaming request is an INFERENCE from the adjacent
    prose, not a shape any example shows. The guard does not depend on that inference —
    `choices: []` and any malformed body land here too."""
    envelope = {"error": {"code": 502, "message": "Provider returned error",
                          "metadata": {"error_type": "provider_unavailable"}}}
    for label, payload in (("no `choices` key", envelope),
                           ("empty `choices` list", {"choices": [], **envelope})):
        try:
            drive(payload)
            check(f"{label}: raises TerminationError", False, "generate() returned")
        except TerminationError as exc:
            d = exc.details
            check(f"{label}: raises TerminationError (case fails, run lives)", True)
            check(f"{label}: provider error code recorded as a flat scalar",
                  d.get("provider_error_code") == 502, f"got {d.get('provider_error_code')!r}")
            check(f"{label}: provider error message recorded",
                  d.get("provider_error_message") == "Provider returned error",
                  f"got {d.get('provider_error_message')!r}")
            check(f"{label}: finish_reason stays None — nothing reported one",
                  d.get("finish_reason") is None, f"got {d.get('finish_reason')!r}")
            check(f"{label}: every recorded detail is a scalar (record stays flat)",
                  all(v is None or isinstance(v, (int, str)) for v in d.values()),
                  f"got {d!r}")
        except (KeyError, IndexError) as exc:
            check(f"{label}: raises TerminationError, not {type(exc).__name__}", False,
                  f"{type(exc).__name__}({exc!r}) — uncatchable by retry.py AND "
                  f"run_exam, kills the whole run")

    # A body with no choices AND no error object at all: still classified, never a crash.
    try:
        drive({"usage": OLLAMA_USAGE})
        check("bare body with neither choices nor error raises TerminationError", False,
              "generate() returned")
    except TerminationError as exc:
        check("bare body with neither choices nor error raises TerminationError", True)
        check("absent error object -> code/message are None, not invented",
              exc.details.get("provider_error_code") is None
              and exc.details.get("provider_error_message") is None,
              f"got {exc.details!r}")
    except Exception as exc:
        check("bare body with neither choices nor error raises TerminationError", False,
              f"{type(exc).__name__}({exc!r})")

    # `error` present but not a dict — a malformed body must not turn into AttributeError.
    try:
        drive({"choices": [], "error": "just a string"})
        check("non-dict error object raises TerminationError", False, "generate() returned")
    except TerminationError:
        check("non-dict error object raises TerminationError, not AttributeError", True)
    except Exception as exc:
        check("non-dict error object raises TerminationError, not AttributeError", False,
              f"{type(exc).__name__}({exc!r})")


# ------------------------------------------------------ 7c. the declared gap (TRIPWIRE)
def test_7c_DECLARED_GAP_partial_content_provider_error_is_scored_as_an_answer():
    """⚠️ TRIPWIRE DOCUMENTING A GAP — THIS IS NOT AN ENDORSEMENT OF THE BEHAVIOUR.

    Read this before "fixing" a red here: the assertion below records what the adapter
    does TODAY (measured 2026-08-29, on this branch AND on master), so that a silent
    change of it goes red and gets noticed. It is the D3 pattern from the termination
    lane. If a later lane DELIBERATELY decides a partial-content provider error should
    fail its case, this test is expected to go red and should be REWRITTEN, not patched.

    The shape is OpenRouter's DOCUMENTED non-streaming provider error for the Chat
    Completions skin (api-reference/errors -> "Skin-Specific Error Formats"): the error
    rides in the choice ALONGSIDE partial content. Because content is non-empty, no
    termination fires, and `choice["error"]` is never read — a truncated fragment is
    graded as though it were the model's answer.

    Not fixed in this lane: that is a decision about WHAT GETS SCORED, and could move
    committed numbers. Declared, pinned, and left to an operator."""
    documented = {"choices": [{"message": {"role": "assistant",
                                           "content": "partial output..."},
                               "finish_reason": "error",
                               "error": {"code": 502,
                                         "message": "Provider disconnected mid-stream",
                                         "metadata": {"error_type": "provider_unavailable"}}}],
                  "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}
    try:
        text, meta = drive(documented)
        check("TODAY (not endorsed): partial content is returned as the answer",
              text == "partial output...", f"got {text!r}")
        check("TODAY (not endorsed): choice-level `error` object is never surfaced",
              "error" not in meta and "provider_error_code" not in meta,
              f"meta keys={sorted(meta)}")
        check("finish_reason 'error' IS recorded — the only trace of the failure a "
              "consumer gets today", meta.get("finish_reason") == "error",
              f"got {meta.get('finish_reason')!r}")
    except TerminationError as exc:
        check("TRIPWIRE FIRED: partial-content provider errors now terminate. This is a "
              "BEHAVIOUR CHANGE — rewrite this test deliberately, do not patch it.",
              False, f"TerminationError{exc.details!r}")


def test_7d_null_content_provider_error_already_terminates():
    """The null-content variant of the same documented shape. This ALREADY worked before
    this lane (verified against master 2026-08-29) — pinned so the DIALECT-0/1 guards
    above cannot regress the path that was already correct."""
    nulled = {"choices": [{"message": {"role": "assistant", "content": None},
                           "finish_reason": "error",
                           "error": {"code": 502, "message": "Provider disconnected"}}],
              "usage": {"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5}}
    try:
        drive(nulled)
        check("null content + finish_reason 'error' raises TerminationError", False,
              "generate() returned — a provider failure would be scored as an answer")
    except TerminationError as exc:
        check("null content + finish_reason 'error' raises TerminationError", True)
        check("finish_reason 'error' recorded verbatim off the choice",
              exc.details.get("finish_reason") == "error",
              f"got {exc.details.get('finish_reason')!r}")
        check("content_chars 0 on a null-content choice",
              exc.details.get("content_chars") == 0,
              f"got {exc.details.get('content_chars')}")


# ------------------------------------------------------------------- 8. usage absent/partial
def test_8_absent_usage_yields_None_never_zero():
    """`usage` is typed optional (`usage?: ResponseUsage`) even though OpenRouter says it
    is always returned for non-streaming. The None-not-zero rule is what we rely on, not
    the promise — 'unknown' and 'zero' are different facts."""
    body = {"choices": [{"message": {"role": "assistant", "content": "ok"},
                         "finish_reason": "stop"}]}
    _t, meta = drive(body)
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        check(f"usage absent -> {k} is None, not 0", meta[k] is None, f"got {meta[k]!r}")
    check("usage absent -> chars are still MEASURED (0 is a measurement here)",
          meta["content_chars"] == 2 and meta["reasoning_chars"] == 0,
          f"got {meta['content_chars']}/{meta['reasoning_chars']}")

    # Partial usage: per-field .get(), so a reported field survives while the rest are None.
    partial = {"choices": [{"message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop"}],
               "usage": {"completion_tokens": 4}}
    _t, m2 = drive(partial)
    check("partial usage -> reported field kept", m2["completion_tokens"] == 4,
          f"got {m2['completion_tokens']!r}")
    check("partial usage -> unreported fields are None, not 0",
          m2["prompt_tokens"] is None and m2["total_tokens"] is None,
          f"got {m2['prompt_tokens']!r}/{m2['total_tokens']!r}")

    # usage present but null (a backend that sends the key empty).
    nulled = {"choices": [{"message": {"role": "assistant", "content": "ok"},
                           "finish_reason": "stop"}], "usage": None}
    _t, m3 = drive(nulled)
    check("usage: null -> None per field, no crash", m3["total_tokens"] is None,
          f"got {m3['total_tokens']!r}")


def test_8b_envelope_survives_the_REAL_run_exam_end_to_end():
    """GOTCHA 5 WITNESS — an ad-hoc probe is not a witness for the tool.

    Every other test in this file drives `ChatCompletionsAdapter.generate` directly, so
    none of them proves the two NEW `details` keys survive `runner.py`, which spreads
    `{"cause": "no_answer", **exc.details}` into a case record in THREE places
    (runner.py:401 trajectory, :989 plain, :1562 live). An earlier draft of this PR
    credited the gate with that verification; the gate did not cover it.

    Exactly ONE thing is replaced: `router.requests.post`, the network. `adapter_for`
    returns a REAL adapter, so the raise under test is the production one. Pattern
    lifted from test_termination.py's real-run_exam harness. No retry backoff is slept:
    TerminationError propagates on first occurrence (retry.py wraps only parse_fn).

    What this pins: the documented envelope FAILS ITS CASE and the run CONTINUES, and
    the resulting record is JSON-serializable — which is what writing `results/` does.

    ⚠️ HOW THIS ONE DIES. Reverting the DIALECT-0 guard does NOT produce a `[FAIL]` line
    here — it produces an UNCAUGHT `KeyError: 'choices'` that terminates the process
    mid-file (verified 2026-08-29 in an isolated tree copy, rc=1). The traceback is the
    evidence, and it is the finding itself: the stack reads run_exam -> attempt ->
    run_plain_case -> call_model -> call_with_retry -> generate, i.e. the KeyError walks
    past EVERY handler in the chain. A test that cannot even report its own failure is
    exactly what "kills the run" means for a real exam."""
    try:
        from runner import load_exam, run_exam  # noqa: E402
    except ImportError as exc:
        check("runner importable for the end-to-end witness", False, repr(exc))
        return

    envelope = {"error": {"code": 502, "message": "Provider returned error",
                          "metadata": {"error_type": "provider_unavailable"}}}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return envelope

    import runner as _runner
    exam = load_exam("reply-draft")
    exam = {**exam, "cases": exam["cases"][:1]}
    agent = _runner.load_agent("reply-draft")
    real_post, real_adapter_for = R.requests.post, _runner.adapter_for
    try:
        R.requests.post = lambda *a, **k: _Resp()
        _runner.adapter_for = lambda *a, **k: ChatCompletionsAdapter(
            "http://canned/v1", timeout=7)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_exam(agent, exam, "ollama", "canned-model")
    finally:
        R.requests.post, _runner.adapter_for = real_post, real_adapter_for

    check("run_exam RETURNED — the envelope fails its case, it does not kill the run",
          result is not None and "cases" in result, f"got {result!r}")
    case = result["cases"][0]
    check("the case FAILED (loudly), it was not scored vacuously",
          case.get("passed") is False, f"got {case.get('passed')!r}")
    check("failed_checks is exactly the one termination entry",
          case.get("failed_checks") == [{"bucket": "termination", "check": "termination"}],
          f"got {case.get('failed_checks')!r}")
    term = (case.get("detail") or {}).get("termination") or {}
    check("the provider error code survives into the CASE RECORD",
          term.get("provider_error_code") == 502, f"got {term!r}")
    check("the provider error message survives into the CASE RECORD",
          term.get("provider_error_message") == "Provider returned error", f"got {term!r}")
    check("runner-side cause is 'no_answer' — literally true, and the DECLARED "
          "imprecision: provider_error_code is what says 'the provider errored'",
          term.get("cause") == "no_answer", f"got {term.get('cause')!r}")
    check("every value in the record is a scalar — flat, as designed",
          all(v is None or isinstance(v, (int, str)) for v in term.values()), f"got {term!r}")
    try:
        json.dumps(result)
        check("the whole run result JSON-serializes (this is what writing results/ does)",
              True)
    except (TypeError, ValueError) as exc:
        check("the whole run result JSON-serializes", False, repr(exc))


def test_9_no_other_provider_entry_moved():
    """A one-entry addition must be exactly that. If a future edit retunes scaleway's
    base_url while 'adding a provider', this is where it shows."""
    check("ollama still local-and-keyless",
          PROVIDERS["ollama"] == {"base_url": "http://localhost:11434/v1",
                                  "api_key_env": None}, f"got {PROVIDERS['ollama']!r}")
    check("scaleway untouched",
          PROVIDERS["scaleway"] == {"base_url": "https://api.scaleway.ai/v1",
                                    "api_key_env": "SCALEWAY_API_KEY"})
    check("ovh untouched",
          PROVIDERS["ovh"]["api_key_env"] == "OVH_AI_TOKEN")
    check("nebius untouched",
          PROVIDERS["nebius"] == {"base_url": "https://api.studio.nebius.com/v1",
                                  "api_key_env": "NEBIUS_API_KEY"})
    check("stub untouched", PROVIDERS["stub"] == {"base_url": None, "api_key_env": None})
    check("provider roster is exactly the 5 old ones + openrouter",
          sorted(PROVIDERS) == ["nebius", "ollama", "openrouter", "ovh", "scaleway", "stub"],
          f"got {sorted(PROVIDERS)}")


def main() -> int:
    print("OPENROUTER — provider entry + response-dialect audit\n")
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)), key=lambda f: f.__name__):
        print(f"\n{fn.__name__}")
        fn()
    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
        return 1
    print("all openrouter-dialect assertions hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
