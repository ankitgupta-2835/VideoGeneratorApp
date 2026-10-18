"""Task 1.1 tests: HTTP client retries, backoff, errors, and caching."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from src.errors import ProviderError
from src.http_client import HttpClient


def make_client(
    handler, *, cache_dir: Path | None = None, max_retries: int = 3, backoff_base: float = 0.5
):
    sleeps: list[float] = []
    client = HttpClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        cache_dir=cache_dir,
        max_retries=max_retries,
        backoff_base=backoff_base,
        sleep=sleeps.append,
    )
    return client, sleeps


def test_get_json_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client, _ = make_client(handler)
    assert client.get_json("https://api.test/x") == {"ok": True}


def test_retries_on_500_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    client, sleeps = make_client(handler)
    assert client.get_json("https://api.test/x") == {"ok": True}
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_gives_up_after_max_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client, _ = make_client(handler, max_retries=2)
    with pytest.raises(ProviderError):
        client.get_json("https://api.test/x")


def test_respects_retry_after_header():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={})

    client, sleeps = make_client(handler)
    client.get_json("https://api.test/x")
    assert sleeps == [1.0]


def test_client_error_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    client, _ = make_client(handler)
    with pytest.raises(ProviderError, match="404"):
        client.get_json("https://api.test/x")
    assert calls["n"] == 1


def test_network_error_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client, _ = make_client(handler, max_retries=1)
    with pytest.raises(ProviderError):
        client.get_json("https://api.test/x")


def test_cache_avoids_second_request(tmp_path: Path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"n": calls["n"]})

    client, _ = make_client(handler, cache_dir=tmp_path)
    first = client.get_json("https://api.test/x", params={"a": 1})
    second = client.get_json("https://api.test/x", params={"a": 1})
    assert first == second == {"n": 1}
    assert calls["n"] == 1


def test_cache_can_be_bypassed(tmp_path: Path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"n": calls["n"]})

    client, _ = make_client(handler, cache_dir=tmp_path)
    client.get_json("https://api.test/x", use_cache=True)
    client.get_json("https://api.test/x", use_cache=False)
    assert calls["n"] == 2


def test_invalid_json_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", headers={"content-type": "text/plain"})

    client, _ = make_client(handler)
    with pytest.raises(ProviderError):
        client.get_json("https://api.test/x")


def test_get_bytes_returns_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"abc")

    client, _ = make_client(handler)
    assert client.get_bytes("https://api.test/x") == b"abc"


def test_post_json_sends_body():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"echo": True})

    client, _ = make_client(handler)
    assert client.post_json("https://api.test/x", json_body={"q": 1}) == {"echo": True}
    assert b'"q"' in captured["body"]
