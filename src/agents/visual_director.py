"""``visual_director`` agent: route every blueprint scene to a visual tier.

The director walks the blueprint's scenes in order and routes each one to
exactly one production tier:

- ``hero``   — a short text-to-video clip from the hero cascade (falling back
  to a generated still when no hero backend is configured),
- ``image``  — a generated still (Pollinations),
- ``stock``  — a free stock photo (falling back to a generated still when no
  stock client is configured or the search returns nothing), and
- ``motion`` — a generated still animated with an FFmpeg motion effect
  (falling back to the still when no renderer is configured).

A scene's ``hero`` flag always wins over its declared ``visual.kind``.

Routing is deliberately failure-tolerant: a tier that raises is recorded as a
note and the remaining scenes are still processed, so a single bad prompt can
never abort the whole run. A scene whose tier fails gets a deterministic local
placeholder image instead, so assembly always has one asset per scene. The
director only fails outright when there is nothing to route (an empty
blueprint).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.agents.base import Agent, AgentResult
from src.http_client import HttpClient
from src.schema.blueprint import Blueprint, Scene
from src.visuals.placeholder import write_placeholder
from src.visuals.stock import download

__all__ = [
    "SceneAsset",
    "SceneAssets",
    "VisualDirectorAgent",
    "VisualInput",
]


class SceneAsset(BaseModel):
    """One produced visual for one scene."""

    index: int
    kind: str  # "hero" | "image" | "stock" | "motion"
    path: str
    provider: str


class SceneAssets(BaseModel):
    """Output contract: the ordered visuals produced for the blueprint."""

    items: list[SceneAsset] = Field(default_factory=list)


class VisualInput(BaseModel):
    """Input contract: the blueprint plus render dimensions and output dir."""

    blueprint: Blueprint
    out_dir: Path
    width: int = 1280
    height: int = 720


class VisualDirectorAgent(Agent):
    """Route each scene to a visual tier, degrading per-scene on failure."""

    name = "visual_director"
    input_model = VisualInput
    output_model = SceneAssets

    def __init__(
        self,
        *,
        image_client: Any,
        hero_client: Any = None,
        stock_client: Any = None,
        motion_renderer: Callable[[Path, Path, float], Path] | None = None,
    ) -> None:
        self._image_client = image_client
        self._hero_client = hero_client
        self._stock_client = stock_client
        self._motion_renderer = motion_renderer
        #: Lazily created HTTP client, used only to download stock assets.
        self._http: HttpClient | None = None

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _effective_kind(scene: Scene) -> str:
        """The tier a scene routes to; the ``hero`` flag always wins."""
        return "hero" if scene.hero else scene.visual.kind

    @staticmethod
    def _prompt_for(scene: Scene) -> str:
        """Prompt precedence: explicit prompt, then description, then narration."""
        if scene.visual.prompt:
            return scene.visual.prompt
        if scene.visual.description:
            return scene.visual.description
        return scene.narration

    def _http_client(self) -> HttpClient:
        if self._http is None:
            self._http = HttpClient()
        return self._http

    def _image(self, scene: Scene, prompt: str, payload: VisualInput) -> SceneAsset:
        path = self._image_client.generate(prompt, width=payload.width, height=payload.height)
        return SceneAsset(
            index=scene.index,
            kind="image",
            path=str(path),
            provider="pollinations",
        )

    # ------------------------------------------------------------------ #
    # routing
    # ------------------------------------------------------------------ #
    def _route(self, scene: Scene, payload: VisualInput) -> SceneAsset:
        kind = self._effective_kind(scene)
        prompt = self._prompt_for(scene)

        if kind == "hero":
            if self._hero_client is not None:
                result = self._hero_client.generate(
                    prompt,
                    duration_sec=scene.duration_sec,
                    out_dir=payload.out_dir,
                    width=payload.width,
                    height=payload.height,
                )
                return SceneAsset(
                    index=scene.index,
                    kind=getattr(result, "kind", "hero"),
                    path=str(result.path),
                    provider=result.provider,
                )
            return self._image(scene, prompt, payload)

        if kind == "stock":
            if self._stock_client is not None:
                query = " ".join(scene.visual.keywords) if scene.visual.keywords else prompt
                assets = self._stock_client.search(query)
                if assets:
                    first = assets[0]
                    dest = payload.out_dir / f"scene_{scene.index:03d}_stock.jpg"
                    path = download(self._http_client(), first, dest)
                    return SceneAsset(
                        index=scene.index,
                        kind="stock",
                        path=str(path),
                        provider=first.provider,
                    )
            return self._image(scene, prompt, payload)

        if kind == "motion":
            if self._motion_renderer is not None:
                image_path = self._image_client.generate(
                    prompt, width=payload.width, height=payload.height
                )
                out_path = payload.out_dir / f"scene_{scene.index:03d}_motion.mp4"
                clip = self._motion_renderer(Path(image_path), out_path, scene.duration_sec)
                return SceneAsset(
                    index=scene.index,
                    kind="motion",
                    path=str(clip),
                    provider="pollinations+motion",
                )
            return self._image(scene, prompt, payload)

        # ``image`` (and any unexpected kind) degrades to the still generator.
        return self._image(scene, prompt, payload)

    # ------------------------------------------------------------------ #
    # entry point
    # ------------------------------------------------------------------ #
    def _run(self, payload: VisualInput) -> AgentResult:
        scenes = payload.blueprint.scenes
        if not scenes:
            return AgentResult(status="fail", notes=["blueprint has no scenes"])

        items: list[SceneAsset] = []
        notes: list[str] = []
        for scene in scenes:
            try:
                asset = self._route(scene, payload)
            except Exception as exc:  # noqa: BLE001 - one bad scene must not abort the run
                notes.append(f"scene {scene.index}: {exc}")
                try:
                    path = write_placeholder(
                        payload.out_dir / f"scene_{scene.index:03d}_placeholder.png",
                        width=payload.width,
                        height=payload.height,
                        seed=self._prompt_for(scene),
                    )
                except Exception as placeholder_exc:  # noqa: BLE001
                    notes.append(f"scene {scene.index}: placeholder failed: {placeholder_exc}")
                    continue
                items.append(
                    SceneAsset(
                        index=scene.index,
                        kind="image",
                        path=str(path),
                        provider="placeholder",
                    )
                )
                notes.append(f"scene {scene.index}: using placeholder image")
                continue
            items.append(asset)

        notes.append(f"produced {len(items)}/{len(scenes)} scene assets")
        return AgentResult(status="ok", data=SceneAssets(items=items), notes=notes)
