"""Task 3.10 tests: FFmpeg assembly (normalize / concat / mix / LUFS)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.assemble.ffmpeg import (
    assemble,
    build_concat_command,
    build_mix_command,
    build_normalize_command,
    render,
)
from src.errors import ProviderError

# --- command builders (pure, no ffmpeg needed) -----------------------------


def test_build_normalize_command_shape(tmp_path: Path) -> None:
    clip = tmp_path / "in.mp4"
    out = tmp_path / "norm.mp4"

    cmd = build_normalize_command(clip, out, width=1920, height=1080, fps=30)

    assert cmd[0] == "ffmpeg"
    assert str(clip) in cmd
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1920:1080" in vf
    assert "pad=" in vf
    assert "fps=30" in vf
    assert "yuv420p" in vf
    assert "-an" in cmd
    assert cmd[-1] == str(out)


def test_build_normalize_command_custom_dimensions(tmp_path: Path) -> None:
    cmd = build_normalize_command(
        tmp_path / "in.mp4", tmp_path / "o.mp4", width=640, height=360, fps=24
    )
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=640:360" in vf
    assert "pad=640:360" in vf
    assert "fps=24" in vf
    assert cmd[cmd.index("-r") + 1] == "24"


def test_build_concat_command_shape(tmp_path: Path) -> None:
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    list_file = tmp_path / "concat.txt"
    out = tmp_path / "out.mp4"

    cmd = build_concat_command(clips, out, list_file)

    assert cmd[0] == "ffmpeg"
    assert "-f" in cmd and cmd[cmd.index("-f") + 1] == "concat"
    assert "-safe" in cmd and cmd[cmd.index("-safe") + 1] == "0"
    assert str(list_file) in cmd
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1] == str(out)


def test_build_mix_command_with_narration_and_music(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    narration = tmp_path / "n.wav"
    music = tmp_path / "m.mp3"
    out = tmp_path / "mixed.mp4"

    cmd = build_mix_command(video, out, narration=narration, music=music, music_volume_db=-18.0)

    assert str(video) in cmd
    assert str(narration) in cmd
    assert str(music) in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "amix" in fc
    assert "volume=" in fc
    assert "-18.0dB" in fc
    assert "loudnorm" in fc
    assert "I=-14.0" in fc
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "aac"
    assert "-shortest" in cmd
    assert cmd[-1] == str(out)


def test_build_mix_command_without_audio_has_no_filter(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    out = tmp_path / "out.mp4"

    cmd = build_mix_command(video, out)

    assert "-filter_complex" not in cmd
    assert cmd[-1] == str(out)
    assert str(video) in cmd


def test_build_mix_command_music_only_uses_volume(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    music = tmp_path / "m.mp3"
    out = tmp_path / "out.mp4"

    cmd = build_mix_command(video, out, music=music, music_volume_db=-12.0)

    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "volume=" in fc
    assert "-12.0dB" in fc
    assert "loudnorm" in fc
    assert "amix" not in fc  # single audio input, nothing to mix


# --- render (ffmpeg presence / failure handling) ---------------------------


def test_render_without_ffmpeg_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(ProviderError, match="ffmpeg not found"):
        render(["ffmpeg", "-i", "x", str(tmp_path / "out.mp4")])


def test_render_runs_and_checks_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = tmp_path / "out.mp4"
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        captured["command"] = command
        captured["kwargs"] = kwargs
        Path(command[-1]).write_bytes(b"fake-mp4")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(subprocess, "run", fake_run)

    render(["ffmpeg", "-i", "x", str(out)])

    assert out.exists() and out.stat().st_size > 0
    assert captured["command"] == ["ffmpeg", "-i", "x", str(out)]
    assert captured["kwargs"] == {"check": True, "capture_output": True}


def test_render_failure_raises_provider_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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


# --- integration (runs on CI where ffmpeg is installed) --------------------

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _tiny_clip(path: Path, color: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x180:d=1",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_assemble_integration(tmp_path: Path) -> None:
    clips = []
    for color in ("red", "green", "blue"):
        clip = tmp_path / f"{color}.mp4"
        _tiny_clip(clip, color)
        assert clip.exists() and clip.stat().st_size > 0
        clips.append(clip)

    out = tmp_path / "final.mp4"
    result = assemble(clips, out, tmp_path / "work")

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0

    if FFPROBE is not None:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(out),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        duration = float(probe.stdout.strip())
        assert duration >= 2.5
