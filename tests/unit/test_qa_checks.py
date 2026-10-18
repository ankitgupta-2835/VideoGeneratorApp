"""Task 4.1 tests: technical QA checks (black frames / silence / desync)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.errors import ProviderError
from src.qa.checks import (
    AV_DESYNC_MAX_SEC,
    BLACK_FRAME_MAX_SEC,
    SILENCE_MAX_SEC,
    build_blackdetect_command,
    build_silencedetect_command,
    parse_blackdetect,
    parse_duration,
    parse_silencedetect,
    probe_duration,
    run_checks,
)

# --- realistic ffmpeg/ffprobe stderr fixtures ------------------------------

# ffmpeg writes the container header (incl. Duration) then per-frame
# blackdetect/silencedetect lines to stderr.
BLACKDETECT_STDERR = """\
ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers
  Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':
  Duration: 00:00:12.34, start: 0.000000, bitrate: 512 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 320x180
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono
[Parsed_blackdetect_0 @ 0x55d0] black_start:1.5 black_end:2.5 black_duration:1
[Parsed_blackdetect_0 @ 0x55d0] black_start:5 black_end:5.6 black_duration:0.6
[Parsed_blackdetect_0 @ 0x55d0] black_start:10.5
frame=  370 fps=0.0 q=-0.0 Lsize=N/A time=00:00:12.34 bitrate=N/A speed= 123x
"""

SILENCEDETECT_STDERR = """\
ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers
  Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':
  Duration: 00:00:12.34, start: 0.000000, bitrate: 512 kb/s
