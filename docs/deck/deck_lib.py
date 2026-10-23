"""Shared design primitives for the Aéza Analyzer hackathon deck.

Aéza - это быстрый хостинг

The deck is drawn from scratch on blank layouts: no PowerPoint template, no
placeholder shapes.  Everything here is a thin, explicit wrapper over
python-pptx so the generator stays readable and the output stays editable.
"""

from __future__ import annotations

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt
from PIL import Image

# ---------------------------------------------------------------- palette ---
DARK = RGBColor(0x14, 0x22, 0x38)
DARK_2 = RGBColor(0x20, 0x2F, 0x45)
WARM = RGBColor(0xF7, 0xF6, 0xF2)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x20, 0x2B, 0x3A)
MUTED = RGBColor(0x6B, 0x74, 0x80)
CORAL = RGBColor(0xEF, 0x63, 0x4D)
MINT = RGBColor(0x83, 0xCD, 0xB7)
LINE = RGBColor(0xD9, 0xDE, 0xE2)

# On dark backgrounds these two stand in for INK / MUTED.
INK_ON_DARK = RGBColor(0xE8, 0xEC, 0xF1)
MUTED_ON_DARK = RGBColor(0x9A, 0xA7, 0xB8)
LINE_ON_DARK = RGBColor(0x33, 0x44, 0x5E)

FONT = "Inter"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
MARGIN = Inches(0.85)
CONTENT_W = SLIDE_W - 2 * MARGIN


# ------------------------------------------------------------- primitives ---
def _force_typeface(run, name: str) -> None:
    """Set latin/ea/cs typefaces so Cyrillic never falls back to a default."""

    from pptx.oxml.ns import qn

    rPr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", name)


def rect(slide, x, y, w, h, fill=None, line=None, line_w=Pt(0.75), shape=MSO_SHAPE.RECTANGLE):
    shp = slide.shapes.add_shape(shape, x, y, w, h)
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = line_w
    shp.shadow.inherit = False
    if shp.has_text_frame:
        shp.text_frame.text = ""
    return shp


def line_h(slide, x, y, w, color=LINE, weight=Pt(0.75)):
    """A hairline rule, drawn as a zero-height rectangle outline-free."""

    shp = slide.shapes.add_connector(1, x, y, x + w, y)
    shp.line.color.rgb = color
    shp.line.width = weight
    return shp


def line_v(slide, x, y, h, color=LINE, weight=Pt(0.75)):
    shp = slide.shapes.add_connector(1, x, y, x, y + h)
    shp.line.color.rgb = color
    shp.line.width = weight
    return shp


def textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    return tb, tf


def para(tf, text, size, color, bold=False, first=False, align=PP_ALIGN.LEFT,
         space_before=0, space_after=0, line_spacing=None, italic=False, font=FONT):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    if space_before:
        p.space_before = Pt(space_before)
    if space_after:
        p.space_after = Pt(space_after)
    if line_spacing:
        p.line_spacing = line_spacing
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.italic = italic
    run.font.name = font
    _force_typeface(run, font)
    return p


def rich(tf, parts, size, color, first=False, align=PP_ALIGN.LEFT,
         space_before=0, space_after=0, line_spacing=None):
    """One paragraph built from (text, bold, color_override, size_override) tuples."""

    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    if space_before:
        p.space_before = Pt(space_before)
    if space_after:
        p.space_after = Pt(space_after)
    if line_spacing:
        p.line_spacing = line_spacing
    for item in parts:
        txt, bold = item[0], item[1]
        col = item[2] if len(item) > 2 and item[2] is not None else color
        sz = item[3] if len(item) > 3 and item[3] is not None else size
        run = p.add_run()
        run.text = txt
        run.font.size = Pt(sz)
        run.font.color.rgb = col
        run.font.bold = bold
        run.font.name = FONT
        _force_typeface(run, FONT)
    return p


def kicker(slide, text, x=MARGIN, y=Inches(0.62), color=CORAL):
    """Small uppercase section label with a short coral tick above it."""

    rect(slide, x, y - Inches(0.16), Inches(0.34), Pt(3), fill=color)
    tb, tf = textbox(slide, x, y, Inches(6), Inches(0.3))
    para(tf, text.upper(), 11.5, color, bold=True, first=True)
    return tb


def slide_title(slide, text, x=MARGIN, y=Inches(1.0), w=None, size=34,
                color=INK, line_spacing=1.06):
    w = w or Inches(11.0)
    tb, tf = textbox(slide, x, y, w, Inches(1.4))
    para(tf, text, size, color, bold=True, first=True, line_spacing=line_spacing)
    return tb


def footer(slide, left_text, right_text, color=MUTED, y=Inches(6.92)):
    line_h(slide, MARGIN, y - Inches(0.16), CONTENT_W, color=LINE)
    tb, tf = textbox(slide, MARGIN, y, Inches(7.5), Inches(0.3))
    para(tf, left_text, 11, color, first=True)
    tb2, tf2 = textbox(slide, SLIDE_W - MARGIN - Inches(4.0), y, Inches(4.0), Inches(0.3))
    para(tf2, right_text, 11, color, first=True, align=PP_ALIGN.RIGHT)


# -------------------------------------------------------------- pictures ---
def add_picture_contain(slide, path, x, y, w, h, border=True, bg=WHITE, border_color=LINE):
    """Fit the whole image inside the box, centred, preserving aspect ratio."""

    iw, ih = Image.open(path).size
    scale = min(w / iw, h / ih)
    tw, th = int(iw * scale), int(ih * scale)
    left = x + int((w - tw) / 2)
    top = y + int((h - th) / 2)
    if border:
        rect(slide, left - Emu(1), top - Emu(1), tw + Emu(2), th + Emu(2),
             fill=bg, line=border_color, line_w=Pt(0.75))
    pic = slide.shapes.add_picture(path, left, top, tw, th)
    return pic, (left, top, tw, th)


def add_picture_cover(slide, path, x, y, w, h, focus=(0.5, 0.0)):
    """Fill the box by pre-cropping the image with PIL, then placing it flat.

    Cropping is done on disk rather than with ``crop_left`` offsets so nothing
    can spill outside the intended frame.
    """

    cropped = crop_to_aspect(path, w / h, focus)
    return slide.shapes.add_picture(cropped, x, y, w, h)


def crop_to_aspect(path, target_ratio, focus=(0.5, 0.0)):
    """Return a temp file holding ``path`` cropped to ``target_ratio`` (w/h)."""

    import os
    import tempfile

    im = Image.open(path).convert("RGB")
    iw, ih = im.size
    src_ratio = iw / ih
    if src_ratio > target_ratio:
        new_w = max(1, int(round(ih * target_ratio)))
        left = int((iw - new_w) * focus[0])
        box = (left, 0, left + new_w, ih)
    else:
        new_h = max(1, int(round(iw / target_ratio)))
        top = int((ih - new_h) * focus[1])
        box = (0, top, iw, top + new_h)
    out = os.path.join(tempfile.mkdtemp(prefix="deck_crop_"), "crop.png")
    im.crop(box).save(out)
    return out


# ------------------------------------------------------------ background ---
def background(slide, prs, color):
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = color
    bg.line.fill.background()
    bg.shadow.inherit = False
    return bg
