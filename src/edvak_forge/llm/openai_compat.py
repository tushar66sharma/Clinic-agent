"""One adapter for every OpenAI-compatible provider, with the reliability features.

- Timeout per request.
- Retries with exponential backoff and jitter on 429 / 5xx / network errors, honouring the
  provider's Retry-After header.
- Client-side throttle for requests/minute and tokens/minute, so free-tier limits are respected
  before the provider has to reject anything.
- JSON output: strict JSON-schema mode where the provider supports it, otherwise JSON mode plus
  the schema in the prompt. The answer is always validated with Pydantic; one repair retry is
  made with the validation error shown to the model.
- Optional on-disk response cache, so re-running the same inputs costs nothing.
"""

from __future__ import annotations

import json
import random
import threading
import time
from collections import deque

import openai
from pydantic import ValidationError

from .base import (
    LLMAuthError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    T,
    Usage,
)
from .cache import ResponseCache
from .providers import ProviderConfig


class RateLimiter:
    """Sliding 60-second window over requests and (estimated) tokens. Thread-safe."""

    def __init__(self, requests_per_minute: int, tokens_per_minute: int) -> None:
        self.rpm = requests_per_minute
        self.tpm = tokens_per_minute
        self._events: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def wait(self, tokens: int) -> float:
        """Block until a request of `tokens` fits. Returns seconds waited."""
        if not self.rpm and not self.tpm:
            return 0.0
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                while self._events and now - self._events[0][0] >= 60:
                    self._events.popleft()
                used = sum(t for _, t in self._events)
                fits_rpm = not self.rpm or len(self._events) < self.rpm
                fits_tpm = not self.tpm or used + tokens <= self.tpm or not self._events
                if fits_rpm and fits_tpm:
                    self._events.append((now, tokens))
                    return waited
                sleep_for = max(0.5, 60 - (now - self._events[0][0]) + 0.1)
            time.sleep(sleep_for)
            waited += sleep_for

    def correct(self, estimated: int, actual: int) -> None:
        """Replace the latest estimate with the real token count from the response."""
        with self._lock:
            for i in range(len(self._events) - 1, -1, -1):
                ts, tok = self._events[i]
                if tok == estimated:
                    self._events[i] = (ts, actual)
                    return


COMPLETION_RESERVE = 700  # typical analysis output incl. low-effort reasoning; corrected after


def _estimate_tokens(*texts: str) -> int:
    return int(sum(len(t) for t in texts) / 3.5) + 50


class _SchemaRejected(Exception):
    """Provider-side strict-schema validation failed (e.g. Groq json_validate_failed)."""

    def __init__(self, generation: str, message: str) -> None:
        super().__init__(message)
        self.generation = generation


def _strictify(schema: dict) -> dict:
    """Make a Pydantic JSON schema acceptable to strict structured-output modes."""
    schema = json.loads(json.dumps(schema))

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            node.pop("default", None)
            node.pop("title", None)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema


