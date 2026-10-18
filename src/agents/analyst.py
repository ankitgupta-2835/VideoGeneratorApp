"""``analyst`` agent: turn real video performance into scoring weights.

After a video is published we learn how it actually performed. The analyst
blends a few normalized retention/engagement signals into a single
deterministic ``performance`` value in ``[0, 1]`` and nudges the weight of the
trend source that produced the topic. Better-than-baseline performance raises a
source's weight so future topics from it rank higher; worse performance lowers
it. Everything is pure arithmetic -- no LLM, no network.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from src.agents.base import Agent, AgentResult
from src.trends.scorer import DEFAULT_SOURCE_WEIGHTS

__all__ = [
    "AnalyticsInput",
    "AnalystAgent",
    "ScoringWeightsUpdate",
    "VideoMetrics",
    "performance_score",
    "updated_weights",
]

# Reference engagement magnitude that saturates the normalized engagement term
# to 1.0. Chosen so a video with ~1000 likes+comments scores "fully engaged".
_ENGAGEMENT_REFERENCE = 1000.0


class VideoMetrics(BaseModel):
    """Observed performance of one published video."""

    views: int = 0
    ctr: float = 0.0  # click-through rate, 0..1
    avg_view_pct: float = 0.0  # average view percentage, 0..1
    likes: int = 0
    comments: int = 0


class AnalyticsInput(BaseModel):
    """Input contract: a video's metrics plus the weight table to adjust."""

    run_id: str
    category: str
    source: str  # the trend source that produced this topic
    metrics: VideoMetrics
    current_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_SOURCE_WEIGHTS))


class ScoringWeightsUpdate(BaseModel):
    """Output contract: the before/after weight for one source."""

    source: str
    old_weight: float
    new_weight: float
    performance: float
    weights: dict[str, float]
    notes: list[str] = Field(default_factory=list)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def performance_score(metrics: VideoMetrics) -> float:
    """Blend retention and engagement signals into a deterministic ``[0, 1]``.

    The exact formula is::

        engagement = min(1, log1p(likes + comments) / log1p(1000))
        performance = clamp(0.5*avg_view_pct + 0.3*ctr + 0.2*engagement, 0, 1)

    ``avg_view_pct`` and ``ctr`` are expected in ``[0, 1]`` (they are clamped by
    the final ``clamp``). Empty metrics score exactly ``0.0``.
    """
    engagement = math.log1p(max(metrics.likes + metrics.comments, 0)) / math.log1p(
        _ENGAGEMENT_REFERENCE
    )
    engagement = _clamp(engagement, 0.0, 1.0)
    blended = 0.5 * metrics.avg_view_pct + 0.3 * metrics.ctr + 0.2 * engagement
    return _clamp(blended, 0.0, 1.0)


def updated_weights(
    current: dict[str, float],
    *,
    source: str,
    performance: float,
    baseline: float = 0.5,
    step: float = 0.02,
    lo: float = 0.5,
    hi: float = 2.0,
) -> dict[str, float]:
    """Return a copy of ``current`` with ``source`` nudged toward performance.

    ``delta = step * (performance - baseline)``; the source's new weight is
    ``clamp(current[source] + delta, lo, hi)``. Every other source is left
    untouched and the input dict is never mutated. An unknown ``source`` is
    treated as if its current weight were ``1.0`` before clamping.
    """
    base_weight = current.get(source, 1.0)
    delta = step * (performance - baseline)
    updated = dict(current)
    updated[source] = _clamp(base_weight + delta, lo, hi)
    return updated


class AnalystAgent(Agent):
    """Converts one video's metrics into an updated source-weight table."""

    name = "analyst"
    input_model = AnalyticsInput
    output_model = ScoringWeightsUpdate

    def _run(self, payload: AnalyticsInput) -> AgentResult:
        performance = performance_score(payload.metrics)
        known = payload.source in payload.current_weights
        old_weight = payload.current_weights.get(payload.source, 1.0)
        weights = updated_weights(
            payload.current_weights,
            source=payload.source,
            performance=performance,
        )
        new_weight = weights[payload.source]

        notes: list[str] = []
        if not known:
            notes.append(f"unknown source {payload.source!r}; treated current weight as 1.0")
        direction = "raised" if new_weight > old_weight else "lowered"
        if new_weight == old_weight:
            direction = "held"
        notes.append(
            f"performance={performance:.3f} {direction} {payload.source!r} "
            f"weight {old_weight:.3f} -> {new_weight:.3f}"
        )

        data = ScoringWeightsUpdate(
            source=payload.source,
            old_weight=old_weight,
            new_weight=new_weight,
            performance=performance,
            weights=weights,
            notes=notes,
        )
        return AgentResult(status="ok", data=data, notes=notes)
