"""Short derivation: cut a vertical 9:16 clip out of the long video.

The command builder is a *pure function*: it assembles an ``ffmpeg`` argv
without touching the filesystem or the network, so it is fully unit-testable on
machines (like local dev) where ffmpeg is not installed. :func:`render` is the
only side-effecting entry point; :func:`derive_short` ties selection, command
building and rendering together.

Highlight selection is deterministic: :func:`select_highlight` picks the
contiguous run of segments with the greatest summed score that still fits inside
``max_duration_sec``.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.errors import ProviderError

__all__ = [
    "DEFAULT_SHORT_MAX_SEC",
    "Segment",
    "build_vertical_command",
    "derive_short",
    "render",
    "select_highlight",
]

DEFAULT_SHORT_MAX_SEC = 180.0


@dataclass(frozen=True)
class Segment:
    """A candidate highlight spanning ``[start_sec, end_sec]`` in the long video."""

    index: int
    start_sec: float
    end_sec: float
    score: float = 0.0


def select_highlight(
    segments: list[Segment],
    *,
    max_duration_sec: float = DEFAULT_SHORT_MAX_SEC,
) -> tuple[float, float]:
    """Choose the best contiguous window of ``segments`` as a ``(start, end)`` pair.

    ``segments`` are assumed to be in timeline order. The window is the
    contiguous run whose summed ``score`` is maximal subject to its total span
    (``end of last - start of first``) being at most ``max_duration_sec``. Ties
    are broken by the earliest window: the smallest start index first, then the
    earliest end index.

    A segment whose own duration exceeds ``max_duration_sec`` can never be part
    of a feasible window, so it is effectively **excluded** from selection
    rather than trimmed. If no feasible window exists (empty input, or every
    segment is longer than the cap), :class:`ValueError` is raised.
    """
    if not segments:
        raise ValueError("no segments to select a highlight from")

    best_score: float | None = None
    best_span: tuple[float, float] | None = None

    for i, first in enumerate(segments):
        for j in range(i, len(segments)):
            last = segments[j]
            span = last.end_sec - first.start_sec
            if span > max_duration_sec:
                # Extending j only grows the span; stop scanning this start.
                break
            score = sum(seg.score for seg in segments[i : j + 1])
            if best_score is None or score > best_score:
                best_score = score
                best_span = (first.start_sec, last.end_sec)

    if best_span is None:
        raise ValueError(f"no window fits within max_duration_sec={max_duration_sec}")
    return best_span


def build_vertical_command(
    src: Path,
    out: Path,
    *,
    start_sec: float,
    duration_sec: float,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> list[str]:
    """Build an ffmpeg argv that trims ``src`` into a vertical ``width`` x ``height`` clip.

    The ``[start_sec, start_sec + duration_sec]`` span is extracted, scaled up
    preserving aspect ratio, centre-cropped to fill the ``width`` x ``height``
    (9:16) frame, resampled to ``fps`` and encoded as ``libx264`` / ``yuv420p``
    with ``aac`` audio.
    """
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"fps={fps},"
        f"format=yuv420p"
    )
    return [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_sec),
        "-i",
        str(src),
        "-t",
        str(duration_sec),
        "-vf",
        vf,
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
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


def derive_short(
    src: Path,
    out: Path,
    *,
    segments: list[Segment],
    max_duration_sec: float = DEFAULT_SHORT_MAX_SEC,
    **kw: Any,
) -> Path:
    """Select a highlight in ``src`` and render it as a vertical ``out`` clip.

    ``kw`` is forwarded to :func:`build_vertical_command` (``width``,
    ``height``, ``fps``). Returns ``out``.
    """
    start_sec, end_sec = select_highlight(segments, max_duration_sec=max_duration_sec)
    command = build_vertical_command(
        src,
        out,
        start_sec=start_sec,
        duration_sec=end_sec - start_sec,
        **kw,
    )
    render(command)
    return out
