"""``qa_critic`` agent: technical + LLM quality score and pass/fail gate.

This is the **quality gate** that closes the render loop. It runs the
deterministic technical checks from :mod:`src.qa.checks`
(:func:`~src.qa.checks.run_checks`), converts them into a 0-100 score with a
documented penalty formula, optionally asks an LLM for a short subjective
critique plus a bounded score adjustment, and produces a :class:`QaReport` with
a ``passed`` verdict.

Design guarantees:

- **Deterministic core.** The technical score depends only on the
  :class:`~src.qa.checks.QaChecks` record, so it is reproducible and
  unit-testable without ffmpeg (inject a ``checks_runner``).
- **Bounded LLM.** The LLM's ``adjustment`` is clamped to ``[-10, 10]`` and the
  final score to ``[0, 100]``. A missing/failing/malformed LLM reply is noted
  and tolerated — the agent never crashes on it.
- **Hard technical gate.** ``passed`` is ``False`` whenever there is *any*
  technical issue, regardless of how high the score is.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from src.agents.base import Agent, AgentResult
from src.llm.client import LLMClient
from src.qa.checks import QaChecks, run_checks
from src.schema.blueprint import Blueprint

__all__ = [
    "BLACK_FRAME_PENALTY",
    "BLACK_FRAME_TOTAL_MAX_SEC",
    "ISSUE_PENALTY",
    "LLM_ADJUSTMENT_MAX",
    "LLM_ADJUSTMENT_MIN",
    "SILENCE_PENALTY",
    "SILENCE_TOTAL_MAX_SEC",
    "QaCriticAgent",
    "QaInput",
    "QaReport",
    "score_from_checks",
]

#: Points removed from the technical score for each entry in ``checks.issues``.
ISSUE_PENALTY = 15.0
#: Total black-frame seconds above which the extra black penalty applies.
BLACK_FRAME_TOTAL_MAX_SEC = 2.0
#: Extra points removed when total black-frame seconds exceed the max.
BLACK_FRAME_PENALTY = 10.0
#: Total silence seconds above which the extra silence penalty applies.
SILENCE_TOTAL_MAX_SEC = 5.0
#: Extra points removed when total silence seconds exceed the max.
SILENCE_PENALTY = 10.0
#: Inclusive bounds for the LLM's subjective score adjustment.
LLM_ADJUSTMENT_MIN = -10.0
LLM_ADJUSTMENT_MAX = 10.0

SYSTEM_PROMPT = (
    "You are a strict but fair video quality critic. You are given a list of "
    "technical issues found in a rendered video and a blueprint summary. "
    "Return ONLY a single JSON object with two keys: "
    '"critiques" (a short list of specific, actionable strings) and '
    '"adjustment" (a number between -10 and 10 to add to the technical score; '
    "negative for flaws the technical checks miss, positive only when the video "
    "clearly exceeds expectations). Do not include commentary, markdown, or "
    "code fences."
)


class QaInput(BaseModel):
    """Input contract for the QA critic."""

    blueprint: Blueprint
    video_path: Path
    min_score: float = 70.0


class QaReport(BaseModel):
    """Output contract: the gate's verdict and the reasoning behind it."""

    score: float  # 0..100
    passed: bool
    technical_issues: list[str] = Field(default_factory=list)
    critiques: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def score_from_checks(checks: QaChecks) -> tuple[float, list[str]]:
    """Score ``checks`` deterministically and return ``(score, issues)``.

    The exact formula, starting from a perfect ``100.0``:

    1. Subtract :data:`ISSUE_PENALTY` (15) for **each** string in
       ``checks.issues``.
    2. Subtract :data:`BLACK_FRAME_PENALTY` (10) when the summed black-frame
       duration exceeds :data:`BLACK_FRAME_TOTAL_MAX_SEC` (2.0s).
    3. Subtract :data:`SILENCE_PENALTY` (10) when the summed silence duration
       exceeds :data:`SILENCE_TOTAL_MAX_SEC` (5.0s).
    4. Clamp the result to ``[0.0, 100.0]``.

    The second element is the list of issue strings that drove the penalty, so
    the caller can surface them without re-reading ``checks``.
    """
    score = 100.0
    score -= ISSUE_PENALTY * len(checks.issues)

    black_total = sum(frame.end_sec - frame.start_sec for frame in checks.black_frames)
    if black_total > BLACK_FRAME_TOTAL_MAX_SEC:
        score -= BLACK_FRAME_PENALTY

    silence_total = sum(silence.end_sec - silence.start_sec for silence in checks.silences)
    if silence_total > SILENCE_TOTAL_MAX_SEC:
        score -= SILENCE_PENALTY

    score = max(0.0, min(100.0, score))
    return score, list(checks.issues)


