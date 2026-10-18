"""Live-test harness: nothing here runs unless ``RUN_LIVE=1`` is set.

Every test under ``tests/live/`` performs real network I/O against an external
service. CI must never run them. The suite's ``pyproject.toml`` declares a
``live`` marker but its ``addopts`` only contain ``-q``, so the marker alone
does not deselect anything -- without this conftest a live test would actually
run and hit the network. This file closes that gap two ways:

1. an autouse fixture that skips each live test unless ``RUN_LIVE=1``; and
2. a ``pytest_collection_modifyitems`` hook that *deselects* every item under
   ``tests/live/`` unless ``RUN_LIVE=1``.

The hook is belt-and-suspenders on top of the fixture: a plain ``pytest`` run
reports *zero collected* live tests (rather than a screen of skips), and it
also ensures a forgetful live test still cannot reach the network in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_LIVE_DIR = Path(__file__).resolve().parent


def _live_enabled() -> bool:
    """Whether the caller explicitly opted in via ``RUN_LIVE=1``."""
    return os.environ.get("RUN_LIVE") == "1"


@pytest.fixture(autouse=True)
def _require_live() -> None:
    """Skip every live test unless explicitly opted in with ``RUN_LIVE=1``."""
    if not _live_enabled():
        pytest.skip("set RUN_LIVE=1 to run live tests")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Deselect ``tests/live/`` items unless ``RUN_LIVE=1``.

    Necessary because ``addopts`` do not exclude the ``live`` marker, so a live
    test would otherwise execute in CI. Removing items here (rather than only
    skipping them in the fixture) keeps normal runs at zero collected live
    tests and guarantees no live test can start.
    """
    if _live_enabled():
        return

    deselected: list[pytest.Item] = []
    kept: list[pytest.Item] = []
    for item in items:
        path = Path(str(getattr(item, "path", item.fspath))).resolve()
        if path.is_relative_to(_LIVE_DIR):
            deselected.append(item)
        else:
            kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
