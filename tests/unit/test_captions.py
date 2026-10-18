"""Task 3.2 tests: captions generator (word timings -> SRT / ASS)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.assemble.captions import (
    Cue,
    Word,
    format_ass_time,
    format_srt_time,
    group_words,
    to_ass,
    to_srt,
    write_ass,
    write_srt,
)

# A fixed fixture shared by the golden-file tests so the goldens are reproducible
# byte-for-byte. Words one through seven form the first cue; the 2.0s silent gap
# before "Second" forces a second cue under the default settings.
GOLDEN_WORDS = [
    Word("Hello", 0.00, 0.40),
    Word("world,", 0.45, 0.90),
    Word("this", 0.95, 1.25),
    Word("is", 1.30, 1.55),
    Word("a", 1.60, 1.75),
    Word("captions", 1.80, 2.40),
    Word("test.", 2.45, 3.00),
    Word("Second", 5.00, 5.50),
    Word("cue", 5.55, 5.90),
    Word("starts", 5.95, 6.40),
    Word("here.", 6.45, 7.00),
]

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden" / "captions"


# --- time formatters -------------------------------------------------------


def test_format_srt_time() -> None:
    assert format_srt_time(65.5) == "00:01:05,500"
    assert format_srt_time(0.0) == "00:00:00,000"
    assert format_srt_time(3661.25) == "01:01:01,250"


def test_format_ass_time() -> None:
    assert format_ass_time(65.5) == "0:01:05.50"
    assert format_ass_time(0.0) == "0:00:00.00"
    assert format_ass_time(3661.25) == "1:01:01.25"


@pytest.mark.parametrize(
    ("sec", "srt", "ass"),
    [
        (1.9996, "00:00:02,000", "0:00:02.00"),
        (59.9996, "00:01:00,000", "0:01:00.00"),
        (0.001, "00:00:00,001", "0:00:00.00"),
    ],
)
def test_time_formatters_round_and_carry(sec: float, srt: str, ass: str) -> None:
    assert format_srt_time(sec) == srt
    assert format_ass_time(sec) == ass


# --- grouping --------------------------------------------------------------


def test_group_single_word_is_one_cue() -> None:
    cues = group_words([Word("Solo", 1.0, 1.5)])
    assert cues == [Cue(start_sec=1.0, end_sec=1.5, text="Solo")]


def test_group_empty_returns_empty() -> None:
    assert group_words([]) == []


def test_group_long_gap_splits_cues() -> None:
    words = [
        Word("first", 0.0, 0.5),
        Word("cue", 0.5, 0.8),
        Word("second", 5.0, 5.5),  # gap of 4.2s > default 0.8s
    ]
    cues = group_words(words)
    assert len(cues) == 2
    assert cues[0].text == "first cue"
    assert cues[1].text == "second"
    assert cues[1].start_sec == 5.0


def test_group_max_chars_splits_cues() -> None:
    words = [
        Word("aaaaa", 0.0, 0.2),
        Word("bbbbb", 0.2, 0.4),
        Word("ccccc", 0.4, 0.6),
    ]
    cues = group_words(words, max_chars=11)
    # "aaaaa bbbbb" is 11 chars; adding "ccccc" (17) would exceed the limit.
    assert [c.text for c in cues] == ["aaaaa bbbbb", "ccccc"]


def test_group_max_duration_splits_cues() -> None:
    words = [
        Word("one", 0.0, 1.0),
        Word("two", 1.0, 2.0),
        Word("three", 2.0, 6.0),  # pushes the cue to 6.0s > 5.0s default
    ]
    cues = group_words(words, max_duration_sec=5.0)
    assert [c.text for c in cues] == ["one two", "three"]
    assert cues[1].end_sec == 6.0


def test_group_keeps_words_that_fit() -> None:
    words = [
        Word("a", 0.0, 0.2),
        Word("b", 0.25, 0.4),
        Word("c", 0.45, 0.6),
    ]
    cues = group_words(words)
    assert len(cues) == 1
    assert cues[0].text == "a b c"


# --- SRT rendering ---------------------------------------------------------


def test_to_srt_block_count_and_format() -> None:
    cues = [
        Cue(start_sec=0.0, end_sec=1.0, text="Hello world"),
        Cue(start_sec=1.5, end_sec=2.25, text="Second line"),
    ]
    out = to_srt(cues)
    assert out == (
        "1\n"
        "00:00:00,000 --> 00:00:01,000\n"
        "Hello world\n"
        "\n"
        "2\n"
        "00:00:01,500 --> 00:00:02,250\n"
        "Second line\n"
    )
    assert out.count("-->") == 2


def test_to_srt_empty() -> None:
    assert to_srt([]) == ""


# --- ASS rendering ---------------------------------------------------------


def test_to_ass_structure_and_one_dialogue_per_cue() -> None:
    cues = [
        Cue(start_sec=0.0, end_sec=1.0, text="Hello world"),
        Cue(start_sec=1.5, end_sec=2.25, text="Second line"),
    ]
    out = to_ass(cues)
    assert "[Script Info]" in out
    assert "[V4+ Styles]" in out
    assert "[Events]" in out
    assert "PlayResX: 1920" in out
    assert "PlayResY: 1080" in out
    assert "Style: Default,Arial,64," in out
    dialogue_lines = [line for line in out.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue_lines) == len(cues)
    assert dialogue_lines[0] == ("Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hello world")


def test_to_ass_honours_play_res_and_font() -> None:
    out = to_ass([], play_res=(1280, 720), font="DejaVu Sans", font_size=48)
    assert "PlayResX: 1280" in out
    assert "PlayResY: 720" in out
    assert "Style: Default,DejaVu Sans,48," in out


# --- writers ---------------------------------------------------------------


def test_write_srt_and_ass(tmp_path: Path) -> None:
    cues = [Cue(start_sec=0.0, end_sec=1.0, text="Hi")]
    srt_path = write_srt(cues, tmp_path / "out.srt")
    ass_path = write_ass(cues, tmp_path / "out.ass")
    assert srt_path.read_text(encoding="utf-8") == to_srt(cues)
    assert ass_path.read_text(encoding="utf-8") == to_ass(cues)


# --- golden files ----------------------------------------------------------


def test_to_srt_matches_golden() -> None:
    cues = group_words(GOLDEN_WORDS)
    expected = (GOLDEN_DIR / "sample.srt").read_text(encoding="utf-8")
    assert to_srt(cues) == expected


def test_to_ass_matches_golden() -> None:
    cues = group_words(GOLDEN_WORDS)
    expected = (GOLDEN_DIR / "sample.ass").read_text(encoding="utf-8")
    assert to_ass(cues) == expected
