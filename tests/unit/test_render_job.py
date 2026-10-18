"""Task 3.8 tests: Colab hero-render job spec + transport."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.errors import ProviderError
from src.visuals.render_job import (
    RenderJob,
    RenderResult,
    RenderScene,
    read_job,
    read_result,
    write_job,
    write_result,
)


def make_job() -> RenderJob:
    return RenderJob(
        job_id="job-42",
        scenes=[
            RenderScene(index=0, prompt="a dragon over a city", duration_sec=4.0),
            RenderScene(index=1, prompt="the dragon lands", duration_sec=6.5),
        ],
    )


# --------------------------------------------------------------------------- #
# RenderJob round-trip
# --------------------------------------------------------------------------- #
def test_job_round_trips(tmp_path: Path):
    job = make_job()

    path = write_job(job, tmp_path)
    loaded = read_job(path)

    assert loaded == job
    assert loaded.scenes[0].prompt == "a dragon over a city"
    assert loaded.model == "ltx-video"
    assert loaded.fps == 30


def test_write_job_creates_dirs_and_uses_job_id_name(tmp_path: Path):
    jobs_dir = tmp_path / "nested" / "jobs"

    path = write_job(make_job(), jobs_dir)

    assert path == jobs_dir / "job-42.json"
    assert path.exists()
    assert jobs_dir.is_dir()
    assert not (path.with_name(path.name + ".tmp")).exists()


def test_job_json_is_stable_and_ordered(tmp_path: Path):
    path = write_job(make_job(), tmp_path)
    text = path.read_text(encoding="utf-8")

    assert text == json.dumps(make_job().model_dump(mode="json"), indent=2, sort_keys=False)
    assert list(json.loads(text)) == ["job_id", "model", "width", "height", "fps", "scenes"]


# --------------------------------------------------------------------------- #
# RenderResult round-trip
# --------------------------------------------------------------------------- #
def test_result_round_trips_with_int_keys(tmp_path: Path):
    result = RenderResult(job_id="job-42", outputs={0: "scene_0.mp4", 1: "scene_1.mp4"})

    path = write_result(result, tmp_path)
    loaded = read_result(path)

    assert loaded == result
    assert all(isinstance(k, int) for k in loaded.outputs)
    assert loaded.outputs[1] == "scene_1.mp4"
    assert path == tmp_path / "job-42.json"


# --------------------------------------------------------------------------- #
# error handling
# --------------------------------------------------------------------------- #
def test_read_job_raises_on_invalid_json(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ProviderError):
        read_job(path)


def test_read_job_raises_on_schema_violation(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"nope": 1}), encoding="utf-8")

    with pytest.raises(ProviderError):
        read_job(path)


def test_read_result_raises_on_invalid_json(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ProviderError):
        read_result(path)


# --------------------------------------------------------------------------- #
# notebook template
# --------------------------------------------------------------------------- #
def test_notebook_template_is_valid():
    notebook = Path(__file__).resolve().parents[2] / "notebooks" / "hero_render.ipynb"

    assert notebook.exists()
    data = json.loads(notebook.read_text(encoding="utf-8"))
    assert data["nbformat"] == 4
    assert isinstance(data["cells"], list)
    assert data["cells"]
