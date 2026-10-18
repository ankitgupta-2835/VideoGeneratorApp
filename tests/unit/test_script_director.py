"""Task 2.7 tests: the deterministic ``script_director`` gate."""

from __future__ import annotations

from src.agents.script_director import (
    DirectorInput,
    DirectorReport,
    ScriptDirectorAgent,
)
from src.schema.blueprint import Blueprint, TimingBudget


def make_blueprint(
    *,
    durations: list[float] | None = None,
    heroes: list[bool] | None = None,
    indices: list[int] | None = None,
    narrations: list[str] | None = None,
    language: str = "en",
) -> Blueprint:
    """Build a valid-by-default blueprint, overriding fields as requested."""
    durations = durations if durations is not None else [30.0, 40.0, 50.0]
    count = len(durations)
    heroes = heroes if heroes is not None else [False] * count
    indices = indices if indices is not None else list(range(1, count + 1))
    narrations = (
        narrations
        if narrations is not None
        else [f"Narration for scene {indices[i]}." for i in range(count)]
    )
    scenes = [
        {
            "index": indices[i],
            "narration": narrations[i],
            "on_screen_text": None,
            "visual": {"kind": "hero" if heroes[i] else "image"},
            "duration_sec": durations[i],
            "hero": heroes[i],
        }
        for i in range(count)
    ]
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "A Director Test Blueprint",
                "category": "ai_tech",
                "language": language,
                "target_duration_sec": 120,
            },
            "scenes": scenes,
        }
    )


BUDGET = TimingBudget(min_duration_sec=60, target_duration_sec=120, max_duration_sec=180)


def test_well_formed_blueprint_passes():
    agent = ScriptDirectorAgent()
    result = agent.run(
        DirectorInput(
            blueprint=make_blueprint(heroes=[True, False, False]),
            budget=BUDGET,
        )
    )

    assert result.status == "ok"
    assert isinstance(result.data, DirectorReport)
    assert result.data.passed is True
    assert result.data.issues == []


def test_duration_below_budget_reworks():
    agent = ScriptDirectorAgent()
    budget = TimingBudget(min_duration_sec=200, target_duration_sec=200, max_duration_sec=300)
    result = agent.run(DirectorInput(blueprint=make_blueprint(), budget=budget))

    assert result.status == "rework"
    assert result.data.passed is False
    assert any("below minimum" in issue for issue in result.data.issues)


def test_broken_index_sequence_reworks():
    agent = ScriptDirectorAgent()
    blueprint = make_blueprint(durations=[30.0, 40.0], indices=[1, 3])
    result = agent.run(DirectorInput(blueprint=blueprint, budget=BUDGET))

    assert result.status == "rework"
    assert any("index out of sequence" in issue for issue in result.data.issues)


def test_wrong_required_language_reworks_with_language_issue():
    agent = ScriptDirectorAgent()
    result = agent.run(
        DirectorInput(
            blueprint=make_blueprint(language="en"),
            budget=BUDGET,
            required_language="hi",
        )
    )

    assert result.status == "rework"
    assert any("expected 'hi'" in issue for issue in result.data.issues)


def test_short_scene_narration_reworks():
    agent = ScriptDirectorAgent()
    blueprint = make_blueprint(
        narrations=["Tiny.", "Narration for scene 2.", "Scene 3 words here."]
    )
    result = agent.run(
        DirectorInput(
            blueprint=blueprint,
            budget=BUDGET,
            min_scene_narration_chars=20,
        )
    )

    assert result.status == "rework"
    assert any("narration too short" in issue for issue in result.data.issues)


def test_checks_run_is_positive_and_stable():
    agent = ScriptDirectorAgent()
    payload = DirectorInput(
        blueprint=make_blueprint(heroes=[True, False, False]),
        budget=BUDGET,
        required_language="en",
    )
    first = agent.run(payload)
    second = agent.run(payload)

    assert first.status == "ok"
    assert first.data.checks_run > 0
    assert first.data.checks_run == second.data.checks_run
