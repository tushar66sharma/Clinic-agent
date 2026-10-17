"""Provider-independent LLM interface (see docs/ai-integration.md and ADR 0002).

Business logic depends only on `LLMClient` and the error types below. No module outside
`edvak_forge.llm` imports a provider SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------- normalised errors

class LLMError(Exception):
    """Base class. `retryable` tells callers whether trying again later could help."""
    retryable = False


class LLMAuthError(LLMError):
    """Bad or missing API key, or no access to the model."""


class LLMRateLimitError(LLMError):
    """Provider quota or rate limit hit and retries were exhausted."""
    retryable = True


class LLMTimeoutError(LLMError):
    retryable = True


class LLMUnavailableError(LLMError):
    """Network failure or provider 5xx after retries."""
    retryable = True


class LLMResponseError(LLMError):
    """The model answered, but not with valid JSON matching the expected schema."""


class LLMConfigError(LLMError):
    """Unknown provider or missing configuration."""


# ---------------------------------------------------------------- usage accounting

@dataclass
class Usage:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hits: int = 0
    by_model: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, model: str, prompt: int, completion: int, cached: bool = False) -> None:
        if cached:
            self.cache_hits += 1
            return
        self.requests += 1
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        m = self.by_model.setdefault(model, {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0})
        m["requests"] += 1
        m["prompt_tokens"] += prompt
        m["completion_tokens"] += completion

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict:
        return {"requests": self.requests, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens, "total_tokens": self.total_tokens,
                "cache_hits": self.cache_hits, "by_model": self.by_model}


# ---------------------------------------------------------------- the interface

class LLMClient(Protocol):
    """What the agent needs from any provider: a JSON answer validated against a schema."""

    provider: str
    usage: Usage

    def model_for(self, role: str) -> str:
        """Model id used for a role ("analysis" or "reply")."""
        ...

    def complete_json(self, *, system: str, user: str, schema: type[T], role: str,
                      max_tokens: int = 1200) -> T:
        """Return the model's answer parsed and validated as `schema`, or raise LLMError."""
        ...
