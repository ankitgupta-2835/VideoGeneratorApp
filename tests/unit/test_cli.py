"""Task 5.3 tests: pipeline CLI entrypoint."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.cli import build_parser, main
from src.rerun.controller import STAGE_ORDER


def test_dry_run_returns_zero_and_prints_stage_lines(tmp_path: Path, capsys):
    code = main(["--dry-run", "--category", "ai_tech", "--work-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    for stage in STAGE_ORDER:
        assert f"{stage.value}: ok" in out
    assert "status: ok" in out
    assert (tmp_path / "stages" / "trend.txt").is_file()


def test_invalid_category_rejected_by_argparse(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--dry-run", "--category", "not_a_category"])
    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_live_run_uses_injected_builder(tmp_path: Path, capsys):
    """Non-dry-run now runs the live path via the (injectable) builder."""
    from types import SimpleNamespace

    from src.pipeline.orchestrator import build_dry_run_stages

    calls: list[dict[str, object]] = []

    def builder(**kwargs: object):
        calls.append(kwargs)
        return build_dry_run_stages()

    code = main(
        ["--category", "ai_tech", "--work-dir", str(tmp_path)],
        live_builder=builder,
        secrets_loader=lambda: SimpleNamespace(),
        config_loader=lambda: SimpleNamespace(
            settings=SimpleNamespace(), categories=SimpleNamespace()
        ),
    )

    out = capsys.readouterr().out
    assert code == 0
    assert calls and calls[0]["demo"] is False
    assert "status: ok" in out


def test_language_hi_is_accepted(tmp_path: Path):
    code = main(
        ["--dry-run", "--category", "finance", "--language", "hi", "--work-dir", str(tmp_path)]
    )
    assert code == 0


def test_missing_category_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


def test_parser_choices_are_the_four_categories():
    parser = build_parser()
    action = next(a for a in parser._actions if a.dest == "category")
    assert set(action.choices) == {
        "ai_tech",
        "finance",
        "health_fitness",
        "general_knowledge",
    }


def test_run_id_and_work_dir_are_consistent(tmp_path: Path, monkeypatch, capsys):
    """The printed run_id must match the orchestrator's id and its work dir."""
    monkeypatch.chdir(tmp_path)
    code = main(["--dry-run", "--category", "finance"])

    out = capsys.readouterr().out
    assert code == 0
    printed = {
        line.split(": ", 1)[0]: line.split(": ", 1)[1]
        for line in out.splitlines()
        if ": " in line and not line.startswith("status")
    }
    run_id = printed["run_id"]
    work_dir = Path(printed["work_dir"])
    assert run_id.startswith("finance-")
    assert work_dir.name == run_id
    assert work_dir.is_dir()
