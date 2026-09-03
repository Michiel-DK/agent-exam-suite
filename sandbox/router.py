"""Model router: one adapter speaks the chat-completions wire format to every backend.

Local Ollama, Scaleway, OVHcloud and Nebius all expose OpenAI-compatible endpoints,
so the sovereignty ladder (local <-> EU-sovereign <-> frontier) is pure config:
a provider is just a base_url + api_key env var. Pattern lifted from
mast/mast/llm/provider.py (ABC + factory) and restaurant-brain get_extractor
(offline stub so the harness runs with zero keys).
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

import requests

# base_url values for EU providers are best-effort defaults; confirm the exact URL in
# the provider console before first use (they differ per project/region).
# E22a. This was an inline `timeout: int = 120` default that get_adapter() never
# passed, so 120s was the only value any model call in this repo had ever used —
# and a thinking model on a long input blows through it, burns retry.py's attempts
# and dies (qwen3:4b: 39 minutes to fail, docs/recap-sweep-2026-07-29.md). The
# number is unchanged on purpose: E22a makes the knob REACHABLE, it does not turn it.
DEFAULT_TIMEOUT_S = 120

PROVIDERS: dict[str, dict] = {
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key_env": None},
    "scaleway": {"base_url": "https://api.scaleway.ai/v1", "api_key_env": "SCALEWAY_API_KEY"},
    "ovh": {"base_url": "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", "api_key_env": "OVH_AI_TOKEN"},
    "nebius": {"base_url": "https://api.studio.nebius.com/v1", "api_key_env": "NEBIUS_API_KEY"},
    # OpenRouter: one key, one base_url, both open-weight AND frontier catalogs behind it.
    # ⚠️ PROBE-GRADE ONLY, never gate-grade. OpenRouter load-balances a single model id
    # across multiple backend providers per call, so temperature=0 does NOT reproduce
    # run-to-run the way the local ollama path does. Committed snapshots stay on ollama;
    # see the smoke block in the PR that added this entry.
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",
                   "api_key_env": "OPENROUTER_API_KEY"},
    "stub": {"base_url": None, "api_key_env": None},
}


# A generate() call's usage meta — token counts the provider reported for that one
# request. A count is None (never 0, never estimated) when the backend doesn't report
# it: "unknown" and "zero" are different facts and guessing collapses them.
def _empty_usage() -> dict:
    return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}


class TerminationError(Exception):
    """The model returned no answer at all — there is nothing here to score.

    Raised by ChatCompletionsAdapter.generate when `content` holds no non-whitespace
    characters. It REPLACES the `reasoning` fallback that used to substitute the
    model's thinking text: a reasoning model that drafts its answer object mid-thought
    and is cut off before ever answering was scored as if it had answered (measured
    2026-08-27, reply-draft/budget-figure-demand x qwen3:4b, heldout: finish_reason
    'length', 2048 completion tokens, 0 content chars, 8110 reasoning chars,
    run_properties ok=True with zero failed_checks — a GREEN heldout case off a run
    that emitted no answer).

    Deliberately a direct Exception subclass, for ISOLATION from the two exception
    classes this codebase already catches broadly:
      * NOT ValueError/TypeError. Those are what every case-level boundary here treats
        as "unparseable output" — runner.run_exam's `except (ValueError, TypeError)`
        (scored `error`) and judges.py's (scored "judge unparseable"). A ValueError
        subclass would be classified correctly only as long as the narrower
        `except TerminationError` clause happens to be listed FIRST; reorder or drop
        it and the death silently becomes an `error` again, which is the exact
        misattribution this lane exists to remove. The class hierarchy carries the
        distinction so no clause ordering has to.
      * NOT a requests exception — that is call_with_retry's API-retry class, and a
        socket-level retry of a model that answered fine (it just answered nothing)
        would spend real calls for nothing.

    ⚠️ What this is NOT about: it does not prevent a parse-level re-ask.
    `retry.call_with_retry`'s `except (TypeError, ValueError)` wraps only
    `parse_fn(raw)`, never `call_fn()`, so an exception raised inside `generate()`
    propagates on its first occurrence whatever its class (verified 2026-08-27: a
    ValueError-raising call_fn produces exactly ONE call_fn invocation). The number of
    real generate() calls is unchanged by this lane either way.

    `details` carries the four measured facts the case-boundary record is built from:
    {finish_reason, completion_tokens, content_chars, reasoning_chars}. finish_reason
    is CAUSE ATTRIBUTION ONLY — it never gates the raise (see the predicate comment in
    generate()).
    """

    def __init__(self, message: str, details: dict):
        super().__init__(message)
        self.details = dict(details)


class Adapter(ABC):
    @abstractmethod
    def generate(self, messages: list[dict], model: str, temperature: float = 0.0,
                 max_tokens: int = 512) -> tuple[str, dict]:
        """Return (text, meta) for a chat-completions style request. meta carries the
        provider's token usage: {prompt_tokens, completion_tokens, total_tokens},
        each an int or None when the backend didn't report it."""


