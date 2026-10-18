"""Task 1.5 tests: shared trend helpers + Google Trends source."""

from __future__ import annotations

import httpx

from src.http_client import HttpClient
from src.trends.base import TrendItem, matches_keywords, parse_rss
from src.trends.google_trends import GoogleTrendsSource

GOOGLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
  <channel>
    <title>Daily Trends</title>
    <item>
      <title>New AI model</title>
      <link>https://example.com/ai</link>
      <ht:approx_traffic>200000+</ht:approx_traffic>
    </item>
    <item>
      <title>Football final</title>
      <link>https://example.com/sport</link>
    </item>
  </channel>
</rss>
"""


def http_for(handler) -> HttpClient:
    return HttpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_rss_extracts_titles_and_links():
    items = parse_rss(GOOGLE_RSS)
    assert items[0] == {"title": "New AI model", "link": "https://example.com/ai"}
    assert len(items) == 2


def test_parse_rss_supports_atom_href():
    atom = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Atom story</title><link href="https://example.com/a"/></entry>
    </feed>"""
    assert parse_rss(atom)[0]["link"] == "https://example.com/a"


def test_matches_keywords():
    assert matches_keywords("New AI model", ["ai"]) is True
    assert matches_keywords("New AI model", ["finance"]) is False
    assert matches_keywords("anything", None) is True


def test_google_trends_fetch():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, content=GOOGLE_RSS)

    src = GoogleTrendsSource(http_for(handler), geo="IN")
    items = src.fetch()
    assert [i.title for i in items] == ["New AI model", "Football final"]
    assert items[0].source == "google_trends"
    assert items[0].url == "https://example.com/ai"
    assert "geo=IN" in captured["url"]


def test_google_trends_keyword_filter():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=GOOGLE_RSS)

    items = GoogleTrendsSource(http_for(handler)).fetch(keywords=["ai"])
    assert [i.title for i in items] == ["New AI model"]


def test_trend_item_defaults():
    item = TrendItem(title="x", source="s")
    assert item.metrics == {}
    assert item.url is None
