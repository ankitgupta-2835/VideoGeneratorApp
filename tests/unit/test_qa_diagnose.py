"""QA failure -> stage classification tests."""

from __future__ import annotations

import pytest

from src.qa.diagnose import qa_redo_stage
from src.rerun.controller import Stage


@pytest.mark.parametrize(
    ("issue", "expected"),
    [
        ("silence from 10.000s to 20.000s exceeds 5.0s", Stage.VOICE),
        ("captions missing or empty: captions.srt", Stage.CAPTIONS),
        ("black frame from 0.000s to 3.000s exceeds 2.0s", Stage.VISUALS),
        ("A/V desync 4.200s exceeds 2.0s", Stage.ASSEMBLE),
        ("something completely unexpected", None),
    ],
)
def test_issue_maps_to_producing_stage(issue: str, expected: Stage | None):
    assert qa_redo_stage([issue]) is expected


def test_earliest_affected_stage_wins():
    issues = ["black frame from 0.0s to 3.0s", "silence from 10s to 20s"]
    assert qa_redo_stage(issues) is Stage.VOICE


def test_no_issues_means_no_redo():
    assert qa_redo_stage([]) is None
