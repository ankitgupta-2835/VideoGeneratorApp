"""Placeholder scenes are repaired with a detailed prompt and a free provider."""

from __future__ import annotations

import json
from pathlib import Path

from src.errors import ProviderError
from src.llm.client import FakeLLMClient
from src.pipeline.orchestrator import RunContext
from src.pipeline.stages import Pipeline
from src.rerun.controller import Stage
from src.schema.blueprint import Blueprint


def _blueprint() -> Blueprint:
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "Repair test",
                "category": "ai_tech",
                "language": "en",
                "target_duration_sec": 10,
            },
            "scenes": [
                {
                    "index": index,
                    "narration": f"Scene {index} shows a server room.",
                    "visual": {"kind": "image", "prompt": f"plain prompt {index}"},
                    "duration_sec": 5.0,
                }
                for index in (1, 2)
            ],
        }
    )


class FailingImage:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, width: int = 1280, height: int = 720) -> Path:
        self.prompts.append(prompt)
        raise ProviderError("free tier throttled")


class WorkingImage:
    def __init__(self, out_dir: Path) -> None:
        self._out_dir = out_dir
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, width: int = 1280, height: int = 720) -> Path:
        self.prompts.append(prompt)
        path = self._out_dir / f"gen_{len(self.prompts)}.jpg"
        path.write_bytes(b"generated")
        return path


def _ctx(tmp_path: Path) -> RunContext:
    return RunContext(run_id="r", category="ai_tech", work_dir=tmp_path)


def test_placeholders_are_repaired_with_enhanced_prompts(tmp_path: Path):
    primary = FailingImage()
    fallback = WorkingImage(tmp_path / "fallback-cache")
    llm = FakeLLMClient([json.dumps({"prompt": "a detailed cinematic server room"})] * 2)
    pipeline = Pipeline(
        llm=llm,
        image_client=primary,
        fallback_image_client=fallback,
        out_dir=tmp_path / "run",
        allow_media=False,
    )
    pipeline._bag[Stage.SCRIPT] = _blueprint()

    result = pipeline._stage_visuals(_ctx(tmp_path))

    assert result.status == "ok"
    assets = pipeline._bag[Stage.VISUALS]
    assert [asset.provider for asset in assets.items] == ["workingimage", "workingimage"]
    for asset in assets.items:
        assert Path(asset.path).is_file()
        assert Path(asset.path).name.startswith("scene_")

    manifest = json.loads((tmp_path / "run" / "visuals" / "manifest.json").read_text())
    assert manifest["scenes"][0]["prompt"] == "a detailed cinematic server room"
    assert manifest["scenes"][0]["placeholder"] is False
    assert fallback.prompts == [
        "a detailed cinematic server room",
        "a detailed cinematic server room",
    ]
    # The stale placeholder PNGs were removed once the repaired JPEG arrived.
    assert sorted(p.name for p in (tmp_path / "run" / "visuals").iterdir()) == [
        "manifest.json",
        "scene_001.jpg",
        "scene_002.jpg",
    ]


def test_all_providers_failing_keeps_the_placeholder(tmp_path: Path):
    pipeline = Pipeline(
        llm=None,
        image_client=FailingImage(),
        fallback_image_client=FailingImage(),
        out_dir=tmp_path / "run",
        allow_media=False,
    )
    pipeline._bag[Stage.SCRIPT] = _blueprint()

    result = pipeline._stage_visuals(_ctx(tmp_path))

    assert result.status == "ok"
    assets = pipeline._bag[Stage.VISUALS]
    assert all(asset.provider == "placeholder" for asset in assets.items)
    assert any("image repair failed" in note for note in result.notes)
    # Deterministic fallback prompts were still attempted with both providers.
    assert any("scene 1:" in note for note in result.notes)
