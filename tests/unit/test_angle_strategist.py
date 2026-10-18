"""Task 2.2 tests: the ``angle_strategist`` agent."""

from __future__ import annotations

import json

from src.agents.angle_strategist import Angle, AngleStrategistAgent, ChosenAngle
from src.agents.trend_scout import TopicCandidate, TopicCandidates
from src.llm.client import FakeLLMClient


def make_candidates() -> TopicCandidates:
    return TopicCandidates(
        category="tech",
        items=[
            TopicCandidate(title="AI writes code", source="hackernews", score=0.9),
            TopicCandidate(title="Rust takes over", source="reddit", score=0.7),
            TopicCandidate(title="Local LLMs", source="youtube", score=0.5),
        ],
    )


def angle(title: str, score: float) -> dict[str, object]:
    return {
        "title": title,
        "hook": f"hook for {title}",
        "why_viral": "because reasons",
        "target_emotion": "curiosity",
        "score": score,
    }


def reply(angles: list[dict[str, object]], rationale: str = "winner") -> str:
    return json.dumps({"angles": angles, "rationale": rationale})


def test_valid_reply_returns_ok_and_highest_score():
    scores = [0.4, 0.95, 0.2, 0.6, 0.1]
    angles = [angle(f"angle {i}", s) for i, s in enumerate(scores)]
    fake = FakeLLMClient(replies=[reply(angles)])
    result = AngleStrategistAgent(fake).run(make_candidates())

    assert result.status == "ok"
    assert isinstance(result.data, ChosenAngle)
    assert len(result.data.angles) == 5
    assert result.data.chosen.title == "angle 1"
    assert result.data.chosen.score == 0.95
    assert result.data.category == "tech"
    assert result.data.rationale == "winner"
    assert isinstance(result.data.chosen, Angle)


def test_tie_chooses_first_highest():
    angles = [angle("first", 0.8), angle("second", 0.8), angle("low", 0.3)]
    fake = FakeLLMClient(replies=[reply(angles)])
    result = AngleStrategistAgent(fake).run(make_candidates())

    assert result.status == "ok"
    assert result.data.chosen.title == "first"


def test_empty_angles_returns_fail():
    fake = FakeLLMClient(replies=[reply([])])
    result = AngleStrategistAgent(fake).run(make_candidates())

    assert result.status == "fail"
    assert result.data is None
    assert any("no usable angles" in note for note in result.notes)


def test_malformed_json_returns_fail_without_raising():
    fake = FakeLLMClient(replies=["this is not json"])
    result = AngleStrategistAgent(fake).run(make_candidates())

    assert result.status == "fail"
    assert result.data is None
    assert result.notes


def test_prompt_contains_candidate_titles():
    fake = FakeLLMClient(replies=[reply([angle("solo", 0.5)])])
    AngleStrategistAgent(fake).run(make_candidates())

    prompt = fake.calls[0]["prompt"]
    assert "AI writes code" in prompt
    assert "Rust takes over" in prompt
    assert "Local LLMs" in prompt
    assert fake.calls[0]["json_mode"] is True
