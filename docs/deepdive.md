# Deepdive: building the sandbox from parts we already own

> STATUS: working-note. Written 2026-07-18.
> Companion to [concept.md](concept.md) (the why + market validation). This is the how:
> every sandbox component mapped to existing code in `~/code/Michiel-DK/*`, with the
> blocks worth lifting. Sourced by three code-exploration passes on 2026-07-18.

## What we're building (one paragraph)

A local-first sandbox where an "agent" is a prompt + tools + a model config line, and
every agent gets an eval suite ("exam") at birth. The harness runs agents against their
exams and prints scores; the router makes swapping models (local Ollama ↔ EU-hosted ↔
frontier) a one-line change. New model drops → rerun all exams → diff table → swap or
keep. Agents are disposable; exams compound.

```
agents/            one folder per agent: prompt.md + agent.yaml (model, tools, tier)
evals/             one folder per agent: cases.json (golden) + properties.py + snapshot.json
sandbox/           runner.py · router.py · retry.py · watcher.py · serve.py
harness/           roger3000-dev submodule (shared build methodology, repo convention)
docs/              concept.md · deepdive.md (this file)
```

---

## The steal map

### 1. Model router — `mast/mast/llm/provider.py` (private, not in this snapshot) + `restaurant-brain/app/ingestion/invoices.py` (private, not in this snapshot)

The single best steal in any repo. mast already has a provider-neutral ABC with concrete
adapters and an env-var factory with a cached singleton:

```python
# mast/mast/llm/provider.py — pattern
class LLMProvider(ABC):
    def generate(self, ...): ...
    def embed(self, ...): ...

_VALID_PROVIDERS = {"gemini", "openai"}

def get_provider(api_key=None) -> LLMProvider:
    provider_name = os.environ.get("LLM_PROVIDER", "gemini").lower().strip()
    if _singleton is not None and _singleton_key == provider_name and api_key is None:
        return _singleton
    if provider_name not in _VALID_PROVIDERS:
        raise ValueError(f"Unknown LLM_PROVIDER={provider_name!r}")
    adapter = GeminiAdapter(api_key) if provider_name == "gemini" else OpenAIAdapter(api_key)
```

**Adaptation:** add an `OllamaAdapter` — Ollama exposes an OpenAI-compatible endpoint at
`localhost:11434/v1`, and Scaleway/OVH/Nebius are all OpenAI-compatible too, so ONE
`OpenAICompatAdapter(base_url, api_key, model)` covers local + all three EU providers.
The sovereignty ladder becomes pure config.

restaurant-brain contributes the graceful fallback chain (capability flags on a
pydantic-settings object, explicit preference order, offline stub last — so the harness
runs with zero keys):

```python
# restaurant-brain/app/ingestion/invoices.py::get_extractor — pattern
def get_extractor(settings=None):
    settings = settings or get_settings()
    if settings.has_gemini:  return GeminiInvoiceExtractor(settings)
    if settings.has_llm:     return ClaudeInvoiceExtractor(settings)
    return StubInvoiceExtractor()   # offline stub → harness testable without any API key
```

And mast's config shows per-task model tiering (cheap model for cheap tasks), which is the
per-agent `tier:` field in `agent.yaml`:

```python
# mast/mast/config.py — pattern
GEMINI_SCRAPING_MODEL   = "gemini-2.5-flash"
GEMINI_CLASSIFIER_MODEL = "gemini-3.1-flash-lite"   # ~40% cheaper for cheap tasks
```

### 2. Retry + parsing — `mast/mast/agents/_llm_retry.py` (private, not in this snapshot)

Framework-free, and makes the crucial distinction the naive loop misses: "the API flaked"
(backoff, retry the call) vs "the model returned garbage JSON" (re-ask the model). Lift
nearly verbatim:

```python
# mast/mast/agents/_llm_retry.py — pattern
def call_with_retry(call_fn, parse_fn, *, api_attempts=3, parse_attempts=2, ...):
    for parse_round in range(parse_attempts):
        response = _call_with_api_backoff(call_fn, api_attempts=api_attempts, ...)
        try:
            return parse_fn(response)              # e.g. json.loads(r.text)
        except parse_exceptions:
            if parse_round < parse_attempts - 1:
                sleep(backoff); continue
            raise                                   # loud failure — never a placeholder
```

For small local models that wrap JSON in prose, add the pragmatic extractor from
`stock_agent/my_pa.py` (~line 1049) as the parse_fn's first step:
`re.search(r'\{.*\}', llm_output, re.DOTALL)` → `json.loads`.

