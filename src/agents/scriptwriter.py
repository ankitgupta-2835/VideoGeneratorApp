"""``scriptwriter`` agent: author the English master blueprint.

The writer takes a framed request (title, angle, category, audience, duration
window, facts, sources) and asks the LLM for a scene-by-scene
:class:`~src.schema.blueprint.Blueprint`. The reply is validated against the
schema and then scored by :func:`~src.schema.blueprint.validate_blueprint`
against the requested timing budget.

The writer deliberately does **not** rework a blueprint that only trips the
advisory relational rules (timing, hero ratio, index sequence): those issues
are surfaced as ``notes`` for the downstream ``script_director`` gate to act
on. Only a schema-invalid reply or an LLM failure is a hard ``fail``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from src.agents.base import Agent, AgentResult
from src.llm.client import LLMClient
from src.schema.blueprint import Blueprint, TimingBudget, validate_blueprint

__all__ = ["ScriptRequest", "ScriptwriterAgent"]


SYSTEM_PROMPT = (
    "You are a senior narrative scriptwriter for short-form explainer videos. "
    "Return ONLY a single JSON object matching the Blueprint schema: "
    '{"meta": {...}, "scenes": [...]}. '
    'meta must contain title, category, language (use "en"), target_duration_sec, '
    "and may contain angle, audience, and sources (a list of {title, url}). "
    "Each scene must contain index (starting at 1 and strictly sequential), "
    "narration (the spoken script for that scene, in the requested tone), "
    "optional on_screen_text (<= 80 characters), a visual spec, and duration_sec. "
    "A visual spec has kind (one of hero/image/stock/motion), optional prompt, "
    "keywords, and optional description. "
    "Give each scene a sensible duration so the scene durations sum to about the "
    "requested target duration, and mark a strong opening scene as hero. "
    "Do not include commentary, markdown, or code fences."
)


class ScriptRequest(BaseModel):
    """Input contract for the scriptwriter."""

    title: str
    angle: str
    category: str
    audience: str | None = None
    duration_target_sec: int = 270
    min_duration_sec: int = 240
    max_duration_sec: int = 330
    facts: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ScriptwriterAgent(Agent):
    """LLM-backed author of the English master blueprint."""

    name = "scriptwriter"
    input_model = ScriptRequest
    output_model = Blueprint

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def _build_prompt(self, payload: ScriptRequest) -> str:
        lines = [
            "Write the master blueprint for a short-form video.",
            f"Title: {payload.title}",
            f"Angle: {payload.angle}",
            f"Category: {payload.category}",
            f"Target duration (seconds): {payload.duration_target_sec}",
            (
                "Acceptable duration window (seconds): "
                f"{payload.min_duration_sec}-{payload.max_duration_sec}"
            ),
        ]
        if payload.audience:
            lines.append(f"Audience: {payload.audience}")
        if payload.facts:
            lines.append("Facts to weave in:")
            lines.extend(f"- {fact}" for fact in payload.facts)
        if payload.sources:
            lines.append("Sources:")
            lines.extend(f"- {source}" for source in payload.sources)
        lines.append('Set meta.language to "en".')
        return "\n".join(lines)

    def _run(self, payload: ScriptRequest) -> AgentResult:
        prompt = self._build_prompt(payload)
        try:
            raw = self._llm.complete_json(prompt, system=SYSTEM_PROMPT)
        except Exception as exc:  # an LLM/provider failure is a hard fail
            return AgentResult(status="fail", notes=[str(exc)])

        try:
            blueprint = Blueprint.model_validate(raw)
        except ValidationError as exc:
            return AgentResult(status="fail", notes=[f"invalid blueprint: {exc}"])

        budget = TimingBudget(
            min_duration_sec=payload.min_duration_sec,
            target_duration_sec=payload.duration_target_sec,
            max_duration_sec=payload.max_duration_sec,
        )
        issues = validate_blueprint(blueprint, budget)
        return AgentResult(status="ok", data=blueprint, notes=issues)
