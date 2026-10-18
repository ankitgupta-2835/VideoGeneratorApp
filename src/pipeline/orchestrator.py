"""End-to-end pipeline orchestrator (dry-run capable).

This is the supervisor that drives the pipeline stages *in order*, tracks
per-stage state, applies the ``ok`` / ``rework`` / ``fail`` contract, fires the
human checkpoint alerts, and persists run status. Task 5.3 delivers the engine,
a dry-run stage set, and the CLI; real stage wiring lands in task 5.6.

Decisions (all encoded below and covered by tests):

* :meth:`Orchestrator.run` iterates :data:`~src.rerun.controller.STAGE_ORDER`
  and initialises **every** stage to :attr:`StageStatus.PENDING` first. A stage
  with no wired function is recorded :attr:`StageStatus.SKIPPED` — not a
  failure — so a partially wired pipeline still runs.
* A stage returning ``"ok"`` becomes :attr:`StageStatus.OK`; its ``artifact``
  (if any) is recorded under the stage name and carried forward on the
  :class:`RunContext` so later stages can consume it.
* A stage returning ``"rework"`` is retried **in place**. ``max_rework`` is the
  number of *retries* after the first attempt (mirroring
  :attr:`src.agents.base.Agent.max_retries`), so a stage is invoked at most
  ``max_rework + 1`` times. If it still asks for rework, the stage is recorded
  :attr:`StageStatus.FAIL` and the run stops as ``"failed"``. The orchestrator
  never blocks waiting for a human.
* A stage returning ``"fail"``, or a stage function raising any exception, is
  recorded :attr:`StageStatus.FAIL` (with the error in ``notes``) and stops the
  run.
* After a **checkpoint** stage (:data:`CHECKPOINTS`: trend/assemble/publish)
  completes OK, an alert is sent via ``notifier.send(checkpoint_text(...))``.
  A notifier exception is caught and noted, never fatal.
* When a :class:`~src.store.db.Database` is provided, ``create_run`` runs at the
  start, ``set_run_status`` at the end, and ``record_alert`` is called for each
  checkpoint alert.
* :attr:`RunState.status` is ``"ok"`` only if every **wired** stage reached OK;
  skipped stages do not block. Otherwise it is ``"failed"``.
* :func:`build_dry_run_stages` returns one function per stage that merely writes
  a marker file under ``work_dir/stages`` — so ``--dry-run`` produces a complete
  fake run with **zero** external calls.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from src.notify import Notifier, checkpoint_text
from src.rerun.controller import STAGE_ORDER, Stage
from src.store.db import Database

__all__ = [
    "CHECKPOINTS",
    "RunContext",
    "RunState",
    "StageFn",
    "StageResult",
    "StageStatus",
    "Orchestrator",
    "build_dry_run_stages",
    "new_run_id",
]


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    REWORK = "rework"
    FAIL = "fail"
    SKIPPED = "skipped"


class RunContext(BaseModel):
    """Mutable per-run scratch space handed to every stage function."""

    run_id: str
    category: str
    language: str = "en"
    attempt_no: int = 1
    work_dir: Path
    artifacts: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class StageResult(BaseModel):
    """What a stage function returns: ``ok`` | ``rework`` | ``fail``."""

    status: str = "ok"
    artifact: str | None = None
    notes: list[str] = Field(default_factory=list)


StageFn = Callable[[RunContext], StageResult]


class RunState(BaseModel):
    """The final, persisted view of one orchestrator run."""

    run_id: str
    category: str
    language: str
    status: str  # "ok" | "failed"
    attempt_no: int
    stages: dict[str, str] = Field(default_factory=dict)  # Stage.value -> StageStatus.value
    completed: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


#: Stages that emit a human checkpoint alert, keyed to their checkpoint name.
CHECKPOINTS: dict[Stage, str] = {
    Stage.TREND: "topic",
    Stage.ASSEMBLE: "video",
    Stage.PUBLISH: "publish",
}


class Orchestrator:
    """Runs wired stages in order under the rework/fail contract."""

    def __init__(
        self,
        stages: dict[Stage, StageFn],
        *,
        notifier: Notifier | None = None,
        store: Database | None = None,
        max_rework: int = 2,
    ) -> None:
        self._stages = dict(stages)
        self._notifier = notifier
        self._store = store
        self._max_rework = max(0, max_rework)

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def run(
        self,
        category: str,
        *,
        language: str = "en",
        attempt_no: int = 1,
        work_dir: Path,
        run_id: str | None = None,
    ) -> RunState:
        """Execute the wired stages and return the resulting :class:`RunState`.

        ``run_id`` may be supplied by the caller (e.g. the CLI) so the id it
        prints and the one persisted/used for ``work_dir`` are identical; when
        omitted a fresh id is generated.
        """
        run_id = run_id or new_run_id(category)
        state = RunState(
            run_id=run_id,
            category=category,
            language=language,
            status="failed",
            attempt_no=attempt_no,
            stages={stage.value: StageStatus.PENDING.value for stage in STAGE_ORDER},
        )
        ctx = RunContext(
            run_id=run_id,
            category=category,
            language=language,
            attempt_no=attempt_no,
            work_dir=Path(work_dir),
        )

        if self._store is not None:
            self._store.create_run(run_id, category, language)

        for stage in STAGE_ORDER:
            fn = self._stages.get(stage)
            if fn is None:
                state.stages[stage.value] = StageStatus.SKIPPED.value
                continue

            ok, artifact, notes = self._run_stage(stage, fn, ctx)
            state.notes.extend(notes)
            ctx.notes.extend(notes)

            if not ok:
                state.stages[stage.value] = StageStatus.FAIL.value
                break

            state.stages[stage.value] = StageStatus.OK.value
            state.completed.append(stage.value)
            if artifact is not None:
                state.artifacts[stage.value] = artifact
                ctx.artifacts[stage.value] = artifact
            self._fire_checkpoint(stage, artifact, state)
        else:
            state.status = "ok"

        if self._store is not None:
            self._store.set_run_status(run_id, state.status)

        return state

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _run_stage(
        self, stage: Stage, fn: StageFn, ctx: RunContext
    ) -> tuple[bool, str | None, list[str]]:
        """Invoke ``fn`` with in-place rework retries.

        Returns ``(ok, artifact, notes)``. ``max_rework`` is the number of
        retries after the first call, so at most ``max_rework + 1`` calls are
        made before the stage is failed.
        """
        notes: list[str] = []
        retries = 0
        while True:
            try:
                result = fn(ctx)
            except Exception as exc:  # noqa: BLE001 - a stage may raise anything
                notes.append(f"{stage.value} raised: {exc}")
                return False, None, notes

            if not isinstance(result, StageResult):
                notes.append(f"{stage.value} returned a non-StageResult: {result!r}")
                return False, None, notes

            notes.extend(result.notes)

            if result.status == "ok":
                return True, result.artifact, notes
            if result.status == "fail":
                notes.append(f"{stage.value} failed")
                return False, None, notes
            if result.status == "rework":
                if retries >= self._max_rework:
                    notes.append(
                        f"{stage.value} still requested rework after "
                        f"{self._max_rework} retries; failing"
                    )
                    return False, None, notes
                retries += 1
                continue

            notes.append(f"{stage.value} returned unknown status {result.status!r}")
            return False, None, notes

    def _fire_checkpoint(self, stage: Stage, artifact: str | None, state: RunState) -> None:
        checkpoint = CHECKPOINTS.get(stage)
        if checkpoint is None:
            return

        message = f"{stage.value} stage complete"
        if artifact:
            message += f": {artifact}"

        if self._store is not None:
            try:
                self._store.record_alert(checkpoint, message, run_id=state.run_id)
            except Exception as exc:  # noqa: BLE001 - persistence must not be fatal
                state.notes.append(f"store record_alert failed: {exc}")

        if self._notifier is not None:
            try:
                self._notifier.send(checkpoint_text(checkpoint, message, run_id=state.run_id))
            except Exception as exc:  # noqa: BLE001 - alerts must never be fatal
                state.notes.append(f"notifier failed: {exc}")


def build_dry_run_stages() -> dict[Stage, StageFn]:
    """Return one fake function per stage that writes a marker file only.

    Each function creates ``work_dir/stages/<stage>.txt`` and returns an OK
    :class:`StageResult` pointing at it, so ``--dry-run`` completes a full run
    with no network, media, or agent work.
    """

    def make(stage: Stage) -> StageFn:
        def run_stage(ctx: RunContext) -> StageResult:
            stages_dir = Path(ctx.work_dir) / "stages"
            stages_dir.mkdir(parents=True, exist_ok=True)
            marker = stages_dir / f"{stage.value}.txt"
            marker.write_text(
                f"dry-run stage {stage.value} for run {ctx.run_id}\n",
                encoding="utf-8",
            )
            return StageResult(status="ok", artifact=str(marker))

        return run_stage

    return {stage: make(stage) for stage in STAGE_ORDER}


def new_run_id(category: str) -> str:
    """Build a deterministic-ish run id: ``<category>-<UTC timestamp>``."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{category}-{stamp}"
