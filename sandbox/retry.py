"""Retry + parse helpers. Pattern lifted from mast/mast/agents/_llm_retry.py:
"the API flaked" (backoff, re-call) is a different failure than "the model returned
garbage" (re-ask the model). Both bounded; final failure is loud, never a placeholder.
"""
from __future__ import annotations

import json
import re
import time

import requests


def _iter_top_level_objects(text: str):
    """Yield each top-level JSON value found in the text, nested braces included.

    raw_decode consumes a complete value, so inner objects of a parsed value are
    never yielded separately (a flat-regex approach returned fragments of nested
    output like {"criteria": [...]} — the judge's verdicts vanished)."""
    dec = json.JSONDecoder()
    i = 0
    while True:
        start = text.find("{", i)
        if start == -1:
            return
        try:
            obj, consumed = dec.raw_decode(text[start:])
            yield obj
            i = start + consumed
        except ValueError:
            i = start + 1


def extract_json(text: str) -> dict:
    """Parse a JSON object out of model output that may wrap it in prose, fences,
    or think-tags. Direct parse first; otherwise the LAST top-level object wins
    (reasoning models emit thinking before the answer)."""
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except ValueError:
        pass
    objs = [o for o in _iter_top_level_objects(text) if isinstance(o, dict)]
    if objs:
        return objs[-1]
    raise ValueError(f"no JSON object found in model output: {text[:200]!r}")


def _backoff(round_: int, base: float, cap: float) -> float:
    return min(cap, base * (2 ** round_))


def call_with_retry(call_fn, parse_fn=extract_json, *, api_attempts: int = 3,
                    parse_attempts: int = 2, base_delay: float = 2.0,
                    max_delay: float = 10.0, sleep=time.sleep):
    """call_fn() -> (raw text, meta); parse_fn(raw) -> parsed.
    Returns (parsed, raw, meta, retries) — retries is the count of call_fn()
    invocations actually consumed beyond the first (0 on a clean first try), folding
    in both API-level retries (connection/timeout/5xx) and parse-level re-asks."""
    attempts = 0
    for parse_round in range(parse_attempts):
        raw, meta = None, None
        for api_round in range(api_attempts):
            try:
                attempts += 1
                raw, meta = call_fn()
                break
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
                if api_round == api_attempts - 1:
                    raise
                sleep(_backoff(api_round, base_delay, max_delay))
        try:
            return parse_fn(raw), raw, meta, attempts - 1
        except (TypeError, ValueError):
            if parse_round == parse_attempts - 1:
                raise
            sleep(_backoff(parse_round, base_delay, max_delay))
