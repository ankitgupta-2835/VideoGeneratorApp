"""Task 3.5 tests: stock-photo clients (Pexels + Pixabay) with no network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src.errors import ProviderError
from src.http_client import HttpClient
from src.visuals.stock import PexelsClient, PixabayClient, StockAsset, download

JPEG = b"\xff\xd8\xff\xe0mocked-jpeg-bytes"

PEXELS_BODY = {
    "photos": [
        {
            "id": 12345,
            "width": 1920,
            "height": 1080,
            "src": {
                "medium": "https://images.pexels.com/medium.jpg",
                "original": "https://images.pexels.com/original.jpg",
            },
        },
        {
            "id": 67890,
            "width": 4000,
            "height": 2250,
            "src": {
                "medium": "https://images.pexels.com/medium2.jpg",
                "original": "https://images.pexels.com/original2.jpg",
            },
        },
    ]
}

PIXABAY_BODY = {
    "hits": [
        {
            "id": 111,
            "imageWidth": 1280,
            "imageHeight": 720,
            "previewURL": "https://cdn.pixabay.com/preview.jpg",
            "largeImageURL": "https://cdn.pixabay.com/large.jpg",
        },
        {
            "id": 222,
            "imageWidth": 800,
            "imageHeight": 600,
            "previewURL": "https://cdn.pixabay.com/preview2.jpg",
            "largeImageURL": "https://cdn.pixabay.com/large2.jpg",
        },
    ]
}


def make_http(handler) -> HttpClient:
    return HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def recording_handler(requests: list[httpx.Request], body: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=json.dumps(body).encode())

    return handler


def test_pexels_search_parses_photos_and_sends_auth_header():
    requests: list[httpx.Request] = []
    http = make_http(recording_handler(requests, PEXELS_BODY))
    client = PexelsClient(http, "pexels-key")

    assets = client.search("sunset", per_page=3, orientation="portrait")

    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET"
    assert req.url.host == "api.pexels.com"
    assert req.url.path == "/v1/search"
    assert req.url.params["query"] == "sunset"
    assert req.url.params["per_page"] == "3"
    assert req.url.params["orientation"] == "portrait"
    assert req.headers["Authorization"] == "pexels-key"

    assert len(assets) == 2
    first = assets[0]
    assert isinstance(first, StockAsset)
    assert first.id == "12345"
    assert first.provider == "pexels"
    assert first.preview_url == "https://images.pexels.com/medium.jpg"
    assert first.download_url == "https://images.pexels.com/original.jpg"
    assert first.width == 1920
    assert first.height == 1080


def test_pixabay_search_parses_hits_and_sends_params():
    requests: list[httpx.Request] = []
    http = make_http(recording_handler(requests, PIXABAY_BODY))
    client = PixabayClient(http, "pixabay-key")

    assets = client.search("mountains", per_page=4, orientation="vertical")

    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET"
    assert req.url.host == "pixabay.com"
    assert req.url.params["key"] == "pixabay-key"
    assert req.url.params["q"] == "mountains"
    assert req.url.params["per_page"] == "4"
    assert req.url.params["image_type"] == "photo"
    assert req.url.params["orientation"] == "vertical"

    assert len(assets) == 2
    first = assets[0]
    assert first.id == "111"
    assert first.provider == "pixabay"
    assert first.preview_url == "https://cdn.pixabay.com/preview.jpg"
    assert first.download_url == "https://cdn.pixabay.com/large.jpg"
    assert first.width == 1280
    assert first.height == 720


def test_empty_api_key_raises_without_http_request():
    requests: list[httpx.Request] = []
    handler = recording_handler(requests, PEXELS_BODY)

    with pytest.raises(ProviderError):
        PexelsClient(make_http(handler), "   ").search("sunset")

    assert requests == []


def test_pixabay_empty_api_key_raises_without_http_request():
    requests: list[httpx.Request] = []
    handler = recording_handler(requests, PIXABAY_BODY)

    with pytest.raises(ProviderError):
        PixabayClient(make_http(handler), "").search("mountains")

    assert requests == []


def test_download_writes_bytes_and_returns_path(tmp_path: Path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=JPEG)

    asset = StockAsset(
        id="1",
        provider="pexels",
        preview_url="https://example.com/preview.jpg",
        download_url="https://example.com/full.jpg",
    )
    dest = tmp_path / "nested" / "out.jpg"

    result = download(make_http(handler), asset, dest)

    assert result == dest
    assert dest.read_bytes() == JPEG
    assert len(requests) == 1
    assert str(requests[0].url) == "https://example.com/full.jpg"


def test_download_empty_body_raises_provider_error(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    asset = StockAsset(
        id="1",
        provider="pixabay",
        preview_url="https://example.com/preview.jpg",
        download_url="https://example.com/full.jpg",
    )
    dest = tmp_path / "out.jpg"

    with pytest.raises(ProviderError):
        download(make_http(handler), asset, dest)

    assert not dest.exists()