### 3. Structured output + fail-loud — `restaurant-brain/app/ingestion/invoices.py` (private, not in this snapshot)

The extraction contract: every provider returns the SAME Pydantic model via native
structured output, and a null parse **raises** instead of degrading to a valid-looking
empty object:

```python
# restaurant-brain — pattern
response = client.models.generate_content(
    model=self._settings.gemini_model,
    contents=[...],
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=InvoiceExtract,             # a Pydantic class, directly
    ),
)
extract = response.parsed
if not isinstance(extract, InvoiceExtract):
    raise ValueError("refusing to emit an empty result")   # fail-loud
```

Two mast add-ons: the schema gotcha from `_report_schemas.py` (a property-less
`{"type": "object"}` is silently accepted and returns EMPTY — every object must declare
`properties`), and the validation chokepoint from `_extraction_validator.py` (a typed
`ExtractionFailedError` raised inside the lowest-level function so no caller can bypass
the gate).

### 4. Eval runner — mast golden harnesses + roger3000-dev skill-eval

The canonical runner shape already exists in `mast/scripts/analysis/match_golden_harness.py` (private, not in this snapshot):

```
python sandbox/runner.py <agent>            # capture: run exam, write snapshot
python sandbox/runner.py <agent> --check    # compare vs snapshot, exit 1 on regression
                                            #   (with --tolerance for fuzzy metrics)
```

Frozen golden inputs + committed snapshot + a `--check` gate = deterministic, CI-safe,
diffable. mast's `tests/golden/*.json` fixtures show the file format. roger3000-dev's
`skill-eval/trigger-eval.js` shows the per-case JSON convention worth copying —
POSITIVE cases (must pass) and NEGATIVE cases (must NOT match) in one file — and
`scorecard.js` shows the roll-up: weighted 0–100 with grade→exit-code
(A/B exit 0, C exit 1, F exit 2), and any unparseable sub-check scoring 0 rather than
being skipped.

### 5. Scoring theory — `rlvr-codegen/docs/` (docs-only repo, but the right docs)

Three principles to bake into `evals/` from day one:

- **Train/held-out split** (`04-reward-hacking.md`): the cases you iterate prompts against
  and the cases you report scores from must be different sets. Otherwise "improving the
  agent" silently becomes "overfitting the exam."
