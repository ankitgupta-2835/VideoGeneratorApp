"""Cloudflare Workers AI image client (free FLUX.1 schnell tier)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from src.errors import ProviderError
from src.visuals.images_cloudflare import CloudflareImageClient


class FakeHTTP:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def post_json(self, url: str, *, json_body=None, headers=None):
        self.calls.append({"url": url, "body": json_body, "headers": headers})
        return self.payload


def _client(tmp_path: Path, payload: object) -> tuple[CloudflareImageClient, FakeHTTP]:
    http = FakeHTTP(payload)
    client = CloudflareImageClient(
        http,  # type: ignore[arg-type]
        tmp_path / "cache",
        account_id="acct",
        token="secret-token",
    )
    return client, http


def test_generate_decodes_base64_and_caches(tmp_path: Path):
    encoded = base64.b64encode(b"jpeg-bytes").decode()
    client, http = _client(tmp_path, {"success": True, "result": {"image": encoded}})

    first = client.generate("a quiet office at night")
    second = client.generate("a quiet office at night")

    assert first == second
    assert first.read_bytes() == b"jpeg-bytes"
    assert len(http.calls) == 1
    call = http.calls[0]
    assert "accounts/acct/ai/run/@cf/black-forest-labs/flux-1-schnell" in call["url"]
    assert call["body"]["prompt"] == "a quiet office at night"
    assert call["headers"] == {"Authorization": "Bearer secret-token"}


def test_api_error_is_a_provider_error(tmp_path: Path):
    client, _ = _client(
        tmp_path,
        {"success": False, "errors": [{"message": "daily free allocation exhausted"}]},
    )

    with pytest.raises(ProviderError, match="daily free allocation"):
        client.generate("anything")


def test_missing_image_is_a_provider_error(tmp_path: Path):
    client, _ = _client(tmp_path, {"success": True, "result": {}})

    with pytest.raises(ProviderError, match="no image"):
        client.generate("anything")
