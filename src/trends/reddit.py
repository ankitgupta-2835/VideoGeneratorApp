"""Reddit rising/hot source (public JSON endpoints, no key)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.http_client import HttpClient
from src.trends.base import TrendItem, TrendSource, matches_keywords

__all__ = ["RedditSource"]

_UA = "VideoGeneratorApp/0.1 (trend research)"


class RedditSource(TrendSource):
    name = "reddit"
    BASE = "https://www.reddit.com/r"

    def __init__(
        self,
        http: HttpClient,
        *,
        subreddits: list[str] | None = None,
        listing: str = "rising",
        limit: int = 25,
    ) -> None:
        self._http = http
        self.subreddits = subreddits or []
        self._listing = listing
        self._limit = limit

    def fetch(
        self,
        *,
        keywords: list[str] | None = None,
        subreddits: list[str] | None = None,
    ) -> list[TrendItem]:
        subs = subreddits or self.subreddits
        items: list[TrendItem] = []
        for sub in subs:
            url = f"{self.BASE}/{sub}/{self._listing}.json"
            data = self._http.get_json(
                url, params={"limit": self._limit}, headers={"User-Agent": _UA}
            )
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                title = post.get("title", "")
                if not title or not matches_keywords(title, keywords):
                    continue
                created = post.get("created_utc")
                items.append(
                    TrendItem(
                        title=title,
                        url="https://www.reddit.com" + post.get("permalink", ""),
                        source=self.name,
                        metrics={
                            "ups": float(post.get("ups", 0)),
                            "num_comments": float(post.get("num_comments", 0)),
                            "created_utc": float(created or 0),
                        },
                        published_at=(
                            datetime.fromtimestamp(created, tz=UTC).isoformat() if created else None
                        ),
                    )
                )
        return items
