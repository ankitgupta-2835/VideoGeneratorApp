"""``seo`` agent: generate publish metadata (title/description/tags/thumbnail).

Given a finished :class:`~src.schema.blueprint.Blueprint` (plus optional
chapter markers and extra keywords), the agent asks the LLM for a title, a
description, a tag list and a thumbnail prompt.

The LLM only *proposes*: the agent enforces the platform limits in code so the
result is always publishable — the title is clipped to 100 characters on a word
boundary, tags are cleaned and trimmed so the comma-joined list is at most 500
characters (keeping at least one), and, when chapters are supplied, a
``Chapters`` section is appended to the description in ``M:SS Label`` form.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.agents.base import Agent, AgentResult
from src.llm.client import LLMClient
from src.schema.blueprint import Blueprint

__all__ = ["Chapter", "PublishMetadata", "SeoAgent", "SeoInput"]

#: Maximum characters allowed in a YouTube title.
TITLE_MAX = 100

#: Maximum characters allowed in the comma-joined tag list.
TAGS_MAX = 500

SYSTEM_PROMPT = (
    "You are a YouTube SEO specialist. Given a finished video blueprint, "
    "produce publish metadata that maximizes clicks and discoverability. "
    "Respond with JSON only, matching exactly this shape:\n"
    '{"title": str, "description": str, "tags": [str], '
    '"thumbnail_prompt": str}\n'
    "The title must be compelling and at most 100 characters. The description "
    "should summarize the video and invite engagement. Tags are short keyword "
    "phrases. The thumbnail_prompt is a vivid, visual description for an image "
    "generator. Do not include commentary, markdown or code fences."
)


class Chapter(BaseModel):
    """A single chapter marker in the video timeline."""

    start_sec: float
    label: str


class SeoInput(BaseModel):
    """Input contract for the ``seo`` agent."""

    blueprint: Blueprint
    chapters: list[Chapter] = Field(default_factory=list)
    extra_keywords: list[str] = Field(default_factory=list)


class PublishMetadata(BaseModel):
    """Output contract: publish-ready metadata for the video platform."""

    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    thumbnail_prompt: str = ""
    language: str = "en"


def _trim_title(title: str) -> str:
    """Clip ``title`` to :data:`TITLE_MAX`, preferring a word boundary."""
    title = title.strip()
    if len(title) <= TITLE_MAX:
        return title
    clipped = title[:TITLE_MAX]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    clipped = clipped.strip()
    return clipped or title[:TITLE_MAX].strip()


def _clean_tags(raw_tags: Any) -> list[str]:
    """Strip blanks, drop duplicates (case-insensitive), and cap the join."""
    if not isinstance(raw_tags, list):
        return []

    seen: set[str] = set()
    cleaned: list[str] = []
    for entry in raw_tags:
        if not isinstance(entry, str):
            continue
        tag = entry.strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(tag)

    result: list[str] = []
    total = 0
    for tag in cleaned:
        projected = total + len(tag) + (1 if result else 0)  # comma separator
        if projected > TAGS_MAX:
            break
        result.append(tag)
        total = projected
    if not result and cleaned:  # a single over-long tag: keep one, clipped
        result = [cleaned[0][:TAGS_MAX]]
    return result


def _format_timestamp(start_sec: float) -> str:
    """Format ``start_sec`` as ``M:SS`` (e.g. ``90`` -> ``1:30``)."""
    total = int(start_sec)
    return f"{total // 60}:{total % 60:02d}"


class SeoAgent(Agent):
    """LLM-backed generator of publish metadata with code-enforced limits."""

    name = "seo"
    input_model = SeoInput
    output_model = PublishMetadata

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def _build_prompt(self, payload: SeoInput) -> str:
        meta = payload.blueprint.meta
        lines = [
            "Write publish metadata for this video.",
            f"Title: {meta.title}",
            f"Category: {meta.category}",
            f"Language: {meta.language}",
        ]
        if meta.angle:
            lines.append(f"Angle: {meta.angle}")
        if meta.audience:
            lines.append(f"Audience: {meta.audience}")
        if payload.extra_keywords:
            lines.append("Keywords to include:")
            lines.extend(f"- {keyword}" for keyword in payload.extra_keywords)
        lines.append("Return JSON with title, description, tags and thumbnail_prompt.")
        return "\n".join(lines)

    @staticmethod
    def _append_chapters(description: str, chapters: list[Chapter]) -> str:
        """Append a ``Chapters`` section built from ``chapters`` (in order)."""
        if not chapters:
            return description
        lines = [f"{_format_timestamp(ch.start_sec)} {ch.label}" for ch in chapters]
        block = "Chapters:\n" + "\n".join(lines)
        base = description.rstrip()
        return f"{base}\n\n{block}" if base else block

    def _run(self, payload: SeoInput) -> AgentResult:
        prompt = self._build_prompt(payload)
        try:
            raw = self._llm.complete_json(prompt, system=SYSTEM_PROMPT)
        except Exception as exc:  # a provider failure must not escape
            return AgentResult(status="fail", notes=[str(exc)])

        if not isinstance(raw, dict):
            return AgentResult(status="fail", notes=["LLM reply was not a JSON object"])

        raw_title = raw.get("title")
        if not isinstance(raw_title, str) or not raw_title.strip():
            return AgentResult(status="fail", notes=["LLM reply had no usable title"])

        title = _trim_title(raw_title)
        raw_description = raw.get("description")
        description = raw_description if isinstance(raw_description, str) else ""
        description = self._append_chapters(description, payload.chapters)

        tags = _clean_tags(raw.get("tags"))

        raw_thumbnail = raw.get("thumbnail_prompt")
        thumbnail_prompt = raw_thumbnail.strip() if isinstance(raw_thumbnail, str) else ""
        if not thumbnail_prompt:
            thumbnail_prompt = f"YouTube thumbnail for: {title}"

        data = PublishMetadata(
            title=title,
            description=description,
            tags=tags,
            thumbnail_prompt=thumbnail_prompt,
            language=payload.blueprint.meta.language,
        )
        notes = [f"{len(title)}-char title, {len(tags)} tag(s)"]
        return AgentResult(status="ok", data=data, notes=notes)
