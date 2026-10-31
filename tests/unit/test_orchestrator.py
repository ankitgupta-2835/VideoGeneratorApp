"""Task 5.3 tests: end-to-end orchestrator (dry-run capable)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.notify import FakeNotifier
from src.pipeline.orchestrator import (
    CHECKPOINTS,
    Orchestrator,
    RunContext,
    StageResult,
    StageStatus,
    build_dry_run_stages,
    new_run_id,
)
from src.rerun.controller import STAGE_ORDER, Stage
from src.store.db import Database


def all_ok_stages(*, artifact: bool = False) -> dict[Stage, object]:
    def make(stage: Stage):
        def fn(ctx: RunContext) -> StageResult:
            if not artifact:
                return StageResult(status="ok")
            path = Path(ctx.work_dir) / f"{stage.value}.out"
            path.write_text(stage.value, encoding="utf-8")
            return StageResult(status="ok", artifact=str(path))

        return fn

    return {stage: make(stage) for stage in STAGE_ORDER}


class BoomNotifier:
    def send(self, text: str) -> None:  # noqa: ARG002
        raise RuntimeError("telegram down")


# --------------------------------------------------------------------------- #
# (1) all-ok run
# --------------------------------------------------------------------------- #
def test_all_ok_run_records_every_stage_and_artifacts(tmp_path: Path):
    orch = Orchestrator(all_ok_stages(artifact=True))
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "ok"
    assert state.category == "ai_tech"
    assert state.language == "en"
    for stage in STAGE_ORDER:
        assert state.stages[stage.value] == StageStatus.OK.value
    assert state.completed == [stage.value for stage in STAGE_ORDER]
    assert set(state.artifacts) == {stage.value for stage in STAGE_ORDER}


# --------------------------------------------------------------------------- #
# (2) a failing stage stops the run; later stages never run
# --------------------------------------------------------------------------- #
def test_fail_stage_stops_run_and_later_stages_not_run(tmp_path: Path):
    calls: list[str] = []

    def make(stage: Stage):
        def fn(ctx: RunContext) -> StageResult:
            calls.append(stage.value)
            if stage is Stage.SCRIPT:
                return StageResult(status="fail", notes=["script rejected"])
            return StageResult(status="ok")

        return fn

    orch = Orchestrator({stage: make(stage) for stage in STAGE_ORDER})
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "failed"
    assert state.stages[Stage.SCRIPT.value] == StageStatus.FAIL.value
    # nothing after SCRIPT ran
    idx = STAGE_ORDER.index(Stage.SCRIPT)
    for later in STAGE_ORDER[idx + 1 :]:
        assert later.value not in calls
        assert state.stages[later.value] == StageStatus.PENDING.value
    assert any("rejected" in note for note in state.notes)


# --------------------------------------------------------------------------- #
# (3) rework contract
# --------------------------------------------------------------------------- #
def test_rework_exhausts_retries_then_fails(tmp_path: Path):
    calls = {"n": 0}

    def fn(ctx: RunContext) -> StageResult:
        calls["n"] += 1
        return StageResult(status="rework")

    orch = Orchestrator({Stage.TREND: fn}, max_rework=2)
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "failed"
    assert state.stages[Stage.TREND.value] == StageStatus.FAIL.value
    assert calls["n"] == 3  # first attempt + max_rework (2) retries
    assert any("rework" in note for note in state.notes)


def test_rework_once_then_ok_succeeds(tmp_path: Path):
    calls = {"n": 0}

    def fn(ctx: RunContext) -> StageResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return StageResult(status="rework")
        return StageResult(status="ok")

    orch = Orchestrator({Stage.TREND: fn}, max_rework=2)
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "ok"
    assert state.stages[Stage.TREND.value] == StageStatus.OK.value
    assert calls["n"] == 2


# --------------------------------------------------------------------------- #
# (4) unwired stages are skipped
# --------------------------------------------------------------------------- #
def test_unwired_stages_are_skipped(tmp_path: Path):
    orch = Orchestrator({Stage.TREND: lambda ctx: StageResult(status="ok")})
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "ok"  # skipped stages do not block
    assert state.stages[Stage.TREND.value] == StageStatus.OK.value
    for stage in STAGE_ORDER:
        if stage is not Stage.TREND:
            assert state.stages[stage.value] == StageStatus.SKIPPED.value


# --------------------------------------------------------------------------- #
# (5) checkpoint alerts
# --------------------------------------------------------------------------- #
def test_checkpoint_alerts_sent(tmp_path: Path):
    notifier = FakeNotifier()
    orch = Orchestrator(all_ok_stages(), notifier=notifier)
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "ok"
    assert len(notifier.messages) == len(CHECKPOINTS)
    joined = "\n".join(notifier.messages)
    for checkpoint in CHECKPOINTS.values():
        assert f"{checkpoint.upper()}:" in joined
    assert all(state.run_id in msg for msg in notifier.messages)


def test_checkpoint_only_for_checkpoint_stages(tmp_path: Path):
    notifier = FakeNotifier()
    # only a non-checkpoint stage wired -> no alert
    orch = Orchestrator({Stage.RESEARCH: lambda ctx: StageResult(status="ok")}, notifier=notifier)
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "ok"
    assert notifier.messages == []


# --------------------------------------------------------------------------- #
# (6) a raising notifier does not fail the run
# --------------------------------------------------------------------------- #
def test_raising_notifier_does_not_fail_run(tmp_path: Path):
    orch = Orchestrator(all_ok_stages(), notifier=BoomNotifier())
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "ok"
    assert any("notifier failed" in note for note in state.notes)


# --------------------------------------------------------------------------- #
# (7) persistence
# --------------------------------------------------------------------------- #
def test_store_persists_run_and_alerts(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    db.migrate()
    notifier = FakeNotifier()
    orch = Orchestrator(all_ok_stages(), notifier=notifier, store=db)

    state = orch.run("ai_tech", language="hi", work_dir=tmp_path)

    run = db.get_run(state.run_id)
    assert run is not None
    assert run["category"] == "ai_tech"
    assert run["language"] == "hi"
    assert run["status"] == "ok"

    alerts = db.alerts_for_run(state.run_id)
    assert len(alerts) == len(CHECKPOINTS)
    assert {a["checkpoint"] for a in alerts} == set(CHECKPOINTS.values())
    db.close()


def test_store_records_failed_status(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    db.migrate()
    orch = Orchestrator({Stage.TREND: lambda ctx: StageResult(status="fail")}, store=db)
    state = orch.run("finance", work_dir=tmp_path)

    assert state.status == "failed"
    assert db.get_run(state.run_id)["status"] == "failed"
    db.close()


# --------------------------------------------------------------------------- #
# (8) a raising stage fn -> failed + note
# --------------------------------------------------------------------------- #
def test_raising_stage_fails_run_with_note(tmp_path: Path):
    def boom(ctx: RunContext) -> StageResult:
        raise ValueError("kaboom")

    orch = Orchestrator({Stage.TREND: boom})
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "failed"
    assert state.stages[Stage.TREND.value] == StageStatus.FAIL.value
    assert any("kaboom" in note for note in state.notes)


# --------------------------------------------------------------------------- #
# (9) dry-run stage set writes marker files
# --------------------------------------------------------------------------- #
def test_build_dry_run_stages_writes_markers(tmp_path: Path):
    stages = build_dry_run_stages()
    assert set(stages) == set(STAGE_ORDER)

    orch = Orchestrator(stages)
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "ok"
    for stage in STAGE_ORDER:
        marker = tmp_path / "stages" / f"{stage.value}.txt"
        assert marker.is_file()
        assert state.artifacts[stage.value] == str(marker)


def test_new_run_id_is_category_prefixed():
    run_id = new_run_id("ai_tech")
    assert run_id.startswith("ai_tech-")
    assert run_id != new_run_id("finance")


# --------------------------------------------------------------------------- #
# (extra) context is carried and shared across stages
# --------------------------------------------------------------------------- #
def test_context_artifacts_carried_forward(tmp_path: Path):
    seen: dict[str, str] = {}

    def trend(ctx: RunContext) -> StageResult:
        return StageResult(status="ok", artifact="topic://1")

    def angle(ctx: RunContext) -> StageResult:
        seen.update(ctx.artifacts)
        return StageResult(status="ok")

    orch = Orchestrator({Stage.TREND: trend, Stage.ANGLE: angle})
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "ok"
    assert seen == {Stage.TREND.value: "topic://1"}
    assert state.artifacts[Stage.TREND.value] == "topic://1"


def test_default_max_rework_is_two(tmp_path: Path):
    calls = {"n": 0}

    def fn(ctx: RunContext) -> StageResult:
        calls["n"] += 1
        return StageResult(status="rework")

    orch = Orchestrator({Stage.TREND: fn})
    state = orch.run("ai_tech", work_dir=tmp_path)

    assert state.status == "failed"
    assert calls["n"] == 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))


def test_progress_callback_reports_each_stage(tmp_path: Path):
    lines: list[str] = []
    orch = Orchestrator({Stage.TREND: lambda ctx: StageResult(status="ok")})
    orch.run("ai_tech", work_dir=tmp_path, progress=lines.append)

    assert lines[0].endswith("trend ...")
    assert "trend ok (" in lines[1]


def test_progress_callback_includes_failure_reason(tmp_path: Path):
    lines: list[str] = []
    orch = Orchestrator({Stage.TREND: lambda ctx: StageResult(status="fail", notes=["bad source"])})
    orch.run("ai_tech", work_dir=tmp_path, progress=lines.append)

    joined = "\n".join(lines)
    assert "trend FAILED" in joined
    assert "reason: bad source" in joined
