"""``voice_director`` agent: synthesize a blueprint's narration.

The director concatenates every scene's narration, in scene order, into one
utterance and hands it to a :class:`~src.audio.tts.TTSBackend`. The backend
returns word-level timings, which the director folds into an
:class:`~src.audio.tts.AudioTrack`: a per-scene partition derived from each
scene's word count, so downstream stages can align visuals and cuts to the
spoken words.

A backend failure is surfaced as a ``fail`` result (the message is carried in
``notes``) rather than escaping, keeping the pipeline's bounded-failure
contract.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from src.agents.base import Agent, AgentResult
from src.audio.tts import AudioTrack, SceneTiming, TTSBackend, WordTiming
from src.errors import ProviderError
from src.schema.blueprint import Blueprint, Scene

__all__ = ["VoiceDirectorAgent", "VoiceInput"]


class VoiceInput(BaseModel):
    """Input contract for the voice director."""

    blueprint: Blueprint
    language: str = "en"
    voice: str = "en-US-AriaNeural"
    rate: str = "+0%"
    scene_pause_sec: float = 0.4


class VoiceDirectorAgent(Agent):
    """Turns a :class:`~src.schema.blueprint.Blueprint` into an audio track."""

    name = "voice_director"
    input_model = VoiceInput
    output_model = AudioTrack

    def __init__(self, backend: TTSBackend, out_dir: Path) -> None:
        self._backend = backend
        self._out_dir = out_dir

    def _run(self, payload: VoiceInput) -> AgentResult:
        scenes = payload.blueprint.scenes
        full_text = " ".join(scene.narration for scene in scenes)

        self._out_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._out_dir / "narration.mp3"

        try:
            words = self._backend.synthesize(full_text, voice=payload.voice, out_path=out_path)
        except ProviderError as exc:
            return AgentResult(status="fail", notes=[str(exc)])

        duration = words[-1].end_sec if words else 0.0
        scene_timings = self._partition(scenes, words)

        track = AudioTrack(
            path=str(out_path),
            voice=payload.voice,
            language=payload.language,
            duration_sec=duration,
            words=words,
            scenes=scene_timings,
        )
        notes = [
            f"synthesized {len(words)} words across {len(scenes)} scenes",
            f"scene pause {payload.scene_pause_sec}s between narrations",
        ]
        return AgentResult(status="ok", data=track, notes=notes)

    @staticmethod
    def _partition(scenes: list[Scene], words: list[WordTiming]) -> list[SceneTiming]:
        """Partition ``words`` into per-scene spans by each scene's word count."""
        timings: list[SceneTiming] = []
        cursor = 0
        previous_end = 0.0
        for scene in scenes:
            count = len(scene.narration.split())
            chunk = words[cursor : cursor + count]
            cursor += count
            if chunk:
                start = chunk[0].start_sec
                end = chunk[-1].end_sec
            else:  # no words left (or an empty narration): a zero-length span
                start = end = previous_end
            timings.append(SceneTiming(index=scene.index, start_sec=start, end_sec=end))
            previous_end = end
        return timings
