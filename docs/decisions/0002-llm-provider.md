# ADR 0002: Free-tier LLM provider and pluggable provider layer

- **Status:** Accepted
- **Date:** 2026-10-18

## Context

Project rules require a free-tier AI provider, no Gemini, and the ability to switch providers through configuration only. The agent needs reliable **tool calling** (function calling) and **structured JSON output**.

A full evaluation run is the main load. Rough estimate: 40 messages × about 4–6 model calls each ≈ **160–240 requests**, at roughly 2–4K tokens per request ≈ **0.5–1M tokens per run**. Free-tier daily token caps are the binding limit, not requests per minute.

## Providers checked (official docs, 2026-10-18)

| Provider | Free access | Published limits found | Tool calling | Verdict |
|---|---|---|---|---|
| **Groq** | Free plan, no card | Rate-limits page lists `openai/gpt-oss-120b` at 30 req/min, 1K req/day, 8K tokens/min, 200K tokens/day, **but labels them Developer-plan base limits**. Free-plan numbers are only shown in each account's settings. | Yes (tool use, JSON schema mode). 131K context. | **Default.** Fast and OpenAI-compatible. |
| **Cerebras** | Free trial | `gpt-oss-120b`: 5 req/min, 30K uncached tokens/min, 1M tokens/day | Yes | **Fallback.** Generous daily tokens, but 5 req/min makes a full run slow (about 40+ minutes). |
| **OpenRouter** | `:free` models | 20 req/min. 50 req/day without credits, 1,000/day after buying 10 credits once | Model-dependent | **Optional.** 50/day is not enough for a full run without credits. |
| **Mistral** | Free "Experiment" tier, no card | Exact numbers only shown in the account console. Lowest tier, for prototyping. | Yes | **Optional.** |
| **Ollama (local)** | Free, runs on your machine | No rate limits. Speed depends on your hardware. | Model-dependent | **Optional.** Useful when quotas run out. |
| GitHub Models | — | **Retired 2026-07-30** per GitHub docs | — | Rejected. |
| Gemini | — | — | — | Excluded by project rule. |

Sources: [Groq rate limits](https://console.groq.com/docs/rate-limits), [Groq gpt-oss-120b](https://console.groq.com/docs/model/openai/gpt-oss-120b), [Cerebras rate limits](https://inference-docs.cerebras.ai/support/rate-limits), [OpenRouter limits](https://openrouter.ai/docs/api-reference/limits), [Mistral usage and limits](https://docs.mistral.ai/admin/user-management-finops/tier), [GitHub Models retirement](https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models).

## Decision

1. **Default provider: Groq, model `openai/gpt-oss-120b`.**
2. **All providers go through one adapter interface.** Every listed provider speaks the OpenAI Chat Completions format, so one OpenAI-compatible adapter covers all of them with a per-provider config entry (base URL, key variable, default model). A provider that is not compatible gets its own small adapter class behind the same interface. Business logic never imports a provider SDK directly.
3. **Configuration by environment variables:** `LLM_PROVIDER`, optional `LLM_MODEL` and `LLM_BASE_URL`, and one key variable per provider (see `.env.example`).
4. **Reliability is built into the adapter:** request timeout, retries with exponential backoff on 429 and 5xx, honouring `Retry-After`, a client-side requests-per-minute throttle, and normalized error types.

## Consequences and risks

- **Groq's free daily token cap may be lower than one full run needs.** If the free plan matches the published 200K tokens/day, a full run will not fit in one day on one model. Mitigations, to be applied in the agent design:
  - Keep prompts and tool schemas compact.
  - Let deterministic code do lookups and policy checks so the model needs fewer turns.
  - Cache model responses per message during development so reruns cost nothing.
  - Switch to Cerebras (1M tokens/day) or a second Groq model, which has its own quota, through config.
- **Exact free-plan limits cannot be verified from public docs for Groq and Mistral.** Each user must check the limits page in their own account. This is documented in `docs/ai-integration.md`.
- **Free tiers can change or disappear.** Nothing in the code depends on one vendor.
- **Cost:** $0 on free tiers. Real cost per run will be measured and reported by the evaluation harness (token counts per run).

## Alternatives considered

- **Paid Claude or OpenAI models.** Better tool use, but they violate the free-tier rule.
- **One provider SDK per vendor.** Rejected. More code and more ways for output to diverge between providers.
