"""Task 5.4 tests: validate the scheduled GitHub Actions workflow.

The workflow is parsed as YAML and asserted structurally. Note that YAML 1.1
parses the top-level ``on:`` key as the boolean ``True``, so the triggers are
read via ``doc[True]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "daily.yml"


def _load() -> dict[Any, Any]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _job() -> dict[Any, Any]:
    jobs = _load()["jobs"]
    assert len(jobs) == 1, "the daily workflow should contain a single job"
    return next(iter(jobs.values()))


def _steps() -> list[dict[Any, Any]]:
    return _job()["steps"]


def test_workflow_file_exists():
    assert WORKFLOW_PATH.is_file()


def test_has_schedule_and_workflow_dispatch_triggers():
    doc = _load()
    # `on` is parsed as boolean True by YAML 1.1.
    triggers = doc.get(True) or doc.get("on")
    assert triggers is not None
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    crons = [entry["cron"] for entry in triggers["schedule"]]
    assert "30 2 * * *" in crons


def test_dispatch_declares_dry_run_and_category_inputs():
    triggers = _load()[True]
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert "dry_run" in inputs
    assert inputs["dry_run"]["type"] == "boolean"
    assert "category" in inputs
    assert set(inputs["category"]["options"]) >= {
        "auto",
        "ai_tech",
        "finance",
        "health_fitness",
        "general_knowledge",
    }


def test_concurrency_is_set():
    concurrency = _load()["concurrency"]
    assert concurrency["group"]


def test_job_installs_ffmpeg():
    runs = "\n".join(step.get("run", "") for step in _steps())
    assert "apt-get" in runs
    assert "ffmpeg" in runs


def test_setup_python_313():
    versions = [
        step["with"]["python-version"]
        for step in _steps()
        if step.get("uses", "").startswith("actions/setup-python")
    ]
    assert versions == ["3.13"]


def test_a_step_runs_the_pipeline_module():
    runs = "\n".join(step.get("run", "") for step in _steps())
    assert "python -m src.pipeline " in runs
    assert "--category" in runs


def test_category_is_resolved_for_auto():
    runs = "\n".join(step.get("run", "") for step in _steps())
    assert "python -m src.pipeline.schedule" in runs


def test_secrets_are_passed_as_env():
    env = _job()["env"]
    referenced = {key: value for key, value in env.items() if "secrets." in str(value)}
    assert referenced, "the job must map repository secrets into the environment"
    for key in (
        "LLM_PROVIDER",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "PEXELS_API_KEY",
        "PIXABAY_API_KEY",
        "YOUTUBE_CLIENT_SECRET_EN",
        "YOUTUBE_CLIENT_SECRET_HI",
    ):
        assert key in referenced
        assert referenced[key] == f"${{{{ secrets.{key} }}}}"


def test_uploads_runs_artifact():
    uploads = [
        step for step in _steps() if step.get("uses", "").startswith("actions/upload-artifact")
    ]
    assert uploads, "the workflow must upload run artifacts"
    assert "runs/**" in uploads[0]["with"]["path"]
