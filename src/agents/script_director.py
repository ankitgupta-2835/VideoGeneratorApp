"""``script_director`` gate: the deterministic blueprint quality gate.

The director is the last checkpoint before a blueprint leaves the narrative
stage. It combines the shared relational validator
(:func:`~src.schema.blueprint.validate_blueprint` — index sequence, timing
budget, hero ratio, scene count and on-screen text) with two tone-oriented
rules that are specific to this gate:

- an optional **language** requirement (the blueprint must be authored in the
  requested language), and
- a **narration length** floor so no scene is a throwaway one-liner.

The gate is deterministic and network-free. It returns a
:class:`DirectorReport` and signals ``rework`` whenever any issue is found so
the responsible narrative agent can revise the offending scene.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.agents.base import Agent, AgentResult
from src.schema.blueprint import Blueprint, TimingBudget, validate_blueprint

__all__ = ["DirectorInput", "DirectorReport", "ScriptDirectorAgent"]


class DirectorReport(BaseModel):
    """Output contract: the gate's verdict and the issues that drove it."""

    passed: bool
    issues: list[str] = Field(default_factory=list)
    checks_run: int = 0


class DirectorInput(BaseModel):
    """Input contract: the blueprint plus the tuning knobs for the gate."""

    blueprint: Blueprint
    budget: TimingBudget
    hero_min_ratio: float = 0.3
    max_scenes: int | None = None
    required_language: str | None = None
    min_scene_narration_chars: int = 20


class ScriptDirectorAgent(Agent):
    """Deterministic blueprint gate: structure, timing, hero, tone."""

    name = "script_director"
    input_model = DirectorInput
    output_model = DirectorReport

    def _run(self, payload: DirectorInput) -> AgentResult:
        issues: list[str] = []

        # Rule group 1 (always evaluated): schema/timing/index/hero ratio/
        # scene count/on-screen text, all handled by the shared validator.
        issues.extend(
            validate_blueprint(
                payload.blueprint,
                payload.budget,
                hero_min_ratio=payload.hero_min_ratio,
                max_scenes=payload.max_scenes,
            )
        )

        # Rule group 2 (only when a language is required): language tone.
        if payload.required_language is not None:
            meta_language = payload.blueprint.meta.language
            if meta_language != payload.required_language:
                issues.append(
                    f"language is {meta_language!r}, expected {payload.required_language!r}"
                )

        # Rule group 3 (always evaluated): narration length tone.
        for scene in payload.blueprint.scenes:
            stripped_len = len(scene.narration.strip())
            if stripped_len < payload.min_scene_narration_chars:
                issues.append(f"scene {scene.index} narration too short ({stripped_len} chars)")

        # ``checks_run`` counts the distinct rule groups exercised above.
        checks_run = 2  # structure/timing/index/hero/count + narration length
        if payload.required_language is not None:
            checks_run += 1  # language tone

        if issues:
            report = DirectorReport(passed=False, issues=issues, checks_run=checks_run)
            return AgentResult(status="rework", data=report, notes=issues)

        report = DirectorReport(passed=True, issues=[], checks_run=checks_run)
        return AgentResult(
            status="ok",
            data=report,
            notes=["blueprint passed all checks"],
        )
