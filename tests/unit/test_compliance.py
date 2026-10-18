"""Task 2.8 tests: the deterministic ``compliance`` gate."""

from __future__ import annotations

from src.agents.compliance import (
    ALLOWED_ASSET_SOURCES,
    ComplianceAgent,
    ComplianceInput,
    ComplianceReport,
)
from src.schema.blueprint import Blueprint


def make_blueprint(
    *,
    narrations: list[str] | None = None,
    on_screen_texts: list[str | None] | None = None,
) -> Blueprint:
    """Build a small valid blueprint, overriding narration/on-screen text."""
    narrations = narrations if narrations is not None else ["Welcome to the show."]
    count = len(narrations)
    on_screen_texts = on_screen_texts if on_screen_texts is not None else [None] * count
    scenes = [
        {
            "index": i + 1,
            "narration": narrations[i],
            "on_screen_text": on_screen_texts[i],
            "visual": {"kind": "image"},
            "duration_sec": 20.0,
            "hero": False,
        }
        for i in range(count)
    ]
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "A Compliance Test Blueprint",
                "category": "ai_tech",
                "language": "en",
                "target_duration_sec": 60,
            },
            "scenes": scenes,
        }
    )


def test_clean_blueprint_passes():
    agent = ComplianceAgent()
    result = agent.run(
        ComplianceInput(
            blueprint=make_blueprint(),
            asset_prompts=["a calm studio desk"],
            asset_sources=sorted(ALLOWED_ASSET_SOURCES),
        )
    )

    assert result.status == "ok"
    report = result.data
    assert isinstance(report, ComplianceReport)
    assert report.passed is True
    assert report.monetization_safe is True
    assert report.flags == []


def test_medical_claim_blocks_and_flags_scene():
    blueprint = make_blueprint(
        narrations=["This natural remedy can cure everything.", "A calm closing line."]
    )
    result = ComplianceAgent().run(ComplianceInput(blueprint=blueprint))

    assert result.status == "rework"
    report = result.data
    assert report.passed is False
    assert report.monetization_safe is False
    blocks = [f for f in report.flags if f.severity == "block" and f.category == "medical"]
    assert len(blocks) == 1
    assert blocks[0].scene_index == 1


def test_financial_claim_blocks():
    blueprint = make_blueprint(narrations=["Our system offers guaranteed returns."])
    result = ComplianceAgent().run(ComplianceInput(blueprint=blueprint))

    assert result.status == "rework"
    financial = [
        f for f in result.data.flags if f.severity == "block" and f.category == "financial"
    ]
    assert len(financial) == 1
    assert financial[0].scene_index == 1


def test_unknown_asset_source_warns_but_passes():
    result = ComplianceAgent().run(
        ComplianceInput(
            blueprint=make_blueprint(),
            asset_sources=["pexels", "some-sketchy-site"],
        )
    )

    assert result.status == "ok"
    report = result.data
    assert report.passed is True
    copyright_flags = [f for f in report.flags if f.category == "copyright"]
    assert len(copyright_flags) == 1
    assert copyright_flags[0].severity == "warn"
    assert "some-sketchy-site" in copyright_flags[0].message


def test_superlative_warns():
    blueprint = make_blueprint(narrations=["We are simply the best in the world at this."])
    result = ComplianceAgent().run(ComplianceInput(blueprint=blueprint))

    assert result.status == "ok"
    super_flags = [f for f in result.data.flags if f.category == "superlative"]
    assert len(super_flags) == 1
    assert super_flags[0].severity == "warn"
    assert super_flags[0].scene_index == 1


def test_summary_mentions_issue_count():
    blueprint = make_blueprint(
        narrations=["This miracle works.", "We are number one."],
    )
    result = ComplianceAgent().run(
        ComplianceInput(blueprint=blueprint, asset_sources=["unknown-source"])
    )

    report = result.data
    # 1 medical block + 1 superlative warn + 1 copyright warn
    assert len(report.flags) == 3
    assert "3 issues" in report.summary
    assert "1 block" in report.summary
    assert "2 warn" in report.summary
