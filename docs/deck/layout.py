"""Measurement-driven text placement.

Inter metrics come from the real TTF files, so we can wrap text ourselves and
emit one PowerPoint paragraph per line. That way PowerPoint, LibreOffice and
Keynote all break the lines in exactly the same place — no surprise re-wrap,
no clipped headlines.
"""

from __future__ import annotations

from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from deckkit import FONT, textbox, para, _set_weight, wrap, line_height_in

# build-time log of anything that could not fit its box
OVERFLOW: list[str] = []


def lines_box(slide, x, y, w, lines, size, color, weight=400, align=PP_ALIGN.LEFT,
              spacing=1.16, tag=""):
    """One paragraph per line. Returns the used height in EMU."""
    lh = line_height_in(size, spacing)
    h = Inches(lh * len(lines) + 0.02)
    _, tf = textbox(slide, x, y, w, h)
    for i, ln in enumerate(lines):
        para(tf, ln, size, color, weight, align=align, first=(i == 0), line_spacing=spacing)
    _check(lines, size, w, weight, tag)
    return Emu(int(h))


def text_block(slide, x, y, w, text, size, color, weight=400, align=PP_ALIGN.LEFT,
               spacing=1.16, tag=""):
    """Wrap `text` to width `w` and emit it. Returns the used height in EMU."""
    lines = wrap(text, size, w / 914400, weight)
    return lines_box(slide, x, y, w, lines, size, color, weight, align, spacing, tag)


def _check(lines, size, w, weight, tag):
    for ln in lines:
        from deckkit import text_width_pt
        need = text_width_pt(ln, size, weight) / 72.0
        avail = w / 914400
        if need > avail + 0.005:
            OVERFLOW.append(f"{tag or '?'}: {need:.2f}in > {avail:.2f}in :: {ln[:60]}")