[Parsed_silencedetect_0 @ 0x55e0] silence_start: 0
[Parsed_silencedetect_0 @ 0x55e0] silence_end: 4.2 | silence_duration: 4.2
[Parsed_silencedetect_0 @ 0x55e0] silence_start: 7.0
[Parsed_silencedetect_0 @ 0x55e0] silence_end: 8.0 | silence_duration: 1.0
frame=  370 fps=0.0 q=-0.0 Lsize=N/A time=00:00:12.34 bitrate=N/A speed= 123x
"""


# --- parse_duration --------------------------------------------------------


def test_parse_duration_returns_seconds() -> None:
    assert parse_duration(BLACKDETECT_STDERR) == pytest.approx(12.34)


def test_parse_duration_missing_returns_zero() -> None:
    assert parse_duration("no duration line here") == 0.0


def test_parse_duration_multi_hour() -> None:
    assert parse_duration("  Duration: 01:02:03.50, start: 0.0") == pytest.approx(3723.5)


# --- parse_blackdetect -----------------------------------------------------


def test_parse_blackdetect_multiple_frames() -> None:
    frames = parse_blackdetect(BLACKDETECT_STDERR)

    assert len(frames) == 3
    assert frames[0].start_sec == pytest.approx(1.5)
    assert frames[0].end_sec == pytest.approx(2.5)
    assert frames[1].start_sec == pytest.approx(5.0)
    assert frames[1].end_sec == pytest.approx(5.6)


def test_parse_blackdetect_open_ended_uses_duration() -> None:
    frames = parse_blackdetect(BLACKDETECT_STDERR)

    last = frames[-1]
    assert last.start_sec == pytest.approx(10.5)
    # No black_end on that line -> closed at the container Duration.
    assert last.end_sec == pytest.approx(12.34)


def test_parse_blackdetect_open_ended_without_duration_uses_start() -> None:
    frames = parse_blackdetect("black_start:3.0\n")

    assert len(frames) == 1
    assert frames[0].start_sec == pytest.approx(3.0)
    assert frames[0].end_sec == pytest.approx(3.0)


def test_parse_blackdetect_empty_is_empty() -> None:
    assert parse_blackdetect("") == []


def test_parse_blackdetect_same_line_pair() -> None:
    frames = parse_blackdetect("black_start:0 black_end:1.0 black_duration:1.0")

    assert len(frames) == 1
    assert (frames[0].start_sec, frames[0].end_sec) == (0.0, 1.0)


# --- parse_silencedetect ---------------------------------------------------


def test_parse_silencedetect_pairs() -> None:
    silences = parse_silencedetect(SILENCEDETECT_STDERR)

    assert len(silences) == 2
    assert silences[0].start_sec == pytest.approx(0.0)
    assert silences[0].end_sec == pytest.approx(4.2)
    assert silences[1].start_sec == pytest.approx(7.0)
    assert silences[1].end_sec == pytest.approx(8.0)


def test_parse_silencedetect_with_durations_line() -> None:
    stderr = "silence_start: 1.0\nsilence_end: 2.0 | silence_duration: 1.0\n"
    silences = parse_silencedetect(stderr)

    assert len(silences) == 1
    assert silences[0].start_sec == pytest.approx(1.0)
    assert silences[0].end_sec == pytest.approx(2.0)


def test_parse_silencedetect_open_ended_uses_duration() -> None:
    stderr = "Duration: 00:00:09.00, start: 0.0\nsilence_start: 6.5\n"
    silences = parse_silencedetect(stderr)

    assert len(silences) == 1
    assert silences[0].start_sec == pytest.approx(6.5)
    assert silences[0].end_sec == pytest.approx(9.0)


def test_parse_silencedetect_empty_is_empty() -> None:
    assert parse_silencedetect("") == []


# --- command builders ------------------------------------------------------


def test_build_blackdetect_command_shape(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"

    cmd = build_blackdetect_command(video)

    assert cmd == [
        "ffmpeg",
        "-i",
        str(video),
        "-vf",
        "blackdetect=d=0.5:pix_th=0.10",
        "-an",
        "-f",
        "null",
        "-",
    ]


def test_build_silencedetect_command_shape(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"

    cmd = build_silencedetect_command(video)

    assert cmd == [
        "ffmpeg",
        "-i",
        str(video),
        "-af",
        "silencedetect=noise=-50dB:d=0.5",
        "-f",
        "null",
        "-",
    ]


# --- probe_duration --------------------------------------------------------


def test_probe_duration_parses_float(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffprobe")

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(command, 0, stdout="12.34\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert probe_duration(tmp_path / "v.mp4") == pytest.approx(12.34)


def test_probe_duration_blank_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffprobe")

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(command, 0, stdout="\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ProviderError, match="no duration"):
        probe_duration(tmp_path / "v.mp4")


def test_probe_duration_missing_ffprobe_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(ProviderError, match="ffprobe not found"):
        probe_duration(tmp_path / "v.mp4")


# --- run_checks (stubbed subprocess) ---------------------------------------


def test_run_checks_without_ffmpeg_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(ProviderError, match="ffmpeg not found"):
        run_checks(tmp_path / "v.mp4")


def test_run_checks_aggregates_and_flags_issues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/bin")

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        args = " ".join(command)
        if "blackdetect" in args:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr=BLACKDETECT_STDERR)
        if "silencedetect" in args:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr=SILENCEDETECT_STDERR)
        if "format=duration" in args:
            return subprocess.CompletedProcess(command, 0, stdout="12.34\n", stderr="")
        if "v:0" in args:
            return subprocess.CompletedProcess(command, 0, stdout="12.0\n", stderr="")
        if "a:0" in args:
            return subprocess.CompletedProcess(command, 0, stdout="11.0\n", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    checks = run_checks(tmp_path / "v.mp4")

    assert checks.duration_sec == pytest.approx(12.34)
    assert len(checks.black_frames) == 3
    assert len(checks.silences) == 2
    assert checks.av_desync_sec == pytest.approx(1.0)

    # black frame 1.5->2.5 (1.0s) is NOT an issue; 10.5->12.34 is.
    black_issues = [i for i in checks.issues if "black frame" in i]
    assert len(black_issues) == 1
    assert "10.500s" in black_issues[0]

    # silence 0->4.2 (4.2s) is an issue; 7->8 (1.0s) is not.
    silence_issues = [i for i in checks.issues if "silence" in i]
    assert len(silence_issues) == 1
    assert "4.200s" in silence_issues[0]

    desync_issues = [i for i in checks.issues if "desync" in i]
    assert len(desync_issues) == 1


def test_run_checks_clean_video_has_no_issues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/bin")

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        args = " ".join(command)
        if "blackdetect" in args:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if "silencedetect" in args:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if "format=duration" in args:
            return subprocess.CompletedProcess(command, 0, stdout="5.0\n", stderr="")
        if "v:0" in args:
            return subprocess.CompletedProcess(command, 0, stdout="5.0\n", stderr="")
        if "a:0" in args:
            return subprocess.CompletedProcess(command, 0, stdout="4.9\n", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    checks = run_checks(tmp_path / "v.mp4")

    assert checks.issues == []
    assert checks.black_frames == []
    assert checks.silences == []
    assert checks.av_desync_sec == pytest.approx(0.1)


def test_run_checks_no_audio_stream_desync_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/bin")

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        args = " ".join(command)
        if "blackdetect" in args or "silencedetect" in args:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if "format=duration" in args:
            return subprocess.CompletedProcess(command, 0, stdout="5.0\n", stderr="")
        if "v:0" in args:
            return subprocess.CompletedProcess(command, 0, stdout="5.0\n", stderr="")
        if "a:0" in args:
            # No audio stream -> ffprobe emits nothing.
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    checks = run_checks(tmp_path / "v.mp4")

    assert checks.av_desync_sec == 0.0
    assert checks.issues == []


def test_thresholds_are_the_documented_constants() -> None:
    assert BLACK_FRAME_MAX_SEC == 1.0
    assert SILENCE_MAX_SEC == 3.0
    assert AV_DESYNC_MAX_SEC == 0.5


# --- integration (runs on CI where ffmpeg/ffprobe are installed) -----------

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(FFMPEG is None or FFPROBE is None, reason="ffmpeg/ffprobe not installed")
def test_run_checks_integration_finds_black_frame(tmp_path: Path) -> None:
    clip = tmp_path / "black.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:d=1.5",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(clip),
        ],
        check=True,
        capture_output=True,
    )

    checks = run_checks(clip)

    assert checks.black_frames, "expected blackdetect to find the black clip"
    assert checks.duration_sec > 0.0
    # A 1.5s all-black clip yields a black frame longer than the 1.0s threshold.
    assert any("black frame" in issue for issue in checks.issues)
