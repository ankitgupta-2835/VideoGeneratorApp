"""Task 0.4 tests: typed secrets loading and safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.secrets import Secrets, SecretsError, load_secrets

REPO_ROOT = Path(__file__).resolve().parents[2]
MISSING_ENV = "/tmp/definitely-not-a-real-env-file"


def test_missing_provider_key_raises():
    with pytest.raises(SecretsError, match="GEMINI_API_KEY"):
        load_secrets(MISSING_ENV)


def test_loads_selected_provider_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    secrets = load_secrets(MISSING_ENV)
    assert secrets.llm_api_key.get_secret_value() == "test-key-123"


def test_blank_env_value_treated_as_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    with pytest.raises(SecretsError):
        load_secrets(MISSING_ENV)


def test_switching_provider_requires_its_own_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(SecretsError, match="GROQ_API_KEY"):
        load_secrets(MISSING_ENV)


def test_secret_values_masked_in_repr():
    secrets = Secrets(gemini_api_key="super-secret", telegram_bot_token="bot-secret")
    text = repr(secrets)
    assert "super-secret" not in text
    assert "bot-secret" not in text
    assert "**********" in text


def test_env_is_gitignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert any(line.strip() in {".env", ".env*"} for line in gitignore.splitlines())


def test_llm_model_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    secrets = load_secrets(MISSING_ENV)
    assert secrets.llm_model == "gemini-2.5-flash"


def test_llm_model_defaults_to_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    secrets = load_secrets(MISSING_ENV)
    assert secrets.llm_model is None


def test_openai_provider_requires_base_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(SecretsError, match="LLM_BASE_URL"):
        load_secrets(MISSING_ENV)


def test_openai_provider_requires_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(SecretsError, match="LLM_MODEL"):
        load_secrets(MISSING_ENV)


def test_openai_provider_loads_endpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5-7b-instruct")
    secrets = load_secrets(MISSING_ENV)
    assert secrets.llm_base_url == "http://localhost:8000/v1"
    assert secrets.llm_model == "qwen2.5-7b-instruct"
