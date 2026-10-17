# AI integration

How the agent uses AI models, which free providers work, how to get a key, and how to switch providers.

## How the agent uses the model

The model is called at most **twice per message** ([ADR 0006](decisions/0006-planner-executor-agent.md)):

| Call | Role name | Default Groq model | Input | Output |
|---|---|---|---|---|
| 1 | `analysis` | `openai/gpt-oss-120b` | Policy summary, 3-week calendar, the message | Structured `Analysis` JSON: intents, urgency, requests |
| 2 | `reply` | `openai/gpt-oss-20b` | Language, sender's first name, list of facts | `{"reply": "..."}` |

Emergencies detected by the guard make **no** model call. Emergency replies are never model-written.

Two different models are used on Groq because its limits are **per model**, so this doubles the usable budget. The reply task is simple and the smaller model handles it. Every reply is checked for faithfulness in code anyway.

## Code structure

| File | Purpose |
|---|---|
| `llm/base.py` | The `LLMClient` interface, normalised error types, token usage accounting |
| `llm/providers.py` | Registry: base URL, key variable, default models, throttle defaults, JSON-schema support, extra request fields |
| `llm/openai_compat.py` | The single adapter for all OpenAI-compatible providers: timeout, retries, throttle, JSON parsing and repair |
| `llm/cache.py` | On-disk response cache in `runs/llm_cache/` |
| `llm/factory.py` | Builds the client from environment variables; rejects Gemini; clear errors for missing keys |

Nothing outside `llm/` imports a provider SDK. The agent depends only on `LLMClient.complete_json(system, user, schema, role)`.

## Supported providers

| `LLM_PROVIDER` | Analysis model | Reply model | Key variable | Get a free key |
|---|---|---|---|---|
| `groq` (default) | `openai/gpt-oss-120b` | `openai/gpt-oss-20b` | `GROQ_API_KEY` | https://console.groq.com/keys |
| `cerebras` | `gpt-oss-120b` | `gpt-oss-120b` | `CEREBRAS_API_KEY` | https://cloud.cerebras.ai |
| `openrouter` | set `LLM_MODEL` | same as analysis | `OPENROUTER_API_KEY` | https://openrouter.ai/keys |
| `mistral` | `mistral-small-latest` | `mistral-small-latest` | `MISTRAL_API_KEY` | https://console.mistral.ai |
| `ollama` | set `LLM_MODEL` | same as analysis | none | https://ollama.com (local) |

Gemini is deliberately excluded. Setting `LLM_PROVIDER=gemini` produces an error.

Only Groq has been run end to end in this project. The others are configured from their official documentation but **not yet verified with a live run**.

## How to get a Groq key

1. Go to https://console.groq.com and sign up. No credit card is needed.
2. Open **API Keys**, click **Create API Key**, and copy it. You will not see it again.
3. In the project folder, copy `.env.example` to `.env`.
4. Paste the key after `GROQ_API_KEY=` in `.env`.
5. Check your limits under **Settings → Limits** in the Groq console.

## How to switch providers

1. Get a key for the new provider from the table above.
2. In `.env`, set `LLM_PROVIDER` and the provider's key variable.
3. Optionally set `LLM_MODEL` and `LLM_REPLY_MODEL`.

No code changes are needed. The output format can't change between providers. Model output is validated against the same Pydantic schemas, and the final result is built by code. Providers without strict JSON-schema support get JSON mode plus the schema in the prompt, followed by the same validation.

To add a new OpenAI-compatible provider, add one entry to `llm/providers.py`. To add one that isn't OpenAI-compatible, write a class with `provider`, `usage`, `model_for()` and `complete_json()`, and return it from the factory.

## Free-tier limits

| Provider | Limits | Source |
|---|---|---|
| Groq | **1,000 requests/day and 8,000 tokens/minute per model** | Measured from this account's response headers, 2026-10-18 |
| Cerebras | 5 requests/min, 30K uncached tokens/min, 1M tokens/day (free trial) | Official docs, 2026-10-18 |
| OpenRouter | `:free` models: 20 requests/min; 50/day, or 1,000/day after buying 10 credits once | Official docs, 2026-10-18 |
| Mistral | Free tier exists; numbers only in the console | Official docs, 2026-10-18 |
| Ollama | None (local) | — |

Free tiers can change or end at any time. Nothing in the code depends on one vendor.

## Cost of a run

On free tiers the cost is **$0**. Each run prints its token usage and saves it in `runs/<time>/summary.json`. See [testing.md](testing.md) for measured numbers.

## Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `groq` | Which provider to use |
| `LLM_MODEL` | provider default | Model for message analysis |
| `LLM_REPLY_MODEL` | provider default | Model for writing replies |
| `LLM_BASE_URL` | provider default | Override the endpoint |
| `<PROVIDER>_API_KEY` | — | The key for the chosen provider |
| `LLM_TIMEOUT_SECONDS` | 60 | Give up on one request after this long |
| `LLM_MAX_RETRIES` | 4 | Retries on 429, timeouts, network errors and 5xx |
| `LLM_MAX_REQUESTS_PER_MINUTE` | provider default | Override the client-side request throttle |
| `LLM_CACHE` | 1 | `1` reuses cached responses for identical requests; `0` always calls the model |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `GROQ_API_KEY is not set` | No key in `.env` | Add it (see above) |
| `authentication failed` | Key wrong or revoked | Create a new key |
| `model ... not found` | Model retired or not on your plan | Set `LLM_MODEL` to a model listed in your console |
| Long pauses during a run | Client throttle waiting for the per-minute budget | Normal on free tiers |
| Many `fallback_no_model` in the summary | Rate limit after retries, or the daily cap reached | Wait for the reset, switch provider, or rerun (cached results are reused) |
| Results don't change after editing prompts | Cache is keyed on the full prompt, so edits do invalidate it | Set `LLM_CACHE=0` to force fresh calls |
