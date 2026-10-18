"""Task 1.9 tests: YouTube mostPopular source."""

from __future__ import annotations

import httpx

from src.http_client import HttpClient
from src.trends.youtube import YouTubePopularSource

SAMPLE = {
    "items": [
        {
            "id": "abc123",
            "snippet": {
                "title": "New AI breakthrough",
                "publishedAt": "2024-01-01T12:00:00Z",
            },
            "statistics": {"viewCount": "1500000", "likeCount": "42000"},
        },
        {
            "id": "def456",
            "snippet": {"title": "Cooking tips", "publishedAt": "2024-01-02T08:00:00Z"},
            "statistics": {"viewCount": "200", "likeCount": "5"},
        },
    ]
}


def http_for(handler) -> HttpClient:
    return HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_youtube_fetch_parses_videos():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE)

    src = YouTubePopularSource(http_for(handler), api_key="KEY")
    items = src.fetch()
    assert [i.title for i in items] == ["New AI breakthrough", "Cooking tips"]
    assert items[0].url == "https://www.youtube.com/watch?v=abc123"
    assert items[0].source == "youtube_popular"
    assert items[0].metrics["views"] == 1500000.0
    assert items[0].metrics["likes"] == 42000.0
    assert items[0].published_at == "2024-01-01T12:00:00Z"


def test_youtube_sends_expected_params():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=SAMPLE)

    src = YouTubePopularSource(http_for(handler), api_key="KEY", region="IN", max_results=10)
    src.fetch()
    url = captured["url"]
    assert "regionCode=IN" in url
    assert "maxResults=10" in url
    assert "key=KEY" in url
    assert "part=snippet%2Cstatistics" in url
    assert "chart=mostPopular" in url
    assert "videoCategoryId" not in url


def test_youtube_includes_category_when_set():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=SAMPLE)

    src = YouTubePopularSource(http_for(handler), api_key="KEY", category_id="10")
    src.fetch()
    assert "videoCategoryId=10" in captured["url"]


def test_youtube_keyword_filter():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE)

    items = YouTubePopularSource(http_for(handler), api_key="KEY").fetch(keywords=["ai"])
    assert [i.title for i in items] == ["New AI breakthrough"]
