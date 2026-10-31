"""Task 5.12: the live builder must wire real trend sources.

Regression test for the demo/live run that skipped ``TREND`` (no sources were
passed) and therefore failed at ``ANGLE``. Everything here is offline:
constructing the sources and the stage map performs no network I/O.
"""

from __future__ import annotations

from pathlib import Path

from src.config import Categories, Category, Paths, Settings
from src.llm.client import FakeLLMClient
from src.pipeline.live import _build_trend_sources, build_live_stages
from src.rerun.controller import Stage
from src.trends.google_trends import GoogleTrendsSource
from src.trends.hackernews import HackerNewsSource
from src.trends.news_rss import NewsRssSource
from src.trends.reddit import RedditSource


def _categories() -> Categories:
    return Categories(
        rotation=["ai_tech"],
        categories={
            "ai_tech": Category(
                display_name="AI & Tech",
                keywords=["ai"],
                subreddits=["MachineLearning", "technology"],
            )
        },
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        paths=Paths(
            output_dir=tmp_path / "out",
            assets_dir=tmp_path / "assets",
            db_path=tmp_path / "db.sqlite",
        )
    )


def test_build_trend_sources_includes_the_keyless_sources() -> None:
    sources = _build_trend_sources(object(), categories=None, category=None)  # type: ignore[arg-type]

    assert [s.name for s in sources] == ["google_trends", "hackernews", "news_rss"]
    assert isinstance(sources[0], GoogleTrendsSource)
    assert isinstance(sources[1], HackerNewsSource)
    assert isinstance(sources[2], NewsRssSource)


def test_build_trend_sources_adds_category_subreddits() -> None:
    sources = _build_trend_sources(
        object(), categories=_categories(), category="ai_tech"  # type: ignore[arg-type]
    )

    reddit = [s for s in sources if isinstance(s, RedditSource)]
    assert len(reddit) == 1
    assert reddit[0].subreddits == ["MachineLearning", "technology"]


def test_build_trend_sources_unknown_category_has_no_reddit() -> None:
    sources = _build_trend_sources(
        object(), categories=_categories(), category="does_not_exist"  # type: ignore[arg-type]
    )

    assert not any(isinstance(s, RedditSource) for s in sources)


def test_build_live_stages_wires_the_trend_stage(tmp_path: Path) -> None:
    stages = build_live_stages(
        secrets=object(),  # type: ignore[arg-type]
        settings=_settings(tmp_path),
        out_dir=tmp_path / "run",
        demo=True,
        max_scenes=2,
        categories=_categories(),
        category="ai_tech",
        http=object(),  # type: ignore[arg-type]
        notifier=object(),  # type: ignore[arg-type]
        store=object(),  # type: ignore[arg-type]
        llm=FakeLLMClient([]),
        tts_backend=object(),  # type: ignore[arg-type]
    )

    # The regression: TREND used to be missing, so ANGLE had no topic.
    assert Stage.TREND in stages
    assert Stage.ANGLE in stages
