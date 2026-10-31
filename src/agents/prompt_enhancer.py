"""Write a detailed, generation-ready prompt for one scene's visual.

The visual director uses a scene's ``visual.prompt`` / ``description`` /
``narration`` as-is. When that prompt cannot produce an image (provider error,
rate limit, empty cache miss), the repair pass asks this agent to write a much
more concrete prompt and tries again.

The agent never fails: if the LLM is unavailable or returns something invalid,
it falls back to a deterministic prompt built from the narration, so the repair
pass always has something to send to the image provider.
"""

from __future__ import annotations

from pydantic import BaseModel

from src.agents.base import Agent, AgentResult
from src.llm.client import LLMClient

__all__ = [
    "EnhancedPrompt",
    "PromptEnhanceInput",
    "PromptEnhancerAgent",
    "fallback_prompt",
]

SYSTEM_PROMPT = (
    "You write image-generation prompts for cinematic video B-roll. "
    'Return ONLY a JSON object: {"prompt": "<one detailed prompt>"}. '
    "Describe one concrete scene: the main subject and action, the setting, "
    "lighting, camera angle and lens, color palette, and mood. "
    "Make it photorealistic and visually specific. "
    "Use a wide 16:9 composition. "
    "Do not ask for text, captions, logos, watermarks, UI, or celebrity likeness."
)


class PromptEnhanceInput(BaseModel):
    """Input contract: the scene and the video it belongs to."""

    title: str
    category: str = "general"
    narration: str
    on_screen_text: str | None = None


class EnhancedPrompt(BaseModel):
    """Output contract: a prompt the image provider can consume."""

    prompt: str


def fallback_prompt(payload: PromptEnhanceInput) -> str:
    """A deterministic, reasonably detailed prompt when the LLM is unavailable."""
    subject = " ".join(payload.narration.split())[:400]
    return (
        f"Cinematic editorial photograph for a {payload.category} explainer "
        f'titled "{payload.title}". Scene: {subject}. '
        "Wide 16:9 composition, natural directional lighting, shallow depth of "
        "field, realistic textures, high detail, calm documentary mood. "
        "No text, no captions, no logos, no watermarks."
    )


class PromptEnhancerAgent(Agent):
    """LLM-backed prompt rewriter with a deterministic fallback."""

    name = "prompt_enhancer"
    input_model = PromptEnhanceInput
    output_model = EnhancedPrompt

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def _build_prompt(self, payload: PromptEnhanceInput) -> str:
        lines = [
            "Write an image-generation prompt for this video scene.",
            f"Video title: {payload.title}",
            f"Category: {payload.category}",
            f"Narration: {payload.narration}",
        ]
        if payload.on_screen_text:
            lines.append(
                f"On-screen text (do not render it in the image): {payload.on_screen_text}"
            )
        return "\n".join(lines)

    def _run(self, payload: PromptEnhanceInput) -> AgentResult:
        try:
            raw = self._llm.complete_json(self._build_prompt(payload), system=SYSTEM_PROMPT)
            prompt = str(raw.get("prompt", "")).strip() if isinstance(raw, dict) else ""
        except Exception as exc:  # noqa: BLE001 - the repair pass must still work
            return AgentResult(
                status="ok",
                data=EnhancedPrompt(prompt=fallback_prompt(payload)),
                notes=[f"prompt enhancement failed ({exc}); using deterministic prompt"],
            )
        if not prompt:
            return AgentResult(
                status="ok",
                data=EnhancedPrompt(prompt=fallback_prompt(payload)),
                notes=["prompt enhancement returned no prompt; using deterministic prompt"],
            )
        return AgentResult(status="ok", data=EnhancedPrompt(prompt=prompt))
