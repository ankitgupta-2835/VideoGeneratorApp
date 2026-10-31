"""QA stage diagnostics: a failed gate must say *why* it failed."""

from __future__ import annotations

from pathlib import Path

from src.pipeline.orchestrator import RunContext, StageResult
from src.pipeline.stages import Pipeline
from src.qa.checks import QaChecks
from src.rerun.controller import Stage
from src.schema.blueprint import Blueprint


def _blueprint() -> Blueprint:
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "QA test",
                "category": "ai_tech",
                "language": "en",
                "target_duration_sec": 270,
            },
            "scenes": [
                {
                    "index": 1,
                    "narration": "A short scene.",
                    "visual": {"kind": "image"},
                    "duration_sec": 5.0,
                }
            ],
        }
    )


def test_qa_failure_notes_include_score_and_issues(tmp_path: Path):
    def checks(_path: Path) -> QaChecks:
        return QaChecks(
            duration_sec=180.0,
            issues=["silence from 10.000s to 20.000s exceeds 5.0s"],
        )

    pipeline = Pipeline(llm=None, out_dir=tmp_path, run_checks_fn=checks, allow_media=False)
    pipeline._bag[Stage.SCRIPT] = _blueprint()
    pipeline._bag[Stage.ASSEMBLE] = tmp_path / "video.mp4"

    result = pipeline._stage_qa(RunContext(run_id="r", category="ai_tech", work_dir=tmp_path))

    assert result.status == "fail"
    assert result.redo_from == "voice"
    joined = "\n".join(result.notes)
    assert "QA score" in joined
    assert "silence from 10.000s to 20.000s exceeds 5.0s" in joined
    assert "QA gate not passed" in joined


def test_empty_captions_requests_captions_redo(tmp_path: Path):
    pipeline = Pipeline(llm=None, out_dir=tmp_path, allow_media=False)
    # Wire CAPTIONS so the gate performs the cheap SRT check; no file exists.
    pipeline._stages[Stage.CAPTIONS] = lambda ctx: StageResult(status="ok")

    result = pipeline._stage_qa(RunContext(run_id="r", category="ai_tech", work_dir=tmp_path))

    assert result.status == "fail"
    assert result.redo_from == "captions"
    assert any("captions missing or empty" in note for note in result.notes)
