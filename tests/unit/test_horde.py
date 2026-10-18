"""Task 3.4 tests: Stable Horde async submit/poll client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src.errors import ProviderError
from src.http_client import HttpClient
from src.visuals.horde import HordeClient

PNG = b"\x89PNG\r\n\x1a\nmocked-png-bytes"


class Router:
    """Route-aware MockTransport handler that records every request."""

    def __init__(self, checks: list[dict] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.checks = list(checks or [])
        self.check_calls = 0
        self.status_calls = 0
        self.result_url = "https://cdn.example/img/1.png"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path == "/api/v2/generate/async":
            return httpx.Response(200, json={"id": "job-1", "status": "ok"})
        if path.startswith("/api/v2/generate/check/"):
            body = self.checks[self.check_calls] if self.check_calls < len(self.checks) else {}
            self.check_calls += 1
            return httpx.Response(200, json=body)
        if path.startswith("/api/v2/generate/status/"):
            self.status_calls += 1
            return httpx.Response(200, json={"generations": [{"img": self.result_url}]})
        if path == "/img/1.png":
            return httpx.Response(200, content=PNG)
        return httpx.Response(404)


def make_client(router: Router, sleep=lambda _: None, **kwargs):
    http = HttpClient(client=httpx.Client(transport=httpx.MockTransport(router)))
    return HordeClient(http, sleep=sleep, **kwargs), http


def test_submit_returns_id_and_posts_expected_body(tmp_path: Path):
    router = Router()
    client, _ = make_client(router)

    job_id = client.submit("a red fox", width=512, height=512, model="dreamshaper", steps=25)

    assert job_id == "job-1"
    assert len(router.requests) == 1
    req = router.requests[0]
    assert req.method == "POST"
    assert req.url.path == "/api/v2/generate/async"
    assert req.headers["apikey"] == "0000000000"

    body = json.loads(req.content)
    assert body["prompt"] == "a red fox"
    assert body["models"] == ["dreamshaper"]
    assert body["params"] == {"width": 512, "height": 512, "steps": 25, "n": 1}


def test_check_and_fetch_result_parse_horde_shapes():
    router = Router()
    client, _ = make_client(router)

    assert client.check("job-1") == {}
    assert client.fetch_result("job-1") == ["https://cdn.example/img/1.png"]
    assert router.check_calls == 1
    assert router.status_calls == 1


def test_generate_polls_until_done_and_downloads(tmp_path: Path):
    router = Router(checks=[{"done": False}, {"done": False}, {"done": True}])
    client, _ = make_client(router, sleep=lambda _: None)
    out = tmp_path / "out.png"

    result = client.generate("a red fox", out, width=512, height=512)

    assert result == out
    assert out.read_bytes() == PNG
    # upload, three checks, status, image download
    assert router.check_calls == 3
    assert router.status_calls == 1
    paths = [r.url.path for r in router.requests]
    assert "/api/v2/generate/async" in paths
    assert paths.count("/api/v2/generate/check/job-1") == 3
    assert "/api/v2/generate/status/job-1" in paths
    assert "/img/1.png" in paths


def test_faulted_check_raises_provider_error(tmp_path: Path):
    router = Router(checks=[{"faulted": True, "done": False}])
    client, _ = make_client(router, sleep=lambda _: None)

    with pytest.raises(ProviderError):
        client.generate("a red fox", tmp_path / "out.png")

    assert router.status_calls == 0


def test_exhausted_polls_raise_timeout(tmp_path: Path):
    router = Router(checks=[{"done": False}] * 10)
    client, _ = make_client(router, sleep=lambda _: None, max_polls=3)

    with pytest.raises(ProviderError, match="timed out"):
        client.generate("a red fox", tmp_path / "out.png")

    assert router.check_calls == 3


def test_sleep_called_between_polls_only(tmp_path: Path):
    sleeps: list[float] = []
    router = Router(checks=[{"done": False}, {"done": True}])
    client, _ = make_client(router, sleep=sleeps.append, poll_interval=1.5, max_polls=5)

    client.generate("a red fox", tmp_path / "out.png")

    assert sleeps == [1.5]


def test_no_sleep_after_final_poll_when_exhausted(tmp_path: Path):
    sleeps: list[float] = []
    router = Router(checks=[{"done": False}] * 10)
    client, _ = make_client(router, sleep=sleeps.append, poll_interval=2.0, max_polls=3)

    with pytest.raises(ProviderError):
        client.generate("a red fox", tmp_path / "out.png")

    # 3 polls -> 2 waits between them; never after the last one.
    assert sleeps == [2.0, 2.0]
