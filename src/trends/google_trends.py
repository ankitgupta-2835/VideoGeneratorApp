"""Google Trends trending-now source (free RSS endpoint, no key)."""

from __future__ import annotations

from src.http_client import HttpClient
from src.trends.base import TrendItem, TrendSource, matches_keywords, parse_rss

__all__ = ["GoogleTrendsSource"]


class GoogleTrendsSource(TrendSource):
    name = "google_trends"
    URL = "https://trends.google.com/trending/rss"

    def __init__(self, http: HttpClient, *, geo: str = "US") -> None:
        self._http = http
        self._geo = geo

    def fetch(self, *, keywords: list[str] | None = None) -> list[TrendItem]:
        data = self._http.get_bytes(self.URL, params={"geo": self._geo})
        items: list[TrendItem] = []
        for entry in parse_rss(data):
            if not matches_keywords(entry["title"], keywords):
                continue
            items.append(
                TrendItem(
                    title=entry["title"],
                    url=entry.get("link") or None,
                    source=self.name,
                )
            )
        return items
