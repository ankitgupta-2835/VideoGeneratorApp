"""Task 3.6 tests: Ken Burns / parallax motion via FFmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.errors import ProviderError
from src.visuals.motion import (
    build_kenburns_command,
    build_parallax_command,
    render,
)

# --- command builders (pure, no ffmpeg needed) -----------------------------


def test_build_kenburns_command_shape(tmp_path: Path) -> None:
    image = tmp_path / "in.png"
    out = tmp_path / "out.mp4"

    cmd = build_kenburns_command(image, out, duration_sec=2.5, fps=30)

    assert cmd[0] == "ffmpeg"
    assert "-loop" in cmd
    assert str(image) in cmd
    assert "-t" in cmd
    assert "2.5" in cmd
    assert any("zoompan" in part for part in cmd)
    assert "-r" in cmd
    assert "30" in cmd
    assert cmd[-1] == str(out)
    assert "-c:v" in cmd
    assert "libx264" in cmd
    assert "yuv420p" in cmd


def test_build_kenburns_direction_differs(tmp_path: Path) -> None:
    image = tmp_path / "in.png"
    out = tmp_path / "out.mp4"

    zoom_in = build_kenburns_command(image, out, duration_sec=2.0, direction="in")
    zoom_out = build_kenburns_command(image, out, duration_sec=2.0, direction="out")

    assert zoom_in != zoom_out
    assert "min(zoom+" in zoom_in[zoom_in.index("-vf") + 1]
    assert "max(zoom-" in zoom_out[zoom_out.index("-vf") + 1]


def test_build_kenburns_rejects_bad_direction(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_kenburns_command(
            tmp_path / "in.png", tmp_path / "out.mp4", duration_sec=1.0, direction="sideways"
        )


def test_build_parallax_command_shape(tmp_path: Path) -> None:
    image = tmp_path / "in.png"
    out = tmp_path / "out.mp4"

    cmd = build_parallax_command(image, out, duration_sec=3.0, shift_px=40)

    vf = cmd[cmd.index("-vf") + 1]
    assert "crop" in vf
    assert "zoompan" in vf
    assert "40" in vf  # the x shift is expressed in the filter chain
    assert str(out) == cmd[-1]
    assert "-loop" in cmd
    assert str(image) in cmd


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


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_kenburns_integration(tmp_path: Path) -> None:
    still = tmp_path / "in.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=640x360",
            "-frames:v",
            "1",
            str(still),
        ],
        check=True,
        capture_output=True,
    )
    assert still.exists()

    out = tmp_path / "kenburns.mp4"
    cmd = build_kenburns_command(still, out, duration_sec=1.0, fps=30)
    render(cmd)

    assert out.exists()
    assert out.stat().st_size > 0
