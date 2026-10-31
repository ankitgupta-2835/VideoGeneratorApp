"""The GitHub Actions daily workflow is the no-card production host.

These are file/content checks, like ``test_deploy_assets.py``: parse the YAML
and assert the important contracts (schedule, manual dispatch, secrets, state
cache, artifacts, release, failure alert) without running GitHub Actions.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "daily.yml"
ACTIONS_DOC = REPO_ROOT / "docs" / "actions.md"


def _workflow() -> dict:
    assert WORKFLOW.is_file(), f"missing {WORKFLOW}"
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _triggers(workflow: dict) -> dict:
    # PyYAML (YAML 1.1) parses the key ``on`` as boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _steps(workflow: dict) -> list[dict]:
    steps = workflow["jobs"]["render"]["steps"]
    assert isinstance(steps, list)
    return steps


def _text(workflow: dict) -> str:
    parts: list[str] = []
    for step in _steps(workflow):
        parts.append(str(step.get("uses", "")))
        parts.append(str(step.get("with", "")))
        parts.append(str(step.get("run", "")))
    return "\n".join(parts)


def test_workflow_runs_on_schedule_and_manual_dispatch():
    triggers = _triggers(_workflow())
    schedule = triggers["schedule"]
    assert schedule == [{"cron": "30 1 * * *"}]  # 07:00 IST
    dispatch = triggers["workflow_dispatch"]
    assert set(dispatch["inputs"]) == {"mode", "category", "languages", "max_scenes"}
    assert dispatch["inputs"]["mode"]["options"] == ["dry-run", "demo", "full"]


def test_scheduled_runs_are_full_by_default():
    text = _text(_workflow())
    assert "github.event.inputs.mode || 'full'" in text
    assert "inputs.languages || 'both'" in text
    assert 'languages="en hi"' in text


def test_workflow_uses_the_date_rotation():
    text = _text(_workflow())
    assert "python -m src.pipeline.schedule" in text
    assert "--category" in text
    assert "--dry-run" in text
    assert "--demo" in text


def test_workflow_persists_state_between_runs():
    workflow = _workflow()
    steps = _steps(workflow)
    cache_steps = [step for step in steps if str(step.get("uses", "")).startswith("actions/cache")]
    assert cache_steps, "missing actions/cache state step"
    paths = cache_steps[0]["with"]["path"]
    assert "data/history.db" in paths
    assert "data/assets/cache" in paths
    assert "videogen-state-" in cache_steps[0]["with"]["restore-keys"]


def test_workflow_uploads_and_publishes_artifacts():
    text = _text(_workflow())
    assert "actions/upload-artifact" in text
    assert "runs/**/video.mp4" in text
    assert "runs/**/short.mp4" in text
    assert "gh release create" in text
    assert "review.html" in text


def test_workflow_sends_failure_alert_with_existing_notifier():
    workflow = _workflow()
    alert_steps = [
        step for step in _steps(workflow) if step.get("name", "").startswith("Alert on failure")
    ]
    assert len(alert_steps) == 1
    assert alert_steps[0]["if"] == "failure()"
    assert "python -m src.notify" in alert_steps[0]["run"]


def test_workflow_has_write_permission_for_releases():
    workflow = _workflow()
    assert workflow["permissions"]["contents"] == "write"
    assert workflow["concurrency"]["group"] == "daily-video"


def test_workflow_installs_the_runtime_used_by_live_runs():
    text = _text(_workflow())
    assert "ffmpeg" in text
    assert "edge-tts" in text
    assert "pip install -e ." in text


def test_workflow_does_not_mention_oracle_or_a_vm():
    text = WORKFLOW.read_text(encoding="utf-8").lower()
    assert "oracle" not in text
    assert "systemd" not in text


def test_actions_runbook_covers_the_no_card_host():
    assert ACTIONS_DOC.is_file(), f"missing {ACTIONS_DOC}"
    text = ACTIONS_DOC.read_text(encoding="utf-8")
    lowered = text.lower()
    for needle in ("no card", "github actions", "actions/cache", "github releases", "kaggle"):
        assert needle in lowered, f"docs/actions.md is missing {needle!r}"
