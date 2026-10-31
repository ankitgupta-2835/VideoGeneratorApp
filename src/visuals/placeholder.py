"""Deterministic local placeholder images (no network, no Pillow).

Free image providers throttle hard (Pollinations allows roughly one image per
45 seconds per IP). When every remote attempt for a scene fails, the visual
director writes one of these instead so the run still assembles a complete
video rather than dying with ``No files to concat``.

The image is a vertical gradient tinted from the seed, so scenes remain
visually distinct across a run.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

__all__ = ["write_placeholder"]

#: (top, bottom) RGB pairs; the seed picks one.
_PALETTES: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((26, 34, 72), (7, 10, 26)),
    ((72, 26, 52), (20, 7, 24)),
    ((18, 62, 54), (6, 20, 18)),
    ((68, 50, 16), (22, 15, 5)),
)


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def write_placeholder(
    path: Path,
    *,
    width: int = 1280,
    height: int = 720,
    seed: str = "",
) -> Path:
    """Write a gradient PNG at ``path`` and return it."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    top, bottom = _PALETTES[digest[0] % len(_PALETTES)]
    # Small deterministic brightness shift so near-identical prompts differ.
    shift = digest[1] % 24 - 12

    def tint(color: tuple[int, int, int]) -> tuple[int, int, int]:
        return (
            max(0, min(255, color[0] + shift)),
            max(0, min(255, color[1] + shift)),
            max(0, min(255, color[2] + shift)),
        )

    top = tint(top)
    bottom = tint(bottom)

    rows = bytearray()
    denominator = max(1, height - 1)
    for y in range(height):
        t = y / denominator
        rgb = bytes(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        rows.append(0)  # filter type: none
        rows.extend(rgb * width)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + _chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path
