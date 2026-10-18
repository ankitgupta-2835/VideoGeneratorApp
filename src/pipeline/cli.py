"""``videogen`` command-line entrypoint.

Dry-run mode is fully wired: it runs the orchestrator with
:func:`~src.pipeline.orchestrator.build_dry_run_stages`, prints a one-line
summary per stage, and exits ``0`` on success / ``1`` on failure.

Live mode is **not yet wired** — real stage wiring lands in task 5.6. To keep
the CLI safe, a non-dry-run invocation prints a clear message and exits ``1``;
it never touches the network, agents, or media tools.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import load_config
from src.pipeline.orchestrator import (
    Orchestrator,
    build_dry_run_stages,
    new_run_id,
)
from src.rerun.controller import STAGE_ORDER

__all__ = ["build_parser", "main"]

_FALLBACK_CATEGORIES = ["ai_tech", "finance", "health_fitness", "general_knowledge"]


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
        description="Run the video-generation pipeline (dry-run supported).",
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
        help="Content language (default: en).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run a fake, zero-external-call pipeline to exercise the engine.",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Working directory (default: runs/<run_id> under the current directory).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.dry_run:
        print(
            "live execution is not yet wired; it lands in task 5.6. "
            "Re-run with --dry-run to exercise the pipeline engine."
        )
        return 1

    run_id = new_run_id(args.category)
    work_dir = Path(args.work_dir) if args.work_dir else Path("runs") / run_id

    orchestrator = Orchestrator(build_dry_run_stages())
    state = orchestrator.run(
        args.category, language=args.language, work_dir=work_dir, run_id=run_id
    )

    for stage in STAGE_ORDER:
        print(f"{stage.value}: {state.stages.get(stage.value)}")
    print(f"status: {state.status}")
    print(f"run_id: {state.run_id}")
    print(f"work_dir: {work_dir}")

    return 0 if state.status == "ok" else 1


if __name__ == "__main__":  # pragma: no cover - exercised via __main__
    sys.exit(main())
