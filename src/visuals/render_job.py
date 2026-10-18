"""Colab hero-render job spec and file transport.

The hero render is offloaded to a free Google Colab GPU notebook. The Oracle VM
(the "brain") does not talk to the notebook directly; instead the two sides
exchange small, strict JSON documents through a mounted Drive folder:

- ``RenderJob``    — what to render. A list of :class:`RenderScene` prompts plus
  output dimensions.
- ``RenderResult`` — what came back. A mapping of scene index to output file
  name.

This module is the *contract*: the pydantic models both sides agree on, and a
tiny, deterministic, atomic file transport (:func:`write_job` / :func:`read_job`
and :func:`write_result` / :func:`read_result`). Keeping the transport here means
the notebook and the pipeline cannot drift on field names, ordering, or error
handling.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from src.errors import ProviderError

__all__ = [
    "RenderJob",
    "RenderResult",
    "RenderScene",
    "read_job",
    "read_result",
    "write_job",
    "write_result",
]


class RenderScene(BaseModel):
    """A single scene to be rendered by text-to-video."""

    index: int
    prompt: str
    duration_sec: float = 5.0


class RenderJob(BaseModel):
    """A complete hero-render job handed to the Colab GPU notebook."""

    job_id: str
    model: str = "ltx-video"
    width: int = 1280
    height: int = 720
    fps: int = 30
    scenes: list[RenderScene] = Field(default_factory=list)


class RenderResult(BaseModel):
    """The output of a hero-render job, returned by the notebook.

    ``outputs`` maps a scene ``index`` to the produced file name (not a full
    path — the notebook writes into a results folder the pipeline also mounts).
    """

    job_id: str
    outputs: dict[int, str] = Field(default_factory=dict)


def _dump(model: BaseModel) -> str:
    """Serialise ``model`` to strict, stable-order JSON text."""
    return json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=False)


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically via a sibling ``.tmp`` file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path: Path) -> object:
    """Read and parse ``path`` as JSON, raising :class:`ProviderError` on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderError(f"could not read JSON from {path}: {exc}") from exc


def write_job(job: RenderJob, jobs_dir: Path) -> Path:
    """Write ``job`` to ``jobs_dir/<job_id>.json`` atomically; return the path."""
    path = jobs_dir / f"{job.job_id}.json"
    _atomic_write(path, _dump(job))
    return path


def read_job(path: Path) -> RenderJob:
    """Read and validate a :class:`RenderJob` from ``path``."""
    data = _load_json(path)
    try:
        return RenderJob.model_validate(data)
    except ValidationError as exc:
        raise ProviderError(f"invalid RenderJob at {path}: {exc}") from exc


def write_result(result: RenderResult, results_dir: Path) -> Path:
    """Write ``result`` to ``results_dir/<job_id>.json`` atomically; return the path."""
    path = results_dir / f"{result.job_id}.json"
    _atomic_write(path, _dump(result))
    return path


def read_result(path: Path) -> RenderResult:
    """Read and validate a :class:`RenderResult` from ``path``."""
    data = _load_json(path)
    try:
        return RenderResult.model_validate(data)
    except ValidationError as exc:
        raise ProviderError(f"invalid RenderResult at {path}: {exc}") from exc
