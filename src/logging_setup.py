"""Logging setup.

Provides a single :func:`configure_logging` entry point that installs one
project-tagged handler on the root logger (idempotent unless ``force=True``),
plus :func:`get_logger` for namespaced loggers.
"""

from __future__ import annotations

import logging
import sys
from typing import IO

__all__ = ["configure_logging", "get_logger"]

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_HANDLER_MARKER = "_videogen_handler"


def _our_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if getattr(h, _HANDLER_MARKER, False)]


def configure_logging(
    level: str | int = "INFO",
    *,
    stream: IO[str] | None = None,
    force: bool = False,
) -> logging.Logger:
    """Configure the root logger and return it.

    Calling this repeatedly is safe: the project handler is only added once
    unless ``force=True`` is passed.
    """
    root = logging.getLogger()
    existing = _our_handlers(root)
    if existing and not force:
        root.setLevel(level)
        return root

    for handler in existing:
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream or sys.stderr)
    setattr(handler, _HANDLER_MARKER, True)
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger."""
    return logging.getLogger(name)
