"""``trend_scout`` agent: fetch every source, dedup, rank, and take the top N.

The scout fans out across all configured :class:`TrendSource` implementations,
tolerates individual source failures (recording a note and moving on), then
applies the shared dedup/rank pipeline and returns the best ``limit`` candidates.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel, Field

from src.agents.base import Agent, AgentResult
from src.trends.base import TrendSource
from src.trends.scorer import dedup, rank

__all__ = [
    "ScoutInput",
    "TopicCandidate",
    "TopicCandidates",
    "TrendScoutAgent",
]


class ScoutInput(BaseModel):
    """Input contract for the trend scout."""

    category: str
    keywords: list[str] = Field(default_factory=list)
    limit: int = 10


class TopicCandidate(BaseModel):
    """A scored candidate topic handed to downstream agents."""

    title: str
    url: str | None = None
    source: str
    score: float
    metrics: dict[str, float] = Field(default_factory=dict)


class TopicCandidates(BaseModel):
    """Output contract: the ranked candidates for one category."""

    category: str
    items: list[TopicCandidate] = Field(default_factory=list)


class TrendScoutAgent(Agent):
    """Wraps a set of trend sources plus the deterministic scorer."""

    name = "trend_scout"
    input_model = ScoutInput
    output_model = TopicCandidates

    def __init__(
        self,
        sources: list[TrendSource],
        *,
        is_seen: Callable[[str], bool] | None = None,
        now: datetime | None = None,
    ) -> None:
        self._sources = sources
        self._is_seen = is_seen
        self._now = now

    def _run(self, payload: ScoutInput) -> AgentResult:
        notes: list[str] = []
        collected = []
        for source in self._sources:
            try:
                collected.extend(source.fetch(keywords=payload.keywords))
            except Exception as exc:  # a broken source must not fail the scout
                notes.append(f"{source.name}: {exc}")

        unique = dedup(collected, is_seen=self._is_seen)
        ranked = rank(unique, now=self._now)[: payload.limit]

        if not ranked:
            return AgentResult(status="fail", notes=[*notes, "no candidate topics"])

        items = [
            TopicCandidate(
                title=scored.item.title,
                url=scored.item.url,
                source=scored.item.source,
                score=scored.score,
                metrics=scored.item.metrics,
            )
            for scored in ranked
        ]
        data = TopicCandidates(category=payload.category, items=items)
        return AgentResult(status="ok", data=data, notes=notes)
