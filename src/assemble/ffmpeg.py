"""FFmpeg assembly: normalize, concatenate and mix clips into a final video.

The command builders are *pure functions*: they assemble an ``ffmpeg`` argv
without touching the filesystem or the network, so they are fully unit-testable
on machines (like local dev) where ffmpeg is not installed. :func:`render` is
the only generic side-effecting entry point; :func:`assemble` orchestrates the
whole normalize -> concat -> mix pipeline and calls :func:`render` at each
stage.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.errors import ProviderError

__all__ = [
    "assemble",
    "build_concat_command",
    "build_mix_command",
    "build_normalize_command",
    "render",
]


def build_normalize_command(
    clip: Path,
    out: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> list[str]:
    """Build an ffmpeg argv that scales/pads ``clip`` to a fixed frame format.

    The clip is letterboxed (aspect ratio preserved) onto a ``width`` x
    ``height`` black canvas, resampled to ``fps`` and forced to ``yuv420p`` so
    that every clip shares a pixel format before concatenation. Video only
    (``-an``).
    """
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={fps},"
        f"format=yuv420p"
    )
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(clip),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-an",
        "-r",
        str(fps),
        str(out),
    ]


def build_concat_command(clips: list[Path], out: Path, list_file: Path) -> list[str]:
    """Build an ffmpeg argv that concatenates ``clips`` via the concat demuxer.

    The list of clips is supplied through ``list_file`` (written by
    :func:`assemble`); the streams are copied without re-encoding.
    """
    return [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(out),
    ]


def build_mix_command(
    video: Path,
    out: Path,
    *,
    narration: Path | None = None,
    music: Path | None = None,
    music_volume_db: float = -18.0,
    target_lufs: float = -14.0,
) -> list[str]:
    """Build an ffmpeg argv that mixes narration/music onto ``video``.

    Audio inputs (if any) are mixed with ``amix`` (music attenuated by
    ``music_volume_db``) and normalized to ``target_lufs`` with ``loudnorm``.
    The video stream is passed through unchanged. With no audio inputs the
    video is simply remuxed.
    """
    command = ["ffmpeg", "-y", "-i", str(video)]

    has_narration = narration is not None
    has_music = music is not None

    if has_narration:
        command += ["-i", str(narration)]
    if has_music:
        # narration occupies input 1 when present, music follows it.
        music_index = 2 if has_narration else 1
        command += ["-i", str(music)]

    if not has_narration and not has_music:
        return [*command, "-map", "0:v", "-c:v", "copy", str(out)]

    parts: list[str] = []
    if has_narration and has_music:
        parts.append("[1:a]volume=1.0[narr]")
        parts.append(f"[{music_index}:a]volume={music_volume_db}dB[mus]")
        parts.append("[narr][mus]amix=inputs=2:duration=longest:normalize=0[a_mixed]")
        mixed = "[a_mixed]"
    elif has_narration:
        parts.append("[1:a]anull[a_mixed]")
        mixed = "[a_mixed]"
    else:  # music only
        parts.append(f"[1:a]volume={music_volume_db}dB[a_mixed]")
        mixed = "[a_mixed]"

    # Trim trailing ';' is unnecessary; join cleanly.
    parts.append(f"{mixed}loudnorm=I={target_lufs}[aout]")
    filter_complex = ";".join(parts)

    return [
        *command,
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
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


def assemble(
    clips: list[Path],
    out: Path,
    work_dir: Path,
    *,
    narration: Path | None = None,
    music: Path | None = None,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> Path:
    """Normalize ``clips``, concatenate them and mix narration/music onto them.

    Each clip is normalized into ``work_dir``; a concat list file is written and
    consumed by the concat demuxer. When ``narration`` and/or ``music`` is
    supplied the concatenated video is mixed to ``-14 LUFS``; otherwise it is
    returned as the final output. Returns the final video path.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    normalized: list[Path] = []
    for index, clip in enumerate(clips):
        norm = work_dir / f"norm_{index:04d}.mp4"
        render(build_normalize_command(clip, norm, width=width, height=height, fps=fps))
        normalized.append(norm)

    list_file = work_dir / "concat.txt"
    list_file.write_text(
        "".join(f"file '{clip.resolve()}'\n" for clip in normalized),
        encoding="utf-8",
    )

    concatenated = work_dir / "concat.mp4"
    render(build_concat_command(normalized, concatenated, list_file))

    if narration is not None or music is not None:
        render(
            build_mix_command(
                concatenated,
                out,
                narration=narration,
                music=music,
            )
        )
        return out

    shutil.move(str(concatenated), str(out))
    return out
