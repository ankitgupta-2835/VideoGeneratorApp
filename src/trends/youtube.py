"""YouTube mostPopular trending-videos source (Data API v3, requires API key)."""

from __future__ import annotations

from src.http_client import HttpClient
from src.trends.base import TrendItem, TrendSource, matches_keywords

__all__ = ["YouTubePopularSource"]


class YouTubePopularSource(TrendSource):
    name = "youtube_popular"
    URL = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(
        self,
        http: HttpClient,
        api_key: str,
        *,
        region: str = "US",
        category_id: str | None = None,
        max_results: int = 25,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._region = region
        self._category_id = category_id
        self._max_results = max_results

    def fetch(self, *, keywords: list[str] | None = None) -> list[TrendItem]:
        params = {
            "part": "snippet,statistics",
            "chart": "mostPopular",
            "regionCode": self._region,
            "maxResults": self._max_results,
            "key": self._api_key,
        }
        if self._category_id:
            params["videoCategoryId"] = self._category_id
        data = self._http.get_json(self.URL, params=params)
        items: list[TrendItem] = []
        for entry in data.get("items", []):
            snippet = entry.get("snippet", {})
            title = snippet.get("title", "")
            if not title or not matches_keywords(title, keywords):
                continue
            video_id = entry.get("id", "")
            stats = entry.get("statistics", {})
            items.append(
                TrendItem(
                    title=title,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    source=self.name,
                    metrics={
                        "views": float(stats.get("viewCount", 0)),
                        "likes": float(stats.get("likeCount", 0)),
                    },
                    published_at=snippet.get("publishedAt"),
                )
            )
        return items
