"""Task 2.4 tests: blueprint JSON schema and validator."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schema.blueprint import (
    ON_SCREEN_TEXT_MAX,
    Blueprint,
    TimingBudget,
    hero_ratio,
    total_duration_sec,
    validate_blueprint,
)


def make_blueprint(
    *,
    durations: list[float] | None = None,
    heroes: list[bool] | None = None,
    indices: list[int] | None = None,
    on_screen_texts: list[str | None] | None = None,
    language: str = "en",
) -> Blueprint:
    """Build a valid-by-default blueprint, overriding fields as requested."""
    durations = durations if durations is not None else [30.0, 40.0, 50.0]
    count = len(durations)
    heroes = heroes if heroes is not None else [False] * count
    indices = indices if indices is not None else list(range(1, count + 1))
    on_screen_texts = on_screen_texts if on_screen_texts is not None else [None] * count
    scenes = [
        {
            "index": indices[i],
            "narration": f"Narration for scene {indices[i]}.",
            "on_screen_text": on_screen_texts[i],
            "visual": {"kind": "hero" if heroes[i] else "image"},
            "duration_sec": durations[i],
            "hero": heroes[i],
        }
        for i in range(count)
    ]
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "A Test Blueprint",
                "category": "ai_tech",
                "language": language,
                "target_duration_sec": 120,
            },
            "scenes": scenes,
        }
    )


BUDGET = TimingBudget(min_duration_sec=60, target_duration_sec=120, max_duration_sec=180)


def test_valid_blueprint_passes():
    assert validate_blueprint(make_blueprint(), BUDGET) == []


def test_blueprint_round_trips():
    blueprint = make_blueprint()
    dumped = blueprint.model_dump()
    restored = Blueprint.model_validate(dumped)
    assert restored == blueprint
    assert total_duration_sec(restored) == 120.0


def test_non_positive_duration_rejected():
    with pytest.raises(ValidationError):
        make_blueprint(durations=[0.0])


def test_empty_scenes_rejected():
    with pytest.raises(ValidationError):
        Blueprint.model_validate(
            {
                "meta": {
                    "title": "T",
                    "category": "ai_tech",
                    "language": "en",
                    "target_duration_sec": 120,
                },
                "scenes": [],
            }
        )


def test_empty_narration_rejected():
    with pytest.raises(ValidationError):
        Blueprint.model_validate(
            {
                "meta": {
                    "title": "T",
                    "category": "ai_tech",
                    "language": "en",
                    "target_duration_sec": 120,
                },
                "scenes": [
                    {
                        "index": 1,
                        "narration": "",
                        "visual": {"kind": "image"},
                        "duration_sec": 30.0,
                    }
                ],
            }
        )


def test_bad_language_rejected():
    with pytest.raises(ValidationError):
        make_blueprint(language="fr")


def test_negative_index_rejected():
    with pytest.raises(ValidationError):
        make_blueprint(indices=[0, 2, 3])


def test_timing_budget_rejects_min_above_target():
    with pytest.raises(ValidationError):
        TimingBudget(min_duration_sec=200, target_duration_sec=120, max_duration_sec=300)


def test_total_below_minimum_reports_one_issue():
    budget = TimingBudget(min_duration_sec=150, target_duration_sec=150, max_duration_sec=200)
    issues = validate_blueprint(make_blueprint(), budget)
    assert issues == ["total 120.0s is below minimum 150s"]


def test_total_above_maximum_reports_one_issue():
    budget = TimingBudget(min_duration_sec=10, target_duration_sec=50, max_duration_sec=100)
    issues = validate_blueprint(make_blueprint(), budget)
    assert issues == ["total 120.0s exceeds maximum 100s"]


def test_broken_index_sequence_reports_issue():
    blueprint = make_blueprint(durations=[30.0, 40.0], indices=[1, 3])
    issues = validate_blueprint(blueprint, BUDGET)
    assert issues == ["scene index out of sequence at position 2"]


def test_hero_ratio_not_met_reports_issue():
    blueprint = make_blueprint(heroes=[True, False, False])
    issues = validate_blueprint(blueprint, BUDGET, hero_min_ratio=0.5)
    assert any("hero ratio" in issue for issue in issues)
    assert len(issues) == 1


def test_hero_ratio_met_reports_no_issue():
    blueprint = make_blueprint(heroes=[True, False, False])
    assert validate_blueprint(blueprint, BUDGET, hero_min_ratio=0.3) == []


def test_max_scenes_exceeded_reports_issue():
    issues = validate_blueprint(make_blueprint(), BUDGET, max_scenes=2)
    assert issues == ["3 scenes exceeds maximum 2"]


def test_overlong_on_screen_text_reports_issue():
    too_long = "x" * (ON_SCREEN_TEXT_MAX + 1)
    blueprint = make_blueprint(on_screen_texts=[too_long, None, None])
    issues = validate_blueprint(blueprint, BUDGET)
    assert issues == ["on-screen text too long at scene 1"]


def test_ratio_and_duration_compute_correctly():
    blueprint = make_blueprint(heroes=[True, False, False])
    assert total_duration_sec(blueprint) == 120.0
    assert hero_ratio(blueprint) == pytest.approx(1 / 3)


def test_empty_blueprint_helpers():
    # hero_ratio returns 0.0 for an empty blueprint object built without scenes
    blueprint = make_blueprint(durations=[30.0])
    blueprint.scenes.clear()
    assert hero_ratio(blueprint) == 0.0
