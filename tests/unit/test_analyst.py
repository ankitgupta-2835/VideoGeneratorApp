"""Task 4.6 tests: deterministic performance scoring and weight updates."""

from __future__ import annotations

from src.agents.analyst import (
    AnalystAgent,
    AnalyticsInput,
    VideoMetrics,
    performance_score,
    updated_weights,
)
from src.trends.scorer import DEFAULT_SOURCE_WEIGHTS

WEAK = VideoMetrics()
STRONG = VideoMetrics(ctr=0.2, avg_view_pct=0.8, likes=800, comments=200)


def test_performance_score_zero_and_monotonic():
    assert performance_score(WEAK) == 0.0
    # Better metrics never score lower (monotonic across each signal).
    better_ctr = VideoMetrics(ctr=0.1)
    assert performance_score(better_ctr) > performance_score(WEAK)
    better_retention = VideoMetrics(avg_view_pct=0.5)
    assert performance_score(better_retention) > performance_score(WEAK)
    better_engagement = VideoMetrics(likes=500)
    assert performance_score(better_engagement) > performance_score(WEAK)
    assert performance_score(STRONG) > performance_score(better_ctr)
    # Always within the unit interval.
    assert 0.0 <= performance_score(STRONG) <= 1.0


def test_above_baseline_raises_below_lowers():
    weights = dict(DEFAULT_SOURCE_WEIGHTS)
    source = "reddit"
    raised = updated_weights(weights, source=source, performance=1.0)
    lowered = updated_weights(weights, source=source, performance=0.0)
    assert raised[source] > weights[source]
    assert lowered[source] < weights[source]


def test_update_is_clamped_to_bounds():
    weights = dict(DEFAULT_SOURCE_WEIGHTS)
    source = "reddit"
    # A huge positive delta cannot exceed the upper bound.
    high = updated_weights(weights, source=source, performance=1.0, step=1000.0)
    assert high[source] == 2.0
    # A huge negative delta cannot drop below the lower bound.
    low = updated_weights(weights, source=source, performance=0.0, step=1000.0)
    assert low[source] == 0.5


def test_other_sources_unchanged_and_input_not_mutated():
    weights = dict(DEFAULT_SOURCE_WEIGHTS)
    original = dict(weights)
    updated = updated_weights(weights, source="reddit", performance=0.9)
    changed = {k for k in original if original[k] != updated[k]}
    assert changed == {"reddit"}
    assert weights == original  # input dict untouched (copy returned)
    assert updated["reddit"] != original["reddit"]


def test_unknown_source_starts_from_one_and_is_noted():
    weights = dict(DEFAULT_SOURCE_WEIGHTS)
    updated = updated_weights(weights, source="mastodon", performance=1.0)
    # 1.0 (assumed current) + positive delta, clamped at hi.
    assert updated["mastodon"] == 1.0 + 0.02 * (1.0 - 0.5)

    agent = AnalystAgent()
    payload = AnalyticsInput(
        run_id="run-1",
        category="tech",
        source="mastodon",
        metrics=VideoMetrics(ctr=0.1),
        current_weights=weights,
    )
    result = agent.run(payload)
    assert result.status == "ok"
    assert any("unknown source" in note for note in result.notes)


def test_agent_returns_ok_and_consistent_weight():
    agent = AnalystAgent()
    payload = AnalyticsInput(
        run_id="run-2",
        category="tech",
        source="reddit",
        metrics=STRONG,
    )
    result = agent.run(payload)
    assert result.status == "ok"
    out = result.data
    assert out.source == "reddit"
    assert out.new_weight == out.weights["reddit"]
    assert out.performance == performance_score(STRONG)
