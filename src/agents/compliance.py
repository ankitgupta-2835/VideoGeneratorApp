"""``compliance`` gate: YouTube policy, copyright and monetization safety.

A deterministic, network-free gate that scans a :class:`Blueprint`, its
on-screen text, and the media-asset prompts/sources for policy hazards. It
emits a :class:`ComplianceReport` and signals ``rework`` whenever a *blocking*
flag is present so the narrative stage can revise the offending scene.

Categories and their intent:

- ``medical`` / ``financial`` — banned claims that also forfeit monetization.
- ``copyright`` — an asset source outside the approved allow-list.
- ``superlative`` — unverifiable ("100%") marketing language (monetization
  edge risk, non-blocking).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.agents.base import Agent, AgentResult
from src.schema.blueprint import Blueprint

__all__ = [
    "ALLOWED_ASSET_SOURCES",
    "BANNED_CLAIMS",
    "SUPERLATIVE_CLAIMS",
    "ComplianceAgent",
    "ComplianceFlag",
    "ComplianceInput",
    "ComplianceReport",
]

#: Banned claim phrases keyed by category. Presence in narration, on-screen
#: text or an asset prompt is a blocking violation.
BANNED_CLAIMS: dict[str, set[str]] = {
    "medical": {"cure", "guaranteed cure", "miracle", "lose weight fast", "detox"},
    "financial": {"guaranteed returns", "get rich", "risk-free", "guaranteed profit"},
}

#: Asset sources cleared for use (stock/generative providers with safe terms).
ALLOWED_ASSET_SOURCES: set[str] = {
    "pexels",
    "pixabay",
    "pollinations",
    "stablehorde",
    "stable-horde",
    "luma",
    "pika",
    "pixverse",
}

#: Unverifiable marketing phrases that are a monetization edge risk (non-blocking).
SUPERLATIVE_CLAIMS: set[str] = {"best in the world", "number one", "100%"}

#: Categories that forfeit monetization safety even when they only warn.
_MONETIZATION_RISK_CATEGORIES = {"medical", "financial"}


class ComplianceFlag(BaseModel):
    """A single compliance finding."""

    severity: Literal["info", "warn", "block"]
    category: str
    message: str
    scene_index: int | None = None


class ComplianceReport(BaseModel):
    """Output contract: the gate's verdict and the flags that drove it."""

    passed: bool
    monetization_safe: bool
    flags: list[ComplianceFlag] = Field(default_factory=list)
    summary: str = ""


class ComplianceInput(BaseModel):
    """Input contract: the blueprint plus the media assets already planned."""

    blueprint: Blueprint
    asset_prompts: list[str] = Field(default_factory=list)
    asset_sources: list[str] = Field(default_factory=list)


class ComplianceAgent(Agent):
    """Deterministic YouTube-policy / copyright / monetization gate."""

    name = "compliance"
    input_model = ComplianceInput
    output_model = ComplianceReport

    def _run(self, payload: ComplianceInput) -> AgentResult:
        flags: list[ComplianceFlag] = []

        for scene in payload.blueprint.scenes:
            self._scan_text(scene.narration, scene.index, flags)
            if scene.on_screen_text is not None:
                self._scan_text(scene.on_screen_text, scene.index, flags)
            self._scan_superlatives(scene.narration, scene.index, flags)

        for prompt in payload.asset_prompts:
            self._scan_text(prompt, None, flags)

        for source in payload.asset_sources:
            if source.lower() not in ALLOWED_ASSET_SOURCES:
                flags.append(
                    ComplianceFlag(
                        severity="warn",
                        category="copyright",
                        message=f"asset source {source!r} is not on the approved list",
                        scene_index=None,
                    )
                )

        passed = not any(flag.severity == "block" for flag in flags)
        monetization_safe = passed and not any(
            flag.category in _MONETIZATION_RISK_CATEGORIES for flag in flags
        )
        report = ComplianceReport(
            passed=passed,
            monetization_safe=monetization_safe,
            flags=flags,
            summary=_summarize(flags),
        )
        notes = [f"{flag.severity}: {flag.message}" for flag in flags]
        status: Literal["ok", "rework"] = "ok" if passed else "rework"
        return AgentResult(status=status, data=report, notes=notes)

    @staticmethod
    def _scan_text(text: str, scene_index: int | None, flags: list[ComplianceFlag]) -> None:
        lowered = text.lower()
        for category in sorted(BANNED_CLAIMS):
            for phrase in sorted(BANNED_CLAIMS[category]):
                if phrase in lowered:
                    where = f"scene {scene_index}" if scene_index is not None else "asset prompt"
                    flags.append(
                        ComplianceFlag(
                            severity="block",
                            category=category,
                            message=f"banned {category} claim {phrase!r} in {where}",
                            scene_index=scene_index,
                        )
                    )

    @staticmethod
    def _scan_superlatives(text: str, scene_index: int | None, flags: list[ComplianceFlag]) -> None:
        lowered = text.lower()
        for phrase in sorted(SUPERLATIVE_CLAIMS):
            if phrase in lowered:
                where = f"scene {scene_index}" if scene_index is not None else "asset prompt"
                flags.append(
                    ComplianceFlag(
                        severity="warn",
                        category="superlative",
                        message=f"unverifiable superlative {phrase!r} in {where}",
                        scene_index=scene_index,
                    )
                )


def _summarize(flags: list[ComplianceFlag]) -> str:
    """Return a short human sentence describing the findings."""
    total = len(flags)
    if total == 0:
        return "No compliance issues."
    blocks = sum(1 for flag in flags if flag.severity == "block")
    warns = sum(1 for flag in flags if flag.severity == "warn")
    return f"{total} issues: {blocks} block, {warns} warn"
