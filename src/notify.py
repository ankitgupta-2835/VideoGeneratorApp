"""Checkpoint notifier.

Sends the topic / video-ready / publish alerts. Backed by a Telegram bot when
configured, otherwise a no-op. A :class:`FakeNotifier` records messages for
tests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.errors import ProviderError
from src.http_client import HttpClient
from src.secrets import Secrets

__all__ = [
    "FakeNotifier",
    "Notifier",
    "NullNotifier",
    "TelegramNotifier",
    "build_notifier",
    "checkpoint_text",
]

# Telegram hard limit is 4096 characters.
_TELEGRAM_LIMIT = 4096


def checkpoint_text(checkpoint: str, message: str, *, run_id: str | None = None) -> str:
    """Format a checkpoint alert."""
    prefix = f"[{run_id}] " if run_id else ""
    return f"{prefix}{checkpoint.upper()}: {message}"


@runtime_checkable
class Notifier(Protocol):
    def send(self, text: str) -> None: ...


class NullNotifier:
    """Does nothing (used when alerts are not configured)."""

    def send(self, text: str) -> None:  # noqa: ARG002 - intentional no-op
        return None


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, *, http: HttpClient | None = None) -> None:
        self._token = token
        self._chat_id = chat_id
        self._http = http or HttpClient()
        self._owns_http = http is None
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"

    def send(self, text: str) -> None:
        body = {
            "chat_id": self._chat_id,
            "text": text[:_TELEGRAM_LIMIT],
            "disable_web_page_preview": True,
        }
        try:
            self._http.post_json(self.url, json_body=body)
        except ProviderError as exc:
            raise ProviderError(f"telegram send failed: {exc}") from exc

    def close(self) -> None:
        if self._owns_http:
            self._http.close()


def build_notifier(secrets: Secrets, *, http: HttpClient | None = None) -> Notifier:
    """Return a Telegram notifier if configured, else a no-op notifier."""
    if secrets.telegram_bot_token is not None and secrets.telegram_chat_id:
        return TelegramNotifier(
            secrets.telegram_bot_token.get_secret_value(),
            secrets.telegram_chat_id,
            http=http,
        )
    return NullNotifier()
