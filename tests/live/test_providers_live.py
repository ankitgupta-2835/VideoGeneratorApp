"""Opt-in smoke tests against real external providers.

Every test here performs real network I/O and is skipped/deselected unless
``RUN_LIVE=1`` (enforced by ``tests/live/conftest.py``). Assertions are kept
deliberately minimal: the free tiers these clients target are flaky and
rate-limited, so a live run should surface "the client can talk to the real
service", not a full behavioural specification. See ``docs/live-testing.md``.
"""

from __future__ import annotations

import os

import pytest

from src.http_client import HttpClient
from src.llm.client import build_llm_client
from src.secrets import load_secrets
from src.trends.google_trends import GoogleTrendsSource
from src.trends.hackernews import HackerNewsSource
from src.trends.news_rss import NewsRssSource
from src.trends.reddit import RedditSource
from src.trends.youtube import YouTubePopularSource
from src.visuals.horde import HordeClient
from src.visuals.images_pollinations import PollinationsImageClient
from src.visuals.stock import PexelsClient, PixabayClient

pytestmark = pytest.mark.live

# Never seed secrets from a file here; read the real process environment only.
_NO_ENV_FILE = "/tmp/definitely-not-a-real-env-file"

_LLM_KEY_VARS = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
_LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini")
_LLM_KEY_PRESENT = bool(os.environ.get(_LLM_KEY_VARS.get(_LLM_PROVIDER, ""), ""))

_YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
_PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
_PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")


@pytest.fixture
def http() -> HttpClient:
    """A real HTTP client with a generous timeout for free-tier latency."""
    with HttpClient(timeout=60.0) as client:
        yield client


# --------------------------------------------------------------------------- #
# Trend sources (mostly keyless; free public endpoints)
# --------------------------------------------------------------------------- #
def test_google_trends_live(http: HttpClient) -> None:
    items = GoogleTrendsSource(http).fetch()
    assert isinstance(items, list)
    assert all(item.title for item in items)


def test_reddit_live(http: HttpClient) -> None:
    items = RedditSource(http).fetch(subreddits=["python"], limit=5)
    assert isinstance(items, list)
    assert all(item.title for item in items)


def test_hackernews_live(http: HttpClient) -> None:
    items = HackerNewsSource(http, limit=5).fetch()
    assert isinstance(items, list)
    assert all(item.title for item in items)


def test_news_rss_live(http: HttpClient) -> None:
    items = NewsRssSource(http).fetch()
    assert isinstance(items, list)
    assert all(item.title for item in items)


@pytest.mark.skipif(not _YOUTUBE_API_KEY, reason="YOUTUBE_API_KEY not set")
def test_youtube_popular_live(http: HttpClient) -> None:
    items = YouTubePopularSource(http, _YOUTUBE_API_KEY, max_results=5).fetch()
    assert isinstance(items, list)
    assert all(item.title for item in items)


# --------------------------------------------------------------------------- #
# LLM client (provider selected by LLM_PROVIDER; key read from env)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not _LLM_KEY_PRESENT,
    reason=f"no API key set for LLM_PROVIDER={_LLM_PROVIDER}",
)
def test_llm_client_answers_json(http: HttpClient) -> None:
    secrets = load_secrets(_NO_ENV_FILE)
    client = build_llm_client(secrets, http=http)
    result = client.complete_json('Reply with exactly this JSON: {"ok": true}')
    assert isinstance(result, dict)
    assert "ok" in result


# --------------------------------------------------------------------------- #
# Image generators
# --------------------------------------------------------------------------- #
def test_pollinations_generates_file(http: HttpClient, tmp_path) -> None:
    client = PollinationsImageClient(http, tmp_path)
    out = client.generate("a plain red circle on white", width=256, height=256, seed=1)
    assert out.exists()
    assert out.stat().st_size > 0


def test_horde_submits_job(http: HttpClient) -> None:
    # Anonymous Stable Horde can take minutes to render, so stop after the real
    # submit round-trip and assert the service handed back a job id.
    client = HordeClient(http)
    job_id = client.submit("a plain red circle on white", width=256, height=256)
    assert isinstance(job_id, str)
    assert job_id.strip()


# --------------------------------------------------------------------------- #
# Stock photos (both need a free API key)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _PEXELS_API_KEY, reason="PEXELS_API_KEY not set")
def test_pexels_search_live(http: HttpClient) -> None:
    assets = PexelsClient(http, _PEXELS_API_KEY).search("nature", per_page=2)
    assert isinstance(assets, list)
    assert all(asset.download_url for asset in assets)


@pytest.mark.skipif(not _PIXABAY_API_KEY, reason="PIXABAY_API_KEY not set")
def test_pixabay_search_live(http: HttpClient) -> None:
    assets = PixabayClient(http, _PIXABAY_API_KEY).search("nature", per_page=2)
    assert isinstance(assets, list)
    assert all(asset.download_url for asset in assets)
