"""Favicon regression tests.

The app had no legible favicon, and it was not because the file was missing: the
artwork was near-white on transparency, so it vanished against light browser
chrome. These tests read the real assets and fail if that regresses, or if the
icon stops being derived from the approved brand glyph.

The browser check (that the assets decode and the glyph is legible over both
light and dark chrome) lives in the production acceptance audit; these are cheap
and need no browser.
"""

from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "frontend" / "public"
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


BRAND_GLYPH_PREFIX = "M17.281 28.092"


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", data[16:24])


def _ico_sizes(path: Path) -> list[tuple[int, int]]:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), f"{path.name} is not a valid ICO"
    sizes = []
    for index in range(count):
        offset = 6 + index * 16
        width, height = struct.unpack("<BB", data[offset:offset + 2])
        sizes.append((width or 256, height or 256))
    return sizes


def test_index_links_an_adaptive_svg_icon():
    assert 'rel="icon"' in INDEX
    assert 'type="image/svg+xml"' in INDEX, "the colour-scheme-aware icon is not linked"
    assert "/favicon.svg" in INDEX


def test_svg_carries_both_monochrome_variants():
    """The brand book defines the app icon as é, white on black and black on white."""

    svg = (PUBLIC / "favicon.svg").read_text(encoding="utf-8")
    assert BRAND_GLYPH_PREFIX in svg, "the approved brand glyph was replaced"
    assert "prefers-color-scheme" in svg, "the icon no longer adapts to the colour scheme"
    assert "#000000" in svg and "#ffffff" in svg, "both monochrome variants are required"


def test_favicon_png_is_square_and_large_enough():
    width, height = _png_size(PUBLIC / "favicon.png")
    assert width == height >= 128, f"favicon.png is {width}x{height}"


def test_favicon_ico_contains_the_sizes_browsers_ask_for():
    sizes = _ico_sizes(PUBLIC / "favicon.ico")
    for needed in (16, 32, 48):
        assert (needed, needed) in sizes, f"favicon.ico is missing {needed}x{needed}"

    assert len(sizes) > 1, "favicon.ico collapsed to a single frame"


def test_apple_touch_icon_is_square():
    width, height = _png_size(PUBLIC / "apple-touch-icon.png")
    assert width == height, f"apple-touch-icon.png is {width}x{height}"


def test_icon_is_drawn_on_an_opaque_tile():
    """A transparent icon disappears against one of the two browser chromes.

    The original asset was white-on-transparent; this asserts the mark sits on a
    real tile instead. Parsed without Pillow, which CI does not install.
    """

    import zlib

    data = (PUBLIC / "favicon.png").read_bytes()
    width, height, depth, colour_type, _, _, _ = struct.unpack(">IIBBBBB", data[16:29])
    assert colour_type == 6 and depth == 8, "expected an 8-bit RGBA PNG"


    offset, chunks = 8, b""
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        kind = data[offset + 4:offset + 8]
        if kind == b"IDAT":
            chunks += data[offset + 8:offset + 8 + length]
        offset += 12 + length
    raw = zlib.decompress(chunks)

    stride = width * 4
    rows = []
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        line = bytearray(raw[position + 1:position + 1 + stride])
        position += 1 + stride

        for index in range(stride):
            left = line[index - 4] if index >= 4 else 0
            up = previous[index]
            up_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 1:
                line[index] = (line[index] + left) & 0xFF
            elif filter_type == 2:
                line[index] = (line[index] + up) & 0xFF
            elif filter_type == 3:
                line[index] = (line[index] + (left + up) // 2) & 0xFF
            elif filter_type == 4:
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                predictor = left if (pa <= pb and pa <= pc) else (up if pb <= pc else up_left)
                line[index] = (line[index] + predictor) & 0xFF
        rows.append(bytes(line))
        previous = line

    def pixel(x, y):
        row = rows[y]
        return row[x * 4], row[x * 4 + 1], row[x * 4 + 2], row[x * 4 + 3]

    def luminance(p):
        return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]


    edges = [pixel(width // 2, 4), pixel(width // 2, height - 5),
             pixel(4, height // 2), pixel(width - 5, height // 2)]
    assert all(p[3] > 200 for p in edges), "the icon has no opaque tile; it will vanish on some chrome"
    assert sum(luminance(p) for p in edges) / len(edges) > 200, (
        "the tile is not light, so a dark glyph would not read on it"
    )


    centre = pixel(width // 2, int(height * 0.72))
    assert centre[3] > 200, "the glyph pixel is transparent"
    assert luminance(centre) < 100, "the glyph is not dark against the light tile"
