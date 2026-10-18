"""Text-to-speech backends and word/scene timing contracts.

The voice stage turns narration text into an audio file plus a word-level
timing map. That map is what later stages use to align visuals, captions and
scene cuts to the spoken words, so it is part of the data contract rather than
an implementation detail.

This module defines:

- :class:`WordTiming` / :class:`SceneTiming` / :class:`AudioTrack` — the JSON
  contract produced by the stage.
- :class:`TTSBackend` — the abstract provider interface.
- :class:`FakeTTSBackend` — a deterministic, dependency-free backend used by
  tests (no real audio, synthetic timings).
- :class:`EdgeTTSBackend` — the real backend. ``edge_tts`` is imported lazily
  inside :meth:`EdgeTTSBackend.synthesize` so importing this module never
  requires the optional dependency.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.errors import ProviderError

__all__ = [
    "AudioTrack",
    "EdgeTTSBackend",
    "FakeTTSBackend",
    "SceneTiming",
    "TTSBackend",
    "WordTiming",
]

#: edge-tts reports WordBoundary offsets/durations in 100-nanosecond ticks.
_TICKS_PER_SECOND = 1e7


class WordTiming(BaseModel):
    """A single spoken word with its start/end offset in seconds."""

    word: str
    start_sec: float
    end_sec: float


class SceneTiming(BaseModel):
    """The span of a scene within the synthesized narration."""

    index: int
    start_sec: float
    end_sec: float


class AudioTrack(BaseModel):
    """The synthesized narration plus its timing map."""

    path: str
    voice: str
    language: str
    duration_sec: float
    words: list[WordTiming] = Field(default_factory=list)
    scenes: list[SceneTiming] = Field(default_factory=list)


class TTSBackend(ABC):
    """Provider interface for text-to-speech synthesis."""

    @abstractmethod
    def synthesize(self, text: str, *, voice: str, out_path: Path) -> list[WordTiming]:
        """Synthesize ``text`` to ``out_path`` and return word timings."""
        raise NotImplementedError


class FakeTTSBackend(TTSBackend):
    """Deterministic, dependency-free backend for tests.

    It writes the narration as UTF-8 bytes to ``out_path`` (no real audio) and
    derives synthetic but well-formed word timings: each word lasts
    ``0.3 + 0.05 * len(word)`` seconds, laid out cumulatively so that words
    never overlap.
    """

    def synthesize(self, text: str, *, voice: str, out_path: Path) -> list[WordTiming]:
        timings: list[WordTiming] = []
        cursor = 0.0
        for word in text.split():
            duration = 0.3 + 0.05 * len(word)
            timings.append(WordTiming(word=word, start_sec=cursor, end_sec=cursor + duration))
            cursor += duration
        out_path.write_text(text, encoding="utf-8")
        return timings


class EdgeTTSBackend(TTSBackend):
    """Real backend backed by the optional ``edge-tts`` package.

    ``edge_tts`` is imported lazily so that neither importing this module nor
    constructing the backend requires the dependency. When it is missing,
    :meth:`synthesize` raises :class:`~src.errors.ProviderError`.
    """

    def synthesize(self, text: str, *, voice: str, out_path: Path) -> list[WordTiming]:
        try:
            import edge_tts
        except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
            raise ProviderError("edge-tts not installed") from exc

        return asyncio.run(self._synthesize(edge_tts, text, voice=voice, out_path=out_path))

    @staticmethod
    async def _synthesize(
        edge_tts: Any, text: str, *, voice: str, out_path: Path
    ) -> list[WordTiming]:
        communicate = edge_tts.Communicate(text, voice)
        audio = bytearray()
        timings: list[WordTiming] = []
        async for chunk in communicate.stream():
            chunk_type = chunk.get("type")
            if chunk_type == "audio":
                audio.extend(chunk["data"])
            elif chunk_type == "WordBoundary":
                start = chunk["offset"] / _TICKS_PER_SECOND
                end = (chunk["offset"] + chunk["duration"]) / _TICKS_PER_SECOND
                timings.append(WordTiming(word=chunk["text"], start_sec=start, end_sec=end))
        out_path.write_bytes(bytes(audio))
        return timings
