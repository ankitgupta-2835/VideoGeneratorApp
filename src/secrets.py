"""Typed access to secrets / environment variables.

Secrets are loaded from the process environment (optionally seeded by a local
``.env`` file via python-dotenv) and validated at startup. Secret values are
wrapped in :class:`pydantic.SecretStr` so they never appear in logs or reprs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, SecretStr, ValidationError, model_validator

__all__ = ["Secrets", "SecretsError", "load_secrets"]


class SecretsError(Exception):
    """Raised when required secrets are missing or invalid."""


#: LLM provider -> the name of the field that must hold its API key.
_PROVIDER_KEY_FIELD: dict[str, str] = {
    "gemini": "gemini_api_key",
    "groq": "groq_api_key",
    "openrouter": "openrouter_api_key",
}


class Secrets(BaseModel):
    # LLM
    llm_provider: Literal["gemini", "groq", "openrouter"] = "gemini"
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None

    # Alerts
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    alert_webhook: SecretStr | None = None

    # Media providers
    pexels_api_key: SecretStr | None = None
    pixabay_api_key: SecretStr | None = None

    # Optional upload credentials
    youtube_client_secret_en: SecretStr | None = None
    youtube_client_secret_hi: SecretStr | None = None

    @property
    def llm_api_key(self) -> SecretStr:
        """API key for the currently selected LLM provider."""
        value = getattr(self, _PROVIDER_KEY_FIELD[self.llm_provider])
        assert value is not None  # guaranteed by the validator below
        return value

    @model_validator(mode="after")
    def _require_selected_provider_key(self) -> Secrets:
        field = _PROVIDER_KEY_FIELD[self.llm_provider]
        if getattr(self, field) is None:
            raise ValueError(f"LLM_PROVIDER={self.llm_provider} requires {field.upper()} to be set")
        return self


def _clean(value: str | None) -> str | None:
    """Treat missing/blank environment values as ``None``."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_secrets(env_file: Path | str = ".env") -> Secrets:
    """Load secrets from the environment (optionally seeded from ``env_file``).

    Raises :class:`SecretsError` if the selected LLM provider has no key.
    """
    load_dotenv(env_file, override=False)
    raw: dict[str, Any] = {}
    for name in Secrets.model_fields:
        value = _clean(os.environ.get(name.upper()))
        if value is not None:  # omit blanks so model defaults/validators apply
            raw[name] = value
    try:
        return Secrets.model_validate(raw)
    except ValidationError as exc:
        raise SecretsError(f"invalid secrets/environment: {exc}") from exc
