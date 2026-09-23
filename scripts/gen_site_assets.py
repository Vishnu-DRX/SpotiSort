#!/usr/bin/env python3
"""Generate SpotiSort's favicon set + Open Graph card, stdlib only (no Pillow / cairo).

Draws a small original mark (NOT the Spotify logo/wordmark): a rounded square in the brand green
(#1DB954) with a white upward "sort" chevron stack, matching docs/assets/shell.js's inline SVG mark.
Writes a tiny hand-rolled PNG encoder (raw scanlines + zlib, no external deps) since only the
standard library is allowed.

Outputs (relative to docs/):
  assets/favicon.svg                  - the mark, for <link rel="icon" type="image/svg+xml">
  icons/favicon-32.png                - 32x32
  icons/icon-180.png                  - 180x180 (apple-touch-icon)
  icons/icon-192.png                  - 192x192 (manifest, "any")
  icons/icon-512.png                  - 512x512 (manifest, "any")
  icons/icon-maskable-512.png         - 512x512 with safe-zone padding (manifest, "maskable")
  assets/og.png                       - 1200x630 Open Graph / Twitter card, mark + tagline

Run: python scripts/gen_site_assets.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

GREEN = (29, 185, 84)
GREEN_DARK = (22, 156, 70)
INK = (18, 18, 18)
WHITE = (255, 255, 255)


# --------------------------------------------------------------------------------------- PNG writer
def write_png(path: Path, width: int, height: int, pixels: list[tuple[int, int, int]]) -> None:
    """pixels: flat row-major list of (r, g, b), length width*height."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (none) per scanline
        row = pixels[y * width:(y + 1) * width]
        for r, g, b in row:
            raw += bytes((r, g, b))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit, RGB truecolor
    idat = zlib.compress(bytes(raw), 9)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


# --------------------------------------------------------------------------------------- shape helpers
def rounded_rect_mask(x: int, y: int, w: int, h: int, r: int) -> bool:
    if 0 <= x < w and 0 <= y < h:
        cx = min(max(x, r), w - 1 - r)
        cy = min(max(y, r), h - 1 - r)
        if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
            return True
        # inside the non-corner band
        if r <= x <= w - 1 - r or r <= y <= h - 1 - r:
            return True
    return False


def dist_to_segment(px, py, ax, ay, bx, by):
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    ab2 = abx * abx + aby * aby
    t = 0.0 if ab2 == 0 else max(0.0, min(1.0, (apx * abx + apy * aby) / ab2))
    cx, cy = ax + t * abx, ay + t * aby
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def draw_mark(size: int, margin_frac: float = 0.0) -> list[tuple[int, int, int]]:
    """The rounded-square-with-chevrons mark, `margin_frac` shrinks the square for maskable safe zones."""
    px = [WHITE] * (size * size)  # transparent-ish background not needed; PNG is RGB (no alpha) for icons
    m = int(size * margin_frac)
    inner = size - 2 * m
    r = max(2, int(inner * 0.28))
    thick = max(2, inner * 0.11)
    for y in range(size):
        for x in range(size):
            lx, ly = x - m, y - m
            if rounded_rect_mask(lx, ly, inner, inner, r):
                color = GREEN
                # two chevrons, echoing the inline SVG mark in shell.js
                for band, dim in ((0.62, 1.0), (0.40, 0.55)):
                    apex_y = inner * (band - 0.16)
                    ax, ay = inner * 0.28, inner * band
                    bx, by = inner * 0.5, apex_y
                    cx_, cy_ = inner * 0.72, inner * band
                    d = min(dist_to_segment(lx, ly, ax, ay, bx, by), dist_to_segment(lx, ly, bx, by, cx_, cy_))
                    if d <= thick:
                        if dim < 1.0:
                            color = tuple(int(GREEN[i] + (INK[i] - GREEN[i]) * (1 - dim) * 0.55) for i in range(3))
                        else:
                            color = INK
                        break
                px[y * size + x] = color
            else:
                px[y * size + x] = WHITE
    return px


FONT3X5 = {
    "A": ["111", "101", "111", "101", "101"], "B": ["110", "101", "110", "101", "110"],
    "C": ["111", "100", "100", "100", "111"], "D": ["110", "101", "101", "101", "110"],
    "E": ["111", "100", "111", "100", "111"], "F": ["111", "100", "111", "100", "100"],
    "G": ["111", "100", "101", "101", "111"], "H": ["101", "101", "111", "101", "101"],
    "I": ["111", "010", "010", "010", "111"], "K": ["101", "110", "100", "110", "101"],
    "L": ["100", "100", "100", "100", "111"], "M": ["101", "111", "111", "101", "101"],
    "N": ["101", "111", "111", "111", "101"], "O": ["111", "101", "101", "101", "111"],
    "P": ["111", "101", "111", "100", "100"], "R": ["111", "101", "110", "101", "101"],
    "S": ["111", "100", "111", "001", "111"], "T": ["111", "010", "010", "010", "010"],
    "U": ["101", "101", "101", "101", "111"], "Y": ["101", "101", "111", "010", "010"],
    " ": ["000", "000", "000", "000", "000"],
}


def draw_text(px, canvas_w, canvas_h, text: str, x0: int, y0: int, scale: int, color) -> None:
    cx = x0
    for ch in text.upper():
        glyph = FONT3X5.get(ch, FONT3X5[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            x, y = cx + gx * scale + dx, y0 + gy * scale + dy
                            if 0 <= x < canvas_w and 0 <= y < canvas_h:
                                px[y * canvas_w + x] = color
        cx += (3 * scale) + scale  # glyph width + one column of spacing


def gen_favicon_svg() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img" aria-label="SpotiSort">'
        '<rect x="1" y="1" width="30" height="30" rx="9" fill="#1DB954"/>'
        '<path d="M9 20l7-7 7 7" stroke="#000000" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M9 13l7-7 7 7" stroke="#000000" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round" opacity="0.55"/>'
        "</svg>"
    )


def main() -> None:
    (DOCS / "assets" / "favicon.svg").write_text(gen_favicon_svg(), encoding="utf-8", newline="\n")

    for size, name in ((32, "favicon-32.png"), (180, "icon-180.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        write_png(DOCS / "icons" / name, size, size, draw_mark(size))

    # Maskable: keep the mark inside the ~80% "safe zone" Android applies, background fills the rest.
    write_png(DOCS / "icons" / "icon-maskable-512.png", 512, 512, draw_mark(512, margin_frac=0.12))

    # 1200x630 Open Graph / Twitter card: brand background, mark, wordmark + tagline.
    w, h = 1200, 630
    canvas = [(18, 18, 18)] * (w * h)
    mark_size = 220
    mark = draw_mark(mark_size)
    mx, my = 90, (h - mark_size) // 2
    for y in range(mark_size):
        for x in range(mark_size):
            canvas[(my + y) * w + (mx + x)] = mark[y * mark_size + x]
    draw_text(canvas, w, h, "SPOTISORT", 350, 230, 10, WHITE)
    draw_text(canvas, w, h, "SORT YOUR LIKED SONGS AUTOMATICALLY", 350, 340, 4, (179, 179, 179))
    write_png(DOCS / "assets" / "og.png", w, h, canvas)

    print("Generated favicon set + og.png under docs/")


if __name__ == "__main__":
    main()
