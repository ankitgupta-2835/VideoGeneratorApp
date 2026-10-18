"""``angle_strategist`` agent: turn ranked topics into viral YouTube angles.

Given a :class:`TopicCandidates` payload, the strategist asks the LLM for a set
of viral angles and then deterministically picks the highest-scoring one (ties
resolve to the first proposed angle). The LLM proposes; the code decides.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from src.agents.base import Agent, AgentResult
from src.agents.trend_scout import TopicCandidates
from src.llm.client import LLMClient

__all__ = ["Angle", "AngleStrategistAgent", "ChosenAngle"]

SYSTEM_PROMPT = (
    "You are a YouTube growth strategist. Given a set of candidate topics, "
    "propose viral video angles that maximize click-through and watch time. "
    "Respond with JSON only, matching exactly this shape:\n"
    '{"angles": [{"title": str, "hook": str, "why_viral": str, '
    '"target_emotion": str, "score": float in [0, 1]}], "rationale": str}\n'
    "`score` is your confidence that the angle will perform well."
)


class Angle(BaseModel):
    """A single proposed viral angle."""

    title: str
    hook: str
    why_viral: str
    target_emotion: str
    score: float = Field(ge=0.0, le=1.0)


class ChosenAngle(BaseModel):
    """Output contract: every proposed angle plus the deterministic winner."""

    category: str
    angles: list[Angle]
    chosen: Angle
    rationale: str


class AngleStrategistAgent(Agent):
    """Turns :class:`TopicCandidates` into a chosen :class:`ChosenAngle`."""

    name = "angle_strategist"
    input_model = TopicCandidates
    output_model = ChosenAngle

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def _build_prompt(self, payload: TopicCandidates) -> str:
        lines = [
            f"Category: {payload.category}",
            "Candidate topics (title | source | score):",
        ]
        for item in payload.items:
            lines.append(f"- {item.title} | {item.source} | {item.score:.3f}")
        lines.append("")
        lines.append("Propose several viral angles for this category.")
        return "\n".join(lines)

    def _parse_angles(self, raw: Any) -> tuple[list[Angle], list[str]]:
        """Validate each proposed angle; drop unusable ones with a note."""
        angles: list[Angle] = []
        notes: list[str] = []
        if not isinstance(raw, dict):
            return angles, ["LLM reply was not a JSON object"]
        raw_angles = raw.get("angles")
        if not isinstance(raw_angles, list):
            return angles, ["LLM reply had no angle list"]
        for index, entry in enumerate(raw_angles):
            try:
                angles.append(Angle.model_validate(entry))
            except ValidationError as exc:
                notes.append(f"dropped invalid angle #{index}: {exc.error_count()} error(s)")
        return angles, notes

    def _run(self, payload: TopicCandidates) -> AgentResult:
        prompt = self._build_prompt(payload)
        try:
            raw = self._llm.complete_json(prompt, system=SYSTEM_PROMPT, temperature=0.7)
        except Exception as exc:  # a provider failure must not escape
            return AgentResult(status="fail", notes=[str(exc)])

        angles, notes = self._parse_angles(raw)
        if not angles:
            return AgentResult(
                status="fail",
                notes=[*notes, "no usable angles in LLM reply"],
            )

        best = max(angles, key=lambda angle: angle.score)  # ties -> first proposed
        rationale = ""
        if isinstance(raw, dict) and isinstance(raw.get("rationale"), str):
            rationale = raw["rationale"]

        data = ChosenAngle(
            category=payload.category,
            angles=angles,
            chosen=best,
            rationale=rationale,
        )
        notes.append(f"chose {best.title!r} (score={best.score:.3f}) of {len(angles)} angles")
        return AgentResult(status="ok", data=data, notes=notes)
