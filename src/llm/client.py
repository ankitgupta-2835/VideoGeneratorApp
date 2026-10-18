"""LLM client abstraction.

One small interface (:class:`LLMClient`) with three real providers
(Gemini, Groq, OpenRouter — all OpenAI-compatible except Gemini) plus a
:class:`FakeLLMClient` for tests. Provider selection is driven by
:class:`src.secrets.Secrets`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, runtime_checkable

from src.errors import ProviderError
from src.http_client import HttpClient
from src.secrets import Secrets

__all__ = [
    "FakeLLMClient",
    "GeminiClient",
    "GroqClient",
    "LLMClient",
    "OpenAICompatibleClient",
    "OpenRouterClient",
    "build_llm_client",
    "parse_json",
]

# Default free-tier models.
DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
}


@runtime_checkable
class LLMClient(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str: ...

    def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
    ) -> Any: ...


def parse_json(text: str) -> Any:
    """Parse JSON from an LLM reply, tolerating ```json fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"LLM did not return valid JSON: {exc}") from exc


class _JsonMixin:
    def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
    ) -> Any:
        raw = self.complete(  # type: ignore[attr-defined]
            prompt, system=system, json_mode=True, temperature=temperature
        )
        return parse_json(raw)


class OpenAICompatibleClient(_JsonMixin):
    """Client for OpenAI-compatible chat-completions APIs (Groq, OpenRouter)."""

    def __init__(
        self,
        http: HttpClient,
        api_key: str,
        model: str,
        base_url: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._extra_headers = extra_headers or {}

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key}", **self._extra_headers}
        data = self._http.post_json(self._url, json_body=body, headers=headers)
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected LLM response shape: {data!r}") from exc


class GroqClient(OpenAICompatibleClient):
    def __init__(self, http: HttpClient, api_key: str, model: str = DEFAULT_MODELS["groq"]) -> None:
        super().__init__(http, api_key, model, "https://api.groq.com/openai/v1")


class OpenRouterClient(OpenAICompatibleClient):
    def __init__(
        self, http: HttpClient, api_key: str, model: str = DEFAULT_MODELS["openrouter"]
    ) -> None:
        super().__init__(http, api_key, model, "https://openrouter.ai/api/v1")


class GeminiClient(_JsonMixin):
    _BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self, http: HttpClient, api_key: str, model: str = DEFAULT_MODELS["gemini"]
    ) -> None:
        self._http = http
        self._api_key = api_key
        self.model = model

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        url = f"{self._BASE}/{self.model}:generateContent"
        gen_config: dict[str, Any] = {"temperature": temperature}
        if json_mode:
            gen_config["responseMimeType"] = "application/json"
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = self._http.post_json(url, json_body=body, headers={"x-goog-api-key": self._api_key})
        try:
            return str(data["candidates"][0]["content"]["parts"][0]["text"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected Gemini response shape: {data!r}") from exc


class FakeLLMClient:
    """Deterministic client for tests. Returns queued replies in order."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[dict[str, Any]] = []
        self._default = "{}"

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        self.calls.append(
            {"prompt": prompt, "system": system, "json_mode": json_mode, "temperature": temperature}
        )
        if self.replies:
            return self.replies.pop(0)
        return self._default

    def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
    ) -> Any:
        return parse_json(
            self.complete(prompt, system=system, json_mode=True, temperature=temperature)
        )


def build_llm_client(
    secrets: Secrets,
    *,
    http: HttpClient | None = None,
    model: str | None = None,
) -> LLMClient:
    """Build the LLM client selected by ``secrets.llm_provider``."""
    key = secrets.llm_api_key.get_secret_value()
    http = http or HttpClient()
    provider = secrets.llm_provider
    if provider == "gemini":
        return GeminiClient(http, key, model or DEFAULT_MODELS["gemini"])
    if provider == "groq":
        return GroqClient(http, key, model or DEFAULT_MODELS["groq"])
    if provider == "openrouter":
        return OpenRouterClient(http, key, model or DEFAULT_MODELS["openrouter"])
    raise ProviderError(f"unknown LLM provider: {provider}")
