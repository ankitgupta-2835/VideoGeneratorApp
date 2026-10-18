"""Task 2.3 tests: the ``research`` agent and its deterministic fact-check."""

from __future__ import annotations

import json

from src.agents.angle_strategist import Angle, ChosenAngle
from src.agents.research import Fact, ResearchAgent, ResearchBrief
from src.llm.client import FakeLLMClient


def make_chosen() -> ChosenAngle:
    angle = Angle(
        title="AI writes code",
        hook="What if AI writes your code?",
        why_viral="Developers fear replacement",
        target_emotion="curiosity",
        score=0.9,
    )
    return ChosenAngle(
        category="tech",
        angles=[angle],
        chosen=angle,
        rationale="highest score",
    )


def reply(
    facts: list[dict[str, object]],
    sources: list[dict[str, object]] | None = None,
    summary: str = "a brief summary",
) -> str:
    return json.dumps({"summary": summary, "facts": facts, "sources": sources or []})


def fact(text: str, source: str | None = None, confidence: str = "low") -> dict[str, object]:
    return {"text": text, "source": source, "confidence": confidence}


def test_sourced_facts_ok_with_no_flags():
    facts = [
        fact("AI writes code", source="https://example.com/a", confidence="high"),
        fact("Developers use AI tools", source="https://example.com/b", confidence="medium"),
    ]
    fake = FakeLLMClient(
        replies=[reply(facts, sources=[{"title": "Example", "url": "https://example.com"}])]
    )
    result = ResearchAgent(fake).run(make_chosen())

    assert result.status == "ok"
    assert isinstance(result.data, ResearchBrief)
    assert result.data.category == "tech"
    assert result.data.angle_title == "AI writes code"
    assert len(result.data.facts) == 2
    assert result.data.misinformation_flags == []
    assert result.data.facts[0].confidence == "high"
    assert result.data.facts[1].confidence == "medium"
    assert len(result.data.sources) == 1


def test_unsourced_fact_is_flagged_and_downgraded():
    facts = [fact("AI writes code", source="", confidence="medium")]
    fake = FakeLLMClient(replies=[reply(facts)])
    result = ResearchAgent(fake).run(make_chosen())

    assert result.status == "ok"
    assert result.data.facts[0].confidence == "low"
    assert "unsourced claim: AI writes code" in result.data.misinformation_flags


def test_high_confidence_unsourced_fact_is_downgraded_and_flagged():
    facts = [fact("AI writes code", source=None, confidence="high")]
    fake = FakeLLMClient(replies=[reply(facts)])
    result = ResearchAgent(fake).run(make_chosen())

    assert result.status == "ok"
    assert result.data.facts[0].confidence == "low"
    assert result.data.misinformation_flags == ["unsourced claim: AI writes code"]


def test_empty_facts_returns_fail():
    fake = FakeLLMClient(replies=[reply([])])
    result = ResearchAgent(fake).run(make_chosen())

    assert result.status == "fail"
    assert result.data is None
    assert any("no facts" in note for note in result.notes)


def test_malformed_json_returns_fail_without_raising():
    fake = FakeLLMClient(replies=["this is not json"])
    result = ResearchAgent(fake).run(make_chosen())

    assert result.status == "fail"
    assert result.data is None
    assert result.notes


def test_prompt_contains_angle_title():
    facts = [fact("AI writes code", source="https://example.com", confidence="high")]
    fake = FakeLLMClient(replies=[reply(facts)])
    ResearchAgent(fake).run(make_chosen())

    prompt = fake.calls[0]["prompt"]
    assert "AI writes code" in prompt
    assert "What if AI writes your code?" in prompt
    assert "tech" in prompt
    assert fake.calls[0]["json_mode"] is True


def test_malformed_entries_are_dropped_with_note():
    facts = [
        fact("good fact", source="https://example.com", confidence="high"),
        {"source": "missing text"},
    ]
    fake = FakeLLMClient(replies=[reply(facts)])
    result = ResearchAgent(fake).run(make_chosen())

    assert result.status == "ok"
    assert isinstance(result.data, ResearchBrief)
    assert len(result.data.facts) == 1
    assert isinstance(result.data.facts[0], Fact)
    assert any("dropped invalid fact" in note for note in result.notes)
