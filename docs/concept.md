# Internal Agent Sandbox — concept

> STATUS: working-note (exploratory — no build decision made; canon may not cite this without promotion)
> Written 2026-07-18. Premises verified@2026-07-18 unless marked ⚠️ UNVERIFIED. See "Premises" below.

## What decision would this document eventually make?

None yet — that is why it is a working note. The decision it is *scoping toward*: whether
roger3000 builds an "internal agent sandbox" as (a) a leave-behind artifact of implementation
engagements, (b) a standalone conceptual prototype to learn from, or (c) not at all.

## Origin & provenance

Idea chain: Instagram reel by @realrobertgutierrez (a "decode" of Gartner's June 2025
press release) → transcript analysis → market research. Two caveats the reader must keep:

1. **The reel misattributes.** Two of its three "Gartner findings" (compounding reliability,
   frontier-velocity obsolescence) are the creator's own arguments, not Gartner's. Both
   held up under independent verification, but the Gartner byline on them is false.
2. **Circular-differentiation risk.** The "sandbox" framing came from a content creator's
   pitch, and the delivery-model differentiation ("pay someone to implement") is also his
   line. If this becomes a roger3000 offering, that lineage is named here so it isn't
   "discovered" later in a positioning doc.

## Premises (and their status)

| # | Premise | Status |
|---|---------|--------|
| P1 | Agentic AI projects fail mostly on cost/value/governance, not model capability | ✅ Gartner press release, June 2025 (via syndicated coverage; Gartner.com blocks fetchers), verified@2026-07-18 |
| P2 | Chained-step reliability compounds multiplicatively (0.9¹⁰ ≈ 35%) | ✅ Math self-evident; corroborated by multiple sources + arXiv 2601.22290; ReliabilityBench claim (pass@1 overstates by 20–40%) rank C |
| P3 | Frontier release cadence (~4–6 week competitive floor, 2026) makes long custom builds risky | ⚠️ Rank-C blog sources only (Velocity Index); directionally consistent with observed releases (Kimi K3 shipped 2026-07-16) |
| P4 | Enterprise agent-sandbox market is saturated (Copilot Studio, Gemini Enterprise, Dust, Zapier, Vellum, Kore.ai) | ✅ Existence verified; scale claims (160k orgs on Copilot Studio) rank C ⚠️ UNVERIFIED |
| P5 | EU SMB segment is underserved for sovereign agent tooling | ❌ FALSIFIED as a *software* gap (validation round 2, 2026-07-18): free self-hostable builders (Dify, n8n, Flowise, AnythingLLM) already cover SMB agent-building, incl. non-technical users. Survives only as a *service/assembly* gap — see "Validation round 2". |
| P6 | EU-sovereign inference of strong open-weights models is production-ready | ✅ Scaleway catalog verified@2026-07-18 (rank A); OVHcloud catalog verified@2026-07-18 (rank A); Nebius serves Kimi K2.6 per own catalog/docs (rank A–B) |

## What would kill this

- P5 falsified: an incumbent (Dust, Copilot Studio, or an EU-native player) already serves
  small EU orgs with sovereign hosting at SMB pricing → the commercial angle dies; only the
  learning-prototype angle survives.
- A frontier vendor ships a governed, employee-facing "build your own agent" surface with
  EU residency at SMB pricing (Microsoft is closest) → same effect, worse.
- The eval-first / disposable-agent framing turns out to already be someone's marketed
  positioning (absence in rank-C/D material proves nothing).

## Gated vs safe-regardless

- **Gated on P5:** any commercial packaging, pricing, positioning doc.
- **Safe regardless:** the conceptual MVP below — it reuses existing local stack
  (Ollama, agentmemory, mast-style harness) and produces transferable learning about
  eval-triggered model swapping even if the market angle dies.

---

## The concept

An internal sandbox where non-technical employees describe a task in plain language and
get a **scoped, permission-limited, evaluated agent** — designed around frontier velocity
rather than despite it.

**Inversion vs incumbents:** platforms sell agent-building; here the **eval harness is the
product** and agents are cheap, disposable byproducts ("cattle, not pets"). When a new
frontier model obsoletes an agent, that is the system working: the release trigger re-runs
the evals and reports which agents should switch. Durable assets: evals, data connections,
governance shell. Expected agent lifespan: months.

### Sovereignty ladder (model strategy — answer to "always local?")

Not always local. Three tiers, routed per-agent, gated by a data-classification step:

