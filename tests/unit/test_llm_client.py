"""Task 1.2 tests: LLM client abstraction, providers, factory, fake."""

from __future__ import annotations

import httpx
import pytest

from src.errors import ProviderError
from src.http_client import HttpClient
from src.llm.client import (
    FakeLLMClient,
    GeminiClient,
    GroqClient,
    OpenAICompatibleClient,
    OpenRouterClient,
    build_llm_client,
    parse_json,
)
from src.secrets import Secrets


def http_for(handler) -> HttpClient:
    return HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_json_plain():
    assert parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_strips_code_fence():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_invalid_raises():
    with pytest.raises(ProviderError):
        parse_json("not json at all")


def test_gemini_client_builds_and_parses():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers.get("x-goog-api-key")
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "hello"}]}}]},
        )

    client = GeminiClient(http_for(handler), "secret-key", "gemini-2.0-flash")
    assert client.complete("hi") == "hello"
    assert "gemini-2.0-flash" in captured["url"]
    assert captured["key"] == "secret-key"


def test_gemini_json_mode_sets_mime():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]}
        )

    client = GeminiClient(http_for(handler), "k")
    assert client.complete_json("give json") == {"ok": True}
    assert "application/json" in captured["body"]


def test_groq_client_sends_bearer_and_parses():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "yo"}}]})

    client = GroqClient(http_for(handler), "groq-key")
    assert client.complete("hi") == "yo"
    assert captured["auth"] == "Bearer groq-key"
    assert captured["url"].endswith("/chat/completions")


def test_openrouter_client_parses_json_reply():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '```json\n{"x": 2}\n```'}}]}
        )

    client = OpenRouterClient(http_for(handler), "k", "some/model:free")
    assert client.complete_json("go") == {"x": 2}


def test_unexpected_response_shape_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": True})

    client = GroqClient(http_for(handler), "k")
    with pytest.raises(ProviderError):
        client.complete("hi")


def test_fake_client_returns_queued_and_records():
    fake = FakeLLMClient(replies=['{"a": 1}'])
    assert fake.complete_json("first") == {"a": 1}
    assert fake.calls[0]["json_mode"] is True


def test_build_llm_client_selects_provider():
    secrets = Secrets(llm_provider="groq", groq_api_key="k")
    client = build_llm_client(secrets)
    assert isinstance(client, GroqClient)

    secrets2 = Secrets(llm_provider="gemini", gemini_api_key="k")
    assert isinstance(build_llm_client(secrets2), GeminiClient)


def test_build_llm_client_uses_llm_model_override():
    """``LLM_MODEL`` (Secrets.llm_model) must override the provider default."""
    secrets = Secrets(gemini_api_key="k", llm_model="gemini-flash-latest")
    client = build_llm_client(secrets, http=object())
    assert isinstance(client, GeminiClient)
    assert client.model == "gemini-flash-latest"


def test_gemini_default_model_is_a_floating_alias():
    """Pinned Gemini versions get retired for new users; the default must be
    an alias that keeps resolving (e.g. ``gemini-flash-latest``)."""
    from src.llm.client import DEFAULT_MODELS

    assert DEFAULT_MODELS["gemini"].endswith("-latest")


def test_build_openai_compatible_client_uses_base_url():
    """`LLM_PROVIDER=openai` targets any OpenAI-compatible endpoint (local vLLM,
    Ollama, Cerebras, GitHub Models, ...)."""
    secrets = Secrets(
        llm_provider="openai",
        openai_api_key="k",
        llm_base_url="http://localhost:8000/v1",
        llm_model="qwen2.5-7b-instruct",
    )
    client = build_llm_client(secrets, http=object())
    assert isinstance(client, OpenAICompatibleClient)
    assert client._url == "http://localhost:8000/v1/chat/completions"
    assert client.model == "qwen2.5-7b-instruct"
