"""Task 2.1 tests: the ``trend_scout`` agent."""

from __future__ import annotations

from datetime import UTC, datetime

from src.agents.trend_scout import (
    ScoutInput,
    TopicCandidates,
    TrendScoutAgent,
)
from src.trends.base import TrendItem, TrendSource

NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


class FakeSource(TrendSource):
    """A trend source returning a fixed list or raising on demand."""

    def __init__(
        self,
        name: str,
        items: list[TrendItem] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self._items = items or []
        self._error = error

    def fetch(self, *, keywords: list[str] | None = None) -> list[TrendItem]:
        if self._error is not None:
            raise self._error
        return list(self._items)


def make_item(
    title: str,
    *,
    source: str = "hackernews",
    metrics: dict[str, float] | None = None,
) -> TrendItem:
    return TrendItem(
        title=title,
        source=source,
        metrics=metrics or {},
        published_at=NOW.isoformat(),
    )


def scout(sources: list[TrendSource], **kwargs) -> TrendScoutAgent:
    return TrendScoutAgent(sources, now=NOW, **kwargs)


def test_merges_candidates_from_multiple_sources():
    a = FakeSource("a", [make_item("from a")])
    b = FakeSource("b", [make_item("from b")])
    result = scout([a, b]).run({"category": "tech"})

    assert result.status == "ok"
    assert isinstance(result.data, TopicCandidates)
    assert result.data.category == "tech"
    titles = {item.title for item in result.data.items}
    assert titles == {"from a", "from b"}


def test_respects_limit_top_n():
    items = [make_item(f"topic {i}", metrics={"score": float(i)}) for i in range(5)]
    result = scout([FakeSource("a", items)]).run(ScoutInput(category="tech", limit=2))

    assert result.status == "ok"
    assert len(result.data.items) == 2
    assert [i.title for i in result.data.items] == ["topic 4", "topic 3"]


def test_ranking_is_descending_by_score():
    items = [
        make_item("low", metrics={"score": 1.0}),
        make_item("high", metrics={"score": 500.0}),
        make_item("mid", metrics={"score": 50.0}),
    ]
    result = scout([FakeSource("a", items)]).run({"category": "tech"})

    assert result.status == "ok"
    scores = [item.score for item in result.data.items]
    assert scores == sorted(scores, reverse=True)
    assert [i.title for i in result.data.items] == ["high", "mid", "low"]


def test_is_seen_drops_previously_seen_title():
    items = [make_item("old news"), make_item("fresh topic")]
    agent = scout([FakeSource("a", items)], is_seen=lambda title: title == "old news")
    result = agent.run({"category": "tech"})

    assert result.status == "ok"
    titles = [item.title for item in result.data.items]
    assert titles == ["fresh topic"]


def test_failing_source_is_skipped_and_noted():
    good = FakeSource("good", [make_item("survivor")])
    bad = FakeSource("bad", error=RuntimeError("boom"))
    result = scout([bad, good]).run({"category": "tech"})

    assert result.status == "ok"
    assert [item.title for item in result.data.items] == ["survivor"]
    assert "bad: boom" in result.notes


def test_no_items_returns_fail():
    result = scout([FakeSource("a")]).run({"category": "tech"})

    assert result.status == "fail"
    assert "no candidate topics" in result.notes
    assert result.data is None
