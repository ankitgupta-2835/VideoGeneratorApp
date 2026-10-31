"""Task 3.1 tests: TTS backends and timing contracts."""

from __future__ import annotations

import sys
import types

import pytest

from src.audio.tts import EdgeTTSBackend, FakeTTSBackend, WordTiming
from src.errors import ProviderError

TEXT = "Local models are getting surprisingly good"


def test_module_import_does_not_pull_edge_tts():
    """Importing the module must not import the optional edge-tts package."""
    assert "edge_tts" not in sys.modules


def test_fake_timings_are_monotonic_and_non_overlapping(tmp_path):
    words = FakeTTSBackend().synthesize(TEXT, voice="v", out_path=tmp_path / "ignore.mp3")
    assert words
    assert all(isinstance(w, WordTiming) for w in words)
    for word in words:
        assert word.end_sec >= word.start_sec
    for earlier, later in zip(words, words[1:], strict=False):
        assert later.start_sec >= earlier.end_sec


def test_fake_writes_non_empty_file(tmp_path):
    out = tmp_path / "narration.mp3"
    FakeTTSBackend().synthesize(TEXT, voice="v", out_path=out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_edge_backend_raises_provider_error_when_edge_tts_absent(monkeypatch, tmp_path):
    # A None entry in sys.modules makes ``import edge_tts`` raise ImportError.
    monkeypatch.setitem(sys.modules, "edge_tts", None)
    backend = EdgeTTSBackend()
    with pytest.raises(ProviderError, match="edge-tts not installed"):
        backend.synthesize(TEXT, voice="en-US-AriaNeural", out_path=tmp_path / "a.mp3")


def test_edge_backend_uses_stub_module(monkeypatch, tmp_path):
    seen: dict[str, object] = {}

    class FakeCommunicate:
        def __init__(self, text: str, voice: str, **kwargs: object) -> None:
            self.text = text
            self.voice = voice
            seen.update(kwargs)

        async def stream(self):
            yield {"type": "audio", "data": b"\x00\x01"}
            yield {
                "type": "WordBoundary",
                "offset": 10_000_000,
                "duration": 5_000_000,
                "text": "Hello",
            }
            yield {"type": "audio", "data": b"\x02\x03"}
            yield {
                "type": "WordBoundary",
                "offset": 20_000_000,
                "duration": 3_000_000,
                "text": "world",
            }

    stub = types.ModuleType("edge_tts")
    stub.Communicate = FakeCommunicate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "edge_tts", stub)

    out = tmp_path / "edge.mp3"
    words = EdgeTTSBackend().synthesize("Hello world", voice="en-US-AriaNeural", out_path=out)

    assert out.read_bytes() == b"\x00\x01\x02\x03"
    assert [w.word for w in words] == ["Hello", "world"]
    # edge-tts >=7 defaults to sentence boundaries; we must ask for words,
    # otherwise captions end up empty.
    assert seen.get("boundary") == "WordBoundary"
    # offsets are in 100-nanosecond ticks -> divided by 1e7
    assert words[0].start_sec == pytest.approx(1.0)
    assert words[0].end_sec == pytest.approx(1.5)
    assert words[1].start_sec == pytest.approx(2.0)
    assert words[1].end_sec == pytest.approx(2.3)


def test_edge_backend_tolerates_legacy_communicate(monkeypatch, tmp_path):
    class LegacyCommunicate:
        def __init__(self, text: str, voice: str) -> None:
            pass

        async def stream(self):
            yield {"type": "audio", "data": b"\x00"}
            yield {
                "type": "WordBoundary",
                "offset": 0,
                "duration": 10_000_000,
                "text": "Hi",
            }

    stub = types.ModuleType("edge_tts")
    stub.Communicate = LegacyCommunicate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "edge_tts", stub)

    out = tmp_path / "legacy.mp3"
    words = EdgeTTSBackend().synthesize("Hi", voice="en-US-AriaNeural", out_path=out)

    assert [w.word for w in words] == ["Hi"]
