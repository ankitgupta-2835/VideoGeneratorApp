"""Date → category rotation for the daily scheduled run.

The scheduler needs to answer one question deterministically: *which category
should today's run use?* The rule is deliberately trivial so it is stable and
auditable:

* The rotation is a fixed, ordered list of categories (:data:`ROTATION`).
* The category for a date ``d`` is ``rotation[d.toordinal() % len(rotation)]``.

Because the choice depends only on the **ordinal day number** — never on the
wall clock or time-of-day — every invocation on the same calendar day resolves
to the same category, and walking one day at a time cycles through the whole
rotation before repeating.

The module is runnable so a workflow step can ask it for the category:
``python -m src.pipeline.schedule`` prints today's category (UTC).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime

__all__ = ["ROTATION", "category_for_date", "build_parser", "main"]

#: Default daily rotation, matching ``config/categories.yaml`` ``rotation:``.
ROTATION: list[str] = ["ai_tech", "finance", "health_fitness", "general_knowledge"]


def category_for_date(d: date, rotation: list[str] = ROTATION) -> str:
    """Return the category scheduled for calendar date ``d``.

    The selection is ``rotation[d.toordinal() % len(rotation)]`` — a pure
    function of the date, so it is stable for a whole day (and independent of
    time-of-day), and consecutive days cycle through every entry of
    ``rotation`` before any repeat.

    Raises :class:`ValueError` if ``rotation`` is empty.
    """
    if not rotation:
        raise ValueError("rotation must not be empty")
    return rotation[d.toordinal() % len(rotation)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.pipeline.schedule",
        description="Print the category scheduled for a date (default: today, UTC).",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="ISO date (YYYY-MM-DD) to resolve; defaults to today's UTC date.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Print the category for ``--date`` (or today, UTC) and exit ``0``."""
    args = build_parser().parse_args(argv)
    d = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
    print(category_for_date(d))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via __main__
    sys.exit(main())