class ChatCompletionsAdapter(Adapter):
    """Talks to any OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, base_url: str, api_key: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT_S, json_mode: bool = False,
                 reasoning_effort: str | None = None,
                 provider_routing: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.json_mode = json_mode
        self.reasoning_effort = reasoning_effort
        self.provider_routing = provider_routing

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # E22a: added ONLY when asked for. Every committed agent leaves json_mode off,
        # so the default request body is byte-identical to the pre-E22a one and no
        # committed score can move. Turning it on IS a behaviour change and must be
        # measured per exam, never assumed — see docs/e22-brief.md.
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        # Reasoning-effort-knob lane (2026-08-31): same shape as json_mode above, added
        # ONLY when asked for. Every committed agent leaves reasoning_effort unset, so
        # the default request body is byte-identical to the pre-this-lane one and no
        # committed score can move. This is the openai-dialect top-level key measured
        # honoured in docs/probes/reasoning-effort-2026-08-30/results.json
        # (effort_low_openai: GLM 1002->155, Kimi 682->150 completion tokens) —
        # deliberately NOT OpenRouter's nested reasoning:{effort} dialect, which was
        # also honoured but is not the shape this lane ships. No enum validation: the
        # value travels as an opaque string and an invalid one fails loudly at the
        # provider (this repo's fail-loud convention), not here.
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        # Provider-pin-knob lane (2026-09-01, rung 1 of the day-level-drift response,
        # docs/provider-pin-brief-2026-08-31.md): same shape as json_mode and
        # reasoning_effort above, added ONLY when asked for. Every committed agent
        # leaves provider_routing unset, so the default request body is byte-identical
        # to the pre-this-lane one and no committed score can move. `provider_routing`
        # travels as an opaque dict; an invalid shape fails loudly at the provider, not
        # here — this repo's fail-loud convention, same as reasoning_effort's "No enum
        # validation" above. router.py never inspects, validates, allow-lists, or
        # type-checks its keys.
        #
        # NOTE ON body["provider"] vs THIS FILE'S OTHER SENSES OF "provider": this repo
        # already uses "provider" for the backend selector (agent.yaml's `provider:
        # ollama` / `openrouter`) and for the PROVIDERS registry above. This is a THIRD,
        # unrelated sense — the routing payload OpenRouter reads under the `provider`
        # JSON key to pin which upstream backend serves one call. Verified on build day
        # 2026-09-01 against https://openrouter.ai/docs/features/provider-routing: the
        # top-level request-body key is `provider`, accepting (among others) `order`
        # (string[]) and `allow_fallbacks` (boolean) — the two fields the brief named.
        # This file does not read or care which sub-fields the caller sets.
        #
        # EMPTY-DICT DECISION: `provider_routing={}` is falsy under this truthiness
        # pattern and is treated as OFF, identically to unset — the simplest reading,
        # and consistent with how json_mode=False and reasoning_effort=None both mean
        # "send nothing extra". Pinned by a test in sandbox/test_router_knobs.py.
        if self.provider_routing:
            body["provider"] = self.provider_routing
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            data=json.dumps(body),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        # DIALECT-0 (2026-08-29, OpenRouter audit). `body["choices"][0]` was a hard index
        # on both a key and a position, and a body carrying NO choices at all raises
        # KeyError('choices') (or IndexError on `"choices": []`). Reproduced on master
        # and on this branch — it PRE-DATES the openrouter entry and is not specific to it.
        #
        # Why that matters more than a normal bug: it is caught by NOTHING here. Not
        # call_with_retry — its `except` around call_fn() is requests-only, and its
        # (TypeError, ValueError) clause wraps parse_fn(raw), never the call. Not
        # run_exam's `except (ValueError, TypeError)`. So it propagates out of the case
        # boundary and KILLS THE WHOLE RUN, which is the inverse of this repo's rule that
        # a bad response fails its case loudly.
        #
        # ⚠️ WARRANT, stated at the strength it actually has. The choices-less envelope
        # `{"error": {code, message, metadata?}}` is a DOCUMENTED body shape
        # (api-reference/errors, the ErrorResponse type). Its delivery at 200 OK for a
        # NON-streaming request is an INFERENCE from the adjacent sentence ("the returned
        # HTTP response status will be 200 OK and any error occurred while the LLM is
        # producing the output will be emitted in the response body"), NOT a shape shown
        # by any example: the skin section specifies that for non-streaming the error is
        # embedded in `choices` instead (see DECLARED GAP below). An earlier draft of this
        # comment cited that sentence as though it pinned the shape; it does not.
        # The guard does not rest on the inference — it also covers `"choices": []` and
        # any malformed body, and it converts an uncatchable crash into a scored failure.
        #
        # CAUSE RECORDING. finish_reason stays None: there was no choice to read it off,
        # and this file's rule (see D1 below) is that finish_reason is read straight off
        # the choice and NEVER defaulted or synthesized. The envelope's own code/message
        # are carried instead, as two FLAT scalars so the case record stays uniformly
        # scalar when runner.py spreads `{"cause": "no_answer", **exc.details}`.
        # ⚠️ Declared imprecision: that runner-side `cause` will read "no_answer", which
        # is literally true (no answer arrived) but does not say "the provider errored".
        # `provider_error_code` being present IS the discriminator. A real cause taxonomy
        # is runner.py's, i.e. a different file and a different lane.
        choices = body.get("choices") or []
        if not choices:
            err = body.get("error")
            err = err if isinstance(err, dict) else {}
            code, msg = err.get("code"), err.get("message")
            raise TerminationError(
                f"provider returned no choices "
                f"(error code={code!r}, message={msg!r})",
                {"finish_reason": None,
                 "completion_tokens": (body.get("usage") or {}).get("completion_tokens"),
                 "content_chars": 0,
                 "reasoning_chars": 0,
                 "provider_error_code": code,
                 "provider_error_message": msg})
        choice = choices[0]
        # DIALECT-1 (2026-08-29, OpenRouter audit). DEFENSIVE HARDENING AGAINST AN
        # UNDOCUMENTED SHAPE — `message` was a hard index, and a choice without one
        # raised the same uncatchable KeyError described above.
        #
        # ⚠️ This shape is documented NOWHERE: the chat-completion schema makes `message`
        # REQUIRED on a ChatChoice (`required: [finish_reason, index, message]`). It is
        # kept because it is a strict improvement at zero cost, not because a provider is
        # known to send it. An earlier draft justified it with an errors.md sentence that
        # is actually about the choices-less ENVELOPE (DIALECT-0) and claimed it "records
        # finish_reason='error'" on the provider-failure path — both wrong: the DOCUMENTED
        # provider-failure choice carries partial CONTENT, so it never reaches the
        # empty-content check at all (see DECLARED GAP below). What this line actually
        # buys is that a message-less choice reaches the empty-content check instead of
        # crashing the run.
        #
        # Byte-identical on every backend that returns a message.
        message = choice.get("message") or {}
        # TERMINATION-DETECT D1. Why the provider stopped generating, read straight off
        # the choice and measured BEFORE the empty-content check below so a truncated
        # response reports its REAL reason. None when the backend omits the field —
        # never defaulted to "stop", by the same rule _empty_usage states for token
        # counts: "unknown" and "stop" are different facts and guessing collapses them.
        finish_reason = choice.get("finish_reason")
        # Measured BEFORE the termination check below. If `content` were read after a
        # fallback, a truncated answer would report the reasoning text as BOTH content
        # and reasoning — double-counted, and precisely on the long cases the split
        # exists to explain.
        raw_content = message.get("content") or ""
        # DIALECT-2 (2026-08-29, OpenRouter audit). `reasoning` is the field this repo was
        # built against (Ollama's compat endpoint) and it is ALSO OpenRouter's documented
        # response field — "Reasoning tokens will appear in the `reasoning` field of each
        # message" (docs/use-cases/reasoning-tokens, raw markdown, verified 2026-08-29).
        # So OpenRouter needs no fallback and this line changes nothing for either.
        #
        # `reasoning_content` is the SECOND dialect: DeepSeek's own API and vLLM emit it
        # on the response. ⚠️ Register, stated plainly: DEFENSIVE, NOT MEASURED. It is the
        # same width as the `stop`+zero-content predicate below. OpenRouter's docs mention
        # `reasoning_content` only as a REQUEST-side alias, in the "Preserving Reasoning"
        # section about passing thinking BACK on an assistant message — it is NOT a
        # documented OpenRouter response field, and the WebFetch paraphrase that said
        # otherwise was wrong (raw markdown settled it; MEMORY.md has the standing rule).
        # No provider in PROVIDERS has been OBSERVED emitting it here.
        #
        # PRECEDENCE, stated as what the code DOES: this is a chain of `or`, so it takes
        # the FIRST NON-EMPTY of (reasoning, reasoning_content) — not "the measured field
        # always wins". The difference is observable and was measured 2026-08-29:
        # reasoning="" with reasoning_content="X"*999 reports 999, because "" is falsy and
        # the chain falls through. An earlier draft of this comment claimed `reasoning`
        # wins unconditionally; that was false, and the fixture in
        # test_openrouter_dialect.py now pins the real semantics in both directions.
        # First-non-empty is the behaviour we want (an empty string is not thinking, so
        # falling through to a backend that did report some is right) — the claim was the
        # bug, not the code. On Ollama, where `reasoning_content` is never present, the
        # second .get() cannot fire at all; that is the byte-identity pin.
        raw_reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
        content = raw_content
        # ⚠️ DECLARED GAP (2026-08-29, OpenRouter audit) — NOT FIXED IN THIS LANE.
        # OpenRouter's DOCUMENTED non-streaming provider-error response for the Chat
        # Completions skin embeds the error in the choice ALONGSIDE PARTIAL CONTENT:
        #     {"choices": [{"message": {"role": "assistant",
        #                               "content": "partial output..."},
        #                   "finish_reason": "error",
        #                   "error": {"code": 502,
        #                             "message": "Provider disconnected mid-stream",
        #                             "metadata": {"error_type": "provider_unavailable"}}}]}
        # (api-reference/errors, "Skin-Specific Error Formats" -> Chat Completions.)
        #
        # TODAY, on this branch AND on master, that partial output is scored as a NORMAL
        # ANSWER: content is non-empty so no termination fires, and `choice["error"]` is
        # never read at all. A truncated fragment of an answer is graded as the answer.
        # Measured 2026-08-29, not inferred.
        #
        # Deliberately NOT changed here: deciding that a partial-content provider error
        # should fail its case CHANGES WHAT GETS SCORED, which is a scoring decision, not
        # a provider-plumbing one, and it could move committed numbers. It is declared so
        # it is visible, and a TRIPWIRE FIXTURE in test_openrouter_dialect.py documents
        # today's behaviour so a silent change of it goes red.
        # The null-content variant of the same shape already terminates correctly (also
        # measured) and is pinned in that file too.
        # TERMINATION-DETECT D2 — the `reasoning` fallback that used to sit here is
        # GONE, not bypassed. It substituted the model's thinking text whenever
        # `content` came back empty; retry.extract_json then returned the LAST JSON
        # object in that thinking prose, so an answer object drafted mid-thought and
        # never emitted was scored as an answer. One committed HELDOUT case passed that
        # way (see TerminationError's docstring for the measurement).
        #
        # PREDICATE: `not content.strip()` — no non-whitespace answer characters,
        # REGARDLESS of finish_reason. Two deliberate widths:
        #   * finish_reason is not consulted. Gating on 'length' would NOT leave a
        #     clean-stop empty response scoring off its thinking — with the fallback
        #     deleted there is no thinking left to score off. What it would cost is
        #     ATTRIBUTION, which is this lane's entire product: the empty string would
        #     fall through to extract_json, raise, burn a parse-level re-ask (a second
        #     real generate() call on a model that already emitted nothing) and land
        #     as a generic `error` — indistinguishable from a model that produced
        #     unparseable prose. `stop` + zero content is UNOBSERVED on this box, so
        #     this width is defensive, not measured.
        #   * whitespace-only content counts as empty. This is the fallback's OWN
        #     test, character for character. Gating on len(raw_content) == 0 instead
        #     would leave "   " falling through to a substitution that no longer
        #     exists, i.e. it would reopen the hole in a different place.
        # `content_chars` in the record below is the MEASURED length (0 in every case
        # observed to date), not a restatement of the trigger.
        #
        # The old ValueError("returned empty content") — both fields empty — folds in
        # here: one exit for "there is no answer here", two recorded causes.
        if not content.strip():
            raise TerminationError(
                f"model {model!r} emitted no answer "
                f"(finish_reason={finish_reason!r}, content_chars={len(raw_content)}, "
                f"reasoning_chars={len(raw_reasoning)})",
                {"finish_reason": finish_reason,
                 "completion_tokens": (body.get("usage") or {}).get("completion_tokens"),
                 "content_chars": len(raw_content),
                 "reasoning_chars": len(raw_reasoning)})
        # VERIFIED 2026-07-21: Ollama's OpenAI-compat endpoint populates `usage`. Other
        # backends may omit it entirely — .get() on a missing/partial dict yields None
        # per field rather than guessing.
        # DIALECT-3 (2026-08-29): OpenRouter documents `usage` as ALWAYS returned for
        # non-streaming ("Usage data is always returned for non-streaming",
        # docs/api-reference/overview raw markdown) while typing it `usage?:` — so the
        # None-not-zero rule is what we keep relying on, not the promise. It also ships
        # `usage.completion_tokens_details.reasoning_tokens`, which Ollama does NOT — i.e.
        # on THIS provider a real reasoning TOKEN count exists. It is deliberately NOT
        # read here: `reasoning_chars` is a cross-provider field and filling it from a
        # token count on one backend only would make the column mean two different things.
        # Reading it belongs in its own lane, as a separately-named field.
        usage = body.get("usage") or {}
        meta = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            # CHARS, deliberately NOT tokens. VERIFIED 2026-07-29 against Ollama on both
            # endpoints: neither reports a reasoning TOKEN count — the compat `usage`
            # block carries only prompt/completion/total (no `completion_tokens_details`)
            # and the native API only `eval_count`. Both DO return the reasoning text
            # separately. A char-derived token figure would be a guess, and the comment
            # above states the rule this file lives by: never guess a token count.
            #
            # Thinking IS billed inside completion_tokens (gemma4, busy-day-standard:
            # 221 content + 2178 reasoning = 2399 chars over 628 completion tokens
            # ~= 3.8 ch/tok; content alone would be an implausible 0.35). So these two
            # explain WHERE a measured cost went, they do not add to it.
            #
            # 0 means the backend reported no separate reasoning text. On Ollama that
            # means the model emitted none. On a backend that strips reasoning before
            # returning it, 0 would understate — declared, not silently assumed.
            "content_chars": len(raw_content),
            "reasoning_chars": len(raw_reasoning),
            # D1: cause attribution for the SOFT tier (D3) — a response that was cut
            # off but still carries a parseable answer is RECORDED, never failed.
            # 'length' | 'stop' | 'tool_calls' | ... | None when the backend omits it.
            "finish_reason": finish_reason,
        }
        return content, meta


class StubAdapter(Adapter):
    """Offline stand-in so the harness (and its tests) run with no server at all."""

    def __init__(self, canned: str = '{"label": "reply_later"}'):
        self.canned = canned

    def generate(self, messages, model, temperature=0.0, max_tokens=512):
        # finish_reason is None, not "stop": the stub never talked to a backend, so
        # why generation ended is UNKNOWN here. Reporting "stop" would let a test
        # driven by the stub assert a termination fact nothing measured (D1).
        return self.canned, {**_empty_usage(), "finish_reason": None}


def get_adapter(provider: str, timeout: int | None = None,
                json_mode: bool = False,
                reasoning_effort: str | None = None,
                provider_routing: dict | None = None) -> Adapter:
    """Build the adapter for `provider` (the backend selector — ollama/openrouter/etc,
    see PROVIDERS above; NOT the routing-payload sense of "provider" described below).

    E22a: `timeout` and `json_mode` are the two knobs that work on the CURRENT
    (OpenAI-compat) endpoint. `timeout=None` means DEFAULT_TIMEOUT_S — passing None
    rather than defaulting in the signature keeps "caller said nothing" and "caller
    said 120" the same thing, so a config that omits the key cannot drift from one
    that sets it to the default.

    `reasoning_effort` (2026-08-31): opaque passthrough string, `None` by default —
    mirrors `json_mode` exactly, see ChatCompletionsAdapter.generate.

    `provider_routing` (2026-09-01): opaque passthrough dict, `None` by default —
    mirrors `json_mode`/`reasoning_effort` exactly, see ChatCompletionsAdapter.generate.
    This is the routing-payload sense of "provider" (OpenRouter's `provider` request-
    body key), unrelated to this function's own `provider` parameter (the backend
    selector) and to the PROVIDERS registry.

    NOT here: `num_ctx`. It is accepted and IGNORED by this endpoint (measured
    2026-07-29: byte-identical output, `ollama ps` stays at CONTEXT 4096). It needs
    the native /api/chat path, which is E22b — a different request AND response
    shape. Do not add it to this body and assume it took effect.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}. Valid: {sorted(PROVIDERS)}")
    if provider == "stub":
        return StubAdapter()
    cfg = PROVIDERS[provider]
    api_key = None
    if cfg["api_key_env"]:
        api_key = os.environ.get(cfg["api_key_env"])
        if not api_key:
            raise ValueError(
                f"Provider {provider!r} needs env var {cfg['api_key_env']} (not set)")
    return ChatCompletionsAdapter(
        cfg["base_url"], api_key,
        timeout=DEFAULT_TIMEOUT_S if timeout is None else timeout,
        json_mode=json_mode,
        reasoning_effort=reasoning_effort,
        provider_routing=provider_routing)
