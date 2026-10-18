"""Motion effects for still images via FFmpeg (Ken Burns zoom, parallax pan).

The command builders are *pure functions*: they assemble an ``ffmpeg`` argv
without ever touching the filesystem or the network, which makes them fully
unit-testable on machines (like local dev) where ffmpeg is not installed.
:func:`render` is the only side-effecting entry point; it shells out to ffmpeg
and raises :class:`ProviderError` when the binary is missing or the render
fails.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.errors import ProviderError

__all__ = [
    "build_kenburns_command",
    "build_parallax_command",
    "render",
]


def _frames(duration_sec: float, fps: int) -> int:
    """Number of output frames for a clip of ``duration_sec`` at ``fps``."""
    return max(1, round(duration_sec * fps))


def build_kenburns_command(
    image: Path,
    out: Path,
    *,
    duration_sec: float,
    fps: int = 30,
    width: int = 1920,
    height: int = 1080,
    zoom: float = 0.15,
    direction: str = "in",
) -> list[str]:
    """Build an ffmpeg argv that loops ``image`` and applies a slow Ken Burns zoom.

    ``direction`` is ``"in"`` (zoom toward the frame) or ``"out"`` (start zoomed
    and pull back). ``zoom`` is the total zoom delta over the clip.
    """
    if direction not in ("in", "out"):
        raise ValueError(f"direction must be 'in' or 'out', got {direction!r}")

    frames = _frames(duration_sec, fps)
    step = zoom / frames
    max_zoom = 1.0 + zoom

    if direction == "in":
        z_expr = f"min(zoom+{step:.6f},{max_zoom:.6f})"
    else:
        z_expr = f"if(eq(on,0),{max_zoom:.6f},max(zoom-{step:.6f},1.0))"

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"zoompan=z='{z_expr}':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )
    return [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-t",
        str(duration_sec),
        "-r",
        str(fps),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]


def build_parallax_command(
    image: Path,
    out: Path,
    *,
    duration_sec: float,
    fps: int = 30,
    width: int = 1920,
    height: int = 1080,
    shift_px: int = 40,
) -> list[str]:
    """Build an ffmpeg argv that loops ``image`` and pans it horizontally.

    The frame is scaled slightly wider than the output so there is room to slide
    by ``shift_px`` pixels across the clip, giving a subtle parallax pan.
    """
    frames = _frames(duration_sec, fps)
    scale_w = width + shift_px
    vf = (
        f"scale={scale_w}:{height}:force_original_aspect_ratio=increase,"
        f"crop={scale_w}:{height},"
        f"zoompan=z=1.0:d={frames}:"
        f"x='min({shift_px}*on/{frames},{shift_px})':y='ih/2-(ih/zoom/2)':"
        f"s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )
    return [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-t",
        str(duration_sec),
        "-r",
        str(fps),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]


def render(command: list[str]) -> None:
    """Run an ffmpeg argv produced by a builder.

    Raises :class:`ProviderError` if ffmpeg is not installed, if the process
    exits non-zero (bundling stderr), or if the expected output file is missing
    afterwards.
    """
    if shutil.which("ffmpeg") is None:
        raise ProviderError("ffmpeg not found")

    try:
        subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise ProviderError(f"ffmpeg failed: {stderr or exc}") from exc

    out_path = Path(command[-1])
    if not out_path.exists():
        raise ProviderError(f"ffmpeg did not produce output: {out_path}")
