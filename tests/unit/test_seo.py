"""Task 4.4 tests: the ``seo`` agent (publish metadata generation)."""

from __future__ import annotations

import json

from src.agents.seo import Chapter, PublishMetadata, SeoAgent, SeoInput
from src.llm.client import FakeLLMClient
from src.schema.blueprint import Blueprint


def blueprint() -> Blueprint:
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "Local LLMs Explained",
                "category": "ai_tech",
                "language": "en",
                "target_duration_sec": 120,
            },
            "scenes": [
                {
                    "index": 1,
                    "narration": "Small models run on laptops.",
                    "visual": {"kind": "image", "keywords": ["llm"]},
                    "duration_sec": 120.0,
                }
            ],
        }
    )


def draft(**overrides) -> SeoInput:
    base = {"blueprint": blueprint()}
    base.update(overrides)
    return SeoInput(**base)


def reply(**overrides) -> str:
    payload = {
        "title": "Local LLMs Explained",
        "description": "A short explainer about running LLMs locally.",
        "tags": ["llm", "ai"],
        "thumbnail_prompt": "A glowing laptop running a tiny robot.",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_valid_reply_returns_ok_metadata():
    fake = FakeLLMClient(replies=[reply()])
    result = SeoAgent(fake).run(draft())

    assert result.status == "ok"
    assert isinstance(result.data, PublishMetadata)
    assert result.data.title == "Local LLMs Explained"
    assert result.data.tags == ["llm", "ai"]
    assert result.data.thumbnail_prompt
    assert result.data.language == "en"


def test_long_title_is_trimmed_to_limit():
    long_title = "word " * 30  # 150 characters, spaces on a word boundary
    assert len(long_title) > 100
    fake = FakeLLMClient(replies=[reply(title=long_title)])
    result = SeoAgent(fake).run(draft())

    assert result.status == "ok"
    assert len(result.data.title) <= 100
    assert not result.data.title.endswith(" ")


def test_overlong_tags_are_trimmed_but_keep_at_least_one():
    big_tags = [f"keyword-number-{i:03d}" for i in range(40)]
    assert len(",".join(big_tags)) > 500
    fake = FakeLLMClient(replies=[reply(tags=big_tags)])
    result = SeoAgent(fake).run(draft())

    assert result.status == "ok"
    assert len(result.data.tags) >= 1
    assert len(",".join(result.data.tags)) <= 500


def test_duplicate_and_blank_tags_are_removed():
    tags = ["AI", " ai ", "", "   ", "Tech", "TECH", "ai"]
    fake = FakeLLMClient(replies=[reply(tags=tags)])
    result = SeoAgent(fake).run(draft())

    assert result.status == "ok"
    assert result.data.tags == ["AI", "Tech"]


def test_chapters_are_appended_in_order():
    chapters = [
        Chapter(start_sec=0.0, label="Intro"),
        Chapter(start_sec=120.0, label="Body"),
        Chapter(start_sec=185.0, label="Outro"),
    ]
    fake = FakeLLMClient(replies=[reply(description="Overview of the video.")])
    result = SeoAgent(fake).run(draft(chapters=chapters))

    assert result.status == "ok"
    description = result.data.description
    assert "Chapters" in description
    assert "0:00 Intro" in description
    assert description.index("0:00 Intro") < description.index("2:00 Body")
    assert description.index("2:00 Body") < description.index("3:05 Outro")
    assert description.rstrip().endswith("3:05 Outro")


def test_missing_title_fails():
    fake = FakeLLMClient(replies=[json.dumps({"description": "no title", "tags": ["a"]})])
    result = SeoAgent(fake).run(draft())

    assert result.status == "fail"
    assert result.notes


def test_malformed_json_fails():
    fake = FakeLLMClient(replies=["not json at all"])
    result = SeoAgent(fake).run(draft())

    assert result.status == "fail"
    assert result.notes


def test_prompt_includes_blueprint_title():
    fake = FakeLLMClient(replies=[reply()])
    SeoAgent(fake).run(draft())

    prompt = fake.calls[0]["prompt"]
    assert "Local LLMs Explained" in prompt
    assert fake.calls[0]["json_mode"] is True
