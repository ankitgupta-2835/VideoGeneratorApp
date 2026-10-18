"""``research`` agent: turn a chosen angle into a fact-checked research brief.

Given a :class:`ChosenAngle`, the agent asks the LLM for a summary, supporting
facts and sources. The LLM proposes; the code then applies a deterministic,
network-free fact-check: any claim without a source is downgraded to low
confidence and flagged as misinformation risk.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from src.agents.angle_strategist import ChosenAngle
from src.agents.base import Agent, AgentResult
from src.llm.client import LLMClient
from src.schema.blueprint import SourceRef

__all__ = ["Fact", "ResearchAgent", "ResearchBrief"]

SYSTEM_PROMPT = (
    "You are a meticulous research assistant for a YouTube video. Given a "
    "video angle, produce a concise, well-sourced research brief. Respond "
    "with JSON only, matching exactly this shape:\n"
    '{"summary": str, "facts": [{"text": str, "source": str, '
    '"confidence": "high" | "medium" | "low"}], '
    '"sources": [{"title": str, "url": str}]}\n'
    "Every factual claim must cite a source; omit any claim you cannot source."
)


class Fact(BaseModel):
    """A single supporting claim with an optional source and confidence."""

    text: str
    source: str | None = None
    confidence: Literal["high", "medium", "low"] = "low"


class ResearchBrief(BaseModel):
    """Output contract: the brief plus deterministic fact-check flags."""

    category: str
    angle_title: str
    summary: str
    facts: list[Fact] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    misinformation_flags: list[str] = Field(default_factory=list)


class ResearchAgent(Agent):
    """Turns a :class:`ChosenAngle` into a fact-checked :class:`ResearchBrief`."""

    name = "research"
    input_model = ChosenAngle
    output_model = ResearchBrief

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def _build_prompt(self, payload: ChosenAngle) -> str:
        angle = payload.chosen
        return "\n".join(
            [
                f"Category: {payload.category}",
                f"Angle title: {angle.title}",
                f"Hook: {angle.hook}",
                f"Why it is viral: {angle.why_viral}",
                "",
                "Research this angle: summarise it, list supporting facts with "
                "sources, and list the sources you used.",
            ]
        )

    def _parse_facts(self, raw: Any, notes: list[str]) -> list[Fact]:
        """Validate each proposed fact; drop unusable ones with a note."""
        facts: list[Fact] = []
        if not isinstance(raw, dict):
            return facts
        entries = raw.get("facts")
        if not isinstance(entries, list):
            return facts
        for index, entry in enumerate(entries):
            try:
                facts.append(Fact.model_validate(entry))
            except ValidationError as exc:
                notes.append(f"dropped invalid fact #{index}: {exc.error_count()} error(s)")
        return facts

    def _parse_sources(self, raw: Any, notes: list[str]) -> list[SourceRef]:
        """Validate each proposed source; drop unusable ones with a note."""
        sources: list[SourceRef] = []
        if not isinstance(raw, dict):
            return sources
        entries = raw.get("sources")
        if not isinstance(entries, list):
            return sources
        for index, entry in enumerate(entries):
            try:
                sources.append(SourceRef.model_validate(entry))
            except ValidationError as exc:
                notes.append(f"dropped invalid source #{index}: {exc.error_count()} error(s)")
        return sources

    @staticmethod
    def _factcheck(facts: list[Fact]) -> list[str]:
        """Downgrade and flag unsourced/low-trust claims (deterministic)."""
        flags: list[str] = []
        for fact in facts:
            unsourced = fact.source is None or not fact.source.strip()
            if unsourced:
                fact.confidence = "low"
                flag = f"unsourced claim: {fact.text}"
                if flag not in flags:
                    flags.append(flag)
        return flags

    def _run(self, payload: ChosenAngle) -> AgentResult:
        prompt = self._build_prompt(payload)
        try:
            raw = self._llm.complete_json(prompt, system=SYSTEM_PROMPT, temperature=0.2)
        except Exception as exc:  # a provider failure must not escape
            return AgentResult(status="fail", notes=[str(exc)])

        notes: list[str] = []
        facts = self._parse_facts(raw, notes)
        sources = self._parse_sources(raw, notes)
        if not facts:
            return AgentResult(status="fail", notes=[*notes, "no facts in LLM reply"])

        flags = self._factcheck(facts)
        summary = ""
        if isinstance(raw, dict) and isinstance(raw.get("summary"), str):
            summary = raw["summary"]

        if flags:
            notes.append(f"{len(flags)} unsourced claim(s) downgraded to low confidence")

        data = ResearchBrief(
            category=payload.category,
            angle_title=payload.chosen.title,
            summary=summary,
            facts=facts,
            sources=sources,
            misinformation_flags=flags,
        )
        notes.append(f"{len(facts)} fact(s), {len(sources)} source(s)")
        return AgentResult(status="ok", data=data, notes=notes)
