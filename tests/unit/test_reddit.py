"""Task 1.6 tests: Reddit source."""

from __future__ import annotations

import httpx

from src.http_client import HttpClient
from src.trends.reddit import RedditSource

SAMPLE = {
    "data": {
        "children": [
            {
                "data": {
                    "title": "New AI breakthrough",
                    "permalink": "/r/technology/comments/abc/new_ai/",
                    "ups": 1200,
                    "num_comments": 340,
                    "created_utc": 1_700_000_000,
                }
            },
            {
                "data": {
                    "title": "Sports update",
                    "permalink": "/r/technology/comments/def/sports/",
                    "ups": 10,
                    "num_comments": 2,
                    "created_utc": 1_700_000_100,
                }
            },
        ]
    }
}


def http_for(handler) -> HttpClient:
    return HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_reddit_fetch_parses_posts():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, json=SAMPLE)

    src = RedditSource(http_for(handler), subreddits=["technology"])
    items = src.fetch()
    assert [i.title for i in items] == ["New AI breakthrough", "Sports update"]
    assert items[0].url.startswith("https://www.reddit.com/r/technology/")
    assert items[0].metrics["ups"] == 1200.0
    assert items[0].published_at is not None
    assert "/r/technology/rising.json" in captured["url"]
    assert captured["ua"]


def test_reddit_keyword_filter():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE)

    items = RedditSource(http_for(handler), subreddits=["technology"]).fetch(keywords=["ai"])
    assert [i.title for i in items] == ["New AI breakthrough"]


def test_reddit_multiple_subreddits():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=SAMPLE)

    src = RedditSource(http_for(handler), subreddits=["a", "b"])
    items = src.fetch()
    assert calls["n"] == 2
    assert len(items) == 4
