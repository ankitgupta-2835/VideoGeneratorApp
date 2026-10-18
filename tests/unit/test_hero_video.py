"""Task 3.7 tests: hero-video client, provider cascade, image fallback."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from src.errors import ProviderError
from src.http_client import HttpClient
from src.secrets import Secrets
from src.visuals.hero_video import (
    HeroProvider,
    HeroResult,
    HeroVideoClient,
    LumaProvider,
    build_providers,
)

MP4 = b"\x00\x00\x00\x18ftypmp42mock-video-bytes"


class FakeHeroProvider:
    """Deterministic provider used to exercise the cascade."""

    def __init__(self, name: str, *, succeed: bool = True) -> None:
        self.name = name
        self.succeed = succeed
        self.calls = 0

    def generate(self, prompt: str, *, duration_sec: float, out_dir: Path) -> Path:
        self.calls += 1
        if not self.succeed:
            raise ProviderError(f"{self.name} failed")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{self.name}.mp4"
        path.write_bytes(MP4)
        return path


class RecordingFallback:
    """Stand-in for :class:`PollinationsImageClient` that records calls."""

    def __init__(self, *, succeed: bool = True) -> None:
        self.succeed = succeed
        self.calls: list[dict[str, object]] = []

    def generate(self, prompt: str, *, width: int, height: int) -> Path:
        self.calls.append({"prompt": prompt, "width": width, "height": height})
        if not self.succeed:
            raise ProviderError("pollinations failed")
        return Path("/cache/image.jpg")


def make_client(providers, fallback) -> HeroVideoClient:
    return HeroVideoClient(providers, fallback)


# --------------------------------------------------------------------------- #
# cascade
# --------------------------------------------------------------------------- #
def test_first_provider_succeeds_without_touching_the_rest(tmp_path: Path):
    first = FakeHeroProvider("first", succeed=True)
    second = FakeHeroProvider("second", succeed=True)
    fallback = RecordingFallback()
    client = make_client([first, second], fallback)

    result = client.generate("a dragon", out_dir=tmp_path)

    assert isinstance(result, HeroResult)
    assert result.kind == "hero"
    assert result.provider == "first"
    assert Path(result.path).exists()
    assert first.calls == 1
    assert second.calls == 0
    assert fallback.calls == []


def test_second_provider_used_when_first_fails(tmp_path: Path):
    first = FakeHeroProvider("first", succeed=False)
    second = FakeHeroProvider("second", succeed=True)
    fallback = RecordingFallback()
    client = make_client([first, second], fallback)

    result = client.generate("a dragon", out_dir=tmp_path)

    assert result.kind == "hero"
    assert result.provider == "second"
    assert first.calls == 1
    assert second.calls == 1
    assert fallback.calls == []


def test_all_providers_fail_falls_back_to_image(tmp_path: Path):
    first = FakeHeroProvider("first", succeed=False)
    second = FakeHeroProvider("second", succeed=False)
    fallback = RecordingFallback()
    client = make_client([first, second], fallback)

    result = client.generate("a dragon", out_dir=tmp_path, width=640, height=360)

    assert result.kind == "image"
    assert result.provider == "pollinations"
    assert result.path == "/cache/image.jpg"
    assert len(fallback.calls) == 1
    assert fallback.calls[0] == {"prompt": "a dragon", "width": 640, "height": 360}


def test_fallback_error_propagates(tmp_path: Path):
    first = FakeHeroProvider("first", succeed=False)
    fallback = RecordingFallback(succeed=False)
    client = make_client([first], fallback)

    with pytest.raises(ProviderError):
        client.generate("a dragon", out_dir=tmp_path)


def test_empty_provider_list_goes_straight_to_fallback(tmp_path: Path):
    fallback = RecordingFallback()
    client = make_client([], fallback)

    result = client.generate("a dragon", out_dir=tmp_path)

    assert result.kind == "image"
    assert result.provider == "pollinations"
    assert len(fallback.calls) == 1


def test_provider_satisfies_protocol():
    assert isinstance(FakeHeroProvider("x"), HeroProvider)
    assert isinstance(LumaProvider(HttpClient(), "key"), HeroProvider)


# --------------------------------------------------------------------------- #
# LumaProvider
# --------------------------------------------------------------------------- #
def luma_handler(requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "job1", "state": "queued"})
        if "job1" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "id": "job1",
                    "state": "completed",
                    "assets": {"video": "https://cdn.example/video.mp4"},
                },
            )
        return httpx.Response(200, content=MP4)

    return handler


def test_luma_generate_creates_polls_and_downloads(tmp_path: Path):
    requests: list[httpx.Request] = []
    http = HttpClient(client=httpx.Client(transport=httpx.MockTransport(luma_handler(requests))))
    provider = LumaProvider(http, "secret-key", sleep=lambda _: None)

    path = provider.generate("a dragon", duration_sec=5.0, out_dir=tmp_path)

    assert path.exists()
    assert path.read_bytes() == MP4
    assert path.suffix == ".mp4"

    methods = [r.method for r in requests]
    assert methods == ["POST", "GET", "GET"]
    assert all(r.headers["Authorization"] == "Bearer secret-key" for r in requests)
    assert requests[0].url.path.endswith("/generations")
    assert requests[1].url.path.endswith("/generations/job1")


def test_luma_generate_polls_until_completed(tmp_path: Path):
    requests: list[httpx.Request] = []
    poll_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "job2"})
        if "job2" in str(request.url):
            poll_count["n"] += 1
            if poll_count["n"] < 2:
                return httpx.Response(200, json={"id": "job2", "state": "processing"})
            return httpx.Response(
                200,
                json={"id": "job2", "state": "completed", "assets": {"video": "http://v/2.mp4"}},
            )
        return httpx.Response(200, content=MP4)

    sleeps: list[float] = []
    http = HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = LumaProvider(http, "k", poll_interval=0.01, sleep=sleeps.append)

    path = provider.generate("a dragon", duration_sec=3.0, out_dir=tmp_path)

    assert path.read_bytes() == MP4
    assert poll_count["n"] == 2
    assert len(sleeps) == 1


def test_luma_generate_raises_on_failed_state(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "job3"})
        return httpx.Response(200, json={"id": "job3", "state": "failed"})

    http = HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = LumaProvider(http, "k", sleep=lambda _: None)

    with pytest.raises(ProviderError):
        provider.generate("a dragon", duration_sec=5.0, out_dir=tmp_path)


# --------------------------------------------------------------------------- #
# build_providers
# --------------------------------------------------------------------------- #
def test_build_providers_empty_without_keys():
    secrets = Secrets(gemini_api_key="test-key")

    assert build_providers(secrets) == []
