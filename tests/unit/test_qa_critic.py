"""Task 4.2 tests: qa_critic agent (technical + LLM quality gate)."""

from __future__ import annotations

import json
from pathlib import Path

from src.agents.qa_critic import (
    BLACK_FRAME_PENALTY,
    ISSUE_PENALTY,
    SILENCE_PENALTY,
    QaCriticAgent,
    QaInput,
    score_from_checks,
)
from src.llm.client import FakeLLMClient
from src.qa.checks import BlackFrame, QaChecks, Silence
from src.schema.blueprint import Blueprint


def blueprint() -> Blueprint:
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "A Test Blueprint",
                "category": "ai_tech",
                "language": "en",
                "target_duration_sec": 60,
            },
            "scenes": [
                {
                    "index": 1,
                    "narration": "Narration for scene one.",
                    "on_screen_text": "Scene 1",
                    "visual": {"kind": "hero", "keywords": ["k"]},
                    "duration_sec": 30.0,
                    "hero": True,
                },
                {
                    "index": 2,
                    "narration": "Narration for scene two.",
                    "on_screen_text": "Scene 2",
                    "visual": {"kind": "image", "keywords": ["k"]},
                    "duration_sec": 30.0,
                    "hero": False,
                },
            ],
        }
    )


def clean_checks() -> QaChecks:
    return QaChecks(duration_sec=60.0, av_desync_sec=0.05)


def checks_with_issues(*issues: str) -> QaChecks:
    return QaChecks(duration_sec=60.0, av_desync_sec=0.05, issues=list(issues))


def make_input(*, min_score: float = 70.0) -> QaInput:
    return QaInput(
        blueprint=blueprint(),
        video_path=Path("clip.mp4"),
        min_score=min_score,
    )


def fake_runner(checks: QaChecks):
    def runner(video: Path) -> QaChecks:
        assert video == Path("clip.mp4")
        return checks

    return runner


# --- score_from_checks -----------------------------------------------------


def test_clean_checks_scores_100() -> None:
    score, issues = score_from_checks(clean_checks())

    assert score == 100.0
    assert issues == []


def test_two_issues_reduce_score() -> None:
    checks = checks_with_issues("black frame bad", "desync bad")

    score, issues = score_from_checks(checks)

    assert score == 100.0 - 2 * ISSUE_PENALTY
    assert issues == ["black frame bad", "desync bad"]


def test_score_never_below_zero() -> None:
    checks = checks_with_issues(*[f"issue {i}" for i in range(20)])

    score, _ = score_from_checks(checks)

    assert score == 0.0


def test_black_and_silence_duration_penalties() -> None:
    checks = QaChecks(
        duration_sec=60.0,
        black_frames=[BlackFrame(start_sec=0.0, end_sec=2.5)],
        silences=[Silence(start_sec=10.0, end_sec=16.0)],
    )

    score, _ = score_from_checks(checks)

    assert score == 100.0 - BLACK_FRAME_PENALTY - SILENCE_PENALTY


def test_short_black_and_silence_do_not_trigger_penalty() -> None:
    checks = QaChecks(
        duration_sec=60.0,
        black_frames=[BlackFrame(start_sec=0.0, end_sec=1.5)],
        silences=[Silence(start_sec=10.0, end_sec=14.0)],
    )

    score, _ = score_from_checks(checks)

    assert score == 100.0


# --- gate behavior ---------------------------------------------------------


def test_clean_checks_pass_at_default_min_score() -> None:
    agent = QaCriticAgent(checks_runner=fake_runner(clean_checks()))

    result = agent.run(make_input())

    assert result.status == "ok"
    assert result.data.passed is True
    assert result.data.score == 100.0
    assert result.data.technical_issues == []


def test_any_technical_issue_fails_even_with_high_score() -> None:
    checks = checks_with_issues("A/V desync 1.0s exceeds 0.5s")
    agent = QaCriticAgent(checks_runner=fake_runner(checks))

    result = agent.run(make_input(min_score=70.0))

    assert result.status == "ok"
    assert result.data.score == 100.0 - ISSUE_PENALTY  # still above min_score
    assert result.data.score >= 70.0
    assert result.data.passed is False
    assert result.data.technical_issues == ["A/V desync 1.0s exceeds 0.5s"]


