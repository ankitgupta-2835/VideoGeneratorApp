"""Task 3.1 tests: voice_director agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.voice_director import VoiceDirectorAgent, VoiceInput
from src.audio.tts import AudioTrack, TTSBackend, WordTiming
from src.errors import ProviderError
from src.schema.blueprint import Blueprint


def make_blueprint() -> Blueprint:
    """An inline three-scene blueprint fixture."""
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "The Rise of Local LLMs",
                "category": "ai_tech",
                "language": "en",
                "target_duration_sec": 120,
            },
            "scenes": [
                {
                    "index": 1,
                    "narration": "Small models run on laptops.",
                    "on_screen_text": "On device",
                    "visual": {"kind": "hero", "keywords": ["ai"]},
                    "duration_sec": 30.0,
                    "hero": True,
                },
                {
                    "index": 2,
                    "narration": "They are cheap and private.",
                    "on_screen_text": "Cheap and private",
                    "visual": {"kind": "image", "keywords": ["cost"]},
                    "duration_sec": 45.0,
                    "hero": False,
                },
                {
                    "index": 3,
                    "narration": "The future is local.",
                    "on_screen_text": None,
                    "visual": {"kind": "motion", "keywords": []},
                    "duration_sec": 45.0,
                    "hero": False,
                },
            ],
        }
    )


class FakeBackend(TTSBackend):
    """Records each call and emits fixed-duration, non-overlapping timings."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def synthesize(self, text: str, *, voice: str, out_path: Path) -> list[WordTiming]:
        self.calls.append({"text": text, "voice": voice, "out_path": out_path})
        timings: list[WordTiming] = []
        cursor = 0.0
        for word in text.split():
            timings.append(WordTiming(word=word, start_sec=cursor, end_sec=cursor + 0.2))
            cursor += 0.2
        out_path.write_text(text, encoding="utf-8")
        return timings


class FailingBackend(TTSBackend):
    def synthesize(self, text: str, *, voice: str, out_path: Path) -> list[WordTiming]:
        raise ProviderError("backend exploded")


def test_three_scene_blueprint_produces_ok_audio_track(tmp_path):
    agent = VoiceDirectorAgent(backend=FakeBackend(), out_dir=tmp_path)
    result = agent.run(VoiceInput(blueprint=make_blueprint()))

    assert result.status == "ok"
    assert isinstance(result.data, AudioTrack)
    track = result.data

    assert track.words
    assert track.path.endswith("narration.mp3")
    assert track.duration_sec == track.words[-1].end_sec

    assert len(track.scenes) == 3
    assert [s.index for s in track.scenes] == [1, 2, 3]

    for scene in track.scenes:
        assert 0.0 <= scene.start_sec <= scene.end_sec <= track.duration_sec
    for earlier, later in zip(track.scenes, track.scenes[1:], strict=False):
        assert later.start_sec >= earlier.start_sec
        assert later.end_sec >= earlier.end_sec


def test_scene_timings_are_partitioned_by_word_count(tmp_path):
    blueprint = make_blueprint()
    agent = VoiceDirectorAgent(backend=FakeBackend(), out_dir=tmp_path)
    track = agent.run(VoiceInput(blueprint=blueprint)).data

    counts = [len(scene.narration.split()) for scene in blueprint.scenes]
    assert sum(counts) == len(track.words)

    cursor = 0
    for scene_timing, count in zip(track.scenes, counts, strict=True):
        chunk = track.words[cursor : cursor + count]
        assert scene_timing.start_sec == chunk[0].start_sec
        assert scene_timing.end_sec == chunk[-1].end_sec
        cursor += count


def test_all_narrations_appear_in_synthesized_text(tmp_path):
    blueprint = make_blueprint()
    agent = VoiceDirectorAgent(backend=FakeBackend(), out_dir=tmp_path)
    track = agent.run(VoiceInput(blueprint=blueprint)).data

    content = Path(track.path).read_text(encoding="utf-8")
    for scene in blueprint.scenes:
        assert scene.narration in content


def test_provider_error_is_reported_as_fail(tmp_path):
    agent = VoiceDirectorAgent(backend=FailingBackend(), out_dir=tmp_path)
    result = agent.run(VoiceInput(blueprint=make_blueprint()))

    assert result.status == "fail"
    assert any("backend exploded" in note for note in result.notes)
