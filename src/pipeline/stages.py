"""Real agent -> orchestrator stage wiring (task 5.6).

:func:`build_pipeline` adapts the project's real agents into the
:class:`~src.pipeline.orchestrator.StageFn` contract understood by
:class:`~src.pipeline.orchestrator.Orchestrator`. Each stage reads the previous
stage's typed output out of a private **artifact bag** and feeds it to the next
agent's input model, so the typed hand-offs (``TopicCandidates`` ->
``ChosenAngle`` -> ``ResearchBrief`` -> ``Blueprint`` ...) survive the
string-keyed :class:`~src.pipeline.orchestrator.RunContext`.

Every external dependency is injectable (``llm``, ``notifier``, ``store``,
``tts_backend``, ``image_client``/``hero_client``/``stock_client``, ``http``,
``run_checks_fn``, ``scout``, ``motion_renderer`` ...). Nothing here touches the
network on its own: the agents are given fakes in tests and only the injected
clients decide whether a call is remote.

Stage wiring and skippability
-----------------------------
A stage is **omitted** from the returned mapping when a dependency it needs is
not supplied, so the orchestrator records it :attr:`StageStatus.SKIPPED`
(never a silent fake success). Concretely:

===========================  ==============================================
Stage                        Omitted when
===========================  ==============================================
``TREND``                    no ``scout`` and no ``trend_sources``
``ANGLE`` / ``RESEARCH``     no ``llm``
``SCRIPT``                   no ``llm``
``LOCALIZE``                 no ``llm`` (for ``en`` runs it is a pass-through)
``COMPLIANCE``               no ``llm`` (it consumes the scripted blueprint)
``VOICE``                    no ``tts_backend``
``CAPTIONS``                 no ``tts_backend``
``VISUALS``                  no ``image_client``
``MOTION``                   no ``image_client`` **or** no FFmpeg
``ASSEMBLE``                 no FFmpeg (or ``allow_media=False``)
``SHORT``                    no FFmpeg (or ``allow_media=False``)
``QA``                       no ``llm``, or no FFmpeg **and** the default
                             ``run_checks`` (QA needs a rendered video)
``SEO``                      no ``llm``
``PUBLISH``                  no ``llm``
===========================  ==============================================

FFmpeg-dependent stages (``MOTION``, ``ASSEMBLE``, ``SHORT``) are keyed off
``shutil.which("ffmpeg")`` unless the caller passes ``allow_media`` explicitly.
``notifier`` defaults to :class:`~src.notify.NullNotifier` when omitted; the
orchestrator still fires its own checkpoint alerts through whatever notifier it
was constructed with.

Because skipped stages do not block, a run with no FFmpeg still completes
``ok`` over the content chain while honestly reporting the media stages as
skipped.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.agents.angle_strategist import AngleStrategistAgent
from src.agents.base import Agent, AgentResult
from src.agents.compliance import ComplianceAgent, ComplianceInput, ComplianceReport
from src.agents.localizer import LocalizerAgent
from src.agents.publisher import PublisherAgent, PublishInput
from src.agents.qa_critic import QaCriticAgent, QaInput
from src.agents.research import ResearchAgent
from src.agents.scriptwriter import ScriptRequest, ScriptwriterAgent
from src.agents.seo import Chapter, SeoAgent, SeoInput
from src.agents.trend_scout import ScoutInput, TrendScoutAgent
from src.agents.visual_director import VisualDirectorAgent, VisualInput
from src.agents.voice_director import VoiceDirectorAgent, VoiceInput
from src.assemble.captions import Word as CaptionWord
from src.assemble.captions import group_words, write_srt
from src.assemble.ffmpeg import assemble
from src.assemble.short import Segment, derive_short
from src.audio.tts import AudioTrack, TTSBackend
from src.llm.client import LLMClient
from src.notify import Notifier, NullNotifier
from src.pipeline.orchestrator import RunContext, StageFn, StageResult
from src.qa.checks import QaChecks, run_checks
from src.qa.diagnose import qa_redo_stage
from src.rerun.controller import Stage
from src.schema.blueprint import Blueprint
from src.store.db import Database
from src.trends.base import TrendSource
from src.visuals import motion

__all__ = ["Pipeline", "build_pipeline"]

#: Default narration voices per language (mirrors ``config/voices.yaml``).
_DEFAULT_VOICES = {"en": "en-US-AriaNeural", "hi": "hi-IN-SwaraNeural"}

#: Video-like suffixes that are passed through to assembly untouched.
_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}


def _default_motion_renderer(image: Path, out: Path, duration_sec: float) -> Path:
    """Render a Ken Burns clip from ``image`` for ``duration_sec`` (FFmpeg)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    motion.render(motion.build_kenburns_command(image, out, duration_sec=duration_sec))
    return out


