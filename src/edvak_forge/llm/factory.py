"""Build the configured LLM client from environment variables.

    LLM_PROVIDER        groq | cerebras | openrouter | mistral | ollama   (default groq)
    LLM_MODEL           override the analysis model
    LLM_REPLY_MODEL     override the reply-writing model (default: provider's reply model)
    LLM_BASE_URL        override the endpoint (e.g. a proxy or another Ollama host)
    <PROVIDER>_API_KEY  the key named in providers.py
    LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES, LLM_MAX_REQUESTS_PER_MINUTE, LLM_CACHE
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from ..config import REPO_ROOT
from .base import LLMClient, LLMConfigError
from .cache import ResponseCache
from .openai_compat import OpenAICompatibleClient
from .providers import PROVIDERS

PLACEHOLDER_KEYS = {"", "your-groq-key-here"}


def build_llm_client() -> LLMClient:
    load_dotenv(REPO_ROOT / ".env", override=False)
    name = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    if name == "gemini":
        raise LLMConfigError("Gemini is not supported in this project (project rule).")
    config = PROVIDERS.get(name)
    if config is None:
        raise LLMConfigError(f"Unknown LLM_PROVIDER {name!r}. Choose one of {sorted(PROVIDERS)}.")

    api_key = None
    if config.key_env:
        api_key = os.getenv(config.key_env, "").strip()
        if api_key in PLACEHOLDER_KEYS:
            raise LLMConfigError(f"{config.key_env} is not set. Add it to .env (see .env.example).")

    analysis_model = os.getenv("LLM_MODEL") or config.analysis_model
    reply_model = os.getenv("LLM_REPLY_MODEL") or config.reply_model or analysis_model
    if not analysis_model:
        raise LLMConfigError(f"Provider {name!r} has no default model. Set LLM_MODEL in .env.")

    base_url = os.getenv("LLM_BASE_URL") or None
    if name == "ollama" and not base_url:
        base_url = os.getenv("OLLAMA_BASE_URL") or None

    rpm_env = os.getenv("LLM_MAX_REQUESTS_PER_MINUTE")
    cache = None
    if os.getenv("LLM_CACHE", "1") not in ("0", "false", "no"):
        cache = ResponseCache(REPO_ROOT / "runs" / "llm_cache")

    return OpenAICompatibleClient(
        config,
        api_key=api_key,
        analysis_model=analysis_model,
        reply_model=reply_model,  # type: ignore[arg-type]
        base_url=base_url,
        timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "4")),
        requests_per_minute=int(rpm_env) if rpm_env else None,
        cache=cache,
    )