class QaCriticAgent(Agent):
    """Technical-plus-subjective quality gate over a rendered video."""

    name = "qa_critic"
    input_model = QaInput
    output_model = QaReport

    def __init__(
        self,
        *,
        checks_runner: Callable[[Path], QaChecks] = run_checks,
        llm: LLMClient | None = None,
    ) -> None:
        self._checks_runner = checks_runner
        self._llm = llm

    def _build_prompt(self, payload: QaInput, checks: QaChecks) -> str:
        lines = [
            "Critique this rendered video.",
            f"Title: {payload.blueprint.meta.title}",
            f"Category: {payload.blueprint.meta.category}",
            f"Language: {payload.blueprint.meta.language}",
            f"Scenes: {len(payload.blueprint.scenes)}",
            f"Duration (seconds): {checks.duration_sec:.3f}",
            f"A/V desync (seconds): {checks.av_desync_sec:.3f}",
        ]
        if checks.issues:
            lines.append("Technical issues:")
            lines.extend(f"- {issue}" for issue in checks.issues)
        else:
            lines.append("Technical issues: none")
        return "\n".join(lines)

    def _llm_adjustment(
        self, payload: QaInput, checks: QaChecks
    ) -> tuple[float, list[str], str | None]:
        """Ask the LLM for a critique and a bounded adjustment.

        Returns ``(adjustment, critiques, note)``. ``note`` is ``None`` on a
        clean reply, otherwise a human-readable message explaining why the
        adjustment fell back to ``0.0``. This method never raises.
        """
        assert self._llm is not None
        prompt = self._build_prompt(payload, checks)
        try:
            raw = self._llm.complete_json(prompt, system=SYSTEM_PROMPT)
        except Exception as exc:  # an LLM failure must not crash the gate
            return 0.0, [], f"LLM critique unavailable: {exc}"

        if not isinstance(raw, dict):
            return 0.0, [], "LLM critique malformed: expected a JSON object"

        raw_critiques = raw.get("critiques", [])
        if isinstance(raw_critiques, list):
            critiques = [str(item) for item in raw_critiques]
        else:
            critiques = []

        try:
            adjustment = float(raw.get("adjustment", 0.0))
        except (TypeError, ValueError):
            return 0.0, critiques, "LLM adjustment malformed; using technical score only"
        if not math.isfinite(adjustment):
            return 0.0, critiques, "LLM adjustment malformed; using technical score only"

        bounded = max(LLM_ADJUSTMENT_MIN, min(LLM_ADJUSTMENT_MAX, adjustment))
        return bounded, critiques, None

    def _run(self, payload: QaInput) -> AgentResult:
        try:
            checks = self._checks_runner(payload.video_path)
        except Exception as exc:  # a failing checks runner is a hard fail
            return AgentResult(status="fail", notes=[f"QA checks failed: {exc}"])

        score, technical_issues = score_from_checks(checks)

        critiques: list[str] = []
        notes: list[str] = []
        if self._llm is not None:
            adjustment, critiques, note = self._llm_adjustment(payload, checks)
            score = max(0.0, min(100.0, score + adjustment))
            if note is not None:
                notes.append(note)

        passed = score >= payload.min_score and not checks.issues
        report = QaReport(
            score=score,
            passed=passed,
            technical_issues=technical_issues,
            critiques=critiques,
            notes=list(notes),
        )
        return AgentResult(status="ok", data=report, notes=notes)
