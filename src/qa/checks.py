"""Technical QA checks over a rendered video.

This module inspects an already-produced media file and reports *technical*
defects that a subjective reviewer might miss: fully black frames, stretches of
silence, and audio/video desynchronisation. It shells out to ``ffmpeg``
(``blackdetect`` / ``silencedetect``) and ``ffprobe`` (durations), parses their
textual output, and aggregates everything into a :class:`QaChecks` record with a
human-readable ``issues`` list.

Following the project convention (see :mod:`src.visuals.motion` and
:mod:`src.assemble.ffmpeg`) the parsers and command builders are *pure
functions*, so they are unit-testable on machines where ffmpeg is not
installed. :func:`probe_duration` and :func:`run_checks` are the side-effecting
entry points and raise :class:`ProviderError` when the required binaries are
missing or misbehave.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from src.errors import ProviderError

__all__ = [
    "BlackFrame",
    "QaChecks",
    "Silence",
    "build_blackdetect_command",
    "build_silencedetect_command",
    "parse_blackdetect",
    "parse_duration",
    "parse_silencedetect",
    "probe_duration",
    "run_checks",
]

# A black frame longer than this is reported as an issue.
BLACK_FRAME_MAX_SEC = 1.0
# A silence longer than this is reported as an issue.
SILENCE_MAX_SEC = 3.0
# A/V desync beyond this is reported as an issue.
AV_DESYNC_MAX_SEC = 0.5


class BlackFrame(BaseModel):
    """A detected black stretch, in seconds from the start of the video."""

    start_sec: float
    end_sec: float


class Silence(BaseModel):
    """A detected silent stretch, in seconds from the start of the video."""

    start_sec: float
    end_sec: float


class QaChecks(BaseModel):
    """Aggregated technical QA result for one video."""

    duration_sec: float = 0.0
    black_frames: list[BlackFrame] = Field(default_factory=list)
    silences: list[Silence] = Field(default_factory=list)
    av_desync_sec: float = 0.0
    issues: list[str] = Field(default_factory=list)


_BLACK_START_RE = re.compile(r"black_start:\s*(-?\d+(?:\.\d+)?)")
_BLACK_END_RE = re.compile(r"black_end:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def parse_duration(stderr: str) -> float:
    """Parse an ffmpeg ``Duration: HH:MM:SS.ss,`` line into seconds.

    Returns ``0.0`` when no duration line is present.
    """
    match = _DURATION_RE.search(stderr)
    if match is None:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_blackdetect(stderr: str) -> list[BlackFrame]:
    """Parse ``black_start:``/``black_end:`` pairs from ffmpeg ``blackdetect``.

    Multiple pairs (one per line or several on a line) are tolerated. An
    open-ended ``black_start`` with no matching ``black_end`` (a video that ends
    while still black) is closed using the stream ``Duration`` parsed from the
    same output, falling back to the start value when no duration is known.
    """
    frames: list[BlackFrame] = []
    duration = parse_duration(stderr)
    for line in stderr.splitlines():
        start_match = _BLACK_START_RE.search(line)
        if start_match is None:
            continue
        start = float(start_match.group(1))
        end_match = _BLACK_END_RE.search(line)
        if end_match is not None:
            end = float(end_match.group(1))
        else:
            end = duration if duration > 0.0 else start
        frames.append(BlackFrame(start_sec=start, end_sec=end))
    return frames


def parse_silencedetect(stderr: str) -> list[Silence]:
    """Parse ``silence_start:``/``silence_end:`` lines from ``silencedetect``.

    ``silence_start`` and ``silence_end`` are typically emitted on separate
    lines. An open-ended silence (no matching end) is closed using the stream
    ``Duration`` when available, otherwise it is closed at its start.
    """
    silences: list[Silence] = []
    duration = parse_duration(stderr)
    pending_start: float | None = None
    for line in stderr.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match is not None:
            pending_start = float(start_match.group(1))
        end_match = _SILENCE_END_RE.search(line)
        if end_match is not None:
            end = float(end_match.group(1))
            start = pending_start if pending_start is not None else 0.0
            silences.append(Silence(start_sec=start, end_sec=end))
            pending_start = None
    if pending_start is not None:
        end = duration if duration > 0.0 else pending_start
        silences.append(Silence(start_sec=pending_start, end_sec=end))
    return silences


def build_blackdetect_command(video: Path) -> list[str]:
    """Build an ffmpeg argv that reports black frames to stderr."""
    return [
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


def build_silencedetect_command(video: Path) -> list[str]:
    """Build an ffmpeg argv that reports silent stretches to stderr."""
    return [
        "ffmpeg",
        "-i",
        str(video),
        "-af",
        "silencedetect=noise=-50dB:d=0.5",
        "-f",
        "null",
        "-",
    ]


def _require(binary: str) -> None:
    """Raise :class:`ProviderError` if ``binary`` is not on ``PATH``."""
    if shutil.which(binary) is None:
        raise ProviderError(f"{binary} not found")


def probe_duration(video: Path) -> float:
    """Return the container duration in seconds via ``ffprobe``.

    Raises :class:`ProviderError` when ffprobe is missing, exits non-zero, or
    reports a blank/non-numeric duration.
    """
    _require("ffprobe")
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        str(video),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise ProviderError(f"ffprobe failed: {result.stderr or result.returncode}")
    text = (result.stdout or "").strip()
    if not text:
        raise ProviderError(f"ffprobe returned no duration for {video}")
    try:
        return float(text)
    except ValueError as exc:
        raise ProviderError(f"ffprobe returned a non-numeric duration: {text!r}") from exc


def _probe_stream_duration(video: Path, stream: str) -> float | None:
    """Return the duration of stream ``stream`` (e.g. ``"v:0"``) in seconds.

    Returns ``None`` when the stream is absent or its duration is unknown.
    """
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        stream,
        "-show_entries",
        "stream=duration",
        "-of",
        "default=nw=1:nk=1",
        str(video),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line or line == "N/A":
            continue
        try:
            return float(line)
        except ValueError:
            continue
    return None


def _detect(command: list[str]) -> str:
    """Run a detect command and return its stderr text."""
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise ProviderError(f"ffmpeg check failed: {result.stderr or result.returncode}")
    return result.stderr or ""


def run_checks(video: Path) -> QaChecks:
    """Run every technical check over ``video`` and aggregate the results.

    Detects black frames and silence by parsing ffmpeg stderr, probes the
    container duration with ffprobe, and computes A/V desync as the absolute
    difference between the first video and audio stream durations (``0.0`` when
    there is no audio stream). Appends a human-readable entry to ``issues`` for
    any black frame longer than :data:`BLACK_FRAME_MAX_SEC`, any silence longer
    than :data:`SILENCE_MAX_SEC`, and any desync beyond :data:`AV_DESYNC_MAX_SEC`.
    """
    _require("ffmpeg")
    _require("ffprobe")

    black_frames = parse_blackdetect(_detect(build_blackdetect_command(video)))
    silences = parse_silencedetect(_detect(build_silencedetect_command(video)))
    duration = probe_duration(video)

    video_duration = _probe_stream_duration(video, "v:0")
    audio_duration = _probe_stream_duration(video, "a:0")
    if audio_duration is None or video_duration is None:
        av_desync = 0.0
    else:
        av_desync = abs(video_duration - audio_duration)

    issues: list[str] = []
    for frame in black_frames:
        if frame.end_sec - frame.start_sec > BLACK_FRAME_MAX_SEC:
            issues.append(
                f"black frame from {frame.start_sec:.3f}s to {frame.end_sec:.3f}s "
                f"exceeds {BLACK_FRAME_MAX_SEC:.1f}s"
            )
    for silence in silences:
        if silence.end_sec - silence.start_sec > SILENCE_MAX_SEC:
            issues.append(
                f"silence from {silence.start_sec:.3f}s to {silence.end_sec:.3f}s "
                f"exceeds {SILENCE_MAX_SEC:.1f}s"
            )
    if av_desync > AV_DESYNC_MAX_SEC:
        issues.append(f"A/V desync {av_desync:.3f}s exceeds {AV_DESYNC_MAX_SEC:.1f}s")

    return QaChecks(
        duration_sec=duration,
        black_frames=black_frames,
        silences=silences,
        av_desync_sec=av_desync,
        issues=issues,
    )
