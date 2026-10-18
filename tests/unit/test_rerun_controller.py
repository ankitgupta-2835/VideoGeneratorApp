"""Task 5.1 tests: deterministic rerun controller (scopes + attempt versioning)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.rerun.controller import (
    SCOPE_FIRST_STAGE,
    STAGE_ORDER,
    RerunRequest,
    Scope,
    Stage,
    attempt_dir,
    existing_attempts,
    plan_rerun,
    plan_stages,
)

ALL_SCOPES = [Scope.NEW_TOPIC, Scope.FULL, Scope.ASSETS, Scope.SCENES]


def test_stage_order_matches_enum_declaration_order():
    # STAGE_ORDER is exactly the enum member order, not alphabetical.
    assert STAGE_ORDER == list(Stage)
    assert STAGE_ORDER[0] is Stage.TREND
    assert STAGE_ORDER[-1] is Stage.PUBLISH
    assert len(STAGE_ORDER) == 15
    assert len(set(STAGE_ORDER)) == 15


def test_scope_first_stage_mapping():
    assert SCOPE_FIRST_STAGE[Scope.NEW_TOPIC] is Stage.TREND
    assert SCOPE_FIRST_STAGE[Scope.FULL] is Stage.ANGLE
    assert SCOPE_FIRST_STAGE[Scope.ASSETS] is Stage.VISUALS
    assert SCOPE_FIRST_STAGE[Scope.SCENES] is Stage.VISUALS


@pytest.mark.parametrize("scope", ALL_SCOPES)
def test_plan_stages_is_ordered_suffix_starting_at_first_stage(scope: Scope):
    stages = plan_stages(scope)
    expected_first = SCOPE_FIRST_STAGE[scope]
    assert stages[0] is expected_first
    start = STAGE_ORDER.index(expected_first)
    assert stages == STAGE_ORDER[start:]


def test_first_stage_per_scope():
    assert plan_stages(Scope.NEW_TOPIC)[0] is Stage.TREND
    assert plan_stages(Scope.FULL)[0] is Stage.ANGLE
    assert plan_stages(Scope.ASSETS)[0] is Stage.VISUALS
    assert plan_stages(Scope.SCENES)[0] is Stage.VISUALS


def test_plan_stages_returns_a_fresh_list():
    a = plan_stages(Scope.NEW_TOPIC)
    a.append(Stage.TREND)
    assert plan_stages(Scope.NEW_TOPIC) == STAGE_ORDER


@pytest.mark.parametrize("scope", ALL_SCOPES)
def test_to_run_plus_reused_partitions_stage_order(scope: Scope):
    plan = plan_rerun(RerunRequest(run_id="r1", scope=scope), previous_attempts=0)
    combined = plan.stages_reused + plan.stages_to_run
    assert combined == STAGE_ORDER
    # no gaps or duplicates
    assert len(combined) == len(STAGE_ORDER)
    assert set(combined) == set(STAGE_ORDER)
    assert not (set(plan.stages_to_run) & set(plan.stages_reused))


def test_plan_rerun_attempt_number_is_one_based():
    plan = plan_rerun(RerunRequest(run_id="run-7", scope=Scope.FULL), previous_attempts=2)
    assert plan.attempt_no == 3
    assert plan.run_id == "run-7"
    assert plan.scope is Scope.FULL

    fresh = plan_rerun(RerunRequest(run_id="run-7", scope=Scope.NEW_TOPIC), previous_attempts=0)
    assert fresh.attempt_no == 1
    assert fresh.stages_reused == []


def test_scenes_scope_carries_scene_indices_and_notes():
    plan = plan_rerun(
        RerunRequest(run_id="r", scope=Scope.SCENES, scene_indices=[2, 0, 2]),
        previous_attempts=4,
    )
    assert plan.attempt_no == 5
    assert plan.scene_indices == [2, 0, 2]
    assert plan.stages_to_run == plan_stages(Scope.ASSETS)
    assert any("scene_indices" in note for note in plan.notes)


def test_scenes_scope_empty_indices_degrades_to_assets():
    plan = plan_rerun(RerunRequest(run_id="r", scope=Scope.SCENES), previous_attempts=1)
    # Degrades to ASSETS-like behaviour: replay all visual stages.
    assert plan.stages_to_run == plan_stages(Scope.ASSETS)
    assert (
        plan.stages_reused
        == plan_rerun(
            RerunRequest(run_id="r", scope=Scope.ASSETS), previous_attempts=1
        ).stages_reused
    )
    assert plan.scene_indices == []
    assert plan.notes  # a note records the degradation


def test_non_scenes_scopes_do_not_carry_scene_indices():
    plan = plan_rerun(
        RerunRequest(run_id="r", scope=Scope.ASSETS, scene_indices=[1, 2]),
        previous_attempts=0,
    )
    assert plan.scene_indices == []
    assert plan.notes == []


def test_attempt_dir_is_pure_mapping_and_does_not_create(tmp_path: Path):
    path = attempt_dir(tmp_path, "run-9", 3)
    assert path == tmp_path / "run-9" / "attempt-3"
    assert isinstance(path, Path)
    assert not path.exists()
    assert not (tmp_path / "run-9").exists()


def test_attempt_dir_accepts_str_base(tmp_path: Path):
    path = attempt_dir(str(tmp_path), "run-9", 3)
    assert path == tmp_path / "run-9" / "attempt-3"


def test_distinct_attempt_numbers_map_to_distinct_dirs(tmp_path: Path):
    a = attempt_dir(tmp_path, "run-1", 1)
    b = attempt_dir(tmp_path, "run-1", 2)
    assert a != b
    assert attempt_dir(tmp_path, "run-1", 3) != attempt_dir(tmp_path, "run-1", 2)
    assert attempt_dir(tmp_path, "run-1", 1) != attempt_dir(tmp_path, "run-2", 1)


def test_attempt_dir_rejects_non_positive_number(tmp_path: Path):
    with pytest.raises(ValueError):
        attempt_dir(tmp_path, "run-1", 0)


def test_existing_attempts_lists_sorted_present_numbers(tmp_path: Path):
    run_dir = tmp_path / "run-1"
    (run_dir / "attempt-1").mkdir(parents=True)
    (run_dir / "attempt-3").mkdir()
    (run_dir / "attempt-2.txt").write_text("not a directory", encoding="utf-8")
    (run_dir / "notes").mkdir()
    assert existing_attempts(tmp_path, "run-1") == [1, 3]


def test_existing_attempts_missing_run_dir_is_empty(tmp_path: Path):
    assert existing_attempts(tmp_path, "does-not-exist") == []


def test_existing_attempts_supports_next_attempt_number(tmp_path: Path):
    run_dir = tmp_path / "run-1"
    (run_dir / "attempt-1").mkdir(parents=True)
    (run_dir / "attempt-2").mkdir()
    previous = len(existing_attempts(tmp_path, "run-1"))
    plan = plan_rerun(RerunRequest(run_id="run-1", scope=Scope.ASSETS), previous_attempts=previous)
    assert plan.attempt_no == 3
    assert attempt_dir(tmp_path, "run-1", plan.attempt_no) == (tmp_path / "run-1" / "attempt-3")
