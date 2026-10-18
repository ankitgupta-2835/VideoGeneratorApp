"""Task 5.9 tests: ``build_pipeline(..., max_scenes=N)`` truncates the blueprint.

Modeled on the E2E fakes in ``tests/integration/test_pipeline_e2e.py``: a
scripted :class:`FakeLLMClient` drives the real agents, a local fake image
client records every prompt it is asked to generate, and a fake trend source
keeps the run offline. No FFmpeg is required — the media stages simply skip.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from src.agents.trend_scout import TrendScoutAgent
from src.llm.client import FakeLLMClient
from src.pipeline.orchestrator import Orchestrator, StageStatus
from src.pipeline.stages import build_pipeline
from src.rerun.controller import Stage
from src.trends.base import TrendItem, TrendSource

# A valid 1x1 PNG so downstream tooling can decode the "images" if needed.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class FakeTrendSource(TrendSource):
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


class RecordingImageClient:
    """Writes a tiny real PNG per prompt and records the prompts."""

    def __init__(self, out_dir: Path) -> None:
        self._out_dir = Path(out_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self.prompts: list[str] = []

    def generate(
        self,
        prompt: str,
        *,
        width: int = 1280,
        height: int = 720,
        seed: int | None = None,
        model: str = "flux",
    ) -> Path:
        self.prompts.append(prompt)
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        path = self._out_dir / f"img_{digest}.png"
        path.write_bytes(_PNG_1X1)
        return path


def _blueprint_payload(scene_count: int) -> dict[str, object]:
    scenes = [
        {
            "index": i,
            "narration": f"Scene {i} narration.",
            "on_screen_text": f"Scene {i}",
            "visual": {"kind": "image", "prompt": f"prompt {i}"},
            "duration_sec": 1.0,
            "hero": False,
        }
        for i in range(1, scene_count + 1)
    ]
    return {
        "meta": {
            "title": "Local LLMs Are Coming",
            "category": "ai_tech",
            "language": "en",
            "target_duration_sec": scene_count,
        },
        "scenes": scenes,
    }


def _replies(scene_count: int) -> list[str]:
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
        json.dumps(_blueprint_payload(scene_count)),
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


def _run(tmp_path: Path, *, scene_count: int, max_scenes: int | None):
    image_client = RecordingImageClient(tmp_path / "images")
    stages = build_pipeline(
        llm=FakeLLMClient(_replies(scene_count)),
        tts_backend=None,
        image_client=image_client,
        out_dir=tmp_path / "out",
        max_scenes=max_scenes,
        scout=TrendScoutAgent([FakeTrendSource()]),
    )
    state = Orchestrator(stages).run("ai_tech", work_dir=tmp_path)
    return state, image_client


def test_max_scenes_truncates_blueprint_to_cap(tmp_path: Path):
    state, image_client = _run(tmp_path, scene_count=3, max_scenes=2)

    assert state.status == "ok", state.notes
    assert state.stages[Stage.SCRIPT.value] == StageStatus.OK.value
    # Only the first two scenes were visualised.
    assert image_client.prompts == ["prompt 1", "prompt 2"]


def test_without_max_scenes_keeps_every_scene(tmp_path: Path):
    state, image_client = _run(tmp_path, scene_count=3, max_scenes=None)

    assert state.status == "ok", state.notes
    assert image_client.prompts == ["prompt 1", "prompt 2", "prompt 3"]


def test_max_scenes_larger_than_blueprint_is_a_noop(tmp_path: Path):
    state, image_client = _run(tmp_path, scene_count=2, max_scenes=5)

    assert state.status == "ok", state.notes
    assert image_client.prompts == ["prompt 1", "prompt 2"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(__import__("pytest").main([__file__]))
