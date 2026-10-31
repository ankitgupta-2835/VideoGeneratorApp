"""Task 1.4 tests: notifier (Telegram), no-op, fake, and factory."""

from __future__ import annotations

import httpx

from src.http_client import HttpClient
from src.notify import (
    FakeNotifier,
    NullNotifier,
    TelegramNotifier,
    build_notifier,
    checkpoint_text,
    main,
)
from src.secrets import Secrets


def http_for(handler) -> HttpClient:
    return HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_fake_notifier_records():
    n = FakeNotifier()
    n.send("hello")
    n.send("world")
    assert n.messages == ["hello", "world"]


def test_checkpoint_text_formats_run_id():
    assert checkpoint_text("topic", "Chose X", run_id="run-1") == "[run-1] TOPIC: Chose X"
    assert checkpoint_text("video_ready", "done") == "VIDEO_READY: done"


def test_telegram_posts_correct_request():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})

    n = TelegramNotifier("tok", "12345", http=http_for(handler))
    n.send("hello there")
    assert captured["url"].endswith("/bottok/sendMessage")
    assert "12345" in captured["body"]
    assert "hello there" in captured["body"]


def test_telegram_truncates_long_message():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})

    n = TelegramNotifier("tok", "1", http=http_for(handler))
    n.send("x" * 5000)
    assert len(captured["body"]) < 5000  # message body was truncated


def test_build_notifier_without_token_is_noop():
    assert isinstance(build_notifier(Secrets(gemini_api_key="k")), NullNotifier)


def test_build_notifier_with_token_is_telegram():
    secrets = Secrets(gemini_api_key="k", telegram_bot_token="t", telegram_chat_id="1")
    assert isinstance(build_notifier(secrets), TelegramNotifier)


def test_main_sends_telegram(monkeypatch):
    sent: list[str] = []

    class FakeTelegram:
        def __init__(self, token: str, chat_id: str, *, http=None) -> None:
            self.token = token
            self.chat_id = chat_id

        def send(self, text: str) -> None:
            sent.append(text)

    monkeypatch.setattr("src.notify.TelegramNotifier", FakeTelegram)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv("ALERT_WEBHOOK", raising=False)

    assert main(["hello from CI"]) == 0
    assert sent == ["hello from CI"]


def test_main_uses_webhook_when_telegram_is_unset(monkeypatch):
    calls: list[tuple[str, object]] = []

    class FakeHTTP:
        def post_json(self, url: str, *, json_body=None) -> None:
            calls.append((url, json_body))

        def close(self) -> None:
            return None

    monkeypatch.setattr("src.notify.HttpClient", FakeHTTP)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("ALERT_WEBHOOK", "https://example.test/hook")

    assert main(["webhook message"]) == 0
    assert calls == [("https://example.test/hook", {"text": "webhook message"})]


def test_main_without_a_sink_prints_and_succeeds(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("ALERT_WEBHOOK", raising=False)

    assert main(["no sink"]) == 0
    assert "no TELEGRAM_BOT_TOKEN" in capsys.readouterr().out