- **Property-based checks over fixed assertions**: properties ("reply ≤150 words, same
  language as input, no invented prices") run on ANY input including live traffic, and are
  much harder to overfit than golden answers.
- **pass@k with confidence intervals** (`05-build-plan.md`): for flaky tasks, run k
  samples and report the estimator, not a single lucky run. (Matches ReliabilityBench's
  finding that pass@1 overstates reliability 20–40%.)

### 6. LLM-as-judge + groundedness — `mast/mast/agents/_claim_auditor.py` (private, not in this snapshot) + `restaurant-brain/app/ingestion/recipes.py` (private, not in this snapshot)

For qualitative outputs, mast has a production judge: every claim in a generated report
gets a `verified | fabricated | unverifiable` verdict against a context dict, then a
redaction policy rewrites the output:

```python
# mast/_claim_auditor.py — pattern
if policy == "strip" and verdict == "fabricated":
    rewritten = _safe_replace(rewritten, claim_text, "[claim removed: not in context]")
elif policy == "annotate" and verdict in ("fabricated", "unverifiable"):
    tag = " (fabricated)" if verdict == "fabricated" else " (unverified)"
```

restaurant-brain has the cheaper, stronger trick for anything RAG-shaped — don't judge
groundedness after the fact, make ungrounded output structurally impossible: the LLM may
only *pick from a supplied candidate list*, and deterministic code independently
re-validates every pick against real DB rows, dropping hallucinated names. "The model
chose the ingredients; the graph keeps the numbers." Steal this as the default design for
any agent that answers from company data.

Also relevant: `mast/matching/reranker.py` (private, not in this snapshot) (LLM grades a batch of N candidates and
re-sorts, preserving order for ungraded items) — the head-to-head "which model's output is
better" comparator for the model-swap diff table. Its docstring honestly flags the
circularity caveat: never let the judge be the model under test.

### 7. Bounded, explainable scores — `restaurant-brain/app/services/confidence.py` (private, not in this snapshot)

For the roll-up per agent: every factor bounded to [0,1], documented weights, and an
exception-queue gate that returns items only below a confidence ceiling — when everything
scores well, output falls silent instead of forcing a top-N:

```python
# restaurant-brain/confidence.py — pattern
uncertainty = round(_W_STALE * staleness + _W_VOL * volatility, 4)
confidence  = round(1.0 - uncertainty, 4)
priority    = round(uncertainty * value_norm * factor, 4)
```

### 8. Agent shape + tools — `stock_agent/my_pa.py` (template, with caveats)

A complete working ReAct agent in ~5 lines — model + `@tool`-decorated functions +
checkpointer memory:

```python
# stock_agent/my_pa.py — pattern
model = init_chat_model("gemini-2.5-flash", model_provider="google_genai")
tools = [requests_tool, wikipedia_tool, get_news, sql_query, ...]
agent_executor = create_react_agent(model, tools, checkpointer=MemorySaver(),
                                    prompt=SYSTEM_PROMPT)
```

Caveats from the sweep: do NOT copy its rough edges (`ipdb.set_trace()` left in
`news.py`, bare `except:`, hardcoded paths). And for the MVP we may not need LangGraph at
all — a plain tool-loop over the provider adapter keeps chains short by construction
(the compounding-error argument) and avoids a heavyweight dependency. Decide at build
time; the `@tool` registry shape is worth keeping either way.

### 9. Scheduling + resilient fan-out — `repo-radar-cron` + `tracker`

The release-trigger loop is exactly repo-radar-cron's shape, free on GitHub Actions:

```yaml
# repo-radar-cron/.github/workflows/daily.yml — pattern
on:
  schedule: [{cron: "0 6 * * *"}]
  workflow_dispatch:
concurrency: {group: daily, cancel-in-progress: false}
# best-effort steps: `|| echo "[warn] …; continuing"`
# store = commit the JSONL snapshot back to the repo
```

(Header comment documents the real lesson: laptop `launchd` fails because the Mac sleeps;
plus the 60-day GitHub Actions inactivity pause gotcha.)

From the same repo, the resilient enrichment loop — every external call wraps in
try/except that writes an `enrich_error` field instead of killing the batch. From
tracker: "one cron tick = one job" with per-error-class handling
(`update_weekly.py`), and the Postgres `COPY`-via-StringIO bulk sink if results ever
outgrow JSONL.

### 10. Local embeddings (if an agent needs retrieval) — `stock_agent/description_clustering/`

`finbert_hb_cluster.py` runs a local HuggingFace transformer in batches for embeddings
(no API), `clusterlookup.py` does top-k cosine retrieval over a precomputed table. For the
sandbox, swap FinBERT for `nomic-embed` via Ollama (already running for agentmemory) —
but the batched-embed + top-k shape is the same.

---

## What does NOT exist anywhere (net-new code)

Honest inventory — the sweep found no Ollama client code in any repo (agentmemory uses it
but via its own stack), no eval-diff-across-models table, and no release watcher. All
three are small:

1. **`OpenAICompatAdapter`** (~30 lines): covers Ollama local + Scaleway + OVH + Nebius.
2. **The diff table** (~50 lines): run every agent's exam on model A and model B, print
   the swap/keep table. This is the demo moment and it's just a nested loop.
3. **Release watcher** (~40 lines): poll Ollama's registry / provider model lists, diff
   against a known-models file, trigger the exam rerun. Cron-shaped → pattern 9.

## Build order

| # | Step | Steals from | Net-new |
|---|------|------------|---------|
| 1 | `sandbox/router.py` — ABC + OpenAICompatAdapter + stub | mast provider.py, restaurant-brain get_extractor | ~30 lines |
| 2 | `sandbox/retry.py` | mast _llm_retry.py | ~0 |
| 3 | First agent (`agents/email-triage/` or expense-cat) + Pydantic schema | restaurant-brain invoices.py | prompt + schema |
| 4 | `evals/<agent>/cases.json` (8–10 real cases, train/held-out split) | skill-eval case format, rlvr split | the cases |
| 5 | `sandbox/runner.py` with `--check` + scorecard roll-up | mast golden harness, scorecard.js | ~150 lines |
| 6 | Second model in config → first diff table | — | ~50 lines |
| 7 | Release watcher on GitHub Actions | repo-radar-cron daily.yml | ~40 lines |
| 8 | (later) judges.py: claim-auditor-style groundedness for qualitative agents | mast _claim_auditor.py | adaptation |

Steps 1–6 are the MVP: after them, "new model dropped, which agents should switch?" is
answerable in one command. 1–3 evenings of work at the stated line counts.

## Provenance

Three Explore-agent sweeps over `mast`, `roger3000-dev`, `restaurant-brain`,
`stock_agent`, `repo-radar(-cron)`, `rlvr-codegen`, `tracker` on 2026-07-18. Excerpts
above are patterns, not verbatim lifts — check the named file before copying; line
numbers drift.
