"""Hacker News top-stories source (free public API, no key)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.http_client import HttpClient
from src.trends.base import TrendItem, TrendSource, matches_keywords

__all__ = ["HackerNewsSource"]


class HackerNewsSource(TrendSource):
    name = "hackernews"
    TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
    ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"

    def __init__(self, http: HttpClient, *, limit: int = 30) -> None:
        self._http = http
        self._limit = limit

    def fetch(self, *, keywords: list[str] | None = None) -> list[TrendItem]:
        ids = self._http.get_json(self.TOP)
        items: list[TrendItem] = []
        for story_id in list(ids)[: self._limit]:
            data = self._http.get_json(self.ITEM.format(id=story_id))
            if not data or data.get("type") != "story":
                continue
            title = data.get("title", "")
            if not title or not matches_keywords(title, keywords):
                continue
            created = data.get("time")
            items.append(
                TrendItem(
                    title=title,
                    url=data.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                    source=self.name,
                    metrics={
                        "score": float(data.get("score", 0)),
                        "comments": float(data.get("descendants", 0)),
                    },
                    published_at=(
                        datetime.fromtimestamp(created, tz=UTC).isoformat() if created else None
                    ),
                )
            )
        return items
