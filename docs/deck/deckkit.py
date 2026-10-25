"""Small layout kit for the Aéza defence deck.

Everything is native PowerPoint: text boxes, autoshapes, pictures, tables.
No slide is a flattened image.
"""

from __future__ import annotations

import copy
from pathlib import Path

from PIL import Image, ImageFont
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt


INK = RGBColor(0x13, 0x13, 0x13)
INK_2 = RGBColor(0x1F, 0x1F, 0x1F)
PAPER = RGBColor(0xF4, 0xF4, 0xF4)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
TEXT = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x66, 0x66, 0x66)
DIM = RGBColor(0x8E, 0x8E, 0x8E)
CORAL = RGBColor(0xFF, 0x6B, 0x00)
CORAL_DEEP = RGBColor(0xB8, 0x4A, 0x00)
MINT = RGBColor(0x83, 0xCD, 0xB7)
LINE = RGBColor(0xE1, 0xE1, 0xE1)
LINE_DARK = RGBColor(0x33, 0x33, 0x33)

FONT = "Manrope"
FONT_DISPLAY = "Manrope"


SW = Inches(13.333)
SH = Inches(7.5)
M = Inches(0.72)
CONTENT_W = SW - 2 * M


_FONT_CACHE: dict[tuple[int, int], ImageFont.FreeTypeFont] = {}


_FONT_DIRS = [
    Path(__file__).resolve().parent / "fonts",
    Path.home() / ".local/share/fonts/manrope",
]
_FONT_FILES = {
    400: "Manrope-Regular.ttf",
    500: "Manrope-Medium.ttf",
    600: "Manrope-SemiBold.ttf",
    700: "Manrope-Bold.ttf",
    800: "Manrope-ExtraBold.ttf",
}


def _font_path(weight: int) -> Path:
    name = _FONT_FILES.get(weight, _FONT_FILES[400])
    for d in _FONT_DIRS:
        if (d / name).exists():
            return d / name
    raise FileNotFoundError(
        f"Manrope not found: expected {name} in {_FONT_DIRS[0]}. "
        "Run the build from a checkout of this repository."
    )


def _pil_font(pt: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    key = (round(pt), weight)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(str(_font_path(weight)),
                                              max(4, int(round(pt) * 4)))
    return _FONT_CACHE[key]


def text_width_pt(text: str, pt: float, weight: int = 400) -> float:
    """Width of a single line in points."""
    f = _pil_font(round(pt), weight)
    return f.getlength(text) / 4.0


def wrap(text: str, pt: float, max_in: float, weight: int = 400) -> list[str]:
    """Greedy wrap using real Manrope metrics; max_in is the box width in inches."""
    max_pt = max_in * 72.0
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            if text_width_pt(cur + " " + w, pt, weight) <= max_pt:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def line_height_in(pt: float, spacing: float = 1.16) -> float:
    return pt * spacing / 72.0


def solid(shape, color: RGBColor) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = color


def noline(shape) -> None:
    shape.line.fill.background()


def no_shadow(shape) -> None:
    sp = shape._element.spPr
    for tag in ("a:effectLst",):
        for el in sp.findall(qn(tag)):
            sp.remove(el)
    sp.append(copy.deepcopy(sp.makeelement(qn("a:effectLst"), {})))


def rect(slide, x, y, w, h, fill=None, line=None, line_w=0.75, shape=MSO_SHAPE.RECTANGLE):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    if fill is None:
        s.fill.background()
    else:
        solid(s, fill)
    if line is None:
        noline(s)
    else:
        s.line.color.rgb = line
        s.line.width = Pt(line_w)
    no_shadow(s)
    s.shadow.inherit = False
    return s


def textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP, wrap_text=True):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = wrap_text
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    return tb, tf


def para(tf, text, size, color, weight=400, align=PP_ALIGN.LEFT, space_before=0,
         space_after=0, line_spacing=1.16, first=False, italic=False, spacing_pt=None):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_before = Pt(space_before)
    p.space_after = Pt(space_after)
    p.line_spacing = line_spacing
    run = p.add_run()
    run.text = text
    f = run.font
    f.name = FONT
    f.size = Pt(size)
    f.bold = weight >= 600
    f.italic = italic
    f.color.rgb = color
    if spacing_pt is not None:
        run.font._rPr.set("spc", str(int(spacing_pt * 100)))
    _set_weight(run, weight)
    return p


def _set_weight(run, weight: int) -> None:
    """Inter has real weights; ask for them via the typeface name when needed."""
    name = {
        300: "Manrope",
        400: "Manrope",
        500: "Manrope Medium",
        600: "Manrope SemiBold",
        700: "Manrope",
        800: "Manrope ExtraBold",
    }.get(weight, "Manrope")
    run.font.name = name
    rPr = run.font._rPr
    for tag in ("a:latin", "a:cs", "a:ea"):
        for el in rPr.findall(qn(tag)):
            rPr.remove(el)
    for tag in ("a:latin", "a:cs", "a:ea"):
        el = rPr.makeelement(qn(tag), {"typeface": name})
        rPr.append(el)


