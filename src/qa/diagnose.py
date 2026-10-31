"""Map a QA failure to the earliest pipeline stage that can fix it.

QA reports technical issues as free text (see :mod:`src.qa.checks`). A failed
render should not discard a good topic, script, and audio just because, say,
one scene has a black frame. This module classifies the issue text into the
stage that produces the broken artifact, so the orchestrator can replay that
stage and the ones after it.

The mapping is intentionally conservative: an unrecognised issue yields
``None`` and the run fails as before.
"""

from __future__ import annotations

from src.rerun.controller import STAGE_ORDER, Stage

__all__ = ["qa_redo_stage"]

#: Keyword sets per producing stage. Order does not matter: the earliest match
#: in :data:`~src.rerun.controller.STAGE_ORDER` wins, so an audio problem is
#: fixed at ``voice`` before any later visual work is redone.
_RULES: tuple[tuple[tuple[str, ...], Stage], ...] = (
    (("silence", "no audio", "missing audio", "narration"), Stage.VOICE),
    (("caption", "subtitle", "srt", "cue"), Stage.CAPTIONS),
    (("black frame", "black", "visual", "scene asset", "image"), Stage.VISUALS),
    (("desync", "a/v", "encode", "video stream", "container"), Stage.ASSEMBLE),
)


def qa_redo_stage(issues: list[str]) -> Stage | None:
    """Return the earliest stage implicated by ``issues``, or ``None``.

    The caller should replay that stage and every stage after it; stages
    before it (topic, script, unaffected media) are reused.
    """
    if not issues:
        return None
    text = " ".join(issues).lower()
    matched = [stage for keywords, stage in _RULES if any(k in text for k in keywords)]
    if not matched:
        return None
    return min(matched, key=STAGE_ORDER.index)
