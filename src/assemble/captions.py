"""Captions generator: word timings -> SRT / ASS subtitle files.

This module turns a sequence of per-word timings (as produced by the TTS stage)
into cue-level subtitles and renders them as SRT or ASS. It is a pure module:
no network and no ffmpeg.

The input type :class:`Word` is defined locally so this module has no hard
dependency on the audio/TTS package; anything with matching ``text``,
``start_sec`` and ``end_sec`` attributes can be grouped.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Cue",
    "Word",
    "format_ass_time",
    "format_srt_time",
    "group_words",
    "to_ass",
    "to_srt",
    "write_ass",
    "write_srt",
]

# ASS style line is fixed except for the font face and size.
_ASS_STYLE_TEMPLATE = (
    "Style: Default,{font},{font_size},&H00FFFFFF,&H00000000,&H00000000,"
    "0,0,0,0,100,100,0,0,1,3,1,2,60,60,80,1"
)
_ASS_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
_ASS_EVENTS_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
)


@dataclass(frozen=True)
class Word:
    """A single spoken word with its start and end time in seconds."""

    text: str
    start_sec: float
    end_sec: float


@dataclass(frozen=True)
class Cue:
    """A subtitle cue covering one or more words."""

    start_sec: float
    end_sec: float
    text: str


def _clamp(sec: float) -> float:
    return sec if sec > 0.0 else 0.0


def group_words(
    words: Iterable[Word],
    *,
    max_chars: int = 42,
    max_duration_sec: float = 5.0,
    max_gap_sec: float = 0.8,
) -> list[Cue]:
    """Greedily group consecutive words into cues.

    A new cue starts when adding the next word would push the joined text past
    ``max_chars``, stretch the cue beyond ``max_duration_sec``, or when the silent
    gap between the previous word's end and the next word's start exceeds
    ``max_gap_sec``. A single word longer than ``max_chars`` still forms its own cue.
    """

    cues: list[Cue] = []
    current: list[Word] = []

    for word in words:
        if not current:
            current.append(word)
            continue

        prev = current[-1]
        candidate_len = len(" ".join(w.text for w in current)) + 1 + len(word.text)
        candidate_duration = word.end_sec - current[0].start_sec
        gap = word.start_sec - prev.end_sec

        if candidate_len > max_chars or candidate_duration > max_duration_sec or gap > max_gap_sec:
            cues.append(
                Cue(
                    start_sec=current[0].start_sec,
                    end_sec=prev.end_sec,
                    text=" ".join(w.text for w in current),
                )
            )
            current = [word]
        else:
            current.append(word)

    if current:
        cues.append(
            Cue(
                start_sec=current[0].start_sec,
                end_sec=current[-1].end_sec,
                text=" ".join(w.text for w in current),
            )
        )

    return cues


def format_srt_time(sec: float) -> str:
    """Format seconds as an SRT timestamp ``HH:MM:SS,mmm``."""

    total_ms = int(round(_clamp(sec) * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def format_ass_time(sec: float) -> str:
    """Format seconds as an ASS timestamp ``H:MM:SS.cc`` (centiseconds)."""

    total_cs = int(round(_clamp(sec) * 100))
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    seconds, centis = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def to_srt(cues: list[Cue]) -> str:
    """Render cues as an SRT document."""

    blocks = [
        f"{index}\n"
        f"{format_srt_time(cue.start_sec)} --> {format_srt_time(cue.end_sec)}\n"
        f"{cue.text}"
        for index, cue in enumerate(cues, start=1)
    ]
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def to_ass(
    cues: list[Cue],
    *,
    play_res: tuple[int, int] = (1920, 1080),
    font: str = "Arial",
    font_size: int = 64,
) -> str:
    """Render cues as an ASS (Advanced SubStation Alpha) document."""

    width, height = play_res
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        _ASS_STYLE_FORMAT,
        _ASS_STYLE_TEMPLATE.format(font=font, font_size=font_size),
        "",
        "[Events]",
        _ASS_EVENTS_FORMAT,
    ]
    for cue in cues:
        lines.append(
            "Dialogue: 0,"
            f"{format_ass_time(cue.start_sec)},{format_ass_time(cue.end_sec)},"
            f"Default,,0,0,0,,{cue.text}"
        )
    return "\n".join(lines) + "\n"


def write_srt(cues: list[Cue], path: Path) -> Path:
    """Write cues to ``path`` as SRT and return the path."""

    path = Path(path)
    path.write_text(to_srt(cues), encoding="utf-8")
    return path


def write_ass(cues: list[Cue], path: Path) -> Path:
    """Write cues to ``path`` as ASS and return the path."""

    path = Path(path)
    path.write_text(to_ass(cues), encoding="utf-8")
    return path
