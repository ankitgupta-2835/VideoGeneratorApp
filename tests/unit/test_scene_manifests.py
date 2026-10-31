"""Scene-numbered assets and join manifests make a run self-explanatory."""

from __future__ import annotations

import json
from pathlib import Path

from src.agents.visual_director import SceneAsset, SceneAssets
from src.audio.tts import AudioTrack, SceneTiming
from src.pipeline.orchestrator import RunContext
from src.pipeline.stages import Pipeline
from src.rerun.controller import Stage
from src.schema.blueprint import Blueprint


def _blueprint(scene_count: int = 2) -> Blueprint:
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "Manifest test",
                "category": "ai_tech",
                "language": "en",
                "target_duration_sec": 10,
            },
            "scenes": [
                {
                    "index": index,
                    "narration": f"Scene {index} narration.",
                    "visual": {"kind": "image"},
                    "duration_sec": 5.0,
                }
                for index in range(1, scene_count + 1)
            ],
        }
    )


class ExternalImageClient:
    """Mimics Pollinations: writes into a shared cache outside the run dir."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, prompt: str, *, width: int = 1280, height: int = 720) -> Path:
        path = self._cache_dir / f"{hash(prompt) & 0xFFFF:04x}.jpg"
        path.write_bytes(b"fake image")
        return path


def _ctx(tmp_path: Path) -> RunContext:
    return RunContext(run_id="r", category="ai_tech", work_dir=tmp_path)


def test_visuals_are_copied_to_scene_numbered_files(tmp_path: Path):
    pipeline = Pipeline(
        llm=None,
        image_client=ExternalImageClient(tmp_path / "cache"),
        out_dir=tmp_path / "run",
        allow_media=False,
    )
    pipeline._bag[Stage.SCRIPT] = _blueprint()

    result = pipeline._stage_visuals(_ctx(tmp_path))

    assert result.status == "ok"
    run_visuals = tmp_path / "run" / "visuals"
    assert (run_visuals / "scene_001.jpg").is_file()
    assert (run_visuals / "scene_002.jpg").is_file()

    manifest = json.loads((run_visuals / "manifest.json").read_text())
    assert [entry["index"] for entry in manifest["scenes"]] == [1, 2]
    assert manifest["scenes"][0]["scene_file"] == "visuals/scene_001.jpg"

    assets = pipeline._bag[Stage.VISUALS]
    assert Path(assets.items[0].path) == run_visuals / "scene_001.jpg"


def test_motion_uses_narration_durations_and_writes_manifest(tmp_path: Path):
    recorded: list[float] = []

    def renderer(image: Path, out: Path, duration_sec: float) -> Path:
        recorded.append(duration_sec)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"clip")
        return out

    pipeline = Pipeline(
        llm=None,
        out_dir=tmp_path / "run",
        allow_media=False,
        motion_renderer=renderer,
    )
    pipeline._bag[Stage.SCRIPT] = _blueprint()
    source_dir = tmp_path / "run" / "visuals"
    source_dir.mkdir(parents=True)
    (source_dir / "scene_001.jpg").write_bytes(b"a")
    (source_dir / "scene_002.jpg").write_bytes(b"b")
    pipeline._bag[Stage.VISUALS] = SceneAssets(
        items=[
            SceneAsset(index=1, kind="image", path=str(source_dir / "scene_001.jpg"), provider="x"),
            SceneAsset(index=2, kind="image", path=str(source_dir / "scene_002.jpg"), provider="x"),
        ]
    )
    pipeline._bag[Stage.VOICE] = AudioTrack(
        path=str(tmp_path / "run" / "audio" / "narration.mp3"),
        voice="v",
        language="en",
        duration_sec=6.0,
        scenes=[
            SceneTiming(index=1, start_sec=0.0, end_sec=2.5),
            SceneTiming(index=2, start_sec=2.5, end_sec=6.0),
        ],
    )

    result = pipeline._stage_motion(_ctx(tmp_path))

    assert result.status == "ok"
    # Blueprint says 5s per scene; the narration is authoritative.
    assert recorded == [2.5, 3.5]
    manifest = json.loads((tmp_path / "run" / "motion" / "manifest.json").read_text())
    assert [entry["index"] for entry in manifest["clips"]] == [1, 2]
    assert manifest["clips"][1]["duration_sec"] == 3.5


def test_motion_missing_a_scene_requests_a_visuals_redo(tmp_path: Path):
    pipeline = Pipeline(llm=None, out_dir=tmp_path / "run", allow_media=False)
    pipeline._bag[Stage.SCRIPT] = _blueprint(scene_count=2)
    source = tmp_path / "run" / "visuals" / "scene_001.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"a")
    pipeline._bag[Stage.VISUALS] = SceneAssets(
        items=[SceneAsset(index=1, kind="image", path=str(source), provider="x")]
    )

    result = pipeline._stage_motion(_ctx(tmp_path))

    assert result.status == "fail"
    assert result.redo_from == "visuals"
    assert any("no visual for scene" in note for note in result.notes)
