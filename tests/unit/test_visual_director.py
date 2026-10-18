"""Task 3.9 tests: the ``visual_director`` tier router (all fakes, no network)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.agents import visual_director as vd
from src.agents.visual_director import (
    SceneAsset,
    SceneAssets,
    VisualDirectorAgent,
    VisualInput,
)
from src.errors import ProviderError
from src.schema.blueprint import Blueprint
from src.visuals.hero_video import HeroResult
from src.visuals.stock import StockAsset


# --------------------------------------------------------------------------- #
# blueprint helper
# --------------------------------------------------------------------------- #
def make_blueprint(
    *,
    kinds: list[str],
    heroes: list[bool] | None = None,
    keywords: list[list[str]] | None = None,
    prompts: list[str | None] | None = None,
    descriptions: list[str | None] | None = None,
    durations: list[float] | None = None,
) -> Blueprint:
    count = len(kinds)
    heroes = heroes if heroes is not None else [False] * count
    keywords = keywords if keywords is not None else [[] for _ in range(count)]
    prompts = prompts if prompts is not None else [None] * count
    descriptions = descriptions if descriptions is not None else [None] * count
    durations = durations if durations is not None else [5.0] * count
    scenes = [
        {
            "index": i + 1,
            "narration": f"Narration for scene {i + 1}.",
            "visual": {
                "kind": kinds[i],
                "prompt": prompts[i],
                "keywords": keywords[i],
                "description": descriptions[i],
            },
            "duration_sec": durations[i],
            "hero": heroes[i],
        }
        for i in range(count)
    ]
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "A Visual Director Test Blueprint",
                "category": "ai_tech",
                "language": "en",
                "target_duration_sec": 60,
            },
            "scenes": scenes,
        }
    )


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeImageClient:
    def __init__(self, tmp_path: Path, *, fail_for: tuple[str, ...] = ()) -> None:
        self._dir = tmp_path
        self._fail_for = set(fail_for)
        self.calls: list[dict[str, Any]] = []

    def generate(self, prompt: str, *, width: int, height: int) -> Path:
        self.calls.append({"prompt": prompt, "width": width, "height": height})
        if prompt in self._fail_for:
            raise ProviderError("image generation boom")
        path = self._dir / f"image_{len(self.calls)}.jpg"
        path.write_bytes(b"\xff\xd8fake-jpeg")
        return path


class FakeHeroClient:
    def __init__(self, tmp_path: Path, *, kind: str = "hero") -> None:
        self._dir = tmp_path
        self._kind = kind
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        prompt: str,
        *,
        duration_sec: float,
        out_dir: Path,
        width: int = 1280,
        height: int = 720,
    ) -> HeroResult:
        self.calls.append(
            {
                "prompt": prompt,
                "duration_sec": duration_sec,
                "out_dir": out_dir,
                "width": width,
                "height": height,
            }
        )
        path = self._dir / "hero.mp4"
        path.write_bytes(b"fake-mp4")
        return HeroResult(path=str(path), kind=self._kind, provider="fakehero")


class FakeStockClient:
    def __init__(self, assets: list[StockAsset]) -> None:
        self._assets = assets
        self.queries: list[str] = []

    def search(self, query: str, **_kwargs: Any) -> list[StockAsset]:
        self.queries.append(query)
        return self._assets


PEXELS_ASSET = StockAsset(
    id="42",
    provider="pexels",
    preview_url="https://example.com/preview.jpg",
    download_url="https://example.com/full.jpg",
)


# --------------------------------------------------------------------------- #
# 1. image
# --------------------------------------------------------------------------- #
def test_image_kind_routes_to_image_client(tmp_path: Path):
    image = FakeImageClient(tmp_path)
    agent = VisualDirectorAgent(image_client=image)

    result = agent.run(
        VisualInput(
            blueprint=make_blueprint(kinds=["image"]), out_dir=tmp_path, width=640, height=360
        )
    )

    assert result.status == "ok"
    assert isinstance(result.data, SceneAssets)
    assert len(result.data.items) == 1
    item = result.data.items[0]
    assert isinstance(item, SceneAsset)
    assert item.kind == "image"
    assert item.provider == "pollinations"
    assert Path(item.path).exists()
    assert image.calls == [{"prompt": "Narration for scene 1.", "width": 640, "height": 360}]


# --------------------------------------------------------------------------- #
# 2. hero
# --------------------------------------------------------------------------- #
def test_hero_kind_routes_to_hero_client(tmp_path: Path):
    image = FakeImageClient(tmp_path)
    hero = FakeHeroClient(tmp_path)
    agent = VisualDirectorAgent(image_client=image, hero_client=hero)

    result = agent.run(
        VisualInput(
            blueprint=make_blueprint(kinds=["hero"]), out_dir=tmp_path, width=640, height=360
        )
    )

    assert result.status == "ok"
    item = result.data.items[0]
    assert item.kind == "hero"
    assert item.provider == "fakehero"
    assert len(hero.calls) == 1
    assert hero.calls[0]["duration_sec"] == 5.0
    assert hero.calls[0]["width"] == 640
    assert image.calls == []


# --------------------------------------------------------------------------- #
# 3. hero flag wins
# --------------------------------------------------------------------------- #
def test_hero_flag_overrides_declared_image_kind(tmp_path: Path):
    image = FakeImageClient(tmp_path)
    hero = FakeHeroClient(tmp_path)
    agent = VisualDirectorAgent(image_client=image, hero_client=hero)

    result = agent.run(
        VisualInput(
            blueprint=make_blueprint(kinds=["image"], heroes=[True]),
            out_dir=tmp_path,
        )
    )

    assert result.data.items[0].provider == "fakehero"
    assert len(hero.calls) == 1
    assert image.calls == []


# --------------------------------------------------------------------------- #
# 4. stock
# --------------------------------------------------------------------------- #
def test_stock_kind_searches_and_downloads_first_hit(tmp_path: Path, monkeypatch):
    image = FakeImageClient(tmp_path)
    stock = FakeStockClient([PEXELS_ASSET])
    downloads: list[dict[str, Any]] = []

    def fake_download(http: Any, asset: StockAsset, dest: Path) -> Path:
        downloads.append({"http": http, "asset": asset, "dest": Path(dest)})
        Path(dest).write_bytes(b"fake-stock")
        return Path(dest)

    monkeypatch.setattr(vd, "download", fake_download)
    agent = VisualDirectorAgent(image_client=image, stock_client=stock)

    result = agent.run(
        VisualInput(
            blueprint=make_blueprint(kinds=["stock"], keywords=[["sunset", "beach"]]),
            out_dir=tmp_path,
        )
    )

    assert result.status == "ok"
    item = result.data.items[0]
    assert item.kind == "stock"
    assert item.provider == "pexels"
    assert Path(item.path).exists()
    assert stock.queries == ["sunset beach"]
    assert len(downloads) == 1
    assert downloads[0]["asset"] is PEXELS_ASSET
    assert image.calls == []


# --------------------------------------------------------------------------- #
# 5. motion
# --------------------------------------------------------------------------- #
def test_motion_kind_generates_image_then_renders(tmp_path: Path):
    image = FakeImageClient(tmp_path)
    motions: list[tuple[Path, Path, float]] = []

    def motion_renderer(image_path: Path, out_path: Path, duration_sec: float) -> Path:
        motions.append((Path(image_path), Path(out_path), duration_sec))
        Path(out_path).write_bytes(b"fake-mp4")
        return Path(out_path)

    agent = VisualDirectorAgent(image_client=image, motion_renderer=motion_renderer)

    result = agent.run(
        VisualInput(
            blueprint=make_blueprint(kinds=["motion"], durations=[7.0]),
            out_dir=tmp_path,
        )
    )

    assert result.status == "ok"
    item = result.data.items[0]
    assert item.kind == "motion"
    assert item.provider == "pollinations+motion"
    assert len(image.calls) == 1
    assert len(motions) == 1
    assert motions[0][0] == tmp_path / "image_1.jpg"
    assert motions[0][1] == tmp_path / "scene_001_motion.mp4"
    assert motions[0][2] == 7.0


# --------------------------------------------------------------------------- #
# 6. per-scene failure does not abort the run
# --------------------------------------------------------------------------- #
def test_failing_scene_is_noted_and_others_continue(tmp_path: Path):
    image = FakeImageClient(tmp_path, fail_for=("Narration for scene 2.",))
    agent = VisualDirectorAgent(image_client=image)

    result = agent.run(
        VisualInput(blueprint=make_blueprint(kinds=["image", "image", "image"]), out_dir=tmp_path)
    )

    assert result.status == "ok"
    assert [item.index for item in result.data.items] == [1, 3]
    assert any("scene 2" in note for note in result.notes)


# --------------------------------------------------------------------------- #
# 7. empty blueprint fails
# --------------------------------------------------------------------------- #
def test_no_scenes_fails(tmp_path: Path):
    blueprint = make_blueprint(kinds=["image"])
    blueprint.scenes = []  # bypass the schema's min_length to model an empty plan
    agent = VisualDirectorAgent(image_client=FakeImageClient(tmp_path))

    result = agent.run(VisualInput(blueprint=blueprint, out_dir=tmp_path))

    assert result.status == "fail"
    assert result.data is None


# --------------------------------------------------------------------------- #
# degradation paths
# --------------------------------------------------------------------------- #
def test_hero_without_client_falls_back_to_image(tmp_path: Path):
    image = FakeImageClient(tmp_path)
    agent = VisualDirectorAgent(image_client=image)

    result = agent.run(VisualInput(blueprint=make_blueprint(kinds=["hero"]), out_dir=tmp_path))

    item = result.data.items[0]
    assert item.kind == "image"
    assert item.provider == "pollinations"
    assert len(image.calls) == 1


def test_stock_without_hits_falls_back_to_image(tmp_path: Path):
    image = FakeImageClient(tmp_path)
    agent = VisualDirectorAgent(image_client=image, stock_client=FakeStockClient([]))

    result = agent.run(VisualInput(blueprint=make_blueprint(kinds=["stock"]), out_dir=tmp_path))

    item = result.data.items[0]
    assert item.kind == "image"
    assert item.provider == "pollinations"
    assert len(image.calls) == 1


def test_motion_without_renderer_falls_back_to_image(tmp_path: Path):
    image = FakeImageClient(tmp_path)
    agent = VisualDirectorAgent(image_client=image)

    result = agent.run(VisualInput(blueprint=make_blueprint(kinds=["motion"]), out_dir=tmp_path))

    item = result.data.items[0]
    assert item.kind == "image"
    assert item.provider == "pollinations"


# --------------------------------------------------------------------------- #
# prompt precedence
# --------------------------------------------------------------------------- #
def test_prompt_precedence_prompt_then_description_then_narration(tmp_path: Path):
    image = FakeImageClient(tmp_path)
    agent = VisualDirectorAgent(image_client=image)

    result = agent.run(
        VisualInput(
            blueprint=make_blueprint(
                kinds=["image", "image", "image"],
                prompts=["explicit prompt", None, None],
                descriptions=[None, "a description", None],
            ),
            out_dir=tmp_path,
        )
    )

    assert result.status == "ok"
    prompts = [call["prompt"] for call in image.calls]
    assert prompts == ["explicit prompt", "a description", "Narration for scene 3."]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
