"""Deterministic, transparent scoring and deduplication for trend topics."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from src.trends.base import TrendItem

__all__ = [
    "DEFAULT_SOURCE_WEIGHTS",
    "HOOK_TOKENS",
    "ScoredTopic",
    "dedup",
    "engagement_raw",
    "rank",
    "recency_factor",
    "score_item",
    "shorts_bonus",
]

DEFAULT_SOURCE_WEIGHTS = {
    "google_trends": 1.3,
    "reddit": 1.1,
    "hackernews": 1.0,
    "news_rss": 1.0,
    "youtube_popular": 0.9,
}
HOOK_TOKENS = ("?", "how", "why", "!", "top ", "best ", "vs ", "secret")


@dataclass
class ScoredTopic:
    """A trend item paired with its computed score."""

    item: TrendItem
    score: float


def engagement_raw(item: TrendItem) -> float:
    """Combine raw engagement metrics into a single magnitude."""
    m = item.metrics
    return (
        m.get("ups", 0.0)
        + m.get("score", 0.0)
        + m.get("comments", 0.0)
        + m.get("views", 0.0) / 1000.0
    )


def recency_factor(item: TrendItem, now: datetime, half_life_hours: float) -> float:
    """Exponential decay factor based on age; neutral (0.5) when unknown."""
    if item.published_at is None:
        return 0.5
    try:
        published = datetime.fromisoformat(item.published_at)
    except ValueError:
        return 0.5
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    age_hours = max(0.0, (now - published).total_seconds() / 3600.0)
    return 0.5 ** (age_hours / half_life_hours)


def shorts_bonus(title: str) -> float:
    """Reward click-worthy hook tokens, capped at 1.3."""
    lowered = title.lower()
    hits = sum(1 for token in HOOK_TOKENS if token in lowered)
    return min(1.3, 1.0 + 0.1 * hits)


def score_item(
    item: TrendItem,
    *,
    now: datetime | None = None,
    half_life_hours: float = 12.0,
    source_weights: dict[str, float] | None = None,
) -> float:
    """Compute a deterministic score for a single item."""
    if now is None:
        now = datetime.now(UTC)
    weights = DEFAULT_SOURCE_WEIGHTS if source_weights is None else source_weights
    weight = weights.get(item.source, 1.0)
    engagement = 1.0 + math.log1p(max(engagement_raw(item), 0.0))
    recency = recency_factor(item, now, half_life_hours)
    bonus = shorts_bonus(item.title)
    return weight * engagement * recency * bonus


def rank(
    items: Iterable[TrendItem],
    *,
    now: datetime | None = None,
    half_life_hours: float = 12.0,
    source_weights: dict[str, float] | None = None,
) -> list[ScoredTopic]:
    """Score every item and return them sorted by descending score (stable)."""
    scored = [
        ScoredTopic(
            item=item,
            score=score_item(
                item,
                now=now,
                half_life_hours=half_life_hours,
                source_weights=source_weights,
            ),
        )
        for item in items
    ]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


def dedup(
    items: Iterable[TrendItem],
    *,
    is_seen: Callable[[str], bool] | None = None,
) -> list[TrendItem]:
    """Drop seen titles and case-insensitive duplicates, keeping first occurrences."""
    result: list[TrendItem] = []
    seen_titles: set[str] = set()
    for item in items:
        if is_seen is not None and is_seen(item.title):
            continue
        key = item.title.casefold()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        result.append(item)
    return result
