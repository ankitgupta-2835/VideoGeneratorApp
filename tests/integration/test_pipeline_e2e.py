"""Task 5.6 integration test: the real agents wired into the orchestrator.

This drives the **whole** wired pipeline through
:class:`~src.pipeline.orchestrator.Orchestrator` with deterministic fakes:

* a :class:`~src.llm.client.FakeLLMClient` scripted with the exact JSON each
  LLM-backed agent expects,
* a :class:`~src.audio.tts.FakeTTSBackend` subclass that also writes a tiny
  **real** silent WAV (so FFmpeg can mix it on CI),
* a local fake image client that writes tiny real PNG bytes per scene,
* an injected QA ``checks_runner`` so the quality gate is deterministic, and
* a real :class:`~src.agents.trend_scout.TrendScoutAgent` over a fake source.

No network is touched. The media stages need FFmpeg, so on a machine without it
they are asserted ``skipped`` (never ``failed``); on CI (which installs FFmpeg)
the assembly/short stages are exercised for real against generated clips.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import zlib
from pathlib import Path

import pytest

from src.agents.trend_scout import TrendScoutAgent
from src.audio.tts import FakeTTSBackend, WordTiming
from src.llm.client import FakeLLMClient
from src.notify import FakeNotifier
from src.pipeline.orchestrator import Orchestrator, StageStatus
from src.pipeline.stages import build_pipeline
from src.qa.checks import QaChecks
from src.rerun.controller import Stage
from src.store.db import Database
from src.trends.base import TrendItem, TrendSource

HAS_FFMPEG = shutil.which("ffmpeg") is not None

_CONTENT_STAGES = [
    Stage.TREND,
    Stage.ANGLE,
    Stage.RESEARCH,
    Stage.SCRIPT,
    Stage.LOCALIZE,
    Stage.COMPLIANCE,
    Stage.QA,
    Stage.SEO,
    Stage.PUBLISH,
]
_MEDIA_STAGES = [Stage.MOTION, Stage.ASSEMBLE, Stage.SHORT]


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
def _png_bytes(
    width: int = 64, height: int = 36, rgb: tuple[int, int, int] = (200, 60, 60)
) -> bytes:
    """Build a small, valid 8-bit RGB PNG without any image dependency.

    FFmpeg on CI must actually decode these "images", so we emit a real PNG
    (IHDR/IDAT/IEND) rather than opaque bytes. Any leading ``0`` byte per row is
    the PNG filter type (none).
    """
    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        raw.extend(bytes(rgb) * width)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


_PNG_BYTES = _png_bytes()


class FakeTrendSource(TrendSource):
    """A single deterministic candidate topic (no network)."""

    name = "fake"

    def fetch(self, *, keywords: list[str] | None = None) -> list[TrendItem]:
        return [
            TrendItem(
                title="Local LLMs Are Coming",
                url="https://example.com/local-llms",
                source="fake",
                metrics={"views": 10000.0},
            )
        ]


class FakeImageClient:
    """Writes a tiny real PNG per prompt; returns its path."""

    def __init__(self, out_dir: Path) -> None:
        self._out_dir = Path(out_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        prompt: str,
        *,
        width: int = 1280,
        height: int = 720,
        seed: int | None = None,
        model: str = "flux",
    ) -> Path:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        path = self._out_dir / f"img_{digest}.png"
        path.write_bytes(_PNG_BYTES)
        return path


def _wav_tone(seconds: float = 2.0, rate: int = 8000, freq: float = 440.0) -> bytes:
    """Return a mono 16-bit PCM WAV holding a quiet sine tone.

    A tiny *real* audio file is needed so real FFmpeg (on CI) can mix it. It
    must not be pure digital silence: the assembly stage's ``loudnorm`` filter
    yields NaN on silence, which makes the AAC encoder reject the frame.
    """
    frames = int(seconds * rate)
    samples = bytearray()
    for i in range(frames):
        value = int(0.2 * 32767 * math.sin(2 * math.pi * freq * i / rate))
        samples += struct.pack("<h", value)
    data = bytes(samples)
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
    )
    return header + data


class ToneWavTTSBackend(FakeTTSBackend):
    """A :class:`FakeTTSBackend` whose output is real audio, not text.

    The base backend writes narration text into ``narration.mp3``; real FFmpeg
    (on CI) cannot mix that. We keep the deterministic synthetic word timings
    but overwrite the file with a valid, non-silent WAV so assembly can run.
    """

    def synthesize(self, text: str, *, voice: str, out_path: Path) -> list[WordTiming]:
        timings = super().synthesize(text, voice=voice, out_path=out_path)
        out_path.write_bytes(_wav_tone())
        return timings


def _blueprint_payload() -> dict[str, object]:
    return {
        "meta": {
            "title": "Local LLMs Are Coming",
            "category": "ai_tech",
            "language": "en",
            "target_duration_sec": 3,
        },
        "scenes": [
            {
                "index": 1,
                "narration": "Small models run on laptops today.",
                "on_screen_text": "On device",
                "visual": {"kind": "image", "prompt": "a glowing laptop"},
                "duration_sec": 1.0,
                "hero": False,
            },
            {
                "index": 2,
                "narration": "They are cheap and private.",
                "on_screen_text": "Cheap and private",
                "visual": {"kind": "image", "prompt": "a private server"},
                "duration_sec": 1.0,
                "hero": False,
            },
            {
                "index": 3,
                "narration": "The future of AI is local.",
                "on_screen_text": None,
                "visual": {"kind": "image", "prompt": "a bright future"},
                "duration_sec": 1.0,
                "hero": False,
            },
        ],
    }


def _replies() -> list[str]:
    """The exact JSON replies each LLM-backed agent consumes, in stage order."""
    return [
        # ANGLE
        json.dumps(
            {
                "angles": [
                    {
                        "title": "Local LLMs Are Coming",
                        "hook": "Your laptop now runs frontier AI",
                        "why_viral": "Surprising and useful",
                        "target_emotion": "curiosity",
                        "score": 0.9,
                    }
                ],
                "rationale": "High curiosity, broad audience.",
            }
        ),
        # RESEARCH
        json.dumps(
            {
                "summary": "Small language models now run locally.",
                "facts": [
                    {
                        "text": "Small models run on consumer hardware.",
                        "source": "https://example.com/fact",
                        "confidence": "high",
                    }
                ],
                "sources": [{"title": "Example Source", "url": "https://example.com/fact"}],
            }
        ),
        # SCRIPT
        json.dumps(_blueprint_payload()),
        # QA
        json.dumps({"critiques": [], "adjustment": 0}),
        # SEO
        json.dumps(
            {
                "title": "Local LLMs Are Coming",
                "description": "A short explainer on local language models.",
                "tags": ["ai", "llm", "local"],
                "thumbnail_prompt": "A glowing laptop running an AI model",
            }
        ),
    ]


def _clean_checks(_video: Path) -> QaChecks:
    """A deterministic, no-FFmpeg QA result with no issues."""
    return QaChecks(duration_sec=3.0)


def _run(tmp_path: Path, notifier: FakeNotifier, store: Database):
    stages = build_pipeline(
        llm=FakeLLMClient(_replies()),
        notifier=notifier,
        store=store,
        tts_backend=ToneWavTTSBackend(),
        image_client=FakeImageClient(tmp_path / "images"),
        out_dir=tmp_path / "out",
        run_checks_fn=_clean_checks,
        scout=TrendScoutAgent([FakeTrendSource()]),
    )
    orchestrator = Orchestrator(stages, notifier=notifier, store=store)
    return orchestrator.run("ai_tech", work_dir=tmp_path)


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #
def test_full_pipeline_dry_run(tmp_path: Path) -> None:
    notifier = FakeNotifier()
    store = Database(tmp_path / "db.sqlite")
    store.migrate()

    state = _run(tmp_path, notifier, store)

    # The whole run succeeds; every content stage is wired and ok.
    assert state.status == "ok", state.notes
    for stage in _CONTENT_STAGES:
        assert state.stages[stage.value] == StageStatus.OK.value, (stage, state.notes)

    # A checkpoint alert went out (trend -> "topic" and publish are checkpoints).
    assert notifier.messages, "no checkpoint alert was sent"
    assert any("TOPIC:" in message for message in notifier.messages)
    assert any("PUBLISH:" in message for message in notifier.messages)

    # The run and its alerts are persisted.
    run = store.get_run(state.run_id)
    assert run is not None
    assert run["status"] == "ok"
    assert run["category"] == "ai_tech"
    alerts = store.alerts_for_run(state.run_id)
    assert alerts, "no alerts persisted"
    assert any(alert["checkpoint"] == "publish" for alert in alerts)

    # Without FFmpeg the media stages are skipped, never failed.
    if not HAS_FFMPEG:
        for stage in _MEDIA_STAGES:
            assert state.stages[stage.value] == StageStatus.SKIPPED.value, stage

    store.close()


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is required for real media assembly")
def test_assembly_and_short_produce_nonempty_video(tmp_path: Path) -> None:
    notifier = FakeNotifier()
    store = Database(tmp_path / "db.sqlite")
    store.migrate()

    state = _run(tmp_path, notifier, store)

    assert state.status == "ok", state.notes
    for stage in _MEDIA_STAGES:
        assert state.stages[stage.value] == StageStatus.OK.value, (stage, state.notes)

    video = Path(state.artifacts[Stage.ASSEMBLE.value])
    short = Path(state.artifacts[Stage.SHORT.value])
    assert video.is_file() and video.stat().st_size > 0
    assert short.is_file() and short.stat().st_size > 0

    store.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
