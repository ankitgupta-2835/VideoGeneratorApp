"""``localizer`` agent: adapt an English blueprint into Hindi.

The localizer takes the English master :class:`~src.schema.blueprint.Blueprint`
and asks the LLM to *adapt* — not literally translate — the title, each
scene's narration, and each scene's on-screen text into Hindi. Structure and
timing are preserved exactly: every scene keeps its original ``index``,
``duration_sec``, ``hero`` flag, and ``visual`` spec, and the new meta keeps
the original ``category``, ``target_duration_sec``, ``angle``, ``audience``,
and ``sources`` while switching ``language`` to ``"hi"``.

A reply that translates only some scenes is still a success: the missing
scenes keep their English narration and a per-scene note flags them. Only an
LLM failure, a malformed reply, or a reply with no usable scenes is a hard
``fail``.
"""

from __future__ import annotations

from typing import Any

from src.agents.base import Agent, AgentResult
from src.llm.client import LLMClient
from src.schema.blueprint import Blueprint, Meta, Scene

__all__ = ["LocalizerAgent"]


SYSTEM_PROMPT = (
    "You are a Hindi localization editor for short-form explainer videos. "
    "Adapt the given English video script into natural, idiomatic Hindi — "
    "localize idioms and phrasing for a Hindi-speaking audience rather than "
    "translating word for word, while keeping the meaning and tone intact. "
    "Do NOT change the structure: translate only the title, each scene's "
    "narration, and each scene's on-screen text. "
    "Return ONLY a single JSON object of the form "
    '{"title": <string>, "scenes": [{"index": <int>, "narration": <string>, '
    '"on_screen_text": <string or null>}]} — one entry for every input scene, '
    "using the same index values as the input. "
    "Use Devanagari script. Do not include commentary, markdown, or code fences."
)


class LocalizerAgent(Agent):
    """LLM-backed adapter of an English blueprint into Hindi."""

    name = "localizer"
    input_model = Blueprint
    output_model = Blueprint

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def _build_prompt(self, payload: Blueprint) -> str:
        lines = [
            "Adapt this video script into Hindi.",
            f"Title: {payload.meta.title}",
            "Scenes:",
        ]
        for scene in payload.scenes:
            lines.append(f"- index: {scene.index}")
            lines.append(f"  narration: {scene.narration}")
            lines.append(f"  on_screen_text: {scene.on_screen_text}")
        lines.append(
            "Return JSON with the localized title and a scenes list, one entry "
            "per input scene, keeping the same index values."
        )
        return "\n".join(lines)

    def _run(self, payload: Blueprint) -> AgentResult:
        prompt = self._build_prompt(payload)
        try:
            raw = self._llm.complete_json(prompt, system=SYSTEM_PROMPT)
        except Exception as exc:  # an LLM/provider failure is a hard fail
            return AgentResult(status="fail", notes=[str(exc)])

        if not isinstance(raw, dict):
            return AgentResult(status="fail", notes=["reply is not a JSON object"])

        translated_scenes = raw.get("scenes")
        if not isinstance(translated_scenes, list) or not translated_scenes:
            return AgentResult(status="fail", notes=["reply has no usable scenes"])

        by_index: dict[Any, dict[str, Any]] = {}
        for item in translated_scenes:
            if isinstance(item, dict) and "index" in item:
                by_index[item["index"]] = item

        notes: list[str] = []
        scenes: list[Scene] = []
        for original in payload.scenes:
            entry = by_index.get(original.index)
            narration = original.narration
            on_screen_text = original.on_screen_text
            if entry is None:
                notes.append(f"scene {original.index} not translated; kept English")
            else:
                translated_narration = entry.get("narration")
                if isinstance(translated_narration, str) and translated_narration:
                    narration = translated_narration
                else:
                    notes.append(f"scene {original.index} not translated; kept English")
                translated_ost = entry.get("on_screen_text")
                if isinstance(translated_ost, str):
                    on_screen_text = translated_ost
                elif translated_ost is None:
                    on_screen_text = None
            scenes.append(
                Scene(
                    index=original.index,
                    narration=narration,
                    on_screen_text=on_screen_text,
                    visual=original.visual,
                    duration_sec=original.duration_sec,
                    hero=original.hero,
                )
            )

        translated_title = raw.get("title")
        title = (
            translated_title
            if isinstance(translated_title, str) and translated_title
            else payload.meta.title
        )
        meta = Meta(
            title=title,
            category=payload.meta.category,
            language="hi",
            target_duration_sec=payload.meta.target_duration_sec,
            angle=payload.meta.angle,
            audience=payload.meta.audience,
            sources=payload.meta.sources,
        )
        blueprint = Blueprint(meta=meta, scenes=scenes)
        return AgentResult(status="ok", data=blueprint, notes=notes)
