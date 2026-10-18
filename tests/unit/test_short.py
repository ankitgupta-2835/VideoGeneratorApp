"""Task 3.11 tests: short derivation (9:16 highlight clip from the long video)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.assemble.short import (
    DEFAULT_SHORT_MAX_SEC,
    Segment,
    build_vertical_command,
    derive_short,
    render,
    select_highlight,
)
from src.errors import ProviderError

# --- select_highlight (pure, no ffmpeg needed) -----------------------------


def test_select_highlight_picks_highest_scoring_window() -> None:
    segments = [
        Segment(0, 0.0, 10.0, score=1.0),
        Segment(1, 10.0, 20.0, score=5.0),
        Segment(2, 20.0, 30.0, score=1.0),
    ]

    assert select_highlight(segments, max_duration_sec=15.0) == (10.0, 20.0)


def test_select_highlight_respects_max_duration() -> None:
    # The two top segments together span 20s but the cap is 12s, so only a
    # single segment within the cap can win (the higher-scoring one).
    segments = [
        Segment(0, 0.0, 10.0, score=2.0),
        Segment(1, 10.0, 20.0, score=3.0),
        Segment(2, 20.0, 30.0, score=1.0),
    ]

    assert select_highlight(segments, max_duration_sec=12.0) == (10.0, 20.0)


def test_select_highlight_tie_prefers_earliest() -> None:
    segments = [
        Segment(0, 0.0, 10.0, score=2.0),
        Segment(1, 10.0, 20.0, score=2.0),
    ]

    assert select_highlight(segments, max_duration_sec=10.0) == (0.0, 10.0)


def test_select_highlight_empty_raises() -> None:
    with pytest.raises(ValueError):
        select_highlight([], max_duration_sec=60.0)


def test_select_highlight_excludes_segment_longer_than_cap() -> None:
    # The high-scoring segment is longer than the cap and is excluded, not
    # trimmed, so the short neighbour is selected instead.
    segments = [
        Segment(0, 0.0, 100.0, score=99.0),
        Segment(1, 100.0, 110.0, score=1.0),
    ]

    assert select_highlight(segments, max_duration_sec=30.0) == (100.0, 110.0)


def test_select_highlight_all_too_long_raises() -> None:
    segments = [Segment(0, 0.0, 100.0, score=1.0)]

    with pytest.raises(ValueError):
        select_highlight(segments, max_duration_sec=30.0)


def test_default_max_duration_is_180() -> None:
    assert DEFAULT_SHORT_MAX_SEC == 180.0


# --- build_vertical_command (pure) -----------------------------------------


def test_build_vertical_command_shape(tmp_path: Path) -> None:
    src = tmp_path / "long.mp4"
    out = tmp_path / "short.mp4"

    cmd = build_vertical_command(src, out, start_sec=12.5, duration_sec=30.0)

    assert cmd[0] == "ffmpeg"
    assert str(src) in cmd
    assert "-ss" in cmd and cmd[cmd.index("-ss") + 1] == "12.5"
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "30.0"
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1080:1920" in vf
    assert "crop=1080:1920" in vf
    assert "yuv420p" in vf
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[-1] == str(out)


def test_build_vertical_command_custom_dimensions(tmp_path: Path) -> None:
    cmd = build_vertical_command(
        tmp_path / "in.mp4", tmp_path / "o.mp4", start_sec=0.0, duration_sec=5.0, fps=24
    )

    vf = cmd[cmd.index("-vf") + 1]
    assert "fps=24" in vf
    assert cmd[cmd.index("-r") + 1] == "24"


# --- render (ffmpeg presence / failure handling) ---------------------------


def test_render_without_ffmpeg_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(ProviderError, match="ffmpeg not found"):
        render(["ffmpeg", "-i", "x", str(tmp_path / "out.mp4")])


def test_render_failure_bundles_stderr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(1, command, stderr=b"boom")

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ProviderError, match="boom"):
        render(["ffmpeg", "-i", "x", str(tmp_path / "out.mp4")])


def test_render_missing_output_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ProviderError, match="did not produce output"):
        render(["ffmpeg", "-i", "x", str(tmp_path / "out.mp4")])


def test_derive_short_uses_selection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "long.mp4"
    out = tmp_path / "short.mp4"
    captured: dict[str, object] = {}

    def fake_render(command: list[str]) -> None:
        captured["command"] = command
        Path(command[-1]).write_bytes(b"fake-mp4")

    monkeypatch.setattr("src.assemble.short.render", fake_render)

    result = derive_short(
        src, out, segments=[Segment(0, 4.0, 14.0, score=1.0)], max_duration_sec=30.0
    )

    assert result == out
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("-ss") + 1] == "4.0"
    assert command[command.index("-t") + 1] == "10.0"


# --- integration (runs on CI where ffmpeg is installed) --------------------

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_derive_short_integration(tmp_path: Path) -> None:
    long_video = tmp_path / "long.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=30:duration=3",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(long_video),
        ],
        check=True,
        capture_output=True,
    )

    out = tmp_path / "short.mp4"
    result = derive_short(
        long_video,
        out,
        segments=[Segment(0, 0.0, 3.0, score=1.0)],
        max_duration_sec=30.0,
    )

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0

    if FFPROBE is not None:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(out),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        width, height = probe.stdout.strip().split(",")
        assert (int(width), int(height)) == (1080, 1920)
