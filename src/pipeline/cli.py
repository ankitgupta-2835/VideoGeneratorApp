"""``videogen`` command-line entrypoint.

Three run modes, selected by flags:

* ``--dry-run`` — a fake, zero-external-call pipeline that exercises the
  engine (placeholder stages only).
* ``--demo`` — a **live**, bounded demo run: real clients from secrets/env,
  English, image-only visuals, dry-run publish, and the blueprint capped to
  ``--max-scenes`` (default 6). Needs secrets and FFmpeg.
* neither — a **live** full run through the real stage wiring.

Live modes build their stages via :func:`~src.pipeline.live.build_live_stages`,
which is injectable (``live_builder=...``) so tests never touch the network.
Missing secrets/keys or any provider/config error prints a friendly message and
exits ``1``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.config import Config, load_config
from src.errors import VideoGenError
from src.pipeline.live import build_live_stages
from src.pipeline.orchestrator import (
    Orchestrator,
    RunState,
    build_dry_run_stages,
    new_run_id,
)
from src.rerun.controller import STAGE_ORDER, Stage
from src.secrets import Secrets, load_secrets

__all__ = ["build_parser", "main"]

_FALLBACK_CATEGORIES = ["ai_tech", "finance", "health_fitness", "general_knowledge"]

#: Default number of scenes in a bounded demo run.
_DEFAULT_MAX_SCENES = 6

StageMap = dict[Stage, Callable[..., Any]]


def _categories() -> list[str]:
    """Return the configured categories, falling back to the known four."""
    try:
        config = load_config()
    except Exception:  # noqa: BLE001 - config may be unavailable at runtime
        return list(_FALLBACK_CATEGORIES)
    return list(config.categories.categories)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="videogen",
        description="Run the video-generation pipeline (dry-run, demo, or live).",
    )
    parser.add_argument(
        "--category",
        required=True,
        choices=_categories(),
        help="Topic category to run.",
    )
    parser.add_argument(
        "--language",
        choices=["en", "hi"],
        default="en",
        help="Content language (default: en). Forced to 'en' for --demo.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Run a fake, zero-external-call pipeline to exercise the engine.",
    )
    mode.add_argument(
        "--demo",
        action="store_true",
        help="Bounded live demo: en, image-only, dry-run publish, --max-scenes capped.",
    )
    parser.add_argument(
        "--max-scenes",
        type=int,
        default=_DEFAULT_MAX_SCENES,
        help=f"Scene cap for --demo (default: {_DEFAULT_MAX_SCENES}).",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Working directory (default: runs/<run_id> under the current directory).",
    )
    return parser


def _print_artifacts(state: RunState, work_dir: Path) -> None:
    """Print the produced artifact paths (long video, Short, ...)."""
    labels = {
        Stage.ASSEMBLE.value: "long video",
        Stage.SHORT.value: "short",
        Stage.PUBLISH.value: "publish metadata",
    }
    if state.artifacts.get(Stage.ASSEMBLE.value):
        print(f"long video: {state.artifacts[Stage.ASSEMBLE.value]}")
    if state.artifacts.get(Stage.SHORT.value):
        print(f"short: {state.artifacts[Stage.SHORT.value]}")
    for stage in STAGE_ORDER:
        artifact = state.artifacts.get(stage.value)
        if artifact is None or stage.value in labels:
            continue
        print(f"{stage.value}: {artifact}")
    print(f"work_dir: {work_dir}")


def _write_review_page(state: RunState, work_dir: Path) -> Path | None:
    """Render the review page if the helper is available; return its path."""
    try:
        from src.review.build_review_page import Attempt, build_review_page
    except ImportError:  # pragma: no cover - helper is part of the repo
        return None

    video = state.artifacts.get(Stage.ASSEMBLE.value) or state.artifacts.get(Stage.SHORT.value)
    attempt = Attempt(
        run_id=state.run_id,
        attempt_no=state.attempt_no,
        category=state.category,
        title=state.category,
        video_path=video or "",
        short_path=state.artifacts.get(Stage.SHORT.value),
        status=state.status,
        notes="\n".join(state.notes),
    )
    return build_review_page([attempt], work_dir / "review.html")


def _progress(message: str) -> None:
    """Print one progress line immediately so notebooks stream it live."""
    print(message, flush=True)


def _run_live(
    args: argparse.Namespace,
    *,
    live_builder: Callable[..., StageMap],
    secrets_loader: Callable[[], Secrets],
    config_loader: Callable[[], Config],
) -> int:
    run_id = new_run_id(args.category)
    work_dir = Path(args.work_dir) if args.work_dir else Path("runs") / run_id
    language = "en" if args.demo else args.language
    max_scenes = args.max_scenes if args.demo else None

    try:
        secrets = secrets_loader()
        config = config_loader()
        stages = live_builder(
            secrets=secrets,
            settings=config.settings,
            out_dir=work_dir,
            demo=args.demo,
            max_scenes=max_scenes,
            categories=config.categories,
            category=args.category,
        )
    except VideoGenError as exc:
        print(f"error: {exc}")
        return 1

    orchestrator = Orchestrator(stages)
    _progress(f"run {run_id} | category {args.category} | language {language}")
    state = orchestrator.run(
        args.category,
        language=language,
        work_dir=work_dir,
        run_id=run_id,
        progress=_progress,
    )

    for stage in STAGE_ORDER:
        print(f"{stage.value}: {state.stages.get(stage.value)}")
    print(f"status: {state.status}")
    # Surface why a stage failed (LLM error, throttled source, ...). Without
    # this a failed run printed only "fail" and hid the cause.
    for note in state.notes:
        print(f"note: {note}")
    print(f"run_id: {state.run_id}")
    _print_artifacts(state, work_dir)

    review = _write_review_page(state, work_dir)
    if review is not None:
        print(f"review page: {review}")

    return 0 if state.status == "ok" else 1


def main(
    argv: list[str] | None = None,
    *,
    live_builder: Callable[..., StageMap] = build_live_stages,
    secrets_loader: Callable[[], Secrets] = load_secrets,
    config_loader: Callable[[], Config] = load_config,
) -> int:
    args = build_parser().parse_args(argv)

    if args.dry_run:
        run_id = new_run_id(args.category)
        work_dir = Path(args.work_dir) if args.work_dir else Path("runs") / run_id

        orchestrator = Orchestrator(build_dry_run_stages())
        state = orchestrator.run(
            args.category,
            language=args.language,
            work_dir=work_dir,
            run_id=run_id,
            progress=_progress,
        )

        for stage in STAGE_ORDER:
            print(f"{stage.value}: {state.stages.get(stage.value)}")
        print(f"status: {state.status}")
        print(f"run_id: {state.run_id}")
        print(f"work_dir: {work_dir}")

        return 0 if state.status == "ok" else 1

    return _run_live(
        args,
        live_builder=live_builder,
        secrets_loader=secrets_loader,
        config_loader=config_loader,
    )


if __name__ == "__main__":  # pragma: no cover - exercised via __main__
    sys.exit(main())
