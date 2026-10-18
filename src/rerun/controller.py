"""Deterministic re-run planner: scopes and non-overwriting attempt versioning.

When a reviewer rejects a run, the revision policy must answer two questions
without any LLM, network, or media tooling involved:

1. **Which pipeline stages do we replay?** A *scope* names how far back to go.
   ``NEW_TOPIC`` discovers a brand-new topic and replays everything; ``FULL``
   keeps the topic but replays from the angle onwards; ``ASSETS`` keeps the
   script and audio and only regenerates visuals/motion/assembly/short;
   ``SCENES`` is ``ASSETS`` restricted to specific scene indices.

2. **Which attempt directory do we write into?** Every re-run gets a fresh,
   1-based ``attempt-<n>`` directory. Distinct attempt numbers always map to
   distinct directories, so an earlier attempt is never clobbered.

The module is pure and deterministic: given the same inputs it returns the same
plan, and it never touches the filesystem except in :func:`existing_attempts`,
which only *reads* to report which attempts already exist.

Decisions (all encoded below and covered by tests):

* ``STAGE_ORDER`` is exactly the :class:`Stage` member order; stage ordering is
  the enum's definition order, not alphabetical.
* Scope -> first replayed stage:
  ``NEW_TOPIC -> TREND``, ``FULL -> ANGLE``, ``ASSETS -> VISUALS``,
  ``SCENES -> VISUALS``.
* :func:`plan_stages` returns the ordered *suffix* of ``STAGE_ORDER`` beginning
  at the scope's first stage.
* ``stages_reused`` is the ordered *prefix* before that first stage; together
  ``stages_to_run`` and ``stages_reused`` partition ``STAGE_ORDER`` with no gaps
  or duplicates.
* Attempts are 1-based: a fresh run is attempt 1, so
  ``attempt_no = previous_attempts + 1``.
* ``SCENES`` carries its ``scene_indices`` into the plan and records a note.
  ``SCENES`` with an **empty** ``scene_indices`` list does not raise; it records
  a note and degrades to ``ASSETS`` behaviour (replay all visual stages).
* :func:`attempt_dir` only *builds* the path (``base/run/attempt-n``); it never
  creates the directory and never overwrites.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

__all__ = [
    "SCOPE_FIRST_STAGE",
    "STAGE_ORDER",
    "RerunPlan",
    "RerunRequest",
    "Scope",
    "Stage",
    "attempt_dir",
    "existing_attempts",
    "plan_rerun",
    "plan_stages",
]


class Stage(StrEnum):
    """Pipeline stages, declared in canonical execution order."""

    TREND = "trend"
    ANGLE = "angle"
    RESEARCH = "research"
    SCRIPT = "script"
    LOCALIZE = "localize"
    COMPLIANCE = "compliance"
    VOICE = "voice"
    CAPTIONS = "captions"
    VISUALS = "visuals"
    MOTION = "motion"
    ASSEMBLE = "assemble"
    SHORT = "short"
    QA = "qa"
    SEO = "seo"
    PUBLISH = "publish"


#: Canonical execution order — exactly the :class:`Stage` member order.
STAGE_ORDER: list[Stage] = list(Stage)


class Scope(StrEnum):
    """How much of the pipeline a re-run replays."""

    NEW_TOPIC = "new_topic"  # discover a brand-new topic; replay everything
    FULL = "full"  # keep the topic; replay from the angle onwards
    ASSETS = "assets"  # keep script+audio; replay visuals/motion/assemble/short
    SCENES = "scenes"  # like ASSETS but only for the listed scene indices


#: First stage replayed for each scope.
SCOPE_FIRST_STAGE: dict[Scope, Stage] = {
    Scope.NEW_TOPIC: Stage.TREND,
    Scope.FULL: Stage.ANGLE,
    Scope.ASSETS: Stage.VISUALS,
    Scope.SCENES: Stage.VISUALS,
}

_ATTEMPT_RE = re.compile(r"^attempt-(\d+)$")


class RerunRequest(BaseModel):
    """A reviewer's request to re-run (part of) a run."""

    run_id: str
    scope: Scope
    reason: str = ""
    scene_indices: list[int] = Field(default_factory=list)
    feedback: str = ""


