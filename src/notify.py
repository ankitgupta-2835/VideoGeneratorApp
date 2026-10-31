"""Checkpoint notifier.

Sends the topic / video-ready / publish alerts. Backed by a Telegram bot when
configured, otherwise a no-op. A :class:`FakeNotifier` records messages for
tests.
"""

from __future__ import annotations

import argparse
import os
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
    "main",
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


def main(argv: list[str] | None = None) -> int:
    """Send one alert from the command line (used by CI failure hooks).

    Prefers Telegram; falls back to ``ALERT_WEBHOOK`` when only that is set.
    With no sink configured it prints a note and exits ``0`` so a missing
    optional alert never masks the real CI failure.
    """
    parser = argparse.ArgumentParser(
        prog="python -m src.notify",
        description="Send one alert through Telegram or ALERT_WEBHOOK.",
    )
    parser.add_argument(
        "text",
        nargs="?",
        default="VideoGeneratorApp alert",
        help="Message body (default: a generic alert).",
    )
    args = parser.parse_args(argv)

    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    webhook = (os.environ.get("ALERT_WEBHOOK") or "").strip()

    http = HttpClient()
    try:
        if token and chat_id:
            TelegramNotifier(token, chat_id, http=http).send(args.text)
            return 0
        if webhook:
            http.post_json(webhook, json_body={"text": args.text})
            return 0
        print("alert: no TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID or ALERT_WEBHOOK configured")
        return 0
    except ProviderError as exc:
        print(f"alert failed: {exc}")
        return 1
    finally:
        http.close()


if __name__ == "__main__":  # pragma: no cover - exercised via ``python -m``
    raise SystemExit(main())