| Tier | What | When | Verified examples |
|------|------|------|-------------------|
| 1 | Truly local / on-prem small models (Ollama) | Narrow high-volume agents; PII-touching tasks; the only tier an SMB literally runs in-house | Qwen, Gemma, Mistral small models |
| 2 | EU-sovereign inference of open weights (CLOUD-Act-free where provider is EU) | Default workhorse tier | Scaleway (Paris-only DC: glm-5.2, qwen3.5-397b-a17b, gpt-oss-120b, mistral-medium-3.5, devstral-2-123b…); OVHcloud AI Endpoints (Qwen3.5/3.6, Llama 3.3 70B, gpt-oss-120b/20b; €0.04–0.6/Mtok input); Nebius Token Factory (**serves Kimi K2.6** — EU region pinning for Kimi specifically ⚠️ UNVERIFIED; Nebius is Dutch-HQ'd with Finland/France DCs, and not CLOUD-Act-immune in the way Scaleway/OVH are — check corporate structure before claiming sovereignty parity) |
| 3 | Frontier API escape hatch (Anthropic/OpenAI/Google) | Genuinely hard tasks; opt-in per agent; blocked for classified data | — |

**On Kimi specifically** (the prompt that raised this): K2.6 is a 1T-param MoE (32B active),
~MIT license below 100M MAU / $20M monthly revenue, strong agentic benchmarks (rank C,
⚠️ UNVERIFIED against independent leaderboards). Self-hosting needs H100/H200-class infra —
never "local" for an SMB. It enters only via tier 2 (Nebius serves it). Treat it as one
swappable cartridge among several, not a design anchor — K3 (2.8T) shipped via API
2026-07-16 with weights due 2026-07-27, which is premise P3 demonstrating itself mid-scoping.

### Architecture

```
┌─────────────────────────────────────────────┐
│ GOVERNANCE SHELL (durable)                  │
│  identity · scoped permissions · audit log  │
│  data classification · EU AI Act artifacts  │
├─────────────────────────────────────────────┤
│ EVAL HARNESS (durable — the real asset)     │
│  per-agent eval suite, created at agent     │
│  birth · release triggers: new model →      │
│  re-run evals → swap recommendation         │
├─────────────────────────────────────────────┤
│ MODEL ROUTER (semi-durable)                 │
│  tier 1 local ↔ tier 2 EU-sovereign ↔       │
│  tier 3 frontier (classification-gated)     │
├─────────────────────────────────────────────┤
│ AGENTS (disposable)                         │
│  plain-language spec → short chains (2–3    │
│  steps, human checkpoints — P2 math) →      │
│  scoped tools · lifespan: months            │
└─────────────────────────────────────────────┘
```

### Conceptual MVP

1. **Router + two tiers:** Ollama local + one EU provider (Scaleway or OVH; OpenAI-compatible
   APIs) with per-agent tier pinning.
2. **One agent template:** plain-language task → scoped agent + mandatory 5-case eval at birth.
3. **Release trigger:** watch model releases → re-run all evals on new model → diff report.
   Demo moment: "K3 dropped Tuesday; Wednesday the sandbox told you which of your 12 agents
   should switch."
4. **Memory:** agentmemory (already running locally).

Explicitly out of MVP scope: multi-agent chains (P2), UI polish, SSO, billing.

---

## Validation round 2 — saturation check (2026-07-18)

Prompted by the challenge "everything is saturated, no?" — answer: **yes, at the software
layer, at every tier.** The first sweep missed the open-source layer entirely.

**1. Free self-hostable agent builders are mature and cover the SMB case.** Dify
(non-technical users manage apps/prompts/knowledge bases from a UI; 4 GB RAM), n8n
(production-hardened automation primitives, German origin), Flowise (1 GB RAM,
prototyping), AnythingLLM (MIT, chat-with-docs). An SMB can self-host any of these for €0.
This falsifies the commercial-software angle of P5 — the doc's original "build a sandbox
product" framing is dead. Residual weakness in the free tier: access control is
all-or-nothing and governance is thin — which points at services, not at building another
platform. ([comparison](https://rapidclaw.dev/blog/low-code-ai-agent-platforms-compared-2026), rank C–D)

**2. The eval-first niche is taken as developer tooling, open as an SMB wrapper.**
Braintrust (CI eval on every PR, online eval on production traffic), Confident AI, MLflow,
FutureAGI, Adaline all do continuous eval / regression on model swaps. Nobody found
marketing it as a non-technical, SMB-facing "your sandbox tells you when to swap models"
surface — but the underlying capability is commoditized, so this is a thin wrapper
opportunity, not a moat. ([Braintrust](https://www.braintrust.dev/articles/best-ai-evals-tools-cicd-2025), rank B)

**3. The services side is where the demand signal is.** Done-for-you agent setup runs
$3k–12k, custom builds $15k+; claimed 41% of European SMBs run at least one production
agent and 68% report decision paralysis from too many options (rank C ⚠️ UNVERIFIED — but
decision paralysis is itself a symptom of tool saturation, i.e. the saturation *is* the
service opportunity). Timing catalyst **corrected 2026-07-31**: the Digital Omnibus
(Parliament, 2026-06-16) pushed most high-risk obligations to **Dec 2027 (Annex III) / Aug
2028 (Annex I)** — the "fully applicable Aug 2026" framing is dead. What DOES land
2026-08-02: **Article 50 transparency** (chatbot disclosure, AI-content marking) + GPAI
enforcement (Gibson Dunn / Travers Smith / DLA Piper, rank B). The sovereign angle is
unaffected (CLOUD-Act/procurement-driven, not Act-driven).
([DestiLabs](https://www.destilabs.com/blog/top-ai-agent-development-companies-2026), [Key4Web](https://key4web.it/en/ai-agents-smbs-2026/), rank C)

**Recast decision space.** The project survives as:
- **(a) Blueprint, not product:** an opinionated, reproducible assembly — Dify or n8n +
  EU-sovereign inference (Scaleway/OVH/Nebius) + eval harness + governance defaults — that
  roger3000 deploys as the leave-behind of an implementation engagement. The saturation is
  the moat for a curator: someone must pick.
- **(b) One small differentiating build:** the release-trigger/eval-diff component ("K3
  dropped Tuesday; Wednesday you knew which agents should switch"), riding on top of
  existing eval tooling rather than competing with it.
- **(c) Learning prototype:** unchanged — build the MVP router + eval-at-birth loop on the
  local stack to develop the judgment the service sells.

## Open verification items

- [ ] ~~**P5 (load-bearing):** Dust EU-hosting gate + minimum seats~~ — downgraded to
  nice-to-have: P5's software angle was falsified by the open-source layer regardless of
  what Dust's pricing says (validation round 2)
- [ ] Nebius: EU region availability for Kimi K2.6 specifically; corporate CLOUD-Act exposure
- [ ] Kimi K2.6 benchmark claims vs an independent leaderboard
- [ ] Copilot Studio: actual price/governance surface from Microsoft's own pages (rank A)
- [ ] Is "eval-first / disposable agents" already someone's marketed positioning?

## Source table

| Claim | Source | Rank | Verified |
|-------|--------|------|----------|
| Gartner: >40% agentic projects canceled by 2027; costs/value/risk controls; agent washing (~130 real vendors); 2028 predictions | [Gartner PR](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027) via [MarTech](https://martech.org/gartner-40-of-agentic-ai-projects-will-fail-making-humans-indispensable/), [Daily Brief](https://www.beri.net/article/40-percent-agentic-ai-projects-canceled-2027-gartner) | B–C | 2026-07-18 |
| Compounding error math + self-conditioning + ReliabilityBench | [Zartis](https://www.zartis.com/the-compounding-errors-problem-why-multi-agent-systems-fail-and-the-architecture-that-fixes-it/), [MindStudio](https://www.mindstudio.ai/blog/multi-agent-reliability-compounding-problem-77-percent), [arXiv 2601.22290](https://arxiv.org/pdf/2601.22290) | C (math verifiable) | 2026-07-18 |
| Release velocity: ~12 frontier releases Q1 2026, 4–6 wk floor | [Velocity Index](https://www.digitalapplied.com/blog/frontier-model-release-velocity-index-q2-2026) | C ⚠️ | 2026-07-18 |
| Scaleway catalog + Paris-only residency | [scaleway.com/en/generative-apis](https://www.scaleway.com/en/generative-apis/) | **A** | 2026-07-18 |
| OVHcloud AI Endpoints catalog + pricing | [ovhcloud.com AI Endpoints catalog](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/catalog/) | **A** | 2026-07-18 |
| Nebius serves Kimi K2.6/K2.5 | [Token Factory catalog](https://tokenfactory.nebius.com/models/catalog), [docs](https://docs.tokenfactory.nebius.com/ai-models-inference/overview) (via search snippets; catalog JS-rendered) | A–B | 2026-07-18 |
| Kimi K2.6 specs/license/benchmarks; K3 ship dates | [codersera K2.6](https://codersera.com/blog/kimi-k2-6-complete-guide-2026/), [Latent Space](https://www.latent.space/p/ainews-moonshot-kimi-k26-the-worlds), [codersera K3](https://codersera.com/blog/kimi-k3-complete-guide-2026/) | C ⚠️ | 2026-07-18 |
| Dust €29/user Pro; EU hosting gated Enterprise 100+ users | [dust.tt/home/pricing](https://dust.tt/home/pricing) via snippets (site blocks fetchers) | B ⚠️ UNVERIFIED | 2026-07-18 |
| Gemini Enterprise Agent Platform (identity/registry/gateway) | [Google Cloud blog](https://cloud.google.com/blog/products/ai-machine-learning/introducing-gemini-enterprise-agent-platform) | B | 2026-07-18 |
| Copilot Studio 160k orgs / 400k agents / $30 user/mo | [LuMay guide](https://www.lumay.ai/blogs/best-enterprise-agentic-ai-platforms-guide) | C ⚠️ UNVERIFIED | 2026-07-18 |
