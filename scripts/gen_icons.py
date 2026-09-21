"""Generate the PWA icons (stdlib only): docs/icons/icon-192.png, icon-512.png, icon-maskable-512.png.

Design: a green tile with three white bars of decreasing length (a "sort" glyph).
Run: python scripts/gen_icons.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "icons"
BG = (21, 122, 60)
FG = (255, 255, 255)


def _png(width: int, height: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _in_round_rect(x: float, y: float, x0: float, y0: float, x1: float, y1: float, r: float) -> bool:
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size: int, maskable: bool) -> bytes:
    s = float(size)
    # Glyph lives in the central safe zone (maskable icons may be cropped to a circle of ~80%).
    box = 0.56 if maskable else 0.60
    left = s * (1 - box) / 2
    span = s * box
    bar_h = span * 0.16
    gap = span * 0.20
    total = 3 * bar_h + 2 * gap
    top = (s - total) / 2
    lengths = (1.0, 0.72, 0.44)
    bars = [
        (left, top + i * (bar_h + gap), left + span * ln, top + i * (bar_h + gap) + bar_h)
        for i, ln in enumerate(lengths)
    ]
    corner = 0 if maskable else s * 0.22
    ss = 3
    pixels = bytearray()
    for py in range(size):
        for px in range(size):
            r_acc = g_acc = b_acc = a_acc = 0
            for sy in range(ss):
                for sx in range(ss):
                    x = px + (sx + 0.5) / ss
                    y = py + (sy + 0.5) / ss
                    if maskable or _in_round_rect(x, y, 0, 0, s, s, corner):
                        colour = BG
                        for (x0, y0, x1, y1) in bars:
                            if _in_round_rect(x, y, x0, y0, x1, y1, bar_h / 2):
                                colour = FG
                                break
                        r_acc += colour[0]; g_acc += colour[1]; b_acc += colour[2]; a_acc += 255
            n = ss * ss
            if a_acc == 0:
                pixels += b"\x00\x00\x00\x00"
            else:
                cov = a_acc // 255
                pixels += bytes((r_acc // cov, g_acc // cov, b_acc // cov, a_acc // n))
    return _png(size, size, bytes(pixels))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, maskable in (
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
    ):
        (OUT / name).write_bytes(render(size, maskable))
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
