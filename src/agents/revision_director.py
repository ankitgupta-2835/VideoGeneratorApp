"""``revision_director`` agent: feedback -> targeted revision plan + escalation.

When a render fails QA or a human reviewer rejects it, something has to turn
that free-text feedback into an *actionable* revision: which pipeline stages to
replay, what to change, and how many times we are willing to retry before
abandoning the topic entirely. This agent owns that policy.

It deliberately splits the problem in two:

- **Stage selection is delegated** to the deterministic rerun controller
  (:mod:`src.rerun.controller`). This agent builds a
  :class:`~src.rerun.controller.RerunRequest` from its input, calls
  :func:`~src.rerun.controller.plan_rerun`, and copies the resulting
  ``stages_to_run`` / ``stages_reused`` / ``scene_indices`` / ``attempt_no``
  into its own :class:`RevisionPlan`. There is exactly one source of truth for
  "what does a scope replay" and this agent is not it.
- **Instruction authoring is optional-LLM.** If an :class:`LLMClient` is
  supplied the agent asks it for short, actionable revision steps derived from
  the ``reason``/``feedback`` and any QA ``technical_issues``/``critiques``. A
  missing, failing, or malformed reply is *tolerated*: the agent falls back to
  deterministic instructions and records a note explaining the fallback. With
  no LLM at all it simply uses the deterministic instructions.

Escalation ladder (:func:`escalation_for`), 1-based attempt numbers:

* attempt ``1`` -> ``"retry"`` (just replay the targeted stages),
* attempt ``2 .. max_attempts-1`` -> ``"adjust"`` (tighten the approach),
* attempt ``>= max_attempts`` -> ``"new_topic"`` (the topic itself is the
  problem; start over).

Planning is an advisory step: it never *fails* a pipeline, so ``_run`` returns
``status="ok"`` unless the underlying planner itself raises.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.agents.base import Agent, AgentResult
from src.agents.qa_critic import QaReport
from src.llm.client import LLMClient
from src.rerun.controller import RerunPlan, RerunRequest, Scope, plan_rerun

__all__ = [
    "SYSTEM_PROMPT",
    "RevisionDirectorAgent",
    "RevisionInput",
    "RevisionPlan",
    "escalation_for",
]

SYSTEM_PROMPT = (
    "You are a revision director for an automated video pipeline. You are given "
    "why a run is being re-done and the quality problems found. Return ONLY a "
    'single JSON object with one key: "instructions", a short list of specific, '
    "actionable revision steps (imperative, one sentence each). Order them so the "
    "most impactful fix comes first. Do not include commentary, markdown, or code "
    "fences."
)


class RevisionInput(BaseModel):
    """Input contract for the revision director."""

    run_id: str
    scope: Scope
    reason: str = ""
    feedback: str = ""
    scene_indices: list[int] = Field(default_factory=list)
    qa_report: QaReport | None = None
    previous_attempts: int = 0
    max_attempts: int = 3


class RevisionPlan(BaseModel):
    """Output contract: targeted stages, instructions, and the escalation rung."""

    run_id: str
    scope: Scope
    attempt_no: int
    stages_to_run: list[str] = Field(default_factory=list)
    stages_reused: list[str] = Field(default_factory=list)
    scene_indices: list[int] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    escalation: str = "retry"  # retry | adjust | new_topic
    notes: list[str] = Field(default_factory=list)


def escalation_for(attempt_no: int, *, max_attempts: int = 3) -> str:
    """Return the escalation rung for a 1-based ``attempt_no``.

    The ladder is deliberately simple and monotone: the *first* attempt always
    just retries the targeted stages; middle attempts ``2 .. max_attempts-1``
    move to ``"adjust"`` (change the approach); once we reach the last allowed
    attempt (``attempt_no >= max_attempts``) the topic itself is suspect and we
    escalate to ``"new_topic"``.
    """
    if attempt_no <= 1:
        return "retry"
    if attempt_no < max_attempts:
        return "adjust"
    return "new_topic"


class RevisionDirectorAgent(Agent):
    """Turn reviewer/QA feedback into a targeted, escalated revision plan."""

    name = "revision_director"
    input_model = RevisionInput
    output_model = RevisionPlan

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    # -- instructions -------------------------------------------------------

    def _build_prompt(self, payload: RevisionInput, plan: RerunPlan) -> str:
        """Build the instruction-authoring prompt, including the feedback text."""
        lines = [
            "Plan the revision of a video run.",
            f"Run: {payload.run_id}",
            f"Scope: {payload.scope.value}",
            f"Attempt number: {plan.attempt_no}",
            f"Stages to replay: {', '.join(s.value for s in plan.stages_to_run)}",
        ]
        if payload.scene_indices:
            lines.append(f"Scene indices: {payload.scene_indices}")
        lines.append(f"Reason: {payload.reason or '(none given)'}")
        lines.append(f"Feedback: {payload.feedback or '(none given)'}")
        if payload.qa_report is not None:
            if payload.qa_report.technical_issues:
                lines.append("Technical issues:")
                lines.extend(f"- {issue}" for issue in payload.qa_report.technical_issues)
            if payload.qa_report.critiques:
                lines.append("Critiques:")
                lines.extend(f"- {critique}" for critique in payload.qa_report.critiques)
        return "\n".join(lines)

    def _deterministic_instructions(self, payload: RevisionInput, plan: RerunPlan) -> list[str]:
        """Derive actionable steps without an LLM (also the LLM fallback)."""
        stages = ", ".join(stage.value for stage in plan.stages_to_run)
        instructions = [f"Re-run the {payload.scope.value} scope stages: {stages}."]
        if payload.reason:
            instructions.append(f"Address the reason for revision: {payload.reason}.")
        if payload.feedback:
            instructions.append(f"Address the reviewer feedback: {payload.feedback}.")
        if payload.qa_report is not None:
            for issue in payload.qa_report.technical_issues:
                instructions.append(f"Fix technical issue: {issue}.")
            for critique in payload.qa_report.critiques:
                instructions.append(f"Address critique: {critique}.")
        return instructions

    def _llm_instructions(
        self, payload: RevisionInput, plan: RerunPlan
    ) -> tuple[list[str], str | None]:
        """Ask the LLM for instructions.

        Returns ``(instructions, note)``. ``note`` is ``None`` on a clean reply,
        otherwise a human-readable explanation of why the deterministic
        instructions were used instead. This method never raises.
        """
        assert self._llm is not None
        prompt = self._build_prompt(payload, plan)
        try:
            raw = self._llm.complete_json(prompt, system=SYSTEM_PROMPT)
        except Exception as exc:  # an LLM failure must not crash planning
            return [], f"LLM instructions unavailable: {exc}"

        if not isinstance(raw, dict):
            return [], "LLM instructions malformed: expected a JSON object"

        raw_instructions = raw.get("instructions")
        if not isinstance(raw_instructions, list) or not raw_instructions:
            return [], "LLM instructions malformed: missing non-empty 'instructions' list"

        instructions = [str(item) for item in raw_instructions if str(item).strip()]
        if not instructions:
            return [], "LLM instructions malformed: empty 'instructions' entries"
        return instructions, None

    # -- agent --------------------------------------------------------------

    def _run(self, payload: RevisionInput) -> AgentResult:
        request = RerunRequest(
            run_id=payload.run_id,
            scope=payload.scope,
            reason=payload.reason,
            scene_indices=payload.scene_indices,
            feedback=payload.feedback,
        )
        try:
            plan = plan_rerun(request, previous_attempts=payload.previous_attempts)
        except Exception as exc:  # a failing planner is the only hard failure
            return AgentResult(status="fail", notes=[f"revision planning failed: {exc}"])

        notes: list[str] = list(plan.notes)
        if self._llm is not None:
            instructions, note = self._llm_instructions(payload, plan)
            if note is not None:
                notes.append(note)
                notes.append("used deterministic instructions as fallback")
            if not instructions:
                instructions = self._deterministic_instructions(payload, plan)
        else:
            instructions = self._deterministic_instructions(payload, plan)

        escalation = escalation_for(plan.attempt_no, max_attempts=payload.max_attempts)
        if escalation == "new_topic":
            notes.append(
                f"attempt {plan.attempt_no} reached max_attempts="
                f"{payload.max_attempts}; a fresh topic is advised"
            )

        revision = RevisionPlan(
            run_id=plan.run_id,
            scope=plan.scope,
            attempt_no=plan.attempt_no,
            stages_to_run=[stage.value for stage in plan.stages_to_run],
            stages_reused=[stage.value for stage in plan.stages_reused],
            scene_indices=list(plan.scene_indices),
            instructions=instructions,
            escalation=escalation,
            notes=notes,
        )
        return AgentResult(status="ok", data=revision, notes=notes)
