"""Task 2.5 tests: scriptwriter agent (English master blueprint)."""

from __future__ import annotations

import json

from src.agents.scriptwriter import ScriptRequest, ScriptwriterAgent
from src.llm.client import FakeLLMClient
from src.schema.blueprint import Blueprint


def scene(index: int, duration_sec: float, *, hero: bool = False) -> dict:
    return {
        "index": index,
        "narration": f"Narration for scene {index}.",
        "on_screen_text": f"Scene {index}",
        "visual": {"kind": "hero" if hero else "image", "keywords": ["k"]},
        "duration_sec": duration_sec,
        "hero": hero,
    }


def blueprint_json(durations: list[float]) -> str:
    """Build a valid blueprint JSON string with the given scene durations."""
    payload = {
        "meta": {
            "title": "A Test Blueprint",
            "category": "ai_tech",
            "language": "en",
            "target_duration_sec": int(sum(durations)),
        },
        "scenes": [
            scene(i, duration, hero=(i == 1)) for i, duration in enumerate(durations, start=1)
        ],
    }
    return json.dumps(payload)


def request(**overrides) -> ScriptRequest:
    base = {
        "title": "The Rise of Local LLMs",
        "angle": "why small models now matter",
        "category": "ai_tech",
        "audience": "developers",
        "duration_target_sec": 120,
        "min_duration_sec": 100,
        "max_duration_sec": 140,
        "facts": ["7B models run on laptops"],
        "sources": ["https://example.com/source"],
    }
    base.update(overrides)
    return ScriptRequest(**base)


def test_valid_reply_returns_ok_blueprint():
    fake = FakeLLMClient(replies=[blueprint_json([40.0, 40.0, 40.0])])
    result = ScriptwriterAgent(fake).run(request())
    assert result.status == "ok"
    assert isinstance(result.data, Blueprint)
    assert len(result.data.scenes) == 3
    assert result.notes == []


def test_below_minimum_duration_reports_timing_issue():
    fake = FakeLLMClient(replies=[blueprint_json([10.0, 10.0])])
    result = ScriptwriterAgent(fake).run(request())
    assert result.status == "ok"
    assert any("below minimum" in note for note in result.notes)


def test_missing_scenes_fails():
    fake = FakeLLMClient(replies=[json.dumps({"meta": {}})])
    result = ScriptwriterAgent(fake).run(request())
    assert result.status == "fail"
    assert result.notes


def test_non_dict_reply_fails():
    fake = FakeLLMClient(replies=[json.dumps([1, 2, 3])])
    result = ScriptwriterAgent(fake).run(request())
    assert result.status == "fail"
    assert result.notes


def test_malformed_json_fails_without_escaping():
    fake = FakeLLMClient(replies=["not json at all"])
    result = ScriptwriterAgent(fake).run(request())
    assert result.status == "fail"
    assert result.notes


def test_prompt_includes_title_and_facts():
    fake = FakeLLMClient(replies=[blueprint_json([40.0, 40.0, 40.0])])
    ScriptwriterAgent(fake).run(request())
    prompt = fake.calls[0]["prompt"]
    assert "The Rise of Local LLMs" in prompt
    assert "7B models run on laptops" in prompt
    assert "why small models now matter" in prompt


def test_prompt_includes_compliance_feedback():
    fake = FakeLLMClient(replies=[blueprint_json([40.0, 40.0, 40.0])])
    feedback = ["scene 2: banned medical claim 'cure' in scene 2"]
    ScriptwriterAgent(fake).run(request(compliance_feedback=feedback))
    prompt = fake.calls[0]["prompt"]
    assert "compliance gate" in prompt
    assert "banned medical claim 'cure'" in prompt