class OpenAICompatibleClient:
    def __init__(
        self,
        config: ProviderConfig,
        *,
        api_key: str | None,
        analysis_model: str,
        reply_model: str,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 4,
        requests_per_minute: int | None = None,
        cache: ResponseCache | None = None,
    ) -> None:
        self.provider = config.name
        self.config = config
        self.usage = Usage()
        self._models = {"analysis": analysis_model, "reply": reply_model}
        self._max_retries = max_retries
        self._cache = cache
        self._client = openai.OpenAI(
            api_key=api_key or "not-needed", base_url=base_url or config.base_url,
            timeout=timeout, max_retries=0,  # retries are handled here, uniformly
        )
        rpm = config.requests_per_minute if requests_per_minute is None else requests_per_minute
        # Groq limits are per model, so each model gets its own limiter.
        self._limiters = {m: RateLimiter(rpm, config.tokens_per_minute)
                          for m in set(self._models.values())}

    def model_for(self, role: str) -> str:
        return self._models.get(role, self._models["analysis"])

    # ------------------------------------------------------------------ public

    def complete_json(self, *, system: str, user: str, schema: type[T], role: str,
                      max_tokens: int = 1200) -> T:
        model = self.model_for(role)
        json_schema = schema.model_json_schema()
        if self.config.supports_json_schema:
            response_format = {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True, "schema": _strictify(json_schema)}}
            system_full = system
        else:
            response_format = {"type": "json_object"}
            system_full = (f"{system}\n\nRespond with ONE JSON object matching this JSON schema, "
                           f"and nothing else:\n{json.dumps(json_schema)}")

        messages = [{"role": "system", "content": system_full}, {"role": "user", "content": user}]
        last_error: Exception | None = None
        for _attempt in range(2):  # first try + one repair retry
            try:
                text = self._chat(model, messages, response_format, max_tokens)
                return schema.model_validate_json(_extract_json(text))
            except _SchemaRejected as exc:
                last_error, text = exc, exc.generation or "{}"
            except (ValidationError, ValueError) as exc:
                last_error = exc
            messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That JSON was invalid: {str(last_error)[:800]}. "
                                            "Reply again with corrected JSON only."},
            ]
            if self._cache:
                self._cache.forget(self._cache_key(model, messages[:2], response_format))
        raise LLMResponseError(f"Model output did not match {schema.__name__}: {last_error}")

    # ------------------------------------------------------------------ internals

    def _cache_key(self, model, messages, response_format) -> dict:
        return {"provider": self.provider, "model": model, "messages": messages,
                "response_format": response_format, "extra": self.config.extra_body}

    def _chat(self, model: str, messages: list[dict], response_format: dict, max_tokens: int) -> str:
        key = self._cache_key(model, messages, response_format)
        if self._cache and (hit := self._cache.get(key)) is not None:
            self.usage.add(model, 0, 0, cached=True)
            return hit

        prompt_estimate = _estimate_tokens(*(m["content"] for m in messages))
        estimate = prompt_estimate + min(max_tokens, COMPLETION_RESERVE)
        limiter = self._limiters[model]
        for attempt in range(self._max_retries + 1):
            limiter.wait(estimate)
            try:
                resp = self._client.chat.completions.create(
                    model=model, messages=messages, response_format=response_format,
                    max_completion_tokens=max_tokens, temperature=0, seed=7,
                    extra_body=self.config.extra_body or None,
                )
            except openai.AuthenticationError as exc:
                raise LLMAuthError(f"{self.provider}: authentication failed. Check the API key.") from exc
            except openai.PermissionDeniedError as exc:
                raise LLMAuthError(f"{self.provider}: no access to model {model}.") from exc
            except openai.NotFoundError as exc:
                raise LLMAuthError(f"{self.provider}: model {model} not found.") from exc
            except openai.BadRequestError as exc:
                limiter.correct(estimate, prompt_estimate)
                body = getattr(exc, "body", None) or {}
                err = body.get("error", body) if isinstance(body, dict) else {}
                if isinstance(err, dict) and err.get("code") == "json_validate_failed":
                    raise _SchemaRejected(err.get("failed_generation", ""), err.get("message", "")) from exc
                raise LLMResponseError(f"{self.provider}: request rejected: {exc}") from exc
            except openai.RateLimitError as exc:
                if attempt == self._max_retries:
                    raise LLMRateLimitError(f"{self.provider}: rate limit after retries: {exc}") from exc
                self._sleep_backoff(attempt, _retry_after(exc))
                continue
            except openai.APITimeoutError as exc:
                if attempt == self._max_retries:
                    raise LLMTimeoutError(f"{self.provider}: timed out after retries.") from exc
                self._sleep_backoff(attempt)
                continue
            except (openai.APIConnectionError, openai.InternalServerError) as exc:
                if attempt == self._max_retries:
                    raise LLMUnavailableError(f"{self.provider}: unavailable: {exc}") from exc
                self._sleep_backoff(attempt)
                continue

            text = resp.choices[0].message.content or ""
            usage = resp.usage
            prompt_t = getattr(usage, "prompt_tokens", 0) or 0
            completion_t = getattr(usage, "completion_tokens", 0) or 0
            limiter.correct(estimate, prompt_t + completion_t)
            self.usage.add(model, prompt_t, completion_t)
            if self._cache:
                self._cache.put(key, text)
            return text
        raise LLMUnavailableError(f"{self.provider}: retries exhausted")  # pragma: no cover

    @staticmethod
    def _sleep_backoff(attempt: int, retry_after: float | None = None) -> None:
        delay = retry_after if retry_after else min(30.0, 2 ** attempt) + random.uniform(0, 1)
        time.sleep(min(delay, 90.0))


def _retry_after(exc: openai.APIStatusError) -> float | None:
    try:
        value = exc.response.headers.get("retry-after")
        return float(value) if value else None
    except (AttributeError, ValueError):
        return None


def _extract_json(text: str) -> str:
    """Accept a bare JSON object, or one wrapped in a ```json fence or extra prose."""
    text = text.strip()
    if text.startswith("{"):
        return text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    return text[start:end + 1]
