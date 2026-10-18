"""Google News RSS source (free RSS endpoint, no key)."""

from __future__ import annotations

from src.errors import ProviderError
from src.http_client import HttpClient
from src.logging_setup import get_logger
from src.trends.base import TrendItem, TrendSource, matches_keywords, parse_rss

__all__ = ["NewsRssSource"]

_log = get_logger(__name__)


class NewsRssSource(TrendSource):
    name = "news_rss"
    URL = "https://news.google.com/rss/search"

    def __init__(
        self,
        http: HttpClient,
        *,
        query: str | None = None,
        hl: str = "en-US",
        gl: str = "US",
        ceid: str = "US:en",
    ) -> None:
        self._http = http
        self._query = query
        self._hl = hl
        self._gl = gl
        self._ceid = ceid

    def fetch(self, *, keywords: list[str] | None = None) -> list[TrendItem]:
        q = (
            self._query
            if self._query is not None
            else (" OR ".join(keywords) if keywords else "top stories")
        )
        try:
            data = self._http.get_bytes(
                self.URL,
                params={"q": q, "hl": self._hl, "gl": self._gl, "ceid": self._ceid},
            )
        except ProviderError as exc:
            _log.warning("news_rss fetch failed: %s", exc)
            return []
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
