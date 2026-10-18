"""Task 5.2 tests: revision_director agent (feedback -> revision plan + escalation)."""

from __future__ import annotations

import json

from src.agents.qa_critic import QaReport
from src.agents.revision_director import (
    RevisionDirectorAgent,
    RevisionInput,
    escalation_for,
)
from src.llm.client import FakeLLMClient
from src.rerun.controller import Scope, plan_stages


def make_input(
    *,
    scope: Scope = Scope.FULL,
    reason: str = "",
    feedback: str = "",
    scene_indices: list[int] | None = None,
    qa_report: QaReport | None = None,
    previous_attempts: int = 0,
    max_attempts: int = 3,
) -> RevisionInput:
    return RevisionInput(
        run_id="run-1",
        scope=scope,
        reason=reason,
        feedback=feedback,
        scene_indices=scene_indices or [],
        qa_report=qa_report,
        previous_attempts=previous_attempts,
        max_attempts=max_attempts,
    )


def stage_values(scope: Scope) -> list[str]:
    return [stage.value for stage in plan_stages(scope)]


# --- escalation ladder ------------------------------------------------------


def test_escalation_ladder_default_max_attempts() -> None:
    assert escalation_for(1) == "retry"
    assert escalation_for(2) == "adjust"
    assert escalation_for(3) == "new_topic"
    assert escalation_for(4) == "new_topic"


def test_escalation_ladder_respects_max_attempts() -> None:
    assert escalation_for(1, max_attempts=5) == "retry"
    assert escalation_for(2, max_attempts=5) == "adjust"
    assert escalation_for(4, max_attempts=5) == "adjust"
    assert escalation_for(5, max_attempts=5) == "new_topic"
    assert escalation_for(6, max_attempts=5) == "new_topic"


def test_agent_applies_escalation_ladder_to_attempt_number() -> None:
    agent = RevisionDirectorAgent()

    first = agent.run(make_input(previous_attempts=0))
    second = agent.run(make_input(previous_attempts=1))
    third = agent.run(make_input(previous_attempts=2))

    assert first.data.escalation == "retry"
    assert second.data.escalation == "adjust"
    assert third.data.escalation == "new_topic"


# --- stage selection delegated to the rerun controller ----------------------


def test_stages_match_plan_stages_and_attempt_is_one_based() -> None:
    agent = RevisionDirectorAgent()

    for scope in (Scope.FULL, Scope.ASSETS):
        result = agent.run(make_input(scope=scope, previous_attempts=2))
        assert result.status == "ok"
        assert result.data.stages_to_run == stage_values(scope)
        assert result.data.attempt_no == 3  # previous_attempts + 1


def test_stages_reused_matches_controller_for_full_scope() -> None:
    agent = RevisionDirectorAgent()

    result = agent.run(make_input(scope=Scope.FULL, previous_attempts=0))

    assert result.data.stages_to_run[0] == "angle"
    assert "trend" in result.data.stages_reused
    assert "angle" not in result.data.stages_reused


def test_scenes_scope_carries_scene_indices() -> None:
    agent = RevisionDirectorAgent()

    result = agent.run(make_input(scope=Scope.SCENES, scene_indices=[0, 2, 5], previous_attempts=0))

    assert result.status == "ok"
    assert result.data.scene_indices == [0, 2, 5]
    assert result.data.stages_to_run == stage_values(Scope.ASSETS)


# --- LLM instructions -------------------------------------------------------


def test_llm_instructions_appear_in_plan() -> None:
    fake = FakeLLMClient(
        replies=[json.dumps({"instructions": ["Regenerate scene 2 visuals", "Tighten CTA"]})]
    )
    agent = RevisionDirectorAgent(llm=fake)

    result = agent.run(make_input(reason="too long", feedback="pacing drags"))

    assert result.status == "ok"
    assert result.data.instructions == ["Regenerate scene 2 visuals", "Tighten CTA"]
    assert not any("fallback" in note for note in result.data.notes)


def test_llm_prompt_includes_feedback_text() -> None:
    fake = FakeLLMClient(replies=[json.dumps({"instructions": ["do a thing"]})])
    agent = RevisionDirectorAgent(llm=fake)

    agent.run(make_input(reason="boring", feedback="the ending is too abrupt"))

    prompt = fake.calls[0]["prompt"]
    assert "the ending is too abrupt" in prompt
    assert "boring" in prompt


def test_malformed_llm_reply_falls_back_to_deterministic_instructions() -> None:
    fake = FakeLLMClient(replies=["not json at all"])
    agent = RevisionDirectorAgent(llm=fake)

    result = agent.run(make_input(scope=Scope.ASSETS, feedback="visuals are flat"))

    assert result.status == "ok"
    assert result.data.instructions  # deterministic fallback, never empty
    assert any("visuals" in instruction for instruction in result.data.instructions)
    assert any("fallback" in note for note in result.data.notes)


def test_non_dict_llm_reply_is_tolerated() -> None:
    fake = FakeLLMClient(replies=[json.dumps([1, 2, 3])])
    agent = RevisionDirectorAgent(llm=fake)

    result = agent.run(make_input(scope=Scope.SCENES, scene_indices=[1]))

    assert result.status == "ok"
    assert result.data.instructions
    assert any("malformed" in note for note in result.data.notes)


def test_no_llm_uses_deterministic_instructions_mentioning_issues() -> None:
    report = QaReport(
        score=40.0,
        passed=False,
        technical_issues=["audio gap at 12s"],
        critiques=["hero shot is bland"],
    )
    agent = RevisionDirectorAgent()

    result = agent.run(make_input(qa_report=report, scope=Scope.ASSETS))

    assert result.status == "ok"
    joined = " ".join(result.data.instructions)
    assert "audio gap at 12s" in joined
    assert "hero shot is bland" in joined


# --- escalation note --------------------------------------------------------


def test_max_attempts_reached_adds_new_topic_note() -> None:
    agent = RevisionDirectorAgent()

    result = agent.run(make_input(previous_attempts=2, max_attempts=3))

    assert result.data.escalation == "new_topic"
    assert any("fresh topic" in note for note in result.data.notes)


def test_below_max_attempts_has_no_new_topic_note() -> None:
    agent = RevisionDirectorAgent()

    result = agent.run(make_input(previous_attempts=0, max_attempts=3))

    assert result.data.escalation == "retry"
    assert not any("fresh topic" in note for note in result.data.notes)
