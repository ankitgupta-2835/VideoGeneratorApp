"""Task 2.6 tests: localizer agent (English -> Hindi)."""

from __future__ import annotations

import json

from src.agents.localizer import LocalizerAgent
from src.llm.client import FakeLLMClient
from src.schema.blueprint import Blueprint


def make_blueprint() -> Blueprint:
    """An inline English blueprint fixture with three scenes."""
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "The Rise of Local LLMs",
                "category": "ai_tech",
                "language": "en",
                "target_duration_sec": 120,
                "angle": "why small models now matter",
                "audience": "developers",
                "sources": [{"title": "Source", "url": "https://example.com"}],
            },
            "scenes": [
                {
                    "index": 1,
                    "narration": "English narration one.",
                    "on_screen_text": "Scene one",
                    "visual": {"kind": "hero", "keywords": ["k1"]},
                    "duration_sec": 30.0,
                    "hero": True,
                },
                {
                    "index": 2,
                    "narration": "English narration two.",
                    "on_screen_text": "Scene two",
                    "visual": {"kind": "image", "keywords": ["k2"]},
                    "duration_sec": 45.5,
                    "hero": False,
                },
                {
                    "index": 3,
                    "narration": "English narration three.",
                    "on_screen_text": None,
                    "visual": {"kind": "motion", "keywords": []},
                    "duration_sec": 44.5,
                    "hero": False,
                },
            ],
        }
    )


def hindi_json(indices: list[int] | None = None) -> str:
    """Build a Hindi reply for the given scene indices (default: all three)."""
    if indices is None:
        indices = [1, 2, 3]
    return json.dumps(
        {
            "title": "स्थानीय एलएलएम का उदय",
            "scenes": [
                {
                    "index": i,
                    "narration": f"हिन्दी narration {i}.",
                    "on_screen_text": f"दृश्य {i}",
                }
                for i in indices
            ],
        }
    )


def test_full_translation_preserves_structure_and_timing():
    original = make_blueprint()
    fake = FakeLLMClient(replies=[hindi_json()])
    result = LocalizerAgent(fake).run(original)

    assert result.status == "ok"
    assert isinstance(result.data, Blueprint)
    out = result.data

    # Structure: same scene count and indices.
    assert len(out.scenes) == len(original.scenes)
    assert [s.index for s in out.scenes] == [s.index for s in original.scenes]

    # Timing and structure copied unchanged.
    for new, old in zip(out.scenes, original.scenes, strict=True):
        assert new.duration_sec == old.duration_sec
        assert new.hero == old.hero
        assert new.visual == old.visual

    # Meta preserves the rest but switches language.
    assert out.meta.language == "hi"
    assert out.meta.category == original.meta.category
    assert out.meta.target_duration_sec == original.meta.target_duration_sec
    assert out.meta.angle == original.meta.angle
    assert out.meta.audience == original.meta.audience
    assert out.meta.sources == original.meta.sources

    # Narrations were actually replaced by Hindi.
    for new, old in zip(out.scenes, original.scenes, strict=True):
        assert new.narration != old.narration
    assert result.notes == []


def test_partial_translation_keeps_english_and_notes_missing_index():
    original = make_blueprint()
    fake = FakeLLMClient(replies=[hindi_json(indices=[1, 3])])
    result = LocalizerAgent(fake).run(original)

    assert result.status == "ok"
    out = result.data
    assert any("scene 2" in note for note in result.notes)

    # Scene 2 (index 2) keeps its English narration.
    scene_two = next(s for s in out.scenes if s.index == 2)
    original_two = next(s for s in original.scenes if s.index == 2)
    assert scene_two.narration == original_two.narration

    # The translated scenes changed.
    scene_one = next(s for s in out.scenes if s.index == 1)
    assert scene_one.narration != "English narration one."


def test_reply_with_no_scenes_fails():
    fake = FakeLLMClient(replies=[json.dumps({"title": "x", "scenes": []})])
    result = LocalizerAgent(fake).run(make_blueprint())

    assert result.status == "fail"
    assert result.notes


def test_malformed_json_fails_without_escaping():
    fake = FakeLLMClient(replies=["not json at all"])
    result = LocalizerAgent(fake).run(make_blueprint())

    assert result.status == "fail"
    assert result.notes


def test_prompt_includes_original_english_narration():
    fake = FakeLLMClient(replies=[hindi_json()])
    LocalizerAgent(fake).run(make_blueprint())

    prompt = fake.calls[0]["prompt"]
    assert "English narration one." in prompt
    assert "English narration two." in prompt
    assert "The Rise of Local LLMs" in prompt
