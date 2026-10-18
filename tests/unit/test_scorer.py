"""Task 1.10 tests: deterministic trend scoring and dedup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.trends.base import TrendItem
from src.trends.scorer import (
    ScoredTopic,
    dedup,
    rank,
    recency_factor,
    score_item,
    shorts_bonus,
)

NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def make_item(
    title: str,
    *,
    source: str = "hackernews",
    metrics: dict[str, float] | None = None,
    published_at: str | None = None,
) -> TrendItem:
    return TrendItem(
        title=title,
        source=source,
        metrics=metrics or {},
        published_at=published_at,
    )


def test_fresher_item_ranks_higher():
    older = make_item(
        "older story",
        metrics={"score": 100.0},
        published_at=(NOW - timedelta(hours=48)).isoformat(),
    )
    fresher = make_item(
        "fresher story",
        metrics={"score": 100.0},
        published_at=NOW.isoformat(),
    )
    ordered = rank([older, fresher], now=NOW)
    assert ordered[0].item.title == "fresher story"
    assert ordered[0].score > ordered[1].score


def test_higher_engagement_ranks_higher():
    low = make_item("low", metrics={"score": 1.0}, published_at=NOW.isoformat())
    high = make_item("high", metrics={"score": 500.0}, published_at=NOW.isoformat())
    ordered = rank([low, high], now=NOW)
    assert ordered[0].item.title == "high"
    assert ordered[0].score > ordered[1].score


def test_hook_tokens_get_shorts_bonus():
    plain = make_item("plain cooking advice", published_at=NOW.isoformat())
    hooked = make_item("how to cook? best tips!", published_at=NOW.isoformat())
    assert shorts_bonus(hooked.title) > shorts_bonus(plain.title)
    assert score_item(hooked, now=NOW) > score_item(plain, now=NOW)


def test_source_weights_change_ordering():
    reddit = make_item("reddit story", source="reddit", published_at=NOW.isoformat())
    hackernews = make_item("hn story", source="hackernews", published_at=NOW.isoformat())
    weights = {"reddit": 2.0, "hackernews": 0.5}
    ordered = rank([hackernews, reddit], now=NOW, source_weights=weights)
    assert ordered[0].item.source == "reddit"
    # With default weights the raw scores are equal; here the weight flips ordering.
    assert score_item(reddit, now=NOW, source_weights=weights) > score_item(
        hackernews, now=NOW, source_weights=weights
    )


def test_rank_returns_sorted_scored_topic_list():
    items = [
        make_item("one", metrics={"score": 10.0}, published_at=NOW.isoformat()),
        make_item("two", metrics={"score": 300.0}, published_at=NOW.isoformat()),
        make_item("three", metrics={"score": 50.0}, published_at=NOW.isoformat()),
    ]
    ordered = rank(items, now=NOW)
    assert all(isinstance(s, ScoredTopic) for s in ordered)
    scores = [s.score for s in ordered]
    assert scores == sorted(scores, reverse=True)


def test_dedup_removes_seen_and_case_insensitive_duplicates():
    items = [
        make_item("Alpha"),
        make_item("beta"),
        make_item("ALPHA"),
        make_item("Seen Topic"),
        make_item("gamma"),
    ]
    result = dedup(items, is_seen=lambda title: title == "Seen Topic")
    titles = [i.title for i in result]
    assert titles == ["Alpha", "beta", "gamma"]


def test_none_published_at_uses_neutral_recency():
    item = make_item("no date", metrics={"score": 5.0})
    assert recency_factor(item, NOW, 12.0) == 0.5
    # Should not crash and should produce a finite positive score.
    score = score_item(item, now=NOW)
    assert score > 0.0
