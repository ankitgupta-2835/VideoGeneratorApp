"""Task 1.7 tests: Hacker News source."""

from __future__ import annotations

import httpx

from src.http_client import HttpClient
from src.trends.hackernews import HackerNewsSource


def http_for(handler) -> HttpClient:
    return HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def handler_for(stories: dict[int, dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("topstories.json"):
            return httpx.Response(200, json=list(stories))
        for sid, story in stories.items():
            if url.endswith(f"item/{sid}.json"):
                return httpx.Response(200, json=story)
        return httpx.Response(404)

    return handler


def test_fetch_parses_stories():
    stories = {
        1: {
            "type": "story",
            "title": "Show HN: an AI tool",
            "url": "https://example.com/ai",
            "score": 250,
            "descendants": 88,
            "time": 1_700_000_000,
        },
        2: {
            "type": "story",
            "title": "Ask HN: anything",
            "score": 10,
            "descendants": 3,
            "time": 1_700_000_100,
        },
        3: {"type": "comment", "title": "ignored"},
    }
    items = HackerNewsSource(http_for(handler_for(stories)), limit=10).fetch()
    assert [i.title for i in items] == ["Show HN: an AI tool", "Ask HN: anything"]
    assert items[0].url == "https://example.com/ai"
    assert items[0].metrics["score"] == 250.0
    # story with no url falls back to the HN item link
    assert items[1].url == "https://news.ycombinator.com/item?id=2"


def test_limit_is_respected():
    stories = {i: {"type": "story", "title": f"story {i}"} for i in range(1, 6)}
    items = HackerNewsSource(http_for(handler_for(stories)), limit=2).fetch()
    assert len(items) == 2


def test_keyword_filter():
    stories = {
        1: {"type": "story", "title": "AI news"},
        2: {"type": "story", "title": "Cooking tips"},
    }
    items = HackerNewsSource(http_for(handler_for(stories))).fetch(keywords=["ai"])
    assert [i.title for i in items] == ["AI news"]
