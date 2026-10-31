"""Targeted redo tests: a broken artifact replays only its own stage."""

from __future__ import annotations

from pathlib import Path

from src.agents.compliance import ComplianceFlag, ComplianceReport
from src.audio.tts import TTSBackend
from src.errors import ProviderError
from src.pipeline.orchestrator import RunContext, StageResult
from src.pipeline.stages import Pipeline
from src.rerun.controller import Stage
from src.schema.blueprint import Blueprint


def _blueprint(*, narration: str = "A calm scene about technology.") -> Blueprint:
    return Blueprint.model_validate(
        {
            "meta": {
                "title": "Redo test",
                "category": "ai_tech",
                "language": "en",
                "target_duration_sec": 270,
            },
            "scenes": [
                {
                    "index": 1,
                    "narration": narration,
                    "visual": {"kind": "image"},
                    "duration_sec": 5.0,
                }
            ],
        }
    )


def _ctx(tmp_path: Path) -> RunContext:
    return RunContext(run_id="r", category="ai_tech", work_dir=tmp_path)


class BoomTTS(TTSBackend):
    def synthesize(self, text: str, *, voice: str, out_path: Path):
        raise ProviderError("tts provider is down")


class BoomImage:
    def generate(self, prompt: str, *, width: int = 1280, height: int = 720):
        raise ProviderError("image provider is down")


def test_compliance_failure_requests_a_script_redo(tmp_path: Path):
    pipeline = Pipeline(llm=None, out_dir=tmp_path, allow_media=False)
    # SCRIPT must be wired for the redo target to be valid.
    pipeline._stages[Stage.SCRIPT] = lambda ctx: StageResult(status="ok")
    pipeline._bag[Stage.SCRIPT] = _blueprint(narration="This will cure everything.")

    result = pipeline._stage_compliance(_ctx(tmp_path))

    assert result.status == "fail"
    assert result.redo_from == "script"
    assert "compliance gate not passed" in result.notes
    # The rejected report is kept for the script stage to consume.
    assert Stage.COMPLIANCE in pipeline._bag


def test_compliance_feedback_is_consumed_once(tmp_path: Path):
    pipeline = Pipeline(llm=None, out_dir=tmp_path, allow_media=False)
    pipeline._bag[Stage.COMPLIANCE] = ComplianceReport(
        passed=False,
        monetization_safe=False,
        flags=[
            ComplianceFlag(
                severity="block",
                category="medical",
                message="banned medical claim 'cure' in scene 1",
                scene_index=1,
            ),
            ComplianceFlag(
                severity="warn",
                category="superlative",
                message="unverifiable superlative '100%' in scene 1",
                scene_index=1,
            ),
        ],
    )

    feedback = pipeline._compliance_feedback()

    assert feedback == ["scene 1: banned medical claim 'cure' in scene 1"]
    assert pipeline._compliance_feedback() == []


def test_voice_failure_asks_to_redo_voice_and_captions(tmp_path: Path):
    pipeline = Pipeline(llm=None, tts_backend=BoomTTS(), out_dir=tmp_path, allow_media=False)
    pipeline._bag[Stage.SCRIPT] = _blueprint()

    result = pipeline._stage_voice(_ctx(tmp_path))

    assert result.status == "fail"
    assert result.redo_from == "voice"
    assert any("tts provider is down" in note for note in result.notes)


def test_placeholder_only_visuals_ask_for_one_soft_retry(tmp_path: Path):
    pipeline = Pipeline(llm=None, image_client=BoomImage(), out_dir=tmp_path, allow_media=False)
    pipeline._bag[Stage.SCRIPT] = _blueprint()

    result = pipeline._stage_visuals(_ctx(tmp_path))

    assert result.status == "ok"
    assert result.redo_from == "visuals"
    assert any("placeholder" in note for note in result.notes)
    assert pipeline._bag[Stage.VISUALS].items[0].provider == "placeholder"
