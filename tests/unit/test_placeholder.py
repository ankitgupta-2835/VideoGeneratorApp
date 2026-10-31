"""Placeholder image writer tests (pure stdlib, no ffmpeg)."""

from __future__ import annotations

from pathlib import Path

from src.visuals.placeholder import write_placeholder


def test_writes_a_valid_png_of_the_requested_size(tmp_path: Path):
    path = write_placeholder(tmp_path / "nested" / "p.png", width=64, height=32, seed="scene 1")

    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(data[16:20], "big") == 64
    assert int.from_bytes(data[20:24], "big") == 32


def test_seed_changes_the_image(tmp_path: Path):
    first = write_placeholder(tmp_path / "a.png", width=8, height=8, seed="alpha").read_bytes()
    second = write_placeholder(tmp_path / "b.png", width=8, height=8, seed="beta").read_bytes()

    assert first != second
