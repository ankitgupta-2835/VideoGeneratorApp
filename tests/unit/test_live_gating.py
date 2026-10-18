"""Task 5.8 tests: live tests are gated and never run in normal CI.

These tests do not touch the network. They verify the self-skipping harness in
``tests/live/conftest.py`` and that a plain collection of ``tests/live`` yields
zero items when ``RUN_LIVE`` is unset.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_CONFTEST = REPO_ROOT / "tests" / "live" / "conftest.py"
LIVE_DOC = REPO_ROOT / "docs" / "live-testing.md"


def test_live_conftest_exists_and_gates_on_run_live():
    assert LIVE_CONFTEST.is_file()
    text = LIVE_CONFTEST.read_text(encoding="utf-8")
    assert "RUN_LIVE" in text


def test_live_docs_describe_opt_in_run():
    assert LIVE_DOC.is_file()
    text = LIVE_DOC.read_text(encoding="utf-8")
    assert "RUN_LIVE=1" in text
    assert "pytest -m live" in text


def test_plain_pytest_collects_no_live_tests():
    env = {k: v for k, v in os.environ.items() if k != "RUN_LIVE"}
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/live"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr

    # pytest exit code 5 means "no tests collected"; 0 is also acceptable on
    # versions that print a summary even when every item was deselected.
    assert result.returncode in (0, 5), output
    assert "::test_" not in output, output

    reported_none = any(
        token in output
        for token in (
            "no tests ran",
            "no tests collected",
            "0 tests collected",
            "deselected",
        )
    )
    # Some pytest versions swallow the summary line under -q, leaving stdout
    # empty while still exiting 5; an empty quiet-mode collection is itself
    # proof that nothing was collected.
    assert reported_none or (result.returncode == 5 and not output.strip()), output
