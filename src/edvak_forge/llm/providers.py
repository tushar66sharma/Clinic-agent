"""Registry of supported providers. Adding an OpenAI-compatible provider = one entry here.

Free-tier figures were checked on 2026-10-18 (docs/decisions/0002-llm-provider.md).
Gemini is intentionally absent (project rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    key_env: str | None  # None = no key needed (local Ollama)
    analysis_model: str | None  # None = user must set LLM_MODEL
    reply_model: str | None
    requests_per_minute: int  # client-side throttle default, kept under the free limit
    tokens_per_minute: int  # 0 = no token throttle
    supports_json_schema: bool  # response_format={"type": "json_schema"} with strict schemas
    extra_body: dict = field(default_factory=dict)  # provider-specific request fields


PROVIDERS: dict[str, ProviderConfig] = {
    # Groq free plan (measured from response headers on 2026-10-18): 1,000 requests/day and
    # 8,000 tokens/minute PER MODEL. Using a different model for replies doubles the budget.
    "groq": ProviderConfig(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        key_env="GROQ_API_KEY",
        analysis_model="openai/gpt-oss-120b",
        reply_model="openai/gpt-oss-20b",
        requests_per_minute=25,
        tokens_per_minute=7500,
        supports_json_schema=True,
        extra_body={"reasoning_effort": "low"},
    ),
    # Cerebras free trial: 5 requests/min, 30K uncached tokens/min, 1M tokens/day.
    "cerebras": ProviderConfig(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1",
        key_env="CEREBRAS_API_KEY",
        analysis_model="gpt-oss-120b",
        reply_model="gpt-oss-120b",
        requests_per_minute=4,
        tokens_per_minute=28000,
        supports_json_schema=True,
        extra_body={"reasoning_effort": "low"},
    ),
    # OpenRouter ":free" models: 20 requests/min, 50/day without purchased credits.
    "openrouter": ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        key_env="OPENROUTER_API_KEY",
        analysis_model=None,
        reply_model=None,
        requests_per_minute=15,
        tokens_per_minute=0,
        supports_json_schema=False,
    ),
    # Mistral free tier: limits shown only in the console; kept conservative.
    "mistral": ProviderConfig(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        key_env="MISTRAL_API_KEY",
        analysis_model="mistral-small-latest",
        reply_model="mistral-small-latest",
        requests_per_minute=20,
        tokens_per_minute=0,
        supports_json_schema=False,
    ),
    # Local Ollama: no key, no limits; speed depends on the machine.
    "ollama": ProviderConfig(
        name="ollama",
        base_url="http://localhost:11434/v1",
        key_env=None,
        analysis_model=None,
        reply_model=None,
        requests_per_minute=0,
        tokens_per_minute=0,
        supports_json_schema=False,
    ),
}
