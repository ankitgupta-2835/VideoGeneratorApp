"""Blueprint JSON schema and validator.

The blueprint is the structured scene-by-scene script produced by the
narrative stage and consumed by downstream media, localization and
compliance stages. This module is the single, shared data contract for it:

- :class:`Blueprint` and its nested models describe the JSON payload.
- :class:`TimingBudget` describes the acceptable duration window.
- :func:`validate_blueprint` applies cross-cutting, non-schema rules
  (index sequence, timing budget, hero ratio, scene count, on-screen text)
  and returns a list of human-readable issues (empty == valid).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "ON_SCREEN_TEXT_MAX",
    "Blueprint",
    "Meta",
    "Scene",
    "SourceRef",
    "TimingBudget",
    "VisualSpec",
    "hero_ratio",
    "total_duration_sec",
    "validate_blueprint",
]

#: Maximum number of characters allowed in a scene's on-screen text.
ON_SCREEN_TEXT_MAX = 80


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class SourceRef(BaseModel):
    title: str
    url: str | None = None


class VisualSpec(BaseModel):
    kind: Literal["hero", "image", "stock", "motion"]
    prompt: str | None = None
    keywords: list[str] = Field(default_factory=list)
    description: str | None = None


class Scene(BaseModel):
    index: int = Field(ge=1)
    narration: str = Field(min_length=1)
    on_screen_text: str | None = None
    visual: VisualSpec
    duration_sec: float = Field(gt=0)
    hero: bool = False


class Meta(BaseModel):
    title: str = Field(min_length=1)
    category: str
    language: Literal["en", "hi"]
    target_duration_sec: int = Field(gt=0)
    angle: str | None = None
    audience: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)


class Blueprint(BaseModel):
    meta: Meta
    scenes: list[Scene] = Field(min_length=1)


class TimingBudget(BaseModel):
    min_duration_sec: int
    target_duration_sec: int
    max_duration_sec: int

    @model_validator(mode="after")
    def _duration_ordering(self) -> TimingBudget:
        if not (self.min_duration_sec <= self.target_duration_sec <= self.max_duration_sec):
            raise ValueError(
                "durations must satisfy min <= target <= max "
                f"(got {self.min_duration_sec} / {self.target_duration_sec} / "
                f"{self.max_duration_sec})"
            )
        return self


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def total_duration_sec(blueprint: Blueprint) -> float:
    """Return the summed duration of every scene in ``blueprint``."""
    return sum(scene.duration_sec for scene in blueprint.scenes)


def hero_ratio(blueprint: Blueprint) -> float:
    """Return the fraction of scenes marked ``hero`` (0.0 when empty)."""
    if not blueprint.scenes:
        return 0.0
    heroes = sum(1 for scene in blueprint.scenes if scene.hero)
    return heroes / len(blueprint.scenes)


def validate_blueprint(
    blueprint: Blueprint,
    budget: TimingBudget,
    *,
    hero_min_ratio: float = 0.0,
    max_scenes: int | None = None,
) -> list[str]:
    """Validate ``blueprint`` against cross-cutting rules.

    Returns a list of human-readable issue strings; an empty list means the
    blueprint is valid. Schema-level constraints are already enforced by the
    pydantic models, so this function only checks relational rules.
    """
    issues: list[str] = []

    for position, scene in enumerate(blueprint.scenes, start=1):
        if scene.index != position:
            issues.append(f"scene index out of sequence at position {position}")

    total = total_duration_sec(blueprint)
    if total < budget.min_duration_sec:
        issues.append(f"total {total:.1f}s is below minimum {budget.min_duration_sec}s")
    if total > budget.max_duration_sec:
        issues.append(f"total {total:.1f}s exceeds maximum {budget.max_duration_sec}s")

    ratio = hero_ratio(blueprint)
    if ratio < hero_min_ratio:
        issues.append(f"hero ratio {ratio:.2f} below required {hero_min_ratio:.2f}")

    scene_count = len(blueprint.scenes)
    if max_scenes is not None and scene_count > max_scenes:
        issues.append(f"{scene_count} scenes exceeds maximum {max_scenes}")

    for scene in blueprint.scenes:
        if scene.on_screen_text is not None and len(scene.on_screen_text) > ON_SCREEN_TEXT_MAX:
            issues.append(f"on-screen text too long at scene {scene.index}")

    return issues