class RerunPlan(BaseModel):
    """The deterministic plan derived from a :class:`RerunRequest`."""

    run_id: str
    scope: Scope
    attempt_no: int
    stages_to_run: list[Stage]
    stages_reused: list[Stage]
    scene_indices: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def plan_stages(scope: Scope, *, scene_indices: list[int] | None = None) -> list[Stage]:
    """Return the ordered stages to replay for ``scope``.

    The result is the suffix of :data:`STAGE_ORDER` starting at the scope's
    first stage (:data:`SCOPE_FIRST_STAGE`). ``scene_indices`` does not narrow
    the *stage* list — scene selection is a per-scene concern, not a per-stage
    one — but it is accepted for symmetry with :func:`plan_rerun`. A new list is
    returned on every call, so callers cannot mutate :data:`STAGE_ORDER`.
    """
    first = SCOPE_FIRST_STAGE[scope]
    start = STAGE_ORDER.index(first)
    return list(STAGE_ORDER[start:])


def plan_rerun(request: RerunRequest, *, previous_attempts: int) -> RerunPlan:
    """Build a :class:`RerunPlan` for ``request``.

    Attempt numbering is 1-based: a fresh run has ``previous_attempts == 0`` and
    becomes attempt 1, so ``attempt_no = previous_attempts + 1``.
    ``stages_reused`` is the ordered prefix of :data:`STAGE_ORDER` before the
    first replayed stage, partitioning the order with ``stages_to_run``.

    For ``SCENES`` the requested ``scene_indices`` are carried into the plan and
    a note is recorded. When ``SCENES`` is requested with an empty index list the
    planner does not raise: it records a note and degrades to ``ASSETS``
    behaviour (replay every visual stage).
    """
    scope = request.scope
    explicit_scenes = scope is Scope.SCENES and bool(request.scene_indices)

    stages_to_run = plan_stages(scope, scene_indices=request.scene_indices)
    first = stages_to_run[0]
    stages_reused = list(STAGE_ORDER[: STAGE_ORDER.index(first)])

    notes: list[str] = []
    carried_scenes: list[int] = []

    if scope is Scope.SCENES:
        if explicit_scenes:
            carried_scenes = list(request.scene_indices)
            notes.append(f"scenes scope limited to scene_indices={sorted(carried_scenes)}")
        else:
            notes.append(
                "scenes scope requested with empty scene_indices; "
                "degrading to assets scope (all visual stages)"
            )

    return RerunPlan(
        run_id=request.run_id,
        scope=scope,
        attempt_no=previous_attempts + 1,
        stages_to_run=stages_to_run,
        stages_reused=stages_reused,
        scene_indices=carried_scenes,
        notes=notes,
    )


def attempt_dir(base_dir: Path | str, run_id: str, attempt_no: int) -> Path:
    """Return the versioned directory for ``attempt_no`` of ``run_id``.

    The path is ``base_dir / run_id / f"attempt-{attempt_no}"``. This function
    never creates the directory and never overwrites: it is a pure mapping. The
    guarantee it encodes is that **distinct attempt numbers map to distinct
    directories**, because ``attempt_no`` appears in the final path component,
    so an earlier attempt can never be clobbered by a later one.

    ``attempt_no`` is 1-based; passing a value below 1 raises :class:`ValueError`
    to catch off-by-one errors early.
    """
    if attempt_no < 1:
        raise ValueError(f"attempt_no must be >= 1, got {attempt_no}")
    return Path(base_dir) / run_id / f"attempt-{attempt_no}"


def existing_attempts(base_dir: Path | str, run_id: str) -> list[int]:
    """Return the sorted attempt numbers already present under ``base_dir``.

    Reads ``base_dir / run_id`` and collects the integer suffix of every
    ``attempt-<n>`` directory. A missing run directory (or one with no matching
    entries) yields ``[]``. Callers pass ``len(existing_attempts(...))`` (or its
    max) as ``previous_attempts`` to :func:`plan_rerun` to pick the next number.
    """
    run_dir = Path(base_dir) / run_id
    if not run_dir.is_dir():
        return []
    found: list[int] = []
    for entry in run_dir.iterdir():
        if not entry.is_dir():
            continue
        match = _ATTEMPT_RE.match(entry.name)
        if match is not None:
            found.append(int(match.group(1)))
    return sorted(found)