def weight_from_run(run) -> int:
    """Inverse of _set_weight: recover the intended weight from a run."""
    name = run.font.name or "Manrope"
    for w, nm in ((800, "Manrope ExtraBold"), (600, "Manrope SemiBold"),
                  (500, "Manrope Medium")):
        if name == nm:
            return w
    return 700 if run.font.bold else 400


def runs(tf, segments, size, align=PP_ALIGN.LEFT, line_spacing=1.16, first=False,
         space_before=0, space_after=0):
    """segments: list of (text, color, weight) tuples rendered in one paragraph."""
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.line_spacing = line_spacing
    p.space_before = Pt(space_before)
    p.space_after = Pt(space_after)
    for text, color, weight in segments:
        r = p.add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.color.rgb = color
        r.font.bold = weight >= 600
        _set_weight(r, weight)
    return p


def picture(slide, path, x, y, w=None, h=None):
    """Insert a picture, preserving aspect ratio if only one dimension is given."""
    iw, ih = Image.open(path).size
    ar = iw / ih
    if w is not None and h is None:
        h = Emu(int(w / ar))
    elif h is not None and w is None:
        w = Emu(int(h * ar))
    return slide.shapes.add_picture(str(path), x, y, w, h)


def picture_fit(slide, path, box_x, box_y, box_w, box_h, align="left", valign="top"):
    """Fit a picture inside a box, preserving aspect ratio."""
    iw, ih = Image.open(path).size
    ar = iw / ih
    bw, bh = box_w, box_h
    w, h = bw, Emu(int(bw / ar))
    if h > bh:
        h, w = bh, Emu(int(bh * ar))
    if align == "center":
        x = Emu(int(box_x + (bw - w) / 2))
    elif align == "right":
        x = Emu(int(box_x + bw - w))
    else:
        x = box_x
    if valign == "middle":
        y = Emu(int(box_y + (bh - h) / 2))
    elif valign == "bottom":
        y = Emu(int(box_y + bh - h))
    else:
        y = box_y
    return slide.shapes.add_picture(str(path), Emu(int(x)), Emu(int(y)), Emu(int(w)), Emu(int(h)))


def hairline(slide, x, y, w, color=LINE, weight=0.75):
    ln = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, Pt(weight))
    solid(ln, color)
    noline(ln)
    no_shadow(ln)
    return ln


def notes(slide, text: str) -> None:
    slide.notes_slide.notes_text_frame.text = text


def bg(slide, color: RGBColor) -> None:
    rect(slide, 0, 0, SW, SH, fill=color)


def badge(slide, x, y, w, h, label, fill, text_color=WHITE, size=11, weight=600):
    s = rect(slide, x, y, w, h, fill=fill, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    s.adjustments[0] = 0.32
    tf = s.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    para(tf, label, size, text_color, weight, align=PP_ALIGN.CENTER, first=True)
    return s


def placeholder(slide, x, y, w, h, label, sub="ЗАПОЛНИТЬ ПЕРЕД ЗАЩИТОЙ",
                text_color=MUTED, line_color=None, fill=None, size=11):
    """Neutral outlined box marking a value the team must fill in."""
    line_color = line_color or RGBColor(0xC2, 0xC9, 0xD0)
    box = rect(slide, x, y, w, h, fill=fill, line=line_color, line_w=0.9)
    box.line.dash_style = 4
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.06)
    tf.margin_right = Inches(0.06)
    tf.margin_top = 0
    tf.margin_bottom = 0
    para(tf, label, size, text_color, 500, align=PP_ALIGN.CENTER, first=True)
    if sub:
        para(tf, sub, 7.5, MUTED, 400, align=PP_ALIGN.CENTER, space_before=2, line_spacing=1.0)
    return box


def qr_slot(slide, x, y, size, caption, caption_color=MUTED, box_fill=WHITE,
            line_color=None):
    """Square placeholder for a QR code. Never a fake pattern."""
    line_color = line_color or RGBColor(0xC2, 0xC9, 0xD0)
    box = rect(slide, x, y, size, size, fill=box_fill, line=line_color, line_w=1.0)
    box.line.dash_style = 4
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.05)
    tf.margin_right = Inches(0.05)
    para(tf, "[ВСТАВИТЬ QR]", 9.5, MUTED, 600, align=PP_ALIGN.CENTER, first=True, line_spacing=1.0)
    cap, cf = textbox(slide, x - Inches(0.1), y + size + Inches(0.06),
                      size + Inches(0.2), Inches(0.3))
    para(cf, caption, 8.5, caption_color, 600, align=PP_ALIGN.CENTER, first=True, line_spacing=1.0)
    return box


def numbered_marker(slide, cx, cy, n, size=Inches(0.30), fill=CORAL):
    s = rect(slide, Emu(int(cx - size / 2)), Emu(int(cy - size / 2)), size, size,
             fill=fill, shape=MSO_SHAPE.OVAL)
    tf = s.text_frame
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = 0
    tf.margin_right = 0
    para(tf, str(n), 11, WHITE, 700, align=PP_ALIGN.CENTER, first=True)
    return s