def test_low_score_fails_gate_without_issues() -> None:
    agent = QaCriticAgent(checks_runner=fake_runner(clean_checks()))

    result = agent.run(make_input(min_score=100.0))

    # score == 100.0 so it passes at exactly min_score; just below fails.
    assert result.data.passed is True

    result = agent.run(make_input(min_score=100.1))
    assert result.data.passed is False


# --- LLM critique ----------------------------------------------------------


def test_llm_adjustment_raises_and_lowers_score() -> None:
    checks = checks_with_issues("one technical issue")  # base score 85
    up = FakeLLMClient(replies=[json.dumps({"critiques": ["good"], "adjustment": 5.0})])
    down = FakeLLMClient(replies=[json.dumps({"critiques": ["bad"], "adjustment": -5.0})])

    up_result = QaCriticAgent(checks_runner=fake_runner(checks), llm=up).run(make_input())
    down_result = QaCriticAgent(checks_runner=fake_runner(checks), llm=down).run(make_input())

    assert up_result.status == "ok"
    assert down_result.status == "ok"
    assert up_result.data.score == 100.0 - ISSUE_PENALTY + 5.0
    assert down_result.data.score == 100.0 - ISSUE_PENALTY - 5.0
    assert up_result.data.score > down_result.data.score
    assert up_result.data.critiques == ["good"]
    assert down_result.data.critiques == ["bad"]


def test_llm_adjustment_is_clamped_to_bounds() -> None:
    checks = checks_with_issues("one technical issue")  # base score 85
    fake = FakeLLMClient(replies=[json.dumps({"critiques": [], "adjustment": 999.0})])

    result = QaCriticAgent(checks_runner=fake_runner(checks), llm=fake).run(make_input())

    assert result.data.score == 95.0  # 85 + 10 (clamped)


def test_malformed_llm_reply_is_tolerated() -> None:
    fake = FakeLLMClient(replies=["not json at all"])
    agent = QaCriticAgent(checks_runner=fake_runner(clean_checks()), llm=fake)

    result = agent.run(make_input())

    assert result.status == "ok"
    assert result.data.score == 100.0
    assert result.data.critiques == []
    assert any("unavailable" in note for note in result.data.notes)


def test_non_dict_llm_reply_is_tolerated() -> None:
    fake = FakeLLMClient(replies=[json.dumps([1, 2, 3])])
    agent = QaCriticAgent(checks_runner=fake_runner(checks_with_issues("x")), llm=fake)

    result = agent.run(make_input())

    assert result.status == "ok"
    assert result.data.score == 100.0 - ISSUE_PENALTY
    assert any("malformed" in note for note in result.data.notes)


def test_malformed_adjustment_is_tolerated() -> None:
    fake = FakeLLMClient(replies=[json.dumps({"critiques": ["hmm"], "adjustment": "lots"})])
    agent = QaCriticAgent(checks_runner=fake_runner(clean_checks()), llm=fake)

    result = agent.run(make_input())

    assert result.status == "ok"
    assert result.data.score == 100.0
    # The critiques survive even though the adjustment was unusable.
    assert result.data.critiques == ["hmm"]
    assert any("malformed" in note for note in result.data.notes)


def test_prompt_includes_title_and_issues() -> None:
    fake = FakeLLMClient(replies=[json.dumps({"critiques": [], "adjustment": 0.0})])
    agent = QaCriticAgent(checks_runner=fake_runner(checks_with_issues("boom")), llm=fake)

    agent.run(make_input())

    prompt = fake.calls[0]["prompt"]
    assert "A Test Blueprint" in prompt
    assert "boom" in prompt


# --- failure / injection ---------------------------------------------------


def test_checks_runner_raising_returns_fail() -> None:
    def boom(video: Path) -> QaChecks:
        raise RuntimeError("ffmpeg exploded")

    agent = QaCriticAgent(checks_runner=boom)

    result = agent.run(make_input())

    assert result.status == "fail"
    assert any("ffmpeg exploded" in note for note in result.notes)


def test_injected_runner_requires_no_ffmpeg() -> None:
    # The default runner shells out to ffmpeg; injecting a fake means the gate
    # is fully exercisable on machines without ffmpeg installed.
    agent = QaCriticAgent(checks_runner=fake_runner(clean_checks()))

    result = agent.run(make_input())

    assert result.status == "ok"
    assert result.data.passed is True
