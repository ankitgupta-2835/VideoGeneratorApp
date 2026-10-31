"""Task 3.3 tests: Pollinations image client + disk cache."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from src.errors import ProviderError
from src.http_client import HttpClient
from src.visuals.images_pollinations import PollinationsImageClient

JPEG = b"\xff\xd8\xff\xe0mocked-jpeg-bytes"


def make_client(handler, cache_dir: Path, **kwargs):
    http = HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    return PollinationsImageClient(http, cache_dir, **kwargs), http


def recording_handler(requests: list[httpx.Request], payload: bytes = JPEG):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=payload)

    return handler


def test_first_call_issues_one_get_with_expected_query(tmp_path: Path):
    requests: list[httpx.Request] = []
    client, _ = make_client(recording_handler(requests), tmp_path)

    client.generate("a cat", width=640, height=360, seed=7, model="flux")

    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET"
    assert req.url.host == "image.pollinations.ai"
    assert " " not in str(req.url)
    assert "/prompt/a%20cat" in str(req.url)
    assert req.url.params["width"] == "640"
    assert req.url.params["height"] == "360"
    assert req.url.params["model"] == "flux"
    assert req.url.params["seed"] == "7"
    assert req.url.params["nologo"] == "true"


def test_seed_omitted_when_none(tmp_path: Path):
    requests: list[httpx.Request] = []
    client, _ = make_client(recording_handler(requests), tmp_path)

    client.generate("a cat")

    assert len(requests) == 1
    assert "seed" not in requests[0].url.params


def test_returned_file_exists_with_mocked_bytes(tmp_path: Path):
    client, _ = make_client(recording_handler([]), tmp_path)

    path = client.generate("a cat", seed=1)

    assert path.exists()
    assert path.read_bytes() == JPEG
    assert path.suffix == ".jpg"


def test_second_call_is_cache_hit_and_makes_no_request(tmp_path: Path):
    requests: list[httpx.Request] = []
    client, _ = make_client(recording_handler(requests), tmp_path)

    first = client.generate("a cat", width=640, height=360, seed=3)
    second = client.generate("a cat", width=640, height=360, seed=3)

    assert len(requests) == 1
    assert first == second


def test_different_seed_yields_new_request(tmp_path: Path):
    requests: list[httpx.Request] = []
    client, _ = make_client(recording_handler(requests), tmp_path)

    a = client.generate("a cat", seed=1)
    b = client.generate("a cat", seed=2)

    assert len(requests) == 2
    assert a != b


def test_different_size_yields_new_request(tmp_path: Path):
    requests: list[httpx.Request] = []
    client, _ = make_client(recording_handler(requests), tmp_path)

    a = client.generate("a cat", width=640, height=360, seed=1)
    b = client.generate("a cat", width=1280, height=720, seed=1)

    assert len(requests) == 2
    assert a != b


def test_prompt_is_url_encoded(tmp_path: Path):
    requests: list[httpx.Request] = []
    client, _ = make_client(recording_handler(requests), tmp_path)

    client.generate("a cat / dog on a hill", seed=1)

    req = requests[0]
    rendered = str(req.url)
    assert " " not in rendered
    assert "/prompt/a%20cat%20%2F%20dog%20on%20a%20hill" in rendered
    assert "%20" in rendered
    assert "%2F" in rendered


def test_empty_body_raises_provider_error(tmp_path: Path):
    requests: list[httpx.Request] = []
    client, _ = make_client(recording_handler(requests, payload=b""), tmp_path)

    with pytest.raises(ProviderError):
        client.generate("a cat")

    assert len(requests) == 1


def test_402_waits_retry_after_then_succeeds(tmp_path: Path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                402,
                json={
                    "error": {
                        "message": "Free limit reached: 1 image every 45 seconds. "
                        "Retry after 2s."
                    }
                },
            )
        return httpx.Response(200, content=JPEG)

    sleeps: list[float] = []
    client, _ = make_client(handler, tmp_path, sleep=sleeps.append)

    path = client.generate("a cat")

    assert path.read_bytes() == JPEG
    assert calls["n"] == 2
    assert sleeps == [3.0]


def test_token_is_forwarded_when_configured(tmp_path: Path):
    requests: list[httpx.Request] = []
    client, _ = make_client(recording_handler(requests), tmp_path, token="pollen-key")

    client.generate("a cat")

    assert requests[0].url.params["token"] == "pollen-key"
