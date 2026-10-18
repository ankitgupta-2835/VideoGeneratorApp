"""Task 5.9 tests: the CLI's live / bounded-demo paths.

Every test injects a fake ``live_builder`` (and fake secrets/config loaders),
so no network, secrets, or FFmpeg is ever touched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.errors import ProviderError
from src.pipeline.cli import main
from src.pipeline.orchestrator import build_dry_run_stages
from src.rerun.controller import STAGE_ORDER


class _BuilderSpy:
    """A stand-in live builder that records its kwargs and returns dry-run stages."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object):
        self.calls.append(kwargs)
        return build_dry_run_stages()


def _fake_secrets():  # noqa: ANN202 - test helper
    return SimpleNamespace()


def _fake_config():  # noqa: ANN202 - test helper
    return SimpleNamespace(settings=SimpleNamespace())


def test_live_run_returns_zero_and_prints_paths(tmp_path: Path, capsys):
    builder = _BuilderSpy()

    code = main(
        ["--category", "ai_tech", "--work-dir", str(tmp_path)],
        live_builder=builder,
        secrets_loader=_fake_secrets,
        config_loader=_fake_config,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert builder.calls, "live builder was not called"
    assert builder.calls[0]["demo"] is False
    assert builder.calls[0]["max_scenes"] is None
    assert "status: ok" in out
    # long video + short artifacts are printed as explicit paths
    assert f"long video: {tmp_path / 'stages' / 'assemble.txt'}" in out
    assert f"short: {tmp_path / 'stages' / 'short.txt'}" in out
    assert (tmp_path / "review.html").is_file()
    assert "review page:" in out


def test_demo_run_returns_zero_and_is_bounded(tmp_path: Path, capsys):
    builder = _BuilderSpy()

    code = main(
        ["--demo", "--max-scenes", "2", "--category", "ai_tech", "--work-dir", str(tmp_path)],
        live_builder=builder,
        secrets_loader=_fake_secrets,
        config_loader=_fake_config,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert builder.calls[0]["demo"] is True
    assert builder.calls[0]["max_scenes"] == 2
    assert "status: ok" in out


def test_demo_caps_max_scenes_defaulting_to_six(tmp_path: Path):
    builder = _BuilderSpy()

    code = main(
        ["--demo", "--category", "finance", "--work-dir", str(tmp_path)],
        live_builder=builder,
        secrets_loader=_fake_secrets,
        config_loader=_fake_config,
    )

    assert code == 0
    assert builder.calls[0]["demo"] is True
    assert builder.calls[0]["max_scenes"] == 6


def test_builder_provider_error_exits_one_with_message(tmp_path: Path, capsys):
    def boom(**kwargs: object):
        raise ProviderError("missing GEMINI_API_KEY (LLM_PROVIDER=gemini)")

    code = main(
        ["--category", "ai_tech", "--work-dir", str(tmp_path)],
        live_builder=boom,
        secrets_loader=_fake_secrets,
        config_loader=_fake_config,
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "GEMINI_API_KEY" in out


def test_secrets_error_exits_one_with_message(tmp_path: Path, capsys):
    from src.errors import SecretsError

    def bad_secrets():
        raise SecretsError("invalid secrets/environment: LLM key required")

    code = main(
        ["--category", "ai_tech", "--work-dir", str(tmp_path)],
        live_builder=_BuilderSpy(),
        secrets_loader=bad_secrets,
        config_loader=_fake_config,
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "LLM key required" in out


def test_dry_run_never_calls_the_live_builder(tmp_path: Path, capsys):
    called = False

    def builder(**kwargs: object):
        nonlocal called
        called = True
        raise AssertionError("dry-run must not build live stages")

    code = main(
        ["--dry-run", "--category", "ai_tech", "--work-dir", str(tmp_path)],
        live_builder=builder,
        secrets_loader=_fake_secrets,
        config_loader=_fake_config,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert called is False
    assert "status: ok" in out
    for stage in STAGE_ORDER:
        assert f"{stage.value}: ok" in out
    assert (tmp_path / "stages" / "trend.txt").is_file()


def test_dry_run_and_demo_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--dry-run", "--demo", "--category", "ai_tech"])
    assert excinfo.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
