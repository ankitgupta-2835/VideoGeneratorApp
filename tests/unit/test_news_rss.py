"""Task 1.8 tests: Google News RSS source."""

from __future__ import annotations

import httpx

from src.http_client import HttpClient
from src.trends.news_rss import NewsRssSource

NEWS_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>news search</title>
    <item>
      <title>AI startup raises funds</title>
      <link>https://example.com/ai</link>
    </item>
    <item>
      <title>Football final tonight</title>
      <link>https://example.com/sport</link>
    </item>
  </channel>
</rss>
"""


def http_for(handler) -> HttpClient:
    return HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def rss_handler(payload: bytes = NEWS_RSS):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    return handler


def test_fetch_parses_titles_and_links():
    items = NewsRssSource(http_for(rss_handler())).fetch()
    assert [i.title for i in items] == ["AI startup raises funds", "Football final tonight"]
    assert items[0].url == "https://example.com/ai"
    assert items[0].source == "news_rss"


def test_query_param_equals_joined_keywords():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, content=NEWS_RSS)

    NewsRssSource(http_for(handler)).fetch(keywords=["ai", "football"])
    assert "q=ai+OR+football" in captured["url"] or "q=ai%20OR%20football" in captured["url"]


def test_keyword_filter_drops_non_matching():
    items = NewsRssSource(http_for(rss_handler())).fetch(keywords=["ai"])
    assert [i.title for i in items] == ["AI startup raises funds"]


def test_init_query_is_used_as_is():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, content=NEWS_RSS)

    src = NewsRssSource(http_for(handler), query="custom terms")
    src.fetch(keywords=["ignored"])
    assert "q=custom+terms" in captured["url"] or "q=custom%20terms" in captured["url"]


def test_empty_rss_returns_empty_list():
    empty = b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    assert NewsRssSource(http_for(rss_handler(empty))).fetch() == []
