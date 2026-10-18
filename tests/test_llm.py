"""Provider layer: configuration, retries, throttling and JSON handling, with no network."""

import httpx
import openai
import pytest
from pydantic import BaseModel

from edvak_forge.llm import factory
from edvak_forge.llm.base import LLMAuthError, LLMConfigError, LLMRateLimitError
from edvak_forge.llm.openai_compat import (
    OpenAICompatibleClient,
    RateLimiter,
    _extract_json,
    _strictify,
)
from edvak_forge.llm.providers import PROVIDERS


class Answer(BaseModel):
    value: int
    note: str | None = None


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://example.invalid"),
                          headers={"retry-after": "0"})


class _Choice:
    def __init__(self, text):
        self.message = type("M", (), {"content": text})()


class _Resp:
    def __init__(self, text):
        self.choices = [_Choice(text)]
        self.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5})()


def make_client(responses, monkeypatch) -> OpenAICompatibleClient:
    client = OpenAICompatibleClient(PROVIDERS["groq"], api_key="test", analysis_model="m",
                                    reply_model="m", max_retries=2, requests_per_minute=0)
    seq = iter(responses)

    def create(**kwargs):
        item = next(seq)
        if isinstance(item, Exception):
            raise item
        return _Resp(item)

    monkeypatch.setattr(client._client.chat.completions, "create", create)
    monkeypatch.setattr(OpenAICompatibleClient, "_sleep_backoff", staticmethod(lambda *a, **k: None))
    return client


# --- configuration ------------------------------------------------------------------------

def test_gemini_is_refused(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(LLMConfigError, match="not supported"):
        factory.build_llm_client()


def test_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(LLMConfigError, match="Unknown"):
        factory.build_llm_client()


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "cerebras")
    monkeypatch.setenv("CEREBRAS_API_KEY", "")
    with pytest.raises(LLMConfigError, match="CEREBRAS_API_KEY"):
        factory.build_llm_client()


def test_switching_provider_is_config_only(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "cerebras")
    monkeypatch.setenv("CEREBRAS_API_KEY", "dummy")
    monkeypatch.setenv("LLM_CACHE", "0")
    client = factory.build_llm_client()
    assert client.provider == "cerebras" and client.model_for("analysis") == "gpt-oss-120b"


def test_every_provider_has_required_fields():
    assert "gemini" not in PROVIDERS
    for p in PROVIDERS.values():
        assert p.base_url.startswith("http")


# --- behaviour ----------------------------------------------------------------------------

def test_retries_rate_limit_then_succeeds(monkeypatch):
    err = openai.RateLimitError("slow down", response=_response(429), body=None)
    client = make_client([err, '{"value": 3, "note": null}'], monkeypatch)
    assert client.complete_json(system="s", user="u", schema=Answer, role="analysis").value == 3
    assert client.usage.requests == 1


def test_rate_limit_exhausted_raises_normalised_error(monkeypatch):
    err = openai.RateLimitError("slow down", response=_response(429), body=None)
    client = make_client([err, err, err], monkeypatch)
    with pytest.raises(LLMRateLimitError):
        client.complete_json(system="s", user="u", schema=Answer, role="analysis")


def test_auth_error_is_not_retried(monkeypatch):
    err = openai.AuthenticationError("bad key", response=_response(401), body=None)
    client = make_client([err], monkeypatch)
    with pytest.raises(LLMAuthError):
        client.complete_json(system="s", user="u", schema=Answer, role="analysis")


def test_invalid_json_gets_one_repair_retry(monkeypatch):
    client = make_client(['{"value": "lots"}', '{"value": 4, "note": null}'], monkeypatch)
    assert client.complete_json(system="s", user="u", schema=Answer, role="analysis").value == 4


def test_extract_json_from_fenced_output():
    assert _extract_json('Here:\n```json\n{"value": 1}\n```') == '{"value": 1}'


def test_strictify_requires_all_fields_and_forbids_extras():
    schema = _strictify(Answer.model_json_schema())
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"value", "note"}


def test_rate_limiter_allows_within_budget():
    limiter = RateLimiter(requests_per_minute=5, tokens_per_minute=1000)
    assert limiter.wait(400) == 0.0
    assert limiter.wait(400) == 0.0


def test_output_parse_failed_gets_a_repair_retry(monkeypatch):
    # Seen live: gpt-oss-20b answered in prose; Groq returned 400 output_parse_failed.
    err = openai.BadRequestError("bad", response=_response(400), body={"error": {
        "code": "output_parse_failed", "message": "Parsing failed", "failed_generation": "We need to parse..."}})
    client = make_client([err, '{"value": 5, "note": null}'], monkeypatch)
    assert client.complete_json(system="s", user="u", schema=Answer, role="analysis").value == 5