def _caption_cues(path: Path) -> int:
    """Count SRT cues; ``0`` means missing, empty, or unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return text.count("-->")


class Pipeline:
    """Holds the artifact bag and builds the wired stage mapping for one run.

    The bag is keyed by :class:`~src.rerun.controller.Stage` and carries the
    typed pydantic outputs between agents; :class:`RunContext` itself only
    carries string artifacts.
    """

    def __init__(
        self,
        *,
        llm: LLMClient | None,
        out_dir: Path,
        notifier: Notifier | None = None,
        store: Database | None = None,
        tts_backend: TTSBackend | None = None,
        image_client: Any = None,
        hero_client: Any = None,
        stock_client: Any = None,
        http: Any = None,
        run_checks_fn: Callable[[Path], QaChecks] = run_checks,
        scout: Agent | None = None,
        trend_sources: list[TrendSource] | None = None,
        keywords: list[str] | None = None,
        motion_renderer: Callable[[Path, Path, float], Path] | None = None,
        uploader: Any = None,
        music: Path | None = None,
        voices: dict[str, str] | None = None,
        min_score: float = 70.0,
        dry_run: bool = True,
        allow_media: bool | None = None,
        max_scenes: int | None = None,
        target_duration_sec: int = 270,
        min_duration_sec: int = 240,
        max_duration_sec: int = 330,
        max_short_duration_sec: float = 180.0,
        **_ignored: Any,
    ) -> None:
        self._llm = llm
        self._out_dir = Path(out_dir)
        self._notifier: Notifier = notifier or NullNotifier()
        self._store = store
        self._tts_backend = tts_backend
        self._image_client = image_client
        self._hero_client = hero_client
        self._stock_client = stock_client
        self._http = http
        self._run_checks_fn = run_checks_fn
        self._scout = scout or (TrendScoutAgent(trend_sources) if trend_sources else None)
        self._keywords = list(keywords or [])
        self._motion_renderer = motion_renderer or _default_motion_renderer
        self._uploader = uploader
        self._music = music
        self._voices = {**_DEFAULT_VOICES, **(voices or {})}
        self._min_score = min_score
        self._dry_run = dry_run
        self._max_scenes = max_scenes if (max_scenes is not None and max_scenes > 0) else None
        self._target_duration_sec = target_duration_sec
        self._min_duration_sec = min_duration_sec
        self._max_duration_sec = max_duration_sec
        self._max_short_duration_sec = max_short_duration_sec
        self._allow_media = (
            shutil.which("ffmpeg") is not None if allow_media is None else bool(allow_media)
        )

        self._bag: dict[Stage, Any] = {}
        self._stages = self._build_stages()

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def stages(self) -> dict[Stage, StageFn]:
        """Return a fresh copy of the wired ``{Stage: StageFn}`` mapping."""
        return dict(self._stages)

    # ------------------------------------------------------------------ #
    # bag helpers
    # ------------------------------------------------------------------ #
    def _blueprint(self) -> Blueprint:
        """The blueprint downstream stages should consume (localized if any)."""
        blueprint = self._bag.get(Stage.LOCALIZE) or self._bag.get(Stage.SCRIPT)
        if not isinstance(blueprint, Blueprint):  # pragma: no cover - defensive
            raise RuntimeError("no blueprint in the artifact bag")
        return blueprint

    def _voice_for(self, language: str) -> str:
        return self._voices.get(language[:2], self._voices["en"])

    def _asset_prompts(self, blueprint: Blueprint) -> list[str]:
        prompts: list[str] = []
        for scene in blueprint.scenes:
            prompt = scene.visual.prompt or scene.visual.description
            if prompt:
                prompts.append(prompt)
        return prompts

    @staticmethod
    def _agent_result(result: AgentResult, *, artifact: str | None = None) -> StageResult:
        notes = list(result.notes)
        if result.status == "ok":
            return StageResult(status="ok", artifact=artifact, notes=notes)
        return StageResult(status="fail", notes=notes)

    # ------------------------------------------------------------------ #
    # stage construction
    # ------------------------------------------------------------------ #
    def _build_stages(self) -> dict[Stage, StageFn]:
        stages: dict[Stage, StageFn] = {}
        if self._scout is not None:
            stages[Stage.TREND] = self._stage_trend
        if self._llm is not None:
            stages[Stage.ANGLE] = self._stage_angle
            stages[Stage.RESEARCH] = self._stage_research
            stages[Stage.SCRIPT] = self._stage_script
            stages[Stage.LOCALIZE] = self._stage_localize
            stages[Stage.COMPLIANCE] = self._stage_compliance
            if self._allow_media or self._run_checks_fn is not run_checks:
                # QA inspects a rendered video. It is wired when media can be
                # produced, or when the caller injects a checks runner that does
                # not depend on FFmpeg.
                stages[Stage.QA] = self._stage_qa
            stages[Stage.SEO] = self._stage_seo
            stages[Stage.PUBLISH] = self._stage_publish
        if self._tts_backend is not None:
            stages[Stage.VOICE] = self._stage_voice
            stages[Stage.CAPTIONS] = self._stage_captions
        if self._image_client is not None:
            stages[Stage.VISUALS] = self._stage_visuals
            if self._allow_media:
                stages[Stage.MOTION] = self._stage_motion
        if self._allow_media:
            stages[Stage.ASSEMBLE] = self._stage_assemble
            stages[Stage.SHORT] = self._stage_short
        return stages

    # ------------------------------------------------------------------ #
    # content stages
    # ------------------------------------------------------------------ #
    def _stage_trend(self, ctx: RunContext) -> StageResult:
        assert self._scout is not None
        result = self._scout.run(ScoutInput(category=ctx.category, keywords=self._keywords))
        if result.status != "ok":
            return self._agent_result(result)
        candidates = result.data
        self._bag[Stage.TREND] = candidates
        top = candidates.items[0].title if candidates.items else ctx.category
        return self._agent_result(result, artifact=top)

    def _stage_angle(self, ctx: RunContext) -> StageResult:
        assert self._llm is not None
        agent = AngleStrategistAgent(self._llm)
        result = agent.run(self._bag[Stage.TREND])
        if result.status != "ok":
            return self._agent_result(result)
        chosen = result.data
        self._bag[Stage.ANGLE] = chosen
        return self._agent_result(result, artifact=chosen.chosen.title)

    def _stage_research(self, ctx: RunContext) -> StageResult:
        assert self._llm is not None
        agent = ResearchAgent(self._llm)
        result = agent.run(self._bag[Stage.ANGLE])
        if result.status != "ok":
            return self._agent_result(result)
        self._bag[Stage.RESEARCH] = result.data
        return self._agent_result(result, artifact=result.data.angle_title)

    def _stage_script(self, ctx: RunContext) -> StageResult:
        assert self._llm is not None
        brief = self._bag[Stage.RESEARCH]
        angle = self._bag[Stage.ANGLE].chosen
        request = ScriptRequest(
            title=angle.title,
            angle=angle.hook or angle.title,
            category=ctx.category,
            facts=[fact.text for fact in brief.facts],
            sources=[source.title for source in brief.sources],
            duration_target_sec=self._target_duration_sec,
            min_duration_sec=self._min_duration_sec,
            max_duration_sec=self._max_duration_sec,
            compliance_feedback=self._compliance_feedback(),
        )
        agent = ScriptwriterAgent(self._llm)
        result = agent.run(request)
        if result.status != "ok":
            return self._agent_result(result)
        blueprint = result.data
        blueprint = self._truncate_blueprint(blueprint)
        self._bag[Stage.SCRIPT] = blueprint
        return self._agent_result(result, artifact=blueprint.meta.title)

    def _compliance_feedback(self) -> list[str]:
        """Return blocking findings from a rejected draft, once.

        The compliance stage stores its report even when it fails, so a redo
        that starts at ``script`` can tell the writer exactly what to avoid.
        The report is consumed so later, unrelated script runs are not given
        stale feedback.
        """
        report = self._bag.pop(Stage.COMPLIANCE, None)
        if not isinstance(report, ComplianceReport) or report.passed:
            return []
        findings: list[str] = []
        for flag in report.flags:
            if flag.severity != "block":
                continue
            if flag.scene_index is not None:
                findings.append(f"scene {flag.scene_index}: {flag.message}")
            else:
                findings.append(flag.message)
        return findings

    def _truncate_blueprint(self, blueprint: Blueprint) -> Blueprint:
        """Cap the blueprint to ``max_scenes`` (deterministic: keep the first N).

        ``max_scenes`` is an optional, additive knob used by the bounded demo
        runner. When set (and positive), only the first ``max_scenes`` scenes
        are kept — their original ``index`` values are preserved and no scene
        is reordered or rewritten — so downstream stages (compliance, visuals,
        assembly, Shorts) all operate on the same, smaller blueprint. ``None``
        (the default) leaves the blueprint untouched.
        """
        limit = self._max_scenes
        if limit is None or len(blueprint.scenes) <= limit:
            return blueprint
        return blueprint.model_copy(update={"scenes": blueprint.scenes[:limit]})

    def _stage_localize(self, ctx: RunContext) -> StageResult:
        source = self._bag[Stage.SCRIPT]
        if not ctx.language.lower().startswith("hi"):
            # English run: pass the master blueprint straight through.
            self._bag[Stage.LOCALIZE] = source
            return StageResult(status="ok", artifact=source.meta.title, notes=["pass-through (en)"])
        assert self._llm is not None
        agent = LocalizerAgent(self._llm)
        result = agent.run(source)
        if result.status != "ok":
            return self._agent_result(result)
        self._bag[Stage.LOCALIZE] = result.data
        return self._agent_result(result, artifact=result.data.meta.title)

    def _stage_compliance(self, ctx: RunContext) -> StageResult:
        blueprint = self._blueprint()
        agent = ComplianceAgent()
        result = agent.run(
            ComplianceInput(
                blueprint=blueprint,
                asset_prompts=self._asset_prompts(blueprint),
            )
        )
        if result.status != "ok" or not result.data.passed:
            if result.data is not None:
                # Keep the rejected report so the script stage can consume the
                # blocking flags when the orchestrator replays from `script`.
                self._bag[Stage.COMPLIANCE] = result.data
            redo_from = Stage.SCRIPT.value if Stage.SCRIPT in self._stages else None
            return StageResult(
                status="fail",
                notes=[*result.notes, "compliance gate not passed"],
                redo_from=redo_from,
            )
        self._bag[Stage.COMPLIANCE] = result.data
        return self._agent_result(result, artifact=result.data.summary)

    # ------------------------------------------------------------------ #
    # media stages
    # ------------------------------------------------------------------ #
    def _stage_voice(self, ctx: RunContext) -> StageResult:
        assert self._tts_backend is not None
        blueprint = self._blueprint()
        agent = VoiceDirectorAgent(self._tts_backend, self._out_dir / "audio")
        result = agent.run(
            VoiceInput(
                blueprint=blueprint,
                language=ctx.language,
                voice=self._voice_for(ctx.language),
            )
        )
        if result.status != "ok":
            # Audio is the only broken artifact: replay voice (and, because it
            # is downstream, captions) without redoing the topic or script.
            return StageResult(
                status="fail",
                notes=list(result.notes),
                redo_from=Stage.VOICE.value,
            )
        track: AudioTrack = result.data
        self._bag[Stage.VOICE] = track
        return self._agent_result(result, artifact=track.path)

    def _stage_captions(self, ctx: RunContext) -> StageResult:
        track: AudioTrack = self._bag[Stage.VOICE]
        words = [
            CaptionWord(text=word.word, start_sec=word.start_sec, end_sec=word.end_sec)
            for word in track.words
        ]
        cues = group_words(words)
        out = self._out_dir / "captions" / "captions.srt"
        out.parent.mkdir(parents=True, exist_ok=True)
        write_srt(cues, out)
        self._bag[Stage.CAPTIONS] = cues
        return StageResult(status="ok", artifact=str(out), notes=[f"{len(cues)} cue(s)"])

    def _stage_visuals(self, ctx: RunContext) -> StageResult:
        assert self._image_client is not None
        blueprint = self._blueprint()
        agent = VisualDirectorAgent(
            image_client=self._image_client,
            hero_client=self._hero_client,
            stock_client=self._stock_client,
            motion_renderer=self._motion_renderer if self._allow_media else None,
        )
        result = agent.run(VisualInput(blueprint=blueprint, out_dir=self._out_dir / "visuals"))
        if result.status != "ok":
            return StageResult(
                status="fail",
                notes=list(result.notes),
                redo_from=Stage.VISUALS.value,
            )
        assets = result.data
        if not assets.items:
            return StageResult(
                status="fail",
                notes=[*result.notes, "no scene visuals were produced"],
                redo_from=Stage.VISUALS.value,
            )
        self._bag[Stage.VISUALS] = assets
        notes = list(result.notes)
        redo_from: str | None = None
        if all(asset.provider == "placeholder" for asset in assets.items):
            # Image generation degraded to placeholders for every scene. Ask
            # the orchestrator for one soft retry of visuals only; if the
            # providers are still unavailable the placeholder run continues.
            notes.append("every scene used a placeholder; retrying image generation once")
            redo_from = Stage.VISUALS.value
        return StageResult(
            status="ok",
            artifact=str(self._out_dir / "visuals"),
            notes=notes,
            redo_from=redo_from,
        )

    def _stage_motion(self, ctx: RunContext) -> StageResult:
        assets = self._bag[Stage.VISUALS]
        blueprint = self._blueprint()
        durations = {scene.index: scene.duration_sec for scene in blueprint.scenes}
        clips: list[Path] = []
        notes: list[str] = []
        for asset in assets.items:
            path = Path(asset.path)
            if path.suffix.lower() in _VIDEO_SUFFIXES:
                clips.append(path)
                continue
            out = self._out_dir / "motion" / f"scene_{asset.index:03d}.mp4"
            clip = self._motion_renderer(path, out, durations.get(asset.index, 3.0))
            clips.append(Path(clip))
        notes.append(f"{len(clips)} clip(s)")
        self._bag[Stage.MOTION] = clips
        return StageResult(status="ok", artifact=str(self._out_dir / "motion"), notes=notes)

    def _clips(self) -> list[Path]:
        clips = self._bag.get(Stage.MOTION)
        if clips:
            return list(clips)
        assets = self._bag.get(Stage.VISUALS)
        if assets is not None:
            return [Path(asset.path) for asset in assets.items]
        raise RuntimeError("no clips available for assembly")

    def _narration_path(self) -> Path | None:
        track = self._bag.get(Stage.VOICE)
        if isinstance(track, AudioTrack) and Path(track.path).is_file():
            return Path(track.path)
        return None

    def _stage_assemble(self, ctx: RunContext) -> StageResult:
        out = self._out_dir / "video.mp4"
        video = assemble(
            self._clips(),
            out,
            self._out_dir / "assemble",
            narration=self._narration_path(),
            music=self._music,
        )
        self._bag[Stage.ASSEMBLE] = Path(video)
        return StageResult(status="ok", artifact=str(video))

    def _segments(self) -> list[Segment]:
        segments: list[Segment] = []
        track = self._bag.get(Stage.VOICE)
        if isinstance(track, AudioTrack) and track.scenes:
            for timing in track.scenes:
                if timing.end_sec > timing.start_sec:
                    segments.append(
                        Segment(
                            index=timing.index,
                            start_sec=timing.start_sec,
                            end_sec=timing.end_sec,
                            score=1.0,
                        )
                    )
            return segments
        blueprint = self._blueprint()
        cursor = 0.0
        for scene in blueprint.scenes:
            segments.append(
                Segment(
                    index=scene.index,
                    start_sec=cursor,
                    end_sec=cursor + scene.duration_sec,
                    score=1.0,
                )
            )
            cursor += scene.duration_sec
        return segments

    def _stage_short(self, ctx: RunContext) -> StageResult:
        src = Path(self._bag[Stage.ASSEMBLE])
        out = self._out_dir / "short.mp4"
        short = derive_short(
            src,
            out,
            segments=self._segments(),
            max_duration_sec=self._max_short_duration_sec,
        )
        self._bag[Stage.SHORT] = Path(short)
        return StageResult(status="ok", artifact=str(short))

    # ------------------------------------------------------------------ #
    # quality / publish stages
    # ------------------------------------------------------------------ #
    def _stage_qa(self, ctx: RunContext) -> StageResult:
        # Cheap, deterministic caption gate first: an empty SRT is a captions
        # failure, never a video failure, so redo only that stage.
        if Stage.CAPTIONS in self._stages:
            captions_path = self._out_dir / "captions" / "captions.srt"
            if _caption_cues(captions_path) == 0:
                return StageResult(
                    status="fail",
                    notes=[
                        f"captions missing or empty: {captions_path}",
                        "QA gate not passed",
                    ],
                    redo_from=Stage.CAPTIONS.value,
                )

        blueprint = self._blueprint()
        video = self._bag.get(Stage.ASSEMBLE) or self._bag.get(Stage.SHORT)
        video_path = Path(video) if video is not None else self._out_dir / "video.mp4"
        agent = QaCriticAgent(checks_runner=self._run_checks_fn, llm=self._llm)
        result = agent.run(
            QaInput(blueprint=blueprint, video_path=video_path, min_score=self._min_score)
        )
        if result.status != "ok" or result.data is None or not result.data.passed:
            notes = list(result.notes)
            report = result.data
            redo_from: str | None = None
            if report is not None:
                notes.append(f"QA score {report.score:.1f} (minimum {self._min_score:.0f})")
                notes.extend(f"technical: {issue}" for issue in report.technical_issues)
                notes.extend(f"critique: {critique}" for critique in report.critiques)
                # Only the artifact that failed should be regenerated; the
                # orchestrator replays this stage and everything after it.
                target = qa_redo_stage(report.technical_issues)
                redo_from = target.value if target is not None else None
            notes.append("QA gate not passed")
            return StageResult(status="fail", notes=notes, redo_from=redo_from)
        self._bag[Stage.QA] = result.data
        return self._agent_result(result, artifact=f"score={result.data.score:.1f}")

    def _stage_seo(self, ctx: RunContext) -> StageResult:
        assert self._llm is not None
        blueprint = self._blueprint()
        chapters = self._chapters(blueprint)
        agent = SeoAgent(self._llm)
        result = agent.run(
            SeoInput(blueprint=blueprint, chapters=chapters, extra_keywords=self._keywords)
        )
        if result.status != "ok":
            return self._agent_result(result)
        metadata = result.data
        self._bag[Stage.SEO] = metadata
        return self._agent_result(result, artifact=metadata.title)

    def _chapters(self, blueprint: Blueprint) -> list[Chapter]:
        chapters: list[Chapter] = []
        track = self._bag.get(Stage.VOICE)
        if isinstance(track, AudioTrack) and track.scenes:
            by_index = {scene.index: scene for scene in blueprint.scenes}
            for timing in track.scenes:
                scene = by_index.get(timing.index)
                label = (scene.on_screen_text if scene else None) or f"Scene {timing.index}"
                chapters.append(Chapter(start_sec=timing.start_sec, label=label))
            return chapters
        cursor = 0.0
        for scene in blueprint.scenes:
            label = scene.on_screen_text or f"Scene {scene.index}"
            chapters.append(Chapter(start_sec=cursor, label=label))
            cursor += scene.duration_sec
        return chapters

    def _stage_publish(self, ctx: RunContext) -> StageResult:
        metadata = self._bag[Stage.SEO]
        video = self._bag.get(Stage.ASSEMBLE) or self._bag.get(Stage.SHORT)
        video_path = Path(video) if video is not None else self._out_dir / "video.mp4"
        short = self._bag.get(Stage.SHORT)
        agent = PublisherAgent(self._notifier, uploader=self._uploader, store=self._store)
        result = agent.run(
            PublishInput(
                run_id=ctx.run_id,
                language=ctx.language,
                metadata=metadata,
                video_path=video_path,
                short_path=Path(short) if short is not None else None,
                dry_run=self._dry_run,
            )
        )
        if result.status != "ok":
            return self._agent_result(result)
        self._bag[Stage.PUBLISH] = result.data
        meta_path = self._out_dir / "publish.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(
                {
                    "title": metadata.title,
                    "status": result.data.status,
                    "video": str(video_path),
                    "short": str(short) if short is not None else None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return StageResult(status="ok", artifact=str(meta_path), notes=list(result.notes))


def build_pipeline(
    *,
    llm: LLMClient | None,
    notifier: Notifier | None = None,
    store: Database | None = None,
    tts_backend: TTSBackend | None = None,
    image_client: Any = None,
    hero_client: Any = None,
    stock_client: Any = None,
    http: Any = None,
    out_dir: Path,
    run_checks_fn: Callable[[Path], QaChecks] = run_checks,
    max_scenes: int | None = None,
    **kw: Any,
) -> dict[Stage, StageFn]:
    """Wire the real agents into ``{Stage: StageFn}`` for the orchestrator.

    Missing dependencies cause the corresponding stage to be **omitted** (the
    orchestrator records it ``skipped``) rather than faked. See the module
    docstring for the full omission table. ``out_dir`` is the per-run directory
    for every produced artifact. ``max_scenes`` caps the blueprint to its first
    N scenes as the SCRIPT stage produces it (used by the bounded demo runner).
    All extra keyword arguments (``scout``, ``trend_sources``,
    ``motion_renderer``, ``voices``, durations, ``dry_run``, ...) are forwarded
    to :class:`Pipeline`.
    """
    return Pipeline(
        llm=llm,
        notifier=notifier,
        store=store,
        tts_backend=tts_backend,
        image_client=image_client,
        hero_client=hero_client,
        stock_client=stock_client,
        http=http,
        out_dir=out_dir,
        run_checks_fn=run_checks_fn,
        max_scenes=max_scenes,
        **kw,
    ).stages()
